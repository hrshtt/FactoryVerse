import hashlib
import io
import queue
from types import SimpleNamespace

import pytest

from FactoryVerse.evals.freeplay.actor_session import ActorRuntimeSession
from FactoryVerse.evals.freeplay.runtime_host import FreeplayRuntimeHost
from FactoryVerse.game.agent.event_stream import EventStream


class _Store:
    campaign_id = "actor-session-test"

    def __init__(self):
        self.protocol = []
        self.session_updates = []

    def manifest(self):
        return {
            "agent_id": "agent_7",
            "documentation": {"api_reference": "/docs/api.md"},
            "capability_profile": "production",
        }

    def append_protocol(self, event):
        self.protocol.append(event)

    def update_session(self, session_id, **updates):
        self.session_updates.append((session_id, updates))


class _Tier3:
    def __init__(self):
        self.tick = 10

    def get_game_tick(self):
        return self.tick


class _Tier4:
    agent_id = "agent_7"
    trajectory_writer = None

    def __init__(self):
        self.sources = []
        self.events = None

    async def execute_code(self, source, compress_output=False):
        self.sources.append((source, compress_output))
        return "done"


def _session():
    store = _Store()
    tier3 = _Tier3()
    tier4 = _Tier4()
    supervisor = SimpleNamespace(
        store=store,
        session_id="runtime-session-1",
        environment=SimpleNamespace(tier3=tier3, tier4=tier4),
    )
    return ActorRuntimeSession(supervisor), store, tier4


def test_ready_descriptor_binds_transport_to_one_actor_runtime():
    session, _, _ = _session()

    ready = session.describe({"game_tick": 10})

    assert ready["protocol_version"] == 3
    assert ready["actor_id"] == "agent_7"
    assert ready["runtime_session_id"] == "runtime-session-1"
    assert ready["operations"] == ["status", "execute"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["checkpoint", "close", "reset", "spawn"])
async def test_actor_cannot_invoke_campaign_or_body_lifecycle(operation):
    session, store, tier4 = _session()

    response = await session.handle({"id": "blocked", "op": operation})

    assert response["ok"] is False
    assert response["error"]["kind"] == "forbidden_operation"
    assert response["actor_id"] == "agent_7"
    assert tier4.sources == []
    assert store.protocol[-1]["direction"] == "actor_response"


@pytest.mark.asyncio
async def test_execute_records_actor_identity_and_submitted_source_provenance():
    session, store, tier4 = _session()
    source = "print('build')"
    source_sha256 = hashlib.sha256(source.encode()).hexdigest()

    response = await session.handle(
        {
            "id": "execute-1",
            "op": "execute",
            "source": source,
            "logical_path": "skills/build.py",
            "source_sha256": source_sha256,
            "compress_output": True,
        }
    )

    assert response["ok"] is True
    assert response["output"] == "done"
    assert response["actor_id"] == "agent_7"
    assert response["runtime_session_id"] == "runtime-session-1"
    assert response["source_sha256"] == source_sha256
    assert response["logical_path"] == "skills/build.py"
    assert tier4.sources == [(source, True)]
    assert store.session_updates == [
        (
            "runtime-session-1",
            {"execution_count": 1, "last_game_tick": 10},
        )
    ]
    assert store.protocol[0]["actor_id"] == "agent_7"
    assert store.protocol[0]["request"]["source"] == source


@pytest.mark.asyncio
async def test_execute_preserves_multiline_error_headline():
    session, _, tier4 = _session()

    async def fail(source, compress_output=False):
        return (
            "Error: RuntimeError: Agent is already walking\n"
            "stack traceback:\n"
            '\t[string "..."]:1: in main chunk'
        )

    tier4.execute_code = fail
    response = await session.handle(
        {"id": "execute-error", "op": "execute", "source": "await walking.walk_to(...)"}
    )

    assert response["ok"] is False
    assert response["error"]["message"] == "RuntimeError: Agent is already walking"
    assert "stack traceback" in response["output"]


