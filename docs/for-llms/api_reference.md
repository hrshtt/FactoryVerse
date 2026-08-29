# FactoryVerse API Reference

This document provides the complete API reference for FactoryVerse agents.
All methods, types, and examples are validated against the actual implementation.

---

## Overview

FactoryVerse provides a dual-view system for interacting with the game:

| View | Accessor | Description |
|------|----------|-------------|
| **REACHABLE** | `reachable_view` | Nearby entities with full mutation access |
| **REMOTE** | `remote_view` | Map-wide SQL queries (read-only, walk_to only) |

### Top-Level Accessors

These are available in the agent runtime:

| Accessor | Class | Purpose |
|----------|-------|---------|
| `walking` | MovementAction | Handles agent walking and pathfinding |
| `crafting` | CraftingAction | Handles hand-crafting operations |
| `research` | ResearchAction | Handles technology research |
| `inventory` | AgentInventory | Query and shape agent inventory contents |
| `mining` | MiningAction | Handles hand-mining of resources (ore, coal, stone) |
| `placement` | PlacementAction | Places entities and ghosts on the map and removes ghosts |
| `entity_ops` | EntityOperationsAction | Low-level entity configuration and inventory operations: set recipes, filters and limits, transfer items, inspect state, and pick up entities |
| `reachable_view` | ReachableView | Query interface for nearby entities and resources within agent's interaction range |
| `remote_view` | RemoteView | DuckDB-backed map queries for entities across the entire map |
| `verify` | VerifyView | Live engine confirmation of power / coverage facts |
| `placement_hints` | PlacementHints | Spatial reasoning engine for entity placement |
| `ghost_builder` | GhostBuilderAction | Orchestrates ghost placement and building |

## Pre-Imported Types

These types are automatically imported in the agent runtime.
You can use them directly without importing.

| Type | Module |
|------|--------|
| `BoundingBox` | `FactoryVerse.game.factory.types` |
| `ConnectionPosition` | `FactoryVerse.game.agent.placement_hints` |
| `ConnectionType` | `FactoryVerse.game.agent.placement_hints` |
| `CraftingQueueStatus` | `FactoryVerse.game.factory.types` |
| `Direction` | `FactoryVerse.game.factory.factorio_types` |
| `EntityValidationError` | `FactoryVerse.game.agent.placement_hints` |
| `GhostPlan` | `FactoryVerse.game.agent.placement_hints` |
| `Item` | `FactoryVerse.game.factory.item.base` |
| `ItemStack` | `FactoryVerse.game.factory.item.base` |
| `MapPosition` | `FactoryVerse.game.factory.types` |
| `PlaceableItem` | `FactoryVerse.game.factory.item.base` |
| `PolePlacementResult` | `FactoryVerse.game.agent.placement_hints` |
| `QueuedTechnology` | `FactoryVerse.game.agent.embodied_actions.research` |
| `ResearchQueueItem` | `FactoryVerse.game.factory.types` |
| `ResearchStatus` | `FactoryVerse.game.agent.embodied_actions.research` |
| `WalkingEntityNotFoundError` | `FactoryVerse.game.agent.embodied_actions.walking` |
| `WalkingError` | `FactoryVerse.game.agent.embodied_actions.walking` |
| `WalkingNoStandableTilesError` | `FactoryVerse.game.agent.embodied_actions.walking` |
| `WalkingUnreachableError` | `FactoryVerse.game.agent.embodied_actions.walking` |
| `WireConnectionPosition` | `FactoryVerse.game.agent.placement_hints` |


## Quick Reference

### `walking`

Handles agent walking and pathfinding. All walking is asynchronous - methods return when the agent reaches the destination or fails.

**Methods:**
- `async walk_to(goal: MapPosition, strict_goal: bool = ..., options: Optional[Dict] = ..., timeout: Optional[int] = ...)`
- `stop()`
- `async walk_to_entity(entity_name: str, entity_position: MapPosition, timeout: Optional[int] = ...)`
- `current_position: MapPosition`

### `crafting`

Handles hand-crafting operations. Craft recipes asynchronously with queue management.

**Methods:**
- `async craft(recipe: str, count: int = ..., timeout: Optional[int] = ...)`
- `enqueue(recipe: str, count: int = ...)`
- `dequeue(recipe: str, count: Optional[int] = ...)`
- `status()`

### `research`

Handles technology research. Queue technologies and monitor progress.

**Methods:**
- `enqueue(technology: str)`
- `dequeue()`
- `status()`
- `get_queue()`

### `inventory`

Query and shape agent inventory contents. Provides methods to check counts and create ItemStack objects for placement.

**Methods:**
- `check_total(item_name: str)`
- `get_item(item_name: str)`
- `create_item_stacks(item_name: str, count: Union[int, Literal[half, full]], number_of_stacks: Union[int, Literal[max]] = ..., strict: bool = ...)`
- `item_stacks: List[ItemStack]`

### `mining`

Handles hand-mining of resources (ore, coal, stone). Mining is asynchronous - mine() returns when the requested items are obtained.

**Methods:**
- `async mine(resource_name: str, max_count: Optional[int] = ..., position: Optional[MapPosition] = ..., timeout: Optional[int] = ...)`
- `cancel()`

### `placement`

Places entities and ghosts on the map and removes ghosts. Placement is synchronous - results are returned immediately.

**Methods:**
- `place(entity_name: PlaceableItemName, position: Union[Dict[str, float], MapPosition], direction: Optional[Direction] = ..., ghost: bool = ..., label: Optional[str] = ..., return_entity: bool = ...)`
- `remove_ghost(entity_name: str, position: Union[Dict[str, float], MapPosition])`

### `entity_ops`

Low-level entity configuration and inventory operations: set recipes, filters and limits, transfer items, inspect state, and pick up entities.

**Methods:**
- `set_entity_recipe(entity_name: str, recipe_name: Optional[str] = ..., position: Optional[MapPosition] = ...)`
- `set_entity_filter(entity_name: str, position: MapPosition, inventory_type: str, filter_index: Optional[int] = ..., filter_item: Optional[str] = ...)`
- `set_inventory_limit(entity_name: str, inventory_type: str, limit: Optional[int] = ..., position: Optional[MapPosition] = ...)`
- `take_inventory_item(entity_name: str, inventory_type: str, item_name: str, count: Optional[int] = ..., position: Optional[MapPosition] = ...)`
- `put_inventory_item(entity_name: str, inventory_type: str, items: Union[ItemStack, List[ItemStack]], position: Optional[MapPosition] = ...)`
- `inspect_entity(entity_name: str, position: MapPosition)`
- `pickup_entity(entity_name: str, position: Optional[MapPosition] = ...)`

### `reachable_view`

Query interface for nearby entities and resources within agent's interaction range. Returns entities with REACHABLE view (full mutation access).

**Methods:**
- `get_entity(entity_name: str, position: Optional[MapPosition] = ..., options: Optional[Dict[str, Any]] = ...)`
- `get_entities(entity_name: Optional[str] = ..., options: Optional[Dict[str, Any]] = ...)`
- `get_ghosts(entity_name: Optional[str] = ...)`
- `get_resource(resource_name: str, position: Optional[MapPosition] = ...)`
- `get_resources(resource_name: Optional[str] = ..., resource_type: Optional[str] = ...)`

### `remote_view`

DuckDB-backed map queries for entities across the entire map. Provides read-only access via SQL queries. Entities have REMOTE view (walk_to, inspect only).

**Methods:**
- `get_entities(sql: str)`
- `find_water(near: Optional['MapPosition'] = ..., radius: Optional[float] = ..., limit: int = ...)`
- `get_entity(sql: str)`
- `get_resources(sql: str)`
- `get_ghosts(sql: str)`
- `query(sql: str)`
- `count_entities(entity_name: Optional[str] = ...)`
- `is_tile_occupied(tile_x: int, tile_y: int)`
- `get_entity_at_tile(tile_x: int, tile_y: int)`
- `get_entities_in_tile_area(min_tile_x: int, min_tile_y: int, max_tile_x: int, max_tile_y: int, entity_name: Optional[str] = ...)`
- `get_entities_at_anchor_tile(tile_x: int, tile_y: int)`
- `get_power_networks(as_of_tick: Optional[int] = ...)`
- `diagnose_power(entity_name: str, position: Any, as_of_tick: Optional[int] = ...)`

### `verify`

Live engine confirmation of power / coverage facts. The snapshot DB answers WHICH poles/entities exist; verify answers IS IT TRUE RIGHT NOW via live reads. Positions/statuses/network-ids are live at call time; supply distances and collision boxes are prototype-derived (static).

**Methods:**
- `supply_coverage(entities: Optional[List[Target]] = ..., area: Optional[Dict[str, Any]] = ..., proposed_pole: Optional[Tuple[str, Any]] = ...)`
- `powered(targets: Union[Target, List[Target]])`
- `connected(a: Target, b: Target)`

### `placement_hints`

Spatial reasoning engine for entity placement. Generates validated GhostPlan objects for lines, connections, and pole coverage. No side effects - validation only.

**Methods:**
- `get_placement_line(entity_name: str, start: MapPosition, end: MapPosition, width: int = ..., validate: bool = ...)`
- `is_buildable(left_top: MapPosition, right_bottom: MapPosition, entity_name: str = ...)`
- `find_offshore_pump_sites(near: MapPosition, radius: int = ..., max_results: int = ...)`
- `get_connection_positions(source_entity: BaseEntity, target_entity_name: str, connection_type: ConnectionType)`
- `get_inserter_placement_positions(source_entity: BaseEntity, target_entity: BaseEntity, inserter_name: str = ...)`
- `get_pole_line(start: MapPosition, end: MapPosition, pole_name: str = ..., validate: bool = ...)`
- `get_pole_coverage_position(entities_to_power: List[BaseEntity], pole_name: str = ...)`
- `get_pole_coverage_plan(entities_to_power: List[BaseEntity], pole_name: str = ...)`
- `get_underground_segment(entity_name: str, start: MapPosition, end: MapPosition, direction: Direction)`
- `evaluate_pole_placement(position: MapPosition, pole_name: str, source_pole: Optional[BaseEntity] = ..., reachable_view: Optional[Any] = ...)`
- `validator: PlacementValidator`

### `ghost_builder`

Orchestrates ghost placement and building. Converts GhostPlan objects into placed ghosts, then builds them into real entities.

**Methods:**
- `async build_ghosts(ghosts: List[BaseEntity], count: int = ..., strict: bool = ...)`
- `async build_ghost(ghost: BaseEntity)`
- `async build_plan(plan: GhostPlan, strict: bool = ...)`


