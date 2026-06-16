# Lab Grid Scenario Design

A new scenario for parallel multi-agent isolated evaluation of lab play tasks.

## Problem Statement

FLE's approach to lab play evaluation:
- **One server per agent**: Spin up N Docker containers for N parallel evaluations
- **Expensive**: Each container has full Factorio overhead (~200MB RAM, CPU cycles)
- **No visual parallelism**: Can't observe multiple agents simultaneously
- **Slow iteration**: Starting/stopping containers adds latency

FactoryVerse's multi-agent architecture enables a better solution.

## Solution: Lab Grid Scenario

A single Factorio game with an **N×N grid of isolated play areas**. Each cell is a self-contained lab environment where one agent runs independently.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Lab Grid (4x4 example)                       │
│                                                                     │
│   ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐                   │
│   │ Cell 0  │ │ Cell 1  │ │ Cell 2  │ │ Cell 3  │                   │
│   │ Agent 1 │ │ Agent 2 │ │ Agent 3 │ │ Agent 4 │                   │
│   └─────────┘ └─────────┘ └─────────┘ └─────────┘                   │
│   ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐                   │
│   │ Cell 4  │ │ Cell 5  │ │ Cell 6  │ │ Cell 7  │                   │
│   │ Agent 5 │ │ (empty) │ │ (empty) │ │ (empty) │                   │
│   └─────────┘ └─────────┘ └─────────┘ └─────────┘                   │
│   ...                                                               │
└─────────────────────────────────────────────────────────────────────┘
```

### Benefits

1. **Resource efficient**: Single Factorio instance serves 16+ parallel agents
2. **Visual debugging**: Zoom out to see all agents working simultaneously
3. **Fast iteration**: No container startup/shutdown overhead
4. **Consistent timing**: All agents share the same game tick
5. **Fair comparison**: Identical resource layouts per cell

## Design Details

### Grid Layout (Chunk-Aligned)

Based on Factorio's chunk system (32×32 tiles), we use chunk-aligned dimensions:

```lua
-- Constants (all in tiles unless noted)
CHUNK_SIZE = 32                    -- Factorio chunk size
PLAY_AREA_CHUNKS = 4               -- 4×4 chunks per play area
GAP_CHUNKS = 1                     -- 1 chunk gap between cells
CELL_CHUNKS = PLAY_AREA_CHUNKS + GAP_CHUNKS  -- 5×5 chunks per cell

PLAY_AREA_SIZE = PLAY_AREA_CHUNKS * CHUNK_SIZE  -- 128 tiles
GAP_SIZE = GAP_CHUNKS * CHUNK_SIZE              -- 32 tiles
CELL_SIZE = CELL_CHUNKS * CHUNK_SIZE            -- 160 tiles

GRID_SIZE = 8                      -- 8×8 grid = 64 cells
MAP_SIZE = GRID_SIZE * CELL_SIZE   -- 1280 tiles (40 chunks)

-- Cell index to position:
--   cell_x = cell_index % GRID_SIZE
--   cell_y = cell_index // GRID_SIZE
--   origin_x = cell_x * CELL_SIZE
--   origin_y = cell_y * CELL_SIZE
```

**Why chunk alignment matters:**
- Factorio optimizes by chunk (entity searches, pollution, map gen)
- Snapshot mod processes chunk-by-chunk
- Debug overlay (F4) shows chunk grid - easy to verify boundaries

### Cell Contents

Each cell contains identical resources (positions relative to cell origin):

```
┌────────────────────────────────────────────────────────────────┐
│                         128×128 Play Area                      │
│                                                                │
│   ┌─────────┐  ┌─────────┐                                    │
│   │  Iron   │  │ Copper  │     Resource patches: 8×8 tiles    │
│   │  Ore    │  │  Ore    │     Amount: 50,000 per tile        │
│   └─────────┘  └─────────┘                                    │
│    (16,16)      (48,16)                                       │
│                                                                │
│   ┌─────────┐  ┌─────────┐                                    │
│   │  Coal   │  │  Stone  │                                    │
│   │         │  │         │                                    │
│   └─────────┘  └─────────┘                                    │
│    (16,48)      (48,48)                                       │
│                                                                │
│                    ⊕ Spawn (64,64)                            │
│                                                                │
│   ≈≈≈≈≈≈≈                                                     │
│   ≈Water ≈  (16,96)    ⛽⛽⛽ Oil wells (80,96)                │
│   ≈≈≈≈≈≈≈                                                     │
│                                                                │
└────────────────────────────────────────────────────────────────┘
│                         32 tile gap                            │
```

- **Lab tile floor** (`lab-dark-1`) - obstacle-free
- **Resource patches** - 8×8 tiles, high richness (enough for full task)
- **Water tiles** - 5×5 for offshore pump placement
- **Oil wells** - 3 crude-oil entities
- **Spawn point** - Cell center (64,64 relative)

### Agent-Cell Assignment

```lua
-- storage.agent_cells[agent_id] = cell_index
-- storage.cell_bounds[cell_index] = {left_top, right_bottom}

