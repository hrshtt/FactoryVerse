# FactoryVerse Test Suite

## Overview

This test suite validates the FactoryVerse mod's remote interfaces and agent actions. Tests run within a Factorio scenario and are executed via RCON.

## Architecture

### Two-Tier Testing Strategy

| Tier | Location | What It Tests | Limitations |
|------|----------|---------------|-------------|
| **Lua Scenario Tests** | `test_scenario/tests/` | Sync actions, async action queueing, state machine behavior | Cannot verify disk writes, UDP notifications |
| **Python Integration Tests** | `tests/integration/` | RCON connectivity, end-to-end workflows, snapshot verification | Requires running Factorio server |

### Why This Split?

Factorio's Lua runtime has restrictions:
- **Cannot read files** it writes (snapshot verification impossible in Lua)
- **Cannot receive UDP** (async completion verification requires external listener)
- **`storage` table not accessible** from scenarios (must use `remote.call` only)

## Test Categories

### Sync Tests (Immediate Verification)

These tests call an action and verify the result in the same tick:

| Category | Tests | What They Verify |
|----------|-------|------------------|
| `agent/` | create, destroy, teleport, inspect | Agent lifecycle and state queries |
| `entity_ops/` | place_entity, pickup_entity, set_recipe | Entity manipulation |
| `inventory/` | put_item, take_item, set_limit, set_filter | Inventory operations |

### Async Tests (Multi-Tick Verification)

These tests start an action and poll for completion via `on_nth_tick`:

| Category | Tests | Pattern |
|----------|-------|---------|
| `crafting/` | enqueue, dequeue, completion | Start craft → poll `get_activity_state()` → verify inventory |
| `mining/` | mine_resource, completion, stop | Start mine → poll until complete → verify ore in inventory |
| `walking/` | walk_to, completion, stop | Start walk → poll until position reached |
| `charting/` | chart_spawn | Verify chunk visibility |

## Test Structure

### Sync Test Module

```lua
return {
    setup = function(ctx)
        -- Create agent, place entities, prepare state
        ctx:create_agent()
        ctx.entity = ctx:place_entity("iron-chest", {x=10, y=10})
        ctx.test_position = ctx.entity.position  -- Use actual position!
    end,
    
    test = function(ctx)
        -- Execute action and verify
        local result = ctx:agent_call("some_action", ...)
        ctx.assert.not_nil(result, "Should return result")
        ctx.assert.is_true(result.success, "Should succeed")
    end,
    
    teardown = function(ctx)
        ctx:clear_area({x=10, y=10}, 15)
        ctx:destroy_agent()
    end,
}
```

### Async Test Module

```lua
return {
    timeout_ticks = 600,  -- 10 seconds
    
    setup = function(ctx)
        ctx:create_agent()
        -- Prepare resources, position, etc.
    end,
    
    start = function(ctx)
        -- Initiate the async action
        local result = ctx:agent_call("walk_to", {x=50, y=50})
        ctx.action_started = result.queued
    end,
    
    poll = function(ctx)
        -- Return true when action is complete
        local state = ctx:agent_call("get_activity_state")
        return not state.walking.active
    end,
    
    verify = function(ctx)
        -- Verify final state
        local pos = ctx:agent_call("inspect").position
        ctx.assert.is_true(pos.x > 40, "Should have moved")
    end,
    
    teardown = function(ctx)
        ctx:destroy_agent()
    end,
}
```

## Test Context API

The test runner provides a `ctx` object with helpers:

### Agent Management
- `ctx:create_agent()` - Creates agent via `remote.call("agent", "create_agents", 1, true)`
- `ctx:destroy_agent()` - Destroys test agent
- `ctx:agent_call(method, ...)` - Calls `remote.call("agent_1", method, ...)`

### Entity Helpers
- `ctx:place_entity(name, position)` - Creates entity on surface
- `ctx:find_entity(name, position)` - Finds entity at position
- `ctx:clear_area(position, radius)` - Removes entities in area

### Assertions
- `ctx.assert.equals(expected, actual, message)`
- `ctx.assert.is_true(condition, message)`
- `ctx.assert.not_nil(value, message)`
- `ctx.assert.has_key(table, key, message)`

