# Factorio Verse Tick Events Analysis

## Overview

This document summarizes all `on_tick` and `on_nth_tick` event handlers in the Factorio Verse mod, their focus, state machines, and identifies gaps in UDP notifications.

### Key Architectural Principle

**Event-Centric State Sync**: The system operates on the principle that actions are decoupled from entity operations. Entity operations represent "what changed on the map" and are triggered by in-game events, not actions. Actions have their own lifecycle tracked separately for action awaiting and logging. DB sync listens to entity operations and file IO notifications, not action completions.

## Event Registration Architecture

Events are aggregated in `control.lua` from modules:
- `Agents` - Agent state processing
- `Entities` - Entity lifecycle and status tracking
- `Resource` - Resource depletion handling
- `Map` - Chunk snapshotting
- `Power` - Power statistics
- `Research` - Research management (no tick handlers)

## on_tick Handlers

### 1. Agents.on_tick (Every Tick)

**Focus**: Process all agent state machines and send action lifecycle UDP notifications

**State Machines Processed**:
- **Walking State Machine** (`Agent:process_walking()`)
  - Tracks pathfinding progress
  - Monitors waypoint completion
  - Detects arrival at goal
  - Sends `status: "progress"` updates during walking
  - Sends `status: "completed"` when goal reached
  - Sends `status: "cancelled"` if walking stopped

- **Mining State Machine** (`Agent:process_mining()`)
  - Tracks mining progress (incremental vs deplete modes)
  - Monitors entity depletion
  - Tracks count progress for incremental mining
  - Sends `status: "progress"` with count updates
  - Sends `status: "completed"` when target reached or entity depleted
  - Sends `status: "cancelled"` if mining stopped
  - Note: Entity destruction from mining triggers separate entity operation event (not action-driven)

- **Crafting State Machine** (`Agent:process_crafting()`)
  - Tracks queued crafting recipes
  - Monitors recipe completion
  - Sends `status: "queued"` when recipe enqueued
  - Sends `status: "completed"` when recipe finishes
  - Sends `status: "cancelled"` if recipe dequeued

**UDP Notifications Sent**:
- Action lifecycle events via `snapshot.send_action_completion_udp()`
  - Includes: `action_id`, `agent_id`, `action_type`, `status`, `category`, `rcon_tick`, `completion_tick`, `success`, `result`
  - Categories: `walking`, `mining`, `crafting`, `entity_ops`
  - Note: These are for action awaiting/logging, NOT for DB sync

**Architectural Note**:
- Actions are decoupled from entity operations
- Entity operations (created, destroyed, etc.) are triggered by in-game events, not actions
- Action lifecycle is tracked separately for action awaiting and logging purposes
- DB sync listens to entity operations, not action completions

**Gaps Identified**:
- ❌ No `status: "started"` notification - only `queued`, `progress`, `completed`, `cancelled`
- ❌ No notification when agent entity becomes invalid
- ❌ No pathfinding completion notification (pathfinding handled internally)

### 2. Map._on_tick_snapshot_chunks (Every Tick)

**Focus**: Process chunk snapshotting using a state machine spread across multiple ticks

**State Machine Phases**:
1. **IDLE** → Find next chunk needing snapshot
2. **FIND_ENTITIES** → Gather all entities/resources/tiles (one tick, expensive)
3. **SERIALIZE** → Convert to JSON strings (batched across ticks)
4. **WRITE** → Write files to disk (batched, most expensive)
5. **COMPLETE** → Mark chunk as snapshotted, reset state

**UDP Notifications Sent**:
- `chunk_init_complete` when `entities_init.jsonl` is written
- `file_created` for: `resource`, `water`, `trees_rocks`, `entities_init`, `ghosts_init`
- File paths included in notifications

**Gaps Identified**:
- ❌ **CRITICAL**: No snapshot state payloads for phase transitions
- ❌ No notification when chunk snapshotting **starts** (only when complete)
- ❌ No notification for snapshot phase transitions (IDLE → FIND_ENTITIES → SERIALIZE → WRITE → COMPLETE)
- ❌ No notification if snapshotting fails or is interrupted
- ❌ No notification for chunk snapshot state (which chunk is being processed, progress)
- ❌ Python cannot orchestrate DB loads (must block until COMPLETE state)

## on_nth_tick Handlers

### 1. Entity Status Tracking (Every 60 Ticks)

**Location**: `control.lua` (aggregated from Map + Entities)

**Focus**: Track entity status changes and dump to disk

**Process**:
1. Get all charted chunks via `Map.get_charted_chunks()`
2. Track entity status for each chunk via `Entities.track_all_charted_chunk_entity_status()`
3. Send UDP `status_snapshot` with status records
4. Dump status to disk via `Entities.dump_status_to_disk()`

