"""VerifyView - the live confirmation half of the agent's power/coverage UX.

The DuckDB snapshot answers *which* poles / entities exist; VerifyView answers
*is it true right now* by reading the live engine. Its centrepiece is
``supply_coverage``: a one-call, visually legible check of whether every
electric consumer's collision box actually intersects a pole's supply area —
the exact geometry that silently defeated the terra-pro attempt-5 run, where a
mining drill sat 0.15 tiles short of a medium-pole spine and the agent could
neither preview nor diagnose the miss.

Freshness contract (honest by construction):
  * Positions, statuses, and ``electric_network_id`` are LIVE engine reads at
    call time (raw ``/sc`` Lua over the existing RCON route — no snapshot lag).
  * Supply-area distances and entity collision boxes are PROTOTYPE-derived
    (the offline ``factorio-data-dump.json`` pipeline, same source
    ``ElectricPole.supply_area_distance`` / ``_pole_prototype_distances`` use).
    They do not change at runtime, so mixing a live position with a prototype
    box is sound.

Why raw Lua and not the typed inspection path: ``supply_coverage`` and
``powered`` need a *batched* multi-position read (poles in an area + N target
statuses + network ids) in a single tick. The typed ``entity_ops.inspect_entity``
route is one-entity-per-roundtrip and returns a heavier payload; a single
xpcall'd Lua loop (the established ``check_L1_14`` / ``PlacementHintsClient``
pattern) is one roundtrip for the whole candidate set, which is small by design.

No mod changes: this module is pure Python over existing RCON — no new remote
interface method, no server restart.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union, TYPE_CHECKING

from FactoryVerse.game.agent.placement_hints import (
    ELECTRIC_POLE_ENTITIES,
    _pole_prototype_distances,
)
from FactoryVerse.game.factory.prototypes import get_entity_prototypes

if TYPE_CHECKING:
    from FactoryVerse.game.agent.infra.rcon_handler import RconHandler

logger = logging.getLogger(__name__)

# A (name, position) target may be given as a tuple, or as a dict carrying an
# entity_name/name and a position/{x,y}. Positions accept MapPosition, {'x','y'}
# dicts, or (x, y) tuples.
Target = Union[Tuple[str, Any], Dict[str, Any]]

# Glyphs for the ascii_map. First letter is a sensible fallback; these override
# it so a scene reads at a glance. Uppercase == covered, lowercase == NOT
# covered (applied by the renderer).
_ENTITY_GLYPHS = {
    "electric-mining-drill": "d",
    "burner-mining-drill": "d",
    "pumpjack": "j",
    "electric-furnace": "f",
    "stone-furnace": "f",
    "steel-furnace": "f",
    "assembling-machine-1": "a",
    "assembling-machine-2": "a",
    "assembling-machine-3": "a",
    "electric-energy-interface": "e",
}


# =============================================================================
# Typed results (freshness contract lives in each docstring)
# =============================================================================


@dataclass
class PoweredCheck:
    """Live power status of one entity, read from the engine at call time.

    ``powered`` is defined as ``electric_network_id is not None AND status_name
    not in ('no_power',)`` — i.e. the entity is attached to an electric network
    and Factorio is not reporting it as unpowered. Note a fuel-starved *producer*
    still reports 'working' and a low_power condition can hide behind a logistics
    status (Factorio has one status slot per entity); for network-level truth use
    ``remote_view.get_power_networks`` / ``diagnose_power``.

    All fields are LIVE (engine read at call time). ``found`` is False when no
    entity of ``entity_name`` exists within 0.6 tiles of ``position`` — the
    remaining fields are then their defaults.
    """

    entity_name: str
    position: Dict[str, float]
    found: bool
    powered: bool = False
    status_name: Optional[str] = None
    electric_network_id: Optional[int] = None


@dataclass
class ConnectedCheck:
    """Whether two entities share one live electric network.

    ``connected`` is True iff both entities are found and have the same non-nil
    ``electric_network_id`` at call time. Network ids are ephemeral (they
    renumber on merge/split), so this is a right-now fact, not a durable id.
    """

    a_name: str
    a_position: Dict[str, float]
    b_name: str
    b_position: Dict[str, float]
    connected: bool
    a_found: bool
    b_found: bool
    a_network_id: Optional[int]
    b_network_id: Optional[int]
    explanation: str


@dataclass
class EntityCoverage:
    """Coverage verdict for one electric consumer against the pole set.

    Geometry is prototype-derived (supply distance, collision box); the pole and
    entity *positions* it is computed from are live. ``covered`` is True iff the
    entity's collision box intersects at least one pole's supply box (the engine
    rule). ``margin`` is a single honest number:
      * covered  -> the smallest overlap depth (tiles you could shift the entity
        before it falls out of coverage);
      * NOT covered -> the shortest distance needed to become covered, with the
        axis in ``margin_axis`` ('X', 'Y', or 'XY' when separated on both).
    ``by_pole_name``/``by_pole_position`` name the covering pole (when covered)
    or the nearest pole that would cover it with the least move (when not).
    ``detail`` is a human sentence, e.g. "0.15 short on Y toward y=64.5 pole line".
    """

    entity_name: str
    position: Dict[str, float]
    covered: bool
    margin: float
    margin_axis: str
    by_pole_name: Optional[str]
    by_pole_position: Optional[Dict[str, float]]
    detail: str


@dataclass
class SupplyCoverageReport:
    """Coverage of an entity set by a pole set, with a tile-aligned ascii map.

    Positions are LIVE engine reads; supply distances and collision boxes are
    prototype-derived (see module docstring). ``poles`` lists every pole
    considered (live ones plus an optional as-if-placed ``proposed_pole``, marked
    ``is_proposed``). ``ascii_map`` renders a bounded tile window: '#' = tile
    inside some pole's (tile-aligned) supply area, '.' = uncovered ground,
    'P' = pole, '?' = proposed pole, a letter for each entity (UPPERCASE covered,
    lowercase NOT). ``summary`` names the uncovered entities and their margins.
    """

    entities: List[EntityCoverage]
    poles: List[Dict[str, Any]]
    covered_count: int
    total_count: int
    summary: str
    ascii_map: str
    freshness_note: str


_FRESHNESS = (
    "positions/statuses/network-ids are LIVE engine reads at call time; "
    "supply distances and collision boxes are prototype-derived (static)"
)


# =============================================================================
# Pure geometry (no RCON — unit-tested directly against the prototype dump)
# =============================================================================

Rect = Tuple[float, float, float, float]  # (min_x, min_y, max_x, max_y)


def _collision_box(prototypes, name: str, x: float, y: float) -> Rect:
    """Absolute collision box of ``name`` centred at (x, y), from the dump.

    The prototype ``collision_box`` is ``[[x1,y1],[x2,y2]]`` relative to the
    entity centre; add the position to get world coordinates. Falls back to a
    unit box if the prototype has no collision_box (loud-ish: still usable).
    """
    proto = prototypes.get_prototype(name)
    cb = proto.get("collision_box") if proto else None
    if not cb:
        return (x - 0.5, y - 0.5, x + 0.5, y + 0.5)
    (x1, y1), (x2, y2) = cb[0], cb[1]
    return (x + x1, y + y1, x + x2, y + y2)


def _supply_box(px: float, py: float, supply: float) -> Rect:
    """Continuous supply box of a pole: centre ± supply_area_distance."""
    return (px - supply, py - supply, px + supply, py + supply)


def _overlap(a: Rect, b: Rect) -> Tuple[float, float]:
    """Signed overlap depths (ox, oy). Positive == overlapping on that axis,
    negative == a gap of that magnitude."""
    ox = min(a[2], b[2]) - max(a[0], b[0])
    oy = min(a[3], b[3]) - max(a[1], b[1])
    return ox, oy


def _coverage_for_entity(
    entity_box: Rect,
    entity_center: Tuple[float, float],
    poles: List[Dict[str, Any]],
) -> Tuple[bool, float, str, Optional[Dict[str, Any]], str]:
    """Compute (covered, margin, margin_axis, by_pole, detail) for one entity.

    ``poles`` is a list of resolved pole dicts each with keys name, x, y, supply.
    Deterministic: poles are consumed in the (already sorted) order given.
    """
    ex, ey = entity_center
    best_cov: Optional[Tuple[float, Dict[str, Any]]] = None   # (depth, pole)
    best_gap: Optional[Tuple[float, float, float, Dict[str, Any]]] = None
    # (gap_dist, gap_x, gap_y, pole)

    for pole in poles:
        sbox = _supply_box(pole["x"], pole["y"], pole["supply"])
        ox, oy = _overlap(entity_box, sbox)
        if ox > 0 and oy > 0:
            depth = min(ox, oy)
            if best_cov is None or depth > best_cov[0]:
                best_cov = (depth, pole)
        else:
            gx = max(0.0, -ox)
            gy = max(0.0, -oy)
            gap = math.hypot(gx, gy)
            if best_gap is None or gap < best_gap[0]:
                best_gap = (gap, gx, gy, pole)

    if best_cov is not None:
        depth, pole = best_cov
        return (
            True,
            round(depth, 4),
            "",
            {"name": pole["name"], "position": {"x": pole["x"], "y": pole["y"]}},
            f"covered by {pole['name']}@({pole['x']},{pole['y']}); "
            f"overlap depth {depth:.2f} tiles",
        )

    if best_gap is None:
        return (False, float("inf"), "", None, "no poles in scene")

    gap, gx, gy, pole = best_gap
    if gx > 0 and gy <= 1e-9:
        axis = "X"
        toward = f"toward x={pole['x']} pole line"
        margin = gx
        detail = f"{gx:.2f} short on X {toward}"
    elif gy > 0 and gx <= 1e-9:
        axis = "Y"
        toward = f"toward y={pole['y']} pole line"
        margin = gy
        detail = f"{gy:.2f} short on Y {toward}"
    else:
        axis = "XY"
        margin = gap
        detail = (
            f"{gap:.2f} short (X {gx:.2f} toward x={pole['x']}, "
            f"Y {gy:.2f} toward y={pole['y']})"
        )
    return (
        False,
        round(margin, 4),
        axis,
        {"name": pole["name"], "position": {"x": pole["x"], "y": pole["y"]}},
        detail,
    )


def compute_supply_coverage(
    entities: List[Tuple[str, float, float]],
    poles: List[Dict[str, Any]],
    prototypes=None,
) -> List[EntityCoverage]:
    """Pure geometry core: coverage of ``entities`` by ``poles``.

    ``entities`` are (name, x, y); ``poles`` are dicts with name/x/y and either a
    resolved ``supply`` or a ``pole_name`` to resolve. ``prototypes`` defaults to
    the shared prototype accessor (offline dump). This function does NO RCON, so
    tests exercise the exact attempt-5 numbers without a live server.
    """
    prototypes = prototypes or get_entity_prototypes()
    resolved: List[Dict[str, Any]] = []
    for p in poles:
        supply = p.get("supply")
        if supply is None:
            _wire, supply = _pole_prototype_distances(p["pole_name"])
        resolved.append(
            {
                "name": p.get("name") or p.get("pole_name"),
                "x": p["x"],
                "y": p["y"],
                "supply": supply,
                "is_proposed": bool(p.get("is_proposed")),
            }
        )
    # Deterministic pole order (proposed last on ties → stable, and the live
    # spine is preferred as the covering reference when equal).
    resolved.sort(key=lambda q: (q["is_proposed"], q["x"], q["y"], q["name"]))

    out: List[EntityCoverage] = []
    for name, x, y in sorted(entities):
        ebox = _collision_box(prototypes, name, x, y)
        covered, margin, axis, by_pole, detail = _coverage_for_entity(
            ebox, (x, y), resolved
        )
        out.append(
            EntityCoverage(
                entity_name=name,
                position={"x": x, "y": y},
                covered=covered,
                margin=margin,
                margin_axis=axis,
                by_pole_name=by_pole["name"] if by_pole else None,
                by_pole_position=by_pole["position"] if by_pole else None,
                detail=detail,
            )
        )
    return out


# =============================================================================
# ASCII rendering (deterministic; tile-aligned supply areas)
# =============================================================================

_MAX_W = 64
_MAX_H = 32


def _glyph(name: str, covered: bool) -> str:
    g = _ENTITY_GLYPHS.get(name)
    if g is None:
        g = (name[:1] or "?").lower()
    return g.upper() if covered else g.lower()


def render_ascii_map(
    coverage: List[EntityCoverage],
    poles: List[Dict[str, Any]],
) -> str:
    """Render a tile-aligned window of the scene.

    Supply areas are drawn as full tiles (Factorio supply areas ARE tile-aligned):
    a tile is '#' iff it intersects some pole's continuous supply box. Poles are
    'P' ('?' if proposed), entities are their glyph (UPPERCASE covered, lowercase
    not). Window auto-fits poles+entities, capped at 64x32 (truncation noted).
    """
    if not poles and not coverage:
        return "(empty scene)"

    # Collect world extents from supply boxes + entity boxes + centres.
    xs: List[float] = []
    ys: List[float] = []
    for p in poles:
        sb = _supply_box(p["x"], p["y"], p["supply"])
        xs += [sb[0], sb[2]]
        ys += [sb[1], sb[3]]
    for c in coverage:
        xs += [c.position["x"]]
        ys += [c.position["y"]]

    min_tx, max_tx = math.floor(min(xs)), math.ceil(max(xs)) - 1
    min_ty, max_ty = math.floor(min(ys)), math.ceil(max(ys)) - 1

    truncated = False
    if max_tx - min_tx + 1 > _MAX_W:
        # centre on entity/pole centroid
        cx = int(round(sum(c.position["x"] for c in coverage) / len(coverage))) if coverage \
            else (min_tx + max_tx) // 2
        min_tx, max_tx = cx - _MAX_W // 2, cx + _MAX_W // 2 - 1
        truncated = True
    if max_ty - min_ty + 1 > _MAX_H:
        cy = int(round(sum(c.position["y"] for c in coverage) / len(coverage))) if coverage \
            else (min_ty + max_ty) // 2
        min_ty, max_ty = cy - _MAX_H // 2, cy + _MAX_H // 2 - 1
        truncated = True

    x_tiles = list(range(min_tx, max_tx + 1))
    y_tiles = list(range(min_ty, max_ty + 1))
    n_cols = len(x_tiles)
    prefix_w = max(len(str(min_ty)), len(str(max_ty)), 4) + 1

    # Precompute covered tiles (union of pole supply areas, tile-aligned).
    covered_tiles = set()
    for p in poles:
        sb = _supply_box(p["x"], p["y"], p["supply"])
        for tx in x_tiles:
            if tx >= sb[2] or tx + 1 <= sb[0]:
                continue
            for ty in y_tiles:
                if ty >= sb[3] or ty + 1 <= sb[1]:
                    continue
                covered_tiles.add((tx, ty))

    pole_tiles = {(math.floor(p["x"]), math.floor(p["y"])): p for p in poles}
    ent_tiles = {(math.floor(c.position["x"]), math.floor(c.position["y"])): c
                 for c in coverage}

    # x ruler (labels every 5 tiles, written starting at their column).
    label_row = [" "] * (prefix_w + n_cols)
    tick_row = [" "] * (prefix_w + n_cols)
    for i, tx in enumerate(x_tiles):
        if tx % 5 == 0:
            col = prefix_w + i
            tick_row[col] = "|"
            s = str(tx)
            for j, ch in enumerate(s):
                if col + j < len(label_row):
                    label_row[col + j] = ch

    lines = ["".join(label_row).rstrip(), "".join(tick_row).rstrip()]
    for ty in y_tiles:
        row_chars = []
        for tx in x_tiles:
            ent = ent_tiles.get((tx, ty))
            if ent is not None:
                row_chars.append(_glyph(ent.entity_name, ent.covered))
            elif (tx, ty) in pole_tiles:
                row_chars.append("?" if pole_tiles[(tx, ty)]["is_proposed"] else "P")
            elif (tx, ty) in covered_tiles:
                row_chars.append("#")
            else:
                row_chars.append(".")
        ymark = "-" if ty % 5 == 0 else " "
        lines.append(f"{ty:>{prefix_w - 1}}{ymark}" + "".join(row_chars))

    legend = (
        "legend: # supply tile  . uncovered  P pole  ? proposed  "
        "UPPER=entity covered  lower=NOT covered"
    )
    lines.append(legend)
    if truncated:
        lines.append(f"(window truncated to {_MAX_W}x{_MAX_H} tiles)")
    return "\n".join(lines)


# =============================================================================
# VerifyView (live)
# =============================================================================


def _pos_xy(position: Any) -> Tuple[float, float]:
    """Normalize a position arg to (x, y): MapPosition | {'x','y'} | (x, y)."""
    if hasattr(position, "x") and hasattr(position, "y"):
        return float(position.x), float(position.y)
    if isinstance(position, dict):
        return float(position["x"]), float(position["y"])
    if isinstance(position, (tuple, list)) and len(position) >= 2:
        return float(position[0]), float(position[1])
    raise TypeError(
        f"Unsupported position {position!r}; expected MapPosition, "
        f"{{'x','y'}} dict, or (x, y) tuple"
    )


def _normalize_target(t: Target) -> Tuple[str, float, float]:
    """(entity_name, x, y) from a (name, position) tuple or a dict."""
    if isinstance(t, dict):
        name = t.get("entity_name") or t.get("name")
        if name is None:
            raise ValueError(f"target dict missing entity_name/name: {t!r}")
        if "position" in t:
            x, y = _pos_xy(t["position"])
        else:
            x, y = float(t["x"]), float(t["y"])
        return name, x, y
    if isinstance(t, (tuple, list)) and len(t) == 2 and isinstance(t[0], str):
        x, y = _pos_xy(t[1])
        return t[0], x, y
    raise TypeError(
        f"Unsupported target {t!r}; expected (entity_name, position) or "
        f"{{'entity_name','position'}}"
    )


class VerifyView:
    """Live confirmation of power / coverage facts via the running engine.

    Bound into the agent namespace as ``verify``. Reads are live (raw ``/sc`` Lua
    over the existing RCON handler — the same route ``PlacementHintsClient`` and
    ``check_L1_14`` use); geometry is prototype-derived. See module docstring for
    the full freshness contract.

    Example:
        >>> # Preview a pole spine before committing drills to it
        >>> report = verify.supply_coverage(
        ...     entities=[("electric-mining-drill", {"x": 5, "y": 59.5})],
        ...     area={"left_top": {"x": 0, "y": 55}, "right_bottom": {"x": 12, "y": 68}},
        ... )
        >>> print(report.summary)
        >>> print(report.ascii_map)
    """

    def __init__(self, rcon_handler: "RconHandler", prototypes=None):
        self._rcon = rcon_handler
        self._prototypes = prototypes or get_entity_prototypes()

    # -- RCON plumbing --------------------------------------------------------

    @staticmethod
    def _to_lua(value: Any) -> str:
        if value is None:
            return "nil"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return repr(float(value)) if isinstance(value, float) else str(value)
        if isinstance(value, str):
            return json.dumps(value)  # safe quoting
        if isinstance(value, dict):
            items = ", ".join(f"[{json.dumps(k)}] = {VerifyView._to_lua(v)}"
                              for k, v in value.items())
            return "{" + items + "}"
        if isinstance(value, (list, tuple)):
            return "{" + ", ".join(VerifyView._to_lua(v) for v in value) + "}"
        raise TypeError(f"cannot convert {type(value)} to Lua")

    def _lua(self, body: str) -> Any:
        """Run a Lua body under xpcall; return the parsed JSON result.

        Mirrors the certified check_L1_14 wrapper: the body should ``return`` a
        table; errors come back as ``{"error": ...}``.
        """
        cmd = (
            "local ok, res = xpcall(function() " + body + " end, debug.traceback) "
            "if ok then rcon.print(helpers.table_to_json("
            "res == nil and {ok=true} or res)) "
            "else rcon.print(helpers.table_to_json({error = tostring(res)})) end"
        )
        out = self._rcon.execute(cmd, silent=True)
        if out is None or out.strip() == "":
            return {"error": "empty RCON response"}
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return {"error": f"non-JSON response: {out[:400]}"}

    # -- powered --------------------------------------------------------------

    def powered(
        self, targets: Union[Target, List[Target]]
    ) -> Dict[str, PoweredCheck]:
        """Live power status for one or many entities, keyed 'name@(x,y)'.

        Accepts a single (name, position) target or a list; positions may be
        MapPosition, {'x','y'} dicts, or (x, y) tuples. One RCON roundtrip for the
        whole batch. See :class:`PoweredCheck` for the ``powered`` definition and
        its caveats.
        """
        if isinstance(targets, (tuple, dict)) and not (
            isinstance(targets, list)
        ):
            # single target (tuple/dict) — but a (name, pos) tuple is length 2
            norm = [_normalize_target(targets)]
        else:
            norm = [_normalize_target(t) for t in targets]

        lua_targets = [{"name": n, "x": x, "y": y} for n, x, y in norm]
        body = (
            "local s = game.surfaces[1] "
            "local names = {} "
            "for k, v in pairs(defines.entity_status) do names[v] = k end "
            f"local targets = {self._to_lua(lua_targets)} "
            "local out = {} "
            "for _, t in ipairs(targets) do "
            "  local e = s.find_entities_filtered{name=t.name, "
            "    position={x=t.x, y=t.y}, radius=0.6}[1] "
            "  if e and e.valid then "
            "    local nid = e.electric_network_id "
            "    local st = names[e.status] "
            "    out[#out+1] = {found=true, name=t.name, x=t.x, y=t.y, "
            "      status_name=st, electric_network_id=nid, "
            "      powered=(nid ~= nil and st ~= 'no_power')} "
            "  else "
            "    out[#out+1] = {found=false, name=t.name, x=t.x, y=t.y} "
            "  end "
            "end "
            "return out"
        )
        raw = self._lua(body)
        result: Dict[str, PoweredCheck] = {}
        rows = raw if isinstance(raw, list) else []
        # Align by index (Lua preserves order); fall back to input on short rows.
        for (name, x, y), row in zip(norm, rows + [{}] * (len(norm) - len(rows))):
            key = f"{name}@({x},{y})"
            if row.get("found"):
                result[key] = PoweredCheck(
                    entity_name=name,
                    position={"x": x, "y": y},
                    found=True,
                    powered=bool(row.get("powered")),
                    status_name=row.get("status_name"),
                    electric_network_id=row.get("electric_network_id"),
                )
            else:
                result[key] = PoweredCheck(
                    entity_name=name, position={"x": x, "y": y}, found=False
                )
        return result

    # -- connected ------------------------------------------------------------

    def connected(self, a: Target, b: Target) -> ConnectedCheck:
        """Whether two entities share one live electric network (right now)."""
        an, ax, ay = _normalize_target(a)
        bn, bx, by = _normalize_target(b)
        checks = self.powered([(an, {"x": ax, "y": ay}), (bn, {"x": bx, "y": by})])
        ca = checks[f"{an}@({ax},{ay})"]
        cb = checks[f"{bn}@({bx},{by})"]
        connected = (
            ca.found and cb.found
            and ca.electric_network_id is not None
            and ca.electric_network_id == cb.electric_network_id
        )
        if not ca.found or not cb.found:
            expl = "not connected: " + ", ".join(
                f"{n} not found" for n, c in ((an, ca), (bn, cb)) if not c.found
            )
        elif connected:
            expl = f"connected: both on electric_network_id {ca.electric_network_id}"
        elif ca.electric_network_id is None or cb.electric_network_id is None:
            expl = "not connected: at least one entity is on no electric network"
        else:
            expl = (
                f"not connected: {an} on network {ca.electric_network_id}, "
                f"{bn} on network {cb.electric_network_id}"
            )
        return ConnectedCheck(
            a_name=an, a_position={"x": ax, "y": ay},
            b_name=bn, b_position={"x": bx, "y": by},
            connected=connected, a_found=ca.found, b_found=cb.found,
            a_network_id=ca.electric_network_id,
            b_network_id=cb.electric_network_id,
            explanation=expl,
        )

    # -- supply_coverage ------------------------------------------------------

    def _live_poles_in_area(self, area: Dict[str, Any]) -> List[Dict[str, Any]]:
        lt, rb = area["left_top"], area["right_bottom"]
        body = (
            "local s = game.surfaces[1] "
            f"local poles = s.find_entities_filtered{{type='electric-pole', "
            f"area={{{{{lt['x']}, {lt['y']}}}, {{{rb['x']}, {rb['y']}}}}}}} "
            "local out = {} "
            "for _, p in ipairs(poles) do "
            "  out[#out+1] = {name=p.name, x=p.position.x, y=p.position.y, "
            "    electric_network_id=p.electric_network_id} "
            "end "
            "return out"
        )
        raw = self._lua(body)
        return raw if isinstance(raw, list) else []

    def _live_consumers_in_area(self, area: Dict[str, Any]) -> List[Dict[str, Any]]:
        lt, rb = area["left_top"], area["right_bottom"]
        body = (
            "local s = game.surfaces[1] "
            f"local ents = s.find_entities_filtered{{"
            f"area={{{{{lt['x']}, {lt['y']}}}, {{{rb['x']}, {rb['y']}}}}}}} "
            "local out = {} "
            "for _, e in ipairs(ents) do "
            "  if e.valid and e.type ~= 'electric-pole' and e.type ~= 'resource' "
            "     and e.type ~= 'character' "
            "     and e.prototype.electric_energy_source_prototype ~= nil then "
            "    out[#out+1] = {name=e.name, x=e.position.x, y=e.position.y} "
            "  end "
            "end "
            "return out"
        )
        raw = self._lua(body)
        return raw if isinstance(raw, list) else []

    def supply_coverage(
        self,
        entities: Optional[List[Target]] = None,
        area: Optional[Dict[str, Any]] = None,
        proposed_pole: Optional[Tuple[str, Any]] = None,
    ) -> SupplyCoverageReport:
        """Is every electric consumer actually inside a pole's supply area?

        The centrepiece live check. Pole set = every live electric pole in
        ``area`` (or a bound around ``entities`` when ``area`` is omitted), PLUS an
        optional ``proposed_pole=(pole_name, position)`` evaluated as-if-placed
        (pre-placement preview). Entity set = ``entities`` (each a
        (name, position)) or, if omitted, every live electric consumer in ``area``.

        Coverage is the engine rule — entity collision box intersects supply box —
        and each entity carries a signed ``margin`` (overlap depth if covered, or
        the shortest move to become covered, with axis, if not). The report also
        renders a tile-aligned ``ascii_map``.

        Args:
            entities: explicit consumers to check (name + position). Optional if
                ``area`` is given (then discovered live).
            area: {'left_top': {x,y}, 'right_bottom': {x,y}} for pole (and entity)
                discovery. Optional if ``entities`` is given (a bound is derived).
            proposed_pole: (pole_name, position) — scored as if already placed.

        Returns:
            SupplyCoverageReport.
        """
        ent_targets: List[Tuple[str, float, float]] = []
        if entities:
            ent_targets = [_normalize_target(t) for t in entities]

        # Derive a discovery area from entities when none was given.
        if area is None:
            if not ent_targets:
                raise ValueError("supply_coverage needs entities or an area")
            xs = [x for _, x, _ in ent_targets]
            ys = [y for _, _, y in ent_targets]
            pad = 8.0  # ~big-pole supply reach, so nearby poles are found
            area = {
                "left_top": {"x": min(xs) - pad, "y": min(ys) - pad},
                "right_bottom": {"x": max(xs) + pad, "y": max(ys) + pad},
            }

        if not ent_targets:
            ent_targets = [
                (c["name"], c["x"], c["y"]) for c in self._live_consumers_in_area(area)
            ]

        # Pole set: live + proposed.
        pole_specs: List[Dict[str, Any]] = []
        for p in self._live_poles_in_area(area):
            try:
                _wire, supply = _pole_prototype_distances(p["name"])
            except ValueError:
                continue
            pole_specs.append(
                {"name": p["name"], "x": p["x"], "y": p["y"],
                 "supply": supply, "is_proposed": False}
            )
        if proposed_pole is not None:
            pname, ppos = proposed_pole
            px, py = _pos_xy(ppos)
            _wire, psupply = _pole_prototype_distances(pname)
            pole_specs.append(
                {"name": pname, "x": px, "y": py,
                 "supply": psupply, "is_proposed": True}
            )

        coverage = compute_supply_coverage(
            ent_targets, pole_specs, prototypes=self._prototypes
        )
        # Re-resolve poles in the same sorted/dedup order the geometry used, for
        # a stable ascii + report.
        resolved_poles = sorted(
            pole_specs, key=lambda q: (q["is_proposed"], q["x"], q["y"], q["name"])
        )

        covered_count = sum(1 for c in coverage if c.covered)
        total = len(coverage)
        uncovered = [c for c in coverage if not c.covered]
        if uncovered:
            miss = "; ".join(
                f"{c.entity_name}@({c.position['x']},{c.position['y']}) "
                f"({c.margin} short on {c.margin_axis or '—'})"
                for c in uncovered
            )
            summary = f"{covered_count}/{total} covered | NOT covered: {miss}"
        else:
            summary = f"{covered_count}/{total} covered | all entities powered-by-geometry"

        ascii_map = render_ascii_map(coverage, resolved_poles)

        return SupplyCoverageReport(
            entities=coverage,
            poles=[
                {"name": p["name"], "position": {"x": p["x"], "y": p["y"]},
                 "supply_area_distance": p["supply"], "is_proposed": p["is_proposed"]}
                for p in resolved_poles
            ],
            covered_count=covered_count,
            total_count=total,
            summary=summary,
            ascii_map=ascii_map,
            freshness_note=_FRESHNESS,
        )


__all__ = [
    "VerifyView",
    "PoweredCheck",
    "ConnectedCheck",
    "EntityCoverage",
    "SupplyCoverageReport",
    "compute_supply_coverage",
    "render_ascii_map",
]
