"""Base types for task definitions and verification.

This module provides the foundational types for the task verification system:
- TaskType: Enum for different task categories
- VerificationCriteria: What to verify (target item, quota, constraints)
- TaskConfig: Complete task definition
- VerificationResult: Outcome of verification
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TaskType(Enum):
    """Types of tasks supported by the verification system."""

    THROUGHPUT = "throughput"  # Produce N items via automation
    UNBOUNDED = "unbounded"  # Maximize production (no quota)
    FREEPLAY = "freeplay"  # No verification criteria


@dataclass(frozen=True)
class VerificationCriteria:
    """Defines what to verify for a task.

    Attributes:
        target_item: The item name to measure (e.g., "iron-plate")
        min_automation_produced: Minimum items that must come from automation
        max_manual_ratio: Optional maximum ratio of manual to total production
    """

    target_item: str
    min_automation_produced: int
    max_manual_ratio: Optional[float] = None

    def __post_init__(self):
        if self.min_automation_produced < 0:
            raise ValueError("min_automation_produced must be non-negative")
        if self.max_manual_ratio is not None:
            if not 0.0 <= self.max_manual_ratio <= 1.0:
                raise ValueError("max_manual_ratio must be between 0.0 and 1.0")


@dataclass(frozen=True)
class TaskConfig:
    """Complete task definition.

    A task config contains everything needed to:
    - Set up the task (starting inventory, technologies)
    - Describe the goal to the agent
    - Verify completion

    Attributes:
        task_key: Unique identifier for this task
        task_type: Category of task (throughput, unbounded, freeplay)
        goal_description: Human-readable description injected into system prompt
        verification: Optional criteria for verifying success
        starting_inventory: Items to give the agent at start
        all_technologies_researched: Whether all tech is unlocked
        max_trajectory_steps: Maximum agent steps allowed
    """

    task_key: str
    task_type: TaskType
    goal_description: str
    verification: Optional[VerificationCriteria] = None
    starting_inventory: dict[str, int] = field(default_factory=dict)
    all_technologies_researched: bool = True
    max_trajectory_steps: int = 64

    def __post_init__(self):
        if not self.task_key:
            raise ValueError("task_key cannot be empty")
        if self.max_trajectory_steps <= 0:
            raise ValueError("max_trajectory_steps must be positive")


@dataclass
class VerificationResult:
    """Outcome of task verification.

    Attributes:
        success: Whether the task criteria were met
        automation_produced: Items produced via automation (force_total - manual)
        manual_produced: Items produced via hand-crafting or hand-mining
        force_total: Total items produced (from force production statistics)
        measured_at_tick: Game tick when measurement was taken
        task_key: Which task was verified
        failure_reason: Optional explanation if verification failed
    """

    success: bool
    automation_produced: int
    manual_produced: int
    force_total: int
    measured_at_tick: int
    task_key: str
    failure_reason: Optional[str] = None

    @property
    def automation_ratio(self) -> float:
        """Ratio of automation to total production."""
        if self.force_total == 0:
            return 0.0
        return self.automation_produced / self.force_total

    @property
    def manual_ratio(self) -> float:
        """Ratio of manual to total production."""
        if self.force_total == 0:
            return 0.0
        return self.manual_produced / self.force_total

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "automation_produced": self.automation_produced,
            "manual_produced": self.manual_produced,
            "force_total": self.force_total,
            "measured_at_tick": self.measured_at_tick,
            "task_key": self.task_key,
            "failure_reason": self.failure_reason,
            "automation_ratio": self.automation_ratio,
            "manual_ratio": self.manual_ratio,
        }
