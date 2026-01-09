# FactoryVerse LLM Reference

> Auto-generated via introspection on 2026-01-10 02:23

You are an embodied agent in Factorio. You have a physical presence, inventory, and can walk, craft, mine, and interact with entities.

---


## Top-Level Accessors

These are available as global variables in your runtime.

### `crafting`

Crafting actions.

```python
await crafting.craft(recipe, count) - Craft items
crafting.get_craftable() - Get what you can craft
```

### `ghost_builder`

Ghost building orchestration.

```python
await ghost_builder.build_ghosts(ghosts, count=10) - Build multiple ghosts
await ghost_builder.build_ghost(ghost) - Build a single ghost
Automatically walks to each ghost and places the entity
```

### `inventory`

Inventory queries and operations.

```python
inventory.get_contents() - Get full inventory
inventory.get_item(name) - Get specific item stack
inventory.count(name) - Count of specific item
```

### `placement_hints`

Spatial reasoning engine for entity placement.

```python
placement_hints.get_placement_line(entity, start, end) - Plan a line of entities
placement_hints.get_connection_positions(source, target, type) - Find valid connection points
plan.valid - Check if GhostPlan is valid
plan.validate(placement_hints.validator) - Re-validate after map changes
```

### `reachable`

Unified reachable entity and resource queries.

```python
reachable.get_entity(name) - Get first entity by name
reachable.get_entities(name) - Get all entities by name
reachable.get_entities() - Get all reachable entities
reachable.get_ghosts() - Get ghost entities
reachable.get_resource(name) - Get specific resource
reachable.get_resources() - Get all reachable resources
```

### `remote_view`

Map-wide entity queries via DuckDB.

```python
remote_view.get_entities(sql) - Query entities by SQL
remote_view.get_ghosts(sql) - Query ghost entities
remote_view.query(sql) - Raw SQL queries
```

### `research`

Research actions.

```python
research.queue(technology) - Queue a technology
research.get_queue() - Get current research queue
```

### `walking`

Movement actions.

```python
await walking.walk_to(position) - Walk to a position
await walking.walk_to(position, timeout=30) - With custom timeout
```


## Getting Entities and Resources

### Reachable (Unified Query Interface)

The `reachable` accessor provides a unified interface for querying both entities and resources within interaction range.

#### Entities

```python
furnace = reachable.get_entity("stone-furnace")
drills = reachable.get_entities("burner-mining-drill")
ghosts = reachable.get_ghosts()  # Ghost entities also have REACHABLE view
```

#### Resources

```python
coal = reachable.get_resource("coal")
iron_ore = reachable.get_resource("iron-ore")
all_resources = reachable.get_resources()
```

### Mining Resources

Resources are mined using the object-based `mine()` method:

```python
# Get a resource
coal = reachable.get_resource("coal")

# Mine it (async)
items = await coal.mine(max_count=25)

# Resource patches work the same way
iron_patch = reachable.get_resources("iron-ore")
items = await iron_patch.mine(max_count=25)  # Mines first tile in patch
```

### Remote Entities (Read-Only)

Query entities anywhere on the map via SQL. **Read-only - cannot mutate.**

```python
drills = remote_view.get_entities("SELECT * FROM map_entity WHERE entity_name = 'electric-mining-drill'")
ghosts = remote_view.get_ghosts("SELECT * FROM ghost")
count = remote_view.count_entities("stone-furnace")
```

### View Distinction

| View | Source | Actions | Use Case |
|------|--------|---------|----------|
| REACHABLE | `reachable.*` | All actions available | Interact with nearby entities/resources |
| REMOTE | `remote_view.*` | Read-only (inspect only) | Query map-wide, then walk to interact |

Ghosts also have this distinction - ghosts from `reachable.get_ghosts()` can be built, ghosts from `remote_view.get_ghosts()` cannot (walk to them first).

---


## Items and Placement

### Getting Items from Inventory

```python
# Get a placeable item (returns PlaceableItem or Item)
furnace_item = inventory.get_item("stone-furnace")

# Get item stacks for fueling/crafting
coal_stacks = inventory.create_item_stacks("coal", count=5)

# Check how many you have
count = inventory.check_total("iron-plate")
```

### Item Types

| Type | What It Is | Key Methods |
|------|------------|-------------|
| `Item` | Non-placeable item | `.stack_size` |
| `PlaceableItem` | Can be placed as entity | `.place(position, direction)`, `.place_ghost(...)` |
| `ItemStack` | Quantity of items | Used for `add_fuel()`, `add_ingredients()` |