## Action Classes

### MovementAction

**Accessor:** `walking`

Handles agent walking and pathfinding. All walking is asynchronous - methods return when the agent reaches the destination or fails.

**When to use:** Use walking when the agent needs to move to interact with entities or resources.

**Notes:**
- Walking is async - the agent continues moving after the call returns
- Entity-based walking uses fallback tiles if the direct path is blocked
- Walking errors indicate permanent failures (path blocked, entity not found)

#### `walking.walk_to`

```python
async walk_to(goal: MapPosition, strict_goal: bool = ..., options: Optional[Dict] = ..., timeout: Optional[int] = ...) -> MapPosition
```

Walk to a target position. Returns when agent arrives or fails.

**Decision Points:**
- Use walk_to(position) for known coordinates
- Use entity.walk_to() for navigating to entities (handles approach tiles)

**Examples:**

*Walking to a known coordinate:*

```python
# Walk to a known coordinate
position = MapPosition(x=10.5, y=20.5)
final_pos = await walking.walk_to(position)
print(f"Arrived at {final_pos}")
```

→ Agent walks to position and returns final MapPosition

Alternatives: Use entity.walk_to() when navigating to an entity

*Requiring exact position (e.g., for precise placement):*

Preconditions: Target position must be walkable

```python
# Walk with strict positioning (fail if exact position unreachable)
try:
    pos = await walking.walk_to(MapPosition(x=5, y=5), strict_goal=True)
except WalkingUnreachableError as e:
    print(f"Cannot reach exact position: {e}")
```

→ Agent reaches exact position or raises error


**Error Handling:**

- **`WalkingUnreachableError`**: Path is completely blocked by obstacles
  - Resolution: Check for obstructions, consider destroying/deconstructing obstacles


#### `walking.stop`

```python
stop() -> WalkingStopped
```

Stop current walking action immediately.

**Decision Points:**
- Use when navigation needs to be interrupted
- Consider if destination is still needed - may need to restart walking

**Examples:**

*Interrupting navigation (e.g., code errors out and agent is stuck in walking state):*

```python
# Stop walking and get current position
result = walking.stop()
if result.position:
    print(f"Stopped at {result.position}")
```

→ Walking stops, returns WalkingStopped with position



#### `walking.walk_to_entity`

```python
async walk_to_entity(entity_name: str, entity_position: MapPosition, timeout: Optional[int] = ...) -> MapPosition
```

Walk to an entity with fallback approach tiles. Tries candidate tiles around the entity until a path succeeds.

**Decision Points:**
- Use entity.walk_to() when you already hold an entity object
- Use walk_to_entity(name, position) when working from raw query results

**Examples:**

*Navigating to an entity when only its name and position are known:*

```python
# Walk to a furnace (approach tiles handled automatically)
pos = await walking.walk_to_entity(
    "stone-furnace", MapPosition(x=10.5, y=10.5)
)
print(f"Arrived at {pos}")
```

→ Agent stands adjacent to the entity, returns final MapPosition

Alternatives: Prefer entity.walk_to() on entity objects - it wraps this method


**Error Handling:**

- **`WalkingEntityNotFoundError`**: No entity with that name exists at the given position
  - Resolution: Verify entity_name + position via remote_view/reachable_view first
- **`WalkingUnreachableError`**: All approach paths around the entity are blocked
  - Resolution: Clear obstructions or approach from a different area


#### `walking.current_position`

```python
current_position: MapPosition
```

Get agent's current map position.

**Examples:**

*Checking agent location before navigation:*

```python
# Check current position before planning movement
pos = walking.current_position
print(f"Agent is at ({pos.x}, {pos.y})")
```

→ Returns current MapPosition




### CraftingAction

**Accessor:** `crafting`

Handles hand-crafting operations. Craft recipes asynchronously with queue management.

**When to use:** Use crafting for recipes that can be hand-crafted (not requiring assemblers).

**Notes:**
- Crafting is async - waits for items to be produced
- Returns ItemStack objects with placement capability
- Check recipe availability via status() before crafting

#### `crafting.craft`

```python
async craft(recipe: str, count: int = ..., timeout: Optional[int] = ...) -> List[ItemStack]
```

Craft a recipe asynchronously. Waits for completion and returns crafted items.

**Decision Points:**
- Use craft() for blocking crafting with results
- Use enqueue() for fire-and-forget crafting

**Examples:**

*Crafting intermediate products for later use:*

Preconditions: Has required ingredients in inventory

```python
# Craft iron gear wheels
items = await crafting.craft("iron-gear-wheel", count=5)
print(f"Crafted {len(items)} stacks")
for stack in items:
    print(f"  {stack.name} x{stack.count}")
```

→ Returns list of ItemStack objects

*Crafting items for placement:*

```python
# Craft placeable items
items = await crafting.craft("stone-furnace", count=3)
# Access the PlaceableItem from the stack via indexing
furnace_stack = items[0]
# Place via: furnace_stack[0].place(position, direction)
# Or via: furnace_stack.item.place(position, direction)
```

→ Returns ItemStack - access item via [0] or .item for placement


**Error Handling:**

- **`RuntimeError`**: Unknown recipe — the name does not exist
  - Resolution: Check spelling; recipe names usually match the product item (e.g. 'iron-gear-wheel')
- **`RuntimeError`**: Recipe locked — exists but not unlocked for your force (message names the unlocking technology when known)
  - Resolution: Research the named technology first. Do NOT retry crafting: no amount of ingredients makes a locked recipe craftable
- **`RuntimeError`**: Missing ingredients — message enumerates each as name (have N, need M)
  - Resolution: Acquire or craft the listed missing ingredients, then retry
- **`RuntimeError`**: Invalid count, crafting queue full, or recipe not hand-craftable (needs a machine)
  - Resolution: Use a positive integer count; let the queue drain or craft_dequeue(); use set_entity_recipe() on a machine for non-hand recipes


#### `crafting.enqueue`

```python
enqueue(recipe: str, count: int = ...) -> Dict[str, Any]
```

Queue a recipe for crafting without waiting. Returns immediately.

**Decision Points:**
- Use enqueue() when you don't need to wait for results
- Use craft() when you need the items immediately

**Examples:**

*Starting crafting while doing other tasks:*

```python
# Queue crafting in background
result = crafting.enqueue("electronic-circuit", count=10)
if result.get("success"):
    print("Crafting queued")
```

→ Crafting queued, returns status dict



#### `crafting.dequeue`

```python
dequeue(recipe: str, count: Optional[int] = ...) -> Dict[str, Any]
```

Cancel queued crafting for a recipe.

**Examples:**

*Canceling crafting to free up queue:*

```python
# Cancel queued crafting
result = crafting.dequeue("electronic-circuit", count=5)
```

→ Specified crafts are cancelled



#### `crafting.status`

```python
status() -> CraftingQueueStatus
```

Get current crafting queue status with full details.

**Examples:**

*Monitoring crafting progress:*

```python
# Check crafting progress
status = crafting.status()
print(f"Queue size: {status.queue_size}")
print(f"Progress: {status.progress:.1%}")
for item in status.queue:
    print(f"  {item.recipe} x{item.count}")
```

→ Returns CraftingQueueStatus with queue details




### ResearchAction

**Accessor:** `research`

Handles technology research. Queue technologies and monitor progress.

**When to use:** Use research to unlock new recipes and capabilities.

**Notes:**
- Research requires labs and science packs
- Progress is tracked per-unit (each unit requires science packs)
- Multiple technologies can be queued

#### `research.enqueue`

```python
enqueue(technology: str) -> Dict[str, Any]
```

Start researching a technology.

**Examples:**

*Starting a new technology research:*

Preconditions: Technology prerequisites are met, Labs are placed and powered

```python
# Start researching automation
result = research.enqueue("automation")
if result.get("success"):
    print("Research started")
```

→ Technology added to research queue



#### `research.dequeue`

```python
dequeue() -> Dict[str, Any]
```

Cancel current research.

**Examples:**

*Changing research priorities:*

```python
# Cancel current research
result = research.dequeue()
```

→ Current research is cancelled



#### `research.status`

```python
status() -> ResearchStatus
```

Get comprehensive research status with progressive detail levels.

**Examples:**

*Monitoring research progress:*

```python
# Check research progress
status = research.status()
if status.active:
    print(f"Researching {status.current_research}")
    print(f"Progress: {status.progress * 100:.1f}%")
    print(f"Units: {status.units_completed}/{status.units_total}")
elif status.queued:
    print(f"{status.queue_length} technologies queued")
else:
    print("No research active")
```

→ Returns ResearchStatus with current state



#### `research.get_queue`

```python
get_queue() -> Dict[str, Any]
```

Get the full research queue with progress information.

**Examples:**

*Planning research order:*

```python
# View research queue
queue = research.get_queue()
print(f"Current: {queue.get('current_research')}")
for item in queue.get('queue', []):
    print(f"  {item}")
```

→ Returns queue dict with technologies




### AgentInventory

**Accessor:** `inventory`

Query and shape agent inventory contents. Provides methods to check counts and create ItemStack objects for placement.

**When to use:** Use inventory to check available items and create placeable stacks.

**Notes:**
- Inventory queries are synchronous
- ItemStacks have placement capability injected
- Use create_item_stacks() to prepare items for placement

#### `inventory.check_total`

```python
check_total(item_name: str) -> int
```

Get total count of an item across all stacks.

**Examples:**

*Checking resource availability before operations:*

```python
# Check how many iron plates we have
count = inventory.check_total("iron-plate")
print(f"Iron plates: {count}")

# Check before crafting
if inventory.check_total("iron-plate") >= 10:
    await crafting.craft("iron-gear-wheel", count=5)
```

→ Returns total count as integer



#### `inventory.get_item`

```python
get_item(item_name: str) -> Union[Item, PlaceableItem, None]
```

Get a single Item or PlaceableItem instance for a specific item name.

**Examples:**

*Getting item metadata (stack size, prototype info):*

```python
# Get item with placement capability
item = inventory.get_item("stone-furnace")
if item:
    # PlaceableItem has stack_size and can be placed
    print(f"Stack size: {item.stack_size}")
```

→ Returns Item/PlaceableItem or None if not in inventory



#### `inventory.create_item_stacks`

```python
create_item_stacks(item_name: str, count: Union[int, Literal[half, full]], number_of_stacks: Union[int, Literal[max]] = ..., strict: bool = ...) -> List[ItemStack]
```

Create ItemStack objects for a specific item with flexible count options.

**Decision Points:**
- Use count='full' for maximum efficiency per stack
- Use strict=True when you need guaranteed quantities
- Use number_of_stacks='max' to use all available items

