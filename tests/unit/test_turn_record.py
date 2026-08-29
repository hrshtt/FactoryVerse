"""TURN_CONTRACT §8 gates 1–2: the record holds what the model SAW.

Gate 1 — nonce conformance. A program prints a nonce; the *input* of the
next inference must contain it, inside a tool-role message. This is the
first check above the model boundary: it proves results are delivered in
context, not by a file the model is told to go and read.

Gate 2 — model input recorded per step. From ``trajectory.jsonl`` alone a
reader rebuilds exactly the message list and tool schema the client
received for any inference — including a notification injected between
iterations and a context compression that rewrote the history. Before
this, the record captured outputs only: a model that ignored its result and
one that never received it were indistinguishable.

Also pinned: every tool result is stamped with the game tick before and
after the call (visible to the model as a trailer, and on the record), and
``turn_complete`` says why the turn ended.

Everything runs against a fake LLM client and a fake runtime — no engine,
no provider. The fake runtime really executes the program (that is how the
nonce gets into the result), and its clock advances per call.
"""

from __future__ import annotations

import contextlib
import io
import json
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from FactoryVerse.infra.llm.client.base import (
    ChatCompletionResult,
    ChatCompletionUsage,
    ChatMessage,
    ToolCall,
)
from FactoryVerse.infra.llm.orchestrator import AgentOrchestrator
from FactoryVerse.infra.session.trajectory import (
    EventType,
    TrajectoryReader,
    TrajectoryWriter,
)


# --- fakes -----------------------------------------------------------------


class _FakeClient:
    """Scripted responses; captures every request verbatim (deep-copied)."""

    def __init__(self, scripted: List[ChatMessage]):
        self._scripted = list(scripted)
        self.requests: List[Dict[str, Any]] = []

    def chat_completion(self, messages, tools=None, **_):
        self.requests.append(
            {
                "messages": json.loads(json.dumps(messages)),
                "tools": json.loads(json.dumps(tools)) if tools is not None else None,
            }
        )
        msg = self._scripted.pop(0)
        return ChatCompletionResult(
            message=msg,
            usage=ChatCompletionUsage(10, 5, 15),
            finish_reason="tool_calls" if msg.has_tool_calls else "stop",
            model="fake",
        )


class _FakeEvents:
    def __init__(self):
        self.pending: List[Dict[str, Any]] = []

    async def drain(self, timeout=0.05):
        out, self.pending = self.pending, []
        return out

    def format_events(self, events):
        return "\n".join(e["text"] for e in events)


class _FakeRuntime:
    """Executes programs for real, advances a tick counter per call."""

    TOOLS = [
        {"type": "function", "function": {"name": "execute_dsl", "parameters": {}}},
        {"type": "function", "function": {"name": "execute_duckdb", "parameters": {}}},
    ]

    def __init__(self, tick: Optional[int] = 1000):
        self.events = _FakeEvents()
        self._tick = tick
        self.last_tick_span: Optional[Dict[str, int]] = None

    def get_tool_definitions(self, mode="autonomous"):
        return self.TOOLS

    def get_game_tick(self):
        return self._tick

    def _advance(self, n: int) -> None:
        if self._tick is not None:
            self._tick += n

    async def execute_dsl(self, code: str, metadata=None) -> str:
        before = self._tick
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exec(code, {})
        self._advance(60)
        self.last_tick_span = (
            {"before": before, "after": self._tick} if before is not None else None
        )
        return buf.getvalue().rstrip("\n")

    def execute_duckdb(self, query: str, metadata=None) -> str:
        before = self._tick
        self._advance(1)
        self.last_tick_span = (
            {"before": before, "after": self._tick} if before is not None else None
        )
        return f"rows for: {query}"

    def respond(self, message, metadata=None):
        return message


def _tool_call(cid: str, name: str, **args) -> ToolCall:
    return ToolCall(id=cid, name=name, arguments=json.dumps(args))


def _assistant_with(*calls: ToolCall) -> ChatMessage:
    return ChatMessage(role="assistant", content="", tool_calls=list(calls))


def _make(tmp_path: Path, client, runtime, **kw) -> tuple[AgentOrchestrator, Path]:
    prompt = tmp_path / "system_prompt.md"
    prompt.write_text("You are the fake agent. " * 50)
    traj = tmp_path / "trajectory.jsonl"
    orch = AgentOrchestrator(
        llm_client=client,
        runtime=runtime,
        system_prompt_path=str(prompt),
        trajectory_writer=TrajectoryWriter(traj),
        **kw,
    )
    return orch, traj


# --- gate 1: nonce conformance ------------------------------------------


