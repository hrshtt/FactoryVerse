"""Offline reproductions for issues found in Codex freeplay run 004.

These tests deliberately separate three outcomes:

* an expected-failure contract test for a known open bug;
* a documentation-liveness test that fails on the advertised surface itself;
* a passing characterization that proves the current score lacks the evidence
  needed to distinguish machine output from unattended automation.

Strict xfails are intentional: once the contract is fixed they become XPASS
failures and must be promoted to ordinary regression tests.
"""

from __future__ import annotations

import importlib
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from FactoryVerse.evals.freeplay.checkpoint import FreeplayCheckpointService
from FactoryVerse.game.agent.embodied_actions.walking import (
    MovementAction,
    WalkingUnreachableError,
)
from FactoryVerse.game.factory.types import MapPosition
from FactoryVerse.utils.docs.reference.inspection import get_preimported_types


class _QueuedWalkRcon:
    def build_command(self, method, *args):
        assert method == "walk_to"
        return method

    def execute_and_parse_json(self, command):
        assert command == "walk_to"
        return {"success": True, "queued": True, "action_id": "reach-1"}


class _FarCompletedWalkListener:
    async def await_action(self, response, timeout=None):
        assert response.action_id == "reach-1"
        return {
            "status": "completed",
            "result": {"position": {"x": 20.0, "y": 0.0}},
        }


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason=(
        "REACH-1: successful entity-targeted walks are not postvalidated "
        "against the interaction surface"
    ),
)
async def test_reach_1_entity_walk_success_means_in_range_or_structured_failure():
    """A completed entity walk must not return an out-of-range success."""
    movement = MovementAction(_QueuedWalkRcon(), _FarCompletedWalkListener())
    target = MapPosition(x=0.0, y=0.0)

    try:
        final = await movement.walk_to_entity("lab", target)
    except WalkingUnreachableError:
        # A structured failure is an honest contract outcome.
        return

    assert math.dist((final.x, final.y), (target.x, target.y)) <= 10.0


@pytest.mark.xfail(
    strict=True,
    reason="BUG-006: generated pre-imported type module paths are stale aliases",
)
def test_bug_006_every_documented_preimported_type_path_resolves():
    """Every module/type pair printed in the generated API must be importable."""
    failures = []
    for type_name, module_name in get_preimported_types():
        try:
            module = importlib.import_module(module_name)
            getattr(module, type_name)
        except (AttributeError, ModuleNotFoundError) as exc:
            failures.append(f"{type_name} -> {module_name}: {exc}")

    assert failures == []


class _ScoreStore:
    def __init__(self):
        self.scores = []

    def append_score(self, score):
        self.scores.append(score)


class _MachineProductionOnlySource:
    """The scorer receives production totals, but no service-flow evidence."""

    maintenance_transfers = {
        "assembling-machine-1@(-9.5,19.5)": {
            "actor_input": {"iron-plate": 104},
            "actor_output": {"iron-gear-wheel": 52},
        }
    }

    async def get_force_production(self, agent_id):
        assert agent_id == 1
        return {
            "tick": 100,
            "input": {"iron-gear-wheel": 52},
            "output": {"iron-plate": 104},
        }

    async def get_manual_production(self, agent_id):
        assert agent_id == 1
        return {"tick": 100, "crafted": {}, "mined": {}}


@pytest.mark.asyncio
async def test_score_1_machine_output_is_called_automation_without_autonomy_evidence(
    monkeypatch, tmp_path: Path
):
    """Characterize SCORE-1 without inventing a replacement metric schema."""
    source = _MachineProductionOnlySource()
    monkeypatch.setattr(
        "FactoryVerse.evals.freeplay.checkpoint.RCONSource",
        lambda *args, **kwargs: source,
    )
    store = _ScoreStore()
    tier3 = SimpleNamespace(
        instance="server_0",
        rcon_helper=object(),
        run_lua=lambda code: {
            "tick": 100,
            "rockets_launched": 0,
            "researched_technology_count": 1,
        },
    )
    tier4 = SimpleNamespace(agent_numeric_id=1, remote_view=None)
    infra = SimpleNamespace(get_script_output_dir=lambda instance: tmp_path)
    environment = SimpleNamespace(
        tier3=tier3,
        tier4=tier4,
        config=SimpleNamespace(infra_config=infra),
    )

    score = await FreeplayCheckpointService(store, environment).capture_score(
        reason="score-1-reproduction"
    )

    assert source.maintenance_transfers
    assert score["automation_produced_items"] == {"iron-gear-wheel": 52}
    assert score["automation_produced_total"] == 52
    assert not any(
        "autonomous" in key or "maintenance" in key or "actor_absence" in key
        for key in score
    )
    assert store.scores == [score]
