# FactoryVerse Schema Reference

> Auto-generated on 2026-08-29 02:09

This document describes the DuckDB database schema used for map-wide queries via `remote_view`.
The database is read-only from the LLM's perspective - data is synchronized from the game automatically.

---


## Query Constraints

### Read-Only Access

All queries must be **read-only** (`SELECT` or `WITH` for CTEs). The following SQL keywords are forbidden:

`INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE, GRANT, REVOKE, EXEC, EXECUTE, CALL, MERGE, UPSERT`

### Scoped Query Methods

> [!IMPORTANT]
> Methods that return **typed objects** (`get_entities`, `get_ghosts`, `get_resources`) require queries
> that return **full row data** - they cannot use aggregates (COUNT, SUM, GROUP BY, etc.) because
> entity/resource objects are constructed from each row.

| Method | Returns | Aggregate Allowed? |
|--------|---------|-------------------|
| `remote_view.query(sql)` | `List[Dict[str, Any]]` | Yes |
| `remote_view.get_entities(sql)` | `List[BaseEntity]` | No |
| `remote_view.get_entity(sql)` | `Optional[BaseEntity]` | No |
| `remote_view.get_ghosts(sql)` | `List[BaseEntity]` | No |
| `remote_view.get_resources(sql)` | `List[BaseResource]` (REMOTE view) | No |
| `remote_view.count_entities(name)` | `int` | (built-in) |
| `remote_view.count_ghosts(name)` | `int` | (built-in) |

### Examples: Correct vs Incorrect Usage

```python
# CORRECT: Full row data for entity construction
drills = remote_view.get_entities(
    "SELECT * FROM map_entity WHERE entity_name = 'burner-mining-drill'"
)

# INCORRECT: Aggregates break entity construction (missing position_x, position_y, etc.)
# This will fail or return empty list
remote_view.get_entities(
    "SELECT entity_name, COUNT(*) FROM map_entity GROUP BY entity_name"
)

# CORRECT: Use query() for aggregates, returns dicts
counts = remote_view.query(
    "SELECT entity_name, COUNT(*) as cnt FROM map_entity GROUP BY entity_name"
)

# CORRECT: Use built-in count methods
drill_count = remote_view.count_entities("burner-mining-drill")
```

---


## Return Types

### `BaseEntity` (from `get_entities`, `get_ghosts`)

Entities returned from remote queries have **REMOTE view** - they are read-only and cannot be mutated.

```python
class BaseEntity:
    name: str                    # Factorio entity name
    position: MapPosition        # (x, y) coordinates
    direction: Direction         # NORTH, EAST, SOUTH, WEST, etc.
    is_ghost: bool               # True if this is a ghost entity
    view: EntityView             # REMOTE (read-only) or REACHABLE (full access)

    # Available methods (read-only on REMOTE view):
    def inspect() -> EntityInspection  # Get current state
    async def walk_to() -> MapPosition  # Navigate to entity (entity-aware pathfinding)

    # Blocked on REMOTE view (must walk to entity first):
    # - add_fuel(), take_fuel()
    # - add_ingredients(), take_products()
    # - set_recipe(), rotate()
    # - pickup()
```

**IMPORTANT**: To interact with a remote entity, use `await entity.walk_to()`. After walking, the entity **automatically becomes REACHABLE** and you can use it directly - no need to get it again via `reachable.get_entity()`.

```python
# Preferred pattern:
drill = remote_view.get_entity("SELECT * FROM map_entity WHERE entity_name = 'burner-mining-drill' LIMIT 1")
await drill.walk_to()  # Automatically converts to REACHABLE
drill.add_fuel(inventory.create_item_stacks("coal", 5, number_of_stacks=1))
```

### `BaseResource` (from `get_resources`)

Resources from database queries have REMOTE view. They can be walked to and inspected, but cannot be mined directly.

```python
class BaseResource:
    name: str                    # Resource name (e.g., 'iron-ore')
    position: MapPosition        # (x, y) coordinates
    amount: int                  # Remaining amount (for ore tiles)
    view: EntityView            # REMOTE (from DB) or REACHABLE (from reachable)

    # Available methods (REMOTE view):
    def inspect() -> str         # Inspection string
    async def walk_to() -> MapPosition  # Navigate to resource

    # Blocked (REMOTE view):
    # - mine()  # Raises AttributeError - must walk to first
```

