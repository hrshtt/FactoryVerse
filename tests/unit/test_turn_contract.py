"""TURN_CONTRACT §3–§7 on the in-repo orchestrator (Phase 2C).

What is pinned here, each against a fake client and a fake runtime whose
clock the test controls:

(a) the tick ledger reconciles — used + advanced == tick delta;
(b) the attention cap ends the turn (see also test_turn_record.py);
(c) the report renders every section from fixture inputs and thresholds
    positions so a large base yields a small report;
(d) a planning turn refuses body verbs by NameError and advances zero;
(e) the drain happens exactly once per turn, after the fast-forward;
(f) status_dump.changed on two fixture blocks yields the transitions;
(g) end_turn fast-forwards max(0, T − used) and the next turn opens with
    the report as its first input; a research completion makes the next
    turn a planning turn.

None of this touches an engine. The live counterpart (advance_world lands
exactly, the ledger reconciles on a real server) is
tests/live/test_turn_contract.py.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from FactoryVerse.environment.config import TurnConfig
from FactoryVerse.game.agent import status_dump, turn_report
from FactoryVerse.infra.llm.client.base import (
    ChatCompletionResult,
    ChatCompletionUsage,
    ChatMessage,
    ToolCall,
)
from FactoryVerse.infra.llm.orchestrator import AgentOrchestrator
from FactoryVerse.infra.session.trajectory import EventType, TrajectoryReader, TrajectoryWriter


# --- fakes -----------------------------------------------------------------


class _Event:
    """A typed-looking event, like GameEvent."""

    def __init__(self, ntype: str, tick: int, data: Optional[Dict[str, Any]] = None, seq: Optional[int] = None):
        self.notification_type = ntype
        self.tick = tick
        self.data = data or {}
        self.seq = seq
        self.epoch = 1 if seq is not None else None

    def to_dict(self):
        d = {"notification_type": self.notification_type, "tick": self.tick, "data": self.data}
        if self.seq is not None:
            d["epoch"], d["seq"] = self.epoch, self.seq
        return d


class _Events:
    def __init__(self):
        self.pending: List[Any] = []
        self.drains: List[int] = []  # tick at each drain

    def bind(self, runtime):
        self._rt = runtime

    async def drain(self, timeout=0.05):
        self.drains.append(self._rt._tick)
        out, self.pending = self.pending, []
        return out

    def format_events(self, events):
        return "\n".join(str(getattr(e, "notification_type", e)) for e in events)


class _Runtime:
    """A world with a controllable clock and the report's reads."""

    def __init__(self, tick: int = 1000):
        self._tick = tick
        self.events = _Events()
        self.events.bind(self)
        self.last_tick_span = None
        self.turn_mode = "gameplay"
        self.plan_store = turn_report.PlanStore(None)
        self.advances: List[int] = []
        self.production = {"input": {}, "output": {"iron-plate": 100}}
        self.inventory = {"iron-plate": 10}
        self.entities: Dict = {}
        self.ghosts: Dict = {}
        self.researched = 0
        self.research = {"current_research": None, "progress": 0.0, "queue_length": 0}
        self.queue: List[Dict[str, Any]] = []
        self.status_reader = None
        self.namespace: Dict[str, Any] = {}

    # tools
    def get_tool_definitions(self, mode="autonomous", horizon_ticks=None, turn_mode="gameplay"):
        from FactoryVerse.environment.tool_definitions import get_tool_definitions

        return get_tool_definitions(mode, horizon_ticks=horizon_ticks, turn_mode=turn_mode)

    def get_game_tick(self):
        return self._tick

    async def execute_dsl(self, code, metadata=None):
        before = self._tick
        buf = io.StringIO()
        ns = dict(self.namespace)
        if self.turn_mode == "planning":
            ns = {k: v for k, v in ns.items() if k in {"remote_view", "research", "inventory", "plan", "agent_id"}}
        ns.setdefault("plan", self.plan_store)
        try:
            with contextlib.redirect_stdout(buf):
                exec(code, ns)
            out = buf.getvalue().rstrip("\n")
        except Exception as e:  # the real adapter returns errors as text
            out = f"{buf.getvalue()}Error: {type(e).__name__}: {e}"
        self._tick += 60
        self.last_tick_span = {"before": before, "after": self._tick}
        return out

    def execute_duckdb(self, query, metadata=None):
        before = self._tick
        self._tick += 1
        self.last_tick_span = {"before": before, "after": self._tick}
        return "rows"

    def respond(self, message, metadata=None):
        return message

    # turn contract reads
    def advance_world(self, ticks):
        self.advances.append(ticks)
        self._tick += ticks
        return ticks

    def production_statistics(self):
        return json.loads(json.dumps(self.production))

    def inventory_counts(self):
        return dict(self.inventory)

    def map_rows(self):
        return dict(self.entities), dict(self.ghosts)

    def research_status(self):
        return dict(self.research)

    def crafting_queue(self):
        return list(self.queue)

    def researched_count(self):
        return self.researched

    def recipe_energy(self, recipe):
        return {"transport-belt": 0.5, "inserter": 0.5, "iron-gear-wheel": 0.5}.get(recipe)


