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
| `reachable_view` | ReachableView | Query interface for nearby entities and resources within agent's interaction range |
| `remote_view` | RemoteView | DuckDB-backed map queries for entities across the entire map |
| `walking` | MovementAction | Handles agent walking and pathfinding |
| `crafting` | CraftingAction | Handles hand-crafting operations |
| `research` | ResearchAction | Handles technology research |
| `inventory` | AgentInventory | Query and shape agent inventory contents |
| `entity_reference` | EntityReferenceAccessor | Hold an entity type on your cursor without placing it |
| `entity_reference(...)` | EntityReference | The object entity_reference(name) returns |

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
| `Item` | `FactoryVerse.game.factory.item.base` |
| `ItemStack` | `FactoryVerse.game.factory.item.base` |
| `MapPosition` | `FactoryVerse.game.factory.types` |
| `PlaceableItem` | `FactoryVerse.game.factory.item.base` |
| `QueuedTechnology` | `FactoryVerse.game.agent.embodied_actions.research` |
| `ResearchQueueItem` | `FactoryVerse.game.factory.types` |
| `ResearchStatus` | `FactoryVerse.game.agent.embodied_actions.research` |
| `WalkingEntityNotFoundError` | `FactoryVerse.game.agent.embodied_actions.walking` |
| `WalkingError` | `FactoryVerse.game.agent.embodied_actions.walking` |
| `WalkingNoStandableTilesError` | `FactoryVerse.game.agent.embodied_actions.walking` |
| `WalkingUnreachableError` | `FactoryVerse.game.agent.embodied_actions.walking` |
| `WireConnectionPosition` | `FactoryVerse.game.agent.placement_hints` |


## Quick Reference

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
- `status(max_positions: int = ..., statuses: Optional[List[str]] = ...)`
- `status_changed(since_tick: int)`
- `power(as_of_tick: Optional[int] = ...)`
- `get_power_networks(as_of_tick: Optional[int] = ...)`
- `production(agent_id: Optional[int] = ...)`
- `diagnose_power(entity_name: str, position: Any, as_of_tick: Optional[int] = ...)`

### `walking`

Handles agent walking and pathfinding. All walking is asynchronous - methods return when the agent reaches the destination or fails.

**Methods:**
- `async walk_to(goal: MapPosition, strict_goal: bool = ..., options: Optional[Dict] = ..., timeout: Optional[int] = ...)`
- `stop()`
- `current_position: MapPosition`

### `crafting`

Handles hand-crafting operations. Craft recipes asynchronously with queue management.

**Methods:**
- `enqueue(recipe: str, count: int = ...)`
- `dequeue(recipe: str, count: Optional[int] = ...)`
- `status()`
- `list_recipes(name_filter: Optional[str] = ..., hand_craftable: Optional[bool] = ..., category: Optional[str] = ...)`
- `take_predictions()`
- `predictions: List[CraftPrediction]`

### `research`

Handles technology research. Queue technologies and monitor progress.

**Methods:**
- `enqueue(technology: str)`
- `dequeue(force: bool = ...)`
- `status()`
- `get_queue()`
- `list_technologies(name_filter: Optional[str] = ..., available: Optional[bool] = ..., researched: Optional[bool] = ...)`

### `inventory`

Query and shape agent inventory contents. Provides methods to check counts and create ItemStack objects for placement.

**Methods:**
- `check_total(item_name: str)`
- `get_item(item_name: str)`
- `create_item_stacks(item_name: str, count: Union[int, Literal[half, full]], number_of_stacks: Union[int, Literal[max]] = ..., strict: bool = ...)`
- `async await_item(item_name: str, count: int = ..., timeout_ticks: int = ..., poll_seconds: float = ...)`
- `item_stacks: List[ItemStack]`

### `entity_reference`

Hold an entity type on your cursor without placing it. entity_reference("small-electric-pole") returns a read-only reference that answers what the placement preview would show: footprint, whether it can go here, the supply overlay a pole would project, a drill's drop arrow, where an inserter could sit between two machines, where an offshore pump could sit. It cannot place anything and holds no inventory — placing still goes through inventory.get_item(name).place().