@pytest.mark.asyncio
async def test_execute_delivers_pending_game_events_to_coding_harness():
    session, _, tier4 = _session()
    notifications = queue.Queue()
    notifications.put(
        {
            "notification_type": "research_finished",
            "agent_id": 7,
            "tick": 420,
            "data": {
                "technology": "automation-science-pack",
                "unlocked_recipes": ["automation-science-pack"],
                "effects": [
                    {"type": "unlock-recipe", "recipe": "automation-science-pack"}
                ],
            },
        }
    )
    tier4.events = EventStream(notifications)

    response = await session.handle(
        {"id": "execute-events", "op": "execute", "source": "print('crafted')"}
    )

    assert response["ok"] is True
    assert response["game_events"] == [
        {
            "notification_type": "research_finished",
            "agent_id": 7,
            "tick": 420,
            "data": {
                "technology": "automation-science-pack",
                "unlocked_recipes": ["automation-science-pack"],
                "effects": [
                    {"type": "unlock-recipe", "recipe": "automation-science-pack"}
                ],
            },
            "critical": True,
        }
    ]
    assert notifications.empty()


@pytest.mark.asyncio
async def test_execute_rejects_a_mismatched_source_hash_without_running_code():
    session, _, tier4 = _session()

    response = await session.handle(
        {
            "id": "execute-bad-hash",
            "op": "execute",
            "source": "print('no')",
            "source_sha256": "0" * 64,
        }
    )

    assert response["ok"] is False
    assert response["error"]["kind"] == "source_hash_mismatch"
    assert tier4.sources == []


@pytest.mark.asyncio
async def test_execute_rejects_a_non_finite_timeout_without_running_code():
    session, _, tier4 = _session()

    response = await session.handle(
        {
            "id": "execute-bad-timeout",
            "op": "execute",
            "source": "print('no')",
            "timeout_seconds": "nan",
        }
    )

    assert response["ok"] is False
    assert response["error"]["kind"] == "invalid_request"
    assert tier4.sources == []


@pytest.mark.asyncio
async def test_status_reports_actor_runtime_state_not_campaign_control_state():
    session, _, _ = _session()

    response = await session.handle({"id": "status-1", "op": "status"})

    assert response["ok"] is True
    assert response["game_tick"] == 10
    assert response["execution_count"] == 0
    assert "campaign" not in response


class _FinishingSupervisor:
    def __init__(self):
        self.finish_calls = []

    async def finish(self, **kwargs):
        self.finish_calls.append(kwargs)
        return {"classification": "paused"}


class _HostActorSession:
    execution_count = 3

    def describe(self, preflight):
        return {"event": "ready", "game_tick": preflight["game_tick"]}


@pytest.mark.asyncio
async def test_stdio_eof_is_a_supervisor_owned_finalization(monkeypatch):
    supervisor = _FinishingSupervisor()
    host = object.__new__(FreeplayRuntimeHost)
    host.supervisor = supervisor
    host.actor_session = _HostActorSession()
    monkeypatch.setattr("FactoryVerse.evals.freeplay.runtime_host.sys.stdin", io.StringIO(""))
    monkeypatch.setattr(host, "_emit", lambda payload: None)

    result = await host.serve_stdio({"game_tick": 10})

    assert result == {"classification": "paused"}
    assert supervisor.finish_calls == [
        {
            "reason": "actor_transport_eof",
            "checkpoint": True,
            "execution_count": 3,
        }
    ]


class _BrokenInput:
    def readline(self):
        raise OSError("transport broke")


@pytest.mark.asyncio
async def test_stdio_error_still_finalizes_the_owned_runtime(monkeypatch):
    supervisor = _FinishingSupervisor()
    host = object.__new__(FreeplayRuntimeHost)
    host.supervisor = supervisor
    host.actor_session = _HostActorSession()
    monkeypatch.setattr(
        "FactoryVerse.evals.freeplay.runtime_host.sys.stdin", _BrokenInput()
    )
    monkeypatch.setattr(host, "_emit", lambda payload: None)

    with pytest.raises(OSError, match="transport broke"):
        await host.serve_stdio({"game_tick": 10})

    assert supervisor.finish_calls == [
        {
            "reason": "actor_transport_error",
            "checkpoint": True,
            "execution_count": 3,
        }
    ]
