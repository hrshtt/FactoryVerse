# FV Embodied Agent

Independent Factorio mod that provides embodied agent control by replicating human player affordances - the actions a human can perform via the game GUI (walk, place, craft, mine). The mod exposes 30+ methods through Factorio's remote interface system for programmatic control, enabling any framework to build agent systems on top of it.

**Design Philosophy**: This mod is designed to be **fully independent** and **framework-agnostic**. It has no hard dependencies beyond Factorio base (`base >= 2.0`). Any coupling with other mods is intentionally limited to:
- **Remote interfaces** - Other mods can query agent state via `remote.call()`
- **Custom events** - Other mods can listen to agent actions via Factorio's event system

This design allows the mod to be used by anyone to build any kind of agent framework, not just FactoryVerse's specific approach (Snapshot mod + Hints-Based + Stateful API). The mod provides the low-level primitives; higher-level abstractions can be built in any language or paradigm.

## Overview

| Field | Value |
|-------|-------|
| Mod Name | `fv_embodied_agent` |
| Version | 0.1.3 |
| Factorio Version | 2.0+ |
| Dependencies | base >= 2.0 (no other mods required) |
| Independence | Fully independent; can be used standalone or with any other mods |

**Key Insight**: Human players have full map visibility and can perform actions through the GUI (walk, place, craft, mine). This mod replicates both capabilities for AI agents, exposing 30+ methods via Factorio's remote interface system.

## Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                         control.lua                                │
│  - Event dispatcher (aggregates handlers from all modules)         │
│  - Remote interface registration                                   │
│  - Lifecycle callbacks (on_init, on_load, on_configuration_changed)│
└────────────────────────────────────────────────────────────────────┘
                                  │
            ┌─────────────────────┼─────────────────────┐
            ▼                     ▼                     ▼
┌───────────────────┐   ┌─────────────────┐   ┌──────────────────────┐
│   game_state/     │   │    Agent.lua    │   │   agent_actions/     │
│                   │   │                 │   │                      │
│ - Agents.lua      │   │ - Agent class   │   │ - walking.lua        │
│ - Notifications   │   │ - State machine │   │ - mining.lua         │
│ - EntityInterface │   │ - Message queue │   │ - crafting.lua       │
└───────────────────┘   │ - Lifecycle     │   │ - placement.lua      │
                        └─────────────────┘   │ - entity_ops.lua     │
                                              │ - reachability.lua   │
                                              │ - researching.lua    │
                                              │ - charting.lua       │
                                              │ - RemoteInterface.lua│
                                              └──────────────────────┘