**UDP Notifications Sent**:
- `status_snapshot` event with `tick` and `status_records` map

**File Operations**:
- Status dump written to disk via `Entities.dump_status_to_disk()`
- File path: `factoryverse/status/status-{tick}.jsonl`

**Gaps Identified**:
- ✅ Status snapshots are sent (good)
- ❌ No file IO notification when status dump file is written to disk
- ❌ No way to know which entities changed status (only new/changed records included)
- Note: Status files are queried on-demand by Python, not synced to DB

### 2. Power Statistics (Every 300 Ticks)

**Location**: `Power._on_nth_tick_global_power_snapshot()`

**Focus**: Snapshot global power network statistics (periodic append)

**Process**:
1. Get global electric network statistics
2. Write to `factoryverse/snapshots/global_power_statistics.jsonl` (append mode)

**File Operations**:
- Power statistics appended to `factoryverse/snapshots/global_power_statistics.jsonl` (append mode)

**UDP Notifications Sent**:
- ❌ **NONE** - No file IO notification when file is appended

**Gaps Identified**:
- ❌ No file IO notification when power statistics are appended
- ❌ Python must poll file to detect new entries
- Note: File is append-only, Python should track last read position or use file IO notifications

### 3. Agent Production Statistics (Not Currently Registered)

**Location**: `Agents._on_nth_tick_agent_production_snapshot()`

**Focus**: Snapshot agent production statistics per agent (periodic append)

**Process**:
1. Iterate all agents
2. Get production statistics for each agent
3. Write to `factoryverse/snapshots/{agent_id}/production_statistics.jsonl` (append mode)

**File Operations**:
- Agent production statistics appended to `factoryverse/snapshots/{agent_id}/production_statistics.jsonl` (append mode)

**UDP Notifications Sent**:
- ❌ **NONE** - No file IO notification when file is appended
- ❌ **NOT REGISTERED** - Function exists but not in `get_events()` return value

**Gaps Identified**:
- ❌ **CRITICAL**: Function not registered (dead code)
- ❌ No file IO notification when agent production stats are appended
- ❌ Python must poll file to detect new entries
- Note: File is append-only, Python should track last read position or use file IO notifications

## Defined Event Handlers

### 1. Entities Disk Write Snapshot Events

**Events Registered**:
- `on_built_entity` → `_on_entity_built()` → `write_entity_snapshot()`
- `script_raised_built` → `_on_entity_built()` → `write_entity_snapshot()`
- `script_raised_destroy` → `_on_entity_destroyed()` → `_delete_entity_snapshot()`
- `on_entity_settings_pasted` → `_on_entity_settings_pasted()` → `write_entity_snapshot()`
- `EntityInterface.on_entity_configuration_changed` → `_on_entity_configuration_changed()` → `write_entity_snapshot()`

**UDP Notifications Sent**:
- `entity_operation` with `op: "upsert"` or `op: "remove"`
- Includes full entity data for upserts
- Includes chunk coordinates, entity_key, entity_name, position

**Architectural Note**:
- Entity operations are triggered by in-game events (`on_built_entity`, `script_raised_destroy`, etc.)
- These are independent of actions - they represent "what changed on the map"
- Agent actions that modify entities should trigger equivalent events (agent event equivalents needed)

**Gaps Identified**:
- ✅ Entity operations are well-notified for created/destroyed
- ❌ Operation types limited to `upsert`/`remove` - missing `rotated` and `configuration_changed`
- ❌ No notification for `on_player_mined_entity` (commented out in code) - needs agent equivalent
- ❌ No notification for entity rotation changes (separate operation type needed)
- ❌ No notification for entity inventory changes (only configuration changes tracked)
- ❌ Agent actions that modify entities may not trigger entity operations (need agent event equivalents)

### 2. Resource Disk Write Snapshot Events

**Events Registered**:
- `on_resource_depleted` → `_on_resource_depleted()` → `_rewrite_chunk_resources()`

**Process**:
1. Get chunk coordinates from depleted resource
2. Rewrite entire chunk's resource files:
   - `resources_init.jsonl` (ore tiles)
   - `water_init.jsonl` (water tiles)
   - `trees_rocks_init.jsonl` (trees and rocks)

**UDP Notifications Sent**:
- `file_updated` for each rewritten file type
- Includes chunk coordinates and file path

**Architectural Note**:
- Resource tiles are overwritten (not incremental) - this is by design
- When a resource tile is depleted, entire chunk's resource files are rewritten
- Python syncs resource tiles on file write notification (full chunk reload)

