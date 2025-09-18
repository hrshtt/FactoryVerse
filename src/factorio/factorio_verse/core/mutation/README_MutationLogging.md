# Mutation Logging System

The mutation logging system tracks changes to the game state caused by agent actions and autonomous game processes. It produces structured JSONL logs that can be easily imported into SQL databases for analysis.

## Quick Start

Mutation logging is automatically configured in `control.lua`. By default, it uses the "minimal" profile which only logs action-based mutations:

```lua
-- In control.lua
local MutationConfig = require("core.MutationConfig")
MutationConfig.setup("minimal")  -- Only action-based logging
```

## Configuration Profiles

- **`minimal`** (default): Only action-based mutations, no tick-based logging
- **`full`**: Both action-based and autonomous tick-based mutations  
- **`debug`**: Full logging with debug output
- **`disabled`**: No mutation logging

```lua
-- Enable full logging including autonomous changes
MutationConfig.setup("full", 60) -- 60-tick interval for autonomous logging

-- Custom configuration
MutationConfig.setup({
    enabled = true,
    log_actions = true,
    log_tick_events = false,
    debug = true
})
```

## What Gets Logged

### Action-Based Mutations (Implemented)
- **Entity mutations**: Entity placement, removal, recipe changes
- **Resource mutations**: Resource depletion from mining
- **Inventory mutations**: Agent inventory changes from crafting, mining, placing

### Autonomous Mutations (Skeleton for Future)
- Resource depletion by mining drills/pumpjacks
- Entity status changes (working/idle/no_power)
- Chest inventory changes from inserters/belts

## Output Format

Logs are written as JSONL files in `script-output/factoryverse/mutations/` with separate directories for different mutation sources:

```
mutations/
├── action/                    # Player/agent action mutations
│   ├── entities.jsonl         # Entity placement/removal/changes
│   ├── resources.jsonl        # Resource depletion from mining
│   └── inventories.jsonl      # Inventory changes from crafting/mining
└── tick/                      # Autonomous game mutations (future)
    ├── entities.jsonl         # Entity status changes
    ├── resources.jsonl        # Automated mining depletion
    └── inventories.jsonl      # Inserter/belt inventory changes
```

### Example Log Entries:

**action/entities.jsonl:**
```jsonl
{"tick":12345,"surface":"nauvis","action":"entity.place","data":{"mutation_type":"created","unit_number":123,"entity_data":{...}}}
```

**action/resources.jsonl:**
```jsonl
{"tick":12346,"surface":"nauvis","action":"mine_resource","data":{"mutation_type":"depleted","resource_name":"iron-ore","position":{"x":15,"y":20},"delta":-5}}
```

**action/inventories.jsonl:**
```jsonl
{"tick":12347,"surface":"nauvis","action":"item.craft","data":{"mutation_type":"inventory_changed","owner_type":"agent","owner_id":1,"changes":{"iron-plate":-2,"iron-gear-wheel":1}}}
```

## Action Contract

Actions must return mutation hints in their result for logging to work:

```lua
-- In action implementation
local result = {
    -- ... normal result fields ...
    
    -- Mutation contract fields
    affected_unit_numbers = { entity.unit_number },
    affected_resources = {
        {
            name = "iron-ore",
            position = { x = 15, y = 20 },
            delta = -5  -- negative for depletion
        }
    },
    affected_inventories = {
        {
            owner_type = "agent",
            owner_id = agent_id,
            inventory_type = "character_main",
            changes = { ["iron-plate"] = -2, ["iron-gear-wheel"] = 1 }
        }
    }
}
```

## Integration with Snapshots

The mutation logger reuses existing snapshot serializers for consistency:
- `EntitiesSnapshot:_serialize_entity()` for entity data
- Same schema and flattening rules as snapshot system
- Compatible with existing SQL import pipelines

## Runtime Control

```lua
-- Enable/disable at runtime
MutationConfig.set_enabled(false)

-- Toggle debug mode
MutationConfig.set_debug(true)

-- Check current config
local config = MutationConfig.get_current_config()
```

## Files

- `core/MutationLogger.lua` - Main logging system
- `core/TickMutationLogger.lua` - Skeleton for autonomous logging
- `core/MutationConfig.lua` - Configuration management
- `core/mutation_schemas.md` - Detailed schema documentation

## Extending

To add mutation logging to new actions:

1. Return mutation contract fields in action result
2. The system automatically logs via the `Action:_post_run()` hook
3. No additional code needed in the action itself

For tick-based mutations, implement the skeleton methods in `TickMutationLogger.lua`.
