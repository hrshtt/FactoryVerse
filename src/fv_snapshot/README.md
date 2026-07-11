# fv_snapshot

Factorio mod for game state serialization and agent statistics logging. Provides the "vision" layer for AI agents by writing map state to disk, enabling DuckDB spatial queries as the agent's equivalent of a human player's map view.

## Overview

The mod serves two primary purposes:

1. **Map Snapshotting**: Serializes entity state to JSONL files organized by chunk coordinates, enabling map-wide spatial queries via DuckDB
2. **Agent Statistics Logging**: Tracks agent production, crafting, and mining statistics for task verification

## Architecture

```
fv_snapshot/
├── control.lua              # Event dispatcher and initialization
├── settings.lua             # Mod settings (UDP port, orchestration mode)
├── info.json                # Mod metadata
├── fv_filters.json          # Entity type filters for snapshotting
├── game_state/
│   ├── Map.lua              # Chunk-based snapshot orchestration
│   ├── Entities.lua         # Entity serialization and status tracking
│   ├── Resource.lua         # Resource tile gathering
│   ├── Power.lua            # Power network snapshots
│   ├── Research.lua         # Research state snapshots
│   └── Agents.lua           # Agent statistics (production/crafting/mining)
└── utils/
    ├── snapshot.lua         # File I/O helpers, sequence numbers
    ├── udp_payloads.lua     # UDP notification payloads
    └── forces.lua           # Force tracking utilities
```

## Output Directory Structure

```
factoryverse/
├── snapshots/                          # Map state (chunk-organized)
│   └── {chunk_x}/{chunk_y}/
│       ├── entities-init.jsonl         # Initial entity snapshot
│       ├── entities-updates.jsonl      # Entity operations log
│       ├── resources-init.jsonl        # Ore deposits
│       ├── water-init.jsonl            # Water tiles
│       ├── trees_rocks-init.jsonl      # Natural resources
│       ├── ghosts-init.jsonl           # Ghost entities
│       └── ghosts-updates.jsonl        # Ghost operations log
│
└── agent-snapshots/                    # Agent statistics (per-agent)
    └── {agent_id}/
        ├── production-statistics.jsonl # Force-level production (polled)
        ├── crafting-statistics.jsonl   # Manual crafting (event-driven)
        └── mining-statistics.jsonl     # Manual mining (event-driven)
```

## Orchestration Modes

The mod supports three orchestration modes for controlling when map snapshotting occurs:

### AUTO (Default)
- Snapshots immediately when chunks are charted via `on_chunk_charted`
- Standard flow: `INITIAL_SNAPSHOTTING` → `MAINTENANCE`
- Backward compatible with existing behavior

### DEFERRED
- Tracks charted chunks but doesn't snapshot until explicitly triggered
- Call `trigger_initial_snapshot()` to start processing queued chunks
- Useful when scenario setup must complete before snapshotting

### SELECTIVE
- Ignores `on_chunk_charted` events entirely for snapshotting
- Only snapshots areas explicitly requested via `snapshot_area(bounds)`
- Essential for lab-grid scenarios where cells are isolated

Configure via mod setting or remote interface:
```lua
-- Via mod settings
settings.global["fv-snapshot-orchestration-mode"].value = "SELECTIVE"

-- Via remote interface
remote.call("map", "set_orchestration_mode", "SELECTIVE")
```

## Remote Interface API

### Map Module (`remote.call("map", ...)`)

| Method | Parameters | Description |
|--------|------------|-------------|
| `get_orchestration_mode` | - | Returns current mode ("AUTO", "DEFERRED", "SELECTIVE") |
| `set_orchestration_mode` | `mode` | Sets orchestration mode at runtime |
| `trigger_initial_snapshot` | - | Queues all deferred chunks for snapshotting |
| `snapshot_area` | `bounds, priority?` | Snapshots chunks within bounding box |
| `re_snapshot_area` | `bounds, priority?` | Clears and re-snapshots area (for cell reset) |
| `get_snapshot_status` | - | Returns current snapshot state machine status |
| `get_system_phase` | - | Returns "INITIAL_SNAPSHOTTING" or "MAINTENANCE" |

**Bounds format:**
```lua
{
    left_top = { x = 0, y = 0 },
    right_bottom = { x = 128, y = 128 }
}
```

### Agents Module (`remote.call("agents", ...)`)

| Method | Parameters | Description |
|--------|------------|-------------|
| `get_agent_snapshot_dir` | - | Returns base directory path |
| `force_snapshot_agent` | `agent_id` | Forces immediate snapshot write for agent |

## Agent Statistics

### Production Statistics (Polled)
- Written every 300 ticks (5 seconds)
- Captures force-level aggregate production from automation
- Includes both input (consumed) and output (produced) items

```jsonl
{"tick": 12000, "agent_id": 1, "force_name": "agent_1", "input": {"iron-ore": 50}, "output": {"iron-plate": 50}}
```

### Crafting Statistics (Event-Driven)
- Written on `on_agent_crafting_completed` custom event from fv_embodied_agent
- Logs exact products received from hand-crafting