**Gaps Identified**:
- ✅ File updates are notified
- ❌ File IO operation type not distinguished (`written` vs `appended`)
- ❌ No precise change information (which resource was depleted, how much remains)
- ❌ File rewrite is all-or-nothing (entire chunk rewritten, not incremental)
- Note: Full chunk reload is acceptable - resource tiles are relatively small per chunk

### 3. Map Disk Write Snapshot Events

**Events Registered**:
- `on_chunk_charted` (player charting) → `_on_chunk_charted()` → `mark_chunk_needs_snapshot()`
- `Agent.on_chunk_charted` (agent charting) → `_on_agent_chunk_charted()` → `mark_chunk_needs_snapshot()`

**Process**:
1. Mark chunk as needing snapshot
2. Chunk will be processed by `_on_tick_snapshot_chunks()` state machine

**UDP Notifications Sent**:
- ❌ **NONE** - Chunk charted events only mark chunks for snapshotting
- ❌ No immediate notification when chunk is charted
- ❌ Only notified when chunk snapshot completes (via `chunk_init_complete`)

**Gaps Identified**:
- ❌ **CRITICAL**: No UDP notification when chunk is charted
- ❌ Python cannot know a new chunk was charted until snapshot completes
- ❌ No way to track charting progress (chunk charted → snapshot queued → snapshot in progress → snapshot complete)

### 4. Agents Defined Events

**Events Registered**:
- `on_script_path_request_finished` → Handle pathfinding completion

**Process**:
1. Match path_id to agent's walking.path_id
2. Store path in agent.walking.path
3. Set progress to 1

**UDP Notifications Sent**:
- ❌ **NONE** - Pathfinding completion handled internally
- ❌ No notification when pathfinding completes or fails

**Gaps Identified**:
- ❌ No notification for pathfinding completion/failure
- ❌ Python cannot track pathfinding progress

## Architectural Understanding

### Core Design Principle: Event-Centric State Sync

The system operates on a fundamental pivot: **actions are decoupled from entity operations**. 

- **Entity Operations** are independent events triggered by in-game events (`on_built_entity`, `script_raised_destroy`, etc.) and their agent equivalents. These represent "what changed on the map" and are the primary source of truth for DB sync.

- **Actions** have their own lifecycle (started, progress, cancelled, completed) and are tracked separately for action awaiting and logging. They do NOT directly trigger entity operations.

- **DB Sync** only cares about entity operations payloads and resource tile write payloads. Actions are not the framing for external state sync.

### Payload Categories

The UDP notification system needs to support five distinct payload categories:

1. **Entity Operations** - Map state changes (created, destroyed, rotated, configuration_changed)
2. **Snapshot State** - Chunk snapshotting orchestration (IDLE, FIND_ENTITIES, SERIALIZE, WRITE, COMPLETE)
3. **File IO** - Disk write operations (written, appended)
4. **Actions** - Action lifecycle (started, progress, cancelled, completed)
5. **Game Events** - In-game events (chunk_charted, etc.)

## Summary of Notification Gaps

### Critical Gaps: Entity Operations

1. **Entity Operation Types**
   - Current: Only `upsert` and `remove` operations
   - Gap: Missing `rotated` and `configuration_changed` operation types
   - Impact: Python cannot track entity orientation or configuration changes independently
   - Note: `on_player_mined_entity` is commented out - needs agent equivalent

2. **Entity Operation Independence**
   - Current: Entity operations are tied to action completion flow
   - Gap: Entity operations should be triggered by in-game events, not actions
   - Impact: DB sync cannot distinguish between action-driven and event-driven changes
   - Required: Agent event equivalents for all in-game entity events

### Critical Gaps: Snapshot Orchestration

3. **Snapshot State Tracking**
   - No notification when chunk snapshotting starts (only when complete)
   - No notification for phase transitions (IDLE → FIND_ENTITIES → SERIALIZE → WRITE → COMPLETE)
   - No notification if snapshotting fails or is interrupted
   - Impact: Python cannot orchestrate DB loads (must block until COMPLETE state)
   - Impact: Cannot track which chunk is being processed or snapshot progress

4. **Chunk Charted Events**
   - No notification when chunk is charted (only when snapshot completes)
   - Impact: Python cannot react to new charted chunks immediately
   - Impact: Cannot track charting progress (chunk charted → snapshot queued → snapshot in progress → snapshot complete)

### Critical Gaps: File IO Notifications

5. **File Write Notifications**
   - Status dump files: No notification when written (every 60 ticks)
   - Power statistics: No notification when appended (every 300 ticks)
   - Agent production stats: No notification when appended (not even registered)
   - Impact: Python must poll files to detect changes
   - Impact: Cannot track when append-only files have new entries

