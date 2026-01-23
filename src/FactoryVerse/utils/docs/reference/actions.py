"""
Documentation for Action Classes.

This module registers documentation for all embodied action classes:
- MovementAction (walking)
- CraftingAction (crafting)
- ResearchAction (research)
- AgentInventory (inventory)

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
                when="Missing ingredients or recipe unavailable",
                resolution="Check inventory for required ingredients, verify recipe is unlocked",
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

# Register on import
_register_actions()
