# PostgreSQL Observation Infrastructure Schema

## Overview

This directory contains the PostgreSQL schema for the three-tiered snapshot system that synchronizes Factorio game state into PostgreSQL, enabling parallel, asynchronous access for LLM agents.

## Architecture

### Multi-Instance Design

- **Single PostgreSQL container** with multiple databases: `factoryverse_0`, `factoryverse_1`, ..., `factoryverse_N`
- **Template database** (`factoryverse_template`) for initializing new instances
- **Independent data** per Factorio server instance
- **Shared volume access** to all CSV files from all instances

### Three-Tier Snapshot System

1. **Map Snapshots (Tier 1)** - One-time bulk load at game start
2. **Recurring Snapshots (Tier 2)** - Periodic CSV dumps via `file_fdw`
3. **On-Demand Snapshots (Tier 3)** - Real-time queries via Multicorn FDW

## Schema Files

### Core Setup
- `00_factory_verse.sql` - Template database creation with extensions
- `00_init_instances.sh` - Instance database creation script
- `05_finalize_instances.sh` - Post-creation instance configuration

### Tier 1: Map Snapshots
- `01_map_snapshot.sql` - Static map-level tables (entities, resources, etc.)

### Tier 2: Recurring Snapshots  
- `02_recurring_snapshot.sql` - Foreign tables for CSV-based recurring data

### Tier 3: On-Demand Snapshots
- `03_ondemand_snapshot.sql` - Instance config and placeholder for Multicorn FDW

### Data Loading
- `04_load_functions.sql` - Helper functions for bulk CSV loading

## Lua-to-PostgreSQL Schema Mapping

### Map Entities (Tier 1)

**Source:** `EntitiesSnapshot.lua` ComponentSchema

| Lua Field | PostgreSQL Column | Type | Notes |
|-----------|-------------------|------|-------|
| `unit_number` | `unit_number` | `BIGINT PRIMARY KEY` | Entity identifier |
| `name` | `name` | `TEXT NOT NULL` | Entity name |
| `type` | `type` | `TEXT NOT NULL` | Entity type |
| `force` | `force` | `TEXT` | Force/team |
| `direction` | `direction` | `SMALLINT` | Direction enum |
| `direction_name` | `direction_name` | `TEXT` | Human-readable direction |
| `orientation` | `orientation` | `REAL` | Orientation value |
| `orientation_name` | `orientation_name` | `TEXT` | Human-readable orientation |
| `electric_network_id` | `electric_network_id` | `BIGINT` | Electric network ID |
| `recipe` | `recipe` | `TEXT` | Current recipe (for crafters) |
| `position_x` | `position_x` | `REAL NOT NULL` | X coordinate |
| `position_y` | `position_y` | `REAL NOT NULL` | Y coordinate |
| `tile_width` | `tile_width` | `SMALLINT` | Tile width |
| `tile_height` | `tile_height` | `SMALLINT` | Tile height |
| `bounding_box_min_x` | `bounding_box_min_x` | `REAL` | Bounding box min X |
| `bounding_box_min_y` | `bounding_box_min_y` | `REAL` | Bounding box min Y |
| `bounding_box_max_x` | `bounding_box_max_x` | `REAL` | Bounding box max X |
| `bounding_box_max_y` | `bounding_box_max_y` | `REAL` | Bounding box max Y |
| `chunk_x` | `chunk_x` | `INTEGER NOT NULL` | Chunk X coordinate |
| `chunk_y` | `chunk_y` | `INTEGER NOT NULL` | Chunk Y coordinate |

### Inserter Components

**Source:** `EntitiesSnapshot.lua` ComponentSchema.inserter

| Lua Field | PostgreSQL Column | Type | Notes |
|-----------|-------------------|------|-------|
| `unit_number` | `unit_number` | `BIGINT PRIMARY KEY` | References map_entities |
| `pickup_target_unit` | `pickup_target_unit` | `BIGINT` | Target entity for pickup |
| `drop_target_unit` | `drop_target_unit` | `BIGINT` | Target entity for drop |
| `pickup_position_x` | `pickup_position_x` | `REAL` | Pickup position X |
| `pickup_position_y` | `pickup_position_y` | `REAL` | Pickup position Y |
| `drop_position_x` | `drop_position_x` | `REAL` | Drop position X |
| `drop_position_y` | `drop_position_y` | `REAL` | Drop position Y |
| `chunk_x` | `chunk_x` | `INTEGER NOT NULL` | Chunk X coordinate |
| `chunk_y` | `chunk_y` | `INTEGER NOT NULL` | Chunk Y coordinate |

