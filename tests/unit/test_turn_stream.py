"""The `turn` stream — NOTIFICATIONS_PRIMITIVE_DEFERRED.md, "The unit" and "The Python mirror".

Two halves:

* Lua text contracts — `utils/stream.lua` is side-effect-free at load, the
  envelope has the five fields, emit refuses names outside the vocabulary,
  `new_epoch` is called only from the two writable lifecycle hooks, and the
  turn stream is flushed once per tick from `Agents.on_tick`.
* Python — `TurnStreamCursor`'s acceptance rules (adopt, next, stale,
  duplicate, gap-with-file-fill, gap-without-file, epoch change, in_file)
  and the reshaping into the payload the typed layer reads.

Every set-valued assertion asserts non-emptiness first, so a regex that
stops matching cannot pass as "no violations".
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from FactoryVerse.game.agent.event_stream import (
    CraftingFinishedEvent,
    GameEvent,
    ResearchMovedEvent,
)
from FactoryVerse.game.agent.infra.turn_stream import (
    TurnStreamCursor,
    TurnStreamListener,
    envelope_to_notification,
)

REPO = Path(__file__).resolve().parents[2]
AGENT_MOD = REPO / "src" / "fv_embodied_agent"
STREAM = AGENT_MOD / "utils" / "stream.lua"
AGENT = AGENT_MOD / "Agent.lua"
AGENTS = AGENT_MOD / "game_state" / "Agents.lua"
CONTROL = AGENT_MOD / "control.lua"
NOTIFICATIONS = AGENT_MOD / "game_state" / "Notifications.lua"


def _strip_comments(text: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines())


# ---------------------------------------------------------------------------
# Lua text contracts
# ---------------------------------------------------------------------------


def test_stream_lua_is_side_effect_free_at_load():
    """No `storage`, `script.`, `remote.` outside function bodies.

    Walks the file tracking `function ... end` nesting; anything at depth 0
    that mentions those names is a load-time side effect.
    """
    code = _strip_comments(STREAM.read_text())
    # keywords inside string literals ("... for %s") must not count
    code = re.sub(r'"(?:[^"\\]|\\.)*"', '""', code)
    depth = 0
    top_level = []
    openers = re.compile(r"\b(?:function|if|for|while)\b")
    closers = re.compile(r"\bend\b")
    for line in code.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if depth == 0:
            top_level.append(stripped)
        depth += len(openers.findall(stripped)) - len(closers.findall(stripped))
        assert depth >= 0, stripped
    assert depth == 0
    assert len(top_level) >= 5
    for line in top_level:
        assert "storage" not in line, line
        assert "script." not in line, line
        assert "remote." not in line, line
    # And the named API is all there.
    for fn in ("M.open", "M.emit", "M.flush", "M.new_epoch", "M.state"):
        assert f"function {fn}(" in code, fn


def test_envelope_has_exactly_the_five_fields():
    code = STREAM.read_text()
    m = re.search(r"local envelope = \{(.*?)\}", code, re.S)
    assert m, "envelope literal not found"
    fields = set(re.findall(r"(\w+)\s*=", m.group(1)))
    assert fields == {"epoch", "seq", "tick", "event_type", "data"}


def test_emit_refuses_names_outside_the_vocabulary():
    code = _strip_comments(STREAM.read_text())
    emit = code[code.index("function M.emit(") : code.index("function M.pending(")]
    assert "if not stream.vocabulary[event_type] then" in emit
    assert "return false" in emit


def test_new_epoch_is_called_only_from_writable_hooks():
    """on_init (agent creation) and on_configuration_changed — never on_load."""
    control = _strip_comments(CONTROL.read_text())
    on_load = control[control.index("script.on_load(") : control.index("script.on_event(defines.events.on_runtime_mod_setting_changed")]
    assert "new_epoch" not in on_load
    on_cfg = control[control.index("script.on_configuration_changed(") :]
    assert "Agents.new_epoch_all()" in on_cfg
    agent = _strip_comments(AGENT.read_text())
    new_fn = agent[agent.index("function Agent:new(") : agent.index("function Agent:create_or_get_force(")]
    assert "stream.new_epoch(agent:turn_stream())" in new_fn
    agents = _strip_comments(AGENTS.read_text())
    assert "function M.new_epoch_all()" in agents


def test_turn_stream_is_flushed_once_per_tick_from_agents_on_tick():
    agents = _strip_comments(AGENTS.read_text())
    on_tick = agents[agents.index("function M.on_tick(") : agents.index("function M.get_on_tick_handlers(")]
    assert on_tick.count("stream.flush(agent:turn_stream())") == 1
    # and nothing else flushes it
    assert _strip_comments(NOTIFICATIONS.read_text()).count("stream.flush") == 0


def test_crafting_completion_leaves_once_per_port():
    """`crafting_finished` rides the turn stream only; the action port keeps
    `craft_enqueue completed`. Gate 6's static half."""
    notif = _strip_comments(NOTIFICATIONS.read_text())
    assert notif.count('"crafting_finished"') == 1
    assert "enqueue_message" not in notif
    crafting = _strip_comments((AGENT_MOD / "agent_actions" / "crafting.lua").read_text())
    assert "crafting_finished" not in crafting
    assert 'action="craft_enqueue"' in crafting.replace(" ", "") or "craft_enqueue" in crafting