@pytest.mark.asyncio
async def test_nonce_printed_by_a_program_is_in_the_next_inference_input(tmp_path):
    nonce = f"NONCE-{secrets.token_hex(8)}"
    client = _FakeClient(
        [
            _assistant_with(_tool_call("c1", "execute_dsl", code=f'print("{nonce}")')),
            ChatMessage(role="assistant", content="done"),
        ]
    )
    orch, traj = _make(tmp_path, client, _FakeRuntime())

    await orch.run_turn("go")

    # From the client's side: the second request carries the nonce in a tool message.
    second = client.requests[1]["messages"]
    tool_msgs = [m for m in second if m.get("role") == "tool"]
    assert tool_msgs, "no tool-role message reached the second inference"
    assert any(nonce in (m.get("content") or "") for m in tool_msgs)

    # From the record's side: the same is reconstructible without the client.
    rebuilt = TrajectoryReader(traj).reconstruct_inference_input(turn=0, iteration=2)
    assert rebuilt is not None
    assert any(
        m.get("role") == "tool" and nonce in (m.get("content") or "")
        for m in rebuilt["messages"]
    )


# --- gate 2: full input reconstruction ----------------------------------


@pytest.mark.asyncio
async def test_iteration_three_input_is_rebuilt_from_the_record_alone(tmp_path):
    runtime = _FakeRuntime()
    client = _FakeClient(
        [
            _assistant_with(_tool_call("c1", "execute_dsl", code='print("one")')),
            _assistant_with(_tool_call("c2", "execute_duckdb", query="SELECT 1")),
            ChatMessage(role="assistant", content="finished"),
            # second turn: one inference, ends by text
            ChatMessage(role="assistant", content="turn two"),
        ]
    )
    orch, traj = _make(tmp_path, client, runtime)

    # A notification arrives while the first program runs. Under the turn
    # contract nothing is injected inside a turn (§21): it is drained once at
    # the boundary and is part of the NEXT turn's first input, in the report.
    original = runtime.execute_dsl

    async def execute_and_raise_event(code, metadata=None):
        out = await original(code, metadata)
        runtime.events.pending.append({"text": "Research complete: automation"})
        return out

    runtime.execute_dsl = execute_and_raise_event  # type: ignore[assignment]

    await orch.run_turn("build")
    await orch.run_turn("")

    assert len(client.requests) == 4
    reader = TrajectoryReader(traj)
    for iteration in (1, 2, 3):
        rebuilt = reader.reconstruct_inference_input(turn=0, iteration=iteration)
        assert rebuilt is not None, f"iteration {iteration} missing from record"
        assert rebuilt["messages"] == client.requests[iteration - 1]["messages"]
        assert rebuilt["tools"] == client.requests[iteration - 1]["tools"]

    # Inside turn 0 no user message carried the event.
    turn0_inputs = client.requests[2]["messages"]
    assert not any(
        m.get("role") == "user" and "Research complete" in (m.get("content") or "")
        for m in turn0_inputs
    )
    # The next turn's first input carries it, inside the report, and the
    # record says so.
    turn1_input = reader.reconstruct_inference_input(turn=1, iteration=1)["messages"]
    assert turn1_input == client.requests[3]["messages"]
    assert "Research complete" in turn1_input[-1]["content"]
    events = reader.read_all()
    notes = [e for e in events if e.type == EventType.NOTIFICATION]
    assert len(notes) == 1
    assert notes[0].data["events"] == [{"text": "Research complete: automation"}]
    reports = [e for e in events if e.type == EventType.TURN_REPORT]
    assert reports and reports[0].data["report"]["events"]["count"] == 1


@pytest.mark.asyncio
async def test_context_compression_is_recorded_and_input_still_reconstructs(tmp_path):
    runtime = _FakeRuntime()
    big = "x" * 4000  # ~1000 tokens per result under the 4-chars/token estimate
    client = _FakeClient(
        [
            _assistant_with(_tool_call("c1", "execute_dsl", code=f'print("{big}")')),
            _assistant_with(_tool_call("c2", "execute_dsl", code=f'print("{big}")')),
            _assistant_with(_tool_call("c3", "execute_dsl", code=f'print("{big}")')),
            ChatMessage(role="assistant", content="ok"),
        ]
    )
    # Threshold at 80% of 3000 tokens = 2400; three 1000-token results cross it
    # before iteration 4, with keep_recent_turns=2 so something is dropped.
    orch, traj = _make(
        tmp_path, client, runtime, max_context_tokens=3000, keep_recent_turns=2
    )

    await orch.run_turn("loop")

    reader = TrajectoryReader(traj)
    events = reader.read_all()
    compressions = [e for e in events if e.type == EventType.CONTEXT_COMPRESSED]
    assert compressions, "compression did not fire; the test setup is wrong"
    c = compressions[0].data
    assert c["before_count"] > c["after_count"]
    assert c["removed"], "removed messages must be recorded verbatim"
    assert all("role" in m for m in c["removed"])
    assert c["summary"]["role"] == "user"

    # After the rewrite, the recorded input still equals what the client got.
    for i, req in enumerate(client.requests, start=1):
        rebuilt = reader.reconstruct_inference_input(turn=0, iteration=i)
        assert rebuilt["messages"] == req["messages"], f"iteration {i} diverged"


