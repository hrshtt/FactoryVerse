"""Unit tests for task verification system.

Tests the core verification logic with mock sources,
without requiring a running Factorio instance.
"""

import pytest
from typing import Dict

from FactoryVerse.game.tasks.base import (
    TaskType,
    TaskConfig,
    VerificationCriteria,
    VerificationResult,
)
from FactoryVerse.game.tasks.registry import TaskRegistry
from FactoryVerse.game.tasks.sources import ProductionStats, ManualStats
from FactoryVerse.game.tasks.verification import (
    calculate_automation_score,
    verify_task,
    verify_multiple_items,
)


# =============================================================================
# Mock Source for Testing
# =============================================================================


class MockVerificationSource:
    """Mock source for unit testing verification logic."""

    def __init__(
        self,
        force_input: Dict[str, int] | None = None,
        force_output: Dict[str, int] | None = None,
        manual_crafted: Dict[str, int] | None = None,
        manual_mined: Dict[str, int] | None = None,
        tick: int = 1000,
    ):
        # Factorio FlowStatistics semantics for item_production_statistics:
        #   input_counts = items PRODUCED by automation
        #   output_counts = items CONSUMED by automation
        self._force_input = force_input or {}
        self._force_output = force_output or {}
        self._manual_crafted = manual_crafted or {}
        self._manual_mined = manual_mined or {}
        self._tick = tick

    async def get_force_production(self, agent_id: int) -> ProductionStats:
        return ProductionStats(
            input=self._force_input,
            output=self._force_output,
            tick=self._tick,
        )

    async def get_manual_production(self, agent_id: int) -> ManualStats:
        return ManualStats(
            crafted=self._manual_crafted,
            mined=self._manual_mined,
            agent_id=agent_id,
            tick=self._tick,
        )


# =============================================================================
# Base Type Tests
# =============================================================================


class TestVerificationCriteria:
    """Tests for VerificationCriteria dataclass."""

    def test_valid_criteria(self):
        """Test creating valid verification criteria."""
        criteria = VerificationCriteria(
            target_item="iron-plate",
            quota=16,
        )
        assert criteria.target_item == "iron-plate"
        assert criteria.quota == 16
        assert criteria.max_manual_ratio is None
        assert criteria.sustained_seconds == 30.0
        assert criteria.check_interval_seconds == 5.0
        assert criteria.checks_required == 6

    def test_criteria_with_manual_ratio(self):
        """Test criteria with manual ratio constraint."""
        criteria = VerificationCriteria(
            target_item="iron-plate",
            quota=16,
            max_manual_ratio=0.5,
        )
        assert criteria.max_manual_ratio == 0.5

    def test_invalid_negative_quota(self):
        """Test that negative quota raises error."""
        with pytest.raises(ValueError, match="non-negative"):
            VerificationCriteria(
                target_item="iron-plate",
                quota=-1,
            )

    def test_invalid_manual_ratio_too_high(self):
        """Test that manual ratio > 1.0 raises error."""
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            VerificationCriteria(
                target_item="iron-plate",
                quota=16,
                max_manual_ratio=1.5,
            )

    def test_invalid_manual_ratio_negative(self):
        """Test that negative manual ratio raises error."""
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            VerificationCriteria(
                target_item="iron-plate",
                quota=16,
                max_manual_ratio=-0.1,
            )


class TestTaskConfig:
    """Tests for TaskConfig dataclass."""

    def test_valid_throughput_task(self):
        """Test creating a valid throughput task."""
        task = TaskConfig(
            task_key="test_task",
            task_type=TaskType.THROUGHPUT,
            goal_description="Test task description",
            verification=VerificationCriteria(
                target_item="iron-plate",
                quota=16,
            ),
        )
        assert task.task_key == "test_task"
        assert task.task_type == TaskType.THROUGHPUT
        assert task.verification is not None

    def test_freeplay_task_no_verification(self):
        """Test that freeplay tasks can have no verification."""
        task = TaskConfig(
            task_key="freeplay_test",
            task_type=TaskType.FREEPLAY,
            goal_description="Free exploration",
        )
        assert task.verification is None

    def test_invalid_empty_task_key(self):
        """Test that empty task_key raises error."""
        with pytest.raises(ValueError, match="cannot be empty"):
            TaskConfig(
                task_key="",
                task_type=TaskType.THROUGHPUT,
                goal_description="Test",
            )

    def test_invalid_trajectory_steps(self):
        """Test that non-positive trajectory steps raises error."""
        with pytest.raises(ValueError, match="must be positive"):
            TaskConfig(
                task_key="test",
                task_type=TaskType.THROUGHPUT,
                goal_description="Test",
                max_trajectory_steps=0,
            )