### `entity_reference(...)`

The object entity_reference(name) returns. Read-only planning answers for one entity type.

**Methods:**
- `footprint(position: MapPosition, direction: Optional[Direction] = ...)`
- `can_place(position: MapPosition, direction: Optional[Direction] = ...)`
- `supply_area(position: MapPosition)`
- `covers(position: MapPosition, entity: 'BaseEntity')`
- `wire_reach(position: MapPosition, other: 'BaseEntity')`
- `drop_position(position: MapPosition, direction: Direction = ...)`
- `placements_between(source: 'BaseEntity', target: 'BaseEntity')`
- `sites(near: MapPosition, radius: int = ..., max_results: int = ...)`


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



#### `crafting.list_recipes`

```python
list_recipes(name_filter: Optional[str] = ..., hand_craftable: Optional[bool] = ..., category: Optional[str] = ...) -> List[Dict[str, Any]]
```

The recipe catalog as the crafting screen lists it. A read — nothing is queued. hand_craftable tells you whether a character can make it (smelting is machine-only); craftable_now is an annotation, not a filter.

**Examples:**

*Finding what you can hand-craft from what you hold:*

```python
for r in crafting.list_recipes(name_filter="iron", hand_craftable=True):
    print(r["name"], r["ingredients"], "now" if r["craftable_now"] else "")
```

→ A list of dicts sorted by name



#### `crafting.take_predictions`

```python
take_predictions() -> List[CraftPrediction]
```

Hand the completion predictions recorded at enqueue to the turn report and clear them. The report calls this once per turn; you do not need to.

**Examples:**

*Harness use; the turn report does this for you:*

```python
pending = crafting.take_predictions()
print(len(pending), "predictions handed to the report")
```

→ The pending CraftPrediction list, now cleared



#### `crafting.predictions`

```python
predictions: List[CraftPrediction]
```

The completion predictions recorded at enqueue (recipe energy at speed 1, summed serially) that no turn report has consumed yet.

**Examples:**

*Seeing when queued crafts will finish, in game ticks:*

```python
crafting.enqueue("iron-gear-wheel", count=5)
for p in crafting.predictions:
    print(p.recipe, p.count, "done by tick", p.predicted_completion_tick)
```

→ A list of CraftPrediction




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
dequeue(force: bool = ...) -> Dict[str, Any]
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



#### `research.list_technologies`

```python
list_technologies(name_filter: Optional[str] = ..., available: Optional[bool] = ..., researched: Optional[bool] = ...) -> List[Dict[str, Any]]
```

The technology catalog as the research screen lists it. A read — nothing is queued. available means every prerequisite is researched and it can be queued now. Use this to discover names; never discover by enqueueing.

**Examples:**

*Choosing the next research:*

```python
for t in research.list_technologies(available=True):
    print(t["name"], t["science_packs"], t["unit_count"], "unlocks", t["unlocks"])
```

→ A list of dicts: available first, then locked, then researched




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

# Check before queueing a craft
if inventory.check_total("iron-plate") >= 10:
    crafting.enqueue("iron-gear-wheel", count=5)
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



#### `inventory.await_item`

```python
async await_item(item_name: str, count: int = ..., timeout_ticks: int = ..., poll_seconds: float = ...) -> AwaitItemResult
```

Wait, bounded, for an item to be in your inventory. Returns at once if held; refuses at once if nothing in your crafting queue produces it; otherwise waits up to timeout_ticks and returns actuals — never raises. The wait spends the turn's clock like anything else.

**Decision Points:**
- Prefer the state-join: check inventory.check_total() at the start of the block that needs the items
- Use await_item when the craft is short and you will place the items this turn
- A long craft outlasts the bound: end the turn and the items arrive while the world runs

**Examples:**

*Needing crafted items in this same turn before placing them:*

