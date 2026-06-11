"""Placement Hints Module - Spatial reasoning engine for entity placement.

This module provides pure, context-aware spatial reasoning for entity placement.
It mirrors the visual feedback human players receive in Factorio (green/red tile
highlights, rotation indicators, drag-placement lines) but exposes this as
structured data for the LLM Agent.

Architecture:
- PlacementHintsClient: RCON wrapper for fv_placement_hints Lua mod
- PlacementValidator: Validates placement using the Lua mod
- PlacementHints: Generates validated GhostPlan objects for placement
- GhostPlan: Validated plan ready for commitment via GhostBuilder

The fv_placement_hints Lua mod provides low-level primitives using engine values
(drop_position, fluidbox, wire_connector). This Python module provides high-level
planning algorithms that orchestrate those primitives.

No Side Effects: This module never mutates game state (validation only).
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Dict, Any, Tuple, FrozenSet, TYPE_CHECKING
import logging
import uuid
import time
import json

from FactoryVerse.game.factory.types import MapPosition, Direction

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
    INSERTER_REACH: Inserters pick from ground/belts/entities and drop to ground/belts/entities.
    """

    ITEM_DROP = "item_drop"  # Mining drill -> Chest/Belt (direct push, no inserters)
    FLUID_PIPE = "fluid_pipe"  # Pipe -> Machine/Pipe
    INSERTER_REACH = "inserter"  # Inserter -> Source/Target (picks from ground/belts/entities, NOT drills)
    BELT_FLOW = "belt_flow"  # Belt -> Belt
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


@dataclass
class ConnectionPosition:
    """A valid position for placing a target entity to connect to a source entity.

    Results are pre-sorted by alignment quality - the first position is the best.
    Just use positions[0] for optimal placement.

    Attributes:
        position: The map position where the target entity should be placed.
        direction: The direction the target entity should face (if applicable).
        perpendicular_offset: Alignment quality metric - lower is better (0.0 = perfectly aligned).
    """

    position: MapPosition
    direction: Optional[Direction]
    perpendicular_offset: float = 0.0  # Lower = better alignment

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


@dataclass
class GhostPlan:
    """A complete plan ready for commitment.

    Plans are validated using PlacementValidator.validate_batch() before
    being returned. All returned positions are pre-validated (valid=True).
    """

    entity_name: str
    positions: List[Tuple[MapPosition, Optional[Direction]]]
    label: str
    description: str
    valid: bool

    def validate(self, validator: "PlacementValidator") -> bool:
        """Re-validate all positions in the plan."""
        positions_only = [pos for pos, _ in self.positions]
        directions = [dir for _, dir in self.positions]
        results = validator.validate_batch(
            self.entity_name, positions_only, directions=directions, ghost=True
        )
        self.valid = all(results)
        return self.valid


@dataclass
class PolePlacementResult:
    """Result of dry-run pole placement evaluation."""

    position: MapPosition
    pole_name: str
    supply_area_distance: float
    entities_powered: List["BaseEntity"]
    entities_powered_count: int
    source_pole: Optional["BaseEntity"]
    connects_to_source: bool
    distance_to_source: Optional[float]
    connected_poles: List["BaseEntity"]
    connected_poles_count: int
    can_receive_power: bool
    power_path: Optional[List["BaseEntity"]]
    power_source: Optional["BaseEntity"]
    is_valid_placement: bool
    placement_error: Optional[str]
    maximum_wire_distance: float


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


# =============================================================================
# PLACEMENT VALIDATOR
# =============================================================================


