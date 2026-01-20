# Lab Grid Scenario

A Factorio scenario providing an 8×8 grid of isolated play areas for parallel multi-agent evaluation. Each cell is a self-contained environment where one agent operates independently with its own force, production statistics, and resources.

## Overview

```
┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
│ Cell 0  │ │ Cell 1  │ │ Cell 2  │ │ Cell 3  │ ...
│ 128×128 │ │ 128×128 │ │ 128×128 │ │ 128×128 │
└─────────┘ └─────────┘ └─────────┘ └─────────┘
    32px gap    32px gap    32px gap
┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
│ Cell 8  │ │ Cell 9  │ │ Cell 10 │ │ Cell 11 │ ...
│ 128×128 │ │ 128×128 │ │ 128×128 │ │ 128×128 │
└─────────┘ └─────────┘ └─────────┘ └─────────┘
    ...         ...         ...         ...
```

## Dimensions

| Property | Value | Notes |
|----------|-------|-------|
| Grid Size | 8×8 | 64 total cells |
| Play Area | 128×128 tiles | 4×4 chunks per cell |
| Gap Size | 32 tiles | 1 chunk between cells |
| Cell Size | 160×160 tiles | Play area + gap |
| Total Map | 1280×1280 tiles | 40×40 chunks |

## Features

### Force Isolation
Each cell gets its own Factorio force (`cell_0`, `cell_1`, ... `cell_63`):
- **Independent production statistics** - Each force tracks its own items produced/consumed
- **All technologies researched** - Agents start with full tech tree
- **Friendly relations** - All cell forces are allied (no combat between cells)

### Build Restrictions
Agents can only build within their assigned cell:
- Entities placed outside cell bounds are automatically destroyed
- Characters and items-on-ground are exempt
- Player force can build anywhere (for debugging)