def test_turn_port_offset_matches_python_bases():
    """Lua's default turn port = action port + 98 must equal Python's bases 34300 - 34202."""
    from FactoryVerse.environment.config import FactoryVerseConfig

    agent = AGENT.read_text()
    m = re.search(r"Agent\.TURN_PORT_OFFSET = (\d+)", agent)
    assert m
    cfg = FactoryVerseConfig()
    assert int(m.group(1)) == cfg.agent_turn_port_base - cfg.agent_port_base
    assert cfg.get_agent_turn_port(0, None) == 34300
    assert cfg.get_agent_turn_port(3, 2) == 34300 + 20 + 3
    assert cfg.get_agent_turn_port(3, 2) - cfg.get_agent_port(3, 2) == 98


def test_socat_forwards_the_turn_range():
    from FactoryVerse.infra.docker.factorio_server_manager import FactorioServerManager

    src = Path(FactorioServerManager.__module__.replace(".", "/"))
    text = (REPO / "src" / src).with_suffix(".py").read_text()
    assert "get_agent_turn_port(agent_idx, server_index=instance_id)" in text


# ---------------------------------------------------------------------------
# Python cursor rules
# ---------------------------------------------------------------------------


def _env(epoch, seq, event_type="research_queued", **data):
    d = {"agent_id": 1, **data}
    return {"epoch": epoch, "seq": seq, "tick": 100 + seq, "event_type": event_type, "data": d}


def test_adopt_then_accept_only_the_next_sequence():
    c = TurnStreamCursor()
    c.adopt({"epoch": 1, "seq": 7, "port": 34300, "tick": 5})
    assert c.offer(_env(1, 7)) == []  # duplicate of adopted
    assert c.offer(_env(1, 3)) == []  # stale
    out = c.offer(_env(1, 8))
    assert [a.envelope["seq"] for a in out] == [8]
    assert not out[0].filled_from_file
    assert c.seq == 8 and c.dropped_stale == 2 and c.gaps == []


def test_gap_is_filled_from_the_file_and_marked(tmp_path):
    f = tmp_path / "turn.jsonl"
    lines = [_env(1, s, "crafting_finished", recipe="iron-gear-wheel") for s in range(1, 6)]
    f.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    c = TurnStreamCursor(file_path=f)
    c.adopt({"epoch": 1, "seq": 1})
    out = c.offer(_env(1, 5))  # 2,3,4 missing
    assert [a.envelope["seq"] for a in out] == [2, 3, 4, 5]
    assert [a.filled_from_file for a in out] == [True, True, True, False]
    assert c.gaps == [] and c.filled_count == 3 and c.seq == 5


def test_gap_without_file_is_announced_not_hidden():
    c = TurnStreamCursor(file_path=None)
    c.adopt({"epoch": 2, "seq": 10})
    out = c.offer(_env(2, 14))
    assert [a.envelope["seq"] for a in out] == [14]
    assert c.gaps == [(2, 11, 13)]


def test_epoch_change_resets_and_older_epoch_is_dropped():
    c = TurnStreamCursor()
    c.adopt({"epoch": 1, "seq": 40})
    assert [a.envelope["seq"] for a in c.offer(_env(2, 1))] == [1]
    assert c.epoch == 2 and c.seq == 1 and c.epoch_resets == 1
    assert c.offer(_env(1, 41)) == []
    assert c.dropped_stale == 1


def test_in_file_envelope_is_read_from_the_file(tmp_path):
    f = tmp_path / "turn.jsonl"
    big = _env(1, 2, "research_moved", filler="x" * 50)
    f.write_text(json.dumps(_env(1, 1)) + "\n" + json.dumps(big) + "\n")
    c = TurnStreamCursor(file_path=f)
    c.adopt({"epoch": 1, "seq": 1})
    out = c.offer({"epoch": 1, "seq": 2, "tick": 102, "event_type": "research_moved", "in_file": True})
    assert len(out) == 1 and out[0].filled_from_file
    assert out[0].envelope["data"]["filler"] == "x" * 50


def test_envelope_reshapes_into_a_typed_event_with_provenance():
    payload = envelope_to_notification(_env(3, 9, "crafting_finished", recipe="pipe", count=2), True)
    assert payload["notification_type"] == "crafting_finished"
    assert payload["agent_id"] == 1 and payload["source"] == "turn"
    ev = GameEvent.from_payload(payload)
    assert isinstance(ev, CraftingFinishedEvent)
    assert ev.epoch == 3 and ev.seq == 9 and ev.filled_from_file is True
    assert ev.to_dict()["seq"] == 9 and ev.to_dict()["filled_from_file"] is True
    moved = GameEvent.from_payload(envelope_to_notification(_env(3, 10, "research_moved"), False))
    assert isinstance(moved, ResearchMovedEvent) and moved.seq == 10


def test_listener_feed_adopts_state_and_delivers_in_order(tmp_path):
    delivered = []
    f = tmp_path / "turn.jsonl"
    f.write_text("\n".join(json.dumps(_env(1, s)) for s in range(1, 4)) + "\n")
    lst = TurnStreamListener(
        port=0,
        file_path=f,
        state_source=lambda: {"epoch": 1, "seq": 0, "port": 0, "tick": 0},
        deliver=delivered.append,
    )
    lst.resync()
    assert lst.feed(json.dumps(_env(1, 1)).encode()) == 1
    assert lst.feed(json.dumps(_env(1, 3)).encode()) == 2  # 2 filled from file, 3 live
    assert [d["seq"] for d in delivered] == [1, 2, 3]
    assert [d["filled_from_file"] for d in delivered] == [False, True, False]
    assert lst.feed(b"not json") == 0
