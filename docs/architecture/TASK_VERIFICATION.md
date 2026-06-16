# Task Verification System

The task verification system provides a deterministic way to measure agent performance in FactoryVerse. It answers the question: "Did the agent build automation, or did they just hand-craft everything?"

## Core Insight

Factorio tracks production statistics at the force (team) level. When an agent crafts items by hand or mines resources manually, we track those separately. The difference tells us what came from automation:

```
automation_produced = force_output - manual_crafted - manual_mined
```

This is pure arithmetic—no heuristics, no holdout periods, no plateau detection.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Task Definitions (src/FactoryVerse/tasks/definitions/)         │
│  - 24 throughput tasks (iron-plate, circuits, science packs)   │
│  - Dataclass configs with verification criteria                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Task Registry (singleton)                                      │
│  - Lookup by task_key: "iron_plate_throughput"                 │
│  - List tasks by type: THROUGHPUT, UNBOUNDED, FREEPLAY         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Verification Sources (pluggable)                               │
│  - RCONSource: Query Lua storage directly                      │
│  - JSONLSource: Read snapshot files (offline)                  │
│  - DuckDBSource: Query loaded database                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Verification Engine                                            │
│  - calculate_automation_score(source, agent_id, item)          │
│  - verify_task(task, source, agent_id) → VerificationResult    │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Get a Task from the Registry

```python
from FactoryVerse.tasks import TaskRegistry

registry = TaskRegistry.get()
task = registry.get_task("iron_plate_throughput")

print(task.goal_description)
# "Build an automated factory that produces at least 16 iron-plate..."

print(task.verification.target_item)      # "iron-plate"
print(task.verification.min_automation_produced)  # 16
```

### Verify Task Completion

```python
from FactoryVerse.tasks import RCONSource, verify_task

# Create source from existing RCON connection
source = RCONSource(rcon_helper)

# Verify the task
result = await verify_task(task, source, agent_id=1)

print(result.success)              # True/False
print(result.automation_produced)  # Items from machines
print(result.manual_produced)      # Items from hand-crafting
print(result.automation_ratio)     # e.g., 0.95 (95% automated)
```

### List Available Tasks

```python
from FactoryVerse.tasks import list_tasks, TaskType

# All tasks
all_tasks = list_tasks()  # 24 tasks

# Filter by type
throughput_tasks = list_tasks(TaskType.THROUGHPUT)
```

## Task Types

| Type | Description | Verification |
|------|-------------|--------------|
| `THROUGHPUT` | Produce N items via automation | Must meet `min_automation_produced` quota |
| `UNBOUNDED` | Maximize production | Always passes, records stats |
| `FREEPLAY` | Free exploration | Always passes |

## Verification Sources

### RCONSource

Queries Lua storage directly via RCON. Use when:
- Verifying during gameplay (game can be paused)
- Testing verification logic
- Real-time feedback

```python
from FactoryVerse.tasks import RCONSource

source = RCONSource(rcon_helper)
result = await verify_task(task, source, agent_id=1)
```

### JSONLSource

Reads from snapshot JSONL files. Use when:
- Offline/batch evaluation
- Replaying past runs
- CI/CD testing without Factorio

```python
from pathlib import Path
from FactoryVerse.tasks import JSONLSource

source = JSONLSource(Path("snapshots/run_001.jsonl"))
result = await verify_task(task, source, agent_id=1)
```

### DuckDBSource

Queries loaded DuckDB database. Use when:
- Complex SQL-based analysis
- Aggregating across multiple agents
- Integration with existing database workflows

```python
from FactoryVerse.tasks import DuckDBSource

source = DuckDBSource(db_connection)
result = await verify_task(task, source, agent_id=1)
```

## Task Configuration

Tasks are defined as frozen dataclasses:

```python
from FactoryVerse.tasks import TaskConfig, TaskType, VerificationCriteria

task = TaskConfig(
    task_key="my_custom_task",
    task_type=TaskType.THROUGHPUT,
    goal_description="Build a factory that produces 100 iron gears.",
    verification=VerificationCriteria(
        target_item="iron-gear-wheel",
        min_automation_produced=100,
        max_manual_ratio=0.1,  # Optional: max 10% manual allowed
    ),
    starting_inventory={"iron-plate": 200, "assembling-machine-1": 5},
    all_technologies_researched=True,
    max_trajectory_steps=64,
)
```

### VerificationCriteria Fields

