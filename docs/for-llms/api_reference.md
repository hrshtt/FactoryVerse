# FactoryVerse LLM Reference

> Auto-generated via introspection on 2026-01-15 15:54

You are an embodied agent in Factorio. You have a physical presence, inventory, and can walk, craft, mine, and interact with entities.

---


## Top-Level Accessors

These are available as global variables in your runtime.

### `walking`

Movement actions.

```python
walking.current_position -> MapPosition
walking.stop() -> FactoryVerse.agent.embodied_actions.walking.WalkingStopped
await walking.walk_to(goal: MapPosition, strict_goal: bool = False, options: Optional[Dict] = None, timeout: Optional[int] = None) -> MapPosition
await walking.walk_to_entity(entity_name: str, entity_position: MapPosition, timeout: Optional[int] = None) -> MapPosition
```

### `crafting`

Crafting actions.

```python
await crafting.craft(recipe: str, count: int = 1, timeout: Optional[int] = None) -> List[ItemStack]
crafting.dequeue(recipe: str, count: Optional[int] = None) -> Dict[str, Any]
crafting.enqueue(recipe: str, count: int = 1) -> Dict[str, Any]
crafting.status() -> Dict[str, Any]
```

### `research`

Research and technology management.

```python
research.dequeue() -> Dict[str, Any]
research.enqueue(technology: str) -> Dict[str, Any]
research.get_queue() -> Dict[str, Any]
research.status() -> ResearchStatus
```

### `inventory`

Inventory queries and operations.

```python
inventory.check_total(item_name: str) -> int
inventory.create_item_stacks(item_name: str, count: Union[int, Literal['half', 'full']], number_of_stacks: Union[int, Literal['max']] = 'max', strict: bool = False) -> List[ItemStack]
inventory.get_item(item_name: str) -> Union[Item, PlaceableItem, NoneType]
inventory.item_stacks -> List[ItemStack]
```

### `reachable_view`

Unified reachable entity and resource queries.

```python
reachable_view.get_entities(entity_name: Optional[str] = None, options: Optional[Dict[str, Any]] = None) -> List['BaseEntity']
reachable_view.get_entity(entity_name: str, position: Optional[MapPosition] = None, options: Optional[Dict[str, Any]] = None) -> Optional['BaseEntity']
reachable_view.get_ghosts(entity_name: Optional[str] = None) -> List['BaseEntity']
reachable_view.get_resource(resource_name: str, position: Optional[MapPosition] = None) -> Optional[Any]
reachable_view.get_resources(resource_name: Optional[str] = None, resource_type: Optional[str] = None) -> List[Any]
```

### `remote_view`

Map-wide entity queries via DuckDB.

```python
remote_view.count_entities(entity_name: Optional[str] = None) -> int
remote_view.count_ghosts(ghost_name: Optional[str] = None) -> int
remote_view.debug_info() -> Dict[str, Any]
remote_view.flush() -> int
remote_view.get_entities(sql: str) -> List['BaseEntity']
remote_view.get_entity(sql: str) -> Optional['BaseEntity']
remote_view.get_ghosts(sql: str) -> List['BaseEntity']
remote_view.get_resources(sql: str) -> List['BaseResource']
remote_view.is_loaded -> bool
await remote_view.load(wait_for_bootstrap: bool = True, bootstrap_timeout: float = 120.0) -> FactoryVerse.agent.infra.snapshot.types.LoadResult
remote_view.query(sql: str) -> List[Dict[str, Any]]
remote_view.rebuild() -> FactoryVerse.agent.infra.snapshot.types.LoadResult
await remote_view.start() -> NoneType
await remote_view.stop() -> NoneType
remote_view.sync_state -> FactoryVerse.agent.infra.snapshot.types.SyncState
```

### `ghost_builder`

Ghost building orchestration.

```python
await ghost_builder.build_ghost(ghost: BaseEntity) -> bool
await ghost_builder.build_ghosts(ghosts: List[BaseEntity], count: int = 10, strict: bool = False) -> Dict[str, Any]
await ghost_builder.build_plan(plan: GhostPlan, strict: bool = False) -> Dict[str, Any]
```

### `placement_hints`

Spatial reasoning for entity placement.

