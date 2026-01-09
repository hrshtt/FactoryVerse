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
from typing import List, Optional, Dict, Any, Tuple, Union, TYPE_CHECKING
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
    ) -> List[Tuple[MapPosition, Optional[Direction]]]:
        """Return all valid positions where 'target_entity' can connect to 'source_entity'.

        Args:
            source_entity: The existing entity (e.g., OilRefinery at position)
            target_entity_name: What we want to place (e.g., "pipe")
            connection_type: Type of connection to solve

        Returns:
            List of (position, direction) tuples where target can be placed.
            All returned positions are pre-validated using PlacementValidator.

        Example:
            source = OilRefinery at (10,10)
            target = "pipe"
            type = FLUID_PIPE

            Returns: [
                (MapPosition(9, 10), Direction.EAST),   # Left input
                (MapPosition(12, 10), Direction.WEST), # Right input
                ...
            ]
        """
        if connection_type == ConnectionType.ITEM_DROP:
            return self._get_item_drop_positions(source_entity, target_entity_name)
        elif connection_type == ConnectionType.FLUID_PIPE:
            return self._get_fluid_pipe_positions(source_entity, target_entity_name)
        else:
            logger.warning(f"Connection type {connection_type} not yet implemented")
            return []

    def _get_item_drop_positions(
        self, source_entity: "BaseEntity", target_entity_name: str
    ) -> List[Tuple[MapPosition, Optional[Direction]]]:
        """Get positions where mining drill can drop items into target.

        For mining drills, calculates positions where drill can be placed
        so its output reaches the target entity (chest, belt, etc.).
        """
        from FactoryVerse.factory.prototypes import apply_cardinal_vector

        # Get source entity type
        source_name = source_entity.name

        # Check if source is a mining drill
        if source_name not in ["electric-mining-drill", "burner-mining-drill"]:
            logger.warning(f"Entity {source_name} is not a mining drill")
            return []

        # Get output vector from prototype
        output_vec = tuple(source_entity.prototype["vector_to_place_result"])

        # Calculate positions where drill can be placed to output to target
        target_pos = source_entity.position
        valid_positions: List[Tuple[MapPosition, Optional[Direction]]] = []

        for direction in [
            Direction.NORTH,
            Direction.EAST,
            Direction.SOUTH,
            Direction.WEST,
        ]:
            # Reverse the output_position calculation
            # If output_position(drill_center, dir) = target_pos
            # Then drill_center = target_pos - rotated_vector
            # Apply rotation to get the actual offset
            vx, vy = output_vec
            if direction == Direction.EAST:
                vx, vy = -vy, vx
            elif direction == Direction.SOUTH:
                vx, vy = -vx, -vy
            elif direction == Direction.WEST:
                vx, vy = vy, -vx

            # Drill center = target - offset
            drill_center = MapPosition(
                x=target_pos.x - vx,
                y=target_pos.y - vy,
            )

            # Validate this position
            if self._validator.validate_placement(
                target_entity_name, drill_center, direction, ghost=True
            ):
                valid_positions.append((drill_center, direction))

        return valid_positions

    def _get_fluid_pipe_positions(
        self, source_entity: "BaseEntity", target_entity_name: str
    ) -> List[Tuple[MapPosition, Optional[Direction]]]:
        """Get positions where pipes can connect to source entity's fluidboxes.

        For fluid-handling entities (boilers, refineries, chemical plants),
        calculates positions where pipes can connect based on fluidbox positions.
        """
        # Check if source has FluidMixin and use its method
        from FactoryVerse.factory.entity.capabilities.fluid import FluidMixin

        try:
            if isinstance(source_entity, FluidMixin):
                # Use the mixin's method if available
                pipe_positions = source_entity.get_pipe_connections()
            else:
                # Fallback to direct prototype access
                proto = source_entity.prototype
                fluidbox_data = (
                    proto.get("fluidbox")
                    or proto.get("output_fluid_box")
                    or proto.get("input_fluid_box")
                )

                if not fluidbox_data:
                    logger.warning(f"Entity {source_entity.name} has no fluidbox data")
                    return []

                # Extract pipe connection positions manually
                from FactoryVerse.factory.prototypes import apply_cardinal_vector

                pipe_connections = fluidbox_data.get("pipe_connections", [])
                if not pipe_connections:
                    logger.warning(
                        f"Entity {source_entity.name} has no pipe connections"
                    )
                    return []

                pipe_positions = []
                source_dir = getattr(source_entity, "direction", Direction.NORTH)

                for connection in pipe_connections:
                    positions = connection.get("positions", [])
                    if not positions:
                        position = connection.get("position")
                        if position:
                            positions = [position]

                    for pos_data in positions:
                        if isinstance(pos_data, list) and len(pos_data) == 2:
                            vec = tuple(pos_data)
                            pipe_positions.append(
                                apply_cardinal_vector(
                                    source_entity.position, vec, source_dir
                                )
                            )

            # Validate all positions
            valid_positions: List[Tuple[MapPosition, Optional[Direction]]] = []
            for pipe_pos in pipe_positions:
                if self._validator.validate_placement(
                    target_entity_name, pipe_pos, None, ghost=True
                ):
                    valid_positions.append((pipe_pos, None))

            return valid_positions

        except Exception as e:
            logger.error(
                f"Error getting pipe positions for {source_entity.name}: {e}"
            )
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