**Examples:**

*Preparing items for distribution to multiple entities:*

```python
# Create stacks of 25 iron plates each
stacks = inventory.create_item_stacks("iron-plate", count=25)
for stack in stacks:
    print(f"Stack: {stack.name} x{stack.count}")
```

→ Returns list of ItemStack objects

*Creating standardized stack sizes:*

```python
# Create full stacks (max stack size)
full_stacks = inventory.create_item_stacks("iron-plate", count="full")

# Create half stacks
half_stacks = inventory.create_item_stacks("iron-plate", count="half")
```

→ Returns stacks at specified size

*Requiring exact amounts (fail if insufficient):*

```python
# Create exactly 3 stacks (strict mode raises error if insufficient)
try:
    stacks = inventory.create_item_stacks(
        "iron-plate",
        count=50,
        number_of_stacks=3,
        strict=True
    )
except ValueError as e:
    print(f"Not enough items: {e}")
```

→ Returns exact stacks or raises ValueError



#### `inventory.item_stacks`

```python
item_stacks: List[ItemStack]
```

Get all inventory contents as ItemStack objects.

**Examples:**

*Reviewing full inventory:*

```python
# List all items in inventory
for stack in inventory.item_stacks:
    print(f"{stack.name}: {stack.count}")
```

→ Returns list of all ItemStack objects




### MiningAction

**Accessor:** `mining`

Handles hand-mining of resources (ore, coal, stone). Mining is asynchronous - mine() returns when the requested items are obtained.

**When to use:** Use mining to gather raw resources by hand before automation exists, or to top up small amounts of a resource.

**Notes:**
- Mining is async - the call returns when items are in the agent's inventory
- max_count is capped at 25 items per call for safety
- Resource must be within reach - walk to the patch first
- Returned ItemStacks have placement injected (placeable items can .place())

#### `mining.mine`

```python
async mine(resource_name: str, max_count: Optional[int] = ..., position: Optional[MapPosition] = ..., timeout: Optional[int] = ...) -> List[ItemStack]
```

Mine a resource asynchronously. Waits for completion and returns mined items.

**Decision Points:**
- Use max_count=None to deplete the resource (still capped at 25 per call)
- Walk to the patch first - mining requires the resource within reach

**Examples:**

*Gathering raw resources by hand:*

Preconditions: Resource patch is within reach of the agent

```python
# Mine iron ore from a nearby patch
stacks = await mining.mine("iron-ore", max_count=10)
for stack in stacks:
    print(f"Mined {stack.name} x{stack.count}")
```

→ Returns list of ItemStack objects with mined items

*Mining a specific resource tile rather than the nearest one:*

Preconditions: Position holds the named resource and is within reach

```python
# Mine at a specific position (e.g., a tile found via views)
stacks = await mining.mine(
    "coal",
    max_count=5,
    position=MapPosition(x=12.5, y=8.5),
)
total = sum(stack.count for stack in stacks)
print(f"Mined {total} coal")
```

→ Mines at the given position, returns ItemStack list


**Error Handling:**

- **`RuntimeError`**: Mining fails to start (resource not found / out of reach) or times out
  - Resolution: Walk closer to the resource patch and verify the resource name


#### `mining.cancel`

```python
cancel() -> MiningCancelled
```

Cancel the current mining action.

**Decision Points:**
- Items mined before cancellation stay in the agent's inventory

**Examples:**

*Interrupting mining (e.g., priorities changed mid-action):*

```python
# Stop an in-progress mining action
result = mining.cancel()
if result.was_active:
    print(f"Cancelled mining, items obtained: {result.items_obtained}")
```

→ Returns MiningCancelled with any items already obtained




### PlacementAction

**Accessor:** `placement`

Places entities and ghosts on the map and removes ghosts. Placement is synchronous - results are returned immediately.

**When to use:** Use placement for direct entity/ghost placement at known positions. For planned multi-entity layouts, prefer placement_hints + ghost_builder.

**Notes:**
- Placement requires the item in the agent's inventory (unless ghost=True)
- Target position must be within reach and buildable
- Ghosts are tracked by fv_snapshot - query via remote_view.get_ghosts()
- Prefer item.place() on ItemStack/PlaceableItem objects when you hold them

#### `placement.place`

```python
place(entity_name: PlaceableItemName, position: Union[Dict[str, float], MapPosition], direction: Optional[Direction] = ..., ghost: bool = ..., label: Optional[str] = ..., return_entity: bool = ...) -> Union[EntityPlaced, BaseEntity]
```

Place an entity or ghost on the map. Optionally returns a full BaseEntity.

**Decision Points:**
- Use ghost=True to plan placement without consuming items
- Use return_entity=True when you need to configure the entity immediately
- Use label= to group placed entities for later SQL queries

**Examples:**

*Placing a single entity at a known buildable position:*

Preconditions: Item is in agent inventory, Position is within reach and buildable

```python
# Place a furnace facing north
result = placement.place(
    "stone-furnace",
    MapPosition(x=10.5, y=10.5),
    direction=Direction.NORTH,
)
if result.success:
    print(f"Placed at {result.placed_position}")
```

→ Returns EntityPlaced with position and metadata

*Planning a build without consuming items yet:*

```python
# Place a labeled ghost for later construction
result = placement.place(
    "transport-belt",
    {"x": 5.5, "y": 6.5},
    ghost=True,
    label="main-bus",
)
print(f"Ghost placed: {result.is_ghost}")
# Query later: remote_view.get_ghosts("SELECT * FROM ghost WHERE label = 'main-bus'")
```

→ Ghost entity placed, tracked in DuckDB ghost table

*Needing to configure/inspect the entity right after placement:*

```python
# Place and get a full entity object back for immediate configuration
pos = MapPosition(x=8.5, y=8.5)
chest = placement.place("iron-chest", pos, return_entity=True)
print(f"Placed {chest.name} at {chest.position}")
```

→ Returns BaseEntity with full REACHABLE access


**Error Handling:**

- **`RuntimeError`**: Placement fails (position blocked, out of reach, item missing)
  - Resolution: Check buildability via placement_hints/reachable_view and inventory counts


#### `placement.remove_ghost`

```python
remove_ghost(entity_name: str, position: Union[Dict[str, float], MapPosition]) -> GhostRemoved
```

Remove a ghost entity from the map.

**Decision Points:**
- Reference ghosts by entity_name + position (never unit_number)

**Examples:**

*Cleaning up ghosts after a plan changes:*

```python
# Remove a misplaced ghost
result = placement.remove_ghost("transport-belt", {"x": 5.5, "y": 6.5})
if result.success:
    print(f"Removed ghost at {result.removed_position}")
```

→ Ghost removed, ghost table updated by fv_snapshot




### EntityOperationsAction

**Accessor:** `entity_ops`

Low-level entity configuration and inventory operations: set recipes, filters and limits, transfer items, inspect state, and pick up entities.

**When to use:** Use entity_ops for direct entity manipulation by name + position. When you hold an entity object from reachable_view, prefer its own methods (entity.set_recipe(), entity.inspect(), ...) which wrap these.

**Notes:**
- All operations are synchronous and require the entity within reach
- Entities are referenced by entity_name + position (never unit_number)
- position=None resolves to the nearest matching entity within reach

#### `entity_ops.set_entity_recipe`

```python
set_entity_recipe(entity_name: str, recipe_name: Optional[str] = ..., position: Optional[MapPosition] = ...) -> EntityRecipeSet
```

Set or clear the recipe on a crafting machine.

**Decision Points:**
- Prefer entity.set_recipe() when you already hold the entity object

**Examples:**

*Configuring a crafting machine after placement:*

Preconditions: Machine is within reach, Recipe is unlocked and valid for the machine

```python
# Configure an assembler to make iron gear wheels
result = entity_ops.set_entity_recipe(
    "assembling-machine-1",
    "iron-gear-wheel",
    position=MapPosition(x=12.5, y=4.5),
)
if result.success:
    print(f"Recipe set: {result.recipe_name}")
```

→ Returns EntityRecipeSet with the configured recipe

*Repurposing a machine (clear before setting a new recipe):*

```python
# Clear a machine's recipe
result = entity_ops.set_entity_recipe("assembling-machine-1", None)
```

→ Recipe is cleared



#### `entity_ops.set_entity_filter`

```python
set_entity_filter(entity_name: str, position: MapPosition, inventory_type: str, filter_index: Optional[int] = ..., filter_item: Optional[str] = ...) -> EntityFilterSet
```

Set or clear an inventory filter on an entity (e.g., filter inserter).

**Decision Points:**
- Pass filter_item=None to clear a filter slot

**Examples:**

*Restricting which items an inserter handles:*

Preconditions: Entity supports filters, Entity is within reach

```python
# Make a filter inserter only move iron plates
result = entity_ops.set_entity_filter(
    "fast-inserter",
    MapPosition(x=3.5, y=2.5),
    inventory_type="main",
    filter_index=1,
    filter_item="iron-plate",
)
print(f"Filter set: {result.filter_item}")
```

→ Returns EntityFilterSet with the applied filter



#### `entity_ops.set_inventory_limit`

```python
set_inventory_limit(entity_name: str, inventory_type: str, limit: Optional[int] = ..., position: Optional[MapPosition] = ...) -> InventoryLimitSet
```

Set the inventory bar limit (red bar) on a container.

**Decision Points:**
- Pass limit=None to remove the limit

**Examples:**

*Preventing containers from absorbing too many items:*

```python
# Limit a chest to 10 slots to avoid over-buffering
result = entity_ops.set_inventory_limit(
    "iron-chest",
    inventory_type="main",
    limit=10,
)
if result.success:
    print(f"Limit set to {result.limit} slots")
```

→ Returns InventoryLimitSet with the applied limit



#### `entity_ops.take_inventory_item`

```python
take_inventory_item(entity_name: str, inventory_type: str, item_name: str, count: Optional[int] = ..., position: Optional[MapPosition] = ...) -> InventoryItemTaken
```

Take items from an entity's inventory into the agent's inventory.

**Decision Points:**
- Omit count to take all available items
- Check result.is_partial - transfers can be smaller than requested

**Examples:**

*Collecting outputs from machines or chests:*

Preconditions: Entity is within reach, Items exist in the named inventory

```python
# Collect smelted plates from a furnace
result = entity_ops.take_inventory_item(
    "stone-furnace",
    inventory_type="output",
    item_name="iron-plate",
)
print(f"Took {result.count} iron plates")
if result.is_partial:
    print("Agent inventory could not fit everything")
```

→ Returns InventoryItemTaken with actual count transferred



#### `entity_ops.put_inventory_item`