```python
placement_hints.get_connection_positions(source_entity: BaseEntity, target_entity_name: str, connection_type: <enum 'ConnectionType) -> List[ConnectionPosition]
placement_hints.get_inserter_placement_positions(source_entity: BaseEntity, target_entity: BaseEntity, inserter_name: str = 'inserter') -> List[Tuple[MapPosition, Direction]]
placement_hints.get_placement_line(entity_name: str, start: MapPosition, end: MapPosition, width: int = 1, validate: bool = True) -> GhostPlan
placement_hints.get_pole_coverage_plan(entities_to_power: List[BaseEntity], pole_name: str = 'medium-electric-pole') -> Tuple[GhostPlan, List[BaseEntity]]
placement_hints.get_pole_coverage_position(entities_to_power: List[BaseEntity], pole_name: str = 'medium-electric-pole') -> Optional[MapPosition]
placement_hints.get_pole_line(start: MapPosition, end: MapPosition, pole_name: str = 'medium-electric-pole', validate: bool = True) -> GhostPlan
placement_hints.get_underground_segment(entity_name: str, start: MapPosition, end: MapPosition, direction: <enum 'Direction) -> GhostPlan
placement_hints.validator -> PlacementValidator
```


## Core Types

### MapPosition

Coordinates of a tile on the map.

```python
MapPosition(x: float, y: float)
```

**Methods:**
- `.distance(other: MapPosition) -> float` - Calculate Euclidean distance to another MapPosition.
- `.manhattan_distance(other: MapPosition) -> float` - Calculate Manhattan distance to another MapPosition.

### Direction

Cardinal directions for entity placement and rotation.

```python
Direction.NORTH
Direction.EAST
Direction.SOUTH
Direction.WEST
```

All 16 directions: `NORTH, NORTH_NORTH_EAST, NORTH_EAST, EAST_NORTH_EAST, EAST, EAST_SOUTH_EAST, SOUTH_EAST, SOUTH_SOUTH_EAST, SOUTH, SOUTH_SOUTH_WEST, SOUTH_WEST, WEST_SOUTH_WEST, WEST, WEST_NORTH_WEST, NORTH_WEST, NORTH_NORTH_WEST`

### ConnectionType

Connection types for placement planning.

```python
ConnectionType.ITEM_DROP  # item_drop
ConnectionType.FLUID_PIPE  # fluid_pipe
ConnectionType.INSERTER_REACH  # inserter
ConnectionType.BELT_FLOW  # belt_flow
ConnectionType.ELECTRIC_WIRE  # wire
```

---


## Getting Entities and Resources

### Reachable (Within Interaction Range)

Entities and resources you can interact with immediately.

```python
# Entities
entity = reachable_view.get_entity("stone-furnace")  # -> Optional[BaseEntity]
entities = reachable_view.get_entities("burner-mining-drill")  # -> List[BaseEntity]
ghosts = reachable_view.get_ghosts()  # -> List[BaseEntity]

# Resources
coal = reachable_view.get_resource("coal")  # -> Optional[BaseResource]
resources = reachable_view.get_resources()  # -> List[BaseResource]

# Mining (via resource object)
items = await coal.mine(max_count=25)  # -> List[ItemStack]
```

### Remote View (Map-Wide, Read-Only)

Query entities anywhere via SQL. Cannot mutate - walk to them first.

**IMPORTANT**: Use `entity.walk_to()` or `resource.walk_to()` on remote objects. After walking, the entity/resource **automatically becomes REACHABLE** and you can use it directly - no need to get it again via `reachable_view.get_entity()` or `reachable_view.get_resource()`.

```python
# Entities
drills = remote_view.get_entities("SELECT * FROM map_entity WHERE entity_name = 'electric-mining-drill'")  # -> List[BaseEntity]
drill = drills[0]

# Walk to the drill - it automatically becomes REACHABLE
await drill.walk_to()  # Entity-aware pathfinding

# Now you can use it directly - no need to get it again!
drill.add_fuel(inventory.create_item_stacks("coal", 5))

# Ghosts  
ghosts = remote_view.get_ghosts("SELECT * FROM ghost")  # -> List[BaseEntity]

# Resources
resources = remote_view.get_resources("SELECT * FROM resource_tile WHERE name = 'iron-ore'")  # -> List[BaseResource] (REMOTE view)
iron_ore = resources[0]

# Walk to the resource - it automatically becomes REACHABLE
await iron_ore.walk_to()  # Entity-aware pathfinding

# Now you can mine it directly!
items = await iron_ore.mine(max_count=25)

# Counts
count = remote_view.count_entities("stone-furnace")  # -> int
ghost_count = remote_view.count_ghosts("transport-belt")  # -> int

# Raw queries
rows = remote_view.query("SELECT entity_name, COUNT(*) FROM map_entity GROUP BY entity_name")  # -> List[Dict]
```

