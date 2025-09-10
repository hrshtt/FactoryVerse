# Action System Interfaces

This document explains the two remote interfaces available for executing actions in FactoryVerse.

## Direct Action Interface (`actions`)

The direct action interface executes actions immediately when called. This is the original interface that provides direct access to all registered actions.

### Usage

```lua
-- Direct execution (immediate)
remote.call("actions", "agent.walk", {x = 10, y = 20})
remote.call("actions", "entity.place", {entity_type = "iron-ore", position = {x = 5, y = 5}})
remote.call("actions", "item.craft", {recipe = "iron-plate", count = 10})
```

### Available Actions

All actions registered in ActionRegistry are available with their exact names:
- `agent.walk` (or `agent_walk`)
- `entity.place` (or `entity_place`)
- `item.craft` (or `item_craft`)
- `mine_resource` (or `mine_resource`)
- `start_research` (or `start_research`)

## Queue-Based Action Interface (`action_queue`)

The queue-based interface allows batching and queuing actions for later execution. This is useful for complex operations that need to be coordinated or executed in batches.

### Queue Management Methods

```lua
-- Enqueue an action
remote.call("action_queue", "enqueue", "agent.walk", {x = 10, y = 20}, "batch1", 1)

-- Process all queued actions
remote.call("action_queue", "process_all")

-- Process actions for a specific key
remote.call("action_queue", "process_key", "batch1")

-- Get queue status
local status = remote.call("action_queue", "get_status")
-- Returns: {total_queued = 5, processing = false, immediate_mode = true, key_counts = {batch1 = 3}}

-- Clear queue (optionally for specific key)
remote.call("action_queue", "clear") -- Clear all
remote.call("action_queue", "clear", "batch1") -- Clear specific key

-- Configure queue behavior
remote.call("action_queue", "set_immediate_mode", false) -- Disable immediate execution
remote.call("action_queue", "set_max_queue_size", 5000) -- Set max queue size
```

### Convenience Methods

Each action also has a convenience method for queuing:

```lua
-- Queue versions of actions (with optional key and priority)
remote.call("action_queue", "queue_agent.walk", {x = 10, y = 20}, "batch1", 1)
remote.call("action_queue", "queue_entity.place", {entity_type = "iron-ore", position = {x = 5, y = 5}}, "batch1", 2)
remote.call("action_queue", "queue_item.craft", {recipe = "iron-plate", count = 10}, "batch1", 3)

-- Safe names (with underscores) also work
remote.call("action_queue", "queue_agent_walk", {x = 10, y = 20}, "batch1", 1)
```

### Batch Processing Example

```lua
-- Disable immediate mode to queue actions
remote.call("action_queue", "set_immediate_mode", false)

-- Queue multiple actions with the same key
remote.call("action_queue", "queue_agent.walk", {x = 10, y = 20}, "exploration", 1)
remote.call("action_queue", "queue_entity.place", {entity_type = "iron-ore", position = {x = 15, y = 25}}, "exploration", 2)
remote.call("action_queue", "queue_mine_resource", {resource_type = "iron-ore", position = {x = 15, y = 25}}, "exploration", 3)

-- Process all actions in the exploration batch
local results = remote.call("action_queue", "process_key", "exploration")
-- Results will contain success/error info for each action
```

## When to Use Which Interface

### Use Direct Interface (`actions`) when:
- You need immediate execution
- Simple, one-off actions
- Real-time responses are required
- Actions don't need coordination

### Use Queue Interface (`action_queue`) when:
- You need to batch multiple actions
- Actions need to be coordinated or executed in sequence
- You want to validate all actions before execution
- You need priority-based execution
- You want to group related actions together

## Integration Notes

Both interfaces use the same underlying ActionRegistry and ActionQueue systems. The ActionQueue is initialized with the ActionRegistry as a dependency, ensuring both interfaces have access to the same set of actions and validators.

The ActionRegistry maintains its original remote interface for backward compatibility, while the ActionQueue provides the new queue-based functionality.