### Belt Components

**Source:** `EntitiesSnapshot.lua` ComponentSchema.belt

| Lua Field | PostgreSQL Column | Type | Notes |
|-----------|-------------------|------|-------|
| `unit_number` | `unit_number` | `BIGINT PRIMARY KEY` | Belt entity ID |
| `name` | `name` | `TEXT NOT NULL` | Belt name |
| `type` | `type` | `TEXT NOT NULL` | Belt type |
| `direction` | `direction` | `SMALLINT` | Direction enum |
| `direction_name` | `direction_name` | `TEXT` | Human-readable direction |
| `belt_neighbours_json` | `belt_neighbours_json` | `JSONB` | Neighbor connections |
| `belt_to_ground_type` | `belt_to_ground_type` | `TEXT` | Underground belt type |
| `underground_neighbour_unit` | `underground_neighbour_unit` | `BIGINT` | Other end of underground |
| `position_x` | `position_x` | `REAL NOT NULL` | X coordinate |
| `position_y` | `position_y` | `REAL NOT NULL` | Y coordinate |
| `chunk_x` | `chunk_x` | `INTEGER NOT NULL` | Chunk X coordinate |
| `chunk_y` | `chunk_y` | `INTEGER NOT NULL` | Chunk Y coordinate |

### Pipe Components

**Source:** `EntitiesSnapshot.lua` ComponentSchema.pipe

| Lua Field | PostgreSQL Column | Type | Notes |
|-----------|-------------------|------|-------|
| `unit_number` | `unit_number` | `BIGINT PRIMARY KEY` | Pipe entity ID |
| `name` | `name` | `TEXT NOT NULL` | Pipe name |
| `type` | `type` | `TEXT NOT NULL` | Pipe type |
| `direction` | `direction` | `SMALLINT` | Direction enum |
| `direction_name` | `direction_name` | `TEXT` | Human-readable direction |
| `pipe_neighbours_json` | `pipe_neighbours_json` | `JSONB` | Neighbor connections |
| `position_x` | `position_x` | `REAL NOT NULL` | X coordinate |
| `position_y` | `position_y` | `REAL NOT NULL` | Y coordinate |
| `chunk_x` | `chunk_x` | `INTEGER NOT NULL` | Chunk X coordinate |
| `chunk_y` | `chunk_y` | `INTEGER NOT NULL` | Chunk Y coordinate |

### Resources

**Source:** `ResourceSnapshot.lua` ComponentSchema.resources

| Lua Field | PostgreSQL Column | Type | Notes |
|-----------|-------------------|------|-------|
| `x` | `x` | `INTEGER NOT NULL` | X coordinate |
| `y` | `y` | `INTEGER NOT NULL` | Y coordinate |
| `kind` | `kind` | `TEXT NOT NULL` | Resource type |
| `amount` | `amount` | `REAL NOT NULL` | Resource amount |

### Rocks

**Source:** `ResourceSnapshot.lua` ComponentSchema.rocks

| Lua Field | PostgreSQL Column | Type | Notes |
|-----------|-------------------|------|-------|
| `name` | `name` | `TEXT NOT NULL` | Rock name |
| `type` | `type` | `TEXT NOT NULL` | Rock type |
| `resource_json` | `resource_json` | `JSONB` | Mining results |
| `size` | `size` | `SMALLINT` | Rock size |
| `position_x` | `position_x` | `REAL NOT NULL` | X coordinate |
| `position_y` | `position_y` | `REAL NOT NULL` | Y coordinate |
| `chunk_x` | `chunk_x` | `INTEGER NOT NULL` | Chunk X coordinate |
| `chunk_y` | `chunk_y` | `INTEGER NOT NULL` | Chunk Y coordinate |

### Trees

**Source:** `ResourceSnapshot.lua` ComponentSchema.trees