```python
put_inventory_item(entity_name: str, inventory_type: str, items: Union[ItemStack, List[ItemStack]], position: Optional[MapPosition] = ...) -> Union[InventoryItemPut, List[InventoryItemPut]]
```

Put items from the agent's inventory into an entity's inventory.

**Decision Points:**
- Pass a list of ItemStacks to perform multiple transfers in sequence
- Check result.is_partial - partial inserts SUCCEED with count < requested_count; result.message says the rest returned to your inventory

**Examples:**

*Loading machines with fuel or ingredients:*

Preconditions: Items are in agent inventory, Entity is within reach

```python
# Fuel a furnace with coal from the agent's inventory
stacks = inventory.create_item_stacks("coal", count=10)
result = entity_ops.put_inventory_item(
    "stone-furnace",
    inventory_type="fuel",
    items=stacks[0],
)
print(f"Inserted {result.count} coal")
```

→ Returns InventoryItemPut with actual count transferred


**Error Handling:**

- **`RuntimeError`**: Invalid inventory_type name (valid: 'auto', 'fuel', 'input', 'chest', 'output', 'modules')
  - Resolution: Use one of the listed names; 'auto' lets the engine route fuel/ingredients automatically
- **`RuntimeError`**: Target inventory cannot accept ANY of the item (full, or item not allowed there) — fails before anything moves
  - Resolution: Free space with take_inventory_item() or pick a different inventory_type
- **`RuntimeError`**: Insufficient items in agent inventory (message states have/need) or entity not found / out of reach
  - Resolution: Acquire more items, fix entity_name/position, or walk closer


#### `entity_ops.inspect_entity`

```python
inspect_entity(entity_name: str, position: MapPosition) -> Dict[str, Any]
```

Get comprehensive volatile state for an entity as a raw dict.

**Decision Points:**
- Prefer entity.inspect() via reachable_view - it returns typed EntityInspection
- Use this raw form only when working outside the typed entity layer

**Examples:**

*Reading raw entity state when no typed entity object is at hand:*

Preconditions: Entity is within reach

```python
# Inspect a furnace's full state
state = entity_ops.inspect_entity(
    "stone-furnace", MapPosition(x=10.5, y=10.5)
)
print(f"Status: {state.get('status')}")
```

→ Returns raw dict with entity state (structure varies by type)



#### `entity_ops.pickup_entity`

```python
pickup_entity(entity_name: str, position: Optional[MapPosition] = ...) -> EntityPickedUp
```

Pick up a placed entity from the map into the agent's inventory.

**Decision Points:**
- Entity inventories are extracted along with the entity itself
- Prefer entity.pickup() when you already hold the entity object

**Examples:**

*Removing/relocating placed entities:*

Preconditions: Entity is within reach and can be picked up

```python
# Pick up a misplaced chest (contents come along)
result = entity_ops.pickup_entity(
    "iron-chest", position=MapPosition(x=8.5, y=8.5)
)
if result.has_items:
    print(f"Extracted: {result.extracted_items}")
```

→ Entity removed from map, item + contents in agent inventory





## View Classes

### ReachableView

**Accessor:** `reachable_view`

Query interface for nearby entities and resources within agent's interaction range. Returns entities with REACHABLE view (full mutation access).

**When to use:** Use reachable_view when you need to interact with entities (set recipes, insert items, read inventory). Data is always fresh from the game.

**Notes:**
- Always fetches fresh data - no caching
- Ghosts are included by default for spatial awareness
- Returned entities have full affordances (inspect, place, configure)
- Resource queries return minable resources (ores, trees, rocks)

#### `reachable_view.get_entity`

```python
get_entity(entity_name: str, position: Optional[MapPosition] = ..., options: Optional[Dict[str, Any]] = ...) -> Optional['BaseEntity']
```

Get a single entity matching criteria. Returns entity with REACHABLE view.

**Decision Points:**
- Use get_entity() for single result when you expect at most one
- Use get_entities() when you need to iterate over multiple
- Pass options={'include_ghosts': False} to exclude ghosts

**Examples:**

*Finding a nearby entity to interact with:*

```python
# Find a specific furnace by name
furnace = reachable_view.get_entity("stone-furnace")
if furnace:
    print(f"Found furnace at {furnace.position}")
    # REACHABLE view allows inspection
    state = furnace.inspect()
```

→ Returns BaseEntity with REACHABLE view or None

*Verifying entity at known location:*

```python
# Find entity at specific position
drill = reachable_view.get_entity(
    "burner-mining-drill",
    position=MapPosition(x=10, y=10)
)
```

→ Returns entity at exact position or None

*Finding entity configured for specific production:*

```python
# Find entity with specific recipe
assembler = reachable_view.get_entity(
    "assembling-machine-1",
    options={"recipe": "iron-gear-wheel"}
)
```

→ Returns assembler with matching recipe or None

*Finding ghosts to build or remove:*

```python
# Find only ghost entities
ghost = reachable_view.get_entity(
    "stone-furnace",
    options={"ghosts_only": True}
)
if ghost:
    print(f"Ghost furnace at {ghost.position}")
    # Can build the ghost
    await ghost.build()
```

→ Returns ghost entity or None



#### `reachable_view.get_entities`

```python
get_entities(entity_name: Optional[str] = ..., options: Optional[Dict[str, Any]] = ...) -> List['BaseEntity']
```

Get all entities matching criteria. Returns list with REACHABLE view.

**Decision Points:**
- Returns empty list if no matches (never None)
- Filter by entity_type for broader categories
- Use options={'status': 'no_power'} to find unpowered entities (hyphens are normalized to underscores, so 'no-power' also works; raw int status codes are accepted too)

**Examples:**

*Finding all entities of a type to process:*

```python
# Get all nearby inserters
inserters = reachable_view.get_entities("inserter")
print(f"Found {len(inserters)} inserters")
for ins in inserters:
    print(f"  {ins.name} at {ins.position}")
```

→ Returns list of BaseEntity (may be empty)

*Surveying nearby area:*

```python
# Get all entities (no filter)
all_entities = reachable_view.get_entities()
# Group by type
from collections import Counter
counts = Counter(e.name for e in all_entities)
for name, count in counts.most_common(5):
    print(f"  {name}: {count}")
```

→ Returns all entities in interaction range



#### `reachable_view.get_ghosts`

```python
get_ghosts(entity_name: Optional[str] = ...) -> List['BaseEntity']
```

Get ghost entities matching criteria. Convenience wrapper for get_entities with ghosts_only=True.

**Decision Points:**
- Use get_ghosts() when specifically looking for unbuild structures
- Ghosts can be built with entity.build() method

**Examples:**

*Building all planned structures:*

```python
# Get all ghosts to build
ghosts = reachable_view.get_ghosts()
for ghost in ghosts:
    print(f"Ghost {ghost.name} at {ghost.position}")
    # Build each ghost
    await ghost.build()
```

→ Returns list of ghost entities

*Building specific entity type ghosts:*

```python
# Get ghosts of specific type
belt_ghosts = reachable_view.get_ghosts("transport-belt")
print(f"Found {len(belt_ghosts)} belt ghosts to build")
```

→ Returns filtered ghost list



#### `reachable_view.get_resource`

```python
get_resource(resource_name: str, position: Optional[MapPosition] = ...) -> Optional[Any]
```

Get a single resource (ore, tree, rock) matching criteria.

**Decision Points:**
- Resources include ores (iron-ore, copper-ore, coal, stone)
- Also includes trees and rocks (type='entity')
- Use get_resources() for multiple results

**Examples:**

*Finding mineable resources:*

```python
# Find iron ore to mine
ore = reachable_view.get_resource("iron-ore")
if ore:
    print(f"Iron ore at {ore.position}, amount: {ore.amount}")
    # Can mine directly
    items = await ore.mine(max_count=10)
```

→ Returns BaseResource with mining capability or None

*Verifying resource at known location:*

```python
# Find resource at specific position
coal = reachable_view.get_resource("coal", MapPosition(x=5, y=5))
```

→ Returns resource at position or None



#### `reachable_view.get_resources`

```python
get_resources(resource_name: Optional[str] = ..., resource_type: Optional[str] = ...) -> List[Any]
```

Get resources matching criteria. Returns ResourceOrePatch for grouped ores.

**Decision Points:**
- Use resource_type='ore' for ore patches only
- Use resource_type='entity' for trees/rocks
- Multiple ore tiles of same type are consolidated into ResourceOrePatch

**Examples:**

*Surveying available resources:*

```python
# Get all ore patches
ores = reachable_view.get_resources(resource_type="ore")
for patch in ores:
    print(f"{patch.name}: {patch.total} total")
```

→ Returns list of resources/patches

*Finding harvestable environment objects:*

```python
# Get trees and rocks
entities = reachable_view.get_resources(resource_type="entity")
trees = [r for r in entities if "tree" in r.name.lower()]
rocks = [r for r in entities if "rock" in r.name.lower()]
print(f"Trees: {len(trees)}, Rocks: {len(rocks)}")
```

→ Returns trees and rocks as BaseResource




### RemoteView

**Accessor:** `remote_view`

DuckDB-backed map queries for entities across the entire map. Provides read-only access via SQL queries. Entities have REMOTE view (walk_to, inspect only).

**When to use:** Use remote_view for map-wide planning: finding resources, counting entities, spatial queries. Data is synced via UDP for near real-time updates.

**Notes:**
- Read-only view - cannot modify entities directly
- Entities automatically convert to REACHABLE after walk_to()
- Uses DuckDB for fast spatial queries
- Lifecycle methods (load, start, stop) are managed by the runtime

#### `remote_view.get_entities`

```python
get_entities(sql: str) -> List['BaseEntity']
```

Execute SQL query and return entity instances with REMOTE view.

**Decision Points:**
- REMOTE entities have limited affordances (walk_to, inspect)
- Use SQL WHERE clauses for efficient filtering
- After walk_to(), entity becomes REACHABLE with full access

**Examples:**

*Finding entities anywhere on the map:*

```python
# Find all mining drills on the map
drills = remote_view.get_entities('''
    SELECT * FROM map_entity
    WHERE entity_name = 'burner-mining-drill'
''')
print(f"Found {len(drills)} mining drills")

# Navigate to first one
if drills:
    await drills[0].walk_to()
    # After walk_to, entity becomes REACHABLE
```

→ Returns list of BaseEntity with REMOTE view

*Querying entities in a rectangular area:*

```python
# Find entities in a specific area
entities = remote_view.get_entities('''
    SELECT * FROM map_entity
    WHERE position_x BETWEEN 0 AND 100
    AND position_y BETWEEN 0 AND 100
''')
```