```

## Remote Interfaces

The mod registers multiple remote interfaces for different purposes:

### `agent` - Agent Lifecycle Management

Administrative interface for creating, destroying, and managing agents.

| Method | Parameters | Description |
|--------|------------|-------------|
| `create_agent` | `udp_port?`, `set_unique_forces?`, `default_common_force?`, `initial_inventory?` | Create a new agent |
| `destroy_agents` | `agent_refs`, `remove_forces?` | Destroy agents (pass `0` to destroy all) |
| `list_agents` | - | List all agents with details |
| `list_agent_forces` | - | Get agent ID to force name mapping |
| `update_agent_friends` | `agent_id`, `force_names` | Set friendly forces for an agent |
| `update_agent_enemies` | `agent_id`, `force_names` | Set enemy forces for an agent |
| `reset_research` | `force_name` | Reset all research for a force |
| `inspect_research` | `force_name` | Get research status for a force |
| `add_items` | `agent_id`, `items` | Add items to agent inventory |
| `clear_inventory` | `agent_id` | Clear agent inventory |

### `agent_N` - Per-Agent Control (e.g., `agent_1`, `agent_2`)

Each agent gets its own remote interface with 32 methods for direct control.

#### Async Methods (return `action_id`, completion via UDP)

| Method | Parameters | Description |
|--------|------------|-------------|
| `walk_to` | `goal`, `strict_goal?`, `options?` | Navigate to position using pathfinding |
| `mine_resource` | `resource_name`, `max_count?` | Mine a resource within reach |
| `craft_enqueue` | `recipe_name`, `count?` | Queue hand-crafting |

#### Sync Methods (complete immediately)

| Method | Parameters | Description |
|--------|------------|-------------|
| `stop_walking` | - | Cancel current walk action |
| `stop_mining` | - | Cancel current mining action |
| `craft_dequeue` | `recipe_name`, `count?` | Cancel queued crafting |
| `place_entity` | `entity_name`, `position`, `direction?`, `ghost?`, `label?` | Place entity from inventory |
| `pickup_entity` | `entity_name`, `position?` | Pick up entity into inventory |
| `remove_ghost` | `entity_name`, `position?` | Remove a ghost entity |
| `rotate_entity` | `entity_name`, `position?`, `direction?`, `is_ghost?` | Rotate an entity |
| `set_entity_recipe` | `entity_name`, `position?`, `recipe_name?` | Set machine recipe |
| `set_entity_filter` | `entity_name`, `position?`, `inventory_type`, `filter_index?`, `filter_item?` | Set inventory filter |
| `set_inventory_limit` | `entity_name`, `position?`, `inventory_type`, `limit?` | Set container slot limit |
| `take_inventory_item` | `entity_name`, `position?`, `inventory_type`, `item_name`, `count?` | Take items from entity |
| `put_inventory_item` | `entity_name`, `position?`, `inventory_type`, `item_name`, `count` | Put items into entity |
| `teleport` | `position` | Instantly move agent (debug) |
| `reset` | `reset_force?` | Reset agent (two-call pattern) |
| `enqueue_research` | `technology_name` | Start researching a technology |
| `cancel_current_research` | - | Cancel active research |

#### Query Methods (read-only, no side effects)

| Method | Parameters | Description |
|--------|------------|-------------|
| `inspect` | `attach_state?` | Get agent position and activity state |
| `get_position` | - | Get current position |
| `get_inventory_items` | - | Get inventory contents |
| `get_crafting_queue` | - | Get crafting queue details |
| `get_reachable` | `attach_ghosts?` | Get entities/resources within reach |
| `inspect_entity` | `entity_name`, `position` | Get detailed entity state |
| `get_recipes` | `category?` | Get available recipes |
| `get_technologies` | `only_available?` | Get technology tree |
| `get_research_queue` | - | Get research queue |
| `get_research_status` | - | Get detailed research progress |
| `get_chunks_in_view` | - | Get charted chunks |
| `get_production_statistics` | - | Get force production stats |
| `inspect_state` | - | Get raw agent state (debug) |

### `admin` - Testing API (conditional)

Only registered when `fv-embodied-agent-enable-admin-api` setting is enabled.

| Method | Parameters | Description |
|--------|------------|-------------|
| `add_items` | `agent_id`, `items` | Add items to agent inventory |
| `clear_inventory` | `agent_id` | Clear agent inventory |
| `unlock_technology` | `agent_id`, `tech_name` | Unlock a technology |
| `set_crafting_speed` | `agent_id`, `multiplier` | Set crafting speed multiplier |
| `get_agent_state` | `agent_id` | Get comprehensive agent state |

### `factorio_verse_docs` - Schema Export

| Method | Parameters | Description |
|--------|------------|-------------|
| `get_all_methods` | - | Get paramspec for all agent methods |
| `get_method_schema` | `method_name` | Get paramspec for specific method |

### `custom_events` - Event IDs

| Method | Parameters | Description |
|--------|------------|-------------|
| `get_custom_events` | - | Get custom event IDs for inter-mod communication |

**Inter-Mod Coupling**: This interface, along with the remote interfaces above, are the **only** coupling points between `fv_embodied_agent` and other mods. Other mods can:
- Query agent state via remote interfaces (e.g., `agent.list_agent_forces()`)
- Listen to agent actions via custom events (e.g., `on_agent_entity_built`, `on_agent_resource_mined`)

This design ensures the mod remains independent and can be integrated with any framework or other mods without hard dependencies.

## Usage via RCON

```lua
-- Create an agent
/c rcon.print(helpers.table_to_json(remote.call("agent", "create_agent", {udp_port=34202})))
-- Returns: {"agent_id":1,"force_name":"player","interface_name":"agent_1","udp_port":34202}

-- Walk to position
/c rcon.print(helpers.table_to_json(remote.call("agent_1", "walk_to", {goal={x=10, y=5}})))
-- Returns: {"queued":true,"action_id":"walk_1234_1"}

-- Get inventory
/c rcon.print(helpers.table_to_json(remote.call("agent_1", "get_inventory_items")))
-- Returns: {"iron-plate":50,"copper-plate":25}

-- Place entity
/c rcon.print(helpers.table_to_json(remote.call("agent_1", "place_entity", {
    entity_name="assembling-machine-1",
    position={x=5, y=5},
    direction=4
})))

