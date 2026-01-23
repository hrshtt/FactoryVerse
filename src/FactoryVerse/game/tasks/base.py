"""Base types for task definitions and verification.

This module provides the foundational types for the task verification system:
- TaskType: Enum for different task categories
- VerificationCriteria: What to verify (target item, quota, constraints)
- TaskConfig: Complete task definition
- VerificationResult: Outcome of verification

Rate-based throughput verification:
- quota: Items that must be produced per 60 game seconds (FLE standard)
- sustained_seconds: How long the rate must be sustained (default: 30s)
- check_interval_seconds: How often to check rate (default: 5s)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List


class TaskType(Enum):
    """Types of tasks supported by the verification system."""

    THROUGHPUT = "throughput"  # Sustain N items per 60s via automation
    UNBOUNDED = "unbounded"  # Maximize production (no quota)
    FREEPLAY = "freeplay"  # No verification criteria


@dataclass(frozen=True)
class VerificationCriteria:
    """Defines what to verify for a task.

    For THROUGHPUT tasks, this uses rate-based verification:
    - quota: Items per 60 game seconds (FLE standard)
    - sustained_seconds: Must sustain rate for this duration (default: 30s)
    - check_interval_seconds: Check rate every N seconds (default: 5s)

    Success requires: rate >= quota for (sustained_seconds / check_interval_seconds)
    consecutive successful checks.

    Attributes:
        target_item: The item name to measure (e.g., "iron-plate")
        quota: Items per 60 game seconds (rate target)
        sustained_seconds: Rate must be sustained for this many seconds
        check_interval_seconds: Seconds between rate checks
        max_manual_ratio: Optional maximum ratio of manual to total production
    """

    target_item: str
    quota: int  # Items per 60 game seconds (FLE standard)
    sustained_seconds: float = 30.0  # Must sustain for 30 seconds
    check_interval_seconds: float = 5.0  # Check every 5 seconds
    max_manual_ratio: Optional[float] = None

    def __post_init__(self):
        if self.quota < 0:
            raise ValueError("quota must be non-negative")
        if self.sustained_seconds <= 0:
            raise ValueError("sustained_seconds must be positive")
        if self.check_interval_seconds <= 0:
            raise ValueError("check_interval_seconds must be positive")
        if self.max_manual_ratio is not None:
            if not 0.0 <= self.max_manual_ratio <= 1.0:
                raise ValueError("max_manual_ratio must be between 0.0 and 1.0")

    @property
    def checks_required(self) -> int:
        """Number of consecutive successful checks required."""
        return int(self.sustained_seconds / self.check_interval_seconds)

    @property
    def check_interval_ticks(self) -> int:
        """Check interval in game ticks (60 ticks = 1 second)."""
        return int(self.check_interval_seconds * 60)


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
class ThroughputCheck:
    """Result of a single throughput rate check.

    Represents one point in time measurement of production rate.
    Used by ThroughputVerifier to track sustained throughput.
    """

    tick: int  # Game tick when check occurred
    rate_per_60s: float  # Items per 60 game seconds
    passed: bool  # Rate >= quota?
    automation_produced: int  # Cumulative automation at this check
    delta_produced: int  # Items produced since last check
    delta_ticks: int  # Ticks since last check

    def to_dict(self) -> dict:
        return {
            "tick": self.tick,
            "rate_per_60s": self.rate_per_60s,
            "passed": self.passed,
            "automation_produced": self.automation_produced,
            "delta_produced": self.delta_produced,
            "delta_ticks": self.delta_ticks,
        }


@dataclass
class VerificationResult:
    """Outcome of task verification.

    For rate-based throughput tasks, includes:
    - current_rate: Current production rate (items per 60s)
    - consecutive_passes: Number of consecutive successful rate checks
    - checks_required: Total checks needed for verification
    - check_history: Recent rate checks for debugging/display

    Attributes:
        success: Whether the task criteria were met
        automation_produced: Items produced via automation (cumulative)
        manual_produced: Items produced via hand-crafting or hand-mining
        force_total: Total items produced (from force production statistics)
        measured_at_tick: Game tick when measurement was taken
        task_key: Which task was verified
        failure_reason: Optional explanation if verification failed
        current_rate: Current throughput rate (items per 60 game seconds)
        consecutive_passes: Number of consecutive successful rate checks
        checks_required: Total consecutive checks needed
        check_history: Recent ThroughputCheck results
    """

    success: bool
    automation_produced: int
    manual_produced: int
    force_total: int
    measured_at_tick: int
    task_key: str
    failure_reason: Optional[str] = None

    # Rate-based verification fields
    current_rate: float = 0.0  # Items per 60 game seconds
    target_rate: float = 0.0  # Required rate (quota)
    consecutive_passes: int = 0
    checks_required: int = 6  # Default: 30s / 5s = 6 checks
    check_history: List[ThroughputCheck] = field(default_factory=list)

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
            # Rate-based fields
            "current_rate": self.current_rate,
            "target_rate": self.target_rate,
            "consecutive_passes": self.consecutive_passes,
            "checks_required": self.checks_required,
            "check_history": [c.to_dict() for c in self.check_history[-10:]],  # Last 10
        }