class _Client:
    def __init__(self, scripted):
        self._s = list(scripted)
        self.requests = []

    def chat_completion(self, messages, tools=None, **_):
        self.requests.append({"messages": json.loads(json.dumps(messages)), "tools": tools})
        msg = self._s.pop(0)
        return ChatCompletionResult(
            message=msg, usage=ChatCompletionUsage(1, 1, 2),
            finish_reason="tool_calls" if msg.has_tool_calls else "stop", model="fake",
        )


def _call(cid, name, **args):
    return ToolCall(id=cid, name=name, arguments=json.dumps(args))


def _asst(*calls):
    return ChatMessage(role="assistant", content="", tool_calls=list(calls))


def _text(t="ok"):
    return ChatMessage(role="assistant", content=t)


def _make(tmp_path, client, runtime, **kw):
    prompt = tmp_path / "p.md"
    prompt.write_text("prompt")
    traj = tmp_path / "trajectory.jsonl"
    orch = AgentOrchestrator(
        llm_client=client, runtime=runtime, system_prompt_path=str(prompt),
        trajectory_writer=TrajectoryWriter(traj), **kw,
    )
    return orch, traj


def _events(traj, etype):
    return [e for e in TrajectoryReader(traj).read_all() if e.type == etype]


# --- (a) the tick ledger reconciles; (g) end_turn advances the remainder ---


@pytest.mark.asyncio
async def test_end_turn_advances_the_remainder_and_the_ledger_reconciles(tmp_path):
    rt = _Runtime(tick=1000)
    cfg = TurnConfig(t_min=600, t_max=600)
    client = _Client([
        _asst(_call("p", "end_turn")),                                   # planning turn
        _asst(_call("a", "execute_dsl", code="print('x')")),             # gameplay: +60
        _asst(_call("b", "execute_duckdb", query="SELECT 1")),           # +1
        _asst(_call("c", "end_turn")),
    ])
    orch, traj = _make(tmp_path, client, rt, turn_config=cfg)

    await orch.run_turn("go")          # planning: advances 0
    assert orch.turn_mode == "gameplay"
    assert rt.advances == []
    await orch.run_turn("")            # gameplay under a 600-tick horizon

    assert rt.advances == [600 - 61], rt.advances
    report = _events(traj, EventType.TURN_REPORT)[-1].data["report"]
    clock = report["clock"]
    assert clock["used"] == 61 and clock["execution"] == 61 and clock["thinking"] == 0
    assert clock["advanced"] == 539 and clock["total"] == 600 and clock["reconciles"]
    assert clock["used"] + clock["advanced"] == clock["total"]
    done = _events(traj, EventType.TURN_COMPLETE)
    assert [d.data["ended_by"] for d in done] == ["end_turn", "end_turn"]
    # The end_turn result told the model the arithmetic (it is the last tool
    # message in the history; no inference follows it inside the turn).
    assert orch.messages[-1]["role"] == "tool"
    assert "advances the remaining 539" in orch.messages[-1]["content"]