### Utilities
- `ctx.surface` - Game surface reference
- `ctx.grid` - TestGrid module for deterministic positions

## Running Tests

### Via RCON

```lua
-- Run all tests
/c rcon.print(remote.call("test_runner", "run_all_tests"))

-- Run specific category
/c rcon.print(remote.call("test_runner", "run_category", "agent"))

-- Run single test
/c rcon.print(remote.call("test_runner", "run_test", "agent.test_create"))

-- List available tests
/c rcon.print(remote.call("test_runner", "list_tests"))

-- Check async test status
/c rcon.print(remote.call("test_runner", "get_pending_tests"))
/c rcon.print(remote.call("test_runner", "get_async_result", "async_1"))
```

### Via Python

```bash
uv run pytest tests/integration/test_rcon_smoke.py -v
```

## Key Gotchas

### 1. Entity Position Snapping

Factorio snaps entities to grid positions. Always use the entity's actual position after creation:

```lua
-- WRONG: Position may not match after grid snapping
ctx.test_position = {x = pos.x + 2, y = pos.y + 2}
ctx.chest = ctx:place_entity("iron-chest", ctx.test_position)

-- RIGHT: Use entity's actual position
ctx.chest = ctx:place_entity("iron-chest", {x = pos.x + 2, y = pos.y + 2})
ctx.test_position = ctx.chest.position
```

### 2. Entity References Become Invalid

After pickup/destruction, entity references are invalid:

```lua
-- WRONG: Entity reference invalid after pickup
ctx.entity = ctx:place_entity("wooden-chest", pos)
ctx:agent_call("pickup_entity", "wooden-chest", ctx.entity.position)
-- ctx.entity is now invalid!

-- RIGHT: Copy position, don't keep entity reference
local entity = ctx:place_entity("wooden-chest", pos)
ctx.test_position = {x = entity.position.x, y = entity.position.y}
```

### 3. No `storage` Access in Scenarios

Scenarios cannot access `storage.agents`. Use remote interfaces:

```lua
-- WRONG: storage not accessible
local agent = storage.agents[1]

-- RIGHT: Use remote interface
local state = remote.call("agent_1", "inspect")
local activity = remote.call("agent_1", "get_activity_state")
```

### 4. Async Tests Need Polling

Async actions (walk, mine, craft) don't complete in the same tick:

```lua
-- WRONG: Checking immediately after start
local result = ctx:agent_call("mine_resource", "iron-ore", 10)
local inv = ctx:agent_call("inspect", true)  -- Mining not done yet!

-- RIGHT: Use async test pattern with poll/verify
start = function(ctx)
    ctx:agent_call("mine_resource", "iron-ore", 10)
end,
poll = function(ctx)
    local state = ctx:agent_call("get_activity_state")
    return not state.mining.active
end,
verify = function(ctx)
    local inv = ctx:agent_call("inspect", true)
    -- Now mining is complete
end,
```

### 5. Inventory Type Names

The `EntityInterface` uses specific inventory type names:

| Valid Names | Entity Types |
|-------------|--------------|
| `chest` | Containers (chests, cars, wagons) |
| `fuel` | Burner entities |
| `input` | Assemblers, furnaces (input slot) |
| `output` | Assemblers, furnaces (output slot) |
| `modules` | Entities with module slots |
| `ammo` | Turrets |
| `trunk` | Cars |
| `cargo` | Cargo wagons |

**Note:** Inserter filters use `entity.set_filter()` directly, not inventory filters.

## Adding New Tests

1. Create test file in appropriate category directory
2. Follow sync or async test pattern
3. Register in `tests/test_suite.lua`:

```lua
return {
    category_name = {
        test_name = require("tests.category_name.test_name"),
    },
}
```

## Test Results Format

```json
{
    "total": 21,
    "passed": 16,
    "failed": 2,
    "pending": 3,
    "duration": 0,
    "results": [
        {"test_name": "agent.test_create", "passed": true, "duration": 0},
        {"test_name": "entity_ops.test_pickup", "passed": false, "error": "..."}
    ],
    "failures": [...],
    "success_rate": 76.19
}
```

- `pending` - Async tests still running (check with `get_async_result`)
- `duration` - Ticks elapsed (0 for sync tests)