→ Returns entities within bounds

*Finding nearest entities to a point:*

```python
# Find closest furnace to a position
target_x, target_y = 50, 50
furnaces = remote_view.get_entities(f'''
    SELECT *,
           SQRT(POW(position_x - {target_x}, 2) + POW(position_y - {target_y}, 2)) as dist
    FROM map_entity
    WHERE entity_name = 'stone-furnace'
    ORDER BY dist
    LIMIT 5
''')
```

→ Returns entities sorted by distance



#### `remote_view.find_water`

```python
find_water(near: Optional['MapPosition'] = ..., radius: Optional[float] = ..., limit: int = ...) -> List[Dict[str, Any]]
```

Find water-tile centers on the map as search hints. Results are not walkable destinations and are not validated offshore-pump anchors. Terrain affordance — never probe placements to discover terrain.

**Decision Points:**
- Empty list + stale chunk_snapshot_meta tick means OLD DATA, not 'no water'
- Never pass a returned water-tile position to walking.walk_to()
- Resolve placement_hints.find_offshore_pump_sites() before travelling or placing

**Examples:**

*Finding a water cluster before resolving a pump anchor:*

```python
# Nearest water to my position
pos = walking.current_position
water = remote_view.find_water(near=pos, radius=120)
if water:
    closest = water[0]
    print(f"Water at ({closest['x']}, {closest['y']}), {closest['distance']:.1f} tiles away")
else:
    # Distinguish 'no water' from 'stale snapshot' before concluding
    freshness = remote_view.query("SELECT MAX(tick) AS t FROM chunk_snapshot_meta")
    print(f"No water in range; snapshot tick {freshness[0]['t']}")
```

→ List of water-tile search hints sorted by distance, or []; do not walk to or place at a returned tile



#### `remote_view.get_entity`

```python
get_entity(sql: str) -> Optional['BaseEntity']
```

Execute SQL with LIMIT 1 and return single entity.

**Decision Points:**
- Convenience method for single result queries
- LIMIT 1 is added if not present

**Examples:**

*Finding any entity of a type:*

```python
# Find any available furnace
furnace = remote_view.get_entity('''
    SELECT * FROM map_entity
    WHERE entity_name = 'stone-furnace'
    LIMIT 1
''')
if furnace:
    await furnace.walk_to()
```

→ Returns single BaseEntity or None



#### `remote_view.get_resources`

```python
get_resources(sql: str) -> List['BaseResource']
```

Execute SQL against resource tables and return resource instances.

**Examples:**

*Locating resource deposits:*

```python
# Find all iron ore on the map
iron = remote_view.get_resources('''
    SELECT * FROM resource_tile
    WHERE name = 'iron-ore'
''')
print(f"Found {len(iron)} iron ore tiles")
```

→ Returns list of BaseResource with REMOTE view



#### `remote_view.get_ghosts`

```python
get_ghosts(sql: str) -> List['BaseEntity']
```

Execute SQL against ghost table and return ghost entities.

**Examples:**

*Finding blueprint ghosts to build:*

```python
# Find all planned but unbuilt structures
ghosts = remote_view.get_ghosts('''
    SELECT * FROM ghost
    WHERE ghost_name LIKE '%assembling%'
''')
print(f"Found {len(ghosts)} assembler ghosts")
```

→ Returns list of ghost entities



#### `remote_view.query`

```python
query(sql: str) -> List[Dict[str, Any]]
```

Execute raw SQL query and return list of dicts.

**Decision Points:**
- Use for aggregations, counts, and existence checks
- Use get_entities() when you need entity objects

**Examples:**

*Custom aggregation queries:*

```python
# Get entity counts by type
results = remote_view.query('''
    SELECT entity_name, COUNT(*) as count
    FROM map_entity
    GROUP BY entity_name
    ORDER BY count DESC
    LIMIT 10
''')
for row in results:
    print(f"{row['entity_name']}: {row['count']}")
```

→ Returns list of row dictionaries

*Checking area availability:*

```python
# Check if area is clear for building
clear = len(remote_view.query('''
    SELECT 1 FROM map_entity
    WHERE position_x BETWEEN 10 AND 15
    AND position_y BETWEEN 10 AND 15
    LIMIT 1
''')) == 0
print(f"Area is {'clear' if clear else 'occupied'}")
```

→ Returns empty list if area is clear



#### `remote_view.count_entities`

```python
count_entities(entity_name: Optional[str] = ...) -> int
```

Count entities, optionally filtered by name.

**Examples:**

*Quick entity counts without full query:*

```python
# Count all entities
total = remote_view.count_entities()
print(f"Total entities: {total}")

# Count specific type
drills = remote_view.count_entities("burner-mining-drill")
print(f"Mining drills: {drills}")
```

→ Returns integer count



#### `remote_view.is_tile_occupied`

```python
is_tile_occupied(tile_x: int, tile_y: int) -> bool
```

Fast check if a tile is occupied by any entity.

**Decision Points:**
- O(1) lookup using footprint_tiles index
- Faster than get_entity_at_tile() for existence check

**Examples:**

*Checking tile availability before placement:*

```python
# Check before placing
if not remote_view.is_tile_occupied(5, 10):
    print("Tile is clear for placement")
else:
    print("Tile is occupied")
```

→ Returns True/False



#### `remote_view.get_entity_at_tile`

```python
get_entity_at_tile(tile_x: int, tile_y: int) -> Optional['BaseEntity']
```

Get entity occupying a specific tile (uses footprint lookup).

**Examples:**

*Identifying entity at known tile:*

```python
# Find what's at a tile
entity = remote_view.get_entity_at_tile(5, 10)
if entity:
    print(f"Tile occupied by {entity.name}")
else:
    print("Tile is empty")
```

→ Returns BaseEntity or None



#### `remote_view.get_entities_in_tile_area`

```python
get_entities_in_tile_area(min_tile_x: int, min_tile_y: int, max_tile_x: int, max_tile_y: int, entity_name: Optional[str] = ...) -> List['BaseEntity']
```

Get all entities with footprints overlapping a rectangular tile area.

**Decision Points:**
- Uses tile-based indexing for efficiency
- Includes entities whose footprints overlap the area

**Examples:**

*Querying entities in tile-aligned area:*

```python
# Get entities in a 10x10 area
entities = remote_view.get_entities_in_tile_area(0, 0, 9, 9)
print(f"Found {len(entities)} entities in area")

# Filter by type
inserters = remote_view.get_entities_in_tile_area(
    0, 0, 9, 9,
    entity_name="inserter"
)
```

→ Returns list of entities in area



#### `remote_view.get_entities_at_anchor_tile`

```python
get_entities_at_anchor_tile(tile_x: int, tile_y: int) -> List['BaseEntity']
```

Get entities whose anchor (center) is at a specific tile.

**Examples:**

*Finding entities by their center position:*

```python
# Find entities centered at tile
entities = remote_view.get_entities_at_anchor_tile(5, 10)
# Different from get_entity_at_tile which checks footprint overlap
```

→ Returns list of entities anchored at tile



#### `remote_view.get_power_networks`

```python
get_power_networks(as_of_tick: Optional[int] = ...) -> PowerNetworksReport
```

Per-network power census from the latest power sample: anchor pole, pole/member counts, production/consumption/storage, headroom ratio, per-prototype breakdowns, and low_power/no_power member counts.

**Decision Points:**
- Engine network_id is ephemeral (renumbers on merge/split) — the anchor pole is the durable reference
- headroom_ratio is production/consumption, or None when consumption is 0
- low_power/no_power counts use map_entity's as-of-write electric_network_id (see freshness_note)

**Examples:**

*Checking whether the factory's networks are over/under-supplied:*

```python
# Survey every electric network's supply vs demand
report = remote_view.get_power_networks()
if report.sample_tick is None:
    print("No power sample yet")
else:
    for net in report.networks:
        print(net.anchor_pole_name, net.production_w, net.consumption_w)
        print(f"  {net.no_power_count} no_power, {net.low_power_count} low_power")
    print(report.freshness_note)
```

→ Returns PowerNetworksReport (sample_tick None if no sample ingested)



#### `remote_view.diagnose_power`

```python
diagnose_power(entity_name: str, position: Any, as_of_tick: Optional[int] = ...) -> PowerDiagnosis
```

Diagnose why an entity is unpowered (or confirm it is fine) in one call: status -> pole coverage -> network generation -> undersupply -> upstream generator starvation.

**Decision Points:**
- verdict is one of working/not_covered_by_any_pole/network_has_no_generation/network_undersupplied/upstream_generator_starved/no_status_data/entity_not_found/non_electric_or_no_issue
- A fuel-starved generator still reports 'working' — the explanation flags this
- Poles report nil status; diagnosing a pole returns non_electric_or_no_issue

**Examples:**

*Triaging a no_power / low_power entity without a manual multi-query walk:*

```python
# Why is this assembler dark?
diag = remote_view.diagnose_power("assembling-machine-1", pos)
print(diag.verdict)       # e.g. 'not_covered_by_any_pole'
print(diag.explanation)   # human-readable, with live caveats
print(diag.production_w, diag.consumption_w)
```

→ Returns PowerDiagnosis with a verdict, explanation, and supporting numbers




### VerifyView

**Accessor:** `verify`

Live engine confirmation of power / coverage facts. The snapshot DB answers WHICH poles/entities exist; verify answers IS IT TRUE RIGHT NOW via live reads. Positions/statuses/network-ids are live at call time; supply distances and collision boxes are prototype-derived (static).

**When to use:** Use verify before committing a build to a pole spine, or to confirm an entity is actually powered. supply_coverage previews coverage geometry (including an as-if-placed proposed_pole) so a fractional-tile miss is visible BEFORE the entities go dark.

**Notes:**
- Coverage is the engine rule: entity collision box intersects pole supply box
- margin is signed: overlap depth if covered, shortest move (with axis) if not
- supply areas render tile-aligned in ascii_map (as Factorio computes them)
- No snapshot lag — reads hit the running engine directly via RCON

#### `verify.supply_coverage`

```python
supply_coverage(entities: Optional[List[Target]] = ..., area: Optional[Dict[str, Any]] = ..., proposed_pole: Optional[Tuple[str, Any]] = ...) -> SupplyCoverageReport
```

Check whether every electric consumer's collision box actually intersects a pole's supply area, with per-entity margins and a tile-aligned ascii map. Optionally score an as-if-placed proposed_pole (pre-placement preview).

**Decision Points:**
- Pass entities explicitly, or an area to discover live consumers
- proposed_pole is scored as if already placed — nothing is built
- margin_axis is 'X', 'Y', or 'XY'; margin is tiles (overlap depth or shortfall)