@pytest.mark.asyncio
async def test_no_debt_when_the_turn_ran_longer_than_the_horizon(tmp_path):
    rt = _Runtime(tick=0)
    cfg = TurnConfig(t_min=100, t_max=100)
    client = _Client([
        _asst(_call("p", "end_turn")),
        _asst(_call("a", "execute_dsl", code="pass"), _call("b", "execute_dsl", code="pass")),  # 120 > 100
        _asst(_call("c", "end_turn")),
    ])
    orch, traj = _make(tmp_path, client, rt, turn_config=cfg)
    await orch.run_turn("go")
    await orch.run_turn("")
    assert rt.advances == []  # no fast-forward, and no debt carried
    clock = _events(traj, EventType.TURN_REPORT)[-1].data["report"]["clock"]
    assert clock["used"] == 120 and clock["advanced"] == 0 and clock["reconciles"]


# --- (e) exactly one drain per turn, after the fast-forward --------------


@pytest.mark.asyncio
async def test_events_are_drained_once_per_turn_after_the_advance(tmp_path):
    rt = _Runtime(tick=0)
    cfg = TurnConfig(t_min=300, t_max=300)
    client = _Client([
        _asst(_call("p", "end_turn")),
        _asst(_call("a", "execute_dsl", code="pass")),
        _asst(_call("b", "execute_dsl", code="pass")),
        _asst(_call("c", "end_turn")),
        _text("third turn"),
    ])
    orch, traj = _make(tmp_path, client, rt, turn_config=cfg)
    await orch.run_turn("go")
    drains_after_planning = len(rt.events.drains)
    assert drains_after_planning == 1

    rt.events.pending.append(_Event("crafting_finished", tick=50, data={"recipe": "inserter", "count": 2}, seq=7))
    await orch.run_turn("")
    assert len(rt.events.drains) == 2
    # The drain happened at the tick AFTER the advance (300), not mid-turn.
    assert rt.events.drains[-1] == 300
    # Inside the turn no user message was injected between the tool calls:
    # the only user messages are the opening line and the turn-2 report.
    roles = [m["role"] for m in client.requests[3]["messages"]]
    assert roles.count("user") == 2
    assert roles[-4:] == ["user", "assistant", "tool", "assistant"] or roles[-3:] == ["assistant", "tool", "assistant"] or roles[-1] == "tool"

    # The third turn's first input is the report, carrying the event with seq.
    await orch.run_turn("")
    first = client.requests[4]["messages"][-1]
    assert first["role"] == "user" and first["content"].startswith("# Turn 3")
    assert "crafting_finished inserter ×2" in first["content"] and "[1:7]" in first["content"]


# --- (d) planning turn: no body verbs, zero advance; research → planning --


