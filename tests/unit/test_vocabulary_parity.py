"""Gate 5 of the notifications plan: the wire vocabulary is one file, read by both sides.

`src/fv_embodied_agent/vocabulary.lua` is a nested Lua table of `name = true`
entries with no code in it. It has two blocks:

- `wire`   — what the two emitting mods put on the UDP wire today, keyed by
             the field the string sits in. Every leg below derives the same
             set from Lua source and asserts equality. These are plain tests
             and must be green: the vocabulary may not claim a wire string
             that Lua does not emit, nor omit one it does.
- `target` — the stream layout the plan intends. `target.not_on_wire` names
             what exists in no Lua string yet; that is asserted too, so the
             file cannot quietly describe the future as the present.

The Python side is checked leg by leg against `wire`: the typed event
dispatch, the action listener's status set, the sync service's file_type
filter, and the sync/remote-view subscription list. Legs that disagree
today are `xfail(strict=True)` with a reason naming the exact gap, so the
battery stays green while the claim stays checkable — the moment a leg is
brought into line it flips to an unexpected pass and the marker comes off.

Why parse Lua with a regex rather than run it: the file is data by
contract. If someone puts code in it, the parser stops matching and the
structure test fails, which is the right outcome.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from FactoryVerse.game.agent.event_stream import GameEvent

REPO = Path(__file__).resolve().parents[2]
VOCAB = REPO / "src" / "fv_embodied_agent" / "vocabulary.lua"

AGENT_MOD = REPO / "src" / "fv_embodied_agent"
SNAPSHOT_MOD = REPO / "src" / "fv_snapshot"

EVENT_STREAM = REPO / "src" / "FactoryVerse" / "game" / "agent" / "event_stream.py"
NOTIFICATIONS = AGENT_MOD / "game_state" / "Notifications.lua"
LISTENER = REPO / "src" / "FactoryVerse" / "game" / "agent" / "infra" / "async_listener.py"
SYNC = REPO / "src" / "FactoryVerse" / "game" / "infra" / "duckdb" / "sync.py"
REMOTE_VIEW = REPO / "src" / "FactoryVerse" / "game" / "agent" / "remote_view.py"

_SECTION = re.compile(r"^\s*(\w+)\s*=\s*\{\s*$")
_ENTRY = re.compile(r"^\s*(\w+)\s*=\s*true\s*,\s*$")
_CLOSE = re.compile(r"^\s*\},?\s*$")


# --------------------------------------------------------------------------
# Vocabulary parsing
# --------------------------------------------------------------------------


def _strip(line: str) -> str:
    return line.split("--", 1)[0].rstrip()


def load_vocabulary() -> dict:
    """Parse the nested `name = true` table into nested dicts of sets.

    A section whose children are all entries becomes a set; a section with
    sub-sections becomes a dict. Mixed sections are refused (that is code,
    or a mistake, either way not data).
    """
    root: dict = {}
    stack: list[tuple[str | None, dict]] = [(None, root)]
    for raw in VOCAB.read_text().splitlines():
        line = _strip(raw)
        if not line.strip():
            continue
        if line.strip() == "return {":
            stack.append(("return", root))
            continue
        m = _SECTION.match(line)
        if m:
            node: dict = {}
            stack[-1][1][m.group(1)] = node
            stack.append((m.group(1), node))
            continue
        e = _ENTRY.match(line)
        if e:
            stack[-1][1][e.group(1)] = True
            continue
        if _CLOSE.match(line):
            stack.pop()
            continue
        raise AssertionError(f"code in vocabulary: {raw!r}")
    assert len(stack) == 1, "unbalanced braces in vocabulary"  # the return-frame was popped by the final brace

    def finish(node: dict):
        if all(v is True for v in node.values()):
            return set(node)
        assert all(isinstance(v, dict) for v in node.values()), (
            f"mixed section (entries and sub-sections): {sorted(node)}"
        )
        return {k: finish(v) for k, v in node.items()}

    return finish(root)


def lua_strings(pattern: str, *roots: Path) -> set[str]:
    """All `\\w+` captures of `pattern` across every .lua under `roots`."""
    found: set[str] = set()
    rx = re.compile(pattern)
    for root in roots:
        for path in root.rglob("*.lua"):
            if path == VOCAB:
                continue
            found |= set(rx.findall(path.read_text()))
    return found


@pytest.fixture(scope="module")
def vocab():
    return load_vocabulary()


# --------------------------------------------------------------------------
# Structure
# --------------------------------------------------------------------------


def test_vocabulary_is_flat_data_with_two_blocks(vocab):
    assert set(vocab) == {"wire", "target"}
    assert set(vocab["wire"]) == {
        "event_type", "turn", "action", "status", "op", "file_op", "file_type",
    }
    assert set(vocab["target"]) == {"action", "turn", "entities", "files", "not_on_wire"}
    for block in vocab.values():
        for name, members in block.items():
            assert isinstance(members, set) and members, f"empty or nested section: {name}"


# --------------------------------------------------------------------------
# Leg A — `wire` equals what Lua emits. All green by construction; a red
# here means the vocabulary lies about the present.
# --------------------------------------------------------------------------


# The three files whose payload tables reach helpers.send_udp. Map.lua also
# tags write_queue items with `event_type = "file_created"`, but that field
# is never read and no datagram carries it, so it is not a wire string.
_EMIT_FILES = (
    AGENT_MOD / "utils" / "udp.lua",
    AGENT_MOD / "game_state" / "Notifications.lua",
    SNAPSHOT_MOD / "utils" / "udp_payloads.lua",
)


def test_wire_event_type_matches_lua(vocab):
    emitted: set[str] = set()
    for path in _EMIT_FILES:
        emitted |= set(re.findall(r'event_type\s*=\s*"(\w+)"', path.read_text()))
    assert emitted
    assert emitted == vocab["wire"]["event_type"]


def test_file_created_is_a_queue_tag_not_a_wire_string(vocab):
    """Pin the reason Map.lua is excluded above: `.event_type` is never read."""
    map_lua = (SNAPSHOT_MOD / "game_state" / "Map.lua").read_text()
    assert 'event_type = "file_created"' in map_lua
    assert ".event_type" not in map_lua
    assert "file_created" not in vocab["wire"]["event_type"]


def test_wire_turn_matches_lua(vocab):
    """The turn stream's event_types are the literals Notifications.lua emits."""
    text = NOTIFICATIONS.read_text()
    emitted = set(re.findall(r'emit_(?:agent|force)_turn_event\([^,]+,\s*"(\w+)"', text))
    assert emitted, "no emit sites found in Notifications.lua"
    assert emitted == vocab["wire"]["turn"]
    # The stream landed: wire and target agree for `turn`.
    assert vocab["wire"]["turn"] == vocab["target"]["turn"]