**Examples:**

*Previewing coverage geometry before a drill line commits to a pole spine:*

```python
# The attempt-5 miss, made visible: a medium-pole spine at y=64.5
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
        print(c.entity_name, c.margin, c.margin_axis, c.detail)
```

→ Returns SupplyCoverageReport; drill NOT covered (0.15 on Y), furnace covered

*Choosing where to place a new pole so it actually covers the target:*

```python
# Pre-placement preview: move the pole one tile closer (proposed_pole)
# and watch the drill flip to covered without placing anything.
report = verify.supply_coverage(
    entities=[("electric-mining-drill", MapPosition(x=5.5, y=59.5))],
    area={"left_top": {"x": 0, "y": 55}, "right_bottom": {"x": 12, "y": 68}},
    proposed_pole=("medium-electric-pole", MapPosition(x=5.5, y=63.5)),
)
print(report.summary, report.covered_count, "of", report.total_count)
```

→ Proposed pole flips the drill to covered in the preview



#### `verify.powered`

```python
powered(targets: Union[Target, List[Target]]) -> Dict[str, PoweredCheck]
```

Live power status of one or many entities, keyed 'name@(x,y)'. powered == on an electric network AND not reporting no_power.

**Decision Points:**
- A fuel-starved producer still reports 'working' — cross-check network wattages
- found=False means no such entity within 0.6 tiles of the given position

**Examples:**

*Verifying entities actually receive power after wiring a network:*

```python
# Confirm the drill and furnace power state right now
checks = verify.powered([
    ("electric-mining-drill", MapPosition(x=5.5, y=59.5)),
    ("electric-furnace", MapPosition(x=5.5, y=62.5)),
])
for key, chk in checks.items():
    print(key, chk.powered, chk.status_name, chk.electric_network_id)
```

→ Dict of PoweredCheck; uncovered drill powered=False (no_power)



#### `verify.connected`

```python
connected(a: Target, b: Target) -> ConnectedCheck
```

Whether two entities share one live electric network right now (same non-nil electric_network_id).

**Decision Points:**
- Network ids are ephemeral (renumber on merge/split) — this is a right-now fact

**Examples:**

*Confirming a generator actually feeds the intended pole network:*

```python
# Are the EEI and the pole on the same network?
check = verify.connected(
    ("electric-energy-interface", MapPosition(x=2.5, y=64.5)),
    ("medium-electric-pole", MapPosition(x=5.5, y=64.5)),
)
print(check.connected, check.explanation)
```

→ Returns ConnectedCheck with connected bool and an explanation





## Placement & Spatial Reasoning

### PlacementHints

**Accessor:** `placement_hints`

Spatial reasoning engine for entity placement. Generates validated GhostPlan objects for lines, connections, and pole coverage. No side effects - validation only.

**When to use:** Use placement_hints to plan entity layouts before placement. Get validated positions for belts, pipes, poles, and connection puzzles (drill→furnace, inserter placement).

**Notes:**
- Pure computation - never mutates game state
- Uses Lua mod for engine values (drop_position, fluidbox, wire_connector)
- Returns GhostPlan objects ready for ghost_builder.build_plan()
- Validates positions against current game state

#### `placement_hints.get_placement_line`

```python
get_placement_line(entity_name: str, start: MapPosition, end: MapPosition, width: int = ..., validate: bool = ...) -> GhostPlan
```

Calculate a line of entities from start to end with inferred direction.

**Decision Points:**
- Direction is inferred from drag vector (horizontal→EAST/WEST, vertical→NORTH/SOUTH)
- Use validate=False to skip validation (faster but may have invalid positions)
- plan.validate(validator) can re-validate after state changes

**Examples:**

*Planning belt/pipe lines:*

```python
# Plan a belt line from (0,0) to (10,0)
plan = placement_hints.get_placement_line(
    entity_name="transport-belt",
    start=MapPosition(x=0, y=0),
    end=MapPosition(x=10, y=0)
)
print(f"Planned {len(plan.positions)} belts")
print(f"Valid: {plan.valid}")

# Commit plan to create ghosts
if plan.valid:
    await ghost_builder.build_plan(plan)
```

→ Returns GhostPlan with validated positions

*Planning fluid transport lines:*

```python
# Plan a pipe line
pipe_plan = placement_hints.get_placement_line(
    entity_name="pipe",
    start=MapPosition(x=0, y=0),
    end=MapPosition(x=0, y=20),
    validate=True  # Default, validates all positions
)
# Check for invalid positions
invalid_count = sum(1 for pos, dir in pipe_plan.positions if not pipe_plan.valid)
print(f"Invalid positions: {invalid_count}")
```

→ Returns validated pipe positions



#### `placement_hints.is_buildable`

```python
is_buildable(left_top: MapPosition, right_bottom: MapPosition, entity_name: str = ...) -> Dict[str, Any]
```

Check whether an area is buildable land WITHOUT placing anything (non-mutating engine validation). Never place/pickup entities to probe terrain.

**Decision Points:**
- Max 1600 tiles per call - probe sub-areas for bigger regions
- Blocked tiles include water, cliffs, existing entities and out-of-map
- Use find_water() to locate water; this method tells you where you CANNOT build

**Examples:**

*Validating a build site before committing a layout:*

```python
# Is this 10x10 site clear for a factory block?
result = placement_hints.is_buildable(
    left_top=MapPosition(x=20, y=20),
    right_bottom=MapPosition(x=30, y=30),
)
if result["all_buildable"]:
    print("Site is clear")
else:
    print(f"{result['buildable_count']}/{result['total']} tiles buildable")
    print(f"Blocked at: {result['blocked_positions'][:5]}")
```

→ Dict with all_buildable, buildable_count, total, blocked_positions



#### `placement_hints.find_offshore_pump_sites`

```python
find_offshore_pump_sites(near: MapPosition, radius: int = ..., max_results: int = ...) -> List[ConnectionPosition]
```

Find live engine-validated offshore-pump anchors. Each result contains the placement position, required direction, and an engine-derived standable approach position within build reach; these are not merely nearby water tiles. Results are ordered nearest-anchor first.

**Decision Points:**
- remote_view.find_water() returns water tiles, not pump anchors
- Water-tile hints are not walking targets; resolve sites before travelling
- Walk to site.approach_position, never site.position
- Place at site.position and use site.direction unchanged
- If walking cannot reach one approach position, try the next returned site
- Increase radius or choose another water cluster only when the result is empty

**Examples:**

*Placing an offshore pump without guessing shoreline anchors:*

```python
water = remote_view.find_water(near=MapPosition(x=0, y=0), radius=80)
sites = placement_hints.find_offshore_pump_sites(
    near=MapPosition(x=water[0]["x"], y=water[0]["y"]),
    radius=20,
    max_results=20,
)
if not sites:
    raise RuntimeError("No validated offshore-pump site in the searched area")
site = sites[0]
# site.position can overlap water. Walk only to the supplied standable land
# position, then place at the anchor with its validated direction unchanged.
await walking.walk_to(site.approach_position, strict_goal=False)
pump = inventory.get_item("offshore-pump")
pump.place(site.position, site.direction)
```

→ Returns nearest-first validated anchor, direction, and standable-approach candidates



#### `placement_hints.get_connection_positions`

```python
get_connection_positions(source_entity: BaseEntity, target_entity_name: str, connection_type: ConnectionType) -> ConnectionPositionList
```

Find valid positions where target entity can connect to source entity.

**Decision Points:**
- ITEM_DROP: mining-drill → furnace/chest/belt (furnace is most common - direct output, no inserter needed!)
- FLUID_PIPE: fluid machines (boiler, pump, etc.) → pipe → Returns ConnectionPosition
- ELECTRIC_WIRE: electric poles → electric poles → Returns WireConnectionPosition
- Lower perpendicular_offset = better alignment with source entity
- For ELECTRIC_WIRE, use wire_distance_utilization to optimize pole spacing
- The returned list is a ConnectionPositionList: still indexable/iterable like a plain list, but an empty result also carries `.reason` (why zero candidates), and for ELECTRIC_WIRE `.max_wire_distance` — check these instead of treating [] as an unexplained dead end (REASON-1)

**Examples:**

*Placing furnace to receive drill output directly (most efficient):*

```python
# ITEM_DROP: Place furnace directly at drill's drop position
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
    # Furnace will automatically receive ore from drill - no inserter needed!
```

→ Returns List[ConnectionPosition] - furnace receives ore without inserters

*Connecting fluid network to machines (FLUID_PIPE):*

```python
# FLUID_PIPE: Returns List[ConnectionPosition]
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
    item.place(positions[0].position, positions[0].direction)
```

→ Returns List[ConnectionPosition] with required directions

*Extending power network (ELECTRIC_WIRE returns WireConnectionPosition):*

```python
# ELECTRIC_WIRE: Returns List[WireConnectionPosition]
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
    item.place(optimal[0].position)
```

→ Returns List[WireConnectionPosition] with distance metrics


**Error Handling:**

- **`EntityValidationError`**: Source entity doesn't support the connection type
  - Resolution: Check entity type - only drills support ITEM_DROP, only poles support ELECTRIC_WIRE, etc.


#### `placement_hints.get_inserter_placement_positions`

```python
get_inserter_placement_positions(source_entity: BaseEntity, target_entity: BaseEntity, inserter_name: str = ...) -> List[Tuple[MapPosition, Direction]]
```

Find valid inserter positions to transfer items between two entities.

**Decision Points:**
- Inserter direction points toward drop-off (target)
- Different inserter types have different reach
- Consider stack inserters for higher throughput

**Examples:**

*Automating item transfer between entities:*

```python
# Find inserter position from chest to furnace
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
        item.place(pos, direction)
```

→ Returns list of (MapPosition, Direction) tuples

*Using long-reach inserters for larger gaps:*

```python
# Find long-handed inserter positions (longer reach)
positions = placement_hints.get_inserter_placement_positions(
    source_entity=chest,
    target_entity=furnace,
    inserter_name="long-handed-inserter"
)
# Long-handed inserters can reach further, more options
```

→ Returns positions with appropriate reach



#### `placement_hints.get_pole_line`

```python
get_pole_line(start: MapPosition, end: MapPosition, pole_name: str = ..., validate: bool = ...) -> GhostPlan
```

Plan a line of electric poles at maximum wire distance intervals.

**Decision Points:**
- Pole spacing based on max wire distance (small=7.5, medium=9, big=30, substation=18)
- Big poles are good for long distance, small/medium for local distribution

**Examples:**

*Running power line across distance:*

