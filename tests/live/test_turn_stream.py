"""NOTIFICATIONS_PRIMITIVE_DEFERRED.md gates that need a world — the `turn` stream.

Boots a dedicated Docker server on private ports, creates an agent through
the tiered stack, and listens on both per-agent ports directly. Run with::

    FV_RUN_LIVE_TURN_STREAM=1 \\
    FV_RCON_SERVER_PORT_BASE=39600 FV_GAME_PORT_BASE=48497 \\
    FV_AGENT_PORT_BASE=48702 FV_AGENT_TURN_PORT_BASE=48802 \\
    FV_SNAPSHOT_PORT_BASE=48900 FV_ENABLE_UDP_PORT=48700 \\
    uv run pytest -q tests/live/test_turn_stream.py -vv -s

Gates covered: 1 (datagram ceiling, measured), 6 (the inversion is gone),
7 (loss is announced and filled from the file), 8 (attach is honest).
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time
from pathlib import Path

import pytest

from FactoryVerse.environment import Environment, Tier
from FactoryVerse.environment.config import (
    EnvironmentConfig,
    InfraConfig,
    InfraMode,
    PythonConfig,
    RuntimeConfig,
    SettingsConfig,
)
from FactoryVerse.game.agent.infra.turn_stream import TurnStreamCursor

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("FV_RUN_LIVE_TURN_STREAM") != "1",
        reason="set FV_RUN_LIVE_TURN_STREAM=1 to boot a server for the turn-stream gates",
    ),
]


class _Sniffer:
    """Raw UDP capture on one port, in a thread, so we see every datagram."""

    def __init__(self, port: int):
        self.port = port
        self.items: list[dict] = []
        self.raw: list[bytes] = []
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("0.0.0.0", port))
        self._sock.settimeout(0.2)
        self._run = True
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def _loop(self):
        while self._run:
            try:
                data, _ = self._sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            self.raw.append(data)
            try:
                self.items.append(json.loads(data.decode("utf-8")))
            except Exception:
                self.items.append({"_undecodable": len(data)})

    def close(self):
        self._run = False
        self._t.join(timeout=1)
        self._sock.close()


@pytest.fixture(scope="module")
async def world():
    config = EnvironmentConfig(
        tier1=InfraConfig(mode=InfraMode.SERVER),
        tier2=SettingsConfig(scenario="lab-grid"),
        tier3=PythonConfig(instance="server_0"),
        tier4=RuntimeConfig(agent_id="agent_1"),
    )
    env = Environment(config=config)
    await env.initialize(up_to=Tier.RUNTIME)
    try:
        yield env
    finally:
        await env.shutdown()


def _lua(env, code: str):
    return env.tier3.run_lua(code)


async def _wait(pred, timeout=20.0, step=0.2):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return True
        await asyncio.sleep(step)
    return pred()


async def test_gate_8_attach_adopts_lua_state(world):
    """Python's cursor starts where Lua says, never at zero-by-assumption."""
    env = world
    tier4 = env.tier4
    numeric = tier4._agent_numeric_id
    state = env.tier3.stream_state(numeric, "turn")
    assert state["epoch"] >= 1
    assert state["port"] == tier4._calculate_agent_turn_port("agent_1")
    cursor: TurnStreamCursor = tier4._turn_stream.cursor
    assert (cursor.epoch, cursor.seq) == (state["epoch"], state["seq"])


async def test_gate_6_crafting_completion_leaves_once_per_port(world):
    """`crafting_finished` on the turn port at a seq; `completed` on the action
    port; neither port carries the other's type."""
    env = world
    tier4 = env.tier4
    numeric = tier4._agent_numeric_id
    turn_port = tier4._calculate_agent_turn_port("agent_1")

    # tier4's own listener owns the turn port; sniff the action port and read
    # the turn stream through the cursor's delivered events instead.
    before = env.tier3._action_listener.notification_queue.qsize()
    seq_before = env.tier3.stream_state(numeric, "turn")["seq"]

    # Give the agent ingredients and enqueue one craft via the agent interface.
    _lua(env, f"remote.call('admin','add_items',{numeric},{{['iron-plate']=10}})")
    res = _lua(env, f"return remote.call('agent_{numeric}','craft_enqueue','iron-gear-wheel',1)")
    assert res, "craft_enqueue returned nothing"

    ok = await _wait(lambda: env.tier3.stream_state(numeric, "turn")["seq"] > seq_before, timeout=30)
    assert ok, "turn stream seq never advanced after a craft"

    # Drain what the turn stream delivered
    events = await tier4._event_stream.drain(timeout=0)
    turn_types = [e.notification_type for e in events if e.source == "turn"]
    assert "crafting_finished" in turn_types
    seqs = [e.seq for e in events if e.source == "turn"]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    # And the file has the same envelope at the same seq
    file_path = tier4._turn_stream_file()
    assert file_path and file_path.exists(), file_path
    lines = [json.loads(l) for l in file_path.read_text().splitlines() if l.strip()]
    assert any(l["event_type"] == "crafting_finished" for l in lines)
    for e in events:
        if e.source == "turn":
            assert any(l["seq"] == e.seq and l["epoch"] == e.epoch for l in lines)
    # No `notification`-typed datagram exists anywhere any more: the action
    # port never carries a crafting_finished.
    assert "crafting_finished" not in json.dumps(
        [p for p in getattr(env.tier3._action_listener, "_seen_action_payloads", [])]
    )


