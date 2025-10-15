# FactoryVerse Database Schema

This directory contains PostgreSQL schema files for the FactoryVerse project, automatically generated from the Factorio mod's snapshot components.

## Files

- `init.sql` - Main schema initialization file that creates all tables, indexes, views, and functions

## Schema Overview

The schema is organized into two main categories:

### Entity Tables (from EntitiesSnapshot.lua)

1. **entities** - Main entity table with basic properties
2. **entities_crafting** - Crafting entities (assembling machines, furnaces)
3. **entities_burner** - Entities with fuel consumption
4. **entities_inventory** - Entities with item storage
5. **entities_fluids** - Entities with fluid storage
6. **entities_inserter** - Inserter-specific data
7. **entities_belts** - Transport belt data

### Resource Tables (from ResourceSnapshot.lua)

1. **resource_tiles** - Resource deposits and water tiles
2. **resource_rocks** - Rock entities

## Key Features

- **Spatial Support**: Uses PostGIS for spatial queries and indexing
- **JSONB Storage**: Complex data structures stored as JSONB for flexibility
- **Performance Indexes**: Optimized indexes for common query patterns
- **Automatic Timestamps**: Created/updated timestamps with triggers
- **Referential Integrity**: Foreign key constraints between related tables

## Usage

The schema is automatically initialized when using the `launch-postgres.sh` script:

```bash
# Start PostgreSQL with schema initialization
./scripts/launch-postgres.sh

# Or reset and recreate with fresh schema
./scripts/launch-postgres.sh --reset
```

## Table Relationships

```
entities (unit_number) 
├── entities_crafting (unit_number)
├── entities_burner (unit_number)
├── entities_inventory (unit_number)
├── entities_fluids (unit_number)
├── entities_inserter (unit_number)
└── entities_belts (unit_number)

resource_tiles (independent)
resource_rocks (independent)
```

## Spatial Queries

The schema includes spatial indexes and views for efficient position-based queries:

```sql
-- Find entities within a radius
SELECT * FROM entities_with_position 
WHERE ST_DWithin(position, ST_Point(100, 200), 50);

-- Find resource tiles in a specific area
SELECT * FROM resource_tiles_with_position 
WHERE ST_Contains(ST_MakeEnvelope(0, 0, 100, 100), position);
```

## JSONB Queries

Complex data stored as JSONB can be queried efficiently:

```sql
-- Find entities with specific inventory contents
SELECT * FROM entities_inventory 
WHERE inventories->'fuel' ? 'coal';

-- Find belts with items on specific transport lines
SELECT * FROM entities_belts 
WHERE item_lines @> '[{"index": 1, "items": {"iron-ore": 5}}]';
```