6. **File Operation Types**
   - Current: Only `file_created` and `file_updated` events
   - Gap: Missing distinction between `written` (overwrite) and `appended` (append-only) operations
   - Impact: Python cannot optimize sync strategy (full reload vs incremental append)

### Critical Gaps: Action Lifecycle

7. **Action Start Events**
   - No `status: "started"` notification
   - Only `queued`, `progress`, `completed`, `cancelled`
   - Impact: Python cannot distinguish between queued and actually started
   - Impact: Action awaiting cannot track true action lifecycle

8. **Pathfinding Events**
   - No notification when pathfinding completes or fails
   - Impact: Python cannot track pathfinding progress
   - Impact: Action awaiting for walking actions cannot track pathfinding phase

### Medium Priority Gaps

9. **Resource Depletion Details**
   - File rewrite notifications don't specify which resource was depleted
   - Entire chunk file rewritten (all-or-nothing, not incremental)
   - Impact: Python must read entire file to know what changed
   - Note: This is by design (resource tiles are overwritten, not tracked incrementally)

10. **Entity Inventory Changes**
    - No notification for inventory item changes (only configuration changes)
    - Impact: Python cannot track inventory state changes
    - Note: May not be needed if status files are queried on-demand

### Low Priority Gaps

11. **Agent Entity Invalid**
    - No notification when agent character becomes invalid
    - Impact: Python might not know agent died
    - Note: Could be handled via entity destroyed operation

## Recommendations

### High Priority: Refactor UDP Payload System

1. **Create Unified Payload Module**
   - Create `utils/udp_payloads.lua` module for consistent payload creation
   - All event handlers and state machines use this module to structure payloads
   - Ensures consistent API schema for external DB sync
   - Provides single source of truth for payload structure

2. **Entity Operations Payloads**
   - Expand operation types: `created`, `destroyed`, `rotated`, `configuration_changed`
   - Trigger entity operations from in-game events, not actions
   - Create agent event equivalents for all in-game entity events
   - Ensure entity operations are independent of action lifecycle

3. **Snapshot State Payloads**
   - Send `snapshot_state` payload on every phase transition
   - Include: `state` (IDLE, FIND_ENTITIES, SERIALIZE, WRITE, COMPLETE), `chunk`, `tick`, optional `progress`
   - Allows Python to orchestrate DB loads (block until COMPLETE)
   - Enables tracking of snapshot progress per chunk

4. **File IO Payloads**
   - Distinguish `written` (overwrite) vs `appended` (append-only) operations
   - Send notifications for all file writes: status dumps, power stats, agent stats
   - Include: `operation` (written/appended), `file_type`, `chunk`, `tick`, `file_path`, `entry_count`
   - Enables Python to optimize sync strategy

5. **Chunk Charted Events**
   - Send `chunk_charted` payload immediately when chunk is charted
   - Include: `chunk`, `tick`, `charted_by` (player/agent), `snapshot_queued` (boolean)
   - Enables Python to react to new charted chunks immediately

### High Priority: Action Lifecycle

6. **Action Start Notification**
   - Send `action` payload with `status: "started"` when action actually begins
   - Distinguish from `queued` state (action accepted but not yet executing)
   - Enables proper action lifecycle tracking

7. **Pathfinding Completion**
   - Send `action` payload or separate `pathfinding` payload when pathfinding completes/fails
   - Include: `agent_id`, `path_id`, `success`, `path_length` (if successful)
   - Enables tracking of pathfinding phase in walking actions

### Medium Priority

8. **Status Service Design**
   - Status files are queried on-demand (not synced to DB)
   - Python status service reads latest status from disk based on query
   - Agents can subscribe to status reports for notifications
   - Status snapshots remain as-is (UDP notification for file write is sufficient)

9. **Resource Tile Sync Strategy**
   - Resource tiles are overwritten (not incremental) - this is by design
   - Python syncs resource tiles on `file_written` notification
   - Full chunk reload is acceptable (resource tiles are relatively small per chunk)
   - No need for precise change tracking (file is source of truth)

### Implementation Notes

- **Global State Tracking**: Snapshot state machine needs global state tracking to orchestrate DB usage
- **Consistent Updates**: All payloads must follow consistent schema for external DB sync
- **Complete Coverage**: All map state changes must emit entity operations (not just action-driven ones)
- **Agent Equivalents**: All in-game events that trigger entity operations need agent equivalents
- **DB Load Blocking**: Python DB load should block if server snapshot state is not COMPLETE for target chunks