| Field | Type | Description |
|-------|------|-------------|
| `target_item` | `str` | Factorio item name (e.g., "iron-plate") |
| `min_automation_produced` | `int` | Minimum items from automation |
| `max_manual_ratio` | `float?` | Optional cap on manual/total ratio |

## Verification Result

```python
@dataclass
class VerificationResult:
    success: bool                    # Did task pass?
    automation_produced: int         # Items from machines
    manual_produced: int             # Items from hand-craft/mine
    force_total: int                 # Total force output
    measured_at_tick: int            # Game tick
    task_key: str                    # Which task
    failure_reason: Optional[str]    # Why it failed (if applicable)

    @property
    def automation_ratio(self) -> float: ...  # automation / total

    @property
    def manual_ratio(self) -> float: ...      # manual / total
```

## Tier 5 Integration

When a task is loaded via Tier 5 (Specification), the goal description is automatically injected into the system prompt:

```python
# In environment config
config = EnvironmentConfig(
    tier5=SpecificationConfig(
        task_name="iron_plate_throughput",  # Loaded from registry
        include_api_reference=True,
    )
)

# System prompt will include:
# ## Task
# Build an automated factory that produces at least 16 iron-plate...
#
# ### Success Criteria
# - Target item: `iron-plate`
# - Minimum automation-produced: 16
```

Access the loaded task config:

```python
task_config = environment.tier5.task_config
```

## Available Throughput Tasks (24)

### Circuits
- `electronic_circuit_throughput`
- `advanced_circuit_throughput`
- `processing_unit_throughput`

### Science Packs
- `automation_science_pack_throughput`
- `logistics_science_pack_throughput`
- `chemical_science_pack_throughput`
- `military_science_pack_throughput`
- `production_science_pack_throughput`
- `utility_science_pack_throughput`

### Materials
- `iron_plate_throughput`
- `steel_plate_throughput`
- `plastic_bar_throughput`
- `battery_throughput`
- `engine_unit_throughput`
- `low_density_structure_throughput`

### Components
- `iron_gear_wheel_throughput`
- `inserter_throughput`

### Raw Resources
- `iron_ore_throughput`
- `crude_oil_throughput`

### Chemicals
- `petroleum_gas_throughput`
- `sulfuric_acid_throughput`
- `sulfur_throughput`

### Military
- `piercing_round_throughput`
- `stone_wall_throughput`

## Lua Side: Manual Production Tracking

The verification system relies on Lua-side tracking in `fv_embodied_agent`:

```lua
-- In crafting.lua - tracks hand-crafted items
storage.agent_manual_crafted[agent_id][item_name] = count

-- In mining.lua - tracks hand-mined items
storage.agent_manual_mined[agent_id][item_name] = count
```

RCON methods:
- `get_production_statistics()` - Force-level output/input
- `get_manual_production_statistics()` - Agent's manual crafted/mined
- `reset_manual_production_statistics()` - Clear counters for new task

## Design Decisions

### Why No Holdout Periods?

FLE used a "holdout" approach: wait 60 seconds, measure throughput, repeat until plateau. This is:
- Non-deterministic (timing-dependent)
- Slow (requires game time to pass)
- Complex (plateau detection heuristics)

Our approach: just query the counters. Factorio is deterministic—if you built automation, the stats reflect it immediately.

### Why Separate Manual Tracking?

Force production statistics include everything: machines, hand-crafting, mining. By tracking manual actions separately in Lua, we can compute automation with simple subtraction.

### Why Pluggable Sources?

Different use cases need different data access:
- **Development**: RCON for immediate feedback
- **Batch evaluation**: JSONL for offline processing
- **Analysis**: DuckDB for SQL queries

The `VerificationSource` protocol makes this transparent to verification logic.

## File Structure

```
src/FactoryVerse/tasks/
├── __init__.py                    # Public API exports
├── base.py                        # TaskConfig, VerificationCriteria, etc.
├── sources.py                     # RCONSource, JSONLSource, DuckDBSource
├── verification.py                # calculate_automation_score, verify_task
├── registry.py                    # TaskRegistry singleton
└── definitions/
    ├── __init__.py                # Exports ALL_TASKS
    ├── common.py                  # LAB_STARTING_INVENTORY
    └── throughput_tasks.py        # 24 throughput task definitions
```

## Testing

```bash
# Run verification unit tests
uv run pytest tests/unit/test_task_verification.py -v
```

Tests cover:
- Base type validation
- Verification arithmetic
- Registry operations
- Mock source workflows
- Edge cases (negative automation, zero production, etc.)