**IMPORTANT**: To mine a remote resource, use `await resource.walk_to()`. After walking, the resource **automatically becomes REACHABLE** and you can mine it directly - no need to get it again via `reachable.get_resource()`.

```python
# Preferred pattern:
iron_ore = remote_view.get_resources("SELECT * FROM resource_tile WHERE name = 'iron-ore' LIMIT 1")[0]
await iron_ore.walk_to()  # Automatically converts to REACHABLE
items = await iron_ore.mine(max_count=25)  # Use directly
```

### `ResourceOrePatch` (from `reachable_view.get_resources`)

Nearby ore tiles are consolidated into a REACHABLE patch. This is deliberately
different from one remote `BaseResource` tile: use `.total`, not `.amount`.

```python
class ResourceOrePatch:
    name: str
    position: MapPosition        # Average position of its nearby tiles
    total: int                   # Total remaining amount across the patch
    count: int                   # Number of tiles in the patch
    view: EntityView             # REACHABLE

    async def mine(max_count: int = 25) -> List[ItemStack]

patches = reachable_view.get_resources()
if patches:
    print(patches[0].total)
```

`reachable_view.get_resource(name)` returns one reachable `BaseResource`;
`reachable_view.get_resources()` returns consolidated `ResourceOrePatch`
objects.

### `Dict[str, Any]` (from `query`)

Raw query results as dictionaries with column names as keys.

```python
results = remote_view.query("SELECT entity_name, COUNT(*) as cnt FROM map_entity GROUP BY entity_name")
# results = [
#     {"entity_name": "burner-mining-drill", "cnt": 5},
#     {"entity_name": "stone-furnace", "cnt": 10},
#     ...
# ]
```

---


## Table Reference

### Core Tables

#### `map_entity`

Core entity table containing all placed entities on the map

| Column | Type | Description |
|--------|------|-------------|
| `entity_name` | `VARCHAR` | Factorio internal name (e.g., 'burner-mining-drill') |
| `position_x` | `DOUBLE` | X coordinate on the map |
| `position_y` | `DOUBLE` | Y coordinate on the map |
| `chunk_x` | `INTEGER` | Chunk X coordinate (for spatial queries) |
| `chunk_y` | `INTEGER` | Chunk Y coordinate (for spatial queries) |
| `direction` | `VARCHAR` | Entity direction (NORTH, EAST, SOUTH, WEST, etc.) |
| `bbox_min_x` | `DOUBLE` | Bounding box minimum X |
| `bbox_min_y` | `DOUBLE` | Bounding box minimum Y |
| `bbox_max_x` | `DOUBLE` | Bounding box maximum X |
| `bbox_max_y` | `DOUBLE` | Bounding box maximum Y |
| `electric_network_id` | `INTEGER` | Electric network this entity belonged to as of last entity write; fresh network membership lives in power_networks (engine network ids renumber on merge/split) |
| `force` | `VARCHAR` | Force name owning this entity (player, cell_N) |
| `agent_id` | `INTEGER` | ID of agent that placed this entity (if any) |
| `player_id` | `INTEGER` | ID of player that placed this entity (if any) |
| `label` | `VARCHAR` | Optional user-defined label |
| `placed_tick` | `INTEGER` | Game tick when entity was placed |
| `raw_data` | `VARCHAR` | JSON blob with full entity data |
| `tile_x` | `INTEGER` | X of the tile containing the entity centre (floor(position_x)); written on every upsert |
| `tile_y` | `INTEGER` | Y of the tile containing the entity centre (floor(position_y)); written on every upsert |

electric_network_id: as of last entity write; fresh network membership lives in power_networks (engine network ids renumber on merge/split).

**Example:**
```sql
SELECT * FROM map_entity WHERE entity_name = 'burner-mining-drill'
```

#### `ghost`

Ghost entities - planned placements that haven't been built yet

| Column | Type | Description |
|--------|------|-------------|
| `ghost_name` | `VARCHAR` | Entity name this ghost will become when built |
| `position_x` | `DOUBLE` | X coordinate on the map |
| `position_y` | `DOUBLE` | Y coordinate on the map |
| `chunk_x` | `INTEGER` | Chunk X coordinate |
| `chunk_y` | `INTEGER` | Chunk Y coordinate |
| `direction` | `VARCHAR` | Entity direction |
| `placed_tick` | `INTEGER` | Game tick when ghost was created |
| `placed_by` | `VARCHAR` | Who placed this ghost: 'agent:<id>' or 'player:<id>'; NULL when the op carried no builder |
| `label` | `VARCHAR` | Optional label |
| `raw_data` | `VARCHAR` | JSON blob with full ghost data |

