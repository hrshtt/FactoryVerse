"""Placement Hints Module - Spatial reasoning engine for entity placement.

This module provides pure, context-aware spatial reasoning for entity placement.
It mirrors the visual feedback human players receive in Factorio (green/red tile
highlights, rotation indicators, drag-placement lines) but exposes this as
structured data for the LLM Agent.

Core Philosophy: "Query the possibility space, validate it, then commit to the plan."

Architecture:
- PlacementValidator: Validates placement using Factorio's can_place_entity API
- PlacementHints: Generates validated GhostPlan objects for placement
- GhostPlan: Validated plan ready for commitment via GhostBuilder

No Side Effects: This module never mutates game state (validation only).
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Dict, Any, Tuple, Union, FrozenSet, TYPE_CHECKING
import logging
import uuid
import time
import json
import re

from FactoryVerse.factory.types import MapPosition, Direction

if TYPE_CHECKING:
    from FactoryVerse.agent.infra.rcon_handler import RconHandler
    from FactoryVerse.factory.entity.base_entity import BaseEntity

logger = logging.getLogger(__name__)


# =============================================================================
# DATA STRUCTURES
# =============================================================================


class ConnectionType(Enum):
    """Connection types for solving entity placement puzzles.

    Used to determine valid connection positions between entities.
    """

    ITEM_DROP = "item_drop"  # Mining drill -> Chest/Belt
    FLUID_PIPE = "fluid_pipe"  # Pipe -> Machine/Pipe
    INSERTER_REACH = "inserter"  # Inserter -> Source/Target
    BELT_FLOW = "belt_flow"  # Belt -> Belt
    ELECTRIC_WIRE = "wire"  # Pole -> Pole


# =============================================================================
# ENTITY METADATA - Documents and validates applicable entities per method
# =============================================================================

# Entities that support ITEM_DROP connection type (mining drills with output vector)
ITEM_DROP_ENTITIES: FrozenSet[str] = frozenset(
    [
        "electric-mining-drill",
        "burner-mining-drill",
    ]
)

# Entities that support FLUID_PIPE connection type (entities with fluidboxes)
FLUID_PIPE_ENTITIES: FrozenSet[str] = frozenset(
    [
        # Generators
        "boiler",
        "steam-engine",
        "steam-turbine",
        # Fluid machines
        "chemical-plant",
        "oil-refinery",
        "pumpjack",
        # Infrastructure
        "pipe",
        "pipe-to-ground",
        "pump",
        "offshore-pump",
        "storage-tank",
    ]
)

# Entities that require resource tiles for placement (via Lua get_placement_cues)
RESOURCE_PLACEMENT_ENTITIES: FrozenSet[str] = frozenset(
    [
        "electric-mining-drill",
        "burner-mining-drill",
        "pumpjack",
    ]
)

# Entities that require water tiles for placement
WATER_PLACEMENT_ENTITIES: FrozenSet[str] = frozenset(
    [
        "offshore-pump",
    ]
)

# Entities that support INSERTER_REACH connection type (all inserter types)
INSERTER_ENTITIES: FrozenSet[str] = frozenset(
    [
        "inserter",
        "long-handed-inserter",
        "fast-inserter",
        "filter-inserter",
        "stack-inserter",
        "stack-filter-inserter",
        "bulk-inserter",
        "burner-inserter",
    ]
)

# Entities that support ELECTRIC_WIRE connection type (all pole types)
ELECTRIC_POLE_ENTITIES: FrozenSet[str] = frozenset(
    [
        "small-electric-pole",
        "medium-electric-pole",
        "big-electric-pole",
        "substation",
    ]
)


class EntityValidationError(ValueError):
    """Raised when a placement method is called with an incompatible entity.

    This error indicates that the entity provided does not support the
    requested connection type or placement operation.
    """

    pass


def validate_entity_for_connection(
    entity_name: str,
    connection_type: ConnectionType,
) -> None:
    """Validate that an entity is compatible with a connection type.

    Args:
        entity_name: The prototype name of the entity
        connection_type: The type of connection being established

    Raises:
        EntityValidationError: If entity is not compatible with connection_type
    """
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
class PolePlacementResult:
    """Result of dry-run pole placement evaluation.
    
    Provides rich feedback about what would happen if a pole were placed
    at a position, without actually placing anything (not even a ghost).
    """
    
    position: MapPosition
    pole_name: str
    
    # Supply area
    supply_area_distance: float
    entities_powered: List["BaseEntity"]  # Entities within supply area
    entities_powered_count: int
    
    # Connectivity (if source_pole provided)
    source_pole: Optional["BaseEntity"]  # The source pole that was checked against
    connects_to_source: bool  # True if within wire distance of source_pole
    distance_to_source: Optional[float]  # Distance to source_pole if provided
    
    # All nearby poles
    connected_poles: List["BaseEntity"]  # All poles within maximum_wire_distance
    connected_poles_count: int
    
    # Power network analysis (traces through connected poles)
    can_receive_power: bool  # True if connects to power source (via any connected pole)
    power_path: Optional[List["BaseEntity"]]  # Path: [this_pole, ...connected_poles..., power_source]
    power_source: Optional["BaseEntity"]  # Nearest power source
    
    # Placement validation
    is_valid_placement: bool
    placement_error: Optional[str]  # Why placement failed, if any
    
    # Metadata
    maximum_wire_distance: float


@dataclass
class ConnectionPosition:
    """A valid position for placing a target entity to connect to a source entity.

    Returned by `get_connection_positions()` to provide structured placement hints
    with alignment information for optimal positioning.
    """

    position: MapPosition  # Position where target entity can be placed
    direction: Optional[Direction]  # Direction for placement (None if not required)
    perpendicular_offset: float  # Distance from source entity perpendicular to flow direction
    # Lower values indicate better alignment (0.0 = perfectly aligned)

    def __post_init__(self):
        """Validate perpendicular_offset is non-negative."""
        if self.perpendicular_offset < 0:
            raise ValueError("perpendicular_offset must be non-negative")


@dataclass
class WireConnectionPosition(ConnectionPosition):
    """Connection position for ELECTRIC_WIRE connections (pole to pole).
    
    Extends ConnectionPosition with wire-specific distance and utilization metrics.
    """

    wire_distance: float  # Actual distance to source pole (in tiles)
    wire_distance_utilization: float  # Ratio of distance / maximum_wire_distance (0.0 to 1.0+)
    # Typically 0.0-1.0 for valid positions within max wire distance

    def __post_init__(self):
        """Validate wire-specific fields."""
        super().__post_init__()
        if self.wire_distance < 0:
            raise ValueError("wire_distance must be non-negative")
        if self.wire_distance_utilization < 0:
            raise ValueError("wire_distance_utilization must be non-negative")


@dataclass
class GhostPlan:
    """A complete plan ready for commitment.

    Plans are validated using PlacementValidator.validate_batch() before
    being returned. This ensures all positions are valid before any state
    mutation occurs.

    Plans returned from PlacementHints methods are pre-validated (valid=True).
    Agents can re-validate plans if they modify the map before committing.
    """

    entity_name: str  # Entity type for all placements in this plan
    positions: List[
        Tuple[MapPosition, Optional[Direction]]
    ]  # List of (position, direction) tuples
    label: str  # The label to be applied to all ghosts (e.g., "belt_line:123")
    description: str  # Human/LLM readable description of the plan
    valid: bool  # Whether all positions have been validated (True if pre-validated by PlacementHints)

    def validate(self, validator: "PlacementValidator") -> bool:
        """Re-validate all positions in the plan.

        Useful if the agent has modified the map (placed other entities, mined resources)
        after receiving the plan. Updates self.valid and returns the result.

        Args:
            validator: PlacementValidator instance to use for validation

        Returns:
            True if all positions are valid, False otherwise
        """
        positions_only = [pos for pos, _ in self.positions]
        directions = [dir for _, dir in self.positions]

        # Use batch validation for efficiency
        results = validator.validate_batch(
            self.entity_name, positions_only, directions=directions, ghost=True
        )

        self.valid = all(results)
        return self.valid


# =============================================================================
# PLACEMENT VALIDATOR
# =============================================================================


class PlacementValidator:
    """Validates entity placement using Factorio's native can_place_entity API.

    Provides efficient batch validation with compressed coordinate representation
    to avoid stalling the simulation.

    Role in Tiered Placement System:
    - Tier 1 (Plan): Validates all positions in a GhostPlan before committing to ghosts
    - Tier 2 (Ghost): Ghosts are already validated (plan was checked)
    - Tier 3 (Built): No additional validation needed (ghosts were valid, resources available)
    """

    def __init__(self, rcon_handler: "RconHandler", batch_size: int = 250):
        """Initialize validator with RCON handler and batch size.

        Args:
            rcon_handler: RCON handler for executing Lua commands
            batch_size: Maximum number of positions to validate in a single RCON call
        """
        self._rcon = rcon_handler
        self.batch_size = batch_size

    def validate_placement(
        self,
        entity_name: str,
        position: MapPosition,
        direction: Optional[Direction] = None,
        ghost: bool = False,
    ) -> bool:
        """Check if an entity can be placed at a position.

        Uses Factorio's surface.can_place_entity() with correct build_check_type.

        Args:
            entity_name: Entity prototype name
            position: Position to check
            direction: Optional direction (for directional entities)
            ghost: If True, uses manual_ghost build_check_type, else manual

        Returns:
            True if entity can be placed, False otherwise
        """
        build_check_type = "manual_ghost" if ghost else "manual"

        # Build Lua command
        lua_code = f"""
