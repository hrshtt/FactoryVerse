"""Offline reproductions for issues found in Codex freeplay run 004.

These tests deliberately separate three outcomes:

* a regression contract for authoritative entity-walk completion;
* a documentation-liveness test that fails on the advertised surface itself;
* a passing characterization that proves the current score lacks the evidence
  needed to distinguish machine output from unattended automation.

Strict xfails are intentional: once the contract is fixed they become XPASS
failures and must be promoted to ordinary regression tests.
"""

from __future__ import annotations

import importlib
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
async def test_reach_1_entity_walk_rejects_unvalidated_completion():
    """Entity completion requires Factorio's authoritative reach marker."""
    movement = MovementAction(_QueuedWalkRcon(), _FarCompletedWalkListener())
    target = MapPosition(x=0.0, y=0.0)

    with pytest.raises(WalkingUnreachableError) as exc_info:
        await movement.walk_to_entity("lab", target)

    assert exc_info.value.failure_type == "interaction_unvalidated"


class _BoundaryReachableWalkListener:
    async def await_action(self, response, timeout=None):
        assert response.action_id == "reach-1"
        return {
            "status": "completed",
            "result": {
                "position": {"x": 10.2, "y": 0.0},
                "interaction_reachable": True,
            },
        }


@pytest.mark.asyncio
async def test_reach_1_entity_walk_accepts_authoritative_boundary_reach():
    """Do not replace Factorio boundary reach with a center-distance cutoff."""
    movement = MovementAction(_QueuedWalkRcon(), _BoundaryReachableWalkListener())

    final = await movement.walk_to_entity("lab", MapPosition(x=0.0, y=0.0))

    assert final == MapPosition(x=10.2, y=0.0)


class _ImmediateReachableWalkRcon:
    def build_command(self, method, *args):
        assert method == "walk_to"
        return method

    def execute_and_parse_json(self, command):
        assert command == "walk_to"
        return {
            "success": True,
            "queued": False,
            "action_id": "reach-immediate",
            "position": {"x": 3.0, "y": 4.0},
            "interaction_reachable": True,
        }


class _UnusedWalkListener:
    async def await_action(self, response, timeout=None):
        raise AssertionError("immediate completion must not wait for UDP")


@pytest.mark.asyncio
async def test_reach_1_immediate_entity_walk_preserves_reach_confirmation():
    movement = MovementAction(_ImmediateReachableWalkRcon(), _UnusedWalkListener())

    final = await movement.walk_to_entity("lab", MapPosition(x=0.0, y=0.0))

    assert final == MapPosition(x=3.0, y=4.0)


def test_bug_006_every_documented_preimported_type_path_resolves():
    """Every module/type pair printed in the generated API must be importable.

    BUG-006 (fixed): the table used to hardcode stale ``FactoryVerse.agent.*`` /
    ``FactoryVerse.factory.*`` aliases. The paths are now read off each class's
    ``__module__``, so this is a regression guard against re-transcribing them.
    """
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
