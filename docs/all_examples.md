# FactoryVerse Examples Reference
Total examples: 64
## `walking.walk_to`
**Context:** Walking to a known coordinate

```python
# Walk to a known coordinate
position = MapPosition(x=10.5, y=20.5)
final_pos = await walking.walk_to(position)
print(f"Arrived at {final_pos}")
```

---

## `walking.walk_to`
**Context:** Requiring exact position (e.g., for precise placement)

```python
# Walk with strict positioning (fail if exact position unreachable)
try:
    pos = await walking.walk_to(MapPosition(x=5, y=5), strict_goal=True)
except WalkingUnreachableError as e:
    print(f"Cannot reach exact position: {e}")
```

---

## `walking.stop`
**Context:** Interrupting navigation (e.g., code errors out and agent is stuck in walking state)

```python
# Stop walking and get current position
result = walking.stop()
if result.position:
    print(f"Stopped at {result.position}")
```

---

## `walking.current_position`
**Context:** Checking agent location before navigation

```python
# Check current position before planning movement
pos = walking.current_position
print(f"Agent is at ({pos.x}, {pos.y})")
```

---

## `crafting.craft`
**Context:** Crafting intermediate products for later use

```python
# Craft iron gear wheels
items = await crafting.craft("iron-gear-wheel", count=5)
print(f"Crafted {len(items)} stacks")
for stack in items:
    print(f"  {stack.name} x{stack.count}")
```

---

## `crafting.craft`
**Context:** Crafting items for placement

```python
# Craft placeable items
items = await crafting.craft("stone-furnace", count=3)
# Access the PlaceableItem from the stack via indexing
furnace_stack = items[0]
# Place via: furnace_stack[0].place(position, direction)
# Or via: furnace_stack.item.place(position, direction)
```

---

## `crafting.enqueue`
**Context:** Starting crafting while doing other tasks

```python
# Queue crafting in background
result = crafting.enqueue("electronic-circuit", count=10)
if result.get("success"):
    print("Crafting queued")
```

---

## `crafting.dequeue`
**Context:** Canceling crafting to free up queue

```python
# Cancel queued crafting
result = crafting.dequeue("electronic-circuit", count=5)
```

---

## `crafting.status`
**Context:** Monitoring crafting progress

```python
# Check crafting progress
status = crafting.status()
print(f"Queue size: {status.queue_size}")
print(f"Progress: {status.progress:.1%}")
for item in status.queue:
    print(f"  {item.recipe} x{item.count}")
```

---

## `research.enqueue`
**Context:** Starting a new technology research

```python
# Start researching automation
result = research.enqueue("automation")
if result.get("success"):
    print("Research started")
```

---

## `research.dequeue`
**Context:** Changing research priorities

```python
# Cancel current research
result = research.dequeue()
```

---

## `research.status`
**Context:** Monitoring research progress

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

---

## `research.get_queue`
**Context:** Planning research order

```python
# View research queue
queue = research.get_queue()
print(f"Current: {queue.get('current_research')}")
for item in queue.get('queue', []):
    print(f"  {item}")
```

---

## `inventory.check_total`
**Context:** Checking resource availability before operations

```python
# Check how many iron plates we have
count = inventory.check_total("iron-plate")
print(f"Iron plates: {count}")

# Check before crafting
if inventory.check_total("iron-plate") >= 10:
    await crafting.craft("iron-gear-wheel", count=5)
```

---

## `inventory.get_item`
**Context:** Getting item metadata (stack size, prototype info)

```python
# Get item with placement capability
item = inventory.get_item("stone-furnace")
if item:
    # PlaceableItem has stack_size and can be placed
    print(f"Stack size: {item.stack_size}")
```

---

## `inventory.create_item_stacks`
**Context:** Preparing items for distribution to multiple entities

```python
# Create stacks of 25 iron plates each
stacks = inventory.create_item_stacks("iron-plate", count=25)
for stack in stacks:
    print(f"Stack: {stack.name} x{stack.count}")
```

---

## `inventory.create_item_stacks`
**Context:** Creating standardized stack sizes

```python
# Create full stacks (max stack size)
full_stacks = inventory.create_item_stacks("iron-plate", count="full")

# Create half stacks
half_stacks = inventory.create_item_stacks("iron-plate", count="half")
```

---

## `inventory.create_item_stacks`
**Context:** Requiring exact amounts (fail if insufficient)

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

---

## `inventory.item_stacks`
**Context:** Reviewing full inventory