@pytest.mark.asyncio
async def test_attention_cap_is_named_on_the_record(tmp_path):
    """TURN_CONTRACT §3.1: N tool calls per turn; reaching N ends the turn."""
    from FactoryVerse.environment.config import TurnConfig

    client = _FakeClient(
        [_assistant_with(_tool_call(f"c{i}", "execute_duckdb", query="SELECT 1")) for i in range(10)]
    )
    orch, traj = _make(
        tmp_path, client, _FakeRuntime(), turn_config=TurnConfig(attention_calls=4)
    )

    out = await orch.run_turn("forever")

    assert "Attention budget" in out
    assert len(client.requests) == 4
    done = [e for e in TrajectoryReader(traj).read_all() if e.type == EventType.TURN_COMPLETE]
    assert done[-1].data["ended_by"] == "attention_cap"


@pytest.mark.asyncio
async def test_no_engine_means_no_tick_never_a_fake_one(tmp_path):
    client = _FakeClient(
        [
            _assistant_with(_tool_call("c1", "execute_duckdb", query="SELECT 1")),
            ChatMessage(role="assistant", content="ok"),
        ]
    )
    orch, traj = _make(tmp_path, client, _FakeRuntime(tick=None))

    await orch.run_turn("x")

    events = TrajectoryReader(traj).read_all()
    result = [e for e in events if e.type == EventType.TOOL_RESULT][0]
    assert result.data["game_tick_before"] is None and result.data["game_tick_after"] is None
    inp = [e for e in events if e.type == EventType.INFERENCE_INPUT][0]
    assert inp.data["game_tick"] is None


def test_legacy_readers_accept_the_new_event_types(tmp_path):
    """The live viewer's loader and build_turns must not choke on new events."""
    from FactoryVerse.infra.llm.trajectory import TrajectoryManager

    traj = tmp_path / "t.jsonl"
    w = TrajectoryWriter(traj)
    sha = w.system_prompt("p")
    w.user_message("hi", turn=0)
    w.inference_input(0, 1, [{"role": "system", "content": "p"}, {"role": "user", "content": "hi"}], [{"a": 1}], 5, sha)
    w.inference_output(0, 1, {"role": "assistant", "content": "yo"})
    w.context_compressed(0, 5, 3, [{"role": "user", "content": "old"}], {"role": "user", "content": "sum"})
    w.notification("**Game Events:**\n\nx", turn=0, index=2, events=[{"t": 1}])
    w.assistant_response("yo", turn=0)
    w.turn_complete(turn=0, ended_by="text_response")

    reader = TrajectoryReader(traj)
    turns = reader.build_turns()
    assert turns[0].assistant_response == "yo"
    assert turns[0].notifications == ["**Game Events:**\n\nx"]
    TrajectoryManager().load_from_trajectory_events(reader.read_all())
    rebuilt = reader.reconstruct_inference_input(0, 1)
    assert rebuilt["messages"][0] == {"role": "system", "content": "p"}
    assert rebuilt["tools"] == [{"a": 1}]


# --- the real adapter's clock trailer ------------------------------------


class _Tier3:
    def __init__(self):
        self.tick = 500

    def get_game_tick(self):
        self.tick += 30
        return self.tick


class _Tier4:
    remote_view = None
    events = None

    class _DB:
        def execute(self, q):
            class _C:
                description = [("n",)]

                def fetchall(self):
                    return [(1,)]

            return _C()

    database = _DB()

    async def execute_code(self, code, compress_output=False):
        return "printed"


@pytest.mark.asyncio
async def test_real_adapter_stamps_both_tools_with_the_visible_clock():
    from FactoryVerse.environment.tiers.tier6_interaction import _RuntimeAdapter

    adapter = _RuntimeAdapter(_Tier3(), _Tier4())

    out = await adapter.execute_dsl("print(1)")
    assert out.endswith("[tick 530→560, +30]"), out
    assert adapter.last_tick_span == {"before": 530, "after": 560}

    out = adapter.execute_duckdb("SELECT 1 AS n")
    assert out.endswith("[tick 590→620, +30]"), out
    assert adapter.last_tick_span == {"before": 590, "after": 620}

    # A refused statement never touches the engine and carries no span.
    refused = adapter.execute_duckdb("DELETE FROM map_entity")
    assert "[tick" not in refused and adapter.last_tick_span is None


@pytest.mark.asyncio
async def test_real_adapter_without_an_engine_omits_the_trailer():
    from FactoryVerse.environment.tiers.tier6_interaction import _RuntimeAdapter

    adapter = _RuntimeAdapter(None, _Tier4())
    assert adapter.get_game_tick() is None
    out = await adapter.execute_dsl("print(1)")
    assert out == "printed" and adapter.last_tick_span is None