### View Distinction

| View | Source | Actions | Use Case |
|------|--------|---------|----------|
| REACHABLE | `reachable_view.*` | All actions available (no `walk_to` - already in range) | Interact with nearby entities |
| REMOTE | `remote_view.*` | Read-only (inspect, `walk_to`) | Query map-wide, then walk to interact |

---


## Item Types

### Item

Base class for items in inventory.

```python
item.name        # str - item prototype name
item.stack_size  # int - max stack size
```

### PlaceableItem

Items that can be placed as entities on the map.

```python
item.footprint  # Tuple[int, int]
item.place(position: MapPosition, direction: Optional[Direction] = NORTH) -> BaseEntity
item.place_ghost(position: MapPosition, direction: Optional[Direction] = NORTH, label: Optional[str] = None) -> bool
item.prototype  # Dict[str, Any]
item.tile_height  # int
item.tile_width  # int
```

### ItemStack

A quantity of items, used for inventory operations.

```python
stack.name   # str - item name
stack.count  # int - quantity
```

Used with: `entity.add_fuel(stacks)`, `entity.add_ingredients(stacks)`

---


## Resource Types

Resources represent mineable tiles on the map (ore, trees, rocks).

### ResourceOrePatch

Consolidated patch of resource tiles. Returned by `reachable_view.get_resources()`.

**Note:** `reachable_view.get_resources(name)` returns a **list of patches**, not individual tiles.

```python
patch.count  # int - Get number of resource tiles in this patch.
patch.get_resource_tile(position: MapPosition) -> Optional[FactoryVerse.factory.resource.base.BaseResource]
patch.inspect(raw_data: bool = False, live: bool = False) -> Union[str, ResourcePatchData]
await patch.mine(max_count: Optional[int] = None, timeout: Optional[int] = None) -> List['ItemStack']
patch.position  # MapPosition - Get the average position of all resource tiles in the patch.
patch.resource_type  # str - Get the resource type (resource, tree, rock).
patch.total  # int - Get total amount across all resource tiles in the patch.
```

**Indexing:** Access individual tiles via `patch[0]` -> `BaseResource`

### BaseResource

Individual resource tile. Access via `reachable_view.get_resource(name)` or `patch[index]`.

```python
resource.amount  # Optional[int] - Get resource amount (only for ore patches, None for trees/rocks).
resource.inspect(raw_data: bool = False, live: bool = False) -> Union[str, EntityInspectionData]
await resource.mine(max_count: Optional[int] = None, timeout: Optional[int] = None) -> List['ItemStack']
resource.products  # List[ProductData] - Get mineable products from this resource.
resource.resource_type  # str - Get the resource type (resource, tree, rock).
await resource.walk_to(timeout: Optional[int] = None) -> MapPosition
```

### Resources from `remote_view.get_resources()`

Resources from database queries have REMOTE view. Can walk to and inspect, but cannot mine.

```python
resource.name       # str - resource name
resource.position   # MapPosition - location on map
resource.total      # int - total amount (if patch)
resource.amount     # Optional[int] - amount (if single tile)
resource.inspect()  # str - formatted inspection
await resource.walk_to()  # ✓ Navigate to resource
# await resource.mine()   # ✗ AttributeError - REMOTE view blocks mine()
```

**To mine:** Use `await resource.walk_to()` to navigate. After walking, the resource **automatically becomes REACHABLE** and you can mine it directly - no need to get it again via `reachable_view.get_resource()`.

```python
# Preferred pattern:
iron_ore = remote_view.get_resources("SELECT * FROM resource_tile WHERE name = 'iron-ore' LIMIT 1")[0]
await iron_ore.walk_to()  # Automatically converts to REACHABLE
items = await iron_ore.mine(max_count=25)  # Use directly
```

### Patch vs Tile Distinction

| Method | Returns | Use `total` | Use `amount` |
|--------|---------|-------------|--------------|
| `reachable_view.get_resources(name)` | `List[ResourceOrePatch]` | ✓ | ✗ |
| `reachable_view.get_resource(name)` | `BaseResource` | ✗ | ✓ |
| `patch[index]` | `BaseResource` | ✗ | ✓ |
| `remote_view.get_resources(sql)` | `List[BaseResource]` (REMOTE view) | ✓/✗ (depends) | ✓/✗ (depends) |