def test_turn_stream_never_sends_directly(vocab):
    """Notifications.lua emits onto the stream; only stream.lua may send."""
    text = NOTIFICATIONS.read_text()
    assert "send_udp" not in text
    assert 'require("utils.udp")' not in text
    stream_lua = (REPO / "src" / "fv_embodied_agent" / "utils" / "stream.lua").read_text()
    assert "helpers.send_udp" in stream_lua and "helpers.write_file" in stream_lua


def test_wire_action_matches_lua(vocab):
    emitted = lua_strings(r'\baction\s*=\s*"(\w+)"', AGENT_MOD)
    assert emitted
    assert emitted == vocab["wire"]["action"]


def test_wire_status_matches_lua(vocab):
    emitted = lua_strings(r'\bstatus\s*=\s*"(\w+)"', AGENT_MOD)
    assert emitted
    assert emitted == vocab["wire"]["status"]
    # "progress" is a defined constant that nothing emits; the vocabulary
    # must not list it and Lua must not have started sending it.
    assert "progress" not in emitted


def test_wire_op_and_file_op_match_lua(vocab):
    src = (SNAPSHOT_MOD / "utils" / "udp_payloads.lua").read_text()
    ops = set(re.findall(r"^\s*[A-Z_]+\s*=\s*\"(\w+)\",", re.search(r"M\.ENTITY_OP\s*=\s*\{(.*?)\}", src, re.S).group(1), re.M))
    file_ops = set(re.findall(r"^\s*[A-Z_]+\s*=\s*\"(\w+)\",", re.search(r"M\.FILE_OP\s*=\s*\{(.*?)\}", src, re.S).group(1), re.M))
    assert ops and file_ops
    assert ops == vocab["wire"]["op"]
    assert file_ops == vocab["wire"]["file_op"]


def test_wire_file_type_matches_lua(vocab):
    emitted = lua_strings(r'file_(?:written|appended)\(\s*"(\w+)"', SNAPSHOT_MOD)
    assert emitted
    assert emitted == vocab["wire"]["file_type"]


# --------------------------------------------------------------------------
# Leg B — `target` is honest about what is not yet real.
# --------------------------------------------------------------------------


def test_target_not_on_wire_is_exactly_the_names_absent_from_lua(vocab):
    target_names = (
        vocab["target"]["action"] | vocab["target"]["turn"]
        | vocab["target"]["entities"] | vocab["target"]["files"]
    )
    quoted = lua_strings(r'"(\w+)"', AGENT_MOD, SNAPSHOT_MOD)
    absent = {n for n in target_names if n not in quoted}
    assert absent == vocab["target"]["not_on_wire"]
    assert vocab["target"]["not_on_wire"] <= target_names


# --------------------------------------------------------------------------
# Leg C — Python handles exactly the wire sets. Red legs are strict xfails.
# --------------------------------------------------------------------------


def test_notification_types_are_all_typed(vocab):
    """Every wire.turn name has a typed GameEvent subclass (flipped 2026-08-29)."""
    typed = set()
    for name in vocab["wire"]["turn"]:
        event = GameEvent.from_payload(
            {"notification_type": name, "agent_id": 1, "tick": 0, "data": {}}
        )
        if type(event) is not GameEvent:
            typed.add(name)
    dispatch = set(re.findall(r'notification_type == "(\w+)"', EVENT_STREAM.read_text()))
    assert typed and dispatch
    assert typed == vocab["wire"]["turn"]
    assert dispatch == vocab["wire"]["turn"]


def test_typed_events_never_name_a_type_off_the_wire(vocab):
    """The green half of the leg above: no typed class for a phantom type."""
    dispatch = set(re.findall(r'notification_type == "(\w+)"', EVENT_STREAM.read_text()))
    assert dispatch
    assert dispatch <= vocab["wire"]["turn"]


@pytest.mark.xfail(
    strict=True,
    reason="async_listener.py handles status 'progress', which no Lua site emits",
)
def test_listener_status_set_matches_wire(vocab):
    src = LISTENER.read_text()
    handled = set(re.findall(r'status == "(\w+)"', src))
    for group in re.findall(r"status in \(([^)]*)\)", src):
        handled |= set(re.findall(r'"(\w+)"', group))
    assert handled
    assert handled == vocab["wire"]["status"]


def test_listener_handles_every_wire_status(vocab):
    """The green half: nothing Lua emits is unhandled."""
    src = LISTENER.read_text()
    handled = set(re.findall(r'status == "(\w+)"', src))
    for group in re.findall(r"status in \(([^)]*)\)", src):
        handled |= set(re.findall(r'"(\w+)"', group))
    assert handled
    assert vocab["wire"]["status"] <= handled


@pytest.mark.xfail(
    strict=True,
    reason="sync.py's file_io filter consumes 3 of 9 wire file_types by design: "
    "entity_status, power_networks, power_statistics, agent_production_statistics "
    "are polled (not tables — read on demand by remote_view.status/power/production); "
    "resource and water are load-only chunk rewrites nobody consumes live yet",
)
def test_sync_file_type_filter_matches_wire(vocab):
    block = re.search(r"if file_type not in \((.*?)\):", SYNC.read_text(), re.S).group(1)
    handled = set(re.findall(r'"(\w+)"', block))
    assert handled
    assert handled == vocab["wire"]["file_type"]


def test_sync_file_type_filter_names_only_wire_types(vocab):
    """The green half: sync does not wait for a file_type nothing writes."""
    block = re.search(r"if file_type not in \((.*?)\):", SYNC.read_text(), re.S).group(1)
    handled = set(re.findall(r'"(\w+)"', block))
    assert handled
    assert handled <= vocab["wire"]["file_type"]


def _snapshot_port_subscriptions() -> set[str]:
    subs: set[str] = set()
    for path in (SYNC, REMOTE_VIEW):
        subs |= set(re.findall(r'\.subscribe\(\s*"(\w+)"', path.read_text()))
    subs.discard("*")
    return subs


@pytest.mark.xfail(
    strict=True,
    reason="snapshot-port subscriptions disagree with the wire: "
    "ghost_operation is subscribed but never emitted; "
    "snapshot_state and chunk_charted are emitted but never subscribed",
)
def test_snapshot_port_subscriptions_match_wire(vocab):
    # The two per-agent-port event_types are consumed by the action
    # listener via a "*" subscription and are not the snapshot port's.
    snapshot_types = vocab["wire"]["event_type"] - {"action"}
    subs = _snapshot_port_subscriptions()
    assert subs and snapshot_types
    assert subs == snapshot_types


def test_snapshot_port_subscription_gap_is_exactly_as_declared(vocab):
    """Pin the shape of the gap so the xfail above cannot drift silently."""
    snapshot_types = vocab["wire"]["event_type"] - {"action"}
    subs = _snapshot_port_subscriptions()
    assert subs - snapshot_types == {"ghost_operation"}
    assert snapshot_types - subs == {"snapshot_state", "chunk_charted"}