### Placing Entities

```python
# From inventory item (primary pattern)
furnace_item = inventory.get_item("stone-furnace")
furnace = furnace_item.place(MapPosition(10, 10), Direction.NORTH)

# Place as ghost (for planning)
furnace_item.place_ghost(MapPosition(10, 10), Direction.NORTH)
```

---


## Action Availability

Actions are filtered based on **view type** and **ghost status**.

### View-Based Filtering

Remote entities cannot be mutated - you must walk within range first.

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

### Ghost-Based Filtering

Ghosts are placeholders - they have no inventory or internal state.

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
)

# Check if plan is valid
if plan.valid:
    print(f"Plan has {len(plan.positions)} positions")
else:
    print("Invalid placement")

# Find connection points for pipes
positions = placement_hints.get_connection_positions(
    source_entity=refinery,  # Existing entity
    target_entity_name="pipe",
    connection_type=ConnectionType.FLUID_PIPE
)
```

### 2. Place Ghosts

Place ghosts for visual planning or incremental building:

```python
# From inventory item
belt_item = inventory.get_item("transport-belt")
belt_item.place_ghost(MapPosition(0, 0), Direction.EAST)

# Build plan as ghosts then build
await ghost_builder.build_plan(plan)
```

### 3. Build to Real Entities

Convert ghosts to real entities when ready:

```python
# Build a single ghost
ghost = reachable.get_ghosts()[0]
ghost.build()  # Converts to real entity

# Build multiple ghosts
await ghost_builder.build_ghosts(ghosts, count=10)
```

### Ghost Queries

```python
# Nearby ghosts (REACHABLE - can build)
ghosts = reachable.get_ghosts()
ghosts = reachable.get_ghosts("stone-furnace")

# Map-wide ghosts (REMOTE - walk to them first)
ghosts = remote_view.get_ghosts("SELECT * FROM ghost")
```

### GhostPlan Structure

```python
plan.positions   # List[MapPosition] - validated positions
plan.directions  # List[Direction] - directions for each position
plan.valid       # bool - True if all positions are valid
plan.validate(placement_hints.validator)  # Re-validate after map changes
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
| `direction` | `Optional[FactoryVerse.factory.factorio_types.Direction]` |
| `status` | `Optional[FactoryVerse.factory.factorio_types.EntityStatus]` |
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


## Direction

Cardinal directions (most common):
```python
Direction.NORTH
Direction.EAST
Direction.SOUTH
Direction.WEST
```

All 16 directions: `NORTH, NORTH_NORTH_EAST, NORTH_EAST, EAST_NORTH_EAST, EAST, EAST_SOUTH_EAST, SOUTH_EAST, SOUTH_SOUTH_EAST, SOUTH, SOUTH_SOUTH_WEST, SOUTH_WEST, WEST_SOUTH_WEST, WEST, WEST_NORTH_WEST, NORTH_WEST, NORTH_NORTH_WEST`

---


## Common Patterns

### Manual Mining

```python
# Get a resource
coal = reachable.get_resource("coal")

# Mine it (async, max 25 items per call)
items = await coal.mine(max_count=25)

# Or mine from a patch
iron_patch = reachable.get_resources("iron-ore")
items = await iron_patch.mine(max_count=25)
```

### Automated Mining Setup

```python
# Find a resource
coal = reachable.get_resource("coal")

# Place a drill on the resource
drill_item = inventory.get_item("burner-mining-drill")
drill = drill_item.place(coal.position, Direction.SOUTH)

# Fuel it
fuel = inventory.create_item_stacks("wood", 5)
drill.add_fuel(fuel)

# Check status
state = drill.inspect()
print(state.miner.mining_target)
print(state.burner.fuel_inventory)
```

### Smelting Chain

```python
# Place furnace next to drill
furnace_pos = drill.position.offset_by_entity(Direction.SOUTH)
furnace = inventory.get_item("stone-furnace").place(furnace_pos)

# Fuel and add ore
furnace.add_fuel(inventory.create_item_stacks("coal", 10))
furnace.add_ingredients(inventory.create_item_stacks("iron-ore", 50))

# Later, collect output
plates = furnace.take_products()
```

### Walking and Interacting

```python
# Find a remote entity
drills = remote_view.get_entities("SELECT * FROM map_entity WHERE entity_name = 'burner-mining-drill' LIMIT 1")

# Walk to it
await walking.walk_to(drills[0].position)

# Now get reachable version for full access
drill = reachable.get_entity("burner-mining-drill", drills[0].position)
drill.add_fuel(fuel)
```

