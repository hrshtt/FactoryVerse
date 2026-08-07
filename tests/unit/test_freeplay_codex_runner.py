import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from FactoryVerse.evals.freeplay.codex_runner import (
    ACTION_SCHEMA,
    CodexAppServerActionClient,
    CodexCliClient,
    CodexFreeplayRunner,
    CodexInvocation,
    CodexRunnerError,
    _validate_action,
    codex_harness_configuration,
    supervisor_owned_codex_configuration,
)
from FactoryVerse.integrations.codex import CodexTurnResult
from FactoryVerse.evals.freeplay.codex_context import FREEPLAY_DEVELOPER_INSTRUCTIONS


def _fake_codex(tmp_path: Path) -> Path:
    executable = tmp_path / "fake-codex"
    executable.write_text(
        """#!/usr/bin/env python3
import json
import pathlib
import sys

args = sys.argv[1:]
if args == ["--version"]:
    print("codex-cli 9.9.9")
    raise SystemExit(0)

assert "--config" in args
assert args[args.index("--config") + 1] == 'sandbox_mode="workspace-write"'

output = pathlib.Path(args[args.index("--output-last-message") + 1])
resuming = "resume" in args
action = {
    "state_summary": "continued" if resuming else "started",
    "action": "report_complete" if resuming else "execute",
    "code": "" if resuming else "print('hello')",
    "reason": "test response",
}
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(action))
print(json.dumps({"type": "thread.started", "thread_id": "thread-test-123"}))
print(json.dumps({"type": "turn.completed"}))
""",
        encoding="utf-8",
    )
    os.chmod(executable, 0o755)
    return executable


def test_codex_cli_client_uses_jsonl_pipe_protocol_and_resumes(tmp_path):
    executable = _fake_codex(tmp_path)
    workspace = tmp_path / "workspace"
    control = tmp_path / "control"
    workspace.mkdir()
    control.mkdir()
    (control / "next-action.schema.json").write_text(json.dumps(ACTION_SCHEMA))
    client = CodexCliClient(
        executable=str(executable),
        model="test-model",
        workspace=workspace,
        control_dir=control,
        timeout_seconds=10,
    )

    async def run():
        assert await client.version() == "codex-cli 9.9.9"
        first = await client.invoke(turn=1, thread_id=None)
        second = await client.invoke(turn=2, thread_id=first.thread_id)
        return first, second

    first, second = asyncio.run(run())

    assert first.action["action"] == "execute"
    assert second.action["action"] == "report_complete"
    assert first.thread_id == second.thread_id == "thread-test-123"
    events = (control / "codex-events.jsonl").read_text().splitlines()
    assert len(events) == 4
    assert all(json.loads(line)["type"] for line in events)


def test_validate_action_rejects_lifecycle_and_ambiguous_report():
    with pytest.raises(CodexRunnerError, match="Unsupported"):
        _validate_action(
            {
                "state_summary": "",
                "action": "checkpoint",
                "code": "",
                "reason": "try lifecycle",
            }
        )
    with pytest.raises(CodexRunnerError, match="must have empty code"):
        _validate_action(
            {
                "state_summary": "",
                "action": "report_complete",
                "code": "print('should not run')",
                "reason": "done",
            }
        )


class _FakeCodexAppServer:
    def __init__(self):
        self.calls = []

    async def start_thread(self, **kwargs):
        self.calls.append(("thread/start", kwargs))
        return "app-thread-1"

    async def run_turn(self, **kwargs):
        self.calls.append(("turn/start", kwargs))
        return CodexTurnResult(
            thread_id="app-thread-1",
            turn_id="app-turn-1",
            text=json.dumps(
                {
                    "state_summary": "starting",
                    "action": "execute",
                    "code": "print('hello')",
                    "reason": "begin",
                }
            ),
        )


def test_app_server_action_client_supplies_task_without_codex_goal(tmp_path):
    client = CodexAppServerActionClient(
        executable="codex",
        model="test-model",
        workspace=tmp_path / "workspace",
        control_dir=tmp_path / "control",
        timeout_seconds=10,
        task_objective="build durable production",
        developer_instructions="stable developer contract",
    )
    server = _FakeCodexAppServer()
    client._server = server

    invocation = asyncio.run(client.invoke(turn=1, thread_id=None))

    assert invocation.thread_id == "app-thread-1"
    assert [call[0] for call in server.calls] == [
        "thread/start",
        "turn/start",
    ]
    assert server.calls[0][1]["developer_instructions"] == ("stable developer contract")
    prompt = server.calls[1][1]["prompt"]
    assert "Campaign objective:" in prompt
    assert "build durable production" in prompt
    assert "active Codex Goal" not in prompt


def test_factoryverse_app_server_disables_goal_automatic_continuation(tmp_path):
    client = CodexAppServerActionClient(
        executable="codex",
        model="test-model",
        workspace=tmp_path / "workspace",
        control_dir=tmp_path / "control",
        timeout_seconds=10,
        task_objective="build durable production",
    )

    assert client._server.disabled_features == ("goals",)


def test_runner_rejects_prompt_or_task_drift_from_manifest():
    configuration = supervisor_owned_codex_configuration(
        codex_harness_configuration(
            codex_version="codex-cli 9.9.9",
            max_turns=10,
            checkpoint_every=5,
            codex_timeout=30,
            execution_timeout=10,
            maximum_execution_timeout=20,
            factory_debug=True,
        ),
        "build durable production",
    )
    runner = object.__new__(CodexFreeplayRunner)
    runner.supervisor = SimpleNamespace(
        store=SimpleNamespace(manifest=lambda: {"harness_configuration": configuration})
    )
    runner.client = SimpleNamespace(
        developer_instructions="changed",
        task_objective="changed",
    )

    with pytest.raises(CodexRunnerError, match="developer instructions differ"):
        runner._validate_codex_context_identity()

    runner.client.developer_instructions = FREEPLAY_DEVELOPER_INSTRUCTIONS
    with pytest.raises(CodexRunnerError, match="task objective differs"):
        runner._validate_codex_context_identity()


class _FakeStore:
    def __init__(self, root: Path, api: Path, schema: Path):
        self.paths = type(
            "Paths",
            (),
            {"root": root, "protocol_log": root / "runtime-protocol.jsonl"},
        )()
        self._manifest = {
            "agent_id": "agent_1",
            "harness_configuration": {
                "adapter_protocol_version": 4,
                "codex_goals_feature": False,
                "turn_owner": "factoryverse-supervisor",
            },
            "documentation": {
                "api_reference": str(api),
                "schema_reference": str(schema),
            }
        }
        self._checkpoints = []

    def manifest(self):
        return self._manifest

    def checkpoint_records(self):
        return list(self._checkpoints)


class _FakeSupervisor:
    def __init__(self, store):
        self.store = store
        self.checkpoint_reasons = []
        self.environment = SimpleNamespace(tier3=_FakeTier3())

    async def checkpoint(self, reason):
        self.checkpoint_reasons.append(reason)
        value = {
            "checkpoint_id": f"cp-{len(self.checkpoint_reasons)}",
            "reason": reason,
        }
        self.store._checkpoints.append(value)
        return value


class _FakeTier3:
    def __init__(self):
        self.tick = 10

    def run_lua(self, source):
        assert '"get_reachable", true' in source
        self.tick += 1
        return {
            "tick": self.tick,
            "actor": {
                "agent_id": 1,
                "tick": self.tick,
                "position": {"x": 0, "y": 0},
                "state": {
                    "walking": {"active": False},
                    "mining": {"active": False},
                    "crafting": {"active": False, "queue_length": 0},
                },
            },
            "inventory": {"wood": 1},
            "interactable": {
                "tick": self.tick,
                "agent_position": {"x": 0, "y": 0},
                "entities": [],
                "resources": [{"name": "coal", "position": {"x": 1, "y": 0}}],
                "ghosts": [],
            },
        }


class _FakeActor:
    def __init__(self, supervisor, **kwargs):
        self.execution_count = 0

    def describe(self, preflight):
        return {"event": "ready", "game_tick": preflight["game_tick"]}

    async def handle(self, request):
        if request["op"] == "status":
            events = []
            if self.execution_count:
                events = [
                    {
                        "notification_type": "research_finished",
                        "agent_id": 1,
                        "tick": 20,
                        "data": {"technology": "automation-science-pack"},
                        "critical": True,
                    }
                ]
            return {
                "id": request["id"],
                "ok": True,
                "op": "status",
                "game_tick": 20,
                "game_events": events,
            }

        self.execution_count += 1
        return {
            "id": request["id"],
            "ok": True,
            "op": "execute",
            "output": "hello",
            "game_events": [],
            "source_sha256": request["source_sha256"],
        }


class _FakeClient:
    def __init__(self, workspace: Path, control_dir: Path):
        self.workspace = workspace
        self.control_dir = control_dir
        self.model = "test-model"

    async def invoke(self, *, turn, thread_id):
        live_state = json.loads((self.control_dir / "codex-state.json").read_text())
        assert live_state["phase"] == "codex_inference"
        assert live_state["pending_codex_turn"] == turn
        if turn == 1:
            action = {
                "state_summary": "ran hello",
                "action": "execute",
                "code": "print('hello')",
                "reason": "inspect runtime",
            }
        else:
            observation = json.loads(
                (self.workspace / "last-observation.json").read_text()
            )
            assert observation["event"] == "interturn_game_events"
            assert observation["game_events"][0]["data"] == {
                "technology": "automation-science-pack"
            }
            assert observation["previous_observation"]["event"] == "execution_result"
            action = {
                "state_summary": "done",
                "action": "report_complete",
                "code": "",
                "reason": "bounded test complete",
            }
        return CodexInvocation(action=action, thread_id="thread-1", returncode=0)


def test_codex_runner_keeps_lifecycle_in_supervisor(monkeypatch, tmp_path):
    api = tmp_path / "api.md"
    schema = tmp_path / "schema.md"
    api.write_text("api")
    schema.write_text("schema")
    campaign_root = tmp_path / "campaign"
    store = _FakeStore(campaign_root, api, schema)
    supervisor = _FakeSupervisor(store)
    client = _FakeClient(campaign_root / "harness-workspace", campaign_root / "control")
    monkeypatch.setattr(
        "FactoryVerse.evals.freeplay.codex_runner.ActorRuntimeSession", _FakeActor
    )
    runner = CodexFreeplayRunner(
        supervisor,
        client,
        max_turns=3,
        checkpoint_every=1,
        execution_timeout=5,
        maximum_execution_timeout=10,
        notification_debug=True,
    )

    result = asyncio.run(runner.run({"game_tick": 10}))

    assert result["session_executions"] == 1
    assert result["reason"].startswith("codex_report_complete")
    assert supervisor.checkpoint_reasons == ["codex_baseline", "codex_periodic_1"]
    state = json.loads((client.control_dir / "codex-state.json").read_text())
    assert state["thread_id"] == "thread-1"
    assert state["turns_completed"] == 2
    assert state["phase"] == "terminal"
    assert (
        json.loads((client.workspace / "last-observation.json").read_text())["event"]
        == "report_complete_acknowledged"
    )
    interactable = json.loads(
        (client.control_dir / "current-interactable-state.json").read_text()
    )
    assert interactable["ownership"] == "harness"
    assert interactable["replacement_semantics"] == "supersedes_all_previous_snapshots"
    assert interactable["interactable"]["resources"][0]["name"] == "coal"
    assert "Notification Debug Mission" in (client.workspace / "MISSION.md").read_text()
    mechanics = (client.workspace / "EARLY_GAME_MECHANICS.md").read_text()
    assert "Producing 50 iron plates" in mechanics
    assert "Producing 10 copper plates" in mechanics
    assert "research_finished" in mechanics
    assert (client.workspace / "references" / "INDEX.md").exists()
    campaign_start = json.loads(
        (client.workspace / "CAMPAIGN_START.json").read_text()
    )
    assert campaign_start["captured_game_tick"] == 10
    assert "Immutable campaign-start snapshot" in campaign_start["warning"]
    bug_ledger = client.workspace / "BUGS.md"
    assert "FactoryVerse Bug Ledger" in bug_ledger.read_text()
    bug_ledger.write_text("agent-owned evidence\n")
    runner.prepare_workspace()
    assert bug_ledger.read_text() == "agent-owned evidence\n"


def test_factory_debug_workspace_seeds_durable_scaling_artifacts(monkeypatch, tmp_path):
    api = tmp_path / "api.md"
    schema = tmp_path / "schema.md"
    api.write_text("api")
    schema.write_text("schema")
    campaign_root = tmp_path / "campaign"
    store = _FakeStore(campaign_root, api, schema)
    supervisor = _FakeSupervisor(store)
    client = _FakeClient(campaign_root / "harness-workspace", campaign_root / "control")
    monkeypatch.setattr(
        "FactoryVerse.evals.freeplay.codex_runner.ActorRuntimeSession", _FakeActor
    )
    runner = CodexFreeplayRunner(
        supervisor,
        client,
        max_turns=200,
        checkpoint_every=40,
        execution_timeout=5,
        maximum_execution_timeout=10,
        factory_debug=True,
    )

    runner.prepare_workspace()

    mission = (client.workspace / "MISSION.md").read_text()
    assert "Factory Bootstrap and Scaling Debug Mission" in mission
    assert "Productive-capacity floor" not in mission
    assert "4 iron drill-and-furnace cells" not in mission
    assert "live electrical generation is a mandatory" not in mission
    assert "single highest-leverage bottleneck" not in mission
    assert "Start with reconnaissance" not in mission
    assert "smallest coherent expansion" not in mission
    assert "Only use `report_complete` after a rocket" in mission
    assert (client.workspace / "FACTORY_PLAN.md").exists()
    progress = client.workspace / "PROGRESS.md"
    assert "Update this durable log" in progress.read_text()
    progress.write_text("agent progress\n")
    runner.prepare_workspace()
    assert progress.read_text() == "agent progress\n"


def test_debug_profiles_are_mutually_exclusive(tmp_path):
    with pytest.raises(ValueError, match="mutually exclusive"):
        CodexFreeplayRunner(
            object(),
            SimpleNamespace(workspace=tmp_path, control_dir=tmp_path),
            max_turns=1,
            checkpoint_every=0,
            execution_timeout=5,
            maximum_execution_timeout=10,
            notification_debug=True,
            factory_debug=True,
        )
