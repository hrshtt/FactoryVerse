"""
Documentation for Placement Classes.

This module registers documentation for spatial reasoning:
- PlacementHints: Pure spatial reasoning for entity placement
- PlacementValidator: Validates placement positions
- GhostPlan: Validated placement plans

The placement system mirrors Factorio's visual feedback (green/red placement
indicators, connection lines) but exposes it as structured data for agents.
"""

from FactoryVerse.utils.docs.registry import get_registry
from FactoryVerse.utils.docs.models import Example, ErrorCase, ValidationLevel


def _register_placement():
    """Register all placement class documentation."""
    registry = get_registry()

    # =========================================================================
    # PlacementHints
    # =========================================================================

    from FactoryVerse.game.agent.placement_hints import PlacementHints

    registry.register_class(
        cls=PlacementHints,
        accessor_name="placement_hints",
        description="Spatial reasoning engine for entity placement. Generates validated GhostPlan "
        "objects for lines, connections, and pole coverage. No side effects - validation only.",
        decision_context="Use placement_hints to plan entity layouts before placement. Get validated "
        "positions for belts, pipes, poles, and connection puzzles (drill→furnace, inserter placement).",
        notes=[
            "Pure computation - never mutates game state",
            "Uses Lua mod for engine values (drop_position, fluidbox, wire_connector)",
            "Returns GhostPlan objects ready for ghost_builder.commit()",
            "Validates positions against current game state",
        ],
        related_classes=["GhostBuilderAction", "PlacementValidator"],
    )
    registry.register_required_class(PlacementHints)

    registry.register_method(
        cls=PlacementHints,
        method_name="get_placement_line",
        description="Calculate a line of entities from start to end with inferred direction.",
        examples=[
            Example(
                code="""# Plan a belt line from (0,0) to (10,0)
plan = placement_hints.get_placement_line(
    entity_name="transport-belt",
    start=MapPosition(x=0, y=0),
    end=MapPosition(x=10, y=0)
)
print(f"Planned {len(plan.positions)} belts")
print(f"Valid: {plan.valid}")

# Commit plan to create ghosts
if plan.valid:
    await ghost_builder.commit(plan)""",
                decision_context="Planning belt/pipe lines",
                expected_outcome="Returns GhostPlan with validated positions",
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# Plan a pipe line
pipe_plan = placement_hints.get_placement_line(
    entity_name="pipe",
    start=MapPosition(x=0, y=0),
    end=MapPosition(x=0, y=20),
    validate=True  # Default, validates all positions
)
# Check for invalid positions
invalid_count = sum(1 for pos, dir in pipe_plan.positions if not pipe_plan.valid)
print(f"Invalid positions: {invalid_count}")""",
                decision_context="Planning fluid transport lines",
                expected_outcome="Returns validated pipe positions",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Direction is inferred from drag vector (horizontal→EAST/WEST, vertical→NORTH/SOUTH)",
            "Use validate=False to skip validation (faster but may have invalid positions)",
            "plan.validate(validator) can re-validate after state changes",
        ],
    )

    registry.register_method(
        cls=PlacementHints,
        method_name="get_connection_positions",
        description="Find valid positions where target entity can connect to source entity.",
        examples=[
            Example(
                code="""# ITEM_DROP: Place furnace directly at drill's drop position
# No inserter needed - drill outputs directly into furnace!

drill = reachable_view.get_entity("burner-mining-drill")
positions = placement_hints.get_connection_positions(
    source_entity=drill,
    target_entity_name="stone-furnace",
    connection_type=ConnectionType.ITEM_DROP
)

if positions:
    # Positions sorted by perpendicular_offset (lower = better aligned)
    best = positions[0]
    print(f"Furnace position: {best.position}")

    # Place furnace at drill's drop position - it receives ore directly
    item = inventory.get_item("stone-furnace")
    item.place(best.position, best.direction)
    # Furnace will automatically receive ore from drill - no inserter needed!""",
                decision_context="Placing furnace to receive drill output directly (most efficient)",
                expected_outcome="Returns List[ConnectionPosition] - furnace receives ore without inserters",
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# FLUID_PIPE: Returns List[ConnectionPosition]
# Direction is required for pipe connections

boiler = reachable_view.get_entity("boiler")
positions = placement_hints.get_connection_positions(
    source_entity=boiler,
    target_entity_name="pipe",
    connection_type=ConnectionType.FLUID_PIPE
)

for pos in positions:
    # Direction indicates which way pipe should face
    print(f"Pipe at {pos.position}, direction: {pos.direction}")

# Place first pipe
if positions:
    item = inventory.get_item("pipe")
    item.place(positions[0].position, positions[0].direction)""",
                decision_context="Connecting fluid network to machines (FLUID_PIPE)",
                expected_outcome="Returns List[ConnectionPosition] with required directions",
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# ELECTRIC_WIRE: Returns List[WireConnectionPosition]
# WireConnectionPosition extends ConnectionPosition with:
#   - wire_distance: float (actual distance in tiles)
#   - wire_distance_utilization: float (0.0-1.0, ratio of max distance)

pole = reachable_view.get_entity("medium-electric-pole")
wire_positions = placement_hints.get_connection_positions(
    source_entity=pole,
    target_entity_name="medium-electric-pole",
    connection_type=ConnectionType.ELECTRIC_WIRE
)

# WireConnectionPosition has extra wire-specific fields
for pos in wire_positions:
    print(f"Position: {pos.position}")
    print(f"  Wire distance: {pos.wire_distance:.1f} tiles")
    print(f"  Utilization: {pos.wire_distance_utilization:.1%}")
    # e.g., distance=7.2, utilization=0.8 means 80% of 9.0 tile max

# Choose position that uses ~70-80% of wire distance (efficient spacing)
optimal = [p for p in wire_positions if 0.7 <= p.wire_distance_utilization <= 0.85]
if optimal:
    item = inventory.get_item("medium-electric-pole")
    item.place(optimal[0].position)""",
                decision_context="Extending power network (ELECTRIC_WIRE returns WireConnectionPosition)",
                expected_outcome="Returns List[WireConnectionPosition] with distance metrics",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        error_cases=[
            ErrorCase(
                exception="EntityValidationError",
                when="Source entity doesn't support the connection type",
                resolution="Check entity type - only drills support ITEM_DROP, only poles support ELECTRIC_WIRE, etc.",
            ),
        ],
        decision_points=[
            "ITEM_DROP: mining-drill → furnace/chest/belt (furnace is most common - direct output, no inserter needed!)",
            "FLUID_PIPE: fluid machines (boiler, pump, etc.) → pipe → Returns ConnectionPosition",
            "ELECTRIC_WIRE: electric poles → electric poles → Returns WireConnectionPosition",
            "Lower perpendicular_offset = better alignment with source entity",
            "For ELECTRIC_WIRE, use wire_distance_utilization to optimize pole spacing",
        ],
    )

    registry.register_method(
        cls=PlacementHints,
        method_name="get_inserter_placement_positions",
        description="Find valid inserter positions to transfer items between two entities.",
        examples=[
            Example(
                code="""# Find inserter position from chest to furnace
chest = reachable_view.get_entity("iron-chest")
furnace = reachable_view.get_entity("stone-furnace")

positions = placement_hints.get_inserter_placement_positions(
    source_entity=chest,
    target_entity=furnace,
    inserter_name="inserter"
)

if positions:
    pos, direction = positions[0]
    print(f"Place inserter at {pos} facing {direction}")

    # Create and place inserter
    item = inventory.get_item("inserter")
    if item:
        item.place(pos, direction)""",
                decision_context="Automating item transfer between entities",
                expected_outcome="Returns list of (MapPosition, Direction) tuples",
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# Find long-handed inserter positions (longer reach)
positions = placement_hints.get_inserter_placement_positions(
    source_entity=chest,
    target_entity=furnace,
    inserter_name="long-handed-inserter"
)
# Long-handed inserters can reach further, more options""",
                decision_context="Using long-reach inserters for larger gaps",
                expected_outcome="Returns positions with appropriate reach",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Inserter direction points toward drop-off (target)",
            "Different inserter types have different reach",
            "Consider stack inserters for higher throughput",
        ],
    )

    registry.register_method(
        cls=PlacementHints,
        method_name="get_pole_line",
        description="Plan a line of electric poles at maximum wire distance intervals.",
        examples=[
            Example(
                code="""# Plan pole line from start to end
plan = placement_hints.get_pole_line(
    start=MapPosition(x=0, y=0),
    end=MapPosition(x=50, y=0),
    pole_name="medium-electric-pole"
)

print(f"Need {len(plan.positions)} poles")
# Poles are spaced at max wire distance (9 for medium poles)

if plan.valid:
    await ghost_builder.commit(plan)""",
                decision_context="Running power line across distance",
                expected_outcome="Returns GhostPlan with optimally spaced poles",
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# Compare pole types for coverage
for pole_type in ["small-electric-pole", "medium-electric-pole", "big-electric-pole"]:
    plan = placement_hints.get_pole_line(
        start=MapPosition(x=0, y=0),
        end=MapPosition(x=100, y=0),
        pole_name=pole_type,
        validate=False  # Skip validation for comparison
    )
    print(f"{pole_type}: {len(plan.positions)} poles needed")""",
                decision_context="Optimizing power line cost",
                expected_outcome="Shows pole count comparison",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Pole spacing based on max wire distance (small=7.5, medium=9, big=30, substation=18)",
            "Big poles are good for long distance, small/medium for local distribution",
        ],
    )

    registry.register_method(
        cls=PlacementHints,
        method_name="get_pole_coverage_position",
        description="Find a single pole position that covers ALL given entities.",
        examples=[
            Example(
                code="""# Find pole position to power multiple machines
machines = reachable_view.get_entities("assembling-machine-1")

pos = placement_hints.get_pole_coverage_position(
    entities_to_power=machines,
    pole_name="medium-electric-pole"
)

if pos:
    print(f"Place pole at {pos} to cover all machines")
else:
    print("Entities too spread out for single pole")""",
                decision_context="Minimizing poles for compact areas",
                expected_outcome="Returns MapPosition or None if impossible",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Returns None if entities spread beyond supply diameter",
            "Substations have largest supply area (9 tile radius)",
            "Consider get_pole_coverage_plan() for multiple poles",
        ],
    )

    registry.register_method(
        cls=PlacementHints,
        method_name="get_pole_coverage_plan",
        description="Find minimum poles to cover all entities using greedy set cover algorithm.",
        examples=[
            Example(
                code="""# Plan poles to power scattered entities
entities = reachable_view.get_entities()
electric_entities = [e for e in entities if hasattr(e, 'electric_network_id')]

plan, uncovered = placement_hints.get_pole_coverage_plan(
    entities_to_power=electric_entities,
    pole_name="medium-electric-pole"
)

print(f"Need {len(plan.positions)} poles")
if uncovered:
    print(f"Warning: {len(uncovered)} entities cannot be covered")

if plan.valid:
    await ghost_builder.commit(plan)""",
                decision_context="Optimal pole placement for arbitrary layouts",
                expected_outcome="Returns (GhostPlan, list of uncovered entities)",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Greedy algorithm - not globally optimal but good enough",
            "Returns uncovered entities if some can't be reached",
            "Consider splitting into smaller groups if many uncovered",
        ],
    )

    registry.register_method(
        cls=PlacementHints,
        method_name="get_underground_segment",
        description="Plan an underground belt or pipe segment between two points.",
        examples=[
            Example(
                code="""# Plan underground belt to cross obstacle
plan = placement_hints.get_underground_segment(
    entity_name="underground-belt",
    start=MapPosition(x=0, y=0),
    end=MapPosition(x=4, y=0),
    direction=Direction.EAST
)

# Plan includes entry and exit belts with correct directions
print(f"Entry at {plan.positions[0]}")
print(f"Exit at {plan.positions[1]}")""",
                decision_context="Bypassing obstacles with underground transport",
                expected_outcome="Returns GhostPlan with entry/exit positions",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        error_cases=[
            ErrorCase(
                exception="ValueError",
                when="Distance exceeds underground max distance",
                resolution="Use shorter segments or upgrade belt tier",
            ),
        ],
        decision_points=[
            "Max distances: underground-belt=4, fast=6, express=8, pipe-to-ground=10",
            "Exit direction is automatically set to opposite of entry",
        ],
    )

    registry.register_method(
        cls=PlacementHints,
        method_name="evaluate_pole_placement",
        description="Dry-run evaluation of a pole placement position (no actual placement).",
        examples=[
            Example(
                code="""# Evaluate a potential pole position
result = placement_hints.evaluate_pole_placement(
    position=MapPosition(x=10, y=10),
    pole_name="medium-electric-pole",
    source_pole=existing_pole,  # Optional: check wire connection
    reachable_view=reachable_view  # Optional: check entity coverage
)

print(f"Valid placement: {result.is_valid_placement}")
print(f"Entities powered: {result.entities_powered_count}")
print(f"Connects to source: {result.connects_to_source}")
print(f"Distance to source: {result.distance_to_source}")""",
                decision_context="Evaluating pole positions before commitment",
                expected_outcome="Returns PolePlacementResult with detailed metrics",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "No side effects - purely evaluates position",
            "Useful for comparing multiple candidate positions",
            "Checks wire connectivity, power coverage, and placement validity",
        ],
    )

    registry.register_method(
        cls=PlacementHints,
        method_name="validator",
        description="Access the PlacementValidator for direct validation operations.",
        examples=[
            Example(
                code="""# Validate a single position
valid = placement_hints.validator.validate_placement(
    entity_name="stone-furnace",
    position=MapPosition(x=5, y=5),
    direction=Direction.NORTH,
    ghost=True
)
print(f"Can place furnace: {valid}")""",
                decision_context="Single position validation",
                expected_outcome="Returns PlacementValidator instance",
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# Batch validate positions
positions = [MapPosition(x=i, y=0) for i in range(10)]
results = placement_hints.validator.validate_batch(
    entity_name="transport-belt",
    positions=positions,
    directions=[Direction.EAST] * 10,
    ghost=True
)

valid_count = sum(results)
print(f"{valid_count}/{len(results)} positions valid")""",
                decision_context="Efficient batch validation",
                expected_outcome="Returns list of booleans",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Use validator directly for custom validation logic",
            "Batch validation is more efficient than individual calls",
            "ghost=True validates for ghost placement (different collision rules)",
        ],
    )


def _register_ghost_builder():
    """Register GhostBuilderAction documentation."""
    registry = get_registry()

    # =========================================================================
    # GhostBuilderAction
    # =========================================================================

    from FactoryVerse.game.agent.ghost_builder import GhostBuilderAction

    registry.register_class(
        cls=GhostBuilderAction,
        accessor_name="ghost_builder",
        description="Orchestrates ghost placement and building. Converts GhostPlan objects "
        "into placed ghosts, then builds them into real entities.",
        decision_context="Use ghost_builder to commit validated GhostPlan objects from placement_hints. "
        "Also use for building existing ghost entities on the map.",
        notes=[
            "Works with both GhostPlan objects and ghost entities from queries",
            "Handles walking to positions automatically",
            "Use strict=True to validate inventory before building",
        ],
        related_classes=["PlacementHints", "GhostPlan"],
    )
    registry.register_required_class(GhostBuilderAction)

    registry.register_method(
        cls=GhostBuilderAction,
        method_name="build_ghosts",
        description="Build ghost entities in bulk by walking to each and placing real entities.",
        examples=[
            Example(
                code="""# Get ghosts and build them
ghosts = reachable_view.get_ghosts()
result = await ghost_builder.build_ghosts(ghosts, count=10)

print(f"Built: {result['built_count']}")
print(f"Failed: {result['failed_count']}")""",
                decision_context="Building existing ghost entities",
                expected_outcome="Returns dict with built_count, failed_count, built_ghosts, failed_ghosts",
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# Build with strict inventory validation
ghosts = remote_view.get_ghosts("SELECT * FROM ghost WHERE ghost_name = 'transport-belt'")
result = await ghost_builder.build_ghosts(ghosts, strict=True)

if "error" in result:
    print(f"Insufficient items: {result['error']}")
else:
    print(f"Built {result['built_count']} belts")""",
                decision_context="Building ghosts with inventory validation",
                expected_outcome="Returns error if items missing, otherwise builds",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Use count to limit how many ghosts to build in one call",
            "Use strict=True to fail fast if inventory is insufficient",
            "Works with ghosts from reachable_view, remote_view, or any source",
        ],
    )

    registry.register_method(
        cls=GhostBuilderAction,
        method_name="build_ghost",
        description="Build a single ghost entity. Convenience wrapper for build_ghosts.",
        examples=[
            Example(
                code="""# Build a single ghost
ghost = reachable_view.get_ghosts("stone-furnace")[0]
success = await ghost_builder.build_ghost(ghost)
if success:
    print("Furnace ghost built!")""",
                decision_context="Building a single specific ghost",
                expected_outcome="Returns True if successfully built, False otherwise",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Use for single ghost when you only need one",
            "Use build_ghosts() for multiple ghosts (more efficient)",
        ],
    )

    registry.register_method(
        cls=GhostBuilderAction,
        method_name="build_plan",
        description="Build a GhostPlan by placing ghosts at all positions.",
        examples=[
            Example(
                code="""# Commit a validated placement plan
plan = placement_hints.get_placement_line(
    "transport-belt",
    start=MapPosition(x=0, y=0),
    end=MapPosition(x=10, y=0)
)

if plan.valid:
    result = await ghost_builder.build_plan(plan)
    print(f"Placed {result.get('placed_count', 0)} ghosts")""",
                decision_context="Committing a GhostPlan from placement_hints",
                expected_outcome="Places ghosts at all plan positions",
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# Build plan with strict validation
plan = placement_hints.get_pole_line(
    start=MapPosition(x=0, y=0),
    end=MapPosition(x=50, y=0),
    pole_name="medium-electric-pole"
)

result = await ghost_builder.build_plan(plan, strict=True)
if "error" in result:
    print(f"Cannot build: {result['error']}")""",
                decision_context="Building plan with inventory check",
                expected_outcome="Validates inventory before placing",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        error_cases=[
            ErrorCase(
                exception="KeyError",
                when="GhostPlan is invalid (validation failed)",
                resolution="Re-validate the plan or use a fresh plan from placement_hints",
            ),
        ],
        decision_points=[
            "Always check plan.valid before calling build_plan",
            "Use strict=True for early failure on inventory issues",
            "This is the main way to commit placement_hints results",
        ],
    )


# Register on import
_register_placement()
_register_ghost_builder()