---


## Action Availability

Actions are filtered based on **view type** and **ghost status**.

### View-Based Filtering

Remote entities are read-only - walk within range first.

| Action | Reachable | Remote |
|--------|-----------|--------|
| `add_fuel()` | ✓ | ✗ |
| `add_ingredients()` | ✓ | ✗ |
| `build()` | ✓ | ✗ |
| `inspect()` | ✓ | ✓ |
| `pickup()` | ✓ | ✗ |
| `remove()` | ✓ | ✓ |
| `set_recipe()` | ✓ | ✗ |
| `store_items()` | ✓ | ✗ |
| `take_items()` | ✓ | ✗ |
| `take_products()` | ✓ | ✗ |
| `walk_to()` | ✗ | ✓ |

### Ghost-Based Filtering

Ghosts are placeholders - no inventory or internal state.

| Action | Real Entity | Ghost |
|--------|-------------|-------|
| `add_fuel()` | ✓ | ✗ |
| `add_ingredients()` | ✓ | ✗ |
| `build()` | ✗ | ✓ |
| `inspect()` | ✓ | ✓ |
| `pickup()` | ✓ | ✗ |
| `remove()` | ✗ | ✓ |
| `set_recipe()` | ✓ | ✗ |
| `store_items()` | ✓ | ✗ |
| `take_items()` | ✓ | ✗ |
| `take_products()` | ✓ | ✗ |
| `walk_to()` | ✓ | ✓ |

---


## Placement Planning

Entity placement follows a three-tier flow for safety and validation:

### 1. Plan (Dry Run)

Use `placement_hints` to generate validated plans before committing:

```python
# Plan a line of belts
plan = placement_hints.get_placement_line(
    "transport-belt",
    start=MapPosition(0, 0),
    end=MapPosition(10, 0)
)  # -> GhostPlan

# Plans are pre-validated
if plan.valid:
    print(f"Plan has {len(plan.positions)} positions")
```

### Connection Types

`get_connection_positions()` solves spatial puzzles between entities.

```python
ConnectionType.ITEM_DROP  # item_drop
ConnectionType.FLUID_PIPE  # fluid_pipe
ConnectionType.INSERTER_REACH  # inserter
ConnectionType.BELT_FLOW  # belt_flow
ConnectionType.ELECTRIC_WIRE  # wire
```

### Entity Compatibility

Each `ConnectionType` only works with specific source entities. Using incompatible entities raises `EntityValidationError`.

| ConnectionType | Valid Source Entities |
|----------------|----------------------|
| `ITEM_DROP` | `burner-mining-drill`, `electric-mining-drill` |
| `FLUID_PIPE` | `boiler`, `chemical-plant`, `offshore-pump`, `oil-refinery`, `pipe`, `pipe-to-ground`, `pump`, `pumpjack`, `steam-engine`, `steam-turbine`, `storage-tank` |
| `INSERTER_REACH` | Use `get_inserter_placement_positions()` instead |
| `BELT_FLOW` | Use `get_placement_line()` |
| `ELECTRIC_WIRE` | Use `get_pole_line()` or `get_pole_coverage_*()` |

### Placement Constraints

Some entities have special placement requirements:

| Entity | Requirement |
|--------|-------------|
| `burner-mining-drill` | Must be placed on resource tiles |
| `electric-mining-drill` | Must be placed on resource tiles |
| `pumpjack` | Must be placed on resource tiles |
| `offshore-pump` | Must be placed on water tiles |

### Connection Example

```python
# Find where a pipe can connect to a boiler
# Note: placement_hints and ConnectionType are pre-loaded as global variables, no import needed

boiler = reachable_view.get_entity("boiler")
pipe_positions = placement_hints.get_connection_positions(
    source_entity=boiler,
    target_entity_name="pipe",
    connection_type=ConnectionType.FLUID_PIPE
)  # -> List[ConnectionPosition]

# Place pipes at valid positions
# Positions are sorted by alignment (lower perpendicular_offset = better aligned)
for conn_pos in pipe_positions:
    inventory.get_item("pipe").place(conn_pos.position, conn_pos.direction)
    # conn_pos.perpendicular_offset tells you how well-aligned this position is
```