```python
crafting.enqueue("iron-gear-wheel", count=5)
got = await inventory.await_item("iron-gear-wheel", count=5, timeout_ticks=600)
if got:
    print("have", got.have)
else:
    print(got.reason, "have", got.have, "still queued", got.remaining_in_queue)
```

→ AwaitItemResult; truthy when satisfied



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
- Resolve entity_reference("offshore-pump").sites(near=...) before travelling or placing

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



#### `remote_view.status`

```python
status(max_positions: int = ..., statuses: Optional[List[str]] = ...) -> StatusSummary
```

Base-wide entity status summary — which problem, how many, roughly where — read from the newest status dump on disk (source = status_dump:<tick>), never from a table. The per-entity status seen at scale.

**Decision Points:**
- source names the dump block; age_ticks says how stale it is — a dump is a snapshot, not a live read
- Poles carry no status and never appear; a fuel-starved generator still reads 'working'
- Drill into one machine with entity.status (live); a pole's coverage of it is pole.covers(entity)

**Examples:**

*Checking the factory for problems without inspecting entities one at a time:*

```python
# What is wrong right now, and where?
summary = remote_view.status(statuses=["no_power", "low_power", "no_fuel", "no_minable_resources"])
print(summary.source, "age", summary.age_ticks, "ticks")
for name, group in summary.groups.items():
    print(name, group.count, group.entities[:3], f"+{group.more} more")
```

→ Returns StatusSummary (tick None and no groups when no dump exists yet)



#### `remote_view.status_changed`

```python
status_changed(since_tick: int) -> StatusChange
```

Status transitions since a tick — what became unhappy and what recovered — by diffing two status dump blocks (source = status_dump:<from>-><to>).

**Decision Points:**
- The earlier block is the newest at or before since_tick; the window on disk is bounded

**Examples:**

*Reviewing what happened to the base over a period:*

```python
# What changed since I last looked?
change = remote_view.status_changed(since_tick=12000)
for label, transitions in change.grouped().items():
    print(label, len(transitions), transitions[0].entity)
```

→ Returns StatusChange with transitions grouped by before -> after



#### `remote_view.power`

```python
power(as_of_tick: Optional[int] = ...) -> PowerNetworksReport
```

Per-network power census from the newest power sample on disk (source = power_dump:<tick>): anchor pole, pole/member counts, production/consumption/storage, headroom ratio, per-prototype breakdowns, and low_power/no_power member counts from the newest status dump.

**Decision Points:**
- Engine network_id is ephemeral (renumbers on merge/split) — the anchor pole is the durable reference
- headroom_ratio is production/consumption, or None when consumption is 0
- low_power/no_power counts use map_entity's as-of-write electric_network_id (see freshness_note)

**Examples:**

*Checking whether the factory's networks are over/under-supplied:*

```python
# Survey every electric network's supply vs demand
report = remote_view.power()
if report.sample_tick is None:
    print("No power sample yet")
else:
    for net in report.networks:
        print(net.anchor_pole_name, net.production_w, net.consumption_w)
        print(f"  {net.no_power_count} no_power, {net.low_power_count} low_power")
    print(report.source, report.freshness_note)
```

→ Returns PowerNetworksReport (sample_tick None if no sample on disk)



#### `remote_view.get_power_networks`

```python
get_power_networks(as_of_tick: Optional[int] = ...) -> PowerNetworksReport
```

Alias of remote_view.power() kept for older callers; prefer power().

**Examples:**

*Legacy name:*

```python
report = remote_view.get_power_networks()  # same as remote_view.power()
```

→ Returns PowerNetworksReport



#### `remote_view.production`

```python
production(agent_id: Optional[int] = ...) -> ProductionReport
```

Force production read live over RCON (source = live:<tick>) plus this agent's hand-crafted and hand-mined counts from its event records; automated() is the difference.

**Decision Points:**
- produced/consumed are cumulative force counters; diff two reads for a rate

**Examples:**

