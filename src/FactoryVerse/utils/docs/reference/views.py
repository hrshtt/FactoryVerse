"""
Documentation for View Classes.

This module registers documentation for the dual-view system:
- ReachableView: Nearby entities (full mutation access)
- RemoteView: Map-wide queries via DuckDB (read-only)

The view system mirrors how human players see and interact with Factorio:
- Nearby = can interact (place, pick up, set recipes)
- Far away = can see (plan routes, find resources)
"""

from FactoryVerse.utils.docs.registry import get_registry
from FactoryVerse.utils.docs.models import Example, ErrorCase, ValidationLevel


def _register_views():
    """Register all view class documentation."""
    registry = get_registry()

    # =========================================================================
    # ReachableView
    # =========================================================================

    from FactoryVerse.game.agent.reachable_view import ReachableView

    registry.register_class(
        cls=ReachableView,
        accessor_name="reachable_view",
        description="Query interface for nearby entities and resources within agent's interaction range. "
        "Returns entities with REACHABLE view (full mutation access).",
        decision_context="Use reachable_view when you need to interact with entities (set recipes, "
        "insert items, read inventory). Data is always fresh from the game.",
        notes=[
            "Always fetches fresh data - no caching",
            "Ghosts are included by default for spatial awareness",
            "Returned entities have full affordances (inspect, place, configure)",
            "Resource queries return minable resources (ores, trees, rocks)",
        ],
        related_classes=["RemoteView", "MovementAction"],
    )
    registry.register_required_class(ReachableView)

    registry.register_method(
        cls=ReachableView,
        method_name="get_entity",
        description="Get a single entity matching criteria. Returns entity with REACHABLE view.",
        examples=[
            Example(
                code="""# Find a specific furnace by name
furnace = reachable_view.get_entity("stone-furnace")
if furnace:
    print(f"Found furnace at {furnace.position}")
    # REACHABLE view allows inspection
    state = furnace.inspect()""",
                decision_context="Finding a nearby entity to interact with",
                expected_outcome="Returns BaseEntity with REACHABLE view or None",
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# Find entity at specific position
drill = reachable_view.get_entity(
    "burner-mining-drill",
    position=MapPosition(x=10, y=10)
)""",
                decision_context="Verifying entity at known location",
                expected_outcome="Returns entity at exact position or None",
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# Find entity with specific recipe
assembler = reachable_view.get_entity(
    "assembling-machine-1",
    options={"recipe": "iron-gear-wheel"}
)""",
                decision_context="Finding entity configured for specific production",
                expected_outcome="Returns assembler with matching recipe or None",
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# Find only ghost entities
ghost = reachable_view.get_entity(
    "stone-furnace",
    options={"ghosts_only": True}
)
if ghost:
    print(f"Ghost furnace at {ghost.position}")
    # Can build the ghost
    await ghost.build()""",
                decision_context="Finding ghosts to build or remove",
                expected_outcome="Returns ghost entity or None",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Use get_entity() for single result when you expect at most one",
            "Use get_entities() when you need to iterate over multiple",
            "Pass options={'include_ghosts': False} to exclude ghosts",
        ],
    )

    registry.register_method(
        cls=ReachableView,
        method_name="get_entities",
        description="Get all entities matching criteria. Returns list with REACHABLE view.",
        examples=[
            Example(
                code="""# Get all nearby inserters
inserters = reachable_view.get_entities("inserter")
print(f"Found {len(inserters)} inserters")
for ins in inserters:
    print(f"  {ins.name} at {ins.position}")""",
                decision_context="Finding all entities of a type to process",
                expected_outcome="Returns list of BaseEntity (may be empty)",
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# Get all entities (no filter)
all_entities = reachable_view.get_entities()
# Group by type
from collections import Counter
counts = Counter(e.name for e in all_entities)
for name, count in counts.most_common(5):
    print(f"  {name}: {count}")""",
                decision_context="Surveying nearby area",
                expected_outcome="Returns all entities in interaction range",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Returns empty list if no matches (never None)",
            "Filter by entity_type for broader categories",
            "Use options={'status': 'no_power'} to find unpowered entities "
            "(hyphens are normalized to underscores, so 'no-power' also works; "
            "raw int status codes are accepted too)",
        ],
    )

    registry.register_method(
        cls=ReachableView,
        method_name="get_ghosts",
        description="Get ghost entities matching criteria. Convenience wrapper for get_entities with ghosts_only=True.",
        examples=[
            Example(
                code="""# Get all ghosts to build
ghosts = reachable_view.get_ghosts()
for ghost in ghosts:
    print(f"Ghost {ghost.name} at {ghost.position}")
    # Build each ghost
    await ghost.build()""",
                decision_context="Building all planned structures",
                expected_outcome="Returns list of ghost entities",
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# Get ghosts of specific type
belt_ghosts = reachable_view.get_ghosts("transport-belt")
print(f"Found {len(belt_ghosts)} belt ghosts to build")""",
                decision_context="Building specific entity type ghosts",
                expected_outcome="Returns filtered ghost list",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Use get_ghosts() when specifically looking for unbuild structures",
            "Ghosts can be built with entity.build() method",
        ],
    )

    registry.register_method(
        cls=ReachableView,
        method_name="get_resource",
        description="Get a single resource (ore, tree, rock) matching criteria.",
        examples=[
            Example(
                code="""# Find iron ore to mine
ore = reachable_view.get_resource("iron-ore")
if ore:
    print(f"Iron ore at {ore.position}, amount: {ore.amount}")
    # Can mine directly
    items = await ore.mine(max_count=10)""",
                decision_context="Finding mineable resources",
                expected_outcome="Returns BaseResource with mining capability or None",
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# Find resource at specific position
coal = reachable_view.get_resource("coal", MapPosition(x=5, y=5))""",
                decision_context="Verifying resource at known location",
                expected_outcome="Returns resource at position or None",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Resources include ores (iron-ore, copper-ore, coal, stone)",
            "Also includes trees and rocks (type='entity')",
            "Use get_resources() for multiple results",
        ],
    )

    registry.register_method(
        cls=ReachableView,
        method_name="get_resources",
        description="Get resources matching criteria. Returns ResourceOrePatch for grouped ores.",
        examples=[
            Example(
                code="""# Get all ore patches
ores = reachable_view.get_resources(resource_type="ore")
for patch in ores:
    print(f"{patch.name}: {patch.total} total")""",
                decision_context="Surveying available resources",
                expected_outcome="Returns list of resources/patches",
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# Get trees and rocks
entities = reachable_view.get_resources(resource_type="entity")
trees = [r for r in entities if "tree" in r.name.lower()]
rocks = [r for r in entities if "rock" in r.name.lower()]
print(f"Trees: {len(trees)}, Rocks: {len(rocks)}")""",
                decision_context="Finding harvestable environment objects",
                expected_outcome="Returns trees and rocks as BaseResource",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Use resource_type='ore' for ore patches only",
            "Use resource_type='entity' for trees/rocks",
            "Multiple ore tiles of same type are consolidated into ResourceOrePatch",
        ],
    )

    # =========================================================================
    # RemoteView
    # =========================================================================

    from FactoryVerse.game.agent.remote_view import RemoteView

    # Lifecycle methods are internal - not part of agent's public API
    remote_view_internal_methods = {
        "start",      # Lifecycle: start real-time sync
        "stop",       # Lifecycle: stop sync
        "load",       # Lifecycle: load initial snapshot
        "flush",      # Internal: flush pending updates
        "rebuild",    # Internal: rebuild database
        "sync_state", # Internal: sync state management
        "is_loaded",  # Internal: loading state check
        "debug_info", # Internal: debugging
        "count_ghosts",  # Covered by get_ghosts + len()
    }

    registry.register_class(
        cls=RemoteView,
        accessor_name="remote_view",
        description="DuckDB-backed map queries for entities across the entire map. Provides read-only "
        "access via SQL queries. Entities have REMOTE view (walk_to, inspect only).",
        decision_context="Use remote_view for map-wide planning: finding resources, counting entities, "
        "spatial queries. Data is synced via UDP for near real-time updates.",
        notes=[
            "Read-only view - cannot modify entities directly",
            "Entities automatically convert to REACHABLE after walk_to()",
            "Uses DuckDB for fast spatial queries",
            "Lifecycle methods (load, start, stop) are managed by the runtime",
        ],
        related_classes=["ReachableView", "MovementAction"],
        exclude_methods=remote_view_internal_methods,
    )
    registry.register_required_class(RemoteView, exclude_methods=remote_view_internal_methods)

    registry.register_method(
        cls=RemoteView,
        method_name="get_entities",
        description="Execute SQL query and return entity instances with REMOTE view.",
        examples=[
            Example(
                code="""# Find all mining drills on the map
drills = remote_view.get_entities('''
    SELECT * FROM map_entity
    WHERE entity_name = 'burner-mining-drill'
''')
print(f"Found {len(drills)} mining drills")

# Navigate to first one
if drills:
    await drills[0].walk_to()
    # After walk_to, entity becomes REACHABLE""",
                decision_context="Finding entities anywhere on the map",
                expected_outcome="Returns list of BaseEntity with REMOTE view",
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# Find entities in a specific area
entities = remote_view.get_entities('''
    SELECT * FROM map_entity
    WHERE position_x BETWEEN 0 AND 100
    AND position_y BETWEEN 0 AND 100
''')""",
                decision_context="Querying entities in a rectangular area",
                expected_outcome="Returns entities within bounds",
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# Find closest furnace to a position
target_x, target_y = 50, 50
furnaces = remote_view.get_entities(f'''
    SELECT *,
           SQRT(POW(position_x - {target_x}, 2) + POW(position_y - {target_y}, 2)) as dist
    FROM map_entity
    WHERE entity_name = 'stone-furnace'
    ORDER BY dist
    LIMIT 5
''')""",
                decision_context="Finding nearest entities to a point",
                expected_outcome="Returns entities sorted by distance",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "REMOTE entities have limited affordances (walk_to, inspect)",
            "Use SQL WHERE clauses for efficient filtering",
            "After walk_to(), entity becomes REACHABLE with full access",
        ],
    )

    registry.register_method(
        cls=RemoteView,
        method_name="find_water",
        description="Find water-tile centers on the map as search hints. Results are "
        "not walkable destinations and are not validated offshore-pump anchors. "
        "Terrain affordance — never probe placements to discover terrain.",
        examples=[
            Example(
                code="""# Nearest water to my position
pos = walking.current_position
water = remote_view.find_water(near=pos, radius=120)
if water:
    closest = water[0]
    print(f"Water at ({closest['x']}, {closest['y']}), {closest['distance']:.1f} tiles away")
else:
    # Distinguish 'no water' from 'stale snapshot' before concluding
    freshness = remote_view.query("SELECT MAX(tick) AS t FROM chunk_snapshot_meta")
    print(f"No water in range; snapshot tick {freshness[0]['t']}")""",
                decision_context="Finding a water cluster before resolving a pump anchor",
                expected_outcome=(
                    "List of water-tile search hints sorted by distance, or []; "
                    "do not walk to or place at a returned tile"
                ),
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Empty list + stale chunk_snapshot_meta tick means OLD DATA, not 'no water'",
            "Never pass a returned water-tile position to walking.walk_to()",
            "Resolve placement_hints.find_offshore_pump_sites() before travelling or placing",
        ],
    )

    registry.register_method(
        cls=RemoteView,
        method_name="get_entity",
        description="Execute SQL with LIMIT 1 and return single entity.",
        examples=[
            Example(
                code="""# Find any available furnace
furnace = remote_view.get_entity('''
    SELECT * FROM map_entity
    WHERE entity_name = 'stone-furnace'
    LIMIT 1
''')
if furnace:
    await furnace.walk_to()""",
                decision_context="Finding any entity of a type",
                expected_outcome="Returns single BaseEntity or None",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Convenience method for single result queries",
            "LIMIT 1 is added if not present",
        ],
    )

    registry.register_method(
        cls=RemoteView,
        method_name="get_resources",
        description="Execute SQL against resource tables and return resource instances.",
        examples=[
            Example(
                code="""# Find all iron ore on the map
iron = remote_view.get_resources('''
    SELECT * FROM resource_tile
    WHERE name = 'iron-ore'
''')
print(f"Found {len(iron)} iron ore tiles")""",
                decision_context="Locating resource deposits",
                expected_outcome="Returns list of BaseResource with REMOTE view",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
    )

    registry.register_method(
        cls=RemoteView,
        method_name="get_ghosts",
        description="Execute SQL against ghost table and return ghost entities.",
        examples=[
            Example(
                code="""# Find all planned but unbuilt structures
ghosts = remote_view.get_ghosts('''
    SELECT * FROM ghost
    WHERE ghost_name LIKE '%assembling%'
''')
print(f"Found {len(ghosts)} assembler ghosts")""",
                decision_context="Finding blueprint ghosts to build",
                expected_outcome="Returns list of ghost entities",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
    )

    registry.register_method(
        cls=RemoteView,
        method_name="query",
        description="Execute raw SQL query and return list of dicts.",
        examples=[
            Example(
                code="""# Get entity counts by type
results = remote_view.query('''
    SELECT entity_name, COUNT(*) as count
    FROM map_entity
    GROUP BY entity_name
    ORDER BY count DESC
    LIMIT 10
''')
for row in results:
    print(f"{row['entity_name']}: {row['count']}")""",
                decision_context="Custom aggregation queries",
                expected_outcome="Returns list of row dictionaries",
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# Check if area is clear for building
clear = len(remote_view.query('''
    SELECT 1 FROM map_entity
    WHERE position_x BETWEEN 10 AND 15
    AND position_y BETWEEN 10 AND 15
    LIMIT 1
''')) == 0
print(f"Area is {'clear' if clear else 'occupied'}")""",
                decision_context="Checking area availability",
                expected_outcome="Returns empty list if area is clear",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Use for aggregations, counts, and existence checks",
            "Use get_entities() when you need entity objects",
        ],
    )

    registry.register_method(
        cls=RemoteView,
        method_name="count_entities",
        description="Count entities, optionally filtered by name.",
        examples=[
            Example(
                code="""# Count all entities
total = remote_view.count_entities()
print(f"Total entities: {total}")

# Count specific type
drills = remote_view.count_entities("burner-mining-drill")
print(f"Mining drills: {drills}")""",
                decision_context="Quick entity counts without full query",
                expected_outcome="Returns integer count",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
    )

    registry.register_method(
        cls=RemoteView,
        method_name="is_tile_occupied",
        description="Fast check if a tile is occupied by any entity.",
        examples=[
            Example(
                code="""# Check before placing
if not remote_view.is_tile_occupied(5, 10):
    print("Tile is clear for placement")
else:
    print("Tile is occupied")""",
                decision_context="Checking tile availability before placement",
                expected_outcome="Returns True/False",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "O(1) lookup using footprint_tiles index",
            "Faster than get_entity_at_tile() for existence check",
        ],
    )

    registry.register_method(
        cls=RemoteView,
        method_name="get_entity_at_tile",
        description="Get entity occupying a specific tile (uses footprint lookup).",
        examples=[
            Example(
                code="""# Find what's at a tile
entity = remote_view.get_entity_at_tile(5, 10)
if entity:
    print(f"Tile occupied by {entity.name}")
else:
    print("Tile is empty")""",
                decision_context="Identifying entity at known tile",
                expected_outcome="Returns BaseEntity or None",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
    )

    registry.register_method(
        cls=RemoteView,
        method_name="get_entities_in_tile_area",
        description="Get all entities with footprints overlapping a rectangular tile area.",
        examples=[
            Example(
                code="""# Get entities in a 10x10 area
entities = remote_view.get_entities_in_tile_area(0, 0, 9, 9)
print(f"Found {len(entities)} entities in area")

# Filter by type
inserters = remote_view.get_entities_in_tile_area(
    0, 0, 9, 9,
    entity_name="inserter"
)""",
                decision_context="Querying entities in tile-aligned area",
                expected_outcome="Returns list of entities in area",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Uses tile-based indexing for efficiency",
            "Includes entities whose footprints overlap the area",
        ],
    )

    registry.register_method(
        cls=RemoteView,
        method_name="get_entities_at_anchor_tile",
        description="Get entities whose anchor (center) is at a specific tile.",
        examples=[
            Example(
                code="""# Find entities centered at tile
entities = remote_view.get_entities_at_anchor_tile(5, 10)
# Different from get_entity_at_tile which checks footprint overlap""",
                decision_context="Finding entities by their center position",
                expected_outcome="Returns list of entities anchored at tile",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
    )

    registry.register_method(
        cls=RemoteView,
        method_name="get_power_networks",
        description="Per-network power census from the latest power sample: anchor "
        "pole, pole/member counts, production/consumption/storage, headroom ratio, "
        "per-prototype breakdowns, and low_power/no_power member counts.",
        examples=[
            Example(
                code="""# Survey every electric network's supply vs demand
report = remote_view.get_power_networks()
if report.sample_tick is None:
    print("No power sample yet")
else:
    for net in report.networks:
        print(net.anchor_pole_name, net.production_w, net.consumption_w)
        print(f"  {net.no_power_count} no_power, {net.low_power_count} low_power")
    print(report.freshness_note)""",
                decision_context="Checking whether the factory's networks are over/under-supplied",
                expected_outcome="Returns PowerNetworksReport (sample_tick None if no sample ingested)",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Engine network_id is ephemeral (renumbers on merge/split) — the anchor pole is the durable reference",
            "headroom_ratio is production/consumption, or None when consumption is 0",
            "low_power/no_power counts use map_entity's as-of-write electric_network_id (see freshness_note)",
        ],
    )

    registry.register_method(
        cls=RemoteView,
        method_name="diagnose_power",
        description="Diagnose why an entity is unpowered (or confirm it is fine) in one "
        "call: status -> pole coverage -> network generation -> undersupply -> upstream "
        "generator starvation.",
        examples=[
            Example(
                code="""# Why is this assembler dark?
diag = remote_view.diagnose_power("assembling-machine-1", pos)
print(diag.verdict)       # e.g. 'not_covered_by_any_pole'
print(diag.explanation)   # human-readable, with live caveats
print(diag.production_w, diag.consumption_w)""",
                decision_context="Triaging a no_power / low_power entity without a manual multi-query walk",
                expected_outcome="Returns PowerDiagnosis with a verdict, explanation, and supporting numbers",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "verdict is one of working/not_covered_by_any_pole/network_has_no_generation/"
            "network_undersupplied/upstream_generator_starved/no_status_data/entity_not_found/non_electric_or_no_issue",
            "A fuel-starved generator still reports 'working' — the explanation flags this",
            "Poles report nil status; diagnosing a pole returns non_electric_or_no_issue",
        ],
    )

    # =========================================================================
    # VerifyView — live confirmation (the DB says WHICH; verify says IS-IT-TRUE)
    # =========================================================================

    from FactoryVerse.game.agent.verify_view import VerifyView

    registry.register_class(
        cls=VerifyView,
        accessor_name="verify",
        description="Live engine confirmation of power / coverage facts. The snapshot DB "
        "answers WHICH poles/entities exist; verify answers IS IT TRUE RIGHT NOW via live "
        "reads. Positions/statuses/network-ids are live at call time; supply distances and "
        "collision boxes are prototype-derived (static).",
        decision_context="Use verify before committing a build to a pole spine, or to "
        "confirm an entity is actually powered. supply_coverage previews coverage geometry "
        "(including an as-if-placed proposed_pole) so a fractional-tile miss is visible "
        "BEFORE the entities go dark.",
        notes=[
            "Coverage is the engine rule: entity collision box intersects pole supply box",
            "margin is signed: overlap depth if covered, shortest move (with axis) if not",
            "supply areas render tile-aligned in ascii_map (as Factorio computes them)",
            "No snapshot lag — reads hit the running engine directly via RCON",
        ],
        related_classes=["RemoteView", "PlacementHints"],
    )
    registry.register_required_class(VerifyView)

    registry.register_method(
        cls=VerifyView,
        method_name="supply_coverage",
        description="Check whether every electric consumer's collision box actually "
        "intersects a pole's supply area, with per-entity margins and a tile-aligned "
        "ascii map. Optionally score an as-if-placed proposed_pole (pre-placement preview).",
        examples=[
            Example(
                code="""# The attempt-5 miss, made visible: a medium-pole spine at y=64.5
# leaves a drill at y=59.5 exactly 0.15 tiles short on Y, while the
# furnace at y=62.5 is covered.
report = verify.supply_coverage(
    entities=[
        ("electric-mining-drill", MapPosition(x=5.5, y=59.5)),
        ("electric-furnace", MapPosition(x=5.5, y=62.5)),
    ],
    area={"left_top": {"x": 0, "y": 55}, "right_bottom": {"x": 12, "y": 68}},
)
print(report.summary)
# -> '1/2 covered | NOT covered: electric-mining-drill@(5.5,59.5) (0.15 short on Y)'
print(report.ascii_map)
# 59 ...d...      <- lowercase d: NOT covered
# 61 #######      <- '#': tiles inside the medium pole's supply area
# 62 ###F###      <- uppercase F: covered
# 64 ###P###      <- 'P': the pole
for c in report.entities:
    if not c.covered:
        print(c.entity_name, c.margin, c.margin_axis, c.detail)""",
                decision_context="Previewing coverage geometry before a drill line commits to a pole spine",
                expected_outcome="Returns SupplyCoverageReport; drill NOT covered (0.15 on Y), furnace covered",
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# Pre-placement preview: move the pole one tile closer (proposed_pole)
# and watch the drill flip to covered without placing anything.
report = verify.supply_coverage(
    entities=[("electric-mining-drill", MapPosition(x=5.5, y=59.5))],
    area={"left_top": {"x": 0, "y": 55}, "right_bottom": {"x": 12, "y": 68}},
    proposed_pole=("medium-electric-pole", MapPosition(x=5.5, y=63.5)),
)
print(report.summary, report.covered_count, "of", report.total_count)""",
                decision_context="Choosing where to place a new pole so it actually covers the target",
                expected_outcome="Proposed pole flips the drill to covered in the preview",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Pass entities explicitly, or an area to discover live consumers",
            "proposed_pole is scored as if already placed — nothing is built",
            "margin_axis is 'X', 'Y', or 'XY'; margin is tiles (overlap depth or shortfall)",
        ],
    )

    registry.register_method(
        cls=VerifyView,
        method_name="powered",
        description="Live power status of one or many entities, keyed 'name@(x,y)'. "
        "powered == on an electric network AND not reporting no_power.",
        examples=[
            Example(
                code="""# Confirm the drill and furnace power state right now
checks = verify.powered([
    ("electric-mining-drill", MapPosition(x=5.5, y=59.5)),
    ("electric-furnace", MapPosition(x=5.5, y=62.5)),
])
for key, chk in checks.items():
    print(key, chk.powered, chk.status_name, chk.electric_network_id)""",
                decision_context="Verifying entities actually receive power after wiring a network",
                expected_outcome="Dict of PoweredCheck; uncovered drill powered=False (no_power)",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "A fuel-starved producer still reports 'working' — cross-check network wattages",
            "found=False means no such entity within 0.6 tiles of the given position",
        ],
    )

    registry.register_method(
        cls=VerifyView,
        method_name="connected",
        description="Whether two entities share one live electric network right now "
        "(same non-nil electric_network_id).",
        examples=[
            Example(
                code="""# Are the EEI and the pole on the same network?
check = verify.connected(
    ("electric-energy-interface", MapPosition(x=2.5, y=64.5)),
    ("medium-electric-pole", MapPosition(x=5.5, y=64.5)),
)
print(check.connected, check.explanation)""",
                decision_context="Confirming a generator actually feeds the intended pole network",
                expected_outcome="Returns ConnectedCheck with connected bool and an explanation",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Network ids are ephemeral (renumber on merge/split) — this is a right-now fact",
        ],
    )


# Register on import
_register_views()
