"""Core verification logic for rate-based throughput tasks.

This module provides the verification engine for task completion:
- ThroughputVerifier: Stateful verifier that tracks sustained production rate
- calculate_automation_score: Pure arithmetic on production counters
- verify_task: Complete verification against task criteria

Design principles:
- Rate-based verification: Sustained throughput over time, not absolute counts
- Reset on dip: If rate drops below quota, consecutive counter resets
- Configurable: Check interval and sustained duration are customizable
- Stateful: ThroughputVerifier maintains history across checks

FLE Compatibility:
- quota: Items per 60 game seconds (same as FLE)
- Default: 30 seconds sustained (6 checks at 5-second intervals)
"""

import logging
import time
from typing import Callable, Tuple, Optional, List

from .base import (
    TaskConfig,
    TaskType,
    VerificationCriteria,
    VerificationResult,
    ThroughputCheck,
)
from .sources import VerificationSource

logger = logging.getLogger(__name__)


class ThroughputVerifier:
    """Stateful verifier for rate-based throughput tasks.

    Tracks production rate over time and determines when the rate
    has been sustained for long enough to pass verification.

    The verifier:
    - Calculates rate as items per 60 game seconds (FLE standard)
    - Requires rate >= quota for N consecutive checks
    - Resets consecutive counter if rate dips below quota
    - Maintains history of recent checks for display

    Example:
        >>> verifier = ThroughputVerifier(
        ...     criteria=VerificationCriteria(
        ...         target_item="iron-plate",
        ...         quota=16,  # 16 items per 60 seconds
        ...         sustained_seconds=30.0,
        ...         check_interval_seconds=5.0,
        ...     )
        ... )
        >>> # After each tool call:
        >>> result = await verifier.check(source, agent_id)
        >>> if result.success:
        ...     print("Task complete!")
    """

    def __init__(
        self,
        criteria: VerificationCriteria,
        stale_after_seconds: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        """Initialize the verifier with task criteria.

        Args:
            criteria: VerificationCriteria with quota, sustained_seconds, etc.
            stale_after_seconds: Wall-clock seconds the feed tick may stand
                still before checks are flagged feed_stale (VERIF-1 invariant)
            clock: Monotonic time source (injectable for tests)
        """
        self.criteria = criteria
        self.quota = criteria.quota  # Items per 60 game seconds
        self.checks_required = criteria.checks_required
        self.stale_after_seconds = stale_after_seconds
        self._clock = clock

        # State tracking
        self._checks: List[ThroughputCheck] = []
        self._consecutive_passes: int = 0
        self._last_automation: Optional[int] = None
        self._last_tick: Optional[int] = None

        # Feed liveness tracking (VERIF-1)
        self._last_seen_tick: Optional[int] = None
        self._last_advance_walltime: Optional[float] = None

    def reset(self) -> None:
        """Reset verifier state (for task restart)."""
        self._checks = []
        self._consecutive_passes = 0
        self._last_automation = None
        self._last_tick = None
        self._last_seen_tick = None
        self._last_advance_walltime = None

    async def check(
        self,
        source: VerificationSource,
        agent_id: int,
        task_key: str,
    ) -> VerificationResult:
        """Perform a throughput check and return verification result.

        Args:
            source: VerificationSource to query production stats
            agent_id: Agent ID to verify
            task_key: Task key for the result

        Returns:
            VerificationResult with current state and success status
        """
        # Get current production stats
        automation, manual, force_total, tick = await calculate_automation_score(
            source, agent_id, self.criteria.target_item
        )

        # VERIF-1 runtime invariant: the feed tick must advance or we scream.
        # A frozen feed is otherwise indistinguishable from "0 produced"
        # (attempt 3: 63 checks served the same dead frame across 6 turns).
        if tick <= 0:
            logger.warning(
                f"Verification feed has NO DATA for {self.criteria.target_item} "
                f"(tick={tick}) — source returned empty/missing stats"
            )
            return self._feed_problem_result(
                automation, manual, force_total, tick, task_key,
                reason=(
                    "VERIFICATION FEED HAS NO DATA — production statistics "
                    "source returned nothing. Rate cannot be measured."
                ),
            )

        now = self._clock()
        if self._last_seen_tick is None or tick > self._last_seen_tick:
            self._last_seen_tick = tick
            self._last_advance_walltime = now
        else:
            # NOTE: explicit None check — a monotonic timestamp of 0.0 is valid
            stalled_for = (
                now - self._last_advance_walltime
                if self._last_advance_walltime is not None
                else 0.0
            )
            if stalled_for > self.stale_after_seconds:
                logger.warning(
                    f"Verification feed STALE for {self.criteria.target_item}: "
                    f"tick {tick} has not advanced in {stalled_for:.1f}s wall-clock"
                )
                return self._feed_problem_result(
                    automation, manual, force_total, tick, task_key,
                    reason=(
                        f"VERIFICATION FEED STALE — snapshot tick {tick} has not "
                        f"advanced in {stalled_for:.0f}s of wall-clock time. "
                        f"Current rate is UNKNOWN (this is a data-feed problem, "
                        f"not a measurement of your factory)."
                    ),
                )

        # First check - establish baseline
        if self._last_automation is None:
            self._last_automation = automation
            self._last_tick = tick

            return VerificationResult(
                success=False,
                automation_produced=automation,
                manual_produced=manual,
                force_total=force_total,
                measured_at_tick=tick,
                task_key=task_key,
                failure_reason="Establishing baseline...",
                current_rate=0.0,
                target_rate=float(self.quota),
                consecutive_passes=0,
                checks_required=self.checks_required,
                check_history=[],
            )

        # Calculate rate: items per 60 game seconds
        delta_automation = automation - self._last_automation
        delta_ticks = tick - self._last_tick

        if delta_ticks <= 0:
            # Same sample as last check (poll hasn't produced a new frame yet,
            # but within the staleness grace window). A 0-rate "measurement"
            # here would be fabricated and would wrongly reset the consecutive
            # counter — hold state instead.
            return VerificationResult(
                success=False,
                automation_produced=automation,
                manual_produced=manual,
                force_total=force_total,
                measured_at_tick=tick,
                task_key=task_key,
                failure_reason=f"No new sample since tick {tick} — holding (not a rate measurement)",
                current_rate=self._checks[-1].rate_per_60s if self._checks else 0.0,
                target_rate=float(self.quota),
                consecutive_passes=self._consecutive_passes,
                checks_required=self.checks_required,
                check_history=self._checks[-10:],
            )

        # Rate = (delta items / delta ticks) * 3600 ticks per 60 seconds
        # Actually: 60 ticks = 1 second, so 3600 ticks = 60 seconds
        rate_per_60s = (delta_automation / delta_ticks) * 3600

        # Check if rate meets quota
        passed = rate_per_60s >= self.quota

        # Create check record
        check = ThroughputCheck(
            tick=tick,
            rate_per_60s=rate_per_60s,
            passed=passed,
            automation_produced=automation,
            delta_produced=delta_automation,
            delta_ticks=delta_ticks,
        )
        self._checks.append(check)

        # Update state
        self._last_automation = automation
        self._last_tick = tick

        # Update consecutive counter
        if passed:
            self._consecutive_passes += 1
        else:
            # Reset on dip!
            self._consecutive_passes = 0

        # Determine overall success
        success = self._consecutive_passes >= self.checks_required

        failure_reason = None
        if not success:
            if not passed:
                failure_reason = (
                    f"Rate {rate_per_60s:.1f}/60s < quota {self.quota}/60s (reset)"
                )
            else:
                remaining = self.checks_required - self._consecutive_passes
                failure_reason = f"Need {remaining} more consecutive successful checks"

        logger.info(
            f"Throughput check for {self.criteria.target_item}: "
            f"rate={rate_per_60s:.1f}/60s, quota={self.quota}/60s, "
            f"passed={passed}, consecutive={self._consecutive_passes}/{self.checks_required}"
        )

        return VerificationResult(
            success=success,
            automation_produced=automation,
            manual_produced=manual,
            force_total=force_total,
            measured_at_tick=tick,
            task_key=task_key,
            failure_reason=failure_reason,
            current_rate=rate_per_60s,
            target_rate=float(self.quota),
            consecutive_passes=self._consecutive_passes,
            checks_required=self.checks_required,
            check_history=self._checks[-10:],  # Keep last 10 checks
        )

    def _feed_problem_result(
        self,
        automation: int,
        manual: int,
        force_total: int,
        tick: int,
        task_key: str,
        reason: str,
    ) -> VerificationResult:
        """Build a feed_stale result: counters and baselines are left untouched
        so a harness/data failure neither resets nor advances task progress."""
        return VerificationResult(
            success=False,
            automation_produced=automation,
            manual_produced=manual,
            force_total=force_total,
            measured_at_tick=tick,
            task_key=task_key,
            failure_reason=reason,
            current_rate=0.0,
            target_rate=float(self.quota),
            consecutive_passes=self._consecutive_passes,
            checks_required=self.checks_required,
            check_history=self._checks[-10:],
            feed_stale=True,
        )

    @property
    def consecutive_passes(self) -> int:
        """Number of consecutive successful rate checks."""
        return self._consecutive_passes

    @property
    def is_verified(self) -> bool:
        """True if sustained requirement met."""
        return self._consecutive_passes >= self.checks_required

    def format_progress(self, result: VerificationResult) -> str:
        """Format verification result as human-readable progress.

        Args:
            result: VerificationResult from check()

        Returns:
            Formatted progress string for display to agent
        """
        lines = []
        target = self.criteria.target_item
        quota = self.quota
        rate = result.current_rate
        consecutive = result.consecutive_passes
        required = result.checks_required

        if result.success:
            lines.append("=" * 50)
            lines.append("✅ TASK COMPLETE!")
            lines.append("=" * 50)
            lines.append(f"Target: {target}")
            lines.append(f"Required rate: {quota}/60s")
            lines.append(f"Sustained rate: {rate:.1f}/60s")
            lines.append(f"Sustained for: {consecutive} consecutive checks")
            lines.append("")
            lines.append("Your factory has sustained the required throughput.")
            lines.append("The task is complete - you may stop.")
            lines.append("=" * 50)
        elif result.feed_stale:
            lines.append("!" * 45)
            lines.append(f"⚠️  VERIFICATION FEED PROBLEM: {target}")
            lines.append("!" * 45)
            if result.failure_reason:
                lines.append(f"  {result.failure_reason}")
            lines.append(f"  Last data at tick: {result.measured_at_tick}")
            lines.append(f"  Last known total: {result.automation_produced} (automation)")
            lines.append(f"  Sustained progress held at: {result.consecutive_passes}/{result.checks_required}")
            lines.append("!" * 45)
        else:
            lines.append("-" * 45)
            lines.append(f"📊 Throughput: {target}")
            lines.append("-" * 45)
            lines.append(f"  Target rate: {quota}/60s")

            # Current rate with pass/fail indicator
            rate_status = "✓" if rate >= quota else "✗"
            lines.append(f"  Current rate: {rate:.1f}/60s {rate_status}")

            # Sustained progress
            sustained_seconds = consecutive * self.criteria.check_interval_seconds
            required_seconds = self.criteria.sustained_seconds
            lines.append(
                f"  Sustained: {consecutive}/{required} checks "
                f"({sustained_seconds:.0f}s/{required_seconds:.0f}s)"
            )

            # Visual progress bar for sustained checks
            bar_len = required
            filled = min(consecutive, required)
            bar = "●" * filled + "○" * (bar_len - filled)
            lines.append(f"  Progress: [{bar}]")

            # Recent check history (last 5)
            if self._checks:
                history = self._checks[-5:]
                history_str = " ".join("✓" if c.passed else "✗" for c in history)
                lines.append(f"  Last {len(history)}: {history_str}")

                # Show if there was a recent dip (reset)
                for i, check in enumerate(history):
                    if not check.passed and i < len(history) - 1:
                        lines.append(f"           {'  ' * i}↑ dip (reset)")
                        break

            # Cumulative stats
            lines.append(f"  Total produced: {result.automation_produced} (automation)")

            # Tick information for staleness awareness
            # Stats are polled every 60 ticks (1 second), so data may be up to 1s old
            snapshot_tick = result.measured_at_tick
            snapshot_seconds = snapshot_tick / 60.0
            lines.append(f"  Snapshot tick: {snapshot_tick} ({snapshot_seconds:.1f}s game time)")

            if result.failure_reason:
                lines.append(f"  Note: {result.failure_reason}")

            lines.append("-" * 45)

        return "\n".join(lines)


async def calculate_automation_score(
    source: VerificationSource,
    agent_id: int,
    target_item: str,
) -> Tuple[int, int, int, int]:
    """Calculate automation-produced items for a target item.

    The core calculation:
        automation_produced = force_output - manual_crafted - manual_mined

    This is pure arithmetic with no heuristics or waiting.

    Args:
        source: VerificationSource to query data from
        agent_id: Agent ID to calculate for
        target_item: The item name to measure (e.g., "iron-plate")

    Returns:
        Tuple of (automation_produced, manual_produced, force_total, tick)
        The tick is from production stats (force-level), not manual stats.
    """
    # Get force-level production (includes both automation and manual)
    force_stats = await source.get_force_production(agent_id)

    # Get manual production (hand-crafted and hand-mined)
    manual_stats = await source.get_manual_production(agent_id)

    # Extract counts for target item
    # Factorio FlowStatistics semantics for item_production_statistics:
    #   input_counts = items PRODUCED by automation (machines creating items)
    #   output_counts = items CONSUMED by automation (machines using items as ingredients)
    # We want items PRODUCED for throughput verification → use input_counts
    force_total = force_stats["input"].get(target_item, 0)

    manual_crafted = manual_stats["crafted"].get(target_item, 0)
    manual_mined = manual_stats["mined"].get(target_item, 0)

    # Calculate automation-produced
    manual_total = manual_crafted + manual_mined
    automation_produced = force_total - manual_total

    # Handle edge case: automation can't be negative
    # (could happen if stats are out of sync)
    if automation_produced < 0:
        logger.warning(
            f"Negative automation for {target_item}: "
            f"force={force_total}, manual={manual_total}. "
            "Stats may be out of sync."
        )
        automation_produced = 0

    # Use tick from production stats (force-level), NOT manual stats
    # This ensures rate calculations work even when no manual crafting/mining occurs
    tick = force_stats.get("tick", 0)

    logger.debug(
        f"Automation score for {target_item}: "
        f"automation={automation_produced}, manual={manual_total}, "
        f"force_total={force_total}, tick={tick}"
    )

    return automation_produced, manual_total, force_total, tick


async def verify_task(
    task: TaskConfig,
    source: VerificationSource,
    agent_id: int,
    verifier: Optional[ThroughputVerifier] = None,
) -> VerificationResult:
    """Verify a task against its criteria.

    For THROUGHPUT tasks with a verifier: Uses rate-based verification
    For UNBOUNDED tasks: Always succeeds (just records stats)
    For FREEPLAY tasks: Always succeeds

    Args:
        task: TaskConfig with verification criteria
        source: VerificationSource to query data from
        agent_id: Agent ID to verify
        verifier: Optional ThroughputVerifier for rate-based tasks

    Returns:
        VerificationResult with success status and production stats
    """
    # Freeplay tasks always pass
    if task.task_type == TaskType.FREEPLAY:
        return VerificationResult(
            success=True,
            automation_produced=0,
            manual_produced=0,
            force_total=0,
            measured_at_tick=0,
            task_key=task.task_key,
        )

    # Tasks without verification criteria pass by default
    if task.verification is None:
        logger.warning(f"Task {task.task_key} has no verification criteria")
        return VerificationResult(
            success=True,
            automation_produced=0,
            manual_produced=0,
            force_total=0,
            measured_at_tick=0,
            task_key=task.task_key,
        )

    criteria = task.verification

    # THROUGHPUT tasks with verifier use rate-based verification
    if task.task_type == TaskType.THROUGHPUT and verifier is not None:
        return await verifier.check(source, agent_id, task.task_key)

    # Fallback: simple cumulative check (legacy)
    automation, manual, force_total, tick = await calculate_automation_score(
        source, agent_id, criteria.target_item
    )

    success = True
    failure_reason = None

    if task.task_type == TaskType.THROUGHPUT:
        # Simple check: total automation >= quota
        # This is the fallback when no verifier is provided
        if automation < criteria.quota:
            success = False
            failure_reason = f"Automation ({automation}) < quota ({criteria.quota})"

        if criteria.max_manual_ratio is not None and force_total > 0:
            manual_ratio = manual / force_total
            if manual_ratio > criteria.max_manual_ratio:
                success = False
                failure_reason = (
                    f"Manual ratio ({manual_ratio:.2%}) > "
                    f"max allowed ({criteria.max_manual_ratio:.2%})"
                )

    result = VerificationResult(
        success=success,
        automation_produced=automation,
        manual_produced=manual,
        force_total=force_total,
        measured_at_tick=tick,
        task_key=task.task_key,
        failure_reason=failure_reason,
        current_rate=0.0,  # Unknown without verifier
        target_rate=float(criteria.quota),
        consecutive_passes=0,
        checks_required=criteria.checks_required,
    )

    logger.info(
        f"Verification result for {task.task_key}: "
        f"success={result.success}, "
        f"automation={result.automation_produced}/{criteria.quota}"
    )

    return result


async def verify_multiple_items(
    source: VerificationSource,
    agent_id: int,
    target_items: list[str],
) -> dict[str, Tuple[int, int, int]]:
    """Calculate automation scores for multiple items.

    Useful for tasks that produce multiple outputs or for
    comprehensive factory analysis.

    Args:
        source: VerificationSource to query data from
        agent_id: Agent ID to calculate for
        target_items: List of item names to measure

    Returns:
        Dict mapping item_name -> (automation, manual, force_total)
    """
    results = {}
    for item in target_items:
        automation, manual, force_total, _ = await calculate_automation_score(
            source, agent_id, item
        )
        results[item] = (automation, manual, force_total)

    return results