class PlacementValidator:
    """Validates entity placement using the fv_placement_hints Lua mod.

    Role in Tiered Placement System:
    - Tier 1 (Plan): Validates all positions in a GhostPlan before committing
    - Tier 2 (Ghost): Ghosts are already validated
    - Tier 3 (Built): No additional validation needed
    """

    def __init__(self, rcon_handler: "RconHandler", batch_size: int = 250):
        """Initialize validator with RCON handler."""
        self._client = PlacementHintsClient(rcon_handler)
        self.batch_size = batch_size

    def validate_placement(
        self,
        entity_name: str,
        position: MapPosition,
        direction: Optional[Direction] = None,
        ghost: bool = False,
    ) -> bool:
        """Check if an entity can be placed at a position."""
        try:
            return self._client.validate_placement(entity_name, position, direction, ghost)
        except Exception as e:
            logger.error(f"Placement validation failed: {e}")
            return False

    def validate_batch(
        self,
        entity_name: str,
        positions: List[MapPosition],
        directions: Optional[List[Optional[Direction]]] = None,
        ghost: bool = False,
    ) -> List[bool]:
        """Validate multiple positions efficiently."""
        if not positions:
            return []

        if directions is None:
            directions = [None] * len(positions)

        if len(directions) != len(positions):
            raise ValueError("Directions list must match positions list length")

        # Split into batches if needed
        if len(positions) > self.batch_size:
            results = []
            for i in range(0, len(positions), self.batch_size):
                batch_positions = positions[i:i + self.batch_size]
                batch_directions = directions[i:i + self.batch_size]
                try:
                    batch_results = self._client.validate_positions(
                        entity_name, batch_positions, batch_directions, ghost
                    )
                    results.extend(batch_results)
                except Exception as e:
                    logger.error(f"Batch validation failed: {e}")
                    results.extend([False] * len(batch_positions))
            return results
        else:
            try:
                return self._client.validate_positions(entity_name, positions, directions, ghost)
            except Exception as e:
                logger.error(f"Batch validation failed: {e}")
                return [False] * len(positions)

    def validate_line(
        self,
        entity_name: str,
        start: MapPosition,
        end: MapPosition,
        direction: Optional[Direction] = None,
        ghost: bool = False,
    ) -> List[Tuple[MapPosition, bool]]:
        """Validate positions along a line."""
        positions = self._calculate_line_positions(start, end)
        results = self.validate_batch(
            entity_name, positions, directions=[direction] * len(positions), ghost=ghost
        )
        return list(zip(positions, results))

    def validate_grid(
        self,
        entity_name: str,
        top_left: MapPosition,
        bottom_right: MapPosition,
        direction: Optional[Direction] = None,
        ghost: bool = False,
    ) -> Dict[MapPosition, bool]:
        """Validate positions in a rectangular grid."""
        positions = []
        for x in range(int(top_left.x), int(bottom_right.x) + 1):
            for y in range(int(top_left.y), int(bottom_right.y) + 1):
                positions.append(MapPosition(x=float(x), y=float(y)))

        results = self.validate_batch(
            entity_name, positions, directions=[direction] * len(positions), ghost=ghost
        )
        return dict(zip(positions, results))

    @staticmethod
    def _calculate_line_positions(start: MapPosition, end: MapPosition) -> List[MapPosition]:
        """Calculate positions along a line from start to end."""
        positions = []
        dx = end.x - start.x
        dy = end.y - start.y
        abs_dx = abs(dx)
        abs_dy = abs(dy)

        if abs_dx == 0:
            step = 1 if dy > 0 else -1
            for y in range(int(start.y), int(end.y) + step, step):
                positions.append(MapPosition(x=start.x, y=float(y)))
        elif abs_dy == 0:
            step = 1 if dx > 0 else -1
            for x in range(int(start.x), int(end.x) + step, step):
                positions.append(MapPosition(x=float(x), y=start.y))
        else:
            max_steps = max(abs_dx, abs_dy)
            steps = int(max_steps) + 1
            for i in range(steps):
                t = i / max_steps if max_steps > 0 else 0
                x = start.x + t * dx
                y = start.y + t * dy
                positions.append(MapPosition(x=x, y=y))

        return positions