*Measuring automation rather than total output:*

```python
# How much is the factory making without my hands?
p = remote_view.production()
print(p.source, p.automated().get("iron-plate", 0), "automated plates")
print("hand-crafted:", p.hand_crafted)
```

→ Returns ProductionReport (source 'unavailable' without an engine connection)



#### `remote_view.diagnose_power`

```python
diagnose_power(entity_name: str, position: Any, as_of_tick: Optional[int] = ...) -> PowerDiagnosis
```

Diagnose why an entity is unpowered (or confirm it is fine) in one call: status -> pole coverage -> network generation -> undersupply -> upstream generator starvation.

**Decision Points:**
- Reads the newest status dump and power sample on disk (not tables); sample_tick says which sample
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





## Placement & Spatial Reasoning

### EntityReferenceAccessor

**Accessor:** `entity_reference`

Hold an entity type on your cursor without placing it. entity_reference("small-electric-pole") returns a read-only reference that answers what the placement preview would show: footprint, whether it can go here, the supply overlay a pole would project, a drill's drop arrow, where an inserter could sit between two machines, where an offshore pump could sit. It cannot place anything and holds no inventory — placing still goes through inventory.get_item(name).place().

**When to use:** Use it while planning, before you own the item or have walked anywhere: the same questions you would answer by holding the item and looking at the preview. Every answer says where it came from: 'prototype' (static data) or 'live' (an engine check right now). Anything about a machine's contents, status or network needs the real entity, not a reference.

**Notes:**
- Read-only: no method here changes the world
- Every method name also exists on the real entity class, so what you learn here transfers
- can_place() checks the engine's own placement rule live but not reach or inventory
- covers() uses the engine's box-against-box rule; a corner of a 3x3 machine inside the square counts


### EntityReference

**Accessor:** `entity_reference(...)`

The object entity_reference(name) returns. Read-only planning answers for one entity type.

**When to use:** Ask it the preview questions; ask the real entity everything else.

**Notes:**
- Results are SourcedValue: the value plus .source ('prototype' or 'live')

#### `entity_reference(...).footprint`

```python
footprint(position: MapPosition, direction: Optional[Direction] = ...) -> SourcedValue
```

Tiles this entity would occupy at a position and facing (source: prototype).

**Examples:**

*Checking how much room a machine takes before walking over:*

```python
ref = entity_reference("stone-furnace")
tiles = ref.footprint(MapPosition(x=10, y=10))
print(len(tiles), tiles.source)  # 4 prototype
```

→ A list of TilePosition, with .source == 'prototype'



#### `entity_reference(...).can_place`

```python
can_place(position: MapPosition, direction: Optional[Direction] = ...) -> SourcedValue
```

Could this be placed here right now? The engine's red/green preview, read live. Reach and inventory are not checked — the reference holds nothing.

**Examples:**

*Testing a spot before committing to walk there and place:*

```python
ref = entity_reference("burner-mining-drill")
ok = ref.can_place(MapPosition(x=34.5, y=-90.5), Direction.NORTH)
if ok:
    drill = inventory.get_item("burner-mining-drill").place(MapPosition(x=34.5, y=-90.5), Direction.NORTH)
```

→ SourcedValue(True/False, source='live')


**Error Handling:**

- **`RuntimeError`**: The reference was created without a live engine
  - Resolution: Only happens offline; in a run every reference is live


#### `entity_reference(...).supply_area`

```python
supply_area(position: MapPosition) -> SourcedValue
```

The supply box a pole would project from a position (source: prototype). Poles only.

**Examples:**

*Seeing the overlay before placing a pole:*

```python
pole = entity_reference("small-electric-pole")
box = pole.supply_area(MapPosition(x=0, y=0))
print(box)
```

→ A BoundingBox centre ± supply_area_distance



#### `entity_reference(...).covers`

```python
covers(position: MapPosition, entity: 'BaseEntity') -> SourcedValue
```

Would a pole at this position power that entity? Box-against-box, the engine's rule. Poles only.

