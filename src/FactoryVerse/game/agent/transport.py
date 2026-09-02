"""Belt topology derived from event-backed geometry — never stored.

TRANSPORT_CONNECTIVITY_PLAN.md §2–§5: a belt component (heads, tails, merge
points, member belts) is a pure function of ``(entity_name, position,
direction, belt_to_ground_type)`` — four columns that change only when an
entity is placed, removed or rotated, which is the event the map model has a
contract with. So the component is computed at read time from ``map_entity``
joined to ``transport_belt`` and is fresh by construction; a stored component
would need every neighbour's row rewritten on each placement, and the Lua
serializer re-serializes only the placed entity.

Belt rules encoded here (Factorio 2.0):

- A belt on tile ``t`` facing ``d`` feeds the tile ``t + unit(d)``.
- A belt accepts from behind and from either side (a side-load). It does not
  accept from the belt it faces when that belt faces back at it — two belts
  pointing at each other are not connected.
- An underground entrance (``belt_to_ground_type = "input"``) feeds its exit:
  the nearest exit of the same prototype facing the same way along ``d``,
  within the prototype's ``max_distance`` counted **centre to centre** (5 for
  underground-belt → four tiles of gap). An exit feeds the tile in front.
  Undergrounds accept only from behind (entrance) or from their pair (exit);
  side-loading onto an underground's open lane is not modelled.
- A splitter is two tiles wide (its tiles come from ``footprint_tiles``); it
  accepts from behind on either tile and feeds the tile in front of each.
- Loaders are treated as belts with a direction.

What is deliberately not here (§3): no throughput, no bottleneck — the read
tells the agent what it would see, never what it would conclude.

The result is a read, not a noun the agent holds (§4): a ``BeltLine`` value
named ``line``/``lines`` that is recomputed on every call.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

Key = Tuple[str, float, float]
Tile = Tuple[int, int]

# defines.direction in 2.0 is 16-valued; belts use the four cardinals.
_UNIT: Dict[int, Tuple[int, int]] = {0: (0, -1), 4: (1, 0), 8: (0, 1), 12: (-1, 0)}
_DIRECTION_NAMES = {0: "north", 4: "east", 8: "south", 12: "west"}
_DEFAULT_UNDERGROUND_MAX_DISTANCE = {
    "underground-belt": 5,
    "fast-underground-belt": 7,
    "express-underground-belt": 9,
}


def _direction_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, str):
        names = {"north": 0, "east": 4, "south": 8, "west": 12}
        if value.lower() in names:
            return names[value.lower()]
        try:
            value = int(float(value))
        except ValueError:
            return None
    try:
        d = int(value) % 16
    except (TypeError, ValueError):
        return None
    # snap diagonals to the nearest cardinal — belts never face them
    return (round(d / 4) * 4) % 16


def _opposite(d: int) -> int:
    return (d + 8) % 16


def _tile_of(x: float, y: float) -> Tile:
    import math

    return (int(math.floor(x)), int(math.floor(y)))


@dataclass(frozen=True)
class BeltRow:
    """One row of event-backed belt geometry."""

    name: str
    x: float
    y: float
    direction: int
    kind: str  # belt | underground | splitter | loader
    belt_to_ground_type: Optional[str] = None  # input | output for undergrounds
    tiles: Tuple[Tile, ...] = ()  # occupied tiles (splitters are 2-wide)

    @property
    def key(self) -> Key:
        return (self.name, self.x, self.y)

    @property
    def tile(self) -> Tile:
        return self.tiles[0] if self.tiles else _tile_of(self.x, self.y)


@dataclass
class BeltLine:
    """A connected belt component, computed at read time.

    ``heads`` are fed by nothing, ``tails`` feed nothing, ``merges`` are fed by
    more than one belt (a side-load: two sources, one belt). A component with
    two heads and one merge is what a person calls "two lines joining".
    """

    belts: List[Key]
    heads: List[Key]
    tails: List[Key]
    merges: List[Key]
    source: str
    # feeder → fed, restricted to this component, for callers that want the graph
    edges: List[Tuple[Key, Key]] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.belts)

    def contains(self, key: Key) -> bool:
        return key in set(self.belts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "count": self.count,
            "heads": [list(k) for k in self.heads],
            "tails": [list(k) for k in self.tails],
            "merges": [list(k) for k in self.merges],
            "source": self.source,
        }


def classify(name: str, prototype_type: Optional[str] = None) -> str:
    """Belt family from the prototype type when known, else from the name."""
    t = (prototype_type or "").lower()
    n = name.lower()
    if t == "underground-belt" or "underground-belt" in n:
        return "underground"
    if t == "splitter" or "splitter" in n:
        return "splitter"
    if t in ("loader", "loader-1x1") or "loader" in n:
        return "loader"
    return "belt"


def underground_max_distance(name: str) -> int:
    """Centre-to-centre reach of an underground pair, from the prototype dump
    when available, else the vanilla constants. ``max_distance`` is the
    UndergroundBeltPrototype field (5/7/9); pipe-to-ground has no such field
    and is not handled here (TRANSPORT §7 owns fluids)."""
    try:
        from FactoryVerse.game.factory.prototypes import get_entity_prototypes

        proto = get_entity_prototypes().get_prototype(name)
        md = proto.get("max_distance") if isinstance(proto, dict) else None
        if md:
            return int(md)
    except Exception:  # noqa: BLE001 — offline or unknown name: fall through
        pass
    return _DEFAULT_UNDERGROUND_MAX_DISTANCE.get(name, 5)


# ---------------------------------------------------------------------------
# rows → graph
# ---------------------------------------------------------------------------


def _outputs(row: BeltRow, by_tile: Dict[Tile, BeltRow], rows_by_name: Dict[str, List[BeltRow]]) -> List[BeltRow]:
    """The belts this row feeds."""
    ux, uy = _UNIT[row.direction]
    if row.kind == "underground" and row.belt_to_ground_type == "input":
        reach = underground_max_distance(row.name)
        tx, ty = row.tile
        for step in range(1, reach + 1):
            cand = by_tile.get((tx + ux * step, ty + uy * step))
            if cand is None:
                continue
            if cand.kind == "underground" and cand.name == row.name and cand.direction == row.direction:
                # the first same-type entrance in the way blocks the pair
                return [cand] if cand.belt_to_ground_type == "output" else []
        return []
    out: List[BeltRow] = []
    for tx, ty in row.tiles or (row.tile,):
        target = by_tile.get((tx + ux, ty + uy))
        if target is None or target.key == row.key:
            continue
        if _accepts(target, row):
            out.append(target)
    return out


def _accepts(target: BeltRow, feeder: BeltRow) -> bool:
    if target.kind == "underground":
        if target.belt_to_ground_type == "output":
            return False  # an exit is fed only by its pair
        return feeder.direction == target.direction  # entrance: from behind only
    if target.kind == "splitter":
        return feeder.direction == target.direction
    # belt / loader: from behind or either side; never head-on
    return feeder.direction != _opposite(target.direction)


def build_edges(rows: Sequence[BeltRow]) -> List[Tuple[Key, Key]]:
    by_tile: Dict[Tile, BeltRow] = {}
    rows_by_name: Dict[str, List[BeltRow]] = defaultdict(list)
    for r in rows:
        rows_by_name[r.name].append(r)
        for t in r.tiles or (r.tile,):
            by_tile[t] = r
    edges: List[Tuple[Key, Key]] = []
    for r in rows:
        for fed in _outputs(r, by_tile, rows_by_name):
            edges.append((r.key, fed.key))
    return edges


def components(rows: Sequence[BeltRow], source: str) -> List[BeltLine]:
    """Weakly connected components of the feed graph, largest first."""
    edges = build_edges(rows)
    fed_by: Dict[Key, List[Key]] = defaultdict(list)
    feeds: Dict[Key, List[Key]] = defaultdict(list)
    for a, b in edges:
        feeds[a].append(b)
        fed_by[b].append(a)
    keys = [r.key for r in rows]
    seen: set = set()
    out: List[BeltLine] = []
    for k in keys:
        if k in seen:
            continue
        comp: List[Key] = []
        q = deque([k])
        seen.add(k)
        while q:
            cur = q.popleft()
            comp.append(cur)
            for nxt in list(feeds.get(cur, [])) + list(fed_by.get(cur, [])):
                if nxt not in seen:
                    seen.add(nxt)
                    q.append(nxt)
        comp_set = set(comp)
        comp_sorted = sorted(comp)
        out.append(
            BeltLine(
                belts=comp_sorted,
                heads=sorted(c for c in comp if not fed_by.get(c)),
                tails=sorted(c for c in comp if not feeds.get(c)),
                merges=sorted(c for c in comp if len(fed_by.get(c, ())) > 1),
                source=source,
                edges=[(a, b) for a, b in edges if a in comp_set],
            )
        )
    out.sort(key=lambda c: (-c.count, c.belts[0] if c.belts else ("", 0, 0)))
    return out


# ---------------------------------------------------------------------------
# database → rows
# ---------------------------------------------------------------------------

_ROWS_SQL = """
SELECT m.entity_name, m.position_x, m.position_y,
       COALESCE(t.direction, m.direction) AS direction,
       t.belt_to_ground_type, t.loader_type,
       m.raw_data
FROM transport_belt t
JOIN map_entity m
  ON m.entity_name = t.entity_name
 AND m.position_x = t.position_x
 AND m.position_y = t.position_y
"""

_TILES_SQL = """
SELECT f.entity_name, f.entity_position_x, f.entity_position_y, f.tile_x, f.tile_y
FROM footprint_tiles f
JOIN transport_belt t
  ON t.entity_name = f.entity_name
 AND t.position_x = f.entity_position_x
 AND t.position_y = f.entity_position_y
"""


def rows_from_connection(connection) -> List[BeltRow]:
    """Read the belt geometry the map model holds. Pure read; no writes."""
    import json

    tiles: Dict[Key, List[Tile]] = defaultdict(list)
    try:
        for name, x, y, tx, ty in connection.execute(_TILES_SQL).fetchall():
            tiles[(name, float(x), float(y))].append((int(tx), int(ty)))
    except Exception:  # noqa: BLE001 — footprint_tiles may be absent in a bare DB
        pass
    rows: List[BeltRow] = []
    for name, x, y, direction, b2g, loader_type, raw in connection.execute(_ROWS_SQL).fetchall():
        d = _direction_int(direction)
        if d is None:
            continue
        proto_type = None
        if raw:
            try:
                proto_type = (json.loads(raw) or {}).get("type")
            except Exception:  # noqa: BLE001
                proto_type = None
        key = (name, float(x), float(y))
        row_tiles = tuple(sorted(tiles.get(key) or [_tile_of(float(x), float(y))]))
        rows.append(
            BeltRow(
                name=name,
                x=float(x),
                y=float(y),
                direction=d,
                kind=classify(name, proto_type),
                belt_to_ground_type=b2g,
                tiles=row_tiles,
            )
        )
    return rows


class TransportReads:
    """``remote_view.transport`` — derived structure, computed per call.

    Every method declares its source: ``map_entity:seq<n>`` names the map
    model's last applied sequence, so a reader knows how fresh the geometry
    is. Nothing here touches the engine.
    """

    def __init__(self, connection_getter, source_getter):
        self._conn = connection_getter
        self._source = source_getter

    def _all(self) -> Tuple[List[BeltRow], List[BeltLine]]:
        rows = rows_from_connection(self._conn())
        return rows, components(rows, self._source())

    def lines(self) -> List[BeltLine]:
        """Every belt component in the map model, largest first."""
        return self._all()[1]

    def line(self, ref) -> Optional[BeltLine]:
        """The component containing ``ref`` — an entity object, a
        ``(name, x, y)`` key, or a position ``(x, y)`` / object with ``.x/.y``."""
        key = _key_of(ref)
        rows, comps = self._all()
        if key is None:
            return None
        if key[0] is None:  # position only: find the belt on that tile
            tile = _tile_of(key[1], key[2])
            for r in rows:
                if tile in (r.tiles or (r.tile,)):
                    key = r.key
                    break
            else:
                return None
        for c in comps:
            if key in set(c.belts):
                return c
        return None

    def shares_line_with(self, a, b) -> bool:
        """Whether two belts are in one component (derived; a live cross-check
        is ``belt.contents`` on both ends once TRANSPORT §5 lands)."""
        la = self.line(a)
        return la is not None and la.contains(_resolve_key(la, b))


def _key_of(ref) -> Optional[Tuple[Optional[str], float, float]]:
    if ref is None:
        return None
    if isinstance(ref, tuple) and len(ref) == 3:
        return (ref[0], float(ref[1]), float(ref[2]))
    if isinstance(ref, tuple) and len(ref) == 2:
        return (None, float(ref[0]), float(ref[1]))
    name = getattr(ref, "name", None)
    pos = getattr(ref, "position", None)
    if pos is not None and hasattr(pos, "x"):
        return (name, float(pos.x), float(pos.y))
    if hasattr(ref, "x") and hasattr(ref, "y"):
        return (None, float(ref.x), float(ref.y))
    return None


def _resolve_key(line: BeltLine, ref) -> Key:
    k = _key_of(ref)
    if k is None:
        return ("", 0.0, 0.0)
    if k[0] is not None:
        return (k[0], k[1], k[2])
    tile = _tile_of(k[1], k[2])
    for b in line.belts:
        if _tile_of(b[1], b[2]) == tile:
            return b
    return ("", 0.0, 0.0)