# =============================================================================
# PLACEMENT HINTS
# =============================================================================


class PlacementHints:
    """Generates validated placement plans for entity placement.

    Provides pure, context-aware spatial reasoning:
    - get_placement_line: Calculate lines of entities (belts, pipes, walls)
    - get_connection_positions: Solve connection puzzles (pipes to machines, drills to chests)

    Uses the fv_placement_hints Lua mod for connection solving (engine values)
    and keeps high-level planning algorithms in Python.
    """

    def __init__(self, rcon_handler: "RconHandler"):
        """Initialize placement hints."""
        self._rcon = rcon_handler
        self._client = PlacementHintsClient(rcon_handler)
        self._validator = PlacementValidator(rcon_handler)

    @property
    def validator(self) -> PlacementValidator:
        """Expose validator for direct access."""
        return self._validator

    def is_buildable(
        self,
        left_top: MapPosition,
        right_bottom: MapPosition,
        entity_name: str = "wooden-chest",
    ) -> Dict[str, Any]:
        """Check whether an area is buildable land WITHOUT placing anything.

        Terrain affordance (AFFORD-1): probes every integer tile in the area
        with a non-mutating placement validation (engine rules, manual
        build-check). Never use real place/pickup calls as a terrain scanner.

        Args:
            left_top: Top-left corner of the area
            right_bottom: Bottom-right corner (exclusive)
            entity_name: 1x1 entity used as the probe (default wooden-chest)

        Returns:
            {'all_buildable': bool, 'buildable_count': int, 'total': int,
             'blocked_positions': [{'x','y'} up to 25]}

        Raises:
            ValueError: empty area, or area over 1600 tiles (probe sub-areas)
        """
        import math

        x0, x1 = math.floor(left_top.x), math.ceil(right_bottom.x)
        y0, y1 = math.floor(left_top.y), math.ceil(right_bottom.y)
        total = (x1 - x0) * (y1 - y0)
        if total <= 0:
            raise ValueError(
                f"Empty area: ({left_top.x},{left_top.y})..({right_bottom.x},{right_bottom.y})"
            )
        if total > 1600:
            raise ValueError(
                f"Area is {total} tiles; max 1600 per call — probe sub-areas"
            )

        positions = [
            MapPosition(x=x + 0.5, y=y + 0.5)
            for y in range(y0, y1)
            for x in range(x0, x1)
        ]
        results = self._client.validate_positions(entity_name, positions)
        blocked = [p for p, ok in zip(positions, results) if not ok]
        return {
            "all_buildable": not blocked,
            "buildable_count": total - len(blocked),
            "total": total,
            "blocked_positions": [{"x": p.x, "y": p.y} for p in blocked[:25]],
        }

    # =========================================================================
    # LINE PLANNING
    # =========================================================================

    def get_placement_line(
        self,
        entity_name: str,
        start: MapPosition,
        end: MapPosition,
        width: int = 1,
        validate: bool = True,
    ) -> GhostPlan:
        """Calculate a line of entities from start to end.

        Infers direction from drag vector for directional entities.
        """
        positions = self._validator._calculate_line_positions(start, end)

        if not positions:
            raise ValueError("Start and end positions must be different")

        dx = end.x - start.x
        dy = end.y - start.y

        # Infer direction from drag vector
        direction = None
        if abs(dx) > abs(dy):
            direction = Direction.EAST if dx > 0 else Direction.WEST
        elif abs(dy) > abs(dx):
            direction = Direction.SOUTH if dy > 0 else Direction.NORTH
        else:
            direction = Direction.EAST

        requires_direction = self._entity_requires_direction(entity_name)

        if requires_direction:
            position_pairs = [(pos, direction) for pos in positions]
        else:
            position_pairs = [(pos, None) for pos in positions]

        label = self._generate_label(entity_name, "line")
        description = f"Line of {len(positions)} {entity_name} from ({start.x:.1f}, {start.y:.1f}) to ({end.x:.1f}, {end.y:.1f})"

        plan = GhostPlan(
            entity_name=entity_name,
            positions=position_pairs,
            label=label,
            description=description,
            valid=False,
        )

        if validate:
            plan.validate(self._validator)
        else:
            plan.valid = True

        return plan

    # =========================================================================
    # CONNECTION SOLVING - Uses Lua mod for engine values
    # =========================================================================

    def get_connection_positions(
        self,
        source_entity: "BaseEntity",
        target_entity_name: str,
        connection_type: ConnectionType,
    ) -> List[ConnectionPosition]:
        """Return all valid positions where target can connect to source.

        Uses the fv_placement_hints Lua mod which accesses engine values
        (drop_position, fluidbox) rather than prototype calculations.
        """
        validate_entity_for_connection(source_entity.name, connection_type)

        if connection_type == ConnectionType.ITEM_DROP:
            return self._get_item_drop_positions(source_entity, target_entity_name)
        elif connection_type == ConnectionType.FLUID_PIPE:
            return self._get_fluid_pipe_positions(source_entity, target_entity_name)
        elif connection_type == ConnectionType.ELECTRIC_WIRE:
            return self._get_electric_wire_positions(source_entity, target_entity_name)
        else:
            raise NotImplementedError(
                f"Connection type {connection_type} is not supported by "
                f"get_connection_positions. Supported: ITEM_DROP, FLUID_PIPE, "
                f"ELECTRIC_WIRE. For inserters use "
                f"get_inserter_placement_positions(source, target)."
            )

    def _get_item_drop_positions(
        self, source_entity: "BaseEntity", target_entity_name: str
    ) -> List[ConnectionPosition]:
        """Get positions where target can receive items from source.

        Uses Lua mod's get_item_drop_connections which uses engine drop_position.
        """
        try:
            result = self._client.get_item_drop_connections(
                source_entity.name,
                source_entity.position,
                target_entity_name,
                max_results=50,
            )

            positions = result.get("positions", [])
            return [
                ConnectionPosition(
                    position=MapPosition(x=p["position"]["x"], y=p["position"]["y"]),
                    direction=None,
                    perpendicular_offset=p.get("perpendicular_offset", 0.0),
                )
                for p in positions
                if p.get("valid", True)
            ]
        except Exception as e:
            logger.error(f"get_item_drop_positions failed: {e}")
            raise ConnectionQueryError(
                "get_item_drop_positions", source_entity.name, target_entity_name, e
            ) from e

    def _get_fluid_pipe_positions(
        self, source_entity: "BaseEntity", target_entity_name: str
    ) -> List[ConnectionPosition]:
        """Get positions where pipes can connect to source fluidbox.

        Uses Lua mod's get_fluid_connections which uses engine fluidbox.
        """
        try:
            result = self._client.get_fluid_connections(
                source_entity.name,
                source_entity.position,
                target_entity_name,
                max_results=50,
            )

            positions = result.get("positions", [])
            return [
                ConnectionPosition(
                    position=MapPosition(x=p["position"]["x"], y=p["position"]["y"]),
                    # `is not None`: defines.direction.north == 0 is falsy —
                    # a plain truthiness check silently stripped the rotation
                    # off every north-facing cue (L4.6 finding, 2026-06-11)
                    direction=(Direction(p["direction"])
                               if p.get("direction") is not None else None),
                    perpendicular_offset=0.0,
                )
                for p in positions
                if p.get("valid", True)
            ]
        except Exception as e:
            logger.error(f"get_fluid_pipe_positions failed: {e}")
            raise ConnectionQueryError(
                "get_fluid_pipe_positions", source_entity.name, target_entity_name, e
            ) from e

    def _get_electric_wire_positions(
        self, source_entity: "BaseEntity", target_entity_name: str
    ) -> List[WireConnectionPosition]:
        """Get positions where a pole can connect to source pole.

        Uses Lua mod's get_pole_connections which uses engine wire_connector.
        """
        try:
            # Define search area around source pole
            search_area = {
                "left_top": {
                    "x": source_entity.position.x - 20,
                    "y": source_entity.position.y - 20,
                },
                "right_bottom": {
                    "x": source_entity.position.x + 20,
                    "y": source_entity.position.y + 20,
                },
            }

            result = self._client.get_pole_connections(
                source_entity.name,
                source_entity.position,
                target_entity_name,
                search_area,
                max_results=50,
            )

            positions = result.get("positions", [])
            max_wire_distance = result.get("max_wire_distance", 9.0)

            return [
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
        except Exception as e:
            logger.error(f"get_electric_wire_positions failed: {e}")
            raise ConnectionQueryError(
                "get_electric_wire_positions", source_entity.name, target_entity_name, e
            ) from e

    def get_inserter_placement_positions(
        self,
        source_entity: "BaseEntity",
        target_entity: "BaseEntity",
        inserter_name: str = "inserter",
    ) -> List[Tuple[MapPosition, Direction]]:
        """Find valid inserter positions to transfer items from source to target.

        Uses Lua mod's get_inserter_placements which uses engine positions.
        """
        try:
            result = self._client.get_inserter_placements(
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

    # =========================================================================
    # POLE PLANNING - High-level algorithms using Lua primitives
    # =========================================================================

    def get_pole_line(
        self,
        start: MapPosition,
        end: MapPosition,
        pole_name: str = "medium-electric-pole",
        validate: bool = True,
    ) -> GhostPlan:
        """Plan a line of poles at maximum wire distance intervals.

        Uses Lua mod to get pole prototype info (wire distance).
        """
        # Get pole info from Lua mod
        try:
            cue = self._client.get_placement_cue(pole_name, start)
            # Wire distance not directly in cue, use default based on pole type
            max_wire_distance = {
                "small-electric-pole": 7.5,
                "medium-electric-pole": 9.0,
                "big-electric-pole": 30.0,
                "substation": 18.0,
            }.get(pole_name, 9.0)
        except Exception:
            max_wire_distance = 9.0

        dx = end.x - start.x
        dy = end.y - start.y
        distance = (dx**2 + dy**2) ** 0.5

        if distance == 0:
            positions = [(start, None)]
        else:
            num_segments = max(1, int(distance / max_wire_distance) + 1)
            positions = []
            for i in range(num_segments + 1):
                t = i / num_segments
                pos = MapPosition(x=start.x + t * dx, y=start.y + t * dy)
                positions.append((pos, None))

        label = self._generate_label(pole_name, "pole_line")
        description = f"Line of {len(positions)} {pole_name}"

        plan = GhostPlan(
            entity_name=pole_name,
            positions=positions,
            label=label,
            description=description,
            valid=False,
        )

        if validate:
            plan.validate(self._validator)
        else:
            plan.valid = True

        return plan

    def get_pole_coverage_position(
        self,
        entities_to_power: List["BaseEntity"],
        pole_name: str = "medium-electric-pole",
    ) -> Optional[MapPosition]:
        """Find a single pole position that covers ALL given entities."""
        if not entities_to_power:
            return None

        supply_distance = {
            "small-electric-pole": 2.5,
            "medium-electric-pole": 3.5,
            "big-electric-pole": 2.0,
            "substation": 9.0,
        }.get(pole_name, 3.5)

        min_x = min(e.position.x for e in entities_to_power)
        max_x = max(e.position.x for e in entities_to_power)
        min_y = min(e.position.y for e in entities_to_power)
        max_y = max(e.position.y for e in entities_to_power)

        spread_x = max_x - min_x
        spread_y = max_y - min_y
        supply_diameter = supply_distance * 2

        if spread_x > supply_diameter or spread_y > supply_diameter:
            return None

        center = MapPosition(x=(min_x + max_x) / 2, y=(min_y + max_y) / 2)

        if self._validator.validate_placement(pole_name, center, None, ghost=True):
            return center

        # Try snapping to tile center
        snapped = MapPosition(
            x=int(center.x) + 0.5,
            y=int(center.y) + 0.5,
        )
        if self._validator.validate_placement(pole_name, snapped, None, ghost=True):
            return snapped

        return None

    def get_pole_coverage_plan(
        self,
        entities_to_power: List["BaseEntity"],
        pole_name: str = "medium-electric-pole",
    ) -> Tuple[GhostPlan, List["BaseEntity"]]:
        """Find minimum poles to cover all entities using greedy set cover."""
        if not entities_to_power:
            return GhostPlan(
                entity_name=pole_name,
                positions=[],
                label=self._generate_label(pole_name, "coverage"),
                description="Empty coverage plan",
                valid=True,
            ), []

        supply_distance = {
            "small-electric-pole": 2.5,
            "medium-electric-pole": 3.5,
            "big-electric-pole": 2.0,
            "substation": 9.0,
        }.get(pole_name, 3.5)

        uncovered = set(range(len(entities_to_power)))
        pole_positions: List[Tuple[MapPosition, Optional[Direction]]] = []

        while uncovered:
            remaining = [entities_to_power[i] for i in uncovered]
            center = MapPosition(
                x=sum(e.position.x for e in remaining) / len(remaining),
                y=sum(e.position.y for e in remaining) / len(remaining),
            )

            covered = set()
            for idx in uncovered:
                entity = entities_to_power[idx]
                if center.distance(entity.position) <= supply_distance:
                    covered.add(idx)

            if covered and self._validator.validate_placement(pole_name, center, None, ghost=True):
                pole_positions.append((center, None))
                uncovered -= covered
            else:
                break

        uncovered_entities = [entities_to_power[i] for i in uncovered]
        label = self._generate_label(pole_name, "coverage")
        description = f"Coverage plan: {len(pole_positions)} {pole_name}"

        plan = GhostPlan(
            entity_name=pole_name,
            positions=pole_positions,
            label=label,
            description=description,
            valid=True,
        )

        return plan, uncovered_entities

    def get_underground_segment(
        self,
        entity_name: str,
        start: MapPosition,
        end: MapPosition,
        direction: Direction,
    ) -> GhostPlan:
        """Plan an underground segment (belt or pipe) between two points."""
        max_distance = {
            "underground-belt": 4,
            "fast-underground-belt": 6,
            "express-underground-belt": 8,
            "pipe-to-ground": 10,
        }.get(entity_name, 10)

        dx = end.x - start.x
        dy = end.y - start.y
        distance = max(abs(dx), abs(dy))

        if distance > max_distance:
            raise ValueError(
                f"Distance {distance:.1f} exceeds max {max_distance} for {entity_name}"
            )

        opposite_dir = {
            Direction.NORTH: Direction.SOUTH,
            Direction.SOUTH: Direction.NORTH,
            Direction.EAST: Direction.WEST,
            Direction.WEST: Direction.EAST,
        }

        positions: List[Tuple[MapPosition, Optional[Direction]]] = [
            (start, direction),
            (end, opposite_dir.get(direction, direction)),
        ]

        label = self._generate_label(entity_name, "underground")
        description = f"Underground {entity_name}"

        plan = GhostPlan(
            entity_name=entity_name,
            positions=positions,
            label=label,
            description=description,
            valid=False,
        )

        plan.validate(self._validator)
        return plan

    # =========================================================================
    # POLE EVALUATION
    # =========================================================================

    def evaluate_pole_placement(
        self,
        position: MapPosition,
        pole_name: str,
        source_pole: Optional["BaseEntity"] = None,
        reachable_view: Optional[Any] = None,
    ) -> PolePlacementResult:
        """Evaluate a pole placement position without placing anything (dry run)."""
        supply_area_distance = {
            "small-electric-pole": 2.5,
            "medium-electric-pole": 3.5,
            "big-electric-pole": 2.0,
            "substation": 9.0,
        }.get(pole_name, 3.5)

        maximum_wire_distance = {
            "small-electric-pole": 7.5,
            "medium-electric-pole": 9.0,
            "big-electric-pole": 30.0,
            "substation": 18.0,
        }.get(pole_name, 9.0)

        is_valid = self._validator.validate_placement(pole_name, position, None, ghost=True)
        placement_error = None if is_valid else "Cannot place pole at this position"

        result = PolePlacementResult(
            position=position,
            pole_name=pole_name,
            supply_area_distance=supply_area_distance,
            entities_powered=[],
            entities_powered_count=0,
            source_pole=source_pole,
            connects_to_source=False,
            distance_to_source=None,
            connected_poles=[],
            connected_poles_count=0,
            can_receive_power=False,
            power_path=None,
            power_source=None,
            is_valid_placement=is_valid,
            placement_error=placement_error,
            maximum_wire_distance=maximum_wire_distance,
        )

        if source_pole:
            distance = position.distance(source_pole.position)
            result.distance_to_source = distance
            result.connects_to_source = distance <= maximum_wire_distance

        if not is_valid or reachable_view is None:
            return result

        # Find entities within supply area
        all_entities = reachable_view.get_entities()

        entities_powered = []
        for entity in all_entities:
            if entity.name in ELECTRIC_POLE_ENTITIES or getattr(entity, 'is_ghost', False):
                continue
            if position.distance(entity.position) <= supply_area_distance:
                entities_powered.append(entity)

        result.entities_powered = entities_powered
        result.entities_powered_count = len(entities_powered)

        # Find connected poles
        connected_poles = []
        for entity in all_entities:
            if entity.name in ELECTRIC_POLE_ENTITIES and not getattr(entity, 'is_ghost', False):
                dist = position.distance(entity.position)
                if 0.01 < dist <= maximum_wire_distance:
                    connected_poles.append(entity)

        connected_poles.sort(key=lambda p: position.distance(p.position))
        result.connected_poles = connected_poles
        result.connected_poles_count = len(connected_poles)

        # Power path tracing would require more complex logic
        # For now, assume can receive power if connected to any pole
        result.can_receive_power = len(connected_poles) > 0

        return result

    # =========================================================================
    # HELPERS
    # =========================================================================

    @staticmethod
    def _entity_requires_direction(entity_name: str) -> bool:
        """Check if entity requires a direction for placement."""
        directional_types = [
            "transport-belt", "fast-transport-belt", "express-transport-belt",
            "inserter", "long-handed-inserter", "fast-inserter",
            "assembling-machine", "stone-furnace", "steel-furnace", "electric-furnace",
            "electric-mining-drill", "burner-mining-drill", "pumpjack",
            "boiler", "steam-engine", "offshore-pump",
        ]
        return entity_name in directional_types

    @staticmethod
    def _generate_label(entity_name: str, plan_type: str) -> str:
        """Generate a unique label for a ghost plan."""
        timestamp = int(time.time())
        short_hash = str(uuid.uuid4())[:8]
        return f"plan:{entity_name}:{plan_type}:{timestamp}:{short_hash}"

    @staticmethod
    def _rotate_vector(vec: Tuple[float, float], direction: Direction) -> Tuple[float, float]:
        """Rotate a vector based on direction (NORTH = no rotation)."""
        vx, vy = vec
        if direction == Direction.NORTH:
            return (vx, vy)
        elif direction == Direction.EAST:
            return (-vy, vx)
        elif direction == Direction.SOUTH:
            return (-vx, -vy)
        elif direction == Direction.WEST:
            return (vy, -vx)
        return (vx, vy)