**Return Value:**
- Returns `List[ConnectionPosition]` - structured objects with `.position`, `.direction`, and `.perpendicular_offset`
- Positions are sorted by alignment (lower `perpendicular_offset` = better aligned with source entity)
- `perpendicular_offset`: Distance from source entity perpendicular to flow direction (0.0 = perfectly aligned)
- `direction`: May be `None` if the target entity doesn't require explicit direction
- Entities like pipes, chests can be placed without direction (Factorio auto-determines it)
- Always pass `conn_pos.direction` directly to `place()` - it handles `None` gracefully

### Validation API

Access validation directly for custom checks:

```python
validator = placement_hints.validator

validator.validate_batch(entity_name: str, positions: List[MapPosition], directions: Optional[List[Optional[Direction]]] = None, ghost: bool = False) -> List[bool]
validator.validate_grid(entity_name: str, top_left: MapPosition, bottom_right: MapPosition, direction: Optional[Direction] = None, ghost: bool = False) -> Dict[MapPosition, bool]
validator.validate_line(entity_name: str, start: MapPosition, end: MapPosition, direction: Optional[Direction] = None, ghost: bool = False) -> List[Tuple[MapPosition, bool]]
validator.validate_placement(entity_name: str, position: MapPosition, direction: Optional[Direction] = None, ghost: bool = False) -> bool
```

**Build check types:**
- `ghost=False` → validates for real entity placement
- `ghost=True` → validates for ghost placement (less strict)

### Inserter Placement

```python
# Find where to place inserter connecting drill to furnace
drill = reachable_view.get_entity("electric-mining-drill")
furnace = reachable_view.get_entity("stone-furnace")

positions = placement_hints.get_inserter_placement_positions(
    source_entity=drill,
    target_entity=furnace,
    inserter_name="inserter"
)  # -> List[Tuple[MapPosition, Direction]]
```

### Pole Lines & Coverage

```python
# Connect distant areas with poles
plan = placement_hints.get_pole_line(
    start=mining_area,
    end=factory_pos,
    pole_name="big-electric-pole"
)  # Poles spaced at max wire distance

# Find single pole to cover multiple entities
drills = reachable_view.get_entities("electric-mining-drill")
pos = placement_hints.get_pole_coverage_position(drills)  # None if impossible

# Get minimum poles for coverage
plan, uncovered = placement_hints.get_pole_coverage_plan(drills)
```

### Underground Segments

```python
# Plan underground belt section
plan = placement_hints.get_underground_segment(
    entity_name="underground-belt",
    start=MapPosition(0, 0),
    end=MapPosition(5, 0),
    direction=Direction.EAST
)  # Raises ValueError if distance > max_distance (5 for belts)
```

---

### 2. Place Ghosts

Commit the plan by placing ghosts:

```python
# Option 1: Build plan (places ghosts + builds them)
result = await ghost_builder.build_plan(plan, strict=True)  # -> Dict

# Option 2: Manual ghost placement
belt_item = inventory.get_item("transport-belt")
for position, direction in plan.positions:
    belt_item.place_ghost(position, direction)
```

**Ghost Labels:** Each GhostPlan has a unique `label` for grouping related ghosts.

### 3. Build to Real Entities

Convert ghosts to real entities:

```python
# Build from reachable ghosts
ghost = reachable_view.get_ghosts()[0]
ghost.build()

# Or build multiple via ghost_builder
ghosts = reachable_view.get_ghosts("transport-belt")
result = await ghost_builder.build_ghosts(ghosts, count=10, strict=True)
```

### GhostPlan

Validated placement plan from `placement_hints` methods.

```python
ghostplan.entity_name  # str
ghostplan.positions  # List[Tuple[MapPosition, Optional[Direction]]]
ghostplan.label  # str
ghostplan.description  # str
ghostplan.valid  # bool
```

**Methods:**
- `.validate(validator: PlacementValidator) -> bool` - Re-validate all positions in the plan.

### Strict Mode

The `strict` parameter validates inventory before building:

```python
# strict=True: Fails fast if agent lacks required items
result = await ghost_builder.build_plan(plan, strict=True)
if "error" in result:
    print(f"Insufficient items: {result['error']}")

# strict=False (default): Builds what it can, reports failures
result = await ghost_builder.build_ghosts(ghosts, count=10)
print(f"Built {result['built_count']}, Failed {result['failed_count']}")
```

---


## Entity Reference

### Basic

**Entities:** `accumulator`, `big-electric-pole`, `crash-site-chest-1`, `crash-site-chest-2`, `iron-chest`, `medium-electric-pole`, `small-electric-pole`, `steel-chest`, `substation`, `wooden-chest`

### Belt, Rotatable