**Example:**
```sql
SELECT * FROM ghost WHERE ghost_name = 'assembling-machine-1'
```

#### `resource_tile`

Ore deposits (iron-ore, copper-ore, coal, stone, uranium-ore)

| Column | Type | Description |
|--------|------|-------------|
| `name` | `VARCHAR` | Resource type (e.g., 'iron-ore', 'coal') |
| `position_x` | `DOUBLE` | X coordinate |
| `position_y` | `DOUBLE` | Y coordinate |
| `chunk_x` | `INTEGER` | Chunk X coordinate |
| `chunk_y` | `INTEGER` | Chunk Y coordinate |
| `amount` | `INTEGER` | Remaining ore amount in this tile |

**Example:**
```sql
SELECT * FROM resource_tile WHERE name = 'iron-ore' AND amount > 1000
```

#### `resource_entity`

Natural resources like trees, rocks, and other minable objects

| Column | Type | Description |
|--------|------|-------------|
| `name` | `VARCHAR` | Entity name (e.g., 'tree-01', 'rock-big') |
| `entity_type` | `VARCHAR` | Type category (tree, simple-entity for rocks, etc.) |
| `position_x` | `DOUBLE` | X coordinate |
| `position_y` | `DOUBLE` | Y coordinate |
| `chunk_x` | `INTEGER` | Chunk X coordinate |
| `chunk_y` | `INTEGER` | Chunk Y coordinate |
| `raw_data` | `VARCHAR` | JSON blob with full data |

