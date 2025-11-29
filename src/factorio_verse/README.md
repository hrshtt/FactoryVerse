# Factorio Verse Mod

A Factorio 2.0 mod that provides programmatic agent control, game state tracking, and async action execution for AI research and automation.

## Overview

Factorio Verse transforms Factorio into a controllable environment for AI agents by providing:

- **Agent System**: Programmatically controlled character entities with persistent state
- **Action Framework**: Async and sync actions for mining, crafting, walking, placement, and entity operations
- **Game State Tracking**: Real-time tracking of agents, entities, resources, power, research, and map state
- **Remote Interfaces**: RCON-compatible remote interfaces for external control
- **UDP Notifications**: Async action and event completion notifications via UDP

## Architecture

### Core Components

```
factorio_verse/
├── control.lua              # Main entry point, event aggregation
├── Agent.lua                # Agent class with action methods
├── game_state/              # Game state tracking modules
│   ├── Agent.lua            # Agent state processing
│   ├── Entities.lua         # Entity status tracking
│   ├── Map.lua              # Map/chunk management
│   ├── Power.lua            # Power network tracking
│   ├── Research.lua         # Research progress tracking
│   └── Resource.lua         # Resource tracking
├── agent_actions/           # Action implementations
│   ├── walking.lua          # Pathfinding and movement
│   ├── mining.lua           # Resource mining
│   ├── crafting.lua         # Recipe crafting
│   ├── placement.lua        # Entity placement
│   └── entity_ops.lua       # Entity operations (recipes, filters, etc.)
└── utils/                   # Utilities
    ├── ParamSpec.lua        # Parameter validation
    ├── snapshot.lua         # State snapshots
    └── utils.lua            # Helper functions
```

## Agent System

### Creating Agents

Agents are programmatically controlled character entities. Each agent has:

- **Unique ID**: Numeric identifier (e.g., `agent_1`, `agent_2`)
- **Character Entity**: A Factorio character entity with inventory
- **Force**: Separate force for recipes/technologies
- **State Tracking**: Walking, mining, crafting, placement states
- **Remote Interface**: Per-agent remote interface (`agent_1`, `agent_2`, etc.)

### Agent Actions

All actions are exposed via per-agent remote interfaces:

```lua
-- Example: Control agent_1
remote.call("agent_1", "walk_to", {x = 10, y = 20})
remote.call("agent_1", "mine_resource", "iron-ore", 50)
remote.call("agent_1", "craft_enqueue", {{name = "iron-gear-wheel", count = 10}})
```

## Actions

### Async Actions

Async actions return immediately with `queued=true` and send completion notifications via UDP:

#### Walking
- `walk_to(goal, adjust_to_non_colliding, options)` - Move agent to position
- `stop_walking()` - Cancel current walk

#### Mining
- `mine_resource(resource_name, max_count)` - Mine resources (ores, trees, rocks)
  - For trees/rocks: `max_count` is ignored (mines until depleted)
  - Returns: `{success, queued, action_id, tick, estimated_ticks, products}`
- `stop_mining()` - Cancel current mining

#### Crafting
- `craft_enqueue(item_stack)` - Queue crafting recipes
  - `item_stack`: Array of `{name: string, count: number|string}`
  - Supports `count` values: number, `"MAX"`, `"FULL-STACK"`, `"HALF-STACK"`
  - Returns: Array of results with `estimated_ticks` per recipe
- `craft_dequeue(recipe_name, count)` - Cancel queued recipes

### Sync Actions

Sync actions complete immediately and return results:

#### Entity Operations
- `set_entity_recipe(entity_name, position, recipe_name)` - Set recipe on entity
- `set_entity_filter(entity_name, position, inventory_type, filter_index, filter_item)` - Set filter
- `set_inventory_limit(entity_name, position, inventory_type, limit)` - Set inventory limit
- `get_inventory_item(entity_name, position, inventory_type, item_name, count)` - Get items
- `set_inventory_item(entity_name, position, inventory_type, item_name, count)` - Set items

#### Placement
- `place_entity(entity_name, position, options)` - Place entity

#### Utility
- `teleport(position)` - Teleport agent
- `inspect(attach_inventory, attach_reachable_entities)` - Get agent state

## Time Estimation

