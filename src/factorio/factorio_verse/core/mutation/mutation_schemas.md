# Mutation Logger Schemas

This document defines the schema for mutation logs produced by the MutationLogger system.

## Output Format

Mutation logs are written as JSONL (JSON Lines) files with one JSON object per line. Each line represents a single mutation event.

### Directory Structure

```
script-output/factoryverse/mutations/
├── action/                    # Action-based mutations (player/agent actions)
│   ├── entities.jsonl         # Entity create/remove/modify from actions
│   ├── resources.jsonl        # Resource depletion from mining actions
│   └── inventories.jsonl      # Inventory changes from actions
└── tick/                      # Tick-based mutations (autonomous game processes)
    ├── entities.jsonl         # Entity status changes from game simulation
    ├── resources.jsonl        # Resource depletion from automated mining
    └── inventories.jsonl      # Inventory changes from inserters/belts
```

## Base Schema

Every mutation log entry has this base structure:

```json
{
  "tick": 12345,
  "surface": "nauvis", 
  "action": "entity.place",
  "type": "entity|resource|inventory",
  "data": { /* mutation-specific data */ }
}
```

### Base Fields

- `tick` (number): Game tick when the mutation occurred
- `surface` (string): Surface name where the mutation occurred
- `action` (string): Action name that caused the mutation, or "autonomous_*" for tick-based mutations
- `type` (string): Type of mutation - "entity", "resource", or "inventory"
- `data` (object): Mutation-specific data structure

## Entity Mutations

Entity mutations track changes to entities on the map.

### Schema

```json
{
  "tick": 12345,
  "surface": "nauvis",
  "action": "entity.place",
  "type": "entity",
  "data": {
    "mutation_type": "created|removed|modified|recipe_changed|status_changed",
    "unit_number": 123,
    "action": "entity.place",
    "entity_data": { /* Full entity data from EntitiesSnapshot serializer */ },
    "old_status": 1,  // Optional: for status_changed mutations
    "new_status": 2   // Optional: for status_changed mutations
  }
}
```

### Entity Data Structure

The `entity_data` field uses the same serialization format as `EntitiesSnapshot:_serialize_entity()`:

```json
{
  "unit_number": 123,
  "name": "assembling-machine-1",
  "type": "assembling-machine",
  "force": "player",
  "position": {"x": 10.5, "y": 5.5},
  "direction": 0,
  "direction_name": "north",
  "orientation": 0.0,
  "orientation_name": "north",
  "health": 350,
  "status": 1,
  "status_name": "working",
  "recipe": "iron-gear-wheel",
  "crafting_progress": 0.5
}
```

### Mutation Types

- `created`: Entity was placed on the map
- `removed`: Entity was removed from the map  
- `modified`: Entity properties changed (general catch-all)
- `recipe_changed`: Crafting machine recipe was changed
- `status_changed`: Entity status changed (working/idle/no_power/etc.)

## Resource Mutations

Resource mutations track depletion of resource tiles (ore patches, oil, etc.).

### Schema

```json
{
  "tick": 12345,
  "surface": "nauvis", 
  "action": "mine_resource",
  "type": "resource",
  "data": {
    "mutation_type": "depleted",
    "action": "mine_resource",
    "resource_name": "iron-ore",
    "position": {"x": 15.0, "y": 20.0},
    "delta": -5  // Negative for depletion, positive for addition
  }
}
```

### Fields

- `mutation_type`: Always "depleted" for now
- `resource_name`: Name of the resource type (iron-ore, crude-oil, etc.)
- `position`: Exact position of the resource tile
- `delta`: Amount changed (negative for depletion)

## Inventory Mutations

Inventory mutations track changes to agent and entity inventories.

### Schema

```json
{
  "tick": 12345,
  "surface": "nauvis",
  "action": "item.craft", 
  "type": "inventory",
  "data": {
    "mutation_type": "inventory_changed",
    "action": "item.craft",
    "owner_type": "agent|entity",
    "owner_id": 1,
    "inventory_type": "character_main|chest|assembler_input|assembler_output",
    "changes": {
      "iron-plate": -2,
      "iron-gear-wheel": 1
    }
  }
}
```

### Fields

- `owner_type`: Type of inventory owner
  - `agent`: Player character/agent inventory
  - `entity`: Entity inventory (chest, assembler, etc.)
- `owner_id`: 
  - For agents: agent_id number
  - For entities: unit_number
- `inventory_type`: Specific inventory type
  - `character_main`: Agent's main inventory
  - `chest`: Container/chest inventory  
  - `assembler_input`: Assembler input slots
  - `assembler_output`: Assembler output slots
- `changes`: Object mapping item names to quantity changes
  - Positive numbers: items added
  - Negative numbers: items removed

## SQL Integration

These JSONL logs are designed to be easily imported into SQL tables for analysis:

### Suggested Table Structure

```sql
-- Main mutations table
CREATE TABLE mutations (
    tick BIGINT,
    surface TEXT,
    action TEXT,
    mutation_type TEXT,
    data JSONB
);

-- Indexes for efficient querying
CREATE INDEX idx_mutations_tick ON mutations(tick);
CREATE INDEX idx_mutations_action ON mutations(action);
CREATE INDEX idx_mutations_type ON mutations(mutation_type);
CREATE INDEX idx_mutations_surface ON mutations(surface);
```

### Query Examples

```sql
-- Get all entity placements in the last 1000 ticks
SELECT * FROM mutations 
WHERE tick > (SELECT MAX(tick) - 1000 FROM mutations)
  AND data->>'mutation_type' = 'created';

-- Get resource depletion by type
SELECT 
    data->>'resource_name' as resource,
    SUM((data->>'delta')::numeric) as total_depleted
FROM mutations 
WHERE data->>'mutation_type' = 'depleted'
GROUP BY data->>'resource_name';

-- Get inventory changes for a specific agent
SELECT * FROM mutations
WHERE data->>'owner_type' = 'agent' 
  AND data->>'owner_id' = '1'
  AND data->>'mutation_type' = 'inventory_changed';
```

## Configuration

Mutation logging can be configured via the MutationLogger:

```lua
local MutationLogger = require("core.MutationLogger")
MutationLogger.configure({
    enabled = true,              -- Master switch
    log_actions = true,          -- Log action-based mutations  
    log_tick_events = false,     -- Log autonomous mutations (future)
    output_dir = "script-output/factoryverse/mutations",
    debug = false
})
```