**Note on entity_type for rocks:** The database stores 'simple-entity' for rocks (Factorio's internal type), but you can use 'rock' in SQL queries via `get_resources()` - it will be automatically converted. Both work: `WHERE entity_type = 'rock'` or `WHERE entity_type = 'simple-entity'`.

**Examples:**
```sql
SELECT * FROM resource_entity WHERE entity_type = 'tree'
-- Query rocks (use 'rock' - automatically converted to 'simple-entity' in database)
SELECT * FROM resource_entity WHERE entity_type = 'rock'
-- Or use 'simple-entity' directly (database storage format)
SELECT * FROM resource_entity WHERE entity_type = 'simple-entity'
```

#### `water_tile`

Water tiles on the map

| Column | Type | Description |
|--------|------|-------------|
| `position_x` | `DOUBLE` | X coordinate |
| `position_y` | `DOUBLE` | Y coordinate |
| `chunk_x` | `INTEGER` | Chunk X coordinate |
| `chunk_y` | `INTEGER` | Chunk Y coordinate |

**Example:**
```sql
SELECT * FROM water_tile WHERE chunk_x = 0 AND chunk_y = 0
```

#### `chunk_snapshot_meta`

Per-chunk snapshot freshness: the game tick at which each chunk's init files were last written

| Column | Type | Description |
|--------|------|-------------|
| `chunk_x` | `INTEGER` | Chunk X coordinate |
| `chunk_y` | `INTEGER` | Chunk Y coordinate |
| `tick` | `BIGINT` | Game tick when the chunk's init files were written |

Written by fv_snapshot as a kind=chunk_meta first line in every init JSONL. A max(tick) far behind the current game tick means the map snapshot is stale — treat query results as old data, not as the absence of things.

**Example:**
```sql
SELECT MIN(tick) AS oldest, MAX(tick) AS newest FROM chunk_snapshot_meta
```

#### `footprint_tiles`

Maps tiles to entities that occupy them. Enables O(1) 'what entity is at tile X?' queries.

| Column | Type | Description |
|--------|------|-------------|
| `tile_x` | `INTEGER` | Tile X coordinate (integer grid position) |
| `tile_y` | `INTEGER` | Tile Y coordinate (integer grid position) |
| `entity_name` | `VARCHAR` | Name of entity occupying this tile |
| `entity_position_x` | `DOUBLE` | Entity center X coordinate |
| `entity_position_y` | `DOUBLE` | Entity center Y coordinate |
| `is_ghost` | `BOOLEAN` | Whether this is a ghost entity |

**Tile-based queries**: This table enables fast integer-based spatial queries. Each entity occupies one or more tiles based on its footprint (e.g., 3x3 assembler = 9 tiles). The primary key enforces that only one entity can occupy each tile.

**Examples:**
```sql
-- Check if tile is occupied
SELECT * FROM footprint_tiles WHERE tile_x = 5 AND tile_y = 10
-- Find all tiles in an area
SELECT * FROM footprint_tiles WHERE tile_x BETWEEN 0 AND 10 AND tile_y BETWEEN 0 AND 10
-- Get entity at specific tile
SELECT entity_name, entity_position_x, entity_position_y FROM footprint_tiles WHERE tile_x = 5 AND tile_y = 5
```

### Component Tables

These tables contain entity-specific data and are joined via foreign keys to `map_entity`.

#### `inserter`

Inserter-specific data

| Column | Type | Description |
|--------|------|-------------|
| `entity_name` | `VARCHAR` | Entity name matching map_entity's composite key |
| `position_x` | `DOUBLE` | Entity X matching map_entity's composite key |
| `position_y` | `DOUBLE` | Entity Y matching map_entity's composite key |
| `direction` | `VARCHAR` | Inserter direction |
| `pickup_position_x` | `DOUBLE` | Pickup position X |
| `pickup_position_y` | `DOUBLE` | Pickup position Y |
| `drop_position_x` | `DOUBLE` | Drop position X |
| `drop_position_y` | `DOUBLE` | Drop position Y |

#### `transport_belt`

Transport belt data

| Column | Type | Description |
|--------|------|-------------|
| `entity_name` | `VARCHAR` | Entity name matching map_entity's composite key |
| `position_x` | `DOUBLE` | Entity X matching map_entity's composite key |
| `position_y` | `DOUBLE` | Entity Y matching map_entity's composite key |
| `direction` | `VARCHAR` | Belt direction |
| `belt_speed` | `DOUBLE` | Belt speed |

#### `mining_drill`

Mining drill data

| Column | Type | Description |
|--------|------|-------------|
| `entity_name` | `VARCHAR` | Entity name matching map_entity's composite key |
| `position_x` | `DOUBLE` | Entity X matching map_entity's composite key |
| `position_y` | `DOUBLE` | Entity Y matching map_entity's composite key |
| `direction` | `VARCHAR` | Drill direction |
| `mining_target` | `VARCHAR` | What resource this drill is mining |

#### `assembler`

Assembling machine data

| Column | Type | Description |
|--------|------|-------------|
| `entity_name` | `VARCHAR` | Entity name matching map_entity's composite key |
| `position_x` | `DOUBLE` | Entity X matching map_entity's composite key |
| `position_y` | `DOUBLE` | Entity Y matching map_entity's composite key |
| `recipe` | `VARCHAR` | Currently set recipe |
| `crafting_speed` | `DOUBLE` | Crafting speed multiplier |

### Agent Analytics Tables

Cumulative production statistics synchronized from the game. `statistics`, `crafted`, and `mined` are JSON objects stored as VARCHAR and can be inspected with DuckDB JSON functions.

#### `agent_production_statistics`

Per-agent surface-scoped force production statistics over time (machine flow)

| Column | Type | Description |
|--------|------|-------------|
| `agent_id` | `INTEGER` | Agent ID |
| `tick` | `INTEGER` | Game tick when statistics were recorded |
| `statistics` | `VARCHAR` | JSON: {input: produced item counts entering the flow, output: consumed item counts leaving the flow} |

Force input/output is the surface-scoped machine flow. Character crafting and mining are recorded separately in agent_manual_production_statistics; do not subtract them from input.

**Example:**
```sql
SELECT agent_id, tick, json(statistics) FROM agent_production_statistics WHERE agent_id = 1 ORDER BY tick DESC LIMIT 10
```

#### `agent_manual_production_statistics`

Per-agent manual production statistics (hand-crafted and hand-mined items only)

| Column | Type | Description |
|--------|------|-------------|
| `agent_id` | `INTEGER` | Agent ID |
| `tick` | `INTEGER` | Game tick when statistics were recorded |
| `crafted` | `VARCHAR` | JSON: Items hand-crafted by agent {item_name: count} |
| `mined` | `VARCHAR` | JSON: Items hand-mined by agent {item_name: count} |

Tracks ONLY items produced by the agent character directly (crafting queue, mining). Does NOT include items produced by machines/automation. Use with agent_production_statistics to report machine and character production as separate channels.

**Examples:**
```sql
-- Get latest manual production for agent 1
SELECT tick, json(crafted), json(mined) FROM agent_manual_production_statistics WHERE agent_id = 1 ORDER BY tick DESC LIMIT 1
-- Machine production is the force input count; manual counts are independent:
-- machine_produced[item] = statistics.input[item]
```

### State Tables

Live power and entity-status feeds. Cadence: `power_samples`/`power_networks` are sampled every **300 ticks (~5s)**; `entity_status` is a **full snapshot every 60 ticks (~1s)**. The engine `network_id` is **EPHEMERAL** — it renumbers on network merge/split, exactly like `unit_number`; reference a network by its **anchor pole** and an entity by **name + position**, never by a raw id. `map_entity.electric_network_id` is **as-of-write** (the id at the last entity snapshot); fresh network membership lives in `power_networks`.

#### `power_samples`

One row per ingested power-network sample window — heartbeat visibility for power_networks history (includes windows with zero live networks, so 'no rows at all' means the sampler never ran, not that there are no networks)

| Column | Type | Description |
|--------|------|-------------|
| `tick` | `INTEGER` | Game tick this sample window was taken (Power.lua nth_tick(300), MAINTENANCE phase only) |
| `network_count` | `INTEGER` | Number of live electric networks observed in this window (0 is a valid heartbeat value, not a missing-data marker) |

Written exclusively by analytics_ops.apply_power_sample, one row per ingested power_networks.jsonl line (including zero-network heartbeats). Distinguishes 'sampler running, zero networks right now' from 'sampler never ran' — the latter has no rows here at all.

**Example:**
```sql
SELECT * FROM power_samples ORDER BY tick DESC LIMIT 10
```

#### `power_networks`

History of per-electric-network power stats, sampled every 300 ticks (5s) during MAINTENANCE. Engine network_id is EPHEMERAL (renumbers on network split/merge) — anchor_pole is the durable reference for a given network across samples

| Column | Type | Description |
|--------|------|-------------|
| `tick` | `INTEGER` | Sample tick this row belongs to (see power_samples) |
| `network_id` | `INTEGER` | Engine electric_network_id AT THIS SAMPLE ONLY — renumbers arbitrarily on network split/merge; do not treat as a durable network identity across ticks |
| `anchor_pole_name` | `VARCHAR` | Entity name of this network's anchor pole (the pole with lexicographically smallest (x, y) in the network) — the durable per-network reference |
| `anchor_pole_x` | `DOUBLE` | Anchor pole X position |
| `anchor_pole_y` | `DOUBLE` | Anchor pole Y position |
| `pole_count` | `INTEGER` | Number of poles in this network |
| `member_count` | `INTEGER` | Number of tracked-force entities whose electric_network_id matched this network at sample time |
| `production_w` | `DOUBLE` | Total production, watts (summed across producer prototypes) |
| `consumption_w` | `DOUBLE` | Total consumption, watts (summed across consumer prototypes) |
| `storage_j` | `DOUBLE` | Best-effort stored energy, joules (sum of accumulator `energy` among this network's members; 0.0 when none) |
| `production_by_prototype` | `JSON` | JSON: {prototype_name: watts} production breakdown |
| `consumption_by_prototype` | `JSON` | JSON: {prototype_name: watts} consumption breakdown |

This is a HISTORY table (no primary key — every sample's rows are kept); 'current' state is the set of rows at max(tick). network_id is a per-sample handle only (ephemeral) — to track one physical network across samples, join on (anchor_pole_name, anchor_pole_x, anchor_pole_y) instead.

**Example:**
```sql
SELECT * FROM power_networks WHERE tick = (SELECT max(tick) FROM power_samples)
```

#### `entity_status`

Latest-wins snapshot of every tracked entity's Factorio status (e.g. no_power, working, low_power) from the most recently ingested full status dump

| Column | Type | Description |
|--------|------|-------------|
| `entity_name` | `VARCHAR` | Factorio internal entity name |
| `position_x` | `DOUBLE` | X coordinate |
| `position_y` | `DOUBLE` | Y coordinate |
| `status_name` | `VARCHAR` | Symbolic status name (defines.entity_status reverse lookup, e.g. 'no_power', 'working', 'low_power') |
| `tick` | `INTEGER` | Game tick of the status dump this row came from |

FULL REPLACE semantics: every ingested dump is a complete statement of current statuses, so ingestion deletes all rows then inserts the dump's rows (analytics_ops.apply_status_dump). Entities with no status (e.g. poles) are naturally absent from every dump — absence here does not mean 'destroyed', see map_entity for that. Freshness marker: sync_state key 'entity_status_last_tick' records the tick of the last applied dump (observable even for an all-meta, zero-entity dump).

**Example:**
```sql
SELECT * FROM entity_status WHERE status_name IN ('no_power', 'low_power')
```

> **Status caveats (live-learned):** poles carry no status (absent from every dump). A starved producer — including an electric-energy interface — still reads `working`; only consumers show `low_power`. Status is single-valued, so a logistics status (`full_output`, `item_ingredient_shortage`) can mask power distress. In the flow numbers a starved network reads `production_w ≈ consumption_w` (delivered energy), so undersupply is detected by the `low_power` status, NOT by a wattage gap.

---


## Common Query Patterns

### Find Entities by Name

```python
# All drills on the map
drills = remote_view.get_entities(
    "SELECT * FROM map_entity WHERE entity_name = 'burner-mining-drill'"
)
```

### Find Entities in a Region

```python
# Entities in chunk (0, 0)
entities = remote_view.get_entities(
    "SELECT * FROM map_entity WHERE chunk_x = 0 AND chunk_y = 0"
)

# Entities within a bounding box
entities = remote_view.get_entities('''
    SELECT * FROM map_entity
    WHERE position_x BETWEEN -50 AND 50
    AND position_y BETWEEN -50 AND 50
''')
```

### Find Ore Deposits

```python
# Rich iron ore tiles
iron_ore = remote_view.get_resources(
    "SELECT * FROM resource_tile WHERE name = 'iron-ore' AND amount > 1000"
)

# Closest ore to a position
closest = remote_view.get_resources('''
    SELECT *,
           sqrt(power(position_x - 0, 2) + power(position_y - 0, 2)) as distance
    FROM resource_tile
    WHERE name = 'coal'
    ORDER BY distance
    LIMIT 1
''')
```

### Count Entities

```python
# Using built-in method
drill_count = remote_view.count_entities("burner-mining-drill")
ghost_count = remote_view.count_ghosts("stone-furnace")

# Custom aggregates via query()
counts = remote_view.query('''
    SELECT entity_name, COUNT(*) as count
    FROM map_entity
    GROUP BY entity_name
    ORDER BY count DESC
''')
```

### Find Ghosts

```python
# All pending ghosts
ghosts = remote_view.get_ghosts("SELECT * FROM ghost")

# Ghosts of a specific type
furnace_ghosts = remote_view.get_ghosts(
    "SELECT * FROM ghost WHERE ghost_name = 'stone-furnace'"
)
```

### Join Component Tables

```python
# Get drills with their mining targets
results = remote_view.query('''
    SELECT m.entity_name, m.position_x, m.position_y, d.mining_target
    FROM map_entity m
    JOIN mining_drill d
      ON m.entity_name = d.entity_name
     AND m.position_x = d.position_x
     AND m.position_y = d.position_y
''')

# Get inserters with their pickup/drop positions
results = remote_view.query('''
    SELECT m.*, i.pickup_position_x, i.pickup_position_y,
           i.drop_position_x, i.drop_position_y
    FROM map_entity m
    JOIN inserter i
      ON m.entity_name = i.entity_name
     AND m.position_x = i.position_x
     AND m.position_y = i.position_y
''')
```

---


## Complete Workflow Example

```python
# 1. QUERY: Find resources via database
iron_deposits = remote_view.get_resources('''
    SELECT * FROM resource_tile
    WHERE name = 'iron-ore'
    ORDER BY amount DESC
    LIMIT 5
''')

# 2. NAVIGATE: Walk to the best deposit - it automatically becomes REACHABLE
target = iron_deposits[0]
await target.walk_to()  # Entity-aware pathfinding

# 3. MINE: Use it directly - no need to get it again!
items = await target.mine(max_count=50)

# 4. QUERY: Find existing infrastructure
drills = remote_view.get_entities('''
    SELECT * FROM map_entity
    WHERE entity_name = 'burner-mining-drill'
    AND chunk_x = 0 AND chunk_y = 0
''')

# 5. NAVIGATE & INTERACT: Fuel the drills
for drill in drills:
    await drill.walk_to()  # Automatically becomes REACHABLE
    drill.add_fuel(inventory.create_item_stacks("coal", 5, number_of_stacks=1))
```