```python
# List all items in inventory
for stack in inventory.item_stacks:
    print(f"{stack.name}: {stack.count}")
```

---

## `reachable_view.get_entity`
**Context:** Finding a nearby entity to interact with

```python
# Find a specific furnace by name
furnace = reachable_view.get_entity("stone-furnace")
if furnace:
    print(f"Found furnace at {furnace.position}")
    # REACHABLE view allows inspection
    state = furnace.inspect()
```

---

## `reachable_view.get_entity`
**Context:** Verifying entity at known location

```python
# Find entity at specific position
drill = reachable_view.get_entity(
    "burner-mining-drill",
    position=MapPosition(x=10, y=10)
)
```

---

## `reachable_view.get_entity`
**Context:** Finding entity configured for specific production

```python
# Find entity with specific recipe
assembler = reachable_view.get_entity(
    "assembling-machine-1",
    options={"recipe": "iron-gear-wheel"}
)
```

---

## `reachable_view.get_entity`
**Context:** Finding ghosts to build or remove

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

---

## `reachable_view.get_entities`
**Context:** Finding all entities of a type to process

```python
# Get all nearby inserters
inserters = reachable_view.get_entities("inserter")
print(f"Found {len(inserters)} inserters")
for ins in inserters:
    print(f"  {ins.name} at {ins.position}")
```

---

## `reachable_view.get_entities`
**Context:** Surveying nearby area

```python
# Get all entities (no filter)
all_entities = reachable_view.get_entities()
# Group by type
from collections import Counter
counts = Counter(e.name for e in all_entities)
for name, count in counts.most_common(5):
    print(f"  {name}: {count}")
```

---

## `reachable_view.get_ghosts`
**Context:** Building all planned structures

```python
# Get all ghosts to build
ghosts = reachable_view.get_ghosts()
for ghost in ghosts:
    print(f"Ghost {ghost.name} at {ghost.position}")
    # Build each ghost
    await ghost.build()
```

---

## `reachable_view.get_ghosts`
**Context:** Building specific entity type ghosts

```python
# Get ghosts of specific type
belt_ghosts = reachable_view.get_ghosts("transport-belt")
print(f"Found {len(belt_ghosts)} belt ghosts to build")
```

---

## `reachable_view.get_resource`
**Context:** Finding mineable resources

```python
# Find iron ore to mine
ore = reachable_view.get_resource("iron-ore")
if ore:
    print(f"Iron ore at {ore.position}, amount: {ore.amount}")
    # Can mine directly
    items = await ore.mine(max_count=10)
```

---

## `reachable_view.get_resource`
**Context:** Verifying resource at known location

```python
# Find resource at specific position
coal = reachable_view.get_resource("coal", MapPosition(x=5, y=5))
```

---

## `reachable_view.get_resources`
**Context:** Surveying available resources

```python
# Get all ore patches
ores = reachable_view.get_resources(resource_type="ore")
for patch in ores:
    print(f"{patch.name}: {patch.total} total")
```

---

## `reachable_view.get_resources`
**Context:** Finding harvestable environment objects

```python
# Get trees and rocks
entities = reachable_view.get_resources(resource_type="entity")
trees = [r for r in entities if "tree" in r.name.lower()]
rocks = [r for r in entities if "rock" in r.name.lower()]
print(f"Trees: {len(trees)}, Rocks: {len(rocks)}")
```

---

## `remote_view.get_entities`
**Context:** Finding entities anywhere on the map

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

---

## `remote_view.get_entities`
**Context:** Querying entities in a rectangular area

```python
# Find entities in a specific area
entities = remote_view.get_entities('''
    SELECT * FROM map_entity
    WHERE position_x BETWEEN 0 AND 100
    AND position_y BETWEEN 0 AND 100
''')
```

---

## `remote_view.get_entities`
**Context:** Finding nearest entities to a point

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

---

## `remote_view.get_entity`
**Context:** Finding any entity of a type

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

---

## `remote_view.get_resources`
**Context:** Locating resource deposits

```python
# Find all iron ore on the map
iron = remote_view.get_resources('''
    SELECT * FROM resource_tile
    WHERE name = 'iron-ore'
''')
print(f"Found {len(iron)} iron ore tiles")
```

---

## `remote_view.get_ghosts`
**Context:** Finding blueprint ghosts to build

```python
# Find all planned but unbuilt structures
ghosts = remote_view.get_ghosts('''
    SELECT * FROM ghost
    WHERE ghost_name LIKE '%assembling%'
''')
print(f"Found {len(ghosts)} assembler ghosts")
```

---

