"""Placement-hints transport and the connection reads that ride it.

INFRASTRUCTURE, NOT AN ACCESSOR. The agent never sees a ``placement_hints``
name: the lawful reads here (connection cues, inserter placements, offshore
pump sites, the red/green preview) are exposed on ``entity_reference(...)``
and on the real entity objects under identical names
(API_AFFORDANCE_REDESIGN §2.2, Constitution §6). What was deleted with the
accessor (2026-08-29): the set-cover pole planner, the pre-flight validators,
``GhostPlan`` as a commit handle, the line/underground generators with their
hardcoded distances, and the ``BELT_FLOW``/``INSERTER_REACH`` phantom enum
members. The transport (``PlacementHintsClient``) and the pure parsers stay.

No side effects: nothing here mutates game state.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Dict, Any, Tuple, FrozenSet, TYPE_CHECKING
import logging
import json

from FactoryVerse.game.factory.types import MapPosition, Direction
from FactoryVerse.game.factory.prototypes import get_entity_prototypes

if TYPE_CHECKING:
    from FactoryVerse.game.agent.infra.rcon_handler import RconHandler
    from FactoryVerse.game.factory.entity.base_entity import BaseEntity

logger = logging.getLogger(__name__)


class ConnectionQueryError(RuntimeError):
    """A connection-solving query failed to execute.

    Distinct from a successful query with zero candidates (which returns []).
    Returning [] on failure teaches the agent "no candidates exist" — a false
    world-model (see ERR-3, docs/retros/2026-06-10-engine-unit-retro.md).
    """

    def __init__(self, query: str, source: str, target: str, cause: Exception):
        self.query = query
        self.source = source
        self.target = target
        self.cause = cause
        super().__init__(
            f"{query} failed for {source} -> {target}: {cause}. "
            f"This is a query/transport failure, NOT 'no valid positions' — "
            f"do not conclude the connection is impossible."
        )


# =============================================================================
# DATA STRUCTURES
# =============================================================================


class ConnectionType(Enum):
    """Connection types for solving entity placement puzzles.

    ITEM_DROP: Mining drills push items directly into adjacent entities. Cannot use inserters with drills.

    Inserters are NOT a connection type: use
    ``get_inserter_placement_positions(source, target)`` instead.
    """

    ITEM_DROP = "item_drop"  # Mining drill -> Chest/Belt (direct push, no inserters)
    FLUID_PIPE = "fluid_pipe"  # Pipe -> Machine/Pipe
    ELECTRIC_WIRE = "wire"  # Pole -> Pole


# =============================================================================
# ENTITY METADATA
# =============================================================================

ITEM_DROP_ENTITIES: FrozenSet[str] = frozenset([
    "electric-mining-drill",
    "burner-mining-drill",
])

FLUID_PIPE_ENTITIES: FrozenSet[str] = frozenset([
    "boiler", "steam-engine", "steam-turbine",
    "chemical-plant", "oil-refinery", "pumpjack",
    "pipe", "pipe-to-ground", "pump", "offshore-pump", "storage-tank",
])

RESOURCE_PLACEMENT_ENTITIES: FrozenSet[str] = frozenset([
    "electric-mining-drill", "burner-mining-drill", "pumpjack",
])

WATER_PLACEMENT_ENTITIES: FrozenSet[str] = frozenset([
    "offshore-pump",
])

INSERTER_ENTITIES: FrozenSet[str] = frozenset([
    "inserter", "long-handed-inserter", "fast-inserter",
    "filter-inserter", "stack-inserter", "stack-filter-inserter",
    "bulk-inserter", "burner-inserter",
])

ELECTRIC_POLE_ENTITIES: FrozenSet[str] = frozenset([
    "small-electric-pole", "medium-electric-pole",
    "big-electric-pole", "substation",
])


class EntityValidationError(ValueError):
    """Raised when a placement method is called with an incompatible entity."""
    pass


def validate_entity_for_connection(
    entity_name: str,
    connection_type: ConnectionType,
) -> None:
    """Validate that an entity is compatible with a connection type."""
    if connection_type == ConnectionType.ITEM_DROP:
        if entity_name not in ITEM_DROP_ENTITIES:
            raise EntityValidationError(
                f"ITEM_DROP connection not applicable to '{entity_name}'. "
                f"Valid entities: {sorted(ITEM_DROP_ENTITIES)}"
            )
    elif connection_type == ConnectionType.FLUID_PIPE:
        if entity_name not in FLUID_PIPE_ENTITIES:
            raise EntityValidationError(
                f"FLUID_PIPE connection not applicable to '{entity_name}'. "
                f"Valid entities: {sorted(FLUID_PIPE_ENTITIES)}"
            )
    elif connection_type == ConnectionType.ELECTRIC_WIRE:
        if entity_name not in ELECTRIC_POLE_ENTITIES:
            raise EntityValidationError(
                f"ELECTRIC_WIRE connection not applicable to '{entity_name}'. "
                f"Valid entities: {sorted(ELECTRIC_POLE_ENTITIES)}"
            )


def infer_connection_type(source_name: str, target_name: str) -> ConnectionType:
    """The connection kind a pair implies: a drill pushes items, poles wire,
    fluid entities pipe. Raises ``EntityValidationError`` when the pair has no
    connection the engine knows about."""
    if source_name in ITEM_DROP_ENTITIES:
        return ConnectionType.ITEM_DROP
    if source_name in ELECTRIC_POLE_ENTITIES and target_name in ELECTRIC_POLE_ENTITIES:
        return ConnectionType.ELECTRIC_WIRE
    if source_name in FLUID_PIPE_ENTITIES:
        return ConnectionType.FLUID_PIPE
    raise EntityValidationError(
        f"{source_name!r} → {target_name!r}: no item-drop, fluid or wire connection "
        f"exists between these; inserters bridge everything else "
        f"(entity_reference('inserter').placements_between(a, b))"
    )


@dataclass
class ConnectionPosition:
    """A valid position for placing a target entity to connect to a source entity.

    Connection-query results are normally sorted by alignment quality.
    Offshore-pump sites instead use map proximity and are sorted nearest-anchor
    first around the requested search center.

    Attributes:
        position: The map position where the target entity should be placed.
        direction: The direction the target entity should face (if applicable).
        approach_position: Optional standable character position within build
            reach of ``position``. Offshore-pump site results always provide
            this so callers never walk to the water-overlapping anchor.
        perpendicular_offset: Alignment quality metric - lower is better (0.0 = perfectly aligned).
        displaces_character: True when the only thing in the footprint is a
            character (usually YOU). The placement still works — the engine
            steps the character aside, exactly like building on your own
            tile in the GUI. Not an error; do not skip these cues.
    """

    position: MapPosition
    direction: Optional[Direction]
    perpendicular_offset: float = 0.0  # Lower = better alignment
    displaces_character: bool = False
    approach_position: Optional[MapPosition] = None

    def __post_init__(self):
        if self.perpendicular_offset < 0:
            raise ValueError("perpendicular_offset must be non-negative")


@dataclass
class WireConnectionPosition(ConnectionPosition):
    """Connection position for ELECTRIC_WIRE connections (pole to pole)."""

    wire_distance: float = 0.0
    wire_distance_utilization: float = 0.0  # Ratio of distance / max wire distance

    def __post_init__(self):
        super().__post_init__()
        if self.wire_distance < 0:
            raise ValueError("wire_distance must be non-negative")


class ConnectionPositionList(list):
    """A `List[ConnectionPosition]`-compatible result that also carries the
    connection query's raw metadata (REASON-1 fix).

    The Lua connection solvers (`fv_placement_hints/connections/init.lua`)
    return a rich dict — ``positions``, ``count``, and (for fluid) a
    zero-cue ``reason`` — but the Python wrappers used to keep only the
    ``positions`` list and throw the rest away. A zero-cue answer with no
    reason is a "no candidates" dead end the agent can't act on (compare
    ``ConnectionQueryError``, which exists precisely because "empty" and
    "failed" must never look the same to the caller — this is the analogous
    problem for "empty, but WHY").

    Still just a list: truthiness, ``len()``, iteration, and indexing behave
    exactly as before, so `if positions:` / `for p in positions` callers are
    unaffected. The extra fields are attributes, not list elements.

    Attributes:
        reason: Human-readable explanation for why the result is empty (or
            None if non-empty, or if the solver didn't supply one and none
            could be synthesized).
        max_wire_distance: The engine-derived max wire distance used to
            bound the search (ELECTRIC_WIRE queries only; None otherwise).
        source_name: The Lua result's ``source_name`` — the source entity's
            prototype name the query was solved against.
        search_metadata: Any other raw Lua result fields worth keeping
            (e.g. ``count``, ``target_name``, ``blocked_candidates``).
    """

    def __init__(
        self,
        iterable=(),
        *,
        reason: Optional[str] = None,
        max_wire_distance: Optional[float] = None,
        source_name: Optional[str] = None,
        search_metadata: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(iterable)
        self.reason = reason
        self.max_wire_distance = max_wire_distance
        self.source_name = source_name
        self.search_metadata = search_metadata or {}

    def __repr__(self) -> str:
        base = super().__repr__()
        if len(self) > 0:
            return base

        bits = []
        if self.reason:
            bits.append(self.reason)
        if self.max_wire_distance is not None:
            bits.append(f"max_wire_distance={self.max_wire_distance}")
        if self.source_name:
            bits.append(f"source={self.source_name}")
        for key, value in self.search_metadata.items():
            bits.append(f"{key}={value}")

        if not bits:
            return f"{base} (no valid positions; no metadata surfaced)"
        return f"{base} (no valid positions: {', '.join(bits)})"


# =============================================================================
# PLACEMENT HINTS CLIENT - RCON wrapper for fv_placement_hints Lua mod
# =============================================================================


class PlacementHintsClient:
    """Low-level RCON client for fv_placement_hints Lua mod.

    Wraps all remote interface calls to the Lua mod, handling serialization
    and response parsing. Uses engine-provided values (drop_position, fluidbox,
    wire_connector) via the mod rather than prototype calculations.
    """

    INTERFACE_NAME = "placement_hints"

    def __init__(self, rcon_handler: "RconHandler"):
        """Initialize client with RCON handler."""
        self._rcon = rcon_handler

    def _to_lua(self, value: Any) -> str:
        """Convert Python value to Lua literal."""
        if value is None:
            return "nil"
        elif isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, str):
            return f'"{value}"'
        elif isinstance(value, MapPosition):
            return f"{{x = {value.x}, y = {value.y}}}"
        elif isinstance(value, Direction):
            return str(value.value)
        elif isinstance(value, dict):
            items = ", ".join(f"{k} = {self._to_lua(v)}" for k, v in value.items())
            return "{" + items + "}"
        elif isinstance(value, (list, tuple)):
            items = ", ".join(self._to_lua(v) for v in value)
            return "{" + items + "}"
        else:
            raise ValueError(f"Cannot convert {type(value)} to Lua")

    def _call(self, method: str, *args) -> Any:
        """Call a placement_hints remote interface method."""
        lua_args = ", ".join(self._to_lua(arg) for arg in args)
        cmd = (
            f'local ok, res = pcall(function() '
            f'return remote.call("{self.INTERFACE_NAME}", "{method}", {lua_args}) '
            f'end); '
            f'if ok then rcon.print(helpers.table_to_json(res)) '
            f'else rcon.print(helpers.table_to_json({{error = tostring(res)}})) end'
        )
        result = self._rcon.execute(cmd)

        if not result or not result.strip():
            raise RuntimeError(f"Empty response from placement_hints.{method}")

        try:
            parsed = json.loads(result.strip())
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Failed to parse response: {result}") from e

        if isinstance(parsed, dict) and "error" in parsed:
            raise RuntimeError(f"placement_hints.{method} failed: {parsed['error']}")

        return parsed

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    def validate_placement(
        self,
        entity_name: str,
        position: MapPosition,
        direction: Optional[Direction] = None,
        ghost: bool = False,
    ) -> bool:
        """Validate a single placement position."""
        result = self._call(
            "validate_placement",
            entity_name,
            {"x": position.x, "y": position.y},
            direction.value if direction else None,
            ghost,
        )
        return result.get("valid", False) if isinstance(result, dict) else bool(result)

    def validate_positions(
        self,
        entity_name: str,
        positions: List[MapPosition],
        directions: Optional[List[Optional[Direction]]] = None,
        ghost: bool = False,
    ) -> List[bool]:
        """Validate multiple positions in a single call."""
        pos_list = [{"x": p.x, "y": p.y} for p in positions]
        dir_list = None
        if directions:
            dir_list = [d.value if d else None for d in directions]

        result = self._call("validate_positions", entity_name, pos_list, dir_list, ghost)

        if isinstance(result, list):
            return [bool(v) for v in result]
        return [False] * len(positions)

    def get_placement_cue(
        self,
        entity_name: str,
        position: MapPosition,
        direction: Optional[Direction] = None,
    ) -> Dict[str, Any]:
        """Get rich placement feedback (valid, collisions, footprint, etc.)."""
        return self._call(
            "get_placement_cue",
            entity_name,
            {"x": position.x, "y": position.y},
            direction.value if direction else None,
        )

    def get_water_placements(
        self,
        entity_name: str,
        area: Dict[str, Dict[str, float]],
        max_results: int = 20,
    ) -> Dict[str, Any]:
        """Return engine-validated water-edge positions and directions."""
        return self._call(
            "get_water_placements",
            entity_name,
            area,
            {"max_results": max_results},
        )

    # =========================================================================
    # CONNECTION SOLVING METHODS
    # =========================================================================

    def get_item_drop_connections(
        self,
        source_name: str,
        source_position: MapPosition,
        target_name: str,
        max_results: int = 20,
    ) -> Dict[str, Any]:
        """Find positions where target can receive items from source."""
        return self._call(
            "get_item_drop_connections",
            source_name,
            {"x": source_position.x, "y": source_position.y},
            target_name,
            {"max_results": max_results},
        )

    def get_fluid_connections(
        self,
        source_name: str,
        source_position: MapPosition,
        target_name: str,
        max_results: int = 20,
    ) -> Dict[str, Any]:
        """Find positions where pipes can connect to source fluidbox."""
        return self._call(
            "get_fluid_connections",
            source_name,
            {"x": source_position.x, "y": source_position.y},
            target_name,
            {"max_results": max_results},
        )

    def get_inserter_placements(
        self,
        source_name: str,
        source_position: MapPosition,
        target_name: str,
        target_position: MapPosition,
        inserter_name: str = "inserter",
        max_results: int = 10,
    ) -> Dict[str, Any]:
        """Find inserter positions to transfer items from source to target."""
        return self._call(
            "get_inserter_placements",
            source_name,
            {"x": source_position.x, "y": source_position.y},
            target_name,
            {"x": target_position.x, "y": target_position.y},
            inserter_name,
            {"max_results": max_results},
        )

    def get_pole_connections(
        self,
        source_name: str,
        source_position: MapPosition,
        pole_name: str,
        search_area: Dict[str, Any],
        max_results: int = 20,
    ) -> Dict[str, Any]:
        """Find pole positions within wire range of source pole."""
        return self._call(
            "get_pole_connections",
            source_name,
            {"x": source_position.x, "y": source_position.y},
            pole_name,
            search_area,
            {"max_results": max_results},
        )

    # =========================================================================
    # ENTITY INFORMATION METHODS
    # =========================================================================

    def get_entity_output_info(
        self,
        entity_name: str,
        position: MapPosition,
    ) -> Dict[str, Any]:
        """Get entity output info (drop_position, bounding_box) from engine."""
        return self._call(
            "get_entity_output_info",
            entity_name,
            {"x": position.x, "y": position.y},
        )

    def get_fluid_connection_points(
        self,
        entity_name: str,
        position: MapPosition,
    ) -> Dict[str, Any]:
        """Get fluid connection points from engine fluidbox."""
        return self._call(
            "get_fluid_connection_points",
            entity_name,
            {"x": position.x, "y": position.y},
        )

    def get_entity_footprint(
        self,
        entity_name: str,
        position: MapPosition,
        direction: Optional[Direction] = None,
    ) -> Dict[str, Any]:
        """Get entity footprint tiles."""
        return self._call(
            "get_entity_footprint",
            entity_name,
            {"x": position.x, "y": position.y},
            direction.value if direction else None,
        )


def _pole_prototype_distances(pole_name: str) -> Tuple[float, float]:
    """Return (maximum_wire_distance, supply_area_distance) for a pole,
    read from the prototype pipeline (PWR-HARDCODE-1 fix).

    These were previously hardcoded per-pole-name dicts scattered across
    get_pole_line/get_pole_coverage_position/get_pole_coverage_plan/
    evaluate_pole_placement, and had drifted from the engine:
    big-electric-pole's wire distance was hardcoded 30.0 while the real
    prototype value is 32. EntityPrototypes.get_prototype() reads the
    filtered factorio-data-dump.json (offline, no live-server dependency —
    the same source ElectricPole.maximum_wire_distance/supply_area_distance
    already use for these exact fields; see
    game/factory/entity/implementations/electric_pole.py).

    Raises:
        ValueError: if the entity isn't a recognized, filtered electric-pole
            prototype (fv_filters.yaml scope) — loud failure instead of a
            silently wrong hardcoded default.
    """
    proto = get_entity_prototypes().get_prototype(pole_name)
    if not proto or "maximum_wire_distance" not in proto or "supply_area_distance" not in proto:
        raise ValueError(
            f"No prototype data for pole {pole_name!r} (maximum_wire_distance/"
            f"supply_area_distance missing). Is it a recognized, filtered "
            f"electric-pole entity? (fv_filters.yaml scope)"
        )
    return proto["maximum_wire_distance"], proto["supply_area_distance"]


# =============================================================================
# READS — pure parsers over the transport; exposed on entity_reference and on
# the real entity objects under identical names (Constitution §6)
# =============================================================================


def offshore_pump_sites(
    client: "PlacementHintsClient",
    near: MapPosition,
    radius: int = 20,
    max_results: int = 20,
) -> List[ConnectionPosition]:
    """Find valid offshore-pump anchors with required orientations.

    Unlike ``remote_view.find_water()``, every returned pair has already
    passed Factorio's live ``surface.can_place_entity`` check. The input
    ``near`` position is only a search center. A returned site is an entity
    placement anchor and may overlap water. Every result therefore includes
    an engine-derived standable ``approach_position`` within build reach.
    Walk there, then place at ``position`` using ``direction`` unchanged.
    Results are ordered by anchor distance from ``near``. If one approach
    cannot be reached from the actor's current region, try the next site.
    """
    if radius < 1:
        raise ValueError("radius must be at least 1")
    if max_results < 1:
        raise ValueError("max_results must be at least 1")
    area = {
        "left_top": {"x": near.x - radius, "y": near.y - radius},
        "right_bottom": {"x": near.x + radius, "y": near.y + radius},
    }
    result = client.get_water_placements(
        "offshore-pump", area, max_results=max_results
    )
    if result.get("error"):
        raise ConnectionQueryError(
            "find_offshore_pump_sites",
            f"area centered at {near}",
            "offshore-pump",
            RuntimeError(str(result["error"])),
        )

    candidates = [
        candidate
        for candidate in result.get("positions", [])
        if candidate.get("valid", True)
    ]
    missing_approach = [
        candidate for candidate in candidates if not candidate.get("approach_position")
    ]
    if missing_approach:
        raise ConnectionQueryError(
            "find_offshore_pump_sites",
            f"area centered at {near}",
            "offshore-pump",
            RuntimeError(
                "placement-hints result omitted approach_position; "
                "Python and fv_placement_hints versions may differ"
            ),
        )

    sites = [
        ConnectionPosition(
            position=MapPosition(
                x=float(candidate["position"]["x"]),
                y=float(candidate["position"]["y"]),
            ),
            direction=Direction(candidate["direction"]),
            approach_position=MapPosition(
                x=float(candidate["approach_position"]["x"]),
                y=float(candidate["approach_position"]["y"]),
            ),
        )
        for candidate in candidates
    ]
    sites.sort(key=lambda site: site.position.distance(near))
    return sites


def connection_positions(
    client: "PlacementHintsClient",
    source_entity: "BaseEntity",
    target_entity_name: str,
    connection_type: ConnectionType,
) -> ConnectionPositionList:
    """Return all valid positions where target can connect to source.

    Uses the fv_placement_hints Lua mod which accesses engine values
    (drop_position, fluidbox) rather than prototype calculations.
    """
    validate_entity_for_connection(source_entity.name, connection_type)

    if connection_type == ConnectionType.ITEM_DROP:
        return _item_drop_positions(client, source_entity, target_entity_name)
    elif connection_type == ConnectionType.FLUID_PIPE:
        return _fluid_pipe_positions(client, source_entity, target_entity_name)
    elif connection_type == ConnectionType.ELECTRIC_WIRE:
        return _electric_wire_positions(client, source_entity, target_entity_name)
    else:
        raise NotImplementedError(
            f"Connection type {connection_type} is not supported by "
            f"get_connection_positions. Supported: ITEM_DROP, FLUID_PIPE, "
            f"ELECTRIC_WIRE. For inserters use "
            f"inserter_placements(client, source, target)."
        )

def _item_drop_positions(
    client: "PlacementHintsClient", source_entity: "BaseEntity", target_entity_name: str
) -> ConnectionPositionList:
    """Get positions where target can receive items from source.

    Uses Lua mod's get_item_drop_connections which uses engine drop_position.
    """
    try:
        result = client.get_item_drop_connections(
            source_entity.name,
            source_entity.position,
            target_entity_name,
            max_results=50,
        )

        positions = result.get("positions", [])
        cues = [
            ConnectionPosition(
                position=MapPosition(x=p["position"]["x"], y=p["position"]["y"]),
                direction=None,
                perpendicular_offset=p.get("perpendicular_offset", 0.0),
            )
            for p in positions
            if p.get("valid", True)
        ]
        # Lua's get_item_drop_connections never emits a `reason` (unlike
        # fluid); synthesize one from `error` (entity-not-found /
        # unknown-prototype cases) or count so an empty result still
        # carries WHY (REASON-1).
        reason = result.get("error")
        if reason is None and not cues:
            reason = (
                f"no valid item-drop position for {target_entity_name} "
                f"near {source_entity.name}'s drop_position "
                f"(count={result.get('count', 0)}; every geometric "
                f"candidate was blocked or none existed)"
            )
        return ConnectionPositionList(
            cues,
            reason=reason,
            source_name=result.get("source_name"),
            search_metadata={
                "count": result.get("count"),
                "target_name": result.get("target_name"),
                "drop_position": result.get("drop_position"),
            },
        )
    except Exception as e:
        logger.error(f"get_item_drop_positions failed: {e}")
        raise ConnectionQueryError(
            "get_item_drop_positions", source_entity.name, target_entity_name, e
        ) from e

def _fluid_pipe_positions(
    client: "PlacementHintsClient", source_entity: "BaseEntity", target_entity_name: str
) -> ConnectionPositionList:
    """Get positions where pipes can connect to source fluidbox.

    Uses Lua mod's get_fluid_connections which uses engine fluidbox.
    """
    try:
        result = client.get_fluid_connections(
            source_entity.name,
            source_entity.position,
            target_entity_name,
            max_results=50,
        )

        positions = result.get("positions", [])
        cues = [
            ConnectionPosition(
                position=MapPosition(x=p["position"]["x"], y=p["position"]["y"]),
                # `is not None`: defines.direction.north == 0 is falsy —
                # a plain truthiness check silently stripped the rotation
                # off every north-facing cue (L4.6 finding, 2026-06-11)
                direction=(Direction(p["direction"])
                           if p.get("direction") is not None else None),
                perpendicular_offset=0.0,
                displaces_character=bool(p.get("displaces_character")),
            )
            for p in positions
            if p.get("valid", True)
        ]
        # Fluid already carries a structured `reason` on zero cues
        # (connections/init.lua:443-457) — surface it instead of
        # discarding it.
        return ConnectionPositionList(
            cues,
            reason=result.get("error") or result.get("reason"),
            source_name=result.get("source_name"),
            search_metadata={
                "count": result.get("count"),
                "target_name": result.get("target_name"),
                "blocked_candidates": result.get("blocked_candidates"),
            },
        )
    except Exception as e:
        logger.error(f"get_fluid_pipe_positions failed: {e}")
        raise ConnectionQueryError(
            "get_fluid_pipe_positions", source_entity.name, target_entity_name, e
        ) from e

def _electric_wire_positions(
    client: "PlacementHintsClient", source_entity: "BaseEntity", target_entity_name: str
) -> ConnectionPositionList:
    """Get positions where a pole can connect to source pole.

    Uses Lua mod's get_pole_connections which uses engine wire_connector.
    """
    try:
        # Define search area around source pole
        search_radius = 20
        search_area = {
            "left_top": {
                "x": source_entity.position.x - search_radius,
                "y": source_entity.position.y - search_radius,
            },
            "right_bottom": {
                "x": source_entity.position.x + search_radius,
                "y": source_entity.position.y + search_radius,
            },
        }

        result = client.get_pole_connections(
            source_entity.name,
            source_entity.position,
            target_entity_name,
            search_area,
            max_results=50,
        )

        positions = result.get("positions", [])
        max_wire_distance = result.get("max_wire_distance", 9.0)

        cues = [
            WireConnectionPosition(
                position=MapPosition(x=p["position"]["x"], y=p["position"]["y"]),
                direction=None,
                perpendicular_offset=p.get("wire_distance", 0.0),
                wire_distance=p.get("wire_distance", 0.0),
                wire_distance_utilization=p.get("wire_distance_utilization", 0.0),
            )
            for p in positions
            if p.get("valid", True)
        ]
        # get_pole_connections never emits a `reason` field at all
        # (unlike fluid) — synthesize one from what it DOES return
        # (max_wire_distance + search extent + count) so a zero-cue
        # electric-wire answer isn't a silent dead end (REASON-1).
        reason = result.get("error")
        if reason is None and not cues:
            reason = (
                f"no valid electric-wire positions for {target_entity_name} "
                f"within max_wire_distance={max_wire_distance} of "
                f"{source_entity.name} (searched ±{search_radius} "
                f"tiles around source; count={result.get('count', 0)} "
                f"candidates passed placement check)"
            )
        return ConnectionPositionList(
            cues,
            reason=reason,
            max_wire_distance=max_wire_distance,
            source_name=result.get("source_name"),
            search_metadata={
                "count": result.get("count"),
                "search_radius": search_radius,
            },
        )
    except Exception as e:
        logger.error(f"get_electric_wire_positions failed: {e}")
        raise ConnectionQueryError(
            "get_electric_wire_positions", source_entity.name, target_entity_name, e
        ) from e


def inserter_placements(
    client: "PlacementHintsClient",
    source_entity: "BaseEntity",
    target_entity: "BaseEntity",
    inserter_name: str = "inserter",
) -> List[Tuple[MapPosition, Direction]]:
    """Find valid inserter positions to transfer items from source to target.

    Uses Lua mod's get_inserter_placements which uses engine positions.
    """
    try:
        result = client.get_inserter_placements(
            source_entity.name,
            source_entity.position,
            target_entity.name,
            target_entity.position,
            inserter_name,
            max_results=20,
        )

        positions = result.get("positions", [])
        return [
            (
                MapPosition(x=p["position"]["x"], y=p["position"]["y"]),
                Direction(p["direction"]) if p.get("direction") else Direction.NORTH,
            )
            for p in positions
            if p.get("valid", True)
        ]
    except Exception as e:
        logger.error(f"get_inserter_placement_positions failed: {e}")
        raise ConnectionQueryError(
            "get_inserter_placement_positions",
            source_entity.name,
            target_entity.name,
            e,
        ) from e


__all__ = [
    "ConnectionQueryError",
    "ConnectionType",
    "EntityValidationError",
    "validate_entity_for_connection",
    "infer_connection_type",
    "ConnectionPosition",
    "WireConnectionPosition",
    "ConnectionPositionList",
    "PlacementHintsClient",
    "ITEM_DROP_ENTITIES",
    "FLUID_PIPE_ENTITIES",
    "RESOURCE_PLACEMENT_ENTITIES",
    "WATER_PLACEMENT_ENTITIES",
    "INSERTER_ENTITIES",
    "ELECTRIC_POLE_ENTITIES",
    "_pole_prototype_distances",
    "offshore_pump_sites",
    "connection_positions",
    "inserter_placements",
]