| Lua Field | PostgreSQL Column | Type | Notes |
|-----------|-------------------|------|-------|
| `name` | `name` | `TEXT NOT NULL` | Tree name |
| `position_x` | `position_x` | `REAL NOT NULL` | X coordinate |
| `position_y` | `position_y` | `REAL NOT NULL` | Y coordinate |
| `bounding_box_min_x` | `bounding_box_min_x` | `REAL` | Bounding box min X |
| `bounding_box_min_y` | `bounding_box_min_y` | `REAL` | Bounding box min Y |
| `bounding_box_max_x` | `bounding_box_max_x` | `REAL` | Bounding box max X |
| `bounding_box_max_y` | `bounding_box_max_y` | `REAL` | Bounding box max Y |
| `chunk_x` | `chunk_x` | `INTEGER NOT NULL` | Chunk X coordinate |
| `chunk_y` | `chunk_y` | `INTEGER NOT NULL` | Chunk Y coordinate |

### Recurring Snapshots (Tier 2)

**Entity Status** - Source: `EntitiesSnapshot.lua` ComponentSchema.entity_status

| Lua Field | PostgreSQL Column | Type | Notes |
|-----------|-------------------|------|-------|
| `unit_number` | `unit_number` | `BIGINT NOT NULL` | Entity identifier |
| `status` | `status` | `INTEGER` | Status enum |
| `status_name` | `status_name` | `TEXT` | Human-readable status |
| `health` | `health` | `REAL` | Entity health |
| `tick` | `tick` | `BIGINT` | Game tick |

**Resource Yields** - Source: `ResourceSnapshot.lua` ComponentSchema.resource_yields

| Lua Field | PostgreSQL Column | Type | Notes |
|-----------|-------------------|------|-------|
| `x` | `x` | `INTEGER NOT NULL` | X coordinate |
| `y` | `y` | `INTEGER NOT NULL` | Y coordinate |
| `kind` | `kind` | `TEXT NOT NULL` | Resource type |
| `amount` | `amount` | `REAL NOT NULL` | Current amount |
| `tick` | `tick` | `BIGINT` | Game tick |

## Volume Structure

```
.fv/snapshots/
├── factorio_0/
│   ├── chunks/
│   │   ├── 0/0/
│   │   │   ├── entities-{tick}.csv
│   │   │   ├── entities_belts-{tick}.csv
│   │   │   ├── entities_pipes-{tick}.csv
│   │   │   ├── resources-{tick}.csv
│   │   │   ├── rocks-{tick}.csv
│   │   │   └── trees-{tick}.csv
│   │   └── ...
│   ├── recurring/
│   │   ├── entity_status-{tick}.csv
│   │   └── resource_yields-{tick}.csv
│   └── metadata/
│       └── {tick}/
│           ├── entities.json
│           └── resources.json
├── factorio_1/
│   └── ... (same structure)
└── ...
```

## Docker Mounts

```
Factorio_0: /opt/factorio/script-output → host:.fv/snapshots/factorio_0/
Factorio_1: /opt/factorio/script-output → host:.fv/snapshots/factorio_1/
...
Postgres: /var/lib/factoryverse/snapshots → host:.fv/snapshots/ (read-only, all instances)
```

## Usage Examples

### Loading Map Snapshot
```sql
-- Connect to specific instance database
\c factoryverse_0

-- Load map data from CSV files
SELECT * FROM load_map_snapshot_from_csv(0);
```

### Querying Recurring Data
```sql
-- Get current entity status
SELECT * FROM entity_status_current WHERE status != 0;

-- Get latest resource yields
SELECT * FROM recurring_resource_yields ORDER BY tick DESC LIMIT 100;
```

### Cross-Instance Queries
```sql
-- Query across all instances (if needed)
SELECT 'instance_0' as instance, COUNT(*) as entity_count 
FROM factoryverse_0.factoryverse.map_entities
UNION ALL
SELECT 'instance_1' as instance, COUNT(*) as entity_count 
FROM factoryverse_1.factoryverse.map_entities;
```

## Schema Drift Notes

### Known Mismatches
- None currently identified - schemas are aligned

### Future Considerations
- Spatial views and PostGIS features (future iteration)
- Multicorn FDW implementation for on-demand snapshots
- Action contracts for upsert operations
- Cross-instance aggregation views

## File Naming Convention

The Lua mod outputs CSV files with the following patterns:
- Map snapshots: `{type}-{tick}.csv` in `chunks/{chunk_x}/{chunk_y}/`
- Recurring snapshots: `{type}-{tick}.csv` in `recurring/`
- Metadata: `{type}.json` in `metadata/{tick}/`

PostgreSQL functions use `find` commands with glob patterns to locate and load these files.
