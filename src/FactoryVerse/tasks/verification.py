"""Core verification logic.

This module provides the verification engine for task completion:
- calculate_automation_score: Pure arithmetic on production counters
- verify_task: Complete verification against task criteria

Design principles:
- Deterministic over heuristic: No holdout loops or plateau detection
- Simple arithmetic: automation = force_output - manual_crafted - manual_mined
- Decoupled from runtime: Works via any VerificationSource
"""

import logging
from typing import Tuple

from .base import TaskConfig, TaskType, VerificationCriteria, VerificationResult
from .sources import VerificationSource

logger = logging.getLogger(__name__)


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
    """
    # Get force-level production (includes both automation and manual)
    force_stats = await source.get_force_production(agent_id)

    # Get manual production (hand-crafted and hand-mined)
    manual_stats = await source.get_manual_production(agent_id)

    # Extract counts for target item
    force_total = force_stats["output"].get(target_item, 0)
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

    tick = manual_stats.get("tick", 0)

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
) -> VerificationResult:
    """Verify a task against its criteria.

    For THROUGHPUT tasks: checks if automation_produced >= min_automation_produced
    For UNBOUNDED tasks: always succeeds (just records stats)
    For FREEPLAY tasks: always succeeds

    Args:
        task: TaskConfig with verification criteria
        source: VerificationSource to query data from
        agent_id: Agent ID to verify

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

    # Calculate automation score
    automation, manual, force_total, tick = await calculate_automation_score(
        source, agent_id, criteria.target_item
    )

    # Determine success based on task type
    success = True
    failure_reason = None

    if task.task_type == TaskType.THROUGHPUT:
        # Must meet minimum automation quota
        if automation < criteria.min_automation_produced:
            success = False
            failure_reason = (
                f"Automation produced ({automation}) < "
                f"required ({criteria.min_automation_produced})"
            )

        # Optional: check manual ratio constraint
        if criteria.max_manual_ratio is not None and force_total > 0:
            manual_ratio = manual / force_total
            if manual_ratio > criteria.max_manual_ratio:
                success = False
                failure_reason = (
                    f"Manual ratio ({manual_ratio:.2%}) > "
                    f"max allowed ({criteria.max_manual_ratio:.2%})"
                )

    elif task.task_type == TaskType.UNBOUNDED:
        # Unbounded tasks always succeed - we just record the stats
        # Success is defined by maximizing automation, not meeting a quota
        pass

    result = VerificationResult(
        success=success,
        automation_produced=automation,
        manual_produced=manual,
        force_total=force_total,
        measured_at_tick=tick,
        task_key=task.task_key,
        failure_reason=failure_reason,
    )

    logger.info(
        f"Verification result for {task.task_key}: "
        f"success={result.success}, "
        f"automation={result.automation_produced}/{criteria.min_automation_produced}, "
        f"manual_ratio={result.manual_ratio:.2%}"
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