**Examples:**

*Choosing where a pole goes so a machine is inside its area:*

```python
pole = entity_reference("small-electric-pole")
drill = reachable_view.get_entity("electric-mining-drill")
if drill and pole.covers(MapPosition(x=drill.position.x + 3, y=drill.position.y), drill):
    print("a pole 3 tiles east would power the drill")
```

→ SourcedValue(True/False, source='prototype')



#### `entity_reference(...).wire_reach`

```python
wire_reach(position: MapPosition, other: 'BaseEntity') -> SourcedValue
```

Would a pole here be within wire distance of that pole? A bound, not a promise of wiring. Poles only.


#### `entity_reference(...).drop_position`

```python
drop_position(position: MapPosition, direction: Direction = ...) -> SourcedValue
```

Where a drill at this position and facing drops its output — the arrow on the cursor. Drills only.

**Examples:**

*Deciding where the chest or belt goes before placing the drill:*

```python
drill = entity_reference("burner-mining-drill")
drop = drill.drop_position(MapPosition(x=34.5, y=-90.5), Direction.NORTH)
print(drop)  # the tile a chest or belt must occupy
```

→ SourcedValue(MapPosition, source='prototype')



#### `entity_reference(...).placements_between`

```python
placements_between(source: 'BaseEntity', target: 'BaseEntity') -> SourcedValue
```

Positions and facings where this inserter would move items from one placed entity into another. Both entities must exist. Zero candidates come back with a reason, never as an error. Inserters only.

**Examples:**

*Linking two machines with an inserter:*

```python
chest = reachable_view.get_entity("wooden-chest")
furnace = reachable_view.get_entity("stone-furnace")
answer = entity_reference("inserter").placements_between(chest, furnace)
for position, direction in answer["positions"]:
    print(position, direction)
if not answer["positions"]:
    print("why:", answer["reason"])
```

→ SourcedValue({'positions': [(MapPosition, Direction), ...], 'reason': str|None}, source='live')



#### `entity_reference(...).sites`

```python
sites(near: MapPosition, radius: int = ..., max_results: int = ...) -> SourcedValue
```

Where an offshore pump could sit near a position, with its required facing and a standable approach position. Offshore pumps only.

**Examples:**

*Finding water to start power:*

```python
sites = entity_reference("offshore-pump").sites(walking.position, radius=30)
for site in sites:
    print(site.position, site.direction, site.approach_position)
```

→ SourcedValue(list of ConnectionPosition, source='live')





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
positions = entity_reference("inserter").placements_between(chest, furnace).value["positions"]
for pos, direction in positions:
    print(f"Place at {pos} facing {direction.name}")
```

→ Direction indicates where inserter drops items


### ConnectionType

Connection types for solving entity placement puzzles. Each type represents a different way entities can connect (item drop, fluid, wire). CRITICAL: ITEM_DROP is for mining drills (push directly to adjacent entities); you cannot use inserters with drills as source. Inserters are NOT a connection type - use entity_reference('inserter').placements_between(source, target) instead.

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
# For inserters: entity_reference("inserter").placements_between(source, target)

# Usually inferred from the pair; pass it only to force a kind
cues = drill.connection_positions("iron-chest", connection_type=ConnectionType.ITEM_DROP)
```

→ ConnectionType enum member


### ConnectionPosition

A valid position for placing a target entity to connect to a source. Returned by entity.connection_positions(target_name) and entity_reference(target_name).connection_positions(source).

**Fields:**
- `position`: MapPosition where target can be placed
- `direction`: Required direction for target (or None)
- `approach_position`: Optional standable MapPosition within build reach; always set for offshore-pump sites
- `perpendicular_offset`: Alignment metric (0.0 = perfect alignment)

**Examples:**

*Understanding connection results:*

```python
# ConnectionPosition from a placed drill: where would a chest receive its ore?
positions = drill.connection_positions("iron-chest")

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

*Generated from registry on 2026-08-29 12:02:05*