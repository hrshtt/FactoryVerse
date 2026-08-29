"""The entity reference — planning-time answers about a thing on your cursor.

Constitution §6: a method belongs here **if and only if** a person could answer
it holding the item and having placed nothing. Footprint, buildability, supply
overlay, the drop arrow, where an inserter could go between two machines,
where an offshore pump could sit — yes. Contents, status, network membership —
no; those need the thing to exist, and live on the real entity only.

The invariant, enforced by ``tests/unit/test_entity_reference.py``: every
public name here also exists on the real entity class for that prototype
family, under the same name. One vocabulary with a capability gate, never a
second altitude (API_AFFORDANCE_REDESIGN §2.2). Nothing here places anything.

Every read declares its ``source``: ``"prototype"`` (the offline data dump)
or ``"live:<tick>"`` / ``"live"`` (an engine check at call time).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from FactoryVerse.game.factory.prototypes import get_entity_prototypes, get_width_height
from FactoryVerse.game.factory.types import BoundingBox, Direction, MapPosition, TilePosition

if TYPE_CHECKING:
    from FactoryVerse.game.agent.infra.rcon_handler import RconHandler
    from FactoryVerse.game.factory.entity.base_entity import BaseEntity


# Prototype families the reference knows how to answer for. Anything else gets
# the generic surface (footprint / can_place) only.
POLE_TYPES = frozenset({"electric-pole"})
INSERTER_TYPES = frozenset({"inserter"})
DRILL_TYPES = frozenset({"mining-drill"})
OFFSHORE_PUMP_TYPES = frozenset({"offshore-pump"})


@dataclass(frozen=True)
class SourcedValue:
    """A read plus where it came from (Constitution §11)."""

    value: Any
    source: str

    def __bool__(self) -> bool:  # so `if ref.can_place(...)` reads naturally
        return bool(self.value)

    def __iter__(self):
        return iter(self.value)

    def __len__(self) -> int:
        return len(self.value)

    def __getitem__(self, i):
        return self.value[i]

    def __eq__(self, other) -> bool:
        if isinstance(other, SourcedValue):
            return self.value == other.value
        return self.value == other

    def __repr__(self) -> str:
        return f"{self.value!r}  # source={self.source}"


@dataclass
class EntityReference:
    """Planning-time answers for one entity prototype, held but not placed."""

    name: str
    _rcon: Optional["RconHandler"] = field(default=None, repr=False)
    _prototype_cache: Optional[Dict[str, Any]] = field(default=None, repr=False)

    # ---- prototype facts ----------------------------------------------------

    @property
    def prototype(self) -> Dict[str, Any]:
        """Prototype data from the offline dump (source: prototype)."""
        if self._prototype_cache is None:
            self._prototype_cache = get_entity_prototypes().get_prototype(self.name) or {}
        return self._prototype_cache

    @property
    def entity_type(self) -> Optional[str]:
        return self.prototype.get("type")

    @property
    def tile_width(self) -> int:
        proto = self.prototype
        if "tile_width" in proto and proto["tile_width"] is not None:
            return int(proto["tile_width"])
        if "collision_box" in proto:
            w, _ = get_width_height(proto["collision_box"])
            return int(math.ceil(w - 0.001))
        return 0

    @property
    def tile_height(self) -> int:
        proto = self.prototype
        if "tile_height" in proto and proto["tile_height"] is not None:
            return int(proto["tile_height"])
        if "collision_box" in proto:
            _, h = get_width_height(proto["collision_box"])
            return int(math.ceil(h - 0.001))
        return 0

    def footprint(
        self, position: MapPosition, direction: Optional[Direction] = None
    ) -> SourcedValue:
        """Tiles this entity would occupy at ``position`` (source: prototype).

        Same arithmetic as ``BaseEntity.footprint_tiles``; asymmetric entities
        facing EAST/WEST swap width and height.
        """
        width, height = self.tile_width, self.tile_height
        if direction in (Direction.EAST, Direction.WEST) and width != height:
            width, height = height, width
        half_w, half_h = width / 2, height / 2
        min_x = math.floor(position.x - half_w)
        max_x = math.floor(position.x + half_w - 0.001)
        min_y = math.floor(position.y - half_h)
        max_y = math.floor(position.y + half_h - 0.001)
        tiles = [
            TilePosition(x=x, y=y)
            for x in range(min_x, max_x + 1)
            for y in range(min_y, max_y + 1)
        ]
        return SourcedValue(tiles, "prototype")

    # ---- live buildability ----------------------------------------------------

    def can_place(
        self, position: MapPosition, direction: Optional[Direction] = None
    ) -> SourcedValue:
        """Could this be placed here right now? (source: live)

        The engine's own ``can_place_entity`` with ``build_check_type = manual``
        — the red/green preview. Reach and inventory are NOT checked: a person
        sees the preview colour before they walk over, and the reference holds
        nothing (Constitution §6). ``place()`` still needs both.
        """
        if self._rcon is None:
            raise RuntimeError("can_place needs a live engine; this reference is offline")
        from FactoryVerse.game.agent.placement_hints import PlacementHintsClient

        ok = PlacementHintsClient(self._rcon).validate_placement(
            self.name, position, direction, ghost=False
        )
        return SourcedValue(bool(ok), "live")

    # ---- poles ------------------------------------------------------------------

    def _require_family(self, family: frozenset, what: str) -> None:
        if self.entity_type not in family:
            raise AttributeError(
                f"{what} is a {sorted(family)} question; {self.name!r} is "
                f"{self.entity_type!r}"
            )

    def supply_area(self, position: MapPosition) -> SourcedValue:
        """The supply box a pole would project from ``position`` (source: prototype).

        The overlay you see holding a pole: centre ± supply_area_distance.
        """
        self._require_family(POLE_TYPES, "supply_area")
        d = float(self.prototype["supply_area_distance"])
        box = BoundingBox.from_tuple(
            ((position.x - d, position.y - d), (position.x + d, position.y + d))
        )
        return SourcedValue(box, "prototype")

    def covers(self, position: MapPosition, entity: "BaseEntity") -> SourcedValue:
        """Would a pole at ``position`` power ``entity``? (source: prototype)

        The engine rule: the entity's collision box intersects the pole's
        supply square — box against box, never a circle against a centre
        (TRANSPORT_CONNECTIVITY_PLAN §8.4).
        """
        self._require_family(POLE_TYPES, "covers")
        from FactoryVerse.game.agent.infra.live_batch import _collision_box, _overlap, _supply_box

        d = float(self.prototype["supply_area_distance"])
        ebox = _collision_box(get_entity_prototypes(), entity.name, entity.position.x, entity.position.y)
        ox, oy = _overlap(ebox, _supply_box(position.x, position.y, d))
        return SourcedValue(ox > 0 and oy > 0, "prototype")

    def wire_reach(self, position: MapPosition, other: "BaseEntity") -> SourcedValue:
        """Would a pole at ``position`` be within wire distance of ``other``? (source: prototype)

        A bound, not a promise of wiring: what actually gets wired is history
        (TRANSPORT §2). The real pole answers ``can_wire_to`` live.
        """
        self._require_family(POLE_TYPES, "wire_reach")
        reach = float(self.prototype["maximum_wire_distance"])
        other_reach = float(get_entity_prototypes().get_prototype(other.name).get("maximum_wire_distance", reach))
        dist = position.distance(other.position)
        return SourcedValue(dist <= min(reach, other_reach), "prototype")

    # ---- drills -----------------------------------------------------------------

    def drop_position(
        self, position: MapPosition, direction: Direction = Direction.NORTH
    ) -> SourcedValue:
        """Where a drill at ``position`` facing ``direction`` drops its output
        (source: prototype ``vector_to_place_result``, rotated). The arrow on the cursor.
        """
        self._require_family(DRILL_TYPES, "drop_position")
        vx, vy = self.prototype.get("vector_to_place_result", [0.0, 0.0])
        if direction == Direction.EAST:
            vx, vy = -vy, vx
        elif direction == Direction.SOUTH:
            vx, vy = -vx, -vy
        elif direction == Direction.WEST:
            vx, vy = vy, -vx
        return SourcedValue(MapPosition(x=position.x + vx, y=position.y + vy), "prototype")

    # ---- transport ------------------------------------------------------------------

    def _remote(self, method: str, *args) -> Any:
        """Call a placement_hints remote and return its answer as data.

        Unlike ``PlacementHintsClient._call`` this does NOT raise when the
        answer carries an informational ``error`` field: the Lua side files
        "gap too large" that way on a legitimately empty result
        (INSERTER-QUERY-1, 2026-08-25 forensics). Only a transport/pcall
        failure raises — that is the case where the world state is unknown.
        """
        import json as _json
        from FactoryVerse.game.agent.placement_hints import PlacementHintsClient

        client = PlacementHintsClient(self._rcon)
        lua_args = ", ".join(client._to_lua(a) for a in args)
        cmd = (
            f'local ok, res = pcall(function() '
            f'return remote.call("{client.INTERFACE_NAME}", "{method}", {lua_args}) end); '
            f'rcon.print(helpers.table_to_json({{ok = ok, res = res}}))'
        )
        raw = self._rcon.execute(cmd)
        if not raw or not str(raw).strip():
            raise RuntimeError(f"placement_hints.{method}: empty response (transport)")
        parsed = _json.loads(str(raw).strip())
        if isinstance(parsed, dict) and "ok" in parsed:
            if not parsed["ok"]:
                raise RuntimeError(f"placement_hints.{method} failed in Lua: {parsed.get('res')}")
            return parsed.get("res")
        return parsed  # a fake or an older wrapper answered with the bare result

    # ---- inserters --------------------------------------------------------------

    def placements_between(
        self, source: "BaseEntity", target: "BaseEntity"
    ) -> SourcedValue:
        """Positions and facings where this inserter would move items from
        ``source`` into ``target`` (source: live — both must exist).

        Owner decision: the inserter reference, not the source machine. The
        thing on the cursor is the inserter; the machines are what it is held
        over. The engine answers from the placed machines' real geometry.
        """
        self._require_family(INSERTER_TYPES, "placements_between")
        if self._rcon is None:
            raise RuntimeError("placements_between needs a live engine")
        result = self._remote(
            "get_inserter_placements",
            source.name, source.position, target.name, target.position, self.name,
            {"max_results": 20},
        )
        positions = result.get("positions", []) if isinstance(result, dict) else []
        out: List[Tuple[MapPosition, Direction]] = [
            (
                MapPosition(x=p["position"]["x"], y=p["position"]["y"]),
                Direction(p["direction"]) if p.get("direction") is not None else Direction.NORTH,
            )
            for p in positions
            if p.get("valid", True)
        ]
        # The Lua side files "gap too large" as an informational `error` on a
        # successful zero-candidate answer; surface it as data, never raise.
        reason = result.get("error") if isinstance(result, dict) else None
        return SourcedValue({"positions": out, "reason": reason}, "live")

    # ---- offshore pumps -----------------------------------------------------------

    def sites(self, near: MapPosition, radius: int = 20, max_results: int = 20) -> SourcedValue:
        """Where an offshore pump could sit near ``near``, with its required
        facing and a standable approach position (source: live can_place)."""
        self._require_family(OFFSHORE_PUMP_TYPES, "sites")
        if self._rcon is None:
            raise RuntimeError("sites needs a live engine")
        from FactoryVerse.game.agent.placement_hints import PlacementHintsClient, offshore_pump_sites

        return SourcedValue(
            offshore_pump_sites(PlacementHintsClient(self._rcon), near, radius, max_results), "live"
        )

    # ---- connection cues ----------------------------------------------------------

    def connection_positions(self, source_entity: "BaseEntity", connection_type=None) -> SourcedValue:
        """Where this (held) entity would sit so that it connects to
        ``source_entity`` — the cue a person sees holding a boiler next to a
        pump, a chest next to a drill, or a pole in range of another pole.

        The connection kind is inferred from the pair (item-drop from a drill,
        wire between poles, fluid otherwise) unless given. Returns the cues
        with the query's ``reason`` when empty (source: live engine values —
        drop_position, fluidbox, wire_connector — never prototype arithmetic).
        The same read exists on the placed object as
        ``entity.connection_positions(target_name)``.
        """
        if self._rcon is None:
            raise RuntimeError("connection_positions needs a live engine")
        from FactoryVerse.game.agent.placement_hints import (
            PlacementHintsClient,
            connection_positions,
            infer_connection_type,
        )

        ct = connection_type or infer_connection_type(source_entity.name, self.name)
        cues = connection_positions(PlacementHintsClient(self._rcon), source_entity, self.name, ct)
        return SourcedValue(cues, "live")

    def __repr__(self) -> str:
        return f"EntityReference({self.name!r}, type={self.entity_type!r})"


class EntityReferenceAccessor:
    """``entity_reference("small-electric-pole")`` → an :class:`EntityReference`.

    Callable so the namespace reads as one gesture: pick the thing up.
    """

    def __init__(self, rcon_handler: Optional["RconHandler"] = None):
        self._rcon = rcon_handler

    def __call__(self, entity_name: str) -> EntityReference:
        protos = get_entity_prototypes()
        if not protos.get_prototype(entity_name):
            raise ValueError(
                f"{entity_name!r} is not a placeable entity in this scope "
                f"(fv_filters.yaml); nothing to hold"
            )
        return EntityReference(entity_name, self._rcon)

    def get(self, entity_name: str) -> EntityReference:
        """Same as calling the accessor; kept for readers who prefer a verb."""
        return self(entity_name)

    def __repr__(self) -> str:
        return "entity_reference(<entity-name>)"
