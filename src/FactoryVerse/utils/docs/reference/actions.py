"""
Documentation for Action Classes.

This module registers documentation for all embodied action classes:
- MovementAction (walking)
- CraftingAction (crafting)
- ResearchAction (research)
- AgentInventory (inventory)
- MiningAction (mining)
- PlacementAction (placement)
- EntityOperationsAction (entity_ops)

Documentation is decision-driven: examples show WHEN to use each method,
not just HOW.
"""

from FactoryVerse.utils.docs.registry import get_registry
from FactoryVerse.utils.docs.models import Example, ErrorCase, ValidationLevel


def _register_actions():
    """Register all action class documentation."""
    registry = get_registry()

    # =========================================================================
    # MovementAction (walking)
    # =========================================================================

    from FactoryVerse.game.agent.embodied_actions.walking import MovementAction

    registry.register_class(
        cls=MovementAction,
        accessor_name="walking",
        description="Handles agent walking and pathfinding. All walking is asynchronous - "
        "methods return when the agent reaches the destination or fails.",
        decision_context="Use walking when the agent needs to move to interact with entities or resources.",
        notes=[
            "Walking is async - the agent continues moving after the call returns",
            "Entity-based walking uses fallback tiles if the direct path is blocked",
            "Walking errors indicate permanent failures (path blocked, entity not found)",
        ],
        related_classes=["ReachableView", "RemoteView"],
    )
    registry.register_required_class(MovementAction)

    registry.register_method(
        cls=MovementAction,
        method_name="walk_to",
        description="Walk to a target position. Returns when agent arrives or fails.",
        examples=[
            Example(
                code="""# Walk to a known coordinate
position = MapPosition(x=10.5, y=20.5)
final_pos = await walking.walk_to(position)
print(f"Arrived at {final_pos}")""",
                decision_context="Walking to a known coordinate",
                expected_outcome="Agent walks to position and returns final MapPosition",
                alternatives=["Use entity.walk_to() when navigating to an entity"],
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# Walk with strict positioning (fail if exact position unreachable)
try:
    pos = await walking.walk_to(MapPosition(x=5, y=5), strict_goal=True)
except WalkingUnreachableError as e:
    print(f"Cannot reach exact position: {e}")""",
                decision_context="Requiring exact position (e.g., for precise placement)",
                expected_outcome="Agent reaches exact position or raises error",
                preconditions=["Target position must be walkable"],
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        error_cases=[
            ErrorCase(
                exception="WalkingUnreachableError",
                when="Path is completely blocked by obstacles",
                resolution="Check for obstructions, consider destroying/deconstructing obstacles",
            ),
        ],
        decision_points=[
            "Use walk_to(position) for known coordinates",
            "Use entity.walk_to() for navigating to entities (handles approach tiles)",
        ],
    )

    registry.register_method(
        cls=MovementAction,
        method_name="stop",
        description="Stop current walking action immediately.",
        examples=[
            Example(
                code="""# Stop walking and get current position
result = walking.stop()
if result.position:
    print(f"Stopped at {result.position}")""",
                decision_context="Interrupting navigation (e.g., code errors out and agent is stuck in walking state)",
                expected_outcome="Walking stops, returns WalkingStopped with position",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Use when navigation needs to be interrupted",
            "Consider if destination is still needed - may need to restart walking",
        ],
    )

    registry.register_method(
        cls=MovementAction,
        method_name="walk_to_entity",
        description="Walk to an entity with fallback approach tiles. Tries candidate tiles "
        "around the entity until a path succeeds.",
        examples=[
            Example(
                code="""# Walk to a furnace (approach tiles handled automatically)
pos = await walking.walk_to_entity(
    "stone-furnace", MapPosition(x=10.5, y=10.5)
)
print(f"Arrived at {pos}")""",
                decision_context="Navigating to an entity when only its name and position are known",
                expected_outcome="Agent stands adjacent to the entity, returns final MapPosition",
                alternatives=["Prefer entity.walk_to() on entity objects - it wraps this method"],
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        error_cases=[
            ErrorCase(
                exception="WalkingEntityNotFoundError",
                when="No entity with that name exists at the given position",
                resolution="Verify entity_name + position via remote_view/reachable_view first",
            ),
            ErrorCase(
                exception="WalkingUnreachableError",
                when="All approach paths around the entity are blocked",
                resolution="Clear obstructions or approach from a different area",
            ),
        ],
        decision_points=[
            "Use entity.walk_to() when you already hold an entity object",
            "Use walk_to_entity(name, position) when working from raw query results",
        ],
    )

    registry.register_method(
        cls=MovementAction,
        method_name="current_position",
        description="Get agent's current map position.",
        examples=[
            Example(
                code="""# Check current position before planning movement
pos = walking.current_position
print(f"Agent is at ({pos.x}, {pos.y})")""",
                decision_context="Checking agent location before navigation",
                expected_outcome="Returns current MapPosition",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
    )

    # =========================================================================
    # CraftingAction (crafting)
    # =========================================================================

    from FactoryVerse.game.agent.embodied_actions.crafting import CraftingAction

    registry.register_class(
        cls=CraftingAction,
        accessor_name="crafting",
        description="Handles hand-crafting operations. Craft recipes asynchronously with queue management.",
        decision_context="Use crafting for recipes that can be hand-crafted (not requiring assemblers).",
        notes=[
            "Crafting is async - waits for items to be produced",
            "Returns ItemStack objects with placement capability",
            "Check recipe availability via status() before crafting",
        ],
        related_classes=["AgentInventory"],
    )
    registry.register_required_class(CraftingAction)

    registry.register_method(
        cls=CraftingAction,
        method_name="craft",
        description="Craft a recipe asynchronously. Waits for completion and returns crafted items.",
        examples=[
            Example(
                code="""# Craft iron gear wheels
items = await crafting.craft("iron-gear-wheel", count=5)
print(f"Crafted {len(items)} stacks")
for stack in items:
    print(f"  {stack.name} x{stack.count}")""",
                decision_context="Crafting intermediate products for later use",
                expected_outcome="Returns list of ItemStack objects",
                preconditions=["Has required ingredients in inventory"],
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# Craft placeable items
items = await crafting.craft("stone-furnace", count=3)
# Access the PlaceableItem from the stack via indexing
furnace_stack = items[0]
# Place via: furnace_stack[0].place(position, direction)
# Or via: furnace_stack.item.place(position, direction)""",
                decision_context="Crafting items for placement",
                expected_outcome="Returns ItemStack - access item via [0] or .item for placement",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        error_cases=[
            ErrorCase(
                exception="RuntimeError",
                when="Unknown recipe — the name does not exist",
                resolution="Check spelling; recipe names usually match the product item (e.g. 'iron-gear-wheel')",
            ),
            ErrorCase(
                exception="RuntimeError",
                when="Recipe locked — exists but not unlocked for your force (message names the unlocking technology when known)",
                resolution="Research the named technology first. Do NOT retry crafting: no amount of ingredients makes a locked recipe craftable",
            ),
            ErrorCase(
                exception="RuntimeError",
                when="Missing ingredients — message enumerates each as name (have N, need M)",
                resolution="Acquire or craft the listed missing ingredients, then retry",
            ),
            ErrorCase(
                exception="RuntimeError",
                when="Invalid count, crafting queue full, or recipe not hand-craftable (needs a machine)",
                resolution="Use a positive integer count; let the queue drain or craft_dequeue(); use set_entity_recipe() on a machine for non-hand recipes",
            ),
        ],
        decision_points=[
            "Use craft() for blocking crafting with results",
            "Use enqueue() for fire-and-forget crafting",
        ],
    )

    registry.register_method(
        cls=CraftingAction,
        method_name="enqueue",
        description="Queue a recipe for crafting without waiting. Returns immediately.",
        examples=[
            Example(
                code="""# Queue crafting in background
result = crafting.enqueue("electronic-circuit", count=10)
if result.get("success"):
    print("Crafting queued")""",
                decision_context="Starting crafting while doing other tasks",
                expected_outcome="Crafting queued, returns status dict",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Use enqueue() when you don't need to wait for results",
            "Use craft() when you need the items immediately",
        ],
    )

    registry.register_method(
        cls=CraftingAction,
        method_name="dequeue",
        description="Cancel queued crafting for a recipe.",
        examples=[
            Example(
                code="""# Cancel queued crafting
result = crafting.dequeue("electronic-circuit", count=5)""",
                decision_context="Canceling crafting to free up queue",
                expected_outcome="Specified crafts are cancelled",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
    )

    registry.register_method(
        cls=CraftingAction,
        method_name="status",
        description="Get current crafting queue status with full details.",
        examples=[
            Example(
                code="""# Check crafting progress
status = crafting.status()
print(f"Queue size: {status.queue_size}")
print(f"Progress: {status.progress:.1%}")
for item in status.queue:
    print(f"  {item.recipe} x{item.count}")""",
                decision_context="Monitoring crafting progress",
                expected_outcome="Returns CraftingQueueStatus with queue details",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
    )

    # =========================================================================
    # ResearchAction (research)
    # =========================================================================

    from FactoryVerse.game.agent.embodied_actions.research import ResearchAction

    registry.register_class(
        cls=ResearchAction,
        accessor_name="research",
        description="Handles technology research. Queue technologies and monitor progress.",
        decision_context="Use research to unlock new recipes and capabilities.",
        notes=[
            "Research requires labs and science packs",
            "Progress is tracked per-unit (each unit requires science packs)",
            "Multiple technologies can be queued",
        ],
    )
    registry.register_required_class(ResearchAction)

    registry.register_method(
        cls=ResearchAction,
        method_name="enqueue",
        description="Start researching a technology.",
        examples=[
            Example(
                code="""# Start researching automation
result = research.enqueue("automation")
if result.get("success"):
    print("Research started")""",
                decision_context="Starting a new technology research",
                expected_outcome="Technology added to research queue",
                preconditions=["Technology prerequisites are met", "Labs are placed and powered"],
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
    )

    registry.register_method(
        cls=ResearchAction,
        method_name="dequeue",
        description="Cancel current research.",
        examples=[
            Example(
                code="""# Cancel current research
result = research.dequeue()""",
                decision_context="Changing research priorities",
                expected_outcome="Current research is cancelled",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
    )

    registry.register_method(
        cls=ResearchAction,
        method_name="status",
        description="Get comprehensive research status with progressive detail levels.",
        examples=[
            Example(
                code="""# Check research progress
status = research.status()
if status.active:
    print(f"Researching {status.current_research}")
    print(f"Progress: {status.progress * 100:.1f}%")
    print(f"Units: {status.units_completed}/{status.units_total}")
elif status.queued:
    print(f"{status.queue_length} technologies queued")
else:
    print("No research active")""",
                decision_context="Monitoring research progress",
                expected_outcome="Returns ResearchStatus with current state",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
    )

    registry.register_method(
        cls=ResearchAction,
        method_name="get_queue",
        description="Get the full research queue with progress information.",
        examples=[
            Example(
                code="""# View research queue
queue = research.get_queue()
print(f"Current: {queue.get('current_research')}")
for item in queue.get('queue', []):
    print(f"  {item}")""",
                decision_context="Planning research order",
                expected_outcome="Returns queue dict with technologies",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
    )

    # =========================================================================
    # AgentInventory (inventory)
    # =========================================================================

    from FactoryVerse.game.agent.embodied_actions.inventory import AgentInventory

    registry.register_class(
        cls=AgentInventory,
        accessor_name="inventory",
        description="Query and shape agent inventory contents. Provides methods to check counts "
        "and create ItemStack objects for placement.",
        decision_context="Use inventory to check available items and create placeable stacks.",
        notes=[
            "Inventory queries are synchronous",
            "ItemStacks have placement capability injected",
            "Use create_item_stacks() to prepare items for placement",
        ],
        related_classes=["CraftingAction", "PlacementHints"],
    )
    registry.register_required_class(AgentInventory)

    registry.register_method(
        cls=AgentInventory,
        method_name="item_stacks",
        description="Get all inventory contents as ItemStack objects.",
        examples=[
            Example(
                code="""# List all items in inventory
for stack in inventory.item_stacks:
    print(f"{stack.name}: {stack.count}")""",
                decision_context="Reviewing full inventory",
                expected_outcome="Returns list of all ItemStack objects",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
    )

    registry.register_method(
        cls=AgentInventory,
        method_name="check_total",
        description="Get total count of an item across all stacks.",
        examples=[
            Example(
                code="""# Check how many iron plates we have
count = inventory.check_total("iron-plate")
print(f"Iron plates: {count}")

# Check before crafting
if inventory.check_total("iron-plate") >= 10:
    await crafting.craft("iron-gear-wheel", count=5)""",
                decision_context="Checking resource availability before operations",
                expected_outcome="Returns total count as integer",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
    )

    registry.register_method(
        cls=AgentInventory,
        method_name="get_item",
        description="Get a single Item or PlaceableItem instance for a specific item name.",
        examples=[
            Example(
                code="""# Get item with placement capability
item = inventory.get_item("stone-furnace")
if item:
    # PlaceableItem has stack_size and can be placed
    print(f"Stack size: {item.stack_size}")""",
                decision_context="Getting item metadata (stack size, prototype info)",
                expected_outcome="Returns Item/PlaceableItem or None if not in inventory",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
    )

    registry.register_method(
        cls=AgentInventory,
        method_name="create_item_stacks",
        description="Create ItemStack objects for a specific item with flexible count options.",
        examples=[
            Example(
                code="""# Create stacks of 25 iron plates each
stacks = inventory.create_item_stacks("iron-plate", count=25)
for stack in stacks:
    print(f"Stack: {stack.name} x{stack.count}")""",
                decision_context="Preparing items for distribution to multiple entities",
                expected_outcome="Returns list of ItemStack objects",
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# Create full stacks (max stack size)
full_stacks = inventory.create_item_stacks("iron-plate", count="full")

# Create half stacks
half_stacks = inventory.create_item_stacks("iron-plate", count="half")""",
                decision_context="Creating standardized stack sizes",
                expected_outcome="Returns stacks at specified size",
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# Create exactly 3 stacks (strict mode raises error if insufficient)
try:
    stacks = inventory.create_item_stacks(
        "iron-plate",
        count=50,
        number_of_stacks=3,
        strict=True
    )
except ValueError as e:
    print(f"Not enough items: {e}")""",
                decision_context="Requiring exact amounts (fail if insufficient)",
                expected_outcome="Returns exact stacks or raises ValueError",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Use count='full' for maximum efficiency per stack",
            "Use strict=True when you need guaranteed quantities",
            "Use number_of_stacks='max' to use all available items",
        ],
    )

    # =========================================================================
    # MiningAction (mining)
    # =========================================================================

    from FactoryVerse.game.agent.embodied_actions.mining import MiningAction

    registry.register_class(
        cls=MiningAction,
        accessor_name="mining",
        description="Handles hand-mining of resources (ore, coal, stone). Mining is "
        "asynchronous - mine() returns when the requested items are obtained.",
        decision_context="Use mining to gather raw resources by hand before automation exists, "
        "or to top up small amounts of a resource.",
        notes=[
            "Mining is async - the call returns when items are in the agent's inventory",
            "max_count is capped at 25 items per call for safety",
            "Resource must be within reach - walk to the patch first",
            "Returned ItemStacks have placement injected (placeable items can .place())",
        ],
        related_classes=["AgentInventory", "ReachableView", "MovementAction"],
    )
    registry.register_required_class(MiningAction)

    registry.register_method(
        cls=MiningAction,
        method_name="mine",
        description="Mine a resource asynchronously. Waits for completion and returns mined items.",
        examples=[
            Example(
                code="""# Mine iron ore from a nearby patch
stacks = await mining.mine("iron-ore", max_count=10)
for stack in stacks:
    print(f"Mined {stack.name} x{stack.count}")""",
                decision_context="Gathering raw resources by hand",
                expected_outcome="Returns list of ItemStack objects with mined items",
                preconditions=["Resource patch is within reach of the agent"],
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# Mine at a specific position (e.g., a tile found via views)
stacks = await mining.mine(
    "coal",
    max_count=5,
    position=MapPosition(x=12.5, y=8.5),
)
total = sum(stack.count for stack in stacks)
print(f"Mined {total} coal")""",
                decision_context="Mining a specific resource tile rather than the nearest one",
                expected_outcome="Mines at the given position, returns ItemStack list",
                preconditions=["Position holds the named resource and is within reach"],
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        error_cases=[
            ErrorCase(
                exception="RuntimeError",
                when="Mining fails to start (resource not found / out of reach) or times out",
                resolution="Walk closer to the resource patch and verify the resource name",
            ),
        ],
        decision_points=[
            "Use max_count=None to deplete the resource (still capped at 25 per call)",
            "Walk to the patch first - mining requires the resource within reach",
        ],
    )

    registry.register_method(
        cls=MiningAction,
        method_name="cancel",
        description="Cancel the current mining action.",
        examples=[
            Example(
                code="""# Stop an in-progress mining action
result = mining.cancel()
if result.was_active:
    print(f"Cancelled mining, items obtained: {result.items_obtained}")""",
                decision_context="Interrupting mining (e.g., priorities changed mid-action)",
                expected_outcome="Returns MiningCancelled with any items already obtained",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Items mined before cancellation stay in the agent's inventory",
        ],
    )

    # =========================================================================
    # PlacementAction (placement)
    # =========================================================================

    from FactoryVerse.game.agent.embodied_actions.place_entity import PlacementAction

    registry.register_class(
        cls=PlacementAction,
        accessor_name="placement",
        description="Places entities and ghosts on the map and removes ghosts. "
        "Placement is synchronous - results are returned immediately.",
        decision_context="Use placement for direct entity/ghost placement at known positions. "
        "For planned multi-entity layouts, prefer placement_hints + ghost_builder.",
        notes=[
            "Placement requires the item in the agent's inventory (unless ghost=True)",
            "Target position must be within reach and buildable",
            "Ghosts are tracked by fv_snapshot - query via remote_view.get_ghosts()",
            "Prefer item.place() on ItemStack/PlaceableItem objects when you hold them",
        ],
        related_classes=["AgentInventory", "PlacementHints", "GhostBuilderAction"],
    )
    registry.register_required_class(PlacementAction)

    registry.register_method(
        cls=PlacementAction,
        method_name="place",
        description="Place an entity or ghost on the map. Optionally returns a full BaseEntity.",
        examples=[
            Example(
                code="""# Place a furnace facing north
result = placement.place(
    "stone-furnace",
    MapPosition(x=10.5, y=10.5),
    direction=Direction.NORTH,
)
if result.success:
    print(f"Placed at {result.placed_position}")""",
                decision_context="Placing a single entity at a known buildable position",
                expected_outcome="Returns EntityPlaced with position and metadata",
                preconditions=["Item is in agent inventory", "Position is within reach and buildable"],
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# Place a labeled ghost for later construction
result = placement.place(
    "transport-belt",
    {"x": 5.5, "y": 6.5},
    ghost=True,
    label="main-bus",
)
print(f"Ghost placed: {result.is_ghost}")
# Query later: remote_view.get_ghosts("SELECT * FROM ghost WHERE label = 'main-bus'")""",
                decision_context="Planning a build without consuming items yet",
                expected_outcome="Ghost entity placed, tracked in DuckDB ghost table",
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# Place and get a full entity object back for immediate configuration
pos = MapPosition(x=8.5, y=8.5)
chest = placement.place("iron-chest", pos, return_entity=True)
print(f"Placed {chest.name} at {chest.position}")""",
                decision_context="Needing to configure/inspect the entity right after placement",
                expected_outcome="Returns BaseEntity with full REACHABLE access",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        error_cases=[
            ErrorCase(
                exception="RuntimeError",
                when="Placement fails (position blocked, out of reach, item missing)",
                resolution="Check buildability via placement_hints/reachable_view and inventory counts",
            ),
        ],
        decision_points=[
            "Use ghost=True to plan placement without consuming items",
            "Use return_entity=True when you need to configure the entity immediately",
            "Use label= to group placed entities for later SQL queries",
        ],
    )

    registry.register_method(
        cls=PlacementAction,
        method_name="remove_ghost",
        description="Remove a ghost entity from the map.",
        examples=[
            Example(
                code="""# Remove a misplaced ghost
result = placement.remove_ghost("transport-belt", {"x": 5.5, "y": 6.5})
if result.success:
    print(f"Removed ghost at {result.removed_position}")""",
                decision_context="Cleaning up ghosts after a plan changes",
                expected_outcome="Ghost removed, ghost table updated by fv_snapshot",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Reference ghosts by entity_name + position (never unit_number)",
        ],
    )

    # =========================================================================
    # EntityOperationsAction (entity_ops)
    # =========================================================================

    from FactoryVerse.game.agent.embodied_actions.entity_operations import (
        EntityOperationsAction,
    )

    registry.register_class(
        cls=EntityOperationsAction,
        accessor_name="entity_ops",
        description="Low-level entity configuration and inventory operations: set recipes, "
        "filters and limits, transfer items, inspect state, and pick up entities.",
        decision_context="Use entity_ops for direct entity manipulation by name + position. "
        "When you hold an entity object from reachable_view, prefer its own methods "
        "(entity.set_recipe(), entity.inspect(), ...) which wrap these.",
        notes=[
            "All operations are synchronous and require the entity within reach",
            "Entities are referenced by entity_name + position (never unit_number)",
            "position=None resolves to the nearest matching entity within reach",
        ],
        related_classes=["ReachableView", "AgentInventory", "PlacementAction"],
    )
    registry.register_required_class(EntityOperationsAction)

    registry.register_method(
        cls=EntityOperationsAction,
        method_name="set_entity_recipe",
        description="Set or clear the recipe on a crafting machine.",
        examples=[
            Example(
                code="""# Configure an assembler to make iron gear wheels
result = entity_ops.set_entity_recipe(
    "assembling-machine-1",
    "iron-gear-wheel",
    position=MapPosition(x=12.5, y=4.5),
)
if result.success:
    print(f"Recipe set: {result.recipe_name}")""",
                decision_context="Configuring a crafting machine after placement",
                expected_outcome="Returns EntityRecipeSet with the configured recipe",
                preconditions=["Machine is within reach", "Recipe is unlocked and valid for the machine"],
                validation_level=ValidationLevel.SYNTAX,
            ),
            Example(
                code="""# Clear a machine's recipe
result = entity_ops.set_entity_recipe("assembling-machine-1", None)""",
                decision_context="Repurposing a machine (clear before setting a new recipe)",
                expected_outcome="Recipe is cleared",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Prefer entity.set_recipe() when you already hold the entity object",
        ],
    )

    registry.register_method(
        cls=EntityOperationsAction,
        method_name="set_entity_filter",
        description="Set or clear an inventory filter on an entity (e.g., filter inserter).",
        examples=[
            Example(
                code="""# Make a filter inserter only move iron plates
result = entity_ops.set_entity_filter(
    "fast-inserter",
    MapPosition(x=3.5, y=2.5),
    inventory_type="main",
    filter_index=1,
    filter_item="iron-plate",
)
print(f"Filter set: {result.filter_item}")""",
                decision_context="Restricting which items an inserter handles",
                expected_outcome="Returns EntityFilterSet with the applied filter",
                preconditions=["Entity supports filters", "Entity is within reach"],
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Pass filter_item=None to clear a filter slot",
        ],
    )

    registry.register_method(
        cls=EntityOperationsAction,
        method_name="set_inventory_limit",
        description="Set the inventory bar limit (red bar) on a container.",
        examples=[
            Example(
                code="""# Limit a chest to 10 slots to avoid over-buffering
result = entity_ops.set_inventory_limit(
    "iron-chest",
    inventory_type="main",
    limit=10,
)
if result.success:
    print(f"Limit set to {result.limit} slots")""",
                decision_context="Preventing containers from absorbing too many items",
                expected_outcome="Returns InventoryLimitSet with the applied limit",
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Pass limit=None to remove the limit",
        ],
    )

    registry.register_method(
        cls=EntityOperationsAction,
        method_name="take_inventory_item",
        description="Take items from an entity's inventory into the agent's inventory.",
        examples=[
            Example(
                code="""# Collect smelted plates from a furnace
result = entity_ops.take_inventory_item(
    "stone-furnace",
    inventory_type="output",
    item_name="iron-plate",
)
print(f"Took {result.count} iron plates")
if result.is_partial:
    print("Agent inventory could not fit everything")""",
                decision_context="Collecting outputs from machines or chests",
                expected_outcome="Returns InventoryItemTaken with actual count transferred",
                preconditions=["Entity is within reach", "Items exist in the named inventory"],
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Omit count to take all available items",
            "Check result.is_partial - transfers can be smaller than requested",
        ],
    )

    registry.register_method(
        cls=EntityOperationsAction,
        method_name="put_inventory_item",
        description="Put items from the agent's inventory into an entity's inventory.",
        examples=[
            Example(
                code="""# Fuel a furnace with coal from the agent's inventory
stacks = inventory.create_item_stacks("coal", count=10)
result = entity_ops.put_inventory_item(
    "stone-furnace",
    inventory_type="fuel",
    items=stacks[0],
)
print(f"Inserted {result.count} coal")""",
                decision_context="Loading machines with fuel or ingredients",
                expected_outcome="Returns InventoryItemPut with actual count transferred",
                preconditions=["Items are in agent inventory", "Entity is within reach"],
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        error_cases=[
            ErrorCase(
                exception="RuntimeError",
                when="Invalid inventory_type name (valid: 'auto', 'fuel', 'input', 'chest', 'output', 'modules')",
                resolution="Use one of the listed names; 'auto' lets the engine route fuel/ingredients automatically",
            ),
            ErrorCase(
                exception="RuntimeError",
                when="Target inventory cannot accept ANY of the item (full, or item not allowed there) — fails before anything moves",
                resolution="Free space with take_inventory_item() or pick a different inventory_type",
            ),
            ErrorCase(
                exception="RuntimeError",
                when="Insufficient items in agent inventory (message states have/need) or entity not found / out of reach",
                resolution="Acquire more items, fix entity_name/position, or walk closer",
            ),
        ],
        decision_points=[
            "Pass a list of ItemStacks to perform multiple transfers in sequence",
            "Check result.is_partial - partial inserts SUCCEED with count < requested_count; result.message says the rest returned to your inventory",
        ],
    )

    registry.register_method(
        cls=EntityOperationsAction,
        method_name="inspect_entity",
        description="Get comprehensive volatile state for an entity as a raw dict.",
        examples=[
            Example(
                code="""# Inspect a furnace's full state
state = entity_ops.inspect_entity(
    "stone-furnace", MapPosition(x=10.5, y=10.5)
)
print(f"Status: {state.get('status')}")""",
                decision_context="Reading raw entity state when no typed entity object is at hand",
                expected_outcome="Returns raw dict with entity state (structure varies by type)",
                preconditions=["Entity is within reach"],
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Prefer entity.inspect() via reachable_view - it returns typed EntityInspection",
            "Use this raw form only when working outside the typed entity layer",
        ],
    )

    registry.register_method(
        cls=EntityOperationsAction,
        method_name="pickup_entity",
        description="Pick up (mine) an entity from the map into the agent's inventory.",
        examples=[
            Example(
                code="""# Pick up a misplaced chest (contents come along)
result = entity_ops.pickup_entity(
    "iron-chest", position=MapPosition(x=8.5, y=8.5)
)
if result.has_items:
    print(f"Extracted: {result.extracted_items}")""",
                decision_context="Removing/relocating placed entities",
                expected_outcome="Entity removed from map, item + contents in agent inventory",
                preconditions=["Entity is within reach and mineable"],
                validation_level=ValidationLevel.SYNTAX,
            ),
        ],
        decision_points=[
            "Entity inventories are extracted along with the entity itself",
            "Prefer entity.mine() when you already hold the entity object",
        ],
    )

# Register on import
_register_actions()
