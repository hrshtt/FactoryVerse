"""Unit tests for the VERIF-1 runtime invariant: the verification feed tick
must advance or the verifier screams.

Background (engine_unit attempt 3, 2026-06-11): the production feed froze at
tick 404340 for 63 consecutive checks across 6 agent turns. The verifier
served the dead frame as a normal 0-rate reading — indistinguishable from
"0 produced" — and the meter never warned. These tests pin the corrected
behavior:

- tick <= 0 (no data)            -> feed_stale result, loud reason
- tick frozen within grace       -> hold (no fabricated 0-rate, no counter reset)
- tick frozen beyond grace       -> feed_stale result, loud reason
- feed problems never reset or advance the consecutive-pass counter
- recovery after a stall resumes normal measurement
"""

import pytest
from typing import Dict

from FactoryVerse.game.tasks.base import VerificationCriteria
from FactoryVerse.game.tasks.sources import ProductionStats, ManualStats
from FactoryVerse.game.tasks.verification import ThroughputVerifier


class MutableSource:
    """Mock source whose tick and production can be advanced between checks."""

    def __init__(self, tick: int = 1000, produced: int = 0, item: str = "iron-plate"):
        self.tick = tick
        self.produced = produced
        self.item = item

    async def get_force_production(self, agent_id: int) -> ProductionStats:
        return ProductionStats(
            input={self.item: self.produced} if self.produced else {},
            output={},
            tick=self.tick,
        )

    async def get_manual_production(self, agent_id: int) -> ManualStats:
        return ManualStats(crafted={}, mined={}, agent_id=agent_id, tick=self.tick)


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_verifier(clock: FakeClock, stale_after: float = 10.0) -> ThroughputVerifier:
    criteria = VerificationCriteria(
        target_item="iron-plate",
        quota=10,
        sustained_seconds=15.0,
        check_interval_seconds=5.0,
    )
    return ThroughputVerifier(criteria, stale_after_seconds=stale_after, clock=clock)


@pytest.mark.asyncio
async def test_no_data_screams_and_establishes_no_baseline():
    clock = FakeClock()
    verifier = make_verifier(clock)
    source = MutableSource(tick=0)

    result = await verifier.check(source, agent_id=1, task_key="t")

    assert result.feed_stale is True
    assert result.success is False
    assert "NO DATA" in result.failure_reason

    # Once data appears, the first real read establishes the baseline normally
    source.tick = 5000
    source.produced = 100
    result = await verifier.check(source, agent_id=1, task_key="t")
    assert result.feed_stale is False
    assert "baseline" in result.failure_reason.lower()


@pytest.mark.asyncio
async def test_frozen_tick_within_grace_holds_without_reset():
    clock = FakeClock()
    verifier = make_verifier(clock, stale_after=10.0)
    source = MutableSource(tick=1000, produced=0)

    await verifier.check(source, agent_id=1, task_key="t")  # baseline

    # Build up two passing checks (rate well above quota)
    for produced, tick in [(100, 4600), (200, 8200)]:
        source.produced, source.tick = produced, tick
        clock.advance(2.0)
        result = await verifier.check(source, agent_id=1, task_key="t")
        assert result.feed_stale is False
    assert verifier.consecutive_passes == 2

    # Same frame again, only 2s later: hold, don't fabricate a 0-rate reading
    clock.advance(2.0)
    result = await verifier.check(source, agent_id=1, task_key="t")
    assert result.feed_stale is False
    assert "No new sample" in result.failure_reason
    assert result.consecutive_passes == 2
    assert verifier.consecutive_passes == 2


@pytest.mark.asyncio
async def test_frozen_tick_beyond_grace_screams_and_preserves_counter():
    clock = FakeClock()
    verifier = make_verifier(clock, stale_after=10.0)
    source = MutableSource(tick=1000, produced=0)

    await verifier.check(source, agent_id=1, task_key="t")  # baseline

    source.produced, source.tick = 100, 4600
    clock.advance(2.0)
    await verifier.check(source, agent_id=1, task_key="t")
    assert verifier.consecutive_passes == 1

    # Feed freezes: same tick for 12s wall-clock (beyond the 10s grace)
    clock.advance(12.0)
    result = await verifier.check(source, agent_id=1, task_key="t")

    assert result.feed_stale is True
    assert result.success is False
    assert "STALE" in result.failure_reason
    assert "4600" in result.failure_reason
    # The harness failure neither resets nor advances task progress
    assert result.consecutive_passes == 1
    assert verifier.consecutive_passes == 1


@pytest.mark.asyncio
async def test_recovery_after_stall_resumes_measurement():
    clock = FakeClock()
    verifier = make_verifier(clock, stale_after=10.0)
    source = MutableSource(tick=1000, produced=0)

    await verifier.check(source, agent_id=1, task_key="t")  # baseline

    clock.advance(15.0)  # frozen beyond grace
    result = await verifier.check(source, agent_id=1, task_key="t")
    assert result.feed_stale is True

    # Feed recovers: tick advances, production resumed during the gap
    source.produced, source.tick = 500, 10000
    clock.advance(1.0)
    result = await verifier.check(source, agent_id=1, task_key="t")

    assert result.feed_stale is False
    assert result.current_rate == pytest.approx(500 / 9000 * 3600)
    assert verifier.consecutive_passes == 1


@pytest.mark.asyncio
async def test_stale_result_renders_warning_not_rate():
    clock = FakeClock()
    verifier = make_verifier(clock, stale_after=10.0)
    source = MutableSource(tick=1000, produced=50)

    await verifier.check(source, agent_id=1, task_key="t")  # baseline
    clock.advance(15.0)
    result = await verifier.check(source, agent_id=1, task_key="t")
    assert result.feed_stale is True

    rendered = verifier.format_progress(result)
    assert "VERIFICATION FEED PROBLEM" in rendered
    assert "Current rate:" not in rendered  # an unknown rate must not be displayed as a reading


@pytest.mark.asyncio
async def test_healthy_feed_unaffected_by_invariant():
    """Regression guard: a normally-advancing feed verifies exactly as before."""
    clock = FakeClock()
    verifier = make_verifier(clock, stale_after=10.0)
    source = MutableSource(tick=1000, produced=0)

    await verifier.check(source, agent_id=1, task_key="t")  # baseline

    result = None
    for i in range(1, 4):  # 3 checks required (15s / 5s)
        source.produced = i * 100
        source.tick = 1000 + i * 3600
        clock.advance(2.0)
        result = await verifier.check(source, agent_id=1, task_key="t")

    assert result.success is True
    assert result.feed_stale is False