```python
# Plan pole line from start to end
plan = placement_hints.get_pole_line(
    start=MapPosition(x=0, y=0),
    end=MapPosition(x=50, y=0),
    pole_name="medium-electric-pole"
)

print(f"Need {len(plan.positions)} poles")
# Poles are spaced at max wire distance (9 for medium poles)

if plan.valid:
    await ghost_builder.build_plan(plan)
```

→ Returns GhostPlan with optimally spaced poles

*Optimizing power line cost:*

```python
# Compare pole types for coverage
for pole_type in ["small-electric-pole", "medium-electric-pole", "big-electric-pole"]:
    plan = placement_hints.get_pole_line(
        start=MapPosition(x=0, y=0),
        end=MapPosition(x=100, y=0),
        pole_name=pole_type,
        validate=False  # Skip validation for comparison
    )
    print(f"{pole_type}: {len(plan.positions)} poles needed")
```

→ Shows pole count comparison



#### `placement_hints.get_pole_coverage_position`

```python
get_pole_coverage_position(entities_to_power: List[BaseEntity], pole_name: str = ...) -> Optional[MapPosition]
```

Find a single pole position that covers ALL given entities.

**Decision Points:**
- Returns None if entities spread beyond supply diameter
- Substations have largest supply area (9 tile radius)
- Consider get_pole_coverage_plan() for multiple poles

**Examples:**

*Minimizing poles for compact areas:*

```python
# Find pole position to power multiple machines
machines = reachable_view.get_entities("assembling-machine-1")

pos = placement_hints.get_pole_coverage_position(
    entities_to_power=machines,
    pole_name="medium-electric-pole"
)

if pos:
    print(f"Place pole at {pos} to cover all machines")
else:
    print("Entities too spread out for single pole")
```

→ Returns MapPosition or None if impossible



#### `placement_hints.get_pole_coverage_plan`

```python
get_pole_coverage_plan(entities_to_power: List[BaseEntity], pole_name: str = ...) -> Tuple[GhostPlan, List[BaseEntity]]
```

Find minimum poles to cover all entities using greedy set cover algorithm.

**Decision Points:**
- Greedy algorithm - not globally optimal but good enough
- Returns uncovered entities if some can't be reached
- Consider splitting into smaller groups if many uncovered

**Examples:**

*Optimal pole placement for arbitrary layouts:*

```python
# Plan poles to power scattered entities
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
    await ghost_builder.build_plan(plan)
```

→ Returns (GhostPlan, list of uncovered entities)



#### `placement_hints.get_underground_segment`

```python
get_underground_segment(entity_name: str, start: MapPosition, end: MapPosition, direction: Direction) -> GhostPlan
```

Plan an underground belt or pipe segment between two points.

**Decision Points:**
- Max distances: underground-belt=4, fast=6, express=8, pipe-to-ground=10
- Exit direction is automatically set to opposite of entry

**Examples:**

*Bypassing obstacles with underground transport:*

```python
# Plan underground belt to cross obstacle
plan = placement_hints.get_underground_segment(
    entity_name="underground-belt",
    start=MapPosition(x=0, y=0),
    end=MapPosition(x=4, y=0),
    direction=Direction.EAST
)

# Plan includes entry and exit belts with correct directions
print(f"Entry at {plan.positions[0]}")
print(f"Exit at {plan.positions[1]}")
```

→ Returns GhostPlan with entry/exit positions


**Error Handling:**

- **`ValueError`**: Distance exceeds underground max distance
  - Resolution: Use shorter segments or upgrade belt tier


#### `placement_hints.evaluate_pole_placement`

```python
evaluate_pole_placement(position: MapPosition, pole_name: str, source_pole: Optional[BaseEntity] = ..., reachable_view: Optional[Any] = ...) -> PolePlacementResult
```

Dry-run evaluation of a pole placement position (no actual placement).

**Decision Points:**
- No side effects - purely evaluates position
- Useful for comparing multiple candidate positions
- Checks wire connectivity, power coverage, and placement validity

**Examples:**

*Evaluating pole positions before commitment:*

```python
# Evaluate a potential pole position
result = placement_hints.evaluate_pole_placement(
    position=MapPosition(x=10, y=10),
    pole_name="medium-electric-pole",
    source_pole=existing_pole,  # Optional: check wire connection
    reachable_view=reachable_view  # Optional: check entity coverage
)

print(f"Valid placement: {result.is_valid_placement}")
print(f"Entities powered: {result.entities_powered_count}")
print(f"Connects to source: {result.connects_to_source}")
print(f"Distance to source: {result.distance_to_source}")
```

→ Returns PolePlacementResult with detailed metrics



#### `placement_hints.validator`

```python
validator: PlacementValidator
```

Access the PlacementValidator for direct validation operations.

**Decision Points:**
- Use validator directly for custom validation logic
- Batch validation is more efficient than individual calls
- ghost=True validates for ghost placement (different collision rules)

**Examples:**

*Single position validation:*

```python
# Validate a single position
valid = placement_hints.validator.validate_placement(
    entity_name="stone-furnace",
    position=MapPosition(x=5, y=5),
    direction=Direction.NORTH,
    ghost=True
)
print(f"Can place furnace: {valid}")
```

→ Returns PlacementValidator instance

*Efficient batch validation:*

```python
# Batch validate positions
positions = [MapPosition(x=i, y=0) for i in range(10)]
results = placement_hints.validator.validate_batch(
    entity_name="transport-belt",
    positions=positions,
    directions=[Direction.EAST] * 10,
    ghost=True
)

valid_count = sum(results)
print(f"{valid_count}/{len(results)} positions valid")
```

→ Returns list of booleans




### GhostBuilderAction

**Accessor:** `ghost_builder`

Orchestrates ghost placement and building. Converts GhostPlan objects into placed ghosts, then builds them into real entities.

**When to use:** Use ghost_builder to commit validated GhostPlan objects from placement_hints. Also use for building existing ghost entities on the map.

**Notes:**
- Works with both GhostPlan objects and ghost entities from queries
- Handles walking to positions automatically
- Use strict=True to validate inventory before building

#### `ghost_builder.build_ghosts`

```python
async build_ghosts(ghosts: List[BaseEntity], count: int = ..., strict: bool = ...) -> Dict[str, Any]
```

Build ghost entities in bulk by walking to each and placing real entities.

**Decision Points:**
- Use count to limit how many ghosts to build in one call
- Use strict=True to fail fast if inventory is insufficient
- Works with ghosts from reachable_view, remote_view, or any source

**Examples:**

*Building existing ghost entities:*

```python
# Get ghosts and build them
ghosts = reachable_view.get_ghosts()
result = await ghost_builder.build_ghosts(ghosts, count=10)

print(f"Built: {result['built_count']}")
print(f"Failed: {result['failed_count']}")
```

→ Returns dict with built_count, failed_count, built_ghosts, failed_ghosts

*Building ghosts with inventory validation:*

```python
# Build with strict inventory validation
ghosts = remote_view.get_ghosts("SELECT * FROM ghost WHERE ghost_name = 'transport-belt'")
result = await ghost_builder.build_ghosts(ghosts, strict=True)

if "error" in result:
    print(f"Insufficient items: {result['error']}")
else:
    print(f"Built {result['built_count']} belts")
```

→ Returns error if items missing, otherwise builds



#### `ghost_builder.build_ghost`

```python
async build_ghost(ghost: BaseEntity) -> bool
```

Build a single ghost entity. Convenience wrapper for build_ghosts.

**Decision Points:**
- Use for single ghost when you only need one
- Use build_ghosts() for multiple ghosts (more efficient)

**Examples:**

*Building a single specific ghost:*

```python
# Build a single ghost
ghost = reachable_view.get_ghosts("stone-furnace")[0]
success = await ghost_builder.build_ghost(ghost)
if success:
    print("Furnace ghost built!")
```

→ Returns True if successfully built, False otherwise



#### `ghost_builder.build_plan`

```python
async build_plan(plan: GhostPlan, strict: bool = ...) -> Dict[str, Any]
```

Build a GhostPlan by placing ghosts at all positions.

**Decision Points:**
- Always check plan.valid before calling build_plan
- Use strict=True for early failure on inventory issues
- This is the main way to commit placement_hints results

**Examples:**

*Committing a GhostPlan from placement_hints:*

```python
# Commit a validated placement plan
plan = placement_hints.get_placement_line(
    "transport-belt",
    start=MapPosition(x=0, y=0),
    end=MapPosition(x=10, y=0)
)

if plan.valid:
    result = await ghost_builder.build_plan(plan)
    print(f"Placed {result.get('placed_count', 0)} ghosts")
```

→ Places ghosts at all plan positions

*Building plan with inventory check:*

```python
# Build plan with strict validation
plan = placement_hints.get_pole_line(
    start=MapPosition(x=0, y=0),
    end=MapPosition(x=50, y=0),
    pole_name="medium-electric-pole"
)

result = await ghost_builder.build_plan(plan, strict=True)
if "error" in result:
    print(f"Cannot build: {result['error']}")
```

→ Validates inventory before placing


**Error Handling:**

- **`KeyError`**: GhostPlan is invalid (validation failed)
  - Resolution: Re-validate the plan or use a fresh plan from placement_hints




## Entity Inspection Schema

The `EntityInspection` class is returned by `.inspect()` on all entities.
It uses optional capability slots - only relevant slots are populated.

### Base Fields

| Field | Type |
|-------|------|
| `name` | `str` |
| `position` | `Dict[str, float]` |
| `direction` | `Optional[Direction]` |
| `status` | `Optional[EntityStatus]` |
| `is_ghost` | `bool` |

### Capability Slots

Each slot is `Optional` - only populated if the entity has that capability.

#### `accumulator`: `AccumulatorState`

*State for accumulator entities (stub - implement later).*

| Field | Type | Notes |
|-------|------|-------|
| `energy` | `float` |  |
| `capacity` | `float` |  |
| `charge_percentage` | `float` | (property) Get charge as percentage (0-100). |

#### `belt`: `BeltState`

*State for transport belt entities.*

| Field | Type | Notes |
|-------|------|-------|
| `belt_shape` | `Optional[str]` |  |
| `belt_inputs` | `List[BeltNeighbour]` |  |
| `belt_outputs` | `List[BeltNeighbour]` |  |
| `belt_to_ground_type` | `Optional[str]` |  |
| `underground_neighbour` | `Optional[BeltNeighbour]` |  |
| `linked_belt_neighbour` | `Optional[BeltNeighbour]` |  |
| `linked_belt_type` | `Optional[str]` |  |
| `splitter_filter` | `Optional[str]` |  |
| `splitter_input_priority` | `Optional[str]` |  |
| `splitter_output_priority` | `Optional[str]` |  |

