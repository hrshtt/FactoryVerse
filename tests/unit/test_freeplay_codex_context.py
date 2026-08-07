import json
from types import SimpleNamespace

from FactoryVerse.evals.freeplay.codex_context import (
    FREEPLAY_DEVELOPER_INSTRUCTIONS,
    InteractableStateFile,
    freeplay_goal,
)


class _Tier3:
    def __init__(self):
        self.tick = 100

    def run_lua(self, source):
        assert 'remote.call(interface_name, "inspect", true)' in source
        assert 'remote.call(interface_name, "get_reachable", true)' in source
        self.tick += 1
        return {
            "tick": self.tick,
            "actor": {"position": {"x": 1, "y": 2}, "state": {}},
            "inventory": {"coal": 3},
            "interactable": {
                "tick": self.tick,
                "entities": [{"name": "stone-furnace"}],
                "resources": [{"name": "coal"}],
                "ghosts": [],
            },
        }


class _Store:
    def manifest(self):
        return {"agent_id": "agent_1"}


def test_interactable_state_is_atomically_replaced_not_accumulated(tmp_path):
    tier3 = _Tier3()
    supervisor = SimpleNamespace(
        environment=SimpleNamespace(tier3=tier3),
        store=_Store(),
    )
    path = tmp_path / "control" / "current-interactable-state.json"
    state = InteractableStateFile(path)

    first = state.refresh(supervisor, reason="after_execution_1")
    second = state.refresh(supervisor, reason="after_execution_2")

    on_disk = json.loads(path.read_text())
    assert first["tick"] == 101
    assert second["tick"] == 102
    assert second["available"] is True
    assert on_disk == second
    assert path.read_text().count('"schema_version"') == 1
    assert not list(path.parent.glob(".current-interactable-state.json.tmp-*"))


def test_prompt_goal_and_live_state_have_distinct_ownership():
    goal = freeplay_goal(factory_debug=True)

    assert "persistent Python runtime" in FREEPLAY_DEVELOPER_INSTRUCTIONS
    assert "current-interactable-state.json" in FREEPLAY_DEVELOPER_INSTRUCTIONS
    assert "query `remote_view` or DuckDB" in FREEPLAY_DEVELOPER_INSTRUCTIONS
    assert "largest sustainably productive factory" in goal
    assert len(goal) <= 4000


def test_failed_refresh_replaces_prior_state_with_unavailable_marker(tmp_path):
    path = tmp_path / "current-interactable-state.json"
    state = InteractableStateFile(path)
    path.write_text('{"tick": 42}\n')

    state.mark_unavailable(reason="before_turn", error="runtime unavailable")

    on_disk = json.loads(path.read_text())
    assert on_disk["available"] is False
    assert "tick" not in on_disk
    assert on_disk["error"] == "runtime unavailable"