## `remote_view.query`
**Context:** Custom aggregation queries

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

---

## `remote_view.query`
**Context:** Checking area availability

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

---

## `remote_view.count_entities`
**Context:** Quick entity counts without full query

```python
# Count all entities
total = remote_view.count_entities()
print(f"Total entities: {total}")

# Count specific type
drills = remote_view.count_entities("burner-mining-drill")
print(f"Mining drills: {drills}")
```

---

## `remote_view.is_tile_occupied`
**Context:** Checking tile availability before placement

```python
# Check before placing
if not remote_view.is_tile_occupied(5, 10):
    print("Tile is clear for placement")
else:
    print("Tile is occupied")
```

---

## `remote_view.get_entity_at_tile`
**Context:** Identifying entity at known tile

```python
# Find what's at a tile
entity = remote_view.get_entity_at_tile(5, 10)
if entity:
    print(f"Tile occupied by {entity.name}")
else:
    print("Tile is empty")
```

---

## `remote_view.get_entities_in_tile_area`
**Context:** Querying entities in tile-aligned area

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

---

## `remote_view.get_entities_at_anchor_tile`
**Context:** Finding entities by their center position

```python
# Find entities centered at tile
entities = remote_view.get_entities_at_anchor_tile(5, 10)
# Different from get_entity_at_tile which checks footprint overlap
```

---

## `placement_hints.get_placement_line`
**Context:** Planning belt/pipe lines

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
    await ghost_builder.commit(plan)
```

---

## `placement_hints.get_placement_line`
**Context:** Planning fluid transport lines

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

---

## `placement_hints.get_connection_positions`
**Context:** Placing furnace to receive drill output directly (most efficient)

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

---

## `placement_hints.get_connection_positions`
**Context:** Connecting fluid network to machines (FLUID_PIPE)

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

---

## `placement_hints.get_connection_positions`
**Context:** Extending power network (ELECTRIC_WIRE returns WireConnectionPosition)

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

---

## `placement_hints.get_inserter_placement_positions`
**Context:** Automating item transfer between entities

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

---

## `placement_hints.get_inserter_placement_positions`
**Context:** Using long-reach inserters for larger gaps

```python
# Find long-handed inserter positions (longer reach)
positions = placement_hints.get_inserter_placement_positions(
    source_entity=chest,
    target_entity=furnace,
    inserter_name="long-handed-inserter"
)
# Long-handed inserters can reach further, more options
```

---

## `placement_hints.get_pole_line`
**Context:** Running power line across distance

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
    await ghost_builder.commit(plan)
```

---

## `placement_hints.get_pole_line`
**Context:** Optimizing power line cost

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

---

## `placement_hints.get_pole_coverage_position`
**Context:** Minimizing poles for compact areas

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

---

## `placement_hints.get_pole_coverage_plan`
**Context:** Optimal pole placement for arbitrary layouts

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
    await ghost_builder.commit(plan)
```

---

## `placement_hints.get_underground_segment`
**Context:** Bypassing obstacles with underground transport

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

---

## `placement_hints.evaluate_pole_placement`
**Context:** Evaluating pole positions before commitment

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

---

## `placement_hints.validator`
**Context:** Single position validation

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

---

## `placement_hints.validator`
**Context:** Efficient batch validation

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

---

## `ghost_builder.build_ghosts`
**Context:** Building existing ghost entities

```python
# Get ghosts and build them
ghosts = reachable_view.get_ghosts()
result = await ghost_builder.build_ghosts(ghosts, count=10)

print(f"Built: {result['built_count']}")
print(f"Failed: {result['failed_count']}")
```

---

## `ghost_builder.build_ghosts`
**Context:** Building ghosts with inventory validation

```python
# Build with strict inventory validation
ghosts = remote_view.get_ghosts("SELECT * FROM ghost WHERE ghost_name = 'transport-belt'")
result = await ghost_builder.build_ghosts(ghosts, strict=True)

if "error" in result:
    print(f"Insufficient items: {result['error']}")
else:
    print(f"Built {result['built_count']} belts")
```

---

## `ghost_builder.build_ghost`
**Context:** Building a single specific ghost

```python
# Build a single ghost
ghost = reachable_view.get_ghosts("stone-furnace")[0]
success = await ghost_builder.build_ghost(ghost)
if success:
    print("Furnace ghost built!")
```

---

## `ghost_builder.build_plan`
**Context:** Committing a GhostPlan from placement_hints

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

---

## `ghost_builder.build_plan`
**Context:** Building plan with inventory check

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

---