#### `burner`: `BurnerState`

*State for burner-powered entities.*

| Field | Type | Notes |
|-------|------|-------|
| `heat` | `float` |  |
| `heat_capacity` | `float` |  |
| `remaining_burning_fuel` | `float` |  |
| `currently_burning` | `Optional[str]` |  |
| `fuel_inventory` | `Dict[str, int]` |  |

#### `container`: `ContainerState`

*State for container entities.*

| Field | Type | Notes |
|-------|------|-------|
| `contents` | `Dict[str, int]` |  |
| `inventory_size` | `int` |  |
| `filters` | `Dict[int, str]` |  |
| `is_empty` | `bool` | (property) Check if container has no items. |
| `total_items` | `int` | (property) Get total item count. |

#### `crafter`: `CrafterState`

*State for crafting machines.*

| Field | Type | Notes |
|-------|------|-------|
| `recipe` | `Optional[str]` |  |
| `crafting_progress` | `float` |  |
| `crafting_speed` | `float` |  |
| `is_crafting` | `bool` |  |
| `crafter_input` | `Dict[str, int]` |  |
| `crafter_output` | `Dict[str, int]` |  |
| `crafter_modules` | `Dict[str, int]` |  |

#### `electric`: `ElectricState`

*State for electric-powered entities.*

| Field | Type | Notes |
|-------|------|-------|
| `energy` | `float` |  |
| `buffer_capacity` | `float` |  |
| `electric_network_id` | `Optional[int]` |  |
| `charge_percentage` | `float` | (property) Get charge as percentage (0-100). |

#### `electric_pole`: `ElectricPoleState`

*State for electric pole entities.*

| Field | Type | Notes |
|-------|------|-------|
| `electric_network_id` | `Optional[int]` |  |
| `wired_to_other_pole` | `Optional[bool]` |  |
| `connected_poles` | `List[PoleNeighbour]` |  |
| `supply_area_entities` | `List[PoleNeighbour]` |  |
| `supply_area_entity_count` | `int` |  |
| `is_connected` | `Optional[bool]` | (property) Deprecated alias for `wired_to_other_po... |

#### `fluid`: `FluidState`

*State for fluid-handling entities.*

| Field | Type | Notes |
|-------|------|-------|
| `fluidboxes` | `List[FluidBox]` |  |
| `capacity` | `float` |  |
| `connections` | `List[FluidConnection]` |  |
| `total_fluid` | `float` | (property) Get total fluid amount across all boxes... |

#### `generator`: `GeneratorState`

*State for generator entities (stub - implement later).*

| Field | Type | Notes |
|-------|------|-------|
| `power_output` | `float` |  |
| `max_power_output` | `float` |  |
| `effectivity` | `float` |  |

#### `inserter`: `InserterState`

*State for inserter entities.*

| Field | Type | Notes |
|-------|------|-------|
| `held_item` | `Optional[HeldItem]` |  |
| `pickup_position` | `Optional[Dict[str, float]]` |  |
| `drop_position` | `Optional[Dict[str, float]]` |  |
| `pickup_target` | `Optional[str]` |  |
| `drop_target` | `Optional[str]` |  |
| `filters` | `List[str]` |  |

#### `lab`: `LabState`

*State for lab entities (stub - implement later).*

| Field | Type | Notes |
|-------|------|-------|
| `research_progress` | `float` |  |
| `researching_speed` | `float` |  |
| `science_packs` | `Dict[str, int]` |  |

#### `miner`: `MinerState`

*State for mining drills.*

| Field | Type | Notes |
|-------|------|-------|
| `mining_progress` | `float` |  |
| `mining_target` | `Optional[MiningTarget]` |  |
| `drop_position` | `Optional[Dict[str, float]]` |  |
| `drop_target` | `Optional[str]` |  |

### Examples

**Getting volatile runtime state from an entity:**

*Preconditions: Entity exists and is reachable*

```python
drill = reachable_view.get_entity('burner-mining-drill')
inspection = drill.inspect()

# Base fields (always present)
print(inspection.name)       # 'burner-mining-drill'
print(inspection.position)   # {'x': 10.5, 'y': 20.5}
print(inspection.status)     # EntityStatus.WORKING

# Capability slots - check for None before accessing
if inspection.burner:
    print(f"Fuel: {inspection.burner.fuel_inventory}")
    print(f"Heat: {inspection.burner.heat}")

if inspection.miner:
    print(f"Mining progress: {inspection.miner.mining_progress}")
    print(f"Target: {inspection.miner.mining_target}")

# Compact JSON output (excludes None fields)
json_str = inspection.model_dump_json(exclude_none=True)
```

→ EntityInspection with populated capability slots based on entity type

**Checking entity-specific capabilities:**

*Preconditions: Entity exists*

```python
# Different entities have different capability slots populated
furnace = reachable_view.get_entity('stone-furnace')
inspection = furnace.inspect()

# Furnace has: burner (fuel), crafter (smelting)
if inspection.burner:
    remaining = inspection.burner.remaining_burning_fuel
    print(f"Fuel remaining: {remaining}")

if inspection.crafter:
    if inspection.crafter.recipe:
        print(f"Smelting: {inspection.crafter.recipe}")
        print(f"Progress: {inspection.crafter.crafting_progress:.1%}")
```

→ Only relevant slots are non-None


## Core Types

### MapPosition

World coordinates with sub-tile precision (floating point x, y). Used for entity positions, pathfinding targets, and spatial queries.

**Fields:**
- `x`: X coordinate (float) - positive is east
- `y`: Y coordinate (float) - positive is south

**Examples:**

*Working with map coordinates:*

```python
# Create a position
pos = MapPosition(x=10.5, y=20.5)
print(f"Position: ({pos.x}, {pos.y})")

# Calculate distance
other = MapPosition(x=15.5, y=20.5)
dist = pos.distance(other)  # 5.0

# From dict (common when parsing game data)
pos = MapPosition.from_dict({"x": 10, "y": 20})
```

→ MapPosition object with x, y attributes


### TilePosition

Integer tile coordinates. Factorio's map is divided into 1x1 tiles. Used for tile-based queries and footprint calculations.

**Fields:**
- `x`: Tile X coordinate (integer)
- `y`: Tile Y coordinate (integer)

**Examples:**

*Working with tile coordinates:*

```python
# Create tile position
tile = TilePosition(x=5, y=10)

# Convert from MapPosition (truncates to tile)
pos = MapPosition(x=5.7, y=10.3)
tile_x, tile_y = int(pos.x), int(pos.y)  # 5, 10

# Tile-based queries
entity = remote_view.get_entity_at_tile(tile.x, tile.y)
```

→ TilePosition object with integer x, y


### Direction

Cardinal directions for entity orientation. Factorio uses 8-direction system internally but most entities only use 4 cardinal directions.

**Values:**
- `NORTH` = 0
- `NORTH_NORTH_EAST` = 1
- `NORTH_EAST` = 2
- `EAST_NORTH_EAST` = 3
- `EAST` = 4
- `EAST_SOUTH_EAST` = 5
- `SOUTH_EAST` = 6
- `SOUTH_SOUTH_EAST` = 7
- `SOUTH` = 8
- `SOUTH_SOUTH_WEST` = 9
- `SOUTH_WEST` = 10
- `WEST_SOUTH_WEST` = 11
- `WEST` = 12
- `WEST_NORTH_WEST` = 13
- `NORTH_WEST` = 14
- `NORTH_NORTH_WEST` = 15

**Examples:**

*Orienting entities:*

```python
# Direction values
Direction.NORTH  # 0 - Up
Direction.EAST   # 2 - Right
Direction.SOUTH  # 4 - Down
Direction.WEST   # 6 - Left

# Use for entity placement
item.place(position, Direction.EAST)

# Check entity direction
drill = reachable_view.get_entity("burner-mining-drill")
if drill.direction == Direction.SOUTH:
    print("Drill facing south")
```

→ Direction enum member

*Understanding insertion direction:*

```python
# Direction in placement hints
positions = placement_hints.get_inserter_placement_positions(
    source_entity=chest,
    target_entity=furnace,
    inserter_name="inserter"
)
for pos, direction in positions:
    print(f"Place at {pos} facing {direction.name}")
```

→ Direction indicates where inserter drops items


### ConnectionType

Connection types for solving entity placement puzzles. Each type represents a different way entities can connect (item drop, fluid, wire). CRITICAL: ITEM_DROP is for mining drills (push directly to adjacent entities); you cannot use inserters with drills as source. Inserters are NOT a connection type - use get_inserter_placement_positions(source, target) instead.

**Values:**
- `ITEM_DROP` = item_drop
- `FLUID_PIPE` = fluid_pipe
- `ELECTRIC_WIRE` = wire

**Examples:**

*Choosing connection type for placement:*

```python
# Available connection types
ConnectionType.ITEM_DROP    # Mining drill -> Chest/Belt (drills push directly, no inserters)
ConnectionType.FLUID_PIPE   # Pipe -> Machine/Pipe
ConnectionType.ELECTRIC_WIRE   # Pole -> Pole
# For inserters: placement_hints.get_inserter_placement_positions(source, target)

# Use with get_connection_positions
positions = placement_hints.get_connection_positions(
    source_entity=drill,
    target_entity_name="iron-chest",
    connection_type=ConnectionType.ITEM_DROP
)
```

→ ConnectionType enum member


### GhostPlan

A validated placement plan ready for commitment via ghost_builder. Contains entity positions, directions, and validation status.

**Fields:**
- `entity_name`: Name of entity to place
- `positions`: List of (MapPosition, Optional[Direction]) tuples
- `label`: Unique identifier for the plan
- `description`: Human-readable description
- `valid`: True if all positions are validated

**Examples:**

*Working with placement plans:*

```python
# GhostPlan from placement_hints
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
plan.validate(placement_hints.validator)
```

→ GhostPlan ready for ghost_builder.build_plan()


### ConnectionPosition

A valid position for placing a target entity to connect to a source. Returned by get_connection_positions().

**Fields:**
- `position`: MapPosition where target can be placed
- `direction`: Required direction for target (or None)
- `approach_position`: Optional standable MapPosition within build reach; always set for offshore-pump sites
- `perpendicular_offset`: Alignment metric (0.0 = perfect alignment)

**Examples:**

*Understanding connection results:*

```python
# ConnectionPosition from get_connection_positions
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
        print(f"Required direction: {best.direction}")
```

→ ConnectionPosition with placement details



---

*Generated from registry on 2026-08-29 11:36:40*