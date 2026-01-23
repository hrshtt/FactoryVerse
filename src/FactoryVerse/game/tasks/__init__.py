"""Task verification system for FactoryVerse.

This package provides:
- Task definitions (throughput, unbounded, freeplay)
- Verification sources (RCON, JSONL, DuckDB)
- Verification engine for validating task completion
- Task registry for looking up tasks by key

Example usage:

    from FactoryVerse.tasks import (
        TaskRegistry,
        RCONSource,
        verify_task,
    )

    # Get a task
    registry = TaskRegistry.get()
    task = registry.get_task("iron_plate_throughput")

    # Verify completion
    source = RCONSource(rcon_helper)
    result = await verify_task(task, source, agent_id=1)

    print(f"Success: {result.success}")
    print(f"Automation: {result.automation_produced}")
"""

# Base types
from .base import (
    TaskType,
    TaskConfig,
    VerificationCriteria,
    VerificationResult,
)

# Registry
from .registry import (
    TaskRegistry,
    get_task,
    list_tasks,
    task_exists,
)

# Verification sources
from .sources import (
    VerificationSource,
    ProductionStats,
    ManualStats,
    RCONSource,
    JSONLSource,
    DuckDBSource,
)

# Verification engine
from .verification import (
    calculate_automation_score,
    verify_task,
    verify_multiple_items,
)

__all__ = [
    # Base types
    "TaskType",
    "TaskConfig",
    "VerificationCriteria",
    "VerificationResult",
    # Registry
    "TaskRegistry",
    "get_task",
    "list_tasks",
    "task_exists",
    # Sources
    "VerificationSource",
    "ProductionStats",
    "ManualStats",
    "RCONSource",
    "JSONLSource",
    "DuckDBSource",
    # Verification
    "calculate_automation_score",
    "verify_task",
    "verify_multiple_items",
]