@pytest.mark.asyncio
async def test_planning_turn_refuses_body_verbs_and_advances_nothing(tmp_path):
    rt = _Runtime(tick=100)
    rt.namespace = {"walking": object(), "remote_view": object(), "research": object(), "inventory": object()}
    client = _Client([
        _asst(_call("a", "execute_dsl", code="print(walking)")),
        _asst(_call("b", "execute_dsl", code="plan.set('smelt iron'); plan.set_goals(['drills', 'furnaces']); print(remote_view)")),
        _asst(_call("c", "end_turn")),
        _text("next"),
    ])
    orch, traj = _make(tmp_path, client, rt)

    await orch.run_turn("go")

    tools_first = client.requests[0]["tools"]
    dsl = next(t for t in tools_first if t["function"]["name"] == "execute_dsl")
    assert "PLANNING TURN" in dsl["function"]["description"]
    end = next(t for t in tools_first if t["function"]["name"] == "end_turn")
    assert "planning turn: 0" in end["function"]["description"]

    msgs = client.requests[2]["messages"]
    results = [m["content"] for m in msgs if m.get("role") == "tool"]
    assert "NameError" in results[0] and "walking" in results[0]
    assert "Error" not in results[1]
    assert rt.advances == [] and rt._tick == 100 + 120
    report = _events(traj, EventType.TURN_REPORT)[-1].data["report"]
    assert report["mode"] == "planning" and report["clock"]["advanced"] == 0
    assert report["plan"]["plan"] == "smelt iron" and report["plan"]["goals"] == ["drills", "furnaces"]

    # The next turn is gameplay and its input opens with the plan.
    await orch.run_turn("")
    first = client.requests[3]["messages"][-1]["content"]
    assert first.startswith("# Turn 2 — GAMEPLAY turn")
    assert "plan       smelt iron" in first and "1. drills" in first


@pytest.mark.asyncio
async def test_a_research_completion_makes_the_next_turn_a_planning_turn(tmp_path):
    rt = _Runtime(tick=0)
    cfg = TurnConfig(t_min=60, t_max=60)
    client = _Client([_asst(_call("p", "end_turn")), _asst(_call("e", "end_turn")), _asst(_call("f", "end_turn"))])
    orch, traj = _make(tmp_path, client, rt, turn_config=cfg)
    await orch.run_turn("go")
    assert orch.turn_mode == "gameplay"
    rt.events.pending.append(_Event("research_finished", tick=30, data={"technology": "automation"}))
    await orch.run_turn("")
    assert orch.turn_mode == "planning"
    await orch.run_turn("")
    assert rt.advances == [60]  # the planning turn advanced nothing
    reports = _events(traj, EventType.TURN_REPORT)
    assert reports[1].data["report"]["research"]["completed"] == ["automation"]
    assert reports[1].data["report"]["next_mode"] == "planning"


# --- (b) attention cap ----------------------------------------------------


@pytest.mark.asyncio
async def test_attention_cap_ends_the_turn_and_is_named(tmp_path):
    rt = _Runtime()
    cfg = TurnConfig(attention_calls=3, t_min=60, t_max=60)
    calls = [_asst(_call(f"c{i}", "execute_duckdb", query="SELECT 1")) for i in range(6)]
    orch, traj = _make(tmp_path, _Client([_asst(_call("p", "end_turn"))] + calls), rt, turn_config=cfg)
    await orch.run_turn("go")
    out = await orch.run_turn("")
    assert "Attention budget" in out
    assert _events(traj, EventType.TURN_COMPLETE)[-1].data["ended_by"] == "attention_cap"
    # The cap still closes the turn properly: fast-forward and report happened.
    assert rt.advances == [60 - 3]


# --- (c) the report renders every section and thresholds positions -------


def _snapshot(tick, entities=None, ghosts=None, **kw):
    base = dict(tick=tick, production={"input": {}, "output": {}}, inventory={}, map_rows=entities or {},
                ghost_rows=ghosts or {}, research={}, crafting_queue=[], researched_count=0)
    base.update(kw)
    return turn_report.TurnSnapshot(**base)


