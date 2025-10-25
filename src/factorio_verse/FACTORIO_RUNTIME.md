# Factorio Lua Runtime: Lifecycle, Events, and Architecture

## Table of Contents
1. [Lifecycle Events](#lifecycle-events)
2. [Storage and Persistence](#storage-and-persistence)
3. [Event Registration](#event-registration)
4. [Server vs Client Execution](#server-vs-client-execution)
5. [The Dispatcher Pattern](#the-dispatcher-pattern)
6. [Common Pitfalls](#common-pitfalls)

---

## Lifecycle Events

Factorio executes scripts at various stages of the game lifecycle. Understanding when each event fires is critical for correct behavior.

### `script.on_init()`

**When it fires:**
- First time a NEW game is created
- First time a MOD is added to an existing save
- Never fires when loading an existing save

**Use for:**
- Initializing `storage` with default values
- Setting up initial game state
- One-time setup that should only happen on fresh games

**Important:** `storage` is **read-write** during `on_init`

```lua
script.on_init(function()
  storage.player_count = 0
  storage.game_started = true
end)
```

### `script.on_load()`

**When it fires:**
- Every time a saved game is LOADED
- Server startup with an existing save
- When a client joins a multiplayer game (their local copy loads)
- After `/reload` command
- After mod reload

**Use for:**
- Re-establishing non-persistent Lua structures (metatables, function references)
- Re-registering event handlers if they were lost
- Reading from storage to restore state

**Important:** `storage` is **READ-ONLY** during `on_load`. You cannot write to it.

```lua
script.on_load(function()
  -- Read from storage - OK
  if storage.game_started then
    log("Game loaded!")
  end
  
  -- DO NOT write to storage here
  -- storage.new_value = 5  -- ERROR: causes desync
end)
```

### `script.on_configuration_changed()`

**When it fires:**
- When mod configuration changes
- When mod version changes
- When dependency mods are added/removed/updated

**Use for:**
- Updating storage after mod changes
- Migration logic for save compatibility

**Important:** `storage` is **read-write** during this event.

---

## Storage and Persistence

### `storage` vs `global` (Factorio 2.0+)

| Aspect | `global` (1.0+) | `storage` (2.0+) |
|--------|-----------------|-----------------|
| Persists across saves | ✅ | ✅ |
| Survives mod reload | ✅ | ✅ |
| Prevents function writes | ❌ | ✅ |
| Best practice | Deprecated | **Use this** |

**Key difference:** `storage` prevents methods from being written to the table, ensuring clean serialization. Methods cannot be serialized to disk anyway.

```lua
-- BAD: functions serialize unexpectedly
global.handler = function() end  -- Works but causes issues

-- GOOD: only data in storage
storage.config = { enabled = true }
storage.data = { 1, 2, 3 }
```

### Availability by Event

| Event | Read | Write | Use Case |
|-------|------|-------|----------|
| `on_init` | ✅ | ✅ | Initialize on new game |
| `on_load` | ✅ | ❌ | Restore references |
| `on_configuration_changed` | ✅ | ✅ | Migrate on mod updates |
| Event handlers | ✅ | ✅ | During gameplay |

---

## Event Registration

### Critical Rule: Events Can Only Be Registered Once Per Event ID

When you call `script.on_event(event_id, handler)`, it **overwrites** any previous handler for that event ID.

```lua
script.on_event(defines.events.on_tick, handler1)
-- handler1 is now registered

script.on_event(defines.events.on_tick, handler2)
-- handler1 is REPLACED by handler2
-- handler1 is GONE

-- Both handlers never run - only handler2 runs every tick!
```

### Problem: Multiple Modules Need Events

If you have multiple modules (Snapshot, MapDiscovery, ActionRegistry), each wanting to handle `on_tick`:

```lua
-- Module A
script.on_event(defines.events.on_tick, function() 
  -- A's tick logic
end)

-- Module B
script.on_event(defines.events.on_tick, function()
  -- B's tick logic
end)

-- Result: Only B's handler runs. A's handler is lost.
-- This is a BUG!
```

### Solution: The Dispatcher Pattern (Aggregation)

Register events **once at the top level**, aggregating all handlers from all modules:

```lua
-- Step 1: Modules export their events
local module_a_events = {
  [defines.events.on_tick] = function() 
    -- A's logic
  end,
  [defines.events.on_tick] = function()
    -- A's other logic (for nth_tick)
  end
}

local module_b_events = {
  [defines.events.on_tick] = function()
    -- B's logic
  end
}

-- Step 2: Aggregate all handlers
local all_handlers = {}
for event_id, handler in pairs(module_a_events) do
  all_handlers[event_id] = all_handlers[event_id] or {}
  table.insert(all_handlers[event_id], handler)
end
for event_id, handler in pairs(module_b_events) do
  all_handlers[event_id] = all_handlers[event_id] or {}
  table.insert(all_handlers[event_id], handler)
end

-- Step 3: Register ONCE with aggregated handlers
for event_id, handlers_list in pairs(all_handlers) do
  script.on_event(event_id, function(event)
    for _, handler in ipairs(handlers_list) do
      handler(event)
    end
  end)
end

-- Result: All module handlers run when event fires
```

### nth_tick Events (Recurring Events)

Same principle applies to `script.on_nth_tick(n, handler)`:

```lua
-- Can only register ONE handler per tick interval
script.on_nth_tick(60, handler1)
script.on_nth_tick(60, handler2)  -- handler1 is REPLACED!

-- Solution: aggregate before registering
script.on_nth_tick(60, function(event)
  handler1(event)
  handler2(event)
end)
```

---

## Server vs Client Execution

### Deterministic Simulation Model

Factorio requires **server and all clients to execute identically** on the same tick. This prevents desynchronization:

```
Server Tick N:     Logic A → Logic B → Logic C
Client Tick N:     Logic A → Logic B → Logic C
                   ↑ Must match exactly ↑
```

### The Challenge: on_load Fires Everywhere

`script.on_load()` fires on:
- Server when loading a save
- Each client when connecting to server
- Each client when rejoining

```lua
script.on_load(function()
  -- This runs on SERVER
  -- AND on EVERY CONNECTING CLIENT
end)
```

### How to Detect Server vs Client

**Option 1: Check for `rcon` object** (Most Reliable)
```lua
if rcon then
  -- Running on SERVER (rcon only exists on server)
else
  -- Running on CLIENT
end
```

**Option 2: Check connected players** (With Caveats)
```lua
if game.is_multiplayer() and #game.connected_players == 0 then
  -- Likely on SERVER with no clients
else
  -- Likely on CLIENT or server with players
end
```

### Why We Use These Checks

Disk I/O is **server-only**. Clients should never write files:

```lua
if rcon then
  -- Safe: only runs on server
  helpers.write_file(path, data, false)
end
```

### Avoiding Desyncs with Conditional Logic

✅ **CORRECT**: Conditional logic INSIDE handlers
```lua
script.on_event(defines.events.on_tick, function(event)
  if rcon then
    -- Server-only logic
  end
  -- Both server and client run this handler
end)
```

❌ **WRONG**: Conditional event registration
```lua
if rcon then
  script.on_event(defines.events.on_tick, handler)
end
-- Server registers event, client doesn't → DESYNC!
```

---

## The Dispatcher Pattern

### Why Use It

Our `control.lua` uses a dispatcher pattern to:
1. Allow multiple modules to export events independently
2. Aggregate all events in one place
3. Register each event once with all handlers
4. Maintain consistency and prevent desyncs

### How It Works in Our Codebase

```lua
-- In control.lua
local function aggregate_all_events()
  local all_handlers = {}
  
  -- Collect from Module 1
  local snapshot_events = Snapshot:get_events()
  for event_id, handler in pairs(snapshot_events) do
    all_handlers[event_id] = all_handlers[event_id] or {}
    table.insert(all_handlers[event_id], handler)
  end
  
  -- Collect from Module 2
  local action_events = action_registry:get_events()
  for event_id, handler in pairs(action_events) do
    all_handlers[event_id] = all_handlers[event_id] or {}
    table.insert(all_handlers[event_id], handler)
  end
  
  return all_handlers
end

-- Register ONCE
local all_handlers = aggregate_all_events()
for event_id, handlers_list in pairs(all_handlers) do
  script.on_event(event_id, function(event)
    for _, handler in ipairs(handlers_list) do
      pcall(handler, event)  -- Wrap in pcall for error handling
    end
  end)
end
```

### Module Export Pattern

Each module exports `get_events()`:

```lua
-- In Snapshot.lua
function Snapshot:get_events()
  return {
    [defines.events.on_resource_depleted] = function(event)
      -- Handle resource depletion
    end,
    [defines.events.on_chunk_charted] = function(event)
      -- Handle chunk charted
    end
  }
end
```

This keeps modules independent while allowing central registration.

---

## Common Pitfalls

### 1. Writing to Storage in on_load

```lua
-- ❌ WRONG
script.on_load(function()
  storage.tick_count = 0  -- ERROR: read-only
end)

-- ✅ CORRECT
script.on_init(function()
  storage.tick_count = 0
end)

script.on_load(function()
  log("Starting with tick_count: " .. storage.tick_count)
end)
```

### 2. Conditional Event Registration

```lua
-- ❌ WRONG: causes desync
if game.is_multiplayer() then
  script.on_event(defines.events.on_tick, handler)
end

-- ✅ CORRECT: conditional logic in handler
script.on_event(defines.events.on_tick, function(event)
  if game.is_multiplayer() then
    -- server-specific logic
  end
end)
```

### 3. Forgetting Event Overwrites

```lua
-- ❌ WRONG: only handler2 runs
script.on_event(defines.events.on_tick, handler1)
script.on_event(defines.events.on_tick, handler2)

-- ✅ CORRECT: use dispatcher or aggregate
script.on_event(defines.events.on_tick, function(event)
  handler1(event)
  handler2(event)
end)
```

### 4. Blocking I/O in Event Handlers

```lua
-- ⚠️ RISKY: slow file writes can cause tick overruns
script.on_nth_tick(1, function(event)
  local huge_data = gather_massive_snapshot()
  helpers.write_file(path, huge_data, false)  -- Blocks!
end)

-- ✅ BETTER: use async snapshots
snapshot:take_map_snapshot({
  async = true,
  chunks_per_tick = 2
})
```

---

## Our Implementation in control.lua

We use the dispatcher pattern with:

1. **Aggregation Phase**: Collect events from all modules
2. **Registration Phase**: Register each event once with aggregated handlers
3. **Error Handling**: Wrap handlers in `pcall` to prevent one failure from breaking others

Key modules that export events:
- `Snapshot`: on_resource_depleted, on_chunk_charted, nth_tick handlers
- `ActionRegistry`: Custom action events
- `MapDiscovery`: nth_tick handlers for exploration

This ensures:
- ✅ All modules' logic runs when their events fire
- ✅ No handlers are accidentally overwritten
- ✅ Central place to manage all event registration
- ✅ Easy to add new modules without touching core event code

---

## Chunk Tracking and Map Snapshots

### The Chunk Charting Problem

Factorio's chunk charting system has a fundamental limitation on headless servers:

**The Issue:**
- Chunks are "charted" when a **LuaPlayer** (human or AI character) reveals them
- On headless servers without player connections, `force.is_chunk_charted()` returns `false` even after `force.chart()` is called
- This is a known Factorio limitation: charting requires active player connection to work correctly

**Why This Matters:**
When we take a map snapshot, we need to know: **"Which chunks should we include?"**

### Two Sources of Charted Chunks

#### 1. Player-Charted Chunks (Reliable for Connected Players)
```lua
local force = game.forces["player"]
for chunk in surface.get_chunks() do
  if force.is_chunk_charted(surface, chunk) then
    -- This chunk was explored by a LuaPlayer
  end
end
```

**When available:**
- Game loaded with existing LuaPlayer characters
- Players are or were connected to reveal the map

**Why it works:**
- Factorio tracks player discovery in the force's chart data
- `is_chunk_charted()` returns true for these chunks

#### 2. Agent-Tracked Chunks (Fallback for Headless)
```lua
storage.registered_charted_areas = {
  [chunk_key] = { x = cx, y = cy },
  ...
}
```

**When needed:**
- Headless server with no connected players
- Agent characters moving around but not revealing map (LuaEntity type doesn't chart)
- We manually track charted areas via `GameState:register_charted_area()`

**How it works:**
- When agents move/chart, we explicitly call `gs:register_charted_area(area)`
- Stored in `storage.registered_charted_areas`
- Acts as fallback when `is_chunk_charted()` returns false

### Chunk Selection Logic for Map Snapshots

When `take_map_snapshot()` is called, `get_charted_chunks()` executes this decision tree:

```
┌─────────────────────────────────────────┐
│ get_charted_chunks()                    │
└────────────────┬────────────────────────┘
                 │
         ┌───────▼───────┐
         │ Try native    │
         │ is_chunk_     │
         │ charted()     │
         └───┬───────┬───┘
             │       │
        YES  │       │  NO
         ┌───▼──┐ ┌──▼────────────────────┐
         │Return│ │Check for registered   │
         │those │ │charted areas fallback │
         │chunks│ │ storage.registered_.. │
         └──────┘ └──┬───────────────┬────┘
                     │               │
                YES  │               │  NO
                ┌────▼──┐        ┌───▼────┐
                │Use    │        │Return  │
                │those  │        │EMPTY   │
                │chunks │        │CHUNKS  │
                └───────┘        └────────┘
```

**Code in `GameState:get_charted_chunks()`:**

```lua
function GameState:get_charted_chunks(sort_by_distance)
    local charted_chunks = {}
    
    -- Primary: Try native is_chunk_charted() (works for player-connected saves)
    for chunk in surface.get_chunks() do
        if force.is_chunk_charted(surface, chunk) then
            table.insert(charted_chunks, chunk_data)
        end
    end
    
    -- Fallback: If empty, use registered areas (headless server with agents)
    if #charted_chunks == 0 and storage.registered_charted_areas then
        for _, chunk_data in pairs(storage.registered_charted_areas) do
            table.insert(charted_chunks, chunk_data)
        end
    end
    
    return charted_chunks
end
```

### How Chunks Get Registered

#### Path 1: Player Exploration
```
LuaPlayer moves around
         ↓
Factorio auto-charts chunks (is_chunk_charted becomes true)
         ↓
get_charted_chunks() returns them on snapshot
```

#### Path 2: Agent Exploration
```
Agent moves to new location
         ↓
MapDiscovery:scan_and_discover() called every N ticks
         ↓
Agent's force.chart() called (doesn't register as visible on headless!)
         ↓
We manually call gs:register_charted_area() to track it
         ↓
Stored in storage.registered_charted_areas
         ↓
get_charted_chunks() uses as fallback
```

### Server Startup Snapshot Behavior

When server loads:

```lua
-- In control.lua on_load
if game.is_multiplayer() and #game.connected_players == 0 then
  local surface = game.surfaces[1]
  if surface and #surface.find_entities() > 0 then
    -- Existing save loaded
    -- get_charted_chunks() determines which chunks to snapshot:
    -- 1. If players previously explored: use is_chunk_charted()
    -- 2. If only agents explored: use storage.registered_charted_areas
    -- 3. If neither: EMPTY snapshot (no chunks)
    
    snapshot:take_map_snapshot({ async = true, chunks_per_tick = 2 })
  end
end
```

### Important Implications

| Scenario | Chunk Source | Snapshot Includes |
|----------|--------------|------------------|
| Save with LuaPlayer exploration | `is_chunk_charted()` | ✅ All player-explored chunks |
| Headless server + agents only | `registered_charted_areas` | ✅ Agent vision radius around agents |
| Fresh server (no save) | Neither | ❌ EMPTY (no chunks to snapshot) |
| Server mid-startup, agents haven't moved yet | Neither | ❌ EMPTY (until agents move/chart) |

### Practical Implications for Development

1. **Don't assume chunks exist on server start**
   - Headless server with fresh agents = no charted chunks yet
   - Wait for agents to move → chunks get charted/registered → snapshot on next run

2. **Register areas explicitly when agents move**
   - `MapDiscovery.scan_and_discover()` does this automatically
   - Called every N ticks, checks agent positions, charts + registers areas

3. **Use registered_charted_areas only as fallback**
   - Primary method is always `is_chunk_charted()` (more reliable)
   - Falls back only when that returns empty (headless limitation)

4. **Snapshot timing matters**
   - Taking snapshot at server startup catches player-explored chunks
   - But won't include agent-discovered chunks until agents have moved
   - Consider taking additional snapshots after initial agent movement
