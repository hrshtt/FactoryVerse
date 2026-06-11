# Force System Readiness Assessment

Assessment of FactoryVerse's force system readiness for multi-agent isolated evaluation (lab-grid scenario).

## Summary

| Component | Force-Aware | Status | Action Required |
|-----------|-------------|--------|-----------------|
| Agent production stats | ✅ Yes | Ready | None |
| Agent manual stats | ✅ Yes | Ready | None |
| Agent actions | ✅ Yes | Ready | None |
| Agent technology/recipes | ✅ Yes | Ready | None |
| Entity snapshot tracking | ❌ No | **BROKEN** | Fix hardcoded "player" |
| Status dump tracking | ❌ No | **BROKEN** | Fix hardcoded "player" |
| Chunk charting | ❌ No | **BROKEN** | Fix hardcoded "player" |
| Power statistics | N/A | Global | Intentional (global grid) |

**Bottom Line**: Task verification (production stats) will work correctly with per-cell forces. Entity snapshotting will NOT capture entities from non-player forces, breaking the map view for isolated cells.

---

## Detailed Analysis

### fv_embodied_agent - READY ✅

The agent module correctly uses dynamic force references throughout.

#### Agent.lua - Force-Aware Methods

```lua
-- Line 618: Production statistics use agent's force
function Agent:get_production_statistics()
    local stats = self.character.force.get_item_production_statistics()
    ...
end

-- Line 636: Manual stats tracked per-agent (separate from force)
function Agent:get_manual_production_statistics()
    return {
        crafted = storage.agent_manual_crafted[self.agent_id] or {},
        mined = storage.agent_manual_mined[self.agent_id] or {},
        ...
    }
end

-- Line 570: Technologies use agent's force
function Agent:get_technologies(only_available)
    local force = self.character.force
    ...
end

-- Line 545: Recipes use agent's force
function Agent:get_recipes(category)
    local force = self.character.force
    ...
end
```

#### Agents.lua (game_state) - Force Creation

```lua
-- Line 26-57: Force creation with proper relationships
function M.create_or_get_force(force_name)
    local force = game.forces[force_name]
    if not force then
        force = game.create_force(force_name)
        -- Set friendly with player force
        local player_force = game.forces.player
        force.set_friend(player_force, true)
        player_force.set_friend(force, true)
        -- Set friendly with all existing agent forces
        ...
    end
    return force
end

-- Line 129-200: Agent creation with force options
function M.create_agent(udp_port, set_unique_forces, default_common_force, initial_inventory)
    -- WARNING issued when using unique forces
    if use_unique_forces then
        game.print("WARNING: Using unique forces for agents. In-engine charting updates
                   will not work for forces without a connected LuaPlayer...")
    end
    ...
end
```

---

### fv_snapshot - BROKEN ❌

The snapshot module has multiple hardcoded `force = "player"` references that will miss entities from other forces.

#### Entities.lua - Hardcoded "player"

```lua
-- Lines 105-113: Entity status tracking
function M.track_chunk_entity_status(chunk_position)
    ...
    local entity_count = surface.count_entities_filtered {
        area = chunk_area,
        force = "player",  -- ❌ HARDCODED
    }
    ...
    local entities = surface.find_entities_filtered {
        area = chunk_area,
        force = "player",  -- ❌ HARDCODED
    }
    ...
end

-- Lines 198-206: Status dump collection
function M.collect_all_statuses_for_dump(charted_chunks)
    ...
    local entity_count = surface.count_entities_filtered {
        area = chunk_area,
        force = "player",  -- ❌ HARDCODED
    }
    ...
    local entities = surface.find_entities_filtered {
        area = chunk_area,
        force = "player",  -- ❌ HARDCODED
    }
    ...
end
```

#### Map.lua - Hardcoded "player"

```lua
-- Line 588: Force getter returns hardcoded player
function M.get_player_force()
    return game.forces["player"]  -- ❌ HARDCODED
end

-- Lines 926-928: Phase find_entities
local entity_count = surface.count_entities_filtered {
    area = chunk_area,
    force = "player",  -- ❌ HARDCODED
}

-- Lines 1668-1672: On chunk charted
local entity_count = surface.count_entities_filtered {
    area = chunk_area,
    force = "player"  -- ❌ HARDCODED
}

-- Lines 1705-1709: On agent chunk charted
local entity_count = surface.count_entities_filtered {
    area = chunk_area,
    force = "player"  -- ❌ HARDCODED
}
```

---

## Impact on Lab-Grid Scenario

### What Works

1. **Task Verification** ✅
   - `get_production_statistics()` uses `agent.character.force` (dynamic)
   - Each cell's force will have separate production stats
   - Manual tracking is per-agent, not per-force
   - Verification equation works: `automation = force_output - manual`