**Capabilities:**
- Belt
- Rotatable → `rotate`

**Entities:** `express-loader`, `express-transport-belt`, `express-underground-belt`, `fast-loader`, `fast-transport-belt`, `fast-underground-belt`, `loader`, `transport-belt`, `underground-belt`

### Belt, Rotatable180

**Capabilities:**
- Belt
- Rotatable180 → `rotate_180`

**Entities:** `express-splitter`, `fast-splitter`, `splitter`

### Burner, Crafter

**Capabilities:**
- Burner → `add_fuel, take_fuel`
- Crafter → `add_ingredients, take_products`

**Entities:** `steel-furnace`, `stone-furnace`

### Burner, Fluid, Rotatable

**Capabilities:**
- Burner → `add_fuel, take_fuel`
- Fluid → `get_fluid, get_pipe_connections`
- Rotatable → `rotate`

**Entities:** `boiler`

### Burner, Inserter, Rotatable

**Capabilities:**
- Burner → `add_fuel, take_fuel`
- Inserter → `get_drop_position, get_pickup_position, set_filter`
- Rotatable → `rotate`

**Entities:** `burner-inserter`

### Burner, Miner, Rotatable

**Capabilities:**
- Burner → `add_fuel, take_fuel`
- Miner → `get_output_position, get_resource_search_area`
- Rotatable → `rotate`

**Entities:** `burner-mining-drill`

### Crafter, Electric

**Capabilities:**
- Electric
- Crafter → `add_ingredients, take_products`

**Entities:** `electric-furnace`

### Crafter, Electric, Fluid, SetRecipe

**Capabilities:**
- Electric
- Crafter → `add_ingredients, take_products`
- SetRecipe → `set_recipe`
- Fluid → `get_fluid, get_pipe_connections`

**Entities:** `chemical-plant`, `oil-refinery`

### Crafter, Electric, SetRecipe

**Capabilities:**
- Electric
- Crafter → `add_ingredients, take_products`
- SetRecipe → `set_recipe`

**Entities:** `assembling-machine-1`, `assembling-machine-2`, `assembling-machine-3`, `centrifuge`, `rocket-silo`

### Electric

**Capabilities:**
- Electric

**Entities:** `lab`

### Electric, Fluid, Miner, Rotatable

**Capabilities:**
- Electric
- Miner → `get_output_position, get_resource_search_area`
- Fluid → `get_fluid, get_pipe_connections`
- Rotatable → `rotate`

**Entities:** `pumpjack`

### Electric, Fluid, Rotatable

**Capabilities:**
- Electric
- Fluid → `get_fluid, get_pipe_connections`
- Rotatable → `rotate`

**Entities:** `steam-engine`, `steam-turbine`

### Electric, Inserter, Rotatable

**Capabilities:**
- Electric
- Inserter → `get_drop_position, get_pickup_position, set_filter`
- Rotatable → `rotate`

**Entities:** `bulk-inserter`, `fast-inserter`, `filter-inserter`, `inserter`, `long-handed-inserter`, `stack-filter-inserter`, `stack-inserter`

### Electric, Miner, Rotatable

**Capabilities:**
- Electric
- Miner → `get_output_position, get_resource_search_area`
- Rotatable → `rotate`

**Entities:** `electric-mining-drill`


## Inspection

Call `entity.inspect()` to get current state.

### Base Fields (always present)

| Field | Type |
|-------|------|
| `name` | `str` |
| `position` | `Dict[str, float]` |
| `direction` | `Optional[Direction]` |
| `status` | `Optional[EntityStatus]` |
| `is_ghost` | `bool` |

### Capability Slots (when applicable)

| Slot | State Type | When Present |
|------|------------|-------------|
| `burner` | `BurnerState` | BurnerMixin |
| `electric` | `ElectricState` | ElectricMixin |
| `crafter` | `CrafterState` | CrafterMixin |
| `miner` | `MinerState` | MinerMixin |
| `inserter` | `InserterState` | InserterMixin |
| `fluid` | `FluidState` | FluidMixin |
| `belt` | `BeltState` | BeltMixin |
| `container` | `ContainerState` | Container |
| `lab` | `LabState` | Lab |
| `accumulator` | `AccumulatorState` | Accumulator |
| `electric_pole` | `ElectricPoleState` | ElectricPole |
| `generator` | `GeneratorState` | Generator |

---


## Response Types

These dataclasses are returned by action methods.

### GhostPlan

A validated placement plan returned by `placement_hints` methods.