-- When agent is created:
function assign_agent_to_cell(agent_id)
    local cell_index = find_empty_cell()
    storage.agent_cells[agent_id] = cell_index

    -- Teleport agent to cell center
    local bounds = get_cell_bounds(cell_index)
    local center_x = (bounds.left_top.x + bounds.right_bottom.x) / 2
    local center_y = (bounds.left_top.y + bounds.right_bottom.y) / 2
    teleport_agent(agent_id, {center_x, center_y})
end
```

### Movement & Build Constraints

Following the pattern from Factorio's built-in `team-production` scenario:

**1. Area bounds checking:**
```lua
-- Check if position is within agent's assigned cell
function is_in_cell(position, cell_index)
    local bounds = get_cell_bounds(cell_index)
    return position.x >= bounds.left_top.x and
           position.x < bounds.right_bottom.x and
           position.y >= bounds.left_top.y and
           position.y < bounds.right_bottom.y
end
```

**2. Build restriction via event handler:**
```lua
-- Destroy entities built outside assigned cell (from team-production pattern)
script.on_event(defines.events.on_built_entity, function(event)
    local entity = event.entity
    if not (entity and entity.valid) then return end

    local agent_id = get_agent_id_for_force(entity.force)
    local cell_index = storage.agent_cells[agent_id]

    if not is_in_cell(entity.position, cell_index) then
        entity.destroy()
        -- Optionally return items to agent
    end
end)
```

**3. Walking module enforcement:**
```lua
-- In fv_embodied_agent walking.lua, validate target before movement
function validate_walk_target(agent_id, target_pos)
    local cell_index = storage.agent_cells[agent_id]
    if not is_in_cell(target_pos, cell_index) then
        return false, "Target outside assigned cell bounds"
    end
    return true
end
```

**No physical barriers** - We don't place walls (would complicate entity placement and pathfinding).

### Force Isolation

Each cell uses a **separate Factorio force** for production statistics:

```lua
-- Create force for cell
local force_name = "cell_" .. cell_index
game.create_force(force_name)

-- Assign agent character to cell's force
agent_character.force = game.forces[force_name]
```

This ensures `get_production_statistics()` returns only production from that cell's agent.

### Cell Reset

Individual cells can be reset without affecting others:

```lua
function reset_cell(cell_index)
    local bounds = storage.cell_bounds[cell_index]

    -- Clear all entities in cell
    clear_entities_in_bounds(bounds)

    -- Reset force production stats
    local force = game.forces["cell_" .. cell_index]
    force.reset_production_statistics()

    -- Respawn resources
    spawn_cell_resources(cell_index)

    -- Reset manual production tracking for agent
    local agent_id = get_agent_in_cell(cell_index)
    if agent_id then
        reset_manual_production_statistics(agent_id)
    end
end
```

## Python Integration

### Cell Assignment via RCON

```python
# When creating agent, request specific cell or auto-assign
result = rcon_helper.run(
    "lab_grid", "create_agent_in_cell",
    {"cell_index": 0, "starting_inventory": {...}}
)
# Returns: {"agent_id": 1, "cell_index": 0, "spawn_position": {...}}
```

### Task Config Extension

```python
@dataclass
class LabGridTaskConfig(TaskConfig):
    """Task config with cell assignment."""
    cell_index: Optional[int] = None  # None = auto-assign
```

### Verification with Cell Bounds

The verification system already works per-agent via force production stats. With force isolation per cell, no changes needed.

### Batch Evaluation Harness

```python
async def run_parallel_evaluation(
    task_key: str,
    num_agents: int,
    max_steps: int = 64,
) -> list[VerificationResult]:
    """Run N agents in parallel on the same task."""

    # 1. Create agents in cells 0..N-1
    agents = []
    for i in range(num_agents):
        agent = await create_agent_in_cell(cell_index=i)
        agents.append(agent)

    # 2. Run all agents in parallel (same game ticks)
    for step in range(max_steps):
        # All agents take one action (LLM calls can be parallel)
        await asyncio.gather(*[
            agent.take_action() for agent in agents
        ])

    # 3. Verify all agents
    results = []
    for agent in agents:
        result = await verify_task(task, RCONSource(rcon), agent.id)
        results.append(result)

    return results