Both mining and crafting actions provide time estimates:

### Mining Time
- Calculated from `entity.prototype.mineable_properties.mining_time`
- Formula: `(mining_time_seconds / character_mining_speed) * 60`
- Returns `estimated_ticks` in queued message
- Returns `actual_ticks` in completion message
- Includes `products` array from `mineable_properties`

### Crafting Time
- Calculated from `recipe.energy` (base crafting time)
- Formula: `(recipe_energy / effective_crafting_speed) * count * 60`
- Returns `estimated_ticks` per recipe in queued message
- Returns `actual_ticks` in completion message

## Game State Tracking

The mod tracks game state across multiple domains:

### Agent State (`game_state/Agent.lua`)
- Processes agent state machines (walking, mining, crafting, placement)
- Sends UDP completion messages
- Tracks agent activity across ticks

### Entity State (`game_state/Entities.lua`)
- Tracks entity status (working, waiting, etc.)
- Monitors charted chunks
- Updates entity state periodically

### Resource State (`game_state/Resource.lua`)
- Tracks resource patches
- Monitors resource depletion

### Map State (`game_state/Map.lua`)
- Manages chunk charting
- Tracks explored areas

### Power State (`game_state/Power.lua`)
- Tracks power networks
- Monitors power production/consumption

### Research State (`game_state/Research.lua`)
- Tracks research progress
- Monitors technology unlocks

## Remote Interfaces

### Per-Agent Interfaces

Each agent gets its own remote interface: `agent_1`, `agent_2`, etc.

```lua
-- All agent actions are available via remote interface
remote.call("agent_1", "walk_to", {x = 10, y = 20})
remote.call("agent_1", "mine_resource", "iron-ore", 50)
```

### Global Interfaces

- `agent` - Agent management (create, destroy, etc.)
- `entities` - Entity operations
- `map` - Map operations
- `power` - Power network operations
- `research` - Research operations
- `resource` - Resource operations

## UDP Notifications

Async actions send completion notifications via UDP (port 34202):

```json
{
  "action_id": "mine_resource_1234_1",
  "agent_id": 1,
  "action_type": "mine_resource",
  "category": "mining",
  "rcon_tick": 1234,
  "completion_tick": 1414,
  "success": true,
  "result": {
    "resource_name": "iron-ore",
    "item_name": "iron-ore",
    "count": 10,
    "actual_ticks": 180
  }
}
```

## Parameter Validation

Actions use `ParamSpec` for parameter validation:

- Type checking (string, number, table, etc.)
- Required vs optional parameters
- Default values
- Special count values: `"MAX"`, `"FULL-STACK"`, `"HALF-STACK"`

## State Persistence

Agent state persists across game saves/loads via Factorio's `storage` system:

- Agent instances stored in `storage.agents[agent_id]`
- Metatable registration for save/load
- State machines persist across sessions

## Event System

The mod uses an aggregation pattern for events:

- All modules register event handlers
- `control.lua` aggregates handlers into chains
- Events registered once with aggregated handlers
- Supports `on_tick`, `nth_tick`, and custom events

## Usage Examples

### Create and Control an Agent

```lua
-- Create agent via global interface
local agent = remote.call("agent", "create", 1, {r=1, g=0, b=0})

-- Control agent via per-agent interface
remote.call("agent_1", "walk_to", {x = 10, y = 20})
remote.call("agent_1", "mine_resource", "iron-ore", 50)
remote.call("agent_1", "craft_enqueue", {
  {name = "iron-gear-wheel", count = 10},
  {name = "copper-cable", count = 20}
})
```

### Inspect Agent State

```lua
local state = remote.call("agent_1", "inspect", true, true)
-- Returns: {agent_id, tick, position, inventory, reachable_resources, reachable_entities}
```

### Entity Operations

```lua
-- Set recipe on assembling machine
remote.call("agent_1", "set_entity_recipe", "assembling-machine-1", {x=10, y=20}, "iron-gear-wheel")

-- Get items from chest
remote.call("agent_1", "get_inventory_item", "iron-chest", {x=10, y=20}, "chest", "iron-ore", 50)
```

## Dependencies

- Factorio 2.0+
- Base mod (included)

## Version

Current version: 1.0.0

## License

See main repository LICENSE file.