2. **Agent Actions** ✅
   - All actions use `self.character.force` dynamically
   - Building, crafting, mining work regardless of force

3. **Force Creation** ✅
   - `create_or_get_force()` properly creates isolated forces
   - Friendly relationships set correctly

### What Breaks

1. **Entity Snapshotting** ❌
   - Snapshot only captures entities from "player" force
   - Entities in cell-specific forces (e.g., `cell_0`, `cell_1`) won't appear in DuckDB
   - `remote_view` queries will return empty for non-player-force entities

2. **Status Tracking** ❌
   - Entity status dumps (for working/no-power states) miss non-player entities
   - Status monitoring broken for isolated cells

3. **Chunk Tracking** ❌
   - `has_player_entities` flag only tracks player force
   - ChunkTracker metadata inaccurate for multi-force scenarios

---

## Recommended Fix

### Use Existing Remote Interface Pattern (Simple)

The fix leverages the existing cross-mod communication pattern:

1. **fv_embodied_agent already exposes `list_agent_forces()`** via remote interface
2. **fv_snapshot queries it** to build the force list for entity searches

```lua
-- In fv_snapshot: utils/forces.lua (new helper)
local M = {}

--- Get all forces that should be tracked in snapshots
--- Uses remote interface to query agent forces from fv_embodied_agent
--- @return table Array of force names
function M.get_tracked_forces()
    local forces = {"player"}
    local seen = {player = true}

    -- Query agent forces via remote interface
    if remote.interfaces.agent and remote.interfaces.agent.list_agent_forces then
        local agent_forces = remote.call("agent", "list_agent_forces")
        for _, force_name in pairs(agent_forces) do
            if not seen[force_name] then
                table.insert(forces, force_name)
                seen[force_name] = true
            end
        end
    end

    return forces
end

return M
```

Then replace hardcoded `force = "player"` with:

```lua
local forces = require("utils.forces")

-- In Entities.lua, Map.lua
local entities = surface.find_entities_filtered {
    area = chunk_area,
    force = forces.get_tracked_forces(),  -- Dynamic: ["player", "agent-1", "cell_0", ...]
}
```

**Why This Works:**
- Storage table in fv_embodied_agent is the source of truth for agent forces
- Remote interface provides cross-mod access (already exists: `list_agent_forces`)
- No complex parameterization needed - just query and use
- Clean fallback: if no agents exist, returns `{"player"}`

---

## Charting - Custom Events Solve This

From `Agents.lua` line 139-143:

> "WARNING: Using unique forces for agents. In-engine charting updates will not work for forces without a connected LuaPlayer, for the character, radar and bots."

This is a **Factorio engine limitation** for the built-in `on_chunk_charted` event. However, FactoryVerse already has the solution:

**Custom Events Pattern:**
- `fv_embodied_agent` emits custom events based on agent state machine interactions
- `fv_snapshot` listens to these custom events, not Factorio's built-in events
- `on_agent_chunk_charted` already exists and is handled by `Map._on_agent_chunk_charted()`

The control flow is:
```
Agent charting action → Agent state machine → custom_events.on_agent_chunk_charted
    → fv_snapshot Map._on_agent_chunk_charted() → ChunkTracker + snapshot queue
```

This bypasses Factorio's engine limitation because we control the event emission through our own state machines, not through LuaPlayer-dependent engine events.

---

## Files Requiring Modification

| File | Action |
|------|--------|
| `src/fv_snapshot/utils/forces.lua` | **CREATE** - Helper to get tracked forces via remote interface |
| `src/fv_snapshot/game_state/Entities.lua` | Replace `force = "player"` with `forces.get_tracked_forces()` (lines 107, 113, 200, 206) |
| `src/fv_snapshot/game_state/Map.lua` | Replace `force = "player"` with `forces.get_tracked_forces()` (lines 926, 1669, 1706) |

**Total: 1 new file, 2 files modified (7 line changes)**

---

## Verification Plan

After fixes, verify with:

```python
# Test: Create agent with unique force
result = rcon.run("agent", "create_agent", {"set_unique_forces": True})
agent_id = result["agent_id"]
force_name = result["force_name"]  # e.g., "agent-1"

# Test: Place entity with agent
await agent.place_entity("wooden-chest", position)

# Test: Verify entity appears in snapshot
# Check DuckDB entities table has force column matching agent force
entities = db.execute(f"""
    SELECT * FROM entities
    WHERE position_x = {position.x} AND position_y = {position.y}
""").fetchall()
assert len(entities) == 1
assert entities[0].force == force_name  # Must match agent's force, not "player"
```

---

## Related Documents

- [LAB_GRID_SCENARIO_DESIGN.md](./LAB_GRID_SCENARIO_DESIGN.md) - Uses force isolation per cell
- [TASK_VERIFICATION.md](./TASK_VERIFICATION.md) - Verification uses force production stats (works correctly)