def test_report_renders_all_sections_and_thresholds_positions():
    before = _snapshot(
        0,
        production={"input": {"iron-ore": 10}, "output": {"iron-plate": 10, "iron-gear-wheel": 0}},
        inventory={"iron-plate": 5}, research={"current_research": "automation", "progress": 0.2, "queue_length": 1},
        entities={("stone-furnace", 1.0, 1.0): {}},
    )
    after_entities = {("stone-furnace", 1.0, 1.0): {}}
    after_entities.update({("transport-belt", float(i), 0.0): {} for i in range(12)})
    after = _snapshot(
        3600,
        production={"input": {"iron-ore": 60}, "output": {"iron-plate": 70, "iron-gear-wheel": 10}},
        inventory={"iron-plate": 2, "iron-gear-wheel": 10},
        research={"current_research": "logistics", "progress": 0.1, "queue_length": 2},
        entities=after_entities, crafting_queue=[{"recipe": "transport-belt", "count": 150}], researched_count=4,
    )
    events = [
        _Event("research_finished", 1200, {"technology": "automation"}, seq=1),
        _Event("crafting_finished", 1800, {"recipe": "iron-gear-wheel", "count": 10}, seq=2),
    ]
    blocks = (
        status_dump.StatusBlock(0, {("stone-furnace", 1.0, 1.0): "working"}),
        status_dump.StatusBlock(3600, {("stone-furnace", 1.0, 1.0): "no_fuel", ("burner-mining-drill", 5.0, 5.0): "working"}),
    )
    change = status_dump.diff_blocks(*blocks)
    clock = turn_report.ClockLedger(0, 400, 3200, 3600, 300, 3600)
    report = turn_report.assemble(
        turn=3, mode="gameplay", ended_by="end_turn", clock=clock, before=before, after=after, events=events,
        status_change=change, next_horizon=7200,
        next_inputs={"research_tier": 1, "researched_count": 4, "automated_rate_per_min": 50.0},
        energy_for=lambda r: 0.5, plan={"plan": "go", "goals": []},
    )
    # production split: 60 plates produced, 10 gears hand-crafted → 10 gears not automated
    assert report.production["hand_crafted"] == {"iron-gear-wheel": 10}
    assert report.production["automated"] == {"iron-plate": 60}
    assert report.production["automated_rate_per_min"] == 60.0
    # map: 12 belts placed, thresholded to 5 + 7 more
    assert report.map["placed"]["count"] == 12 and len(report.map["placed"]["shown"]) == 5 and report.map["placed"]["more"] == 7
    # status
    assert set(report.status["groups"]) == {"working -> no_fuel", "appeared as working"}
    assert report.status["source"] == "status_dump:0->3600"
    # research, crafting, inventory
    assert report.research["completed"] == ["automation"]
    assert report.crafting["remaining_ticks"] == 150 * 30 and report.crafting["share_of_next_horizon"] == 4500 / 7200
    assert report.inventory["delta"] == {"iron-gear-wheel": 10, "iron-plate": -3}
    assert report.events["count"] == 2

    text = turn_report.render(report)
    for section in ("clock", "horizon", "plan", "production", "map", "status", "research", "crafting", "inventory", "events"):
        assert section in text, section
    assert "(+7 more)" in text and "≈62% of next horizon" in text and "[1:1] research_finished automation" in text
    assert "used 400 ticks (execution 300, thinking 100), advanced 3200, total 3600" in text


# --- (f) status_dump.changed ---------------------------------------------


def _write_block(d: Path, tick: int, records):
    lines = [json.dumps({"meta": True, "tick": tick, "count": len(records)})]
    lines += [json.dumps({"name": n, "status": s, "x": x, "y": y}) for (n, x, y), s in records.items()]
    (d / f"status-{tick}.jsonl").write_text("\n".join(lines) + "\n")