local surface = game.surfaces[1]
local params = {{
    name = "{entity_name}",
    position = {{x = {position.x}, y = {position.y}}},
    force = "player",
    build_check_type = defines.build_check_type.{build_check_type}
}}
"""

        if direction is not None:
            lua_code += f"params.direction = {direction.value}\n"

        lua_code += "rcon.print(tostring(surface.can_place_entity(params)))"

        try:
            result = self._rcon.execute(lua_code)
            return result and result.strip().lower() == "true"
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
        """Validate multiple positions efficiently using compressed coordinate representation.

        Automatically batches large requests to avoid stalling the simulation.

        Args:
            entity_name: Entity prototype name
            positions: List of positions to validate
            directions: Optional list of directions (one per position)
            ghost: If True, uses manual_ghost build_check_type, else manual

        Returns:
            List of booleans matching input positions order
        """
        if not positions:
            return []

        # If no directions provided, use None for all
        if directions is None:
            directions = [None] * len(positions)

        # Ensure directions list matches positions length
        if len(directions) != len(positions):
            raise ValueError("Directions list must match positions list length")

        # Split into batches if needed
        if len(positions) > self.batch_size:
            results = []
            for i in range(0, len(positions), self.batch_size):
                batch_positions = positions[i : i + self.batch_size]
                batch_directions = directions[i : i + self.batch_size]
                batch_results = self._validate_batch_internal(
                    entity_name, batch_positions, batch_directions, ghost
                )
                results.extend(batch_results)
            return results
        else:
            return self._validate_batch_internal(
                entity_name, positions, directions, ghost
            )

    def _validate_batch_internal(
        self,
        entity_name: str,
        positions: List[MapPosition],
        directions: List[Optional[Direction]],
        ghost: bool,
    ) -> List[bool]:
        """Internal batch validation implementation."""
        build_check_type = "manual_ghost" if ghost else "manual"

        # Build Lua command for batch validation
        lua_code = f"""
local surface = game.surfaces[1]
local entity_name = "{entity_name}"
local build_check_type = defines.build_check_type.{build_check_type}
local force = "player"
local results = {{}}

"""

        # Add each position check
        for i, (pos, direction) in enumerate(zip(positions, directions)):
            lua_code += f"""
local params_{i} = {{
    name = entity_name,
    position = {{x = {pos.x}, y = {pos.y}}},
    direction = {direction.value if direction else "nil"},
    force = force,
    build_check_type = build_check_type
}}
results[{i + 1}] = surface.can_place_entity(params_{i})
"""

        lua_code += "\nrcon.print(helpers.table_to_json(results))"

        try:
            result = self._rcon.execute(lua_code)
            if not result:
                return [False] * len(positions)

            # Parse JSON result from helpers.table_to_json
            # May produce array [true, false, ...] or object {"1": true, "2": false, ...}
            result_str = result.strip()
            try:
                parsed = json.loads(result_str)
                # Check if it's an array (consecutive integer keys) or object (string keys)
                if isinstance(parsed, list):
                    # Direct array: [true, true, false, ...]
                    return [bool(v) for v in parsed]
                else:
                    # Object with string keys: {"1": true, "2": false, ...}
                    return [
                        parsed.get(str(i + 1), False) for i in range(len(positions))
                    ]
            except json.JSONDecodeError:
                # Fallback to regex parsing
                matches = re.findall(r"(true|false)", result_str.lower())
                if len(matches) >= len(positions):
                    return [m == "true" for m in matches[: len(positions)]]
                logger.warning(
                    f"Unexpected batch validation result format: {result_str}"
                )
                return [False] * len(positions)

        except Exception as e:
            logger.error(f"Batch placement validation failed: {e}")
            return [False] * len(positions)

    def validate_line(
        self,
        entity_name: str,
        start: MapPosition,
        end: MapPosition,
        direction: Optional[Direction] = None,
        ghost: bool = False,
    ) -> List[Tuple[MapPosition, bool]]:
        """Validate positions along a line using compressed loop generation.

        Generates Lua code with for-loops instead of embedding coordinates.

        Args:
            entity_name: Entity prototype name
            start: Start position
            end: End position
            direction: Optional direction (same for all positions in line)
            ghost: If True, uses manual_ghost build_check_type, else manual

        Returns:
            List of (position, can_place) tuples
        """
        # Calculate line positions
        positions = self._calculate_line_positions(start, end)

        # Use batch validation
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
        """Validate positions in a rectangular grid using nested loops.

        Generates compressed Lua code: for x = x1, x2 do for y = y1, y2 do ... end end

        Args:
            entity_name: Entity prototype name
            top_left: Top-left corner of grid
            bottom_right: Bottom-right corner of grid
            direction: Optional direction (same for all positions in grid)
            ghost: If True, uses manual_ghost build_check_type, else manual

        Returns:
            Dictionary mapping position -> can_place boolean
        """
        build_check_type = "manual_ghost" if ghost else "manual"

        # Build Lua command with nested loops
        lua_code = f"""