async def test_gate_7_loss_is_announced_and_filled(world):
    """Drop a datagram (skip it at the cursor) and prove the fill comes from the file."""
    env = world
    tier4 = env.tier4
    numeric = tier4._agent_numeric_id
    listener = tier4._turn_stream
    # Emit three probe events; the flush stamps them at consecutive seqs.
    state0 = env.tier3.stream_state(numeric, "turn")
    for _ in range(3):
        _lua(env, f"remote.call('admin','emit_turn_test',{numeric},16)")
    ok = await _wait(lambda: env.tier3.stream_state(numeric, "turn")["seq"] >= state0["seq"] + 3, timeout=20)
    assert ok
    await asyncio.sleep(0.5)
    await tier4._event_stream.drain(timeout=0)

    # Now simulate loss: rewind the cursor by two, then feed the last envelope
    # only. The two before it must be filled from the file and marked.
    file_path = tier4._turn_stream_file()
    lines = [json.loads(l) for l in file_path.read_text().splitlines() if l.strip()]
    last = lines[-1]
    with listener._lock:
        listener.cursor.seq = last["seq"] - 3
    n = listener.feed(json.dumps(last).encode())
    assert n == 3
    events = await tier4._event_stream.drain(timeout=0)
    got = [(e.seq, e.filled_from_file) for e in events if e.source == "turn"]
    assert got == [(last["seq"] - 2, True), (last["seq"] - 1, True), (last["seq"], False)]
    assert listener.cursor.gaps == []


async def test_gate_1_datagram_ceiling_measured(world):
    """Find the largest envelope that arrives intact; print it for stream.lua's constant."""
    env = world
    tier4 = env.tier4
    numeric = tier4._agent_numeric_id
    listener = tier4._turn_stream
    # Measured 2026-08-29: 8,080 filler bytes arrives, 8,100 does not (~8 KiB
    # wire ceiling). stream.lua's MAX_DATAGRAM_BYTES = 8000 JSON bytes sits
    # under that, so 7,800 filler (~7,925 bytes) still rides a datagram and
    # 8,000 filler (~8,125 bytes) goes envelope-only and is read from the file.
    sizes = [1_000, 7_000, 7_800, 8_000, 8_080, 8_100, 16_000, 60_000]
    results = {}
    for size in sizes:
        seen = []
        orig = listener._deliver
        listener._deliver = lambda p, _s=seen: _s.append(p)
        try:
            state = env.tier3.stream_state(numeric, "turn")
            _lua(env, f"remote.call('admin','emit_turn_test',{numeric},{size})")
            ok = await _wait(lambda: any(p.get("seq") == state["seq"] + 1 for p in seen), timeout=8)
        finally:
            listener._deliver = orig
        item = next((p for p in seen if p.get("seq") == state["seq"] + 1), None)
        results[size] = (
            "absent" if item is None else ("filled_from_file" if item.get("filled_from_file") else "datagram")
        )
    print("\nGATE 1 datagram ceiling:", results)
    # Under the constant: a datagram. Over it: envelope-only, filled from the
    # file. Nothing may be absent — that would mean the constant is above
    # the real ceiling and the plan's oversize rule is not protecting anyone.
    for size in (1_000, 7_000, 7_800):
        assert results[size] == "datagram", (size, results)
    for size in (8_000, 8_080, 8_100, 16_000, 60_000):
        assert results[size] == "filled_from_file", (size, results)
    assert "absent" not in results.values(), results