```python
ghostplan.entity_name  # str
ghostplan.positions  # List[Tuple[MapPosition, Optional[Direction]]]
ghostplan.label  # str
ghostplan.description  # str
ghostplan.valid  # bool
```

**Methods:**
- `.validate(validator: PlacementValidator) -> bool` - Re-validate all positions in the plan.

### ConnectionPosition

A valid position for placing a target entity to connect to a source entity. Returned by `get_connection_positions()` with alignment information.

```python
connectionposition.position  # MapPosition
connectionposition.direction  # Optional[Direction]
connectionposition.perpendicular_offset  # float
```

### ResearchStatus

Comprehensive research status with progressive detail levels. Returned by `research.status()`. Provides minimal info if no research, queue info if queued, and full details if actively researching.

```python
researchstatus.queued  # bool
researchstatus.active  # bool
researchstatus.progress  # float
researchstatus.status  # str
researchstatus.tick  # int
researchstatus.current_research  # Optional[str]
researchstatus.queue_length  # int
researchstatus.queue  # List[QueuedTechnology]
researchstatus.units_completed  # Optional[int]
researchstatus.units_total  # Optional[int]
researchstatus.units_remaining  # Optional[int]
researchstatus.research_unit_count  # Optional[int]
researchstatus.research_unit_energy  # Optional[float]
researchstatus.research_unit_ingredients  # Optional[List[Dict[str, Any]]]
researchstatus.saved_progress  # Optional[float]
```

### QueuedTechnology

Basic information about a technology in the research queue. Used within `ResearchStatus.queue`.

```python
queuedtechnology.position  # int
queuedtechnology.name  # str
queuedtechnology.is_current  # bool
```

### ResearchQueueItem

Legacy research queue item. Use `QueuedTechnology` and `ResearchStatus` instead.

```python
researchqueueitem.technology  # str
researchqueueitem.progress  # float
researchqueueitem.level  # int
```

---


## Exception Types

These exceptions are raised by action methods when operations fail.

### Walking Exceptions

Raised by `walking.walk_to()`, `walking.walk_to_entity()`, and entity/resource `walk_to()` methods.

#### WalkingUnreachableError

Target is definitively unreachable after exhausting all approach options.

```python
class WalkingUnreachableError(WalkingError):
    failure_type: str  # e.g., 'blocked_path'
    candidates_tried: int  # Number of approach tiles tried
```

**When raised:**
- For entity-aware walking: all candidate tiles were tried, no path found
- For position-only walking: no path to position exists

**Resolution:** The agent may need to destroy/deconstruct obstacles to reach the target.

#### WalkingEntityNotFoundError

Entity reference is no longer valid.

```python
class WalkingEntityNotFoundError(WalkingError):
    entity_name: str  # Name of the entity
    position: MapPosition  # Expected position
```

**When raised:** The entity may have been destroyed, picked up, or moved.

**Resolution:** Refresh the entity reference and try again.

#### WalkingNoStandableTilesError

No standable tiles exist within reach of the target entity.

```python
class WalkingNoStandableTilesError(WalkingError):
    entity_name: str  # Name of the entity
```

**When raised:** The entity may be completely surrounded by obstacles.

**Resolution:** Clear obstacles around the entity or use a different approach path.

---


## Common Patterns

### Complete Mining Setup

```python
# 1. Find resources via remote SQL query
ore_deposits = remote_view.get_resources("SELECT * FROM resource_tile WHERE name = 'iron-ore' LIMIT 5")
target_resource = ore_deposits[0]

# 2. Walk to the resource - it automatically becomes REACHABLE
await target_resource.walk_to()  # Entity-aware pathfinding

# 3. Use it directly - no need to get it again!
items = await target_resource.mine(max_count=25)

# 4. Manual mining for bootstrap resources (if needed)
coal_resources = remote_view.get_resources("SELECT * FROM resource_tile WHERE name = 'coal' LIMIT 1")
if coal_resources:
    await coal_resources[0].walk_to()
    coal_items = await coal_resources[0].mine(max_count=10)

# 5. Place automated mining
drill_item = inventory.get_item("burner-mining-drill")
drill = drill_item.place(target_resource.position, Direction.SOUTH)

# 6. Fuel the drill
fuel = inventory.create_item_stacks("coal", 5)
drill.add_fuel(fuel)

# 7. Check drill status
state = drill.inspect()
print(f"Mining: {state.miner.mining_target}")
```