local surface = game.surfaces[1]
local entity_name = "{entity_name}"
local build_check_type = defines.build_check_type.{build_check_type}
local force = "player"
local results = {{}}

for x = {int(top_left.x)}, {int(bottom_right.x)} do
    for y = {int(top_left.y)}, {int(bottom_right.y)} do
        local pos = {{x = x, y = y}}
        local params = {{
            name = entity_name,
            position = pos,
            direction = {direction.value if direction else "nil"},
            force = force,
            build_check_type = build_check_type
        }}
        local key = string.format("%d,%d", x, y)
        results[key] = surface.can_place_entity(params)
    end
end

rcon.print(helpers.table_to_json(results))
"""

        try:
            result = self._rcon.execute(lua_code)
            if not result:
                return {}

            # Parse JSON result from helpers.table_to_json
            result_dict = {}
            try:
                parsed = json.loads(result.strip())
                # Keys are "x,y" coordinate strings
                for coord_str, can_place in parsed.items():
                    x_str, y_str = coord_str.split(",")
                    pos = MapPosition(x=float(x_str), y=float(y_str))
                    result_dict[pos] = bool(can_place)
            except json.JSONDecodeError:
                # Fallback to regex parsing for Lua table format
                matches = re.findall(
                    r'\["([^"]+)"\]\s*=\s*(true|false)', result.lower()
                )
                for coord_str, bool_str in matches:
                    x_str, y_str = coord_str.split(",")
                    pos = MapPosition(x=float(x_str), y=float(y_str))
                    result_dict[pos] = bool_str == "true"

            return result_dict

        except Exception as e:
            logger.error(f"Grid validation failed: {e}")
            return {}

    @staticmethod
    def _calculate_line_positions(
        start: MapPosition, end: MapPosition
    ) -> List[MapPosition]:
        """Calculate positions along a line from start to end.

        Uses integer stepping for horizontal/vertical lines, Bresenham-like
        algorithm for diagonal lines.
        """
        positions = []

        dx = end.x - start.x
        dy = end.y - start.y

        # Determine if line is horizontal, vertical, or diagonal
        abs_dx = abs(dx)
        abs_dy = abs(dy)

        if abs_dx == 0:
            # Vertical line
            step = 1 if dy > 0 else -1
            for y in range(int(start.y), int(end.y) + step, step):
                positions.append(MapPosition(x=start.x, y=float(y)))
        elif abs_dy == 0:
            # Horizontal line
            step = 1 if dx > 0 else -1
            for x in range(int(start.x), int(end.x) + step, step):
                positions.append(MapPosition(x=float(x), y=start.y))
        else:
            # Diagonal or arbitrary line - use step-based approach
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

    Provides pure, context-aware spatial reasoning for entity placement:
    - get_placement_line: Calculate lines of entities (belts, pipes, walls)
    - get_connection_positions: Solve connection puzzles (pipes to machines, drills to chests)

    All returned GhostPlan objects are pre-validated (valid=True).
    """

    def __init__(self, rcon_handler: "RconHandler"):
        """Initialize placement hints.

        Args:
            rcon_handler: RCON handler for executing Lua commands
        """
        self._rcon = rcon_handler
        self._validator = PlacementValidator(rcon_handler)

    def get_placement_line(
        self,
        entity_name: str,
        start: MapPosition,
        end: MapPosition,
        width: int = 1,
        validate: bool = True,
    ) -> GhostPlan:
        """Calculate a line of entities from start to end.

        Logic:
        1. Calculates vector and validates primary axis (Horizontal/Vertical).
        2. Determines consistent cardinal direction for directional entities (Belts).
        3. Generates a unique label for the group.
        4. Validates all positions before returning.

        Args:
            entity_name: Entity prototype name (e.g., "transport-belt", "pipe")
            start: Start position
            end: End position
            width: Line width (default: 1, for single-wide lines)
            validate: If True, validate all positions before returning (default: True)

        Returns:
            GhostPlan containing the ordered list of (position, direction) tuples
            and the group label. The plan is pre-validated (valid=True) if validate=True.

        Raises:
            ValueError: If start == end or validation fails
        """
        # Generate positions along the line
        positions = self._validator._calculate_line_positions(start, end)

        if not positions:
            raise ValueError("Start and end positions must be different")

        # Determine direction for directional entities
        dx = end.x - start.x
        dy = end.y - start.y

        # Infer direction from drag vector
        direction = None
        if abs(dx) > abs(dy):
            # Horizontal line
            direction = Direction.EAST if dx > 0 else Direction.WEST
        elif abs(dy) > abs(dx):
            # Vertical line
            direction = Direction.SOUTH if dy > 0 else Direction.NORTH
        else:
            # Diagonal or single tile - default to east
            direction = Direction.EAST

        # Check if entity requires direction (belts, inserters, etc.)
        requires_direction = self._entity_requires_direction(entity_name)

        # Build position-direction pairs
        if requires_direction:
            position_pairs = [(pos, direction) for pos in positions]
        else:
            position_pairs = [(pos, None) for pos in positions]

        # Generate unique label
        label = self._generate_label(entity_name, "line")

        # Create description
        description = f"Line of {len(positions)} {entity_name} from ({start.x:.1f}, {start.y:.1f}) to ({end.x:.1f}, {end.y:.1f})"

        # Create plan
        plan = GhostPlan(
            entity_name=entity_name,
            positions=position_pairs,
            label=label,
            description=description,
            valid=False,  # Will be set by validation
        )

        # Validate if requested
        if validate:
            plan.validate(self._validator)
        else:
            plan.valid = True  # Assume valid if validation skipped

        return plan

    def get_connection_positions(
        self,
        source_entity: "BaseEntity",
        target_entity_name: str,
        connection_type: ConnectionType,
    ) -> List[ConnectionPosition]:
        """Return all valid positions where 'target_entity' can connect to 'source_entity'.

        Entity requirements by connection type:
        - ITEM_DROP: source must be a mining drill (see ITEM_DROP_ENTITIES)
        - FLUID_PIPE: source must have fluidboxes (see FLUID_PIPE_ENTITIES)

        Args:
            source_entity: The existing entity (e.g., OilRefinery at position)
            target_entity_name: What we want to place (e.g., "pipe")
            connection_type: Type of connection to solve

        Returns:
            List of ConnectionPosition objects, sorted by alignment (best aligned first).
            Each ConnectionPosition contains:
            - position: MapPosition where target can be placed
            - direction: Optional[Direction] for placement (None if not required)
            - perpendicular_offset: float distance from source perpendicular to flow
              (0.0 = perfectly aligned, lower values = better alignment)
            All returned positions are pre-validated using PlacementValidator.

        Raises:
            EntityValidationError: If source_entity is not compatible with connection_type

        Example:
            source = OilRefinery at (10,10)
            target = "pipe"
            type = FLUID_PIPE

            Returns: [
                ConnectionPosition(
                    position=MapPosition(9, 10),
                    direction=None,
                    perpendicular_offset=0.0
                ),
                ConnectionPosition(
                    position=MapPosition(12, 10),
                    direction=None,
                    perpendicular_offset=0.0
                ),
                ...
            ]
        """
        # Validate entity compatibility before proceeding
        validate_entity_for_connection(source_entity.name, connection_type)

        if connection_type == ConnectionType.ITEM_DROP:
            return self._get_item_drop_positions(source_entity, target_entity_name)
        elif connection_type == ConnectionType.FLUID_PIPE:
            return self._get_fluid_pipe_positions(source_entity, target_entity_name)
        elif connection_type == ConnectionType.ELECTRIC_WIRE:
            return self._get_electric_wire_positions(source_entity, target_entity_name)
        else:
            logger.warning(f"Connection type {connection_type} not yet implemented")
            return []

    def _get_item_drop_positions(
        self, source_entity: "BaseEntity", target_entity_name: str
    ) -> List[Tuple[MapPosition, Optional[Direction]]]:
        """Get positions where target entity can be placed to receive items from source.

        Applicable entities: electric-mining-drill, burner-mining-drill
        (see ITEM_DROP_ENTITIES)

        For mining drills, calculates positions where target entity (furnace, chest, etc.)
        can be placed to receive items from the drill's output.

        Uses discrete tile-based algorithm:
        1. Calculate source entity's output position (drop tile)
        2. Get source and target entity tile footprints
        3. Iterate over all possible tile offsets where target could intersect drop tile
        4. Check for grid overlap - reject positions where footprints collide
        5. Sort by alignment preference (perpendicular to flow direction)
        6. Validate all candidate positions

        Note: Entity validation is performed by get_connection_positions().
        """
        import math
        from FactoryVerse.factory.prototypes import (
            get_entity_prototypes,
            get_width_height,
            snap_to_tile_center,
        )

        # Entity type already validated by get_connection_positions()

        # 1. Get source entity's output position
        # Try using get_output_position() if available (MinerMixin)
        if hasattr(source_entity, "get_output_position"):
            try:
                drop_pos = source_entity.get_output_position()
            except Exception:
                # Fallback: calculate from prototype and direction
                output_vec = tuple(source_entity.prototype["vector_to_place_result"])
                from FactoryVerse.factory.prototypes import apply_cardinal_vector

                source_dir = getattr(source_entity, "direction", Direction.NORTH)
                raw_drop_pos = apply_cardinal_vector(
                    source_entity.position, output_vec, source_dir
                )
                drop_pos = snap_to_tile_center(raw_drop_pos)
        else:
            # Calculate from prototype
            output_vec = tuple(source_entity.prototype["vector_to_place_result"])
            from FactoryVerse.factory.prototypes import apply_cardinal_vector

            source_dir = getattr(source_entity, "direction", Direction.NORTH)
            raw_drop_pos = apply_cardinal_vector(
                source_entity.position, output_vec, source_dir
            )
            drop_pos = snap_to_tile_center(raw_drop_pos)

        # 2. Determine source entity tile footprint
        s_width = source_entity.tile_width
        s_height = source_entity.tile_height
        s_half_w = s_width / 2.0
        s_half_h = s_height / 2.0

        src_left = source_entity.position.x - s_half_w
        src_right = source_entity.position.x + s_half_w
        src_top = source_entity.position.y - s_half_h
        src_bottom = source_entity.position.y + s_half_h

        # 3. Get target entity prototype and dimensions
        prototypes = get_entity_prototypes()
        target_proto = prototypes.get_prototype(target_entity_name)
        if not target_proto:
            logger.warning(
                f"Target entity prototype not found: {target_entity_name}"
            )
            return []

        # Get target tile dimensions
        if "tile_width" in target_proto and "tile_height" in target_proto:
            t_width = int(target_proto["tile_width"])
            t_height = int(target_proto["tile_height"])
        elif "collision_box" in target_proto:
            EPSILON = 0.001
            w, h = get_width_height(target_proto["collision_box"])
            t_width = int(math.ceil(w - EPSILON))
            t_height = int(math.ceil(h - EPSILON))
        else:
            logger.warning(
                f"Target entity {target_entity_name} has no tile dimensions"
            )
            return []

        t_half_w = t_width / 2.0
        t_half_h = t_height / 2.0

        # 4. Identify drop tile (discrete tile coordinates)
        drop_tile_x = math.floor(drop_pos.x)
        drop_tile_y = math.floor(drop_pos.y)

        # 5. Generate candidate positions
        candidates: List[MapPosition] = []

        # Iterate over every relative tile offset the target could have
        for dx in range(t_width):
            for dy in range(t_height):
                # Calculate target footprint if target's (dx, dy) tile is at drop tile
                target_left = drop_tile_x - dx
                target_top = drop_tile_y - dy

                target_right = target_left + t_width
                target_bottom = target_top + t_height

                # 6. Strict grid overlap check (AABB)
                # If bounding boxes don't overlap, entities won't collide
                is_disjoint = (
                    target_right <= src_left  # Target fully to the left
                    or target_left >= src_right  # Target fully to the right
                    or target_bottom <= src_top  # Target fully above
                    or target_top >= src_bottom  # Target fully below
                )

                if is_disjoint:
                    # No overlap - calculate center position
                    center_x = target_left + t_half_w
                    center_y = target_top + t_half_h
                    candidates.append(MapPosition(center_x, center_y))

        if not candidates:
            return []

        # 7. Calculate alignment (perpendicular offset) for each candidate
        source_dir = getattr(source_entity, "direction", Direction.NORTH)

        def calculate_perpendicular_offset(pos: MapPosition) -> float:
            """Calculate perpendicular offset from source entity.

            For vertical flow (NORTH/SOUTH): measures horizontal (X) offset
            For horizontal flow (EAST/WEST): measures vertical (Y) offset
            Returns 0.0 for perfect alignment.
            """
            if source_dir in (Direction.NORTH, Direction.SOUTH):
                # Vertical flow: measure horizontal (X) offset
                return abs(pos.x - source_entity.position.x)
            elif source_dir in (Direction.EAST, Direction.WEST):
                # Horizontal flow: measure vertical (Y) offset
                return abs(pos.y - source_entity.position.y)
            return 0.0

        # Create candidate list with alignment info
        candidates_with_alignment = [
            (pos, calculate_perpendicular_offset(pos)) for pos in candidates
        ]

        # Sort by alignment (lower perpendicular_offset = better alignment)
        candidates_with_alignment.sort(key=lambda x: x[1])

        # 8. Validate positions and return ConnectionPosition objects
        valid_positions: List[ConnectionPosition] = []
        for candidate_pos, perpendicular_offset in candidates_with_alignment:
            # Target entities may or may not need direction
            # Try without direction first (most entities don't need it)
            direction: Optional[Direction] = None
            if self._validator.validate_placement(
                target_entity_name, candidate_pos, None, ghost=True
            ):
                direction = None
            else:
                # Try with source direction if entity requires direction
                if self._entity_requires_direction(target_entity_name):
                    if self._validator.validate_placement(
                        target_entity_name, candidate_pos, source_dir, ghost=True
                    ):
                        direction = source_dir
                    else:
                        continue  # Skip if validation fails with direction
                else:
                    continue  # Skip if validation fails and no direction needed

            valid_positions.append(
                ConnectionPosition(
                    position=candidate_pos,
                    direction=direction,
                    perpendicular_offset=perpendicular_offset,
                )
            )

        return valid_positions

    def _get_fluid_pipe_positions(
        self, source_entity: "BaseEntity", target_entity_name: str
    ) -> List[ConnectionPosition]:
        """Get positions where pipes can connect to source entity's fluidboxes.

        Applicable entities: boiler, steam-engine, steam-turbine, chemical-plant,
        oil-refinery, pumpjack, pipe, pipe-to-ground, pump, offshore-pump, storage-tank
        (see FLUID_PIPE_ENTITIES)

        For fluid-handling entities, calculates positions where pipes can connect
        based on fluidbox prototype data.

        Note: Entity validation is performed by get_connection_positions().
        """
        # Check if source has FluidMixin and use its method
        from FactoryVerse.factory.entity.capabilities.fluid import FluidMixin

        try:
            if isinstance(source_entity, FluidMixin):
                # Use the mixin's method if available
                pipe_positions = source_entity.get_pipe_connections()
                logger.debug(f"FluidMixin.get_pipe_connections() returned {len(pipe_positions)} positions")
            else:
                # Fallback to direct prototype access
                proto = source_entity.prototype
                if not proto:
                    logger.warning(f"Entity {source_entity.name} has no prototype data")
                    return []
                
                # Try multiple possible fluidbox locations (both spellings: fluidbox and fluid_box)
                fluidbox_data = (
                    proto.get("fluidbox")
                    or proto.get("fluid_box")
                    or proto.get("output_fluid_box")
                    or proto.get("input_fluid_box")
                )

                if not fluidbox_data:
                    logger.warning(
                        f"Entity {source_entity.name} has no fluidbox data in prototype. "
                        f"Available keys: {list(proto.keys())[:20]}"
                    )
                    return []

                # Extract pipe connection positions manually
                from FactoryVerse.factory.prototypes import apply_cardinal_vector

                pipe_connections = fluidbox_data.get("pipe_connections", [])
                if not pipe_connections:
                    logger.warning(
                        f"Entity {source_entity.name} has no pipe_connections in fluidbox. "
                        f"Fluidbox keys: {list(fluidbox_data.keys())}"
                    )
                    return []

                pipe_positions = []
                # Get direction from entity, default to NORTH if not available
                source_dir = getattr(source_entity, "direction", None)
                if source_dir is None:
                    source_dir = Direction.NORTH

                logger.debug(f"Processing {len(pipe_connections)} pipe connections for {source_entity.name}")
                for i, connection in enumerate(pipe_connections):
                    # Connection can have "position" (single) or "positions" (list)
                    positions = connection.get("positions", [])
                    if not positions:
                        position = connection.get("position")
                        if position:
                            positions = [position]

                    logger.debug(f"Connection {i}: {len(positions)} positions, keys: {list(connection.keys())}")
                    for pos_data in positions:
                        if isinstance(pos_data, list) and len(pos_data) == 2:
                            vec = tuple(pos_data)
                            calculated_pos = apply_cardinal_vector(
                                source_entity.position, vec, source_dir
                            )
                            pipe_positions.append(calculated_pos)
                            logger.debug(f"  Calculated pipe position: {calculated_pos} from vec {vec}, dir {source_dir}")
                        elif isinstance(pos_data, dict) and "x" in pos_data and "y" in pos_data:
                            # Handle dict format {x: ..., y: ...}
                            vec = (pos_data["x"], pos_data["y"])
                            calculated_pos = apply_cardinal_vector(
                                source_entity.position, vec, source_dir
                            )
                            pipe_positions.append(calculated_pos)
                            logger.debug(f"  Calculated pipe position: {calculated_pos} from dict {pos_data}, dir {source_dir}")
                
                logger.debug(f"Total pipe positions calculated: {len(pipe_positions)}")

            # Validate all positions and create ConnectionPosition objects
            # Pipe connection points are where pipes connect TO the entity, not where to place the pipe.
            # We need to find adjacent positions where we can actually place a pipe.
            # Try positions adjacent to each connection point (cardinal directions)
            valid_positions: List[ConnectionPosition] = []
            
            for connection_point in pipe_positions:
                # Try placing pipe at the connection point first (might work for some entities)
                can_place_at_point = self._validator.validate_placement(
                    target_entity_name, connection_point, None, ghost=True
                )
                if can_place_at_point:
                    valid_positions.append(
                        ConnectionPosition(
                            position=connection_point,
                            direction=None,
                            perpendicular_offset=0.0,
                        )
                    )
                    logger.debug(f"Pipe can be placed at connection point: {connection_point}")
                    continue
                
                # If connection point is invalid (likely inside entity collision box),
                # try adjacent positions (1 tile away in cardinal directions)
                adjacent_offsets = [
                    (0, -1),  # North
                    (1, 0),   # East
                    (0, 1),   # South
                    (-1, 0),  # West
                ]
                
                for dx, dy in adjacent_offsets:
                    adjacent_pos = MapPosition(
                        x=connection_point.x + dx,
                        y=connection_point.y + dy,
                    )
                    can_place = self._validator.validate_placement(
                        target_entity_name, adjacent_pos, None, ghost=True
                    )
                    logger.debug(f"Validation for pipe at {adjacent_pos} (adjacent to {connection_point}): {can_place}")
                    if can_place:
                        valid_positions.append(
                            ConnectionPosition(
                                position=adjacent_pos,
                                direction=None,
                                perpendicular_offset=0.0,  # Pipes don't need alignment sorting
                            )
                        )
                        # Only need one valid adjacent position per connection point
                        break

            logger.debug(f"Returning {len(valid_positions)} valid pipe positions out of {len(pipe_positions)} connection points")
            return valid_positions

        except Exception as e:
            logger.error(f"Error getting pipe positions for {source_entity.name}: {e}")
            return []

    @staticmethod
    def _entity_requires_direction(entity_name: str) -> bool:
        """Check if entity requires a direction for placement.

        Belts, inserters, assemblers require direction.
        Walls, pipes, poles do not.
        """
        directional_types = [
            "transport-belt",
            "fast-transport-belt",
            "express-transport-belt",
            "inserter",
            "long-handed-inserter",
            "fast-inserter",
            "assembling-machine",
            "stone-furnace",
            "steel-furnace",
            "electric-furnace",
            "electric-mining-drill",
            "burner-mining-drill",
            "pumpjack",
            "boiler",
            "steam-engine",
            "offshore-pump",
        ]

        return entity_name in directional_types

    @staticmethod
    def _generate_label(entity_name: str, plan_type: str) -> str:
        """Generate a unique label for a ghost plan.

        Format: plan:{entity}:{type}:{timestamp}:{short_hash}

        Args:
            entity_name: Entity prototype name
            plan_type: Type of plan (e.g., "line", "grid", "connection")

        Returns:
            Unique label string
        """
        timestamp = int(time.time())
        short_hash = str(uuid.uuid4())[:8]
        return f"plan:{entity_name}:{plan_type}:{timestamp}:{short_hash}"

    # =========================================================================
    # NEW PLACEMENT PRIMITIVES
    # =========================================================================

    def get_inserter_placement_positions(
        self,
        source_entity: "BaseEntity",
        target_entity: "BaseEntity",
        inserter_name: str = "inserter",
    ) -> List[Tuple[MapPosition, Direction]]:
        """Find valid inserter positions to transfer items from source to target.

        Calculates positions where an inserter can be placed such that:
        - Its pickup position reaches the source entity's output
        - Its drop position reaches the target entity's center

        Args:
            source_entity: Entity to pick up items from (e.g., mining drill, chest)
            target_entity: Entity to drop items to (e.g., furnace, chest)
            inserter_name: Which inserter type to place (default: "inserter")

        Returns:
            List of (position, direction) tuples for valid placements

        Example:
            >>> drill = reachable.get_entity("electric-mining-drill")
            >>> furnace = reachable.get_entity("stone-furnace")
            >>> positions = placement_hints.get_inserter_placement_positions(
            ...     source_entity=drill,
            ...     target_entity=furnace,
            ...     inserter_name="inserter"
            ... )
        """
        from FactoryVerse.factory.prototypes import (
            get_entity_prototypes,
            apply_cardinal_vector,
        )

        prototypes = get_entity_prototypes()
        inserter_proto = prototypes.get_prototype(inserter_name)
        if not inserter_proto:
            logger.warning(f"Inserter prototype not found: {inserter_name}")
            return []

        pickup_vec = tuple(inserter_proto.get("pickup_position", [0, -1]))
        drop_vec = tuple(inserter_proto.get("insert_position", [0, 1]))

        # Get source output position (use output vector for miners, center otherwise)
        source_output = source_entity.position
        if hasattr(source_entity, "get_output_position"):
            try:
                source_output = source_entity.get_output_position()
            except Exception:
                pass

        # Target input is entity center
        target_input = target_entity.position

        valid_positions: List[Tuple[MapPosition, Direction]] = []

        for direction in [
            Direction.NORTH,
            Direction.EAST,
            Direction.SOUTH,
            Direction.WEST,
        ]:
            # Calculate where inserter would need to be for its pickup to reach source
            # pickup_pos = inserter_pos + rotated(pickup_vec)
            # So inserter_pos = pickup_pos - rotated(pickup_vec)
            rotated_pickup = self._rotate_vector(pickup_vec, direction)
            rotated_drop = self._rotate_vector(drop_vec, direction)

            # Check if from a position we can reach both source and target
            # Inserter at pos: pickup = pos + rotated_pickup, drop = pos + rotated_drop
            # We want: pickup ≈ source_output, drop ≈ target_input
            # So pos = source_output - rotated_pickup (for pickup alignment)
            # And we check if pos + rotated_drop ≈ target_input

            inserter_pos_from_pickup = MapPosition(
                x=source_output.x - rotated_pickup[0],
                y=source_output.y - rotated_pickup[1],
            )

            # Verify drop reaches target
            actual_drop = MapPosition(
                x=inserter_pos_from_pickup.x + rotated_drop[0],
                y=inserter_pos_from_pickup.y + rotated_drop[1],
            )

            # Check if drop is within target bounds (allow some tolerance)
            if actual_drop.distance(target_input) <= 1.0:
                # Validate placement
                if self._validator.validate_placement(
                    inserter_name, inserter_pos_from_pickup, direction, ghost=True
                ):
                    valid_positions.append((inserter_pos_from_pickup, direction))

        return valid_positions

    @staticmethod
    def _rotate_vector(
        vec: Tuple[float, float], direction: Direction
    ) -> Tuple[float, float]:
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

    def get_pole_line(
        self,
        start: MapPosition,
        end: MapPosition,
        pole_name: str = "medium-electric-pole",
        validate: bool = True,
    ) -> GhostPlan:
        """Plan a line of poles from start to end at maximum wire distance intervals.

        Places poles spaced by their maximum_wire_distance to minimize pole count
        while maintaining connectivity.

        Args:
            start: Start position
            end: End position
            pole_name: Electric pole type (default: "medium-electric-pole")
            validate: If True, validates each position

        Returns:
            GhostPlan with pole positions

        Example:
            >>> plan = placement_hints.get_pole_line(
            ...     start=mining_area,
            ...     end=factory_pos,
            ...     pole_name="big-electric-pole"
            ... )
        """
        from FactoryVerse.factory.prototypes import get_entity_prototypes

        prototypes = get_entity_prototypes()
        pole_proto = prototypes.get_prototype(pole_name)
        if not pole_proto:
            raise ValueError(f"Unknown pole type: {pole_name}")

        max_wire_distance = pole_proto.get("maximum_wire_distance", 9)

        # Calculate line length and number of poles needed
        dx = end.x - start.x
        dy = end.y - start.y
        distance = (dx**2 + dy**2) ** 0.5

        if distance == 0:
            positions = [(start, None)]
        else:
            # Number of segments (poles = segments + 1)
            num_segments = max(1, int(distance / max_wire_distance) + 1)
            positions = []

            for i in range(num_segments + 1):
                t = i / num_segments
                pos = MapPosition(
                    x=start.x + t * dx,
                    y=start.y + t * dy,
                )
                positions.append((pos, None))

        label = self._generate_label(pole_name, "pole_line")
        description = f"Line of {len(positions)} {pole_name} from ({start.x:.1f}, {start.y:.1f}) to ({end.x:.1f}, {end.y:.1f})"

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
        """Find a single pole position that covers ALL given entities.

        Args:
            entities_to_power: List of entities that need power
            pole_name: Electric pole type

        Returns:
            MapPosition if single pole can cover all, None otherwise
        """
        from FactoryVerse.factory.prototypes import get_entity_prototypes

        if not entities_to_power:
            return None

        prototypes = get_entity_prototypes()
        pole_proto = prototypes.get_prototype(pole_name)
        if not pole_proto:
            return None

        supply_distance = pole_proto.get("supply_area_distance", 3.5)

        # Calculate bounding box of all entities
        min_x = min(e.position.x for e in entities_to_power)
        max_x = max(e.position.x for e in entities_to_power)
        min_y = min(e.position.y for e in entities_to_power)
        max_y = max(e.position.y for e in entities_to_power)

        # Check if spread exceeds supply diameter
        spread_x = max_x - min_x
        spread_y = max_y - min_y
        supply_diameter = supply_distance * 2

        if spread_x > supply_diameter or spread_y > supply_diameter:
            return None  # Cannot cover with single pole

        # Center of entities
        center = MapPosition(
            x=(min_x + max_x) / 2,
            y=(min_y + max_y) / 2,
        )

        # Validate pole can be placed at center
        if self._validator.validate_placement(pole_name, center, None, ghost=True):
            return center

        # Try snapping to tile center
        from FactoryVerse.factory.prototypes import snap_to_tile_center

        snapped = snap_to_tile_center(center)
        if self._validator.validate_placement(pole_name, snapped, None, ghost=True):
            return snapped

        return None

    def get_pole_coverage_plan(
        self,
        entities_to_power: List["BaseEntity"],
        pole_name: str = "medium-electric-pole",
    ) -> Tuple[GhostPlan, List["BaseEntity"]]:
        """Find minimum poles to cover all entities using greedy set cover.

        Args:
            entities_to_power: List of entities that need power
            pole_name: Electric pole type

        Returns:
            Tuple of (GhostPlan, uncovered_entities)
            uncovered_entities is empty if all were covered
        """
        from FactoryVerse.factory.prototypes import get_entity_prototypes

        if not entities_to_power:
            return GhostPlan(
                entity_name=pole_name,
                positions=[],
                label=self._generate_label(pole_name, "coverage"),
                description="Empty coverage plan",
                valid=True,
            ), []

        prototypes = get_entity_prototypes()
        pole_proto = prototypes.get_prototype(pole_name)
        supply_distance = (
            pole_proto.get("supply_area_distance", 3.5) if pole_proto else 3.5
        )

        uncovered = set(range(len(entities_to_power)))
        pole_positions: List[Tuple[MapPosition, Optional[Direction]]] = []

        while uncovered:
            best_pos = None
            best_covered: set = set()

            # Try center of remaining uncovered entities
            remaining = [entities_to_power[i] for i in uncovered]
            center = MapPosition(
                x=sum(e.position.x for e in remaining) / len(remaining),
                y=sum(e.position.y for e in remaining) / len(remaining),
            )

            # Count which entities this position covers
            covered = set()
            for idx in uncovered:
                entity = entities_to_power[idx]
                if center.distance(entity.position) <= supply_distance:
                    covered.add(idx)

            if covered and self._validator.validate_placement(
                pole_name, center, None, ghost=True
            ):
                best_pos = center
                best_covered = covered

            if best_pos:
                pole_positions.append((best_pos, None))
                uncovered -= best_covered
            else:
                # Cannot place more poles, remaining entities are uncovered
                break

        uncovered_entities = [entities_to_power[i] for i in uncovered]
        label = self._generate_label(pole_name, "coverage")
        description = f"Coverage plan: {len(pole_positions)} {pole_name} covering {len(entities_to_power) - len(uncovered)} entities"

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
        """Plan an underground segment (belt or pipe) between two points.

        Places input entrance at start, output exit at end.
        Validates that distance doesn't exceed max_underground_distance.

        Args:
            entity_name: "underground-belt" or "pipe-to-ground"
            start: Input/entrance position
            end: Output/exit position
            direction: Direction the segment flows

        Returns:
            GhostPlan with 2 positions (entrance, exit)

        Raises:
            ValueError: If distance exceeds maximum or entity not supported
        """
        from FactoryVerse.factory.prototypes import get_entity_prototypes

        prototypes = get_entity_prototypes()
        proto = prototypes.get_prototype(entity_name)
        if not proto:
            raise ValueError(f"Unknown entity: {entity_name}")

        # Get max distance
        if "max_distance" in proto:
            max_distance = proto["max_distance"]
        elif "fluid_box" in proto:
            # pipe-to-ground stores it in fluid_box.pipe_connections
            connections = proto["fluid_box"].get("pipe_connections", [])
            max_distance = 10  # default
            for conn in connections:
                if "max_underground_distance" in conn:
                    max_distance = conn["max_underground_distance"]
                    break
        else:
            raise ValueError(f"Entity {entity_name} doesn't support underground")

        # Calculate distance
        dx = end.x - start.x
        dy = end.y - start.y
        distance = max(abs(dx), abs(dy))  # Manhattan-ish for straight lines

        if distance > max_distance:
            raise ValueError(
                f"Distance {distance:.1f} exceeds max_underground_distance {max_distance} for {entity_name}"
            )

        # Determine input/output directions
        opposite_dir = {
            Direction.NORTH: Direction.SOUTH,
            Direction.SOUTH: Direction.NORTH,
            Direction.EAST: Direction.WEST,
            Direction.WEST: Direction.EAST,
        }

        positions: List[Tuple[MapPosition, Optional[Direction]]] = [
            (start, direction),  # Input facing the direction
            (end, opposite_dir.get(direction, direction)),  # Output facing opposite
        ]

        label = self._generate_label(entity_name, "underground")
        description = f"Underground {entity_name} from ({start.x:.1f}, {start.y:.1f}) to ({end.x:.1f}, {end.y:.1f})"

        plan = GhostPlan(
            entity_name=entity_name,
            positions=positions,
            label=label,
            description=description,
            valid=False,
        )

        plan.validate(self._validator)
        return plan

    def _get_electric_wire_positions(
        self, source_entity: "BaseEntity", target_entity_name: str
    ) -> List[WireConnectionPosition]:
        """Get positions where a pole can connect to source pole.
        
        Early exits:
        - If source_entity is not a pole → raises EntityValidationError (handled by caller)
        - If no valid positions within maximum_wire_distance → returns []
        
        Args:
            source_entity: The source pole entity
            target_entity_name: Pole type to place (e.g., "medium-electric-pole")
            
        Returns:
            List of WireConnectionPosition objects, sorted by distance (closest first)
        """
        from FactoryVerse.factory.prototypes import get_entity_prototypes
        import math
        
        # Get wire distance from target pole prototype
        prototypes = get_entity_prototypes()
        target_proto = prototypes.get_prototype(target_entity_name)
        if not target_proto:
            logger.warning(f"Target pole prototype not found: {target_entity_name}")
            return []
        
        max_wire_distance = target_proto.get("maximum_wire_distance", 7.5)
        
        # Calculate grid of positions within wire distance
        # Use tile-based positions for efficiency
        source_pos = source_entity.position
        positions: List[WireConnectionPosition] = []
        
        # Generate positions in a square grid around source
        # Use integer tile coordinates for efficiency
        max_tiles = int(math.ceil(max_wire_distance))
        
        for dx in range(-max_tiles, max_tiles + 1):
            for dy in range(-max_tiles, max_tiles + 1):
                candidate_pos = MapPosition(
                    x=source_pos.x + dx,
                    y=source_pos.y + dy,
                )
                
                # Early exit: beyond wire distance (with small tolerance for floating point)
                distance = source_pos.distance(candidate_pos)
                if distance > max_wire_distance + 0.01:  # Small tolerance for floating point precision
                    continue
                
                # Validate placement
                if self._validator.validate_placement(
                    target_entity_name, candidate_pos, None, ghost=True
                ):
                    # Calculate wire distance utilization (ratio of distance to max)
                    wire_utilization = distance / max_wire_distance if max_wire_distance > 0 else 0.0
                    
                    positions.append(
                        WireConnectionPosition(
                            position=candidate_pos,
                            direction=None,  # Poles don't have direction
                            perpendicular_offset=distance,  # For sorting by distance
                            wire_distance=distance,  # Explicit wire distance in tiles
                            wire_distance_utilization=wire_utilization,  # How much of max wire distance is used (ratio)
                        )
                    )
        
        # Sort by distance (closest first)
        positions.sort(key=lambda p: p.perpendicular_offset)
        return positions

    def evaluate_pole_placement(
        self,
        position: MapPosition,
        pole_name: str,
        source_pole: Optional["BaseEntity"] = None,
        reachable_view: Optional[Any] = None,
    ) -> PolePlacementResult:
        """Evaluate a pole placement position without placing anything (dry run).
        
        Answers "what if I place a pole here?" - provides rich feedback about
        connectivity, power supply area, and power network access.
        
        Args:
            position: Position to evaluate
            pole_name: Pole type to evaluate (e.g., "medium-electric-pole")
            source_pole: Optional source pole to check connectivity against
            reachable_view: Optional ReachableView for querying entities/poles
                           If None, will try to get from context (may fail)
        
        Returns:
            PolePlacementResult with rich feedback about the placement
        """
        from FactoryVerse.factory.prototypes import get_entity_prototypes
        from FactoryVerse.factory.types import BoundingBox
        
        # Get pole prototype
        prototypes = get_entity_prototypes()
        pole_proto = prototypes.get_prototype(pole_name)
        if not pole_proto:
            return PolePlacementResult(
                position=position,
                pole_name=pole_name,
                supply_area_distance=0.0,
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
                is_valid_placement=False,
                placement_error=f"Unknown pole type: {pole_name}",
                maximum_wire_distance=0.0,
            )
        
        supply_area_distance = pole_proto.get("supply_area_distance", 0.0)
        maximum_wire_distance = pole_proto.get("maximum_wire_distance", 7.5)
        
        # Validate placement first
        is_valid = self._validator.validate_placement(
            pole_name, position, None, ghost=True
        )
        placement_error = None if is_valid else "Cannot place pole at this position (collision or invalid)"
        
        # Initialize result
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
        
        # Check connectivity to source pole if provided (even if placement is invalid)
        if source_pole:
            distance = position.distance(source_pole.position)
            result.distance_to_source = distance
            result.connects_to_source = distance <= maximum_wire_distance
        
        # If placement is invalid, return early with minimal info (but distance_to_source already set)
        if not is_valid:
            return result
        
        # Find entities within supply area and poles within wire distance
        # Note: This requires reachable_view - if not provided, we can't query
        if reachable_view is None:
            logger.warning("evaluate_pole_placement called without reachable_view - limited functionality")
            return result
        
        # Get all reachable entities to check supply area
        all_entities = reachable_view.get_entities()
        
        # Filter entities within supply area
        entities_powered = []
        for entity in all_entities:
            # Skip poles and ghosts for supply area calculation
            if entity.name in ELECTRIC_POLE_ENTITIES or entity.is_ghost:
                continue
            
            # Check if entity is within supply area
            distance_to_entity = position.distance(entity.position)
            if distance_to_entity <= supply_area_distance:
                entities_powered.append(entity)
        
        result.entities_powered = entities_powered
        result.entities_powered_count = len(entities_powered)
        
        # Find poles within wire distance
        connected_poles = []
        for entity in all_entities:
            if entity.name in ELECTRIC_POLE_ENTITIES and not entity.is_ghost:
                distance_to_pole = position.distance(entity.position)
                if distance_to_pole <= maximum_wire_distance and distance_to_pole > 0.01:  # Exclude self
                    connected_poles.append(entity)
        
        # Sort by distance
        connected_poles.sort(key=lambda p: position.distance(p.position))
        result.connected_poles = connected_poles
        result.connected_poles_count = len(connected_poles)
        
        # Trace power path if there are connected poles
        if connected_poles:
            power_path, power_source = self._trace_power_path(
                position, pole_name, connected_poles, reachable_view
            )
            result.power_path = power_path
            result.power_source = power_source
            result.can_receive_power = power_source is not None
        
        return result

    def _trace_power_path(
        self,
        position: MapPosition,
        pole_name: str,
        connected_poles: List["BaseEntity"],
        reachable_view: Any,
    ) -> Tuple[Optional[List["BaseEntity"]], Optional["BaseEntity"]]:
        """Trace connectivity from position through connected poles to find power source.
        
        Uses BFS to find path to power source through pole network.
        
        Args:
            position: Position of the candidate pole
            pole_name: Pole type name
            connected_poles: List of poles within wire distance
            reachable_view: ReachableView for querying entities
        
        Returns:
            Tuple of (power_path, power_source) or (None, None) if not connected
        """
        from FactoryVerse.factory.prototypes import get_entity_prototypes
        
        # Get all poles in reachable area for network traversal
        all_poles = [
            e for e in reachable_view.get_entities()
            if e.name in ELECTRIC_POLE_ENTITIES and not e.is_ghost
        ]
        
        # Get pole prototype for wire distance
        prototypes = get_entity_prototypes()
        pole_proto = prototypes.get_prototype(pole_name)
        max_wire_distance = pole_proto.get("maximum_wire_distance", 7.5) if pole_proto else 7.5
        
        # Power sources are entities that generate electricity
        # Check both by name and by prototype energy_source.type
        POWER_SOURCE_NAMES = {
            "steam-engine",
            "steam-turbine",
            "solar-panel",
            "nuclear-reactor",
        }
        
        def is_power_source(entity: "BaseEntity") -> bool:
            """Check if entity is a power source."""
            if entity.is_ghost:
                return False
            
            # Check by name
            if entity.name in POWER_SOURCE_NAMES:
                return True
            
            # Check by prototype energy_source
            proto = entity.prototype
            if proto:
                energy_source = proto.get("energy_source")
                if energy_source:
                    energy_type = energy_source.get("type")
                    # "electric" with "burns_fluid" or "solar" indicates power generation
                    if energy_type == "electric" and energy_source.get("burns_fluid"):
                        return True
                    if energy_type == "solar":
                        return True
            
            return False
        
        # BFS from position through connected poles to find power source
        visited = set()
        # Use position as string key for visited set
        visited.add(f"{position.x:.2f},{position.y:.2f}")
        
        queue = [(position, [])]  # (current_pos, path_so_far)
        
        # Get all entities once for power source checking
        all_entities = reachable_view.get_entities()
        power_sources = [e for e in all_entities if is_power_source(e)]
        
        while queue:
            current_pos, path = queue.pop(0)
            
            # Check if current position has a power source nearby
            # Power sources connect to poles within their supply area or via wires
            for power_source in power_sources:
                distance = current_pos.distance(power_source.position)
                # Check if power source is within reasonable connection distance
                # (poles can connect to power sources within supply area or wire distance)
                if distance <= max_wire_distance + 2.0:  # Allow some tolerance
                    # Found power source - return path
                    return (path, power_source)
            
            # Check connected poles from current position
            for pole in all_poles:
                pole_key = f"{pole.position.x:.2f},{pole.position.y:.2f}"
                if pole_key in visited:
                    continue
                
                distance = current_pos.distance(pole.position)
                if distance <= max_wire_distance:
                    visited.add(pole_key)
                    queue.append((pole.position, path + [pole]))
        
        return (None, None)  # No path to power source

    @property
    def validator(self) -> PlacementValidator:
        """Expose validator for direct access."""
        return self._validator