class TestVerificationResult:
    """Tests for VerificationResult dataclass."""

    def test_automation_ratio(self):
        """Test automation ratio calculation."""
        result = VerificationResult(
            success=True,
            automation_produced=10,
            manual_produced=5,
            force_total=15,
            measured_at_tick=1000,
            task_key="test",
        )
        assert result.automation_ratio == pytest.approx(10 / 15)
        assert result.manual_ratio == pytest.approx(5 / 15)

    def test_zero_force_total(self):
        """Test ratios when force_total is zero."""
        result = VerificationResult(
            success=False,
            automation_produced=0,
            manual_produced=0,
            force_total=0,
            measured_at_tick=1000,
            task_key="test",
        )
        assert result.automation_ratio == 0.0
        assert result.manual_ratio == 0.0

    def test_to_dict(self):
        """Test serialization to dict."""
        result = VerificationResult(
            success=True,
            automation_produced=16,
            manual_produced=0,
            force_total=16,
            measured_at_tick=1000,
            task_key="test_task",
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["automation_produced"] == 16
        assert d["task_key"] == "test_task"
        assert "automation_ratio" in d


# =============================================================================
# Verification Logic Tests
# =============================================================================


class TestCalculateAutomationScore:
    """Tests for calculate_automation_score function."""

    @pytest.mark.asyncio
    async def test_pure_automation(self):
        """Test scoring when all production is automated."""
        # Factorio FlowStatistics semantics for item_production_statistics:
        #   input = items PRODUCED by automation (machines creating items)
        #   output = items CONSUMED by automation (machines using items)
        source = MockVerificationSource(
            force_input={"iron-plate": 100},
            manual_crafted={},
            manual_mined={},
        )

        automation, manual, force_total, tick = await calculate_automation_score(
            source, agent_id=1, target_item="iron-plate"
        )

        assert automation == 100
        assert manual == 0
        assert force_total == 100

    @pytest.mark.asyncio
    async def test_pure_manual(self):
        """Test scoring when all production is manual."""
        # Surface-scoped force input excludes character production.
        source = MockVerificationSource(
            force_input={},
            manual_crafted={"iron-plate": 50},
        )

        automation, manual, force_total, tick = await calculate_automation_score(
            source, agent_id=1, target_item="iron-plate"
        )

        assert automation == 0
        assert manual == 50
        assert force_total == 0

    @pytest.mark.asyncio
    async def test_mixed_production(self):
        """Test scoring with mixed automation and manual."""
        # input = items produced by automation (force-level total)
        source = MockVerificationSource(
            force_input={"iron-plate": 60},
            manual_crafted={"iron-plate": 30},
            manual_mined={"iron-plate": 10},  # Can mine iron plates from debris
        )

        automation, manual, force_total, tick = await calculate_automation_score(
            source, agent_id=1, target_item="iron-plate"
        )

        assert automation == 60
        assert manual == 40  # 30 + 10
        assert force_total == 60

    @pytest.mark.asyncio
    async def test_item_not_produced(self):
        """Test scoring for an item that wasn't produced."""
        # input = items produced by automation (force-level total)
        source = MockVerificationSource(
            force_input={"copper-plate": 50},  # Different item
        )

        automation, manual, force_total, tick = await calculate_automation_score(
            source, agent_id=1, target_item="iron-plate"
        )

        assert automation == 0
        assert manual == 0
        assert force_total == 0

    @pytest.mark.asyncio
    async def test_manual_channel_does_not_reduce_force_automation(self):
        """Independent manual counts are never subtracted from force input."""
        source = MockVerificationSource(
            force_input={"iron-plate": 10},
            manual_crafted={"iron-plate": 15},
        )

        automation, manual, force_total, tick = await calculate_automation_score(
            source, agent_id=1, target_item="iron-plate"
        )

        assert automation == 10
        assert manual == 15
        assert force_total == 10


class TestVerifyTask:
    """Tests for verify_task function."""

    @pytest.mark.asyncio
    async def test_throughput_task_success(self):
        """Test successful throughput task verification."""
        task = TaskConfig(
            task_key="iron_test",
            task_type=TaskType.THROUGHPUT,
            goal_description="Produce iron",
            verification=VerificationCriteria(
                target_item="iron-plate",
                quota=16,
            ),
        )

        # input = items produced by automation (force-level total)
        source = MockVerificationSource(
            force_input={"iron-plate": 20},
            manual_crafted={},
        )

        result = await verify_task(task, source, agent_id=1)

        assert result.success is True
        assert result.automation_produced == 20
        assert result.task_key == "iron_test"
        assert result.failure_reason is None

    @pytest.mark.asyncio
    async def test_throughput_task_failure_insufficient_automation(self):
        """Test failed verification due to insufficient automation."""
        task = TaskConfig(
            task_key="iron_test",
            task_type=TaskType.THROUGHPUT,
            goal_description="Produce iron",
            verification=VerificationCriteria(
                target_item="iron-plate",
                quota=16,
            ),
        )

        # input = items produced by automation (force-level total)
        source = MockVerificationSource(
            force_input={"iron-plate": 10},
            manual_crafted={},
        )

        result = await verify_task(task, source, agent_id=1)

        assert result.success is False
        assert result.automation_produced == 10
        assert "10" in result.failure_reason
        assert "16" in result.failure_reason

    @pytest.mark.asyncio
    async def test_throughput_task_failure_too_much_manual(self):
        """Test failed verification due to excessive manual production."""
        task = TaskConfig(
            task_key="iron_test",
            task_type=TaskType.THROUGHPUT,
            goal_description="Produce iron",
            verification=VerificationCriteria(
                target_item="iron-plate",
                quota=16,
                max_manual_ratio=0.2,  # Max 20% manual
            ),
        )

        # 20 automation, 30 manual = 60% manual ratio > 20%
        # input = items produced by automation (force-level total)
        source = MockVerificationSource(
            force_input={"iron-plate": 20},
            manual_crafted={"iron-plate": 30},
        )

        result = await verify_task(task, source, agent_id=1)

        assert result.success is False
        assert "manual ratio" in result.failure_reason.lower()

    @pytest.mark.asyncio
    async def test_freeplay_task_always_passes(self):
        """Test that freeplay tasks always pass."""
        task = TaskConfig(
            task_key="freeplay",
            task_type=TaskType.FREEPLAY,
            goal_description="Explore freely",
        )

        source = MockVerificationSource()

        result = await verify_task(task, source, agent_id=1)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_unbounded_task_always_passes(self):
        """Test that unbounded tasks always pass (just record stats)."""
        task = TaskConfig(
            task_key="unbounded_iron",
            task_type=TaskType.UNBOUNDED,
            goal_description="Maximize iron production",
            verification=VerificationCriteria(
                target_item="iron-plate",
                quota=0,  # No minimum for unbounded
            ),
        )

        # input = items produced by automation (force-level total)
        source = MockVerificationSource(
            force_input={"iron-plate": 5},
        )

        result = await verify_task(task, source, agent_id=1)

        assert result.success is True
        assert result.automation_produced == 5


class TestVerifyMultipleItems:
    """Tests for verify_multiple_items function."""

    @pytest.mark.asyncio
    async def test_multiple_items(self):
        """Test verifying multiple items at once."""
        # input = items produced by automation (force-level total)
        source = MockVerificationSource(
            force_input={
                "iron-plate": 90,
                "copper-plate": 50,
                "electronic-circuit": 20,
            },
            manual_crafted={
                "iron-plate": 10,
                "electronic-circuit": 5,
            },
        )

        results = await verify_multiple_items(
            source,
            agent_id=1,
            target_items=["iron-plate", "copper-plate", "electronic-circuit"],
        )

        assert results["iron-plate"] == (90, 10, 90)  # independent channels
        assert results["copper-plate"] == (50, 0, 50)  # 50 auto, 0 manual
        assert results["electronic-circuit"] == (20, 5, 20)


# =============================================================================
# Registry Tests
# =============================================================================


class TestTaskRegistry:
    """Tests for TaskRegistry."""

    def setup_method(self):
        """Reset registry before each test."""
        TaskRegistry.reset()

    def test_get_singleton(self):
        """Test that registry returns singleton."""
        registry1 = TaskRegistry.get()
        registry2 = TaskRegistry.get()
        assert registry1 is registry2

    def test_list_tasks(self):
        """Test listing all tasks."""
        registry = TaskRegistry.get()
        tasks = registry.list_tasks()
        assert len(tasks) == 24  # 24 throughput tasks
        assert "iron_plate_throughput" in tasks

    def test_get_task(self):
        """Test getting a specific task."""
        registry = TaskRegistry.get()
        task = registry.get_task("iron_plate_throughput")

        assert task.task_key == "iron_plate_throughput"
        assert task.task_type == TaskType.THROUGHPUT
        assert task.verification is not None
        assert task.verification.target_item == "iron-plate"
        assert task.verification.quota == 16

    def test_get_unknown_task(self):
        """Test that unknown task raises KeyError."""
        registry = TaskRegistry.get()
        with pytest.raises(KeyError, match="Unknown task"):
            registry.get_task("nonexistent_task")

    def test_task_exists(self):
        """Test task_exists method."""
        registry = TaskRegistry.get()
        assert registry.task_exists("iron_plate_throughput")
        assert not registry.task_exists("nonexistent_task")

    def test_list_by_type(self):
        """Test listing tasks by type."""
        registry = TaskRegistry.get()
        by_type = registry.list_tasks_by_type()

        assert TaskType.THROUGHPUT in by_type
        assert len(by_type[TaskType.THROUGHPUT]) == 24

    def test_register_custom_task(self):
        """Test registering a custom task."""
        registry = TaskRegistry.get()

        custom_task = TaskConfig(
            task_key="custom_test_task",
            task_type=TaskType.FREEPLAY,
            goal_description="Custom test",
        )
        registry.register_task(custom_task)

        assert registry.task_exists("custom_test_task")
        retrieved = registry.get_task("custom_test_task")
        assert retrieved.task_key == "custom_test_task"


# =============================================================================
# Integration-like Tests (with mocks)
# =============================================================================


class TestVerificationWorkflow:
    """Tests for complete verification workflows."""

    def setup_method(self):
        """Reset registry before each test."""
        TaskRegistry.reset()

    @pytest.mark.asyncio
    async def test_full_workflow_success(self):
        """Test complete workflow: get task from registry, verify success."""
        # Get task from registry
        registry = TaskRegistry.get()
        task = registry.get_task("iron_plate_throughput")

        # Create mock source simulating successful automation
        # input = items produced by automation (force-level total)
        source = MockVerificationSource(
            force_input={"iron-plate": 45},
            manual_crafted={"iron-plate": 5},
        )

        # Verify
        result = await verify_task(task, source, agent_id=1)

        assert result.success is True
        assert result.automation_produced == 45
        assert result.manual_produced == 5

    @pytest.mark.asyncio
    async def test_full_workflow_failure_all_manual(self):
        """Test workflow where agent only hand-crafted."""
        registry = TaskRegistry.get()
        task = registry.get_task("iron_plate_throughput")

        # Source simulating only manual production
        # input = items produced by automation (force-level total)
        source = MockVerificationSource(
            force_input={},
            manual_crafted={"iron-plate": 16},  # All manual!
        )

        result = await verify_task(task, source, agent_id=1)

        assert result.success is False
        assert result.automation_produced == 0
        assert result.manual_produced == 16