-- List all agents
/c rcon.print(helpers.table_to_json(remote.call("agent", "list_agents")))
```

## Async Action Pattern

Async methods (`walk_to`, `mine_resource`, `craft_enqueue`) follow a consistent pattern:

1. **Call returns immediately** with `{queued: true, action_id: "..."}`
2. **State machine processes** the action over multiple ticks
3. **UDP notification sent** when action completes/fails

### UDP Message Format

```json
{
  "action_id": "walk_1234_1",
  "agent_id": 1,
  "action": "walk_to",
  "status": "completed",
  "tick": 54321,
  "success": true,
  "result": {
    "position": {"x": 10, "y": 5},
    "elapsed_ticks": 120
  },
  "category": "walking"
}
```

Status values: `"queued"`, `"in_progress"`, `"completed"`, `"failed"`, `"cancelled"`

## Agent State Machine

Each agent maintains state for concurrent activities:

```
Agent
├── walking: {path, path_id, progress, action_id, goal, ...}
├── mining: {mode, action_id, entity_name, target_count, ...}
├── crafting: {in_progress: {recipe, count, action_id}}
└── message_queue: {category -> [messages]}
```

The `Agent:process(event)` method is called every tick to:
1. Process walking (pathfinding, movement)
2. Process mining (progress tracking)
3. Process crafting (queue monitoring)
4. Flush message queue via UDP

## Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `fv-embodied-agent-enable-admin-api` | bool | true | Enable admin API for testing |

## Port Allocation

| Agent | UDP Port |
|-------|----------|
| Default | 34202 |
| Per-agent | Configurable via `create_agent(udp_port=...)` |

For server deployments:
- Server N uses base port `34202 + (N × 10)`
- Each agent on a server can have a unique port offset

## Entity Referencing

**Never use `unit_number`** to reference entities. Unit numbers are ephemeral.

Always reference by:
- `entity_name` + `position` for specific lookups
- `entity_type` + `position` for categorical scans

## Files

```
fv_embodied_agent/
├── info.json                # Mod metadata
├── control.lua              # mod scripting entrypoint
├── settings.lua             # Mod settings definitions
├── Agent.lua                # Agent class with state machine
├── agent_actions/
│   ├── RemoteInterface.lua  # Method definitions with paramspec
│   ├── walking.lua          # Pathfinding and movement
│   ├── mining.lua           # Resource extraction
│   ├── crafting.lua         # Hand crafting
│   ├── placement.lua        # Entity placement/pickup
│   ├── entity_ops.lua       # Entity configuration
│   ├── reachability.lua     # Nearby entity queries
│   ├── researching.lua      # Technology research
│   ├── charting.lua         # Map exploration
│   └── inspection.lua       # Entity inspection
├── game_state/
│   ├── Agents.lua           # Agent lifecycle, admin API
│   ├── Notifications.lua    # UDP message handling
│   ├── EntityInterface.lua  # Entity manipulation utilities
│   └── Spectator.lua        # (Disabled) Spectator mode
└── utils/
    ├── udp.lua              # UDP socket management
    ├── utils.lua            # General utilities
    ├── ParamSpec.lua        # Parameter validation
    ├── Error.lua            # Error handling
    ├── serialize.lua        # Lua table serialization
    ├── custom_events.lua    # Custom event registration
    └── debug_render.lua     # Debug visualization
```

## Integration with Other Mods

This mod is designed to work independently, but can be integrated with other mods through:

1. **Remote Interfaces**: Other mods can query agent state and control agents via `remote.call()`
   - Example: `fv_snapshot` mod queries `agent.list_agent_forces()` to track agent entities
   
2. **Custom Events**: Other mods can listen to agent actions via Factorio's event system
   - Example: `fv_snapshot` mod listens to `on_agent_entity_built` to capture entity placements
   - All custom events are exposed via the `custom_events` remote interface

**No Hard Dependencies**: The mod has zero dependencies on other mods. Any integration is optional and achieved through Factorio's standard remote interface and event systems.

## See Also

- [FactoryVerse Documentation](../../docs/) - FactoryVerse's specific implementation using this mod
- [FV Snapshot Mod](../fv_snapshot/) - Example integration: game state serialization mod that uses this mod's remote interfaces and custom events
- [Python Agent API](../../src/FactoryVerse/agent/) - FactoryVerse's Python bindings (one possible framework built on top of this mod)