### Belt Line with Placement Planning

```python
# 1. Create validated belt line plan
start = reachable_view.get_entity("burner-mining-drill").position
end = start.offset((0, 10), Direction.SOUTH)

plan = placement_hints.get_placement_line("transport-belt", start=start, end=end)

# 2. Check if plan is valid
if not plan.valid:
    print("Invalid placement - obstacles detected")

# 3. Build the plan (places ghosts + builds to real)
result = await ghost_builder.build_plan(plan, strict=True)
print(f"Built {result.get('built_count', 0)} entities")
```

### Remote Query and Maintenance Loop

```python
# 1. Find all drills needing fuel
drills = remote_view.get_entities(
    "SELECT * FROM map_entity WHERE entity_name = 'burner-mining-drill'"
)

for remote_drill in drills:
    # 2. Walk to the drill - it automatically becomes REACHABLE
    await remote_drill.walk_to()  # Entity-aware pathfinding
    
    # 3. Use it directly - no need to get it again!
    state = remote_drill.inspect()
    if state.burner.fuel_inventory.get("coal", 0) < 5:
        fuel = inventory.create_item_stacks("coal", 10)
        remote_drill.add_fuel(fuel)

# 4. Stop walking when done
walking.stop()
```

### Crafting Recipes

**IMPORTANT: Handcraftability**
- Only recipes with `category="crafting"` can be handcrafted
- Recipes like `iron-plate`, `copper-plate`, `steel-plate`, `stone-brick` have `category="smelting"` and **require a furnace**
- Other categories like `chemistry`, `oil-processing` require specific machines

```python
# 1. Basic crafting (waits for completion)
initial_gears = inventory.check_total("iron-gear-wheel")
print("Initial gear count:", initial_gears)

# Craft 5 iron-gear-wheel (requires 2 iron-plate each)
items = await crafting.craft("iron-gear-wheel", count=5)
print("Crafted items:", len(items), "stacks")
for item in items:
    print("  -", item.count, "x", item.name)

final_gears = inventory.check_total("iron-gear-wheel")
print("Gears added:", final_gears - initial_gears)
```

```python
# 2. Crafting with ingredient verification
# Get initial counts
initial_cables = inventory.check_total("copper-cable")
initial_plates = inventory.check_total("copper-plate")
print("Initial:", initial_plates, "plates,", initial_cables, "cables")

# Craft 10 copper-cable (requires 1 copper-plate each)
items = await crafting.craft("copper-cable", count=10)

# Check results
final_cables = inventory.check_total("copper-cable")
final_plates = inventory.check_total("copper-plate")
print("Final:", final_plates, "plates,", final_cables, "cables")
print("Cables added:", final_cables - initial_cables)
```

```python
# 3. Multi-ingredient recipes
# Craft electronic-circuit (requires 1 iron-plate + 3 copper-cable)
initial_circuits = inventory.check_total("electronic-circuit")
items = await crafting.craft("electronic-circuit", count=5)

final_circuits = inventory.check_total("electronic-circuit")
print("Circuits added:", final_circuits - initial_circuits)
```

```python
# 4. Queue management (non-blocking)
# Enqueue recipe for crafting (returns immediately)
crafting.enqueue("iron-gear-wheel", count=10)

# Check crafting status
status = crafting.status()
print("Active:", status.get("active"))
print("Recipe:", status.get("recipe"))
print("Action ID:", status.get("action_id"))

# Cancel queued crafting
crafting.dequeue("iron-gear-wheel", count=5)  # Cancel 5
crafting.dequeue("iron-gear-wheel")  # Cancel all remaining
```

```python
# 5. Error handling for unavailable recipes
try:
    items = await crafting.craft("iron-plate", count=10)
except RuntimeError as e:
    if "not available" in str(e):
        print("Recipe not available - may require furnace or technology research")
    else:
        raise
```

**Common Handcraftable Recipes:**
- `iron-gear-wheel` - Craft from 2x iron-plate
- `copper-cable` - Craft from 1x copper-plate
- `electronic-circuit` - Craft from 1x iron-plate + 3x copper-cable
- `iron-stick` - Craft from 1x iron-plate
- `wooden-chest` - Craft from 2x wood

**NOT Handcraftable (require machines):**
- `iron-plate` - Requires furnace (category=smelting)
- `copper-plate` - Requires furnace (category=smelting)
- `steel-plate` - Requires furnace (category=smelting)
- `stone-brick` - Requires furnace (category=smelting)