def test_status_dump_changed_yields_transitions_from_two_blocks(tmp_path):
    reader = status_dump.StatusDumpReader(tmp_path)
    assert reader.current() is None and reader.changed(0).transitions == []
    _write_block(tmp_path, 600, {("stone-furnace", 1.5, 2.5): "working", ("boiler", 3.5, 4.5): "no_fuel"})
    _write_block(tmp_path, 1200, {("stone-furnace", 1.5, 2.5): "no_fuel", ("boiler", 3.5, 4.5): "no_fuel", ("lab", 9.0, 9.0): "working"})
    (tmp_path / "status-1800.jsonl").write_text("")  # a file mid-write: no meta line

    cur = reader.current()
    assert cur.tick == 1200 and cur.source == "status_dump:1200"
    assert cur.grouped() == {"no_fuel": [("boiler", 3.5, 4.5), ("stone-furnace", 1.5, 2.5)], "working": [("lab", 9.0, 9.0)]}

    change = reader.changed(since_tick=700)  # newest at-or-before 700 is 600
    assert change.from_tick == 600 and change.to_tick == 1200
    assert change.grouped().keys() == {"working -> no_fuel", "appeared as working"}
    # since_tick before any block → earliest block is used and says so
    assert reader.changed(since_tick=0).from_tick == 600
    # same block on both sides → empty, ticks equal
    same = reader.changed(since_tick=1200)
    assert same.transitions == [] and same.from_tick == same.to_tick == 1200


# --- the constants are on the record, not in the prompt -------------------


def test_turn_config_is_hashed_and_the_end_turn_description_carries_no_coefficients():
    from FactoryVerse.environment.tool_definitions import end_turn_description

    cfg = TurnConfig()
    assert len(cfg.sha256()) == 64 and cfg.sha256() == TurnConfig().sha256()
    assert TurnConfig(rate_scale=61).sha256() != cfg.sha256()
    desc = end_turn_description(7200)
    assert "7200" in desc
    for secret in (str(cfg.rate_scale), str(cfg.rate_cap), "tier_base", "t_min"):
        assert secret not in desc
    # monotone and clamped
    assert cfg.horizon_ticks(0, 0) == cfg.t_min
    assert cfg.horizon_ticks(100, 10_000) == cfg.t_max
    assert cfg.horizon_ticks(10, 30) <= cfg.horizon_ticks(10, 60) <= cfg.horizon_ticks(30, 60)


# --- (h) the boundary tick: read while paused, owned by the next turn ---


class _BoundaryRuntime(_Runtime):
    """advance_world returns the paused boundary, then the world keeps running
    (as the real engine does after the unpause) before anyone reads again."""

    def advance_world(self, ticks):
        from types import SimpleNamespace
        self.advances.append(ticks)
        start = self._tick
        self._tick += ticks
        end = self._tick
        self._tick += 7  # ticks that run after the unpause, before the next inference
        return SimpleNamespace(advanced=ticks, start_tick=start, end_tick=end, __int__=lambda s: ticks)


@pytest.mark.asyncio
async def test_boundary_tick_is_the_report_tick_and_the_next_turns_start(tmp_path):
    """Live evidence 2026-08-29: re-reading the tick after the unpause put 6
    ticks on nobody's ledger. The report closes on the paused boundary and the
    next turn starts there, so those ticks are the next turn's thinking (§17)."""
    rt = _BoundaryRuntime(tick=1000)
    cfg = TurnConfig(t_min=600, t_max=600)
    client = _Client([
        _asst(_call("p", "end_turn")),                                   # planning
        _asst(_call("a", "execute_dsl", code="print('x')")),             # +60
        _asst(_call("c", "end_turn")),                                   # advance 540 → boundary
        _asst(_call("d", "execute_dsl", code="print('y')")),             # next turn: +60
        _asst(_call("e", "end_turn")),
    ])
    orch, traj = _make(tmp_path, client, rt, turn_config=cfg)
    await orch.run_turn("go")
    await orch.run_turn("")
    reports = [e.data["report"] for e in _events(traj, EventType.TURN_REPORT)]
    first = reports[-1]["clock"]
    assert first["advanced"] == 540 and first["reconciles"]
    await orch.run_turn("")
    second = [e.data["report"] for e in _events(traj, EventType.TURN_REPORT)][-1]["clock"]
    # The 7 post-unpause ticks are on the second turn's ledger as thinking.
    assert second["thinking"] == 7, second
    assert second["execution"] == 60 and second["used"] == 67
    assert second["reconciles"]