```jsonl
{"tick": 5400, "agent_id": 1, "recipe": "iron-gear-wheel", "count_crafted": 10, "products": {"iron-gear-wheel": 10}}
```

### Mining Statistics (Event-Driven)
- Written on `on_agent_mining_completed` custom event from fv_embodied_agent
- Logs products from hand-mining (trees, rocks, ores)

```jsonl
{"tick": 3200, "agent_id": 1, "entity_name": "iron-ore", "mode": "incremental", "reason": "completed", "products": {"iron-ore": 5}}
```

## Integration with fv_embodied_agent

The mod listens to custom events raised by fv_embodied_agent:

| Event | Raised When | Handler |
|-------|-------------|---------|
| `on_agent_crafting_completed` | Agent finishes hand-crafting | Writes crafting-statistics.jsonl |
| `on_agent_mining_completed` | Agent finishes hand-mining with products | Writes mining-statistics.jsonl |

Custom events are accessed via:
```lua
local events = remote.call("custom_events", "get_custom_events")
-- events.on_agent_crafting_completed
-- events.on_agent_mining_completed
```

## DuckDB Synchronization (Python Side)

The Python `SnapshotLoader` class handles:

1. **Initial Load**: Reads all `*-init.jsonl` files into DuckDB tables
2. **Update Replay**: Processes `*-updates.jsonl` in sequence order
3. **Live Sync**: UDP events trigger incremental updates

**Sequence Numbers**: Every operation has a monotonically increasing sequence number. Gaps trigger full rebuild to maintain consistency.

**Flush-Before-Read**: The sync service flushes pending UDP operations before any query to ensure consistency.

**Single Reducer**: Both consumers of the op stream — `SnapshotLoader` (file
replay) and `SyncService` (live UDP) — apply ops through one shared reducer
(`FactoryVerse.game.infra.duckdb.apply_ops`). Identical logical ops must
produce identical DB rows regardless of transport; this is certified by
ledger L1.13 (`scripts/certification/check_replay_parity.py`).

**Provenance Fold Rule (record contract)**: provenance fields (`agent_id`,
`player_id`, `label`, `placed_tick`; ghost `placed_by`) change ONLY via ops
that carry a non-empty `builder` block (build events, relabel, a re-gather's
"pre-existing" stamp). Ops without one — config-change re-serializations,
partial updates — preserve the existing row's provenance. Consequently the
stream is NOT last-line-wins for provenance: any consumer reconstructing
state from the raw JSONL must FOLD each entity's op history under this rule.
Labels are write-once: set at creation, changed only by an explicit
builder-carrying op, destroyed with the entity (a remove deletes the row, so
a same-key re-place starts clean). Provenance completeness is conditional on
the boot epoch: init re-gathers deliberately re-stamp (PROV-1 soft claim).

## Configuration

### Mod Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `fv-snapshot-udp-port` | int | 34400 | UDP port for notifications |
| `fv-snapshot-orchestration-mode` | string | "AUTO" | Orchestration mode |

### Performance Tuning (Map.lua)

```lua
SnapshotConfig = {
    ENTITIES_PER_TICK = 100,      -- Serialization budget per tick
    WRITES_PER_TICK = 5,          -- File writes per tick
    MAX_QUEUE_SIZE = 1000,        -- Maximum pending chunks
}
```

## Usage Examples

### Lab-Grid Scenario Integration

```lua
-- In scenario on_init:
remote.call("map", "set_orchestration_mode", "SELECTIVE")

-- After cell setup:
local cell_bounds = grid.get_play_area_bounds(cell_index)
remote.call("map", "snapshot_area", cell_bounds)

-- On cell reset:
remote.call("map", "re_snapshot_area", cell_bounds)
```

### Waiting for Snapshot Completion (Python)

```python
# Wait for system to reach MAINTENANCE phase
async def wait_for_snapshot_ready():
    while True:
        status = await rcon.call("map", "get_system_phase")
        if status == "MAINTENANCE":
            break
        await asyncio.sleep(0.5)
```

## File Formats

### Entity JSONL Entry
```json
{
  "entity_name": "assembling-machine-1",
  "position": {"x": 10.5, "y": -5.5},
  "direction": 0,
  "bbox": {"min": {"x": 9, "y": -7}, "max": {"x": 12, "y": -4}},
  "recipe": "iron-gear-wheel",
  "agent_id": 1,
  "placed_tick": 1200
}
```

### Update Operation Entry
```json
{
  "sequence": 42,
  "tick": 1500,
  "operation": "created",
  "entity_name": "transport-belt",
  "position": {"x": 15, "y": 20},
  "direction": 2,
  "agent_id": 1
}
```

## Dependencies

- **fv_embodied_agent**: Required for agent statistics (custom events, Agent class)
- **Factorio 2.0+**: Uses modern API features

## Known Limitations

- Map DB not auto-updating on some entity removal scenarios
- Mining resource entities (trees/rocks) removal needs verification in some edge cases
- Ghost placement not fully tested with all entity types
