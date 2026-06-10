"""Unit tests for Task Progress dedupe and static-prefix prompt caching (OBS-2).

Pure-function tests, no Factorio and no live LLM calls.

The progress-block fixtures below are real blocks taken from the
2026-06-10_23-35-34 engine_unit eval run (.fv-output/evals/engine_unit_throughput/),
where the block was emitted 163 times with only 35 distinct contents.
"""

import pytest

from FactoryVerse.infra.llm.context.progress_dedupe import ProgressDeduper
from FactoryVerse.infra.llm.client.openai_compatible import (
    apply_cache_control_to_static_prefix,
)


# =============================================================================
# Fixtures: real Task Progress blocks from the measured run
# =============================================================================

BLOCK_BASELINE = """\
---------------------------------------------
📊 Throughput: engine-unit
---------------------------------------------
  Target rate: 16/60s
  Current rate: 0.0/60s ✗
  Sustained: 0/6 checks (0s/30s)
  Progress: [○○○○○○]
  Total produced: 0 (automation)
  Snapshot tick: 660 (11.0s game time)
  Note: Establishing baseline...
---------------------------------------------"""

BLOCK_LATER = """\
---------------------------------------------
📊 Throughput: engine-unit
---------------------------------------------
  Target rate: 16/60s
  Current rate: 0.0/60s ✗
  Sustained: 0/6 checks (0s/30s)
  Progress: [○○○○○○]
  Last 5: ✗ ✗ ✗ ✗ ✗
           ↑ dip (reset)
  Total produced: 0 (automation)
  Snapshot tick: 34140 (569.0s game time)
  Note: Rate 0.0/60s < quota 16/60s (reset)
---------------------------------------------"""


# =============================================================================
# ProgressDeduper emission policy
# =============================================================================


class TestProgressDeduper:
    def test_first_emission_is_full(self):
        deduper = ProgressDeduper()
        out = deduper.render(BLOCK_BASELINE, turn=0)
        assert out == BLOCK_BASELINE

    def test_verbatim_repeat_becomes_pointer_naming_last_full_turn(self):
        deduper = ProgressDeduper()
        deduper.render(BLOCK_BASELINE, turn=2)
        out = deduper.render(BLOCK_BASELINE, turn=3)
        assert out != BLOCK_BASELINE
        assert "unchanged since turn 2" in out
        # Pointer must be a single line — that is the whole point of the dedupe
        assert "\n" not in out

    def test_changed_content_always_emitted_in_full(self):
        """Honesty invariant: new information is never collapsed to a pointer."""
        deduper = ProgressDeduper()
        deduper.render(BLOCK_BASELINE, turn=0)
        deduper.render(BLOCK_BASELINE, turn=0)  # pointer
        out = deduper.render(BLOCK_LATER, turn=1)
        assert out == BLOCK_LATER

    def test_change_resets_pointer_reference_turn(self):
        deduper = ProgressDeduper()
        deduper.render(BLOCK_BASELINE, turn=0)
        deduper.render(BLOCK_LATER, turn=4)
        out = deduper.render(BLOCK_LATER, turn=5)
        assert "unchanged since turn 4" in out

    def test_periodic_refresh_reemits_full_block(self):
        deduper = ProgressDeduper(refresh_every=3)
        assert deduper.render(BLOCK_BASELINE, turn=0) == BLOCK_BASELINE
        # 3 verbatim repeats -> pointers
        for turn in (1, 2, 3):
            assert "unchanged since turn 0" in deduper.render(BLOCK_BASELINE, turn=turn)
        # 4th repeat hits the refresh threshold -> full block again
        out = deduper.render(BLOCK_BASELINE, turn=4)
        assert out == BLOCK_BASELINE
        # and the pointer reference moves to the refresh turn
        assert "unchanged since turn 4" in deduper.render(BLOCK_BASELINE, turn=5)

    def test_measured_run_sequence_emission_pattern(self):
        """Replay the shape of the measured run: long verbatim plateaus.

        In the 2026-06-10 run the worst plateau was 38 identical emissions.
        With refresh_every=10 a 38-repeat plateau costs 4 full blocks
        (1 initial + 3 refreshes) + 34 pointers instead of 38 full blocks.
        """
        deduper = ProgressDeduper(refresh_every=10)
        emissions = [deduper.render(BLOCK_BASELINE, turn=t) for t in range(38)]
        full = [e for e in emissions if e == BLOCK_BASELINE]
        pointers = [e for e in emissions if e != BLOCK_BASELINE]
        assert len(full) == 4
        assert len(pointers) == 34
        assert all("unchanged since turn" in p for p in pointers)

    def test_refresh_every_must_be_positive(self):
        with pytest.raises(ValueError):
            ProgressDeduper(refresh_every=0)


# =============================================================================
# Static-prefix cache_control annotation
# =============================================================================


class TestApplyCacheControlToStaticPrefix:
    SYSTEM = {"role": "system", "content": "You are a Factorio automation agent."}
    USER = {"role": "user", "content": "Begin."}
    ASSISTANT = {"role": "assistant", "content": "On it."}

    def test_annotates_leading_system_message(self):
        out = apply_cache_control_to_static_prefix([self.SYSTEM, self.USER])
        assert out[0]["role"] == "system"
        assert out[0]["content"] == [
            {
                "type": "text",
                "text": "You are a Factorio automation agent.",
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def test_message_order_and_other_messages_unchanged(self):
        msgs = [self.SYSTEM, self.USER, self.ASSISTANT]
        out = apply_cache_control_to_static_prefix(msgs)
        assert len(out) == 3
        assert out[1] is msgs[1]
        assert out[2] is msgs[2]

    def test_input_list_not_mutated(self):
        msgs = [dict(self.SYSTEM), dict(self.USER)]
        apply_cache_control_to_static_prefix(msgs)
        assert msgs[0]["content"] == "You are a Factorio automation agent."

    def test_no_system_prefix_returns_input_unchanged(self):
        msgs = [dict(self.USER)]
        out = apply_cache_control_to_static_prefix(msgs)
        assert out is msgs

    def test_block_structured_system_content_left_alone(self):
        msgs = [
            {"role": "system", "content": [{"type": "text", "text": "already blocks"}]},
            dict(self.USER),
        ]
        out = apply_cache_control_to_static_prefix(msgs)
        assert out is msgs

    def test_empty_messages_returns_input(self):
        assert apply_cache_control_to_static_prefix([]) == []


# =============================================================================
# Factory gating: cache_control only for Anthropic models
# =============================================================================


class TestAnthropicModelGate:
    def test_anthropic_namespaced_model_is_gated_on(self):
        from FactoryVerse.infra.llm.client.factory import _is_anthropic_model

        assert _is_anthropic_model("anthropic/claude-sonnet-4.6") is True
        assert _is_anthropic_model("claude-sonnet-4-6") is True

    def test_non_anthropic_models_are_gated_off(self):
        from FactoryVerse.infra.llm.client.factory import _is_anthropic_model

        assert _is_anthropic_model("openai/gpt-4.1") is False
        assert _is_anthropic_model("prime-intellect/intellect-3") is False
        assert _is_anthropic_model("deepseek/deepseek-v3") is False
        assert _is_anthropic_model(None) is False
