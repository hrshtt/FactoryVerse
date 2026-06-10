"""
Documentation for Core Types.

This module registers documentation for fundamental types:
- MapPosition: World coordinates
- TilePosition: Integer tile coordinates
- Direction: Cardinal directions (NORTH, EAST, SOUTH, WEST)
- ConnectionType: Connection types for placement puzzles

These types are used throughout the API for positions, orientations,
and spatial relationships.
"""

from FactoryVerse.utils.docs.registry import get_registry
from FactoryVerse.utils.docs.models import Example, ValidationLevel


def _register_types():
    """Register all type documentation."""
    registry = get_registry()

    # =========================================================================
    # MapPosition
    # =========================================================================

    try:
        from FactoryVerse.game.factory.types import MapPosition
        registry.register_type(
            type_cls=MapPosition,
            description="World coordinates with sub-tile precision (floating point x, y). "
            "Used for entity positions, pathfinding targets, and spatial queries.",
            fields={
                "x": "X coordinate (float) - positive is east",
                "y": "Y coordinate (float) - positive is south",
            },
            examples=[
                Example(
                    code="""# Create a position
pos = MapPosition(x=10.5, y=20.5)
print(f"Position: ({pos.x}, {pos.y})")

# Calculate distance
other = MapPosition(x=15.5, y=20.5)
dist = pos.distance(other)  # 5.0

# From dict (common when parsing game data)
pos = MapPosition.from_dict({"x": 10, "y": 20})""",
                    decision_context="Working with map coordinates",
                    expected_outcome="MapPosition object with x, y attributes",
                    validation_level=ValidationLevel.SYNTAX,
                ),
            ],
        )
    except ImportError:
        pass

    # =========================================================================
    # TilePosition
    # =========================================================================

    try:
        from FactoryVerse.game.factory.types import TilePosition
        registry.register_type(
            type_cls=TilePosition,
            description="Integer tile coordinates. Factorio's map is divided into 1x1 tiles. "
            "Used for tile-based queries and footprint calculations.",
            fields={
                "x": "Tile X coordinate (integer)",
                "y": "Tile Y coordinate (integer)",
            },
            examples=[
                Example(
                    code="""# Create tile position
tile = TilePosition(x=5, y=10)

# Convert from MapPosition (truncates to tile)
pos = MapPosition(x=5.7, y=10.3)
tile_x, tile_y = int(pos.x), int(pos.y)  # 5, 10

# Tile-based queries
entity = remote_view.get_entity_at_tile(tile.x, tile.y)""",
                    decision_context="Working with tile coordinates",
                    expected_outcome="TilePosition object with integer x, y",
                    validation_level=ValidationLevel.SYNTAX,
                ),
            ],
        )
    except ImportError:
        pass

    # =========================================================================
    # Direction
    # =========================================================================

    try:
        from FactoryVerse.game.factory.types import Direction
        registry.register_type(
            type_cls=Direction,
            description="Cardinal directions for entity orientation. Factorio uses 8-direction system "
            "internally but most entities only use 4 cardinal directions.",
            examples=[
                Example(
                    code="""# Direction values
Direction.NORTH  # 0 - Up
Direction.EAST   # 2 - Right
Direction.SOUTH  # 4 - Down
Direction.WEST   # 6 - Left

# Use for entity placement
item.place(position, Direction.EAST)

# Check entity direction
drill = reachable_view.get_entity("burner-mining-drill")
if drill.direction == Direction.SOUTH:
    print("Drill facing south")""",
                    decision_context="Orienting entities",
                    expected_outcome="Direction enum member",
                    validation_level=ValidationLevel.SYNTAX,
                ),
                Example(
                    code="""# Direction in placement hints
positions = placement_hints.get_inserter_placement_positions(
    source_entity=chest,
    target_entity=furnace,
    inserter_name="inserter"
)
for pos, direction in positions:
    print(f"Place at {pos} facing {direction.name}")""",
                    decision_context="Understanding insertion direction",
                    expected_outcome="Direction indicates where inserter drops items",
                    validation_level=ValidationLevel.SYNTAX,
                ),
            ],
        )
    except ImportError:
        pass

    # =========================================================================
    # ConnectionType
    # =========================================================================

    try:
        from FactoryVerse.game.agent.placement_hints import ConnectionType
        registry.register_type(
            type_cls=ConnectionType,
            description="Connection types for solving entity placement puzzles. Each type represents "
            "a different way entities can connect (item drop, fluid, wire, etc.). "
            "CRITICAL: ITEM_DROP is for mining drills (push directly to adjacent entities). "
            "INSERTER_REACH is for inserters (pick from ground/belts/entities). "
            "Cannot use inserters with drills as source.",
            examples=[
                Example(
                    code="""# Available connection types
ConnectionType.ITEM_DROP    # Mining drill -> Chest/Belt (drills push directly, no inserters)
ConnectionType.FLUID_PIPE   # Pipe -> Machine/Pipe
ConnectionType.INSERTER_REACH  # Inserter -> Source/Target (picks from ground/belts/entities, NOT drills)
ConnectionType.BELT_FLOW    # Belt -> Belt
ConnectionType.ELECTRIC_WIRE   # Pole -> Pole

# Use with get_connection_positions
positions = placement_hints.get_connection_positions(
    source_entity=drill,
    target_entity_name="iron-chest",
    connection_type=ConnectionType.ITEM_DROP
)""",
                    decision_context="Choosing connection type for placement",
                    expected_outcome="ConnectionType enum member",
                    validation_level=ValidationLevel.SYNTAX,
                ),
            ],
        )
    except ImportError:
        pass

    # =========================================================================
    # GhostPlan (documented here as it's a key response type)
    # =========================================================================

    try:
        from FactoryVerse.game.agent.placement_hints import GhostPlan
        registry.register_type(
            type_cls=GhostPlan,
            description="A validated placement plan ready for commitment via ghost_builder. "
            "Contains entity positions, directions, and validation status.",
            fields={
                "entity_name": "Name of entity to place",
                "positions": "List of (MapPosition, Optional[Direction]) tuples",
                "label": "Unique identifier for the plan",
                "description": "Human-readable description",
                "valid": "True if all positions are validated",
            },
            examples=[
                Example(
                    code="""# GhostPlan from placement_hints
plan = placement_hints.get_placement_line(
    entity_name="transport-belt",
    start=MapPosition(x=0, y=0),
    end=MapPosition(x=10, y=0)
)

# Check validity
if plan.valid:
    print(f"Plan '{plan.label}' is ready")
    print(f"Entity: {plan.entity_name}")
    print(f"Positions: {len(plan.positions)}")

    # Build the plan to create ghosts
    result = await ghost_builder.build_plan(plan)
else:
    print("Plan has invalid positions")

# Re-validate after game state changes
plan.validate(placement_hints.validator)""",
                    decision_context="Working with placement plans",
                    expected_outcome="GhostPlan ready for ghost_builder.build_plan()",
                    validation_level=ValidationLevel.SYNTAX,
                ),
            ],
        )
    except ImportError:
        pass

    # =========================================================================
    # ConnectionPosition (documented here as it's a key response type)
    # =========================================================================

    try:
        from FactoryVerse.game.agent.placement_hints import ConnectionPosition
        registry.register_type(
            type_cls=ConnectionPosition,
            description="A valid position for placing a target entity to connect to a source. "
            "Returned by get_connection_positions().",
            fields={
                "position": "MapPosition where target can be placed",
                "direction": "Required direction for target (or None)",
                "perpendicular_offset": "Alignment metric (0.0 = perfect alignment)",
            },
            examples=[
                Example(
                    code="""# ConnectionPosition from get_connection_positions
positions = placement_hints.get_connection_positions(
    source_entity=drill,
    target_entity_name="iron-chest",
    connection_type=ConnectionType.ITEM_DROP
)

# Positions are sorted by perpendicular_offset (best alignment first)
if positions:
    best = positions[0]
    print(f"Position: {best.position}")
    print(f"Alignment offset: {best.perpendicular_offset}")
    if best.direction:
        print(f"Required direction: {best.direction}")""",
                    decision_context="Understanding connection results",
                    expected_outcome="ConnectionPosition with placement details",
                    validation_level=ValidationLevel.SYNTAX,
                ),
            ],
        )
    except ImportError:
        pass


# Register on import
_register_types()