```

## Remote Interface

```lua
remote.add_interface("lab_grid", {
    -- Grid management
    get_grid_config = function()
        return {
            grid_size = GRID_SIZE,
            cell_size = CELL_SIZE,
            total_cells = GRID_SIZE * GRID_SIZE
        }
    end,

    -- Cell management
    get_cell_bounds = function(cell_index) ... end,
    reset_cell = function(cell_index) ... end,
    get_cell_status = function(cell_index) ... end,  -- empty/occupied/agent_id

    -- Agent-cell operations
    create_agent_in_cell = function(args) ... end,
    get_agent_cell = function(agent_id) ... end,
    teleport_agent_to_cell_center = function(agent_id) ... end,

    -- Resource placement (per-cell)
    spawn_cell_resources = function(cell_index) ... end,
    clear_cell = function(cell_index) ... end,

    -- Bulk operations
    reset_all_cells = function() ... end,
    get_all_cell_status = function() ... end,
})
```

## File Structure

```
src/factorio/scenarios/lab-grid/
├── control.lua              # Main scenario logic
├── grid.lua                 # Grid layout calculations
├── cell.lua                 # Cell management (spawn, reset, bounds)
├── resources.lua            # Resource patch templates
├── agent_binding.lua        # Agent-cell assignment
├── info.json
└── description.json
```

## Implementation Phases

### Phase 1: Basic Grid
- [ ] Grid layout calculations
- [ ] Lab tile generation per cell
- [ ] Cell bounds tracking
- [ ] Basic remote interface

### Phase 2: Resource Placement
- [ ] Resource patch templates
- [ ] Per-cell resource spawning
- [ ] Oil/water placement

### Phase 3: Agent Integration
- [ ] Force-per-cell isolation
- [ ] Agent-cell assignment
- [ ] Movement constraint enforcement
- [ ] Cell reset with agent handling

### Phase 4: Python Integration
- [ ] RCON helper methods for lab_grid
- [ ] Task config with cell assignment
- [ ] Batch evaluation harness

### Phase 5: Verification Integration
- [ ] Verify force isolation works
- [ ] Test parallel verification
- [ ] Performance benchmarking

## Configuration Options

```lua
-- Configurable via remote interface or scenario settings
LAB_GRID_CONFIG = {
    -- Grid dimensions (chunk-aligned)
    grid_size = 8,                    -- 8×8 = 64 cells
    play_area_chunks = 4,             -- 4×4 chunks = 128×128 tiles
    gap_chunks = 1,                   -- 1 chunk = 32 tiles between cells

    -- Resource patch configuration (offsets from cell origin)
    resource_patches = {
        {name = "iron-ore",   offset = {16, 16},  size = 8, amount = 50000},
        {name = "copper-ore", offset = {48, 16},  size = 8, amount = 50000},
        {name = "coal",       offset = {16, 48},  size = 8, amount = 50000},
        {name = "stone",      offset = {48, 48},  size = 8, amount = 50000},
    },

    -- Fluid resources
    water_offset = {16, 96},          -- 5×5 water tiles
    oil_offsets = {{80, 96}, {88, 96}, {96, 96}},  -- 3 crude-oil wells

    -- Spawn point (relative to cell origin)
    spawn_offset = {64, 64},          -- Center of play area

    -- Technology preset
    all_technologies_researched = true,
}
```

## Comparison: FLE vs Lab Grid

| Aspect | FLE (1 server/agent) | Lab Grid (1 server, 64 cells) |
|--------|---------------------|-------------------------------|
| RAM per agent | ~200MB | ~0 (shared) |
| Startup time | ~5s per container | 0 (cells pre-exist) |
| Visual debugging | One at a time | All 64 simultaneously |
| Game tick sync | Independent | Synchronized |
| Resource fairness | Seed-dependent | Identical by design |
| Max parallel | Limited by hardware | 64 in single 1280×1280 map |
| Play area per agent | Variable | 128×128 tiles (4×4 chunks) |
| Total map size | N/A | 1280×1280 tiles (40×40 chunks) |

## Reference: Factorio's team-production Scenario

The built-in `team-production` scenario (`base/script/team-production/`) implements a very similar pattern:

**Key patterns we're adapting:**

| Pattern | team-production | lab-grid |
|---------|----------------|----------|
| Area layout | 8 teams in ring around origin | 8×8 grid of cells |
| Force isolation | One force per team color | One force per cell |
| Build restriction | `on_built_entity` destroys out-of-bounds | Same |
| Area bounds | `is_in_area(entity, force)` | `is_in_cell(position, cell_index)` |
| Tile creation | `create_tiles(distance, tiles, offset_x, offset_y)` | Similar with cell offset |
| Entity placement | `recreate_entities(entities, offset_x, offset_y, force)` | Similar for resources |
| Map size | `surface.map_gen_settings.width/height` | Same approach |

**Files to reference:**
- `base/script/team-production/team_production.lua` - Main logic, force creation, area bounds
- `base/script/team-production/map_scripts.lua` - Tile/entity creation with offsets
- `base/script/team-production/config.lua` - Starting inventories, task items

## Open Questions

1. **Force limit**: team-production uses 8 forces. We need 64. Factorio likely supports 100+, but need to verify.
2. **Performance at scale**: 64 agents vs team-production's 8. Need benchmarking.
3. **Snapshot overhead**: Does snapshot mod handle 64 cells efficiently?
4. **Oil placement**: team-production places resources programmatically - we can do same for crude-oil.

## Related Documents

- [TASK_VERIFICATION.md](./TASK_VERIFICATION.md) - Verification system that will use this
- [test-ground control.lua](../../src/factorio/scenarios/test-ground/control.lua) - Reference implementation