### On-Demand Charting
Cells are charted only when agents are created:
- Prevents overwhelming `fv_snapshot` with 1600 chunk events at startup
- Each agent creation charts only 16 chunks (the cell's play area)
- Keeps initialization fast (~5 seconds)

### Cell Reset
Cells can be reset to initial state while preserving the agent:
- Clears all entities except the character
- Regenerates tiles
- Respawns all resources

## Resources Per Cell

Each cell spawns with identical resources:

| Resource | Position (offset) | Size | Amount |
|----------|------------------|------|--------|
| Iron Ore | (16, 16) | 8×8 | 50,000/tile |
| Copper Ore | (48, 16) | 8×8 | 50,000/tile |
| Coal | (16, 48) | 8×8 | 50,000/tile |
| Stone | (48, 48) | 8×8 | 50,000/tile |
| Water | (16, 96) | 5×5 | - |
| Crude Oil | (80,88,96 @ y=96) | 3 wells | 300,000 each |

## Remote Interface

All functions available via `remote.call("lab_grid", ...)`:

### Grid Information
```lua
-- Get grid configuration
remote.call("lab_grid", "get_config")
-- Returns: {chunk_size, play_area_size, gap_size, cell_size, grid_size, total_cells, map_size}

-- Get cell bounds
remote.call("lab_grid", "get_cell_bounds", cell_index)
-- Returns: {left_top: {x, y}, right_bottom: {x, y}}

-- Get spawn position for a cell
remote.call("lab_grid", "get_spawn_position", cell_index)
-- Returns: {x, y}
```

### Cell Management
```lua
-- Get status of a specific cell
remote.call("lab_grid", "get_cell_status", cell_index)
-- Returns: {cell_index, bounds, spawn_position, entity_count, force_exists, force_name, has_agent, agent_info}

-- Get status of all cells
remote.call("lab_grid", "get_all_cell_status")
-- Returns: {[0] = status, [1] = status, ...}

-- Reset a cell to initial state
remote.call("lab_grid", "reset_cell", cell_index, preserve_agent)
-- Returns: {success, cell_index}

-- Reset all cells
remote.call("lab_grid", "reset_all_cells", preserve_agents)
-- Returns: {success, cells_reset}
```

### Agent Operations
```lua
-- Create an agent in a cell (integrates with fv_embodied_agent)
remote.call("lab_grid", "create_agent_in_cell", {
    cell_index = 0,              -- Optional: auto-assigns if nil
    starting_inventory = {...}   -- Optional: initial items
})
-- Returns: {success, agent_id, cell_index, spawn_position, force_name}

-- Get which cell an agent is in
remote.call("lab_grid", "get_agent_cell", agent_id)
-- Returns: cell_index or nil

-- Manually assign agent to cell
remote.call("lab_grid", "assign_agent_to_cell", agent_id, cell_index)
-- Returns: boolean success

-- Unassign agent from cell
remote.call("lab_grid", "unassign_agent", agent_id)
-- Returns: {success}

-- Find an empty cell
remote.call("lab_grid", "find_empty_cell")
-- Returns: cell_index or nil

-- Teleport agent to their cell's spawn point
remote.call("lab_grid", "teleport_agent_to_cell", agent_id)
-- Returns: {success, position} or {success=false, error}
```

### Force Management
```lua
-- Get force name for a cell
remote.call("lab_grid", "get_cell_force", cell_index)
-- Returns: "cell_N"
```

### Position Utilities
```lua
-- Check if position is within a cell's play area
remote.call("lab_grid", "is_in_play_area", position, cell_index)
-- Returns: boolean

-- Get cell index from world position
remote.call("lab_grid", "get_cell_at_position", position)
-- Returns: cell_index or nil
```

## Usage

### Starting the Server
```bash
uv run fv server start --scenario lab-grid
```

### Creating Agents (via Python)
```python
from FactoryVerse.utils.rcon_utils import create_rcon_client

rcon = create_rcon_client('localhost', 27000, 'factorio', initialize=True)

# Create agent in specific cell
result = rcon.send_command('''
/silent-command rcon.print(helpers.table_to_json(
    remote.call("lab_grid", "create_agent_in_cell", {cell_index = 5})
))
''')

# Create agent in next available cell
result = rcon.send_command('''
/silent-command rcon.print(helpers.table_to_json(
    remote.call("lab_grid", "create_agent_in_cell", {})
))
''')
```

### Resetting a Cell
```python
# Reset cell 5, keeping the agent
rcon.send_command('''
/silent-command remote.call("lab_grid", "reset_cell", 5, true)
''')
```

## File Structure

```
lab-grid/
├── control.lua      # Main scenario script (events, remote interface)
├── grid.lua         # Grid layout constants and position calculations
├── cell.lua         # Cell management (resources, reset, status)
├── description.json # Scenario metadata
└── info.json        # Additional metadata
```

## Cell Index Layout

```
 0  1  2  3  4  5  6  7
 8  9 10 11 12 13 14 15
16 17 18 19 20 21 22 23
24 25 26 27 28 29 30 31
32 33 34 35 36 37 38 39
40 41 42 43 44 45 46 47
48 49 50 51 52 53 54 55
56 57 58 59 60 61 62 63
```

## Integration with fv_snapshot

The scenario is designed to work efficiently with `fv_snapshot`:
- **No bulk charting at startup** - Avoids triggering 1600 `on_chunk_charted` events
- **On-demand charting** - Each cell charted when agent is created (16 chunks)
- **Force-based filtering** - Snapshot queries can filter by cell force

## Technical Notes

### Map Generation
1. Disables Factorio's default terrain generation via `map_gen_settings`
2. Generates all 1600 chunks with correct tiles (dirt-1 for play areas, out-of-map for gaps)
3. Handles pre-generated spawn chunks by overwriting them
4. Fallback `on_chunk_generated` handler for any late chunk generation

### Performance
- Map initialization: ~5 seconds for 64 cells
- Agent creation: 15-50ms per agent
- Cell reset: ~70ms per cell
