"""Live: the fast-forward lands exactly and the clock ledger reconciles.

Run on ports that are not owned by another campaign::

    FV_RUN_LIVE_TURN_CONTRACT=1 \
    FV_RCON_SERVER_PORT_BASE=39700 FV_GAME_PORT_BASE=48597 \
    FV_AGENT_PORT_BASE=48602 FV_SNAPSHOT_PORT_BASE=48800 FV_ENABLE_UDP_PORT=48600 \
    uv run pytest -q tests/live/test_turn_contract.py

The test attaches to a server the caller has already started on those ports
(`fv server start --num 1 --scenario lab-grid` with the same env), because a
fast-forward is a whole-world operation and must not run on a server another
test owns. Measured 2026-08-29 on factoriotools/factorio:2.0.76 (arm64/box64):
600 ticks in 3.1 s, 3600 in 17.0 s, both exact.
"""

from __future__ import annotations

import os
import time

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("FV_RUN_LIVE_TURN_CONTRACT") != "1",
    reason="set FV_RUN_LIVE_TURN_CONTRACT=1 with a server on FV_RCON_SERVER_PORT_BASE to run",
)


def _rcon():
    from factorio_rcon import RCONClient

    port = int(os.environ.get("FV_RCON_SERVER_PORT_BASE", "27000"))
    password = os.environ.get("FV_RCON_PASSWORD", "factorio")
    # The RCON port opens before the server accepts authentication (seen
    # repeatedly on 2.0.76 in Docker); attach with a bounded retry.
    deadline = time.time() + 120
    last = None
    while time.time() < deadline:
        try:
            c = RCONClient("127.0.0.1", port, password)
            c.send_command("/silent-command rcon.print(game.tick)")
            return c
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2)
    raise RuntimeError(f"RCON at {port} never became ready: {last}")


class _Tier3Like:
    """Just enough of Tier3Python for advance_world: run_lua + get_game_tick."""

    FAST_FORWARD_SPEED = 64.0

    def __init__(self, client):
        self._rcon = client

    def run_lua(self, code: str):
        import json

        wrapped = (
            f"local ok, res = xpcall(function() {code} end, debug.traceback); "
            "if ok then rcon.print(helpers.table_to_json({success=true, result=res})) "
            "else rcon.print(helpers.table_to_json({success=false, error=tostring(res)})) end"
        )
        out = self._rcon.send_command(f"/silent-command {wrapped}")
        parsed = json.loads(out)
        if parsed.get("success") is False:
            raise RuntimeError(parsed.get("error"))
        return parsed.get("result")

    def get_game_tick(self) -> int:
        return int(self._rcon.send_command("/silent-command rcon.print(game.tick)"))

    # Borrow the real implementation so the test exercises the shipped code.
    from FactoryVerse.environment.tiers.tier3_python import Tier3Python as _T

    advance_world = _T.advance_world
    advance_world_to = _T.advance_world_to


@pytest.mark.parametrize("ticks", [600, 3600])
def test_advance_world_lands_exactly(ticks):
    t3 = _Tier3Like(_rcon())
    before = t3.get_game_tick()
    start = time.time()
    result = t3.advance_world(ticks)
    wall = time.time() - start
    after = t3.get_game_tick()
    assert result.advanced == ticks, (result, ticks)
    assert result.end_tick - result.start_tick == ticks
    # The world resumed at speed 1 after the paused boundary read; whatever
    # ran since belongs to the "next turn" and is not bounded here.
    assert after >= result.end_tick >= before
    assert t3.run_lua("return game.speed") == 1
    assert t3.run_lua("return game.tick_paused") is False
    assert wall < ticks / 20.0, f"{ticks} ticks took {wall:.1f}s — slower than 20 t/s"


def test_ledger_reconciles_across_a_simulated_turn():
    """used + advanced == tick delta, with the world running in between."""
    from FactoryVerse.game.agent.turn_report import ClockLedger

    t3 = _Tier3Like(_rcon())
    start = t3.get_game_tick()
    time.sleep(1.0)  # 'thinking': the clock runs at speed 1
    end = t3.get_game_tick()
    horizon = 600
    result = t3.advance_world_to(start + horizon)
    # The turn ended when the world froze (result.start_tick), and the ledger
    # closes on the paused boundary tick, never on a later live read.
    assert result.start_tick >= end
    ledger = ClockLedger(start, result.start_tick, result.advanced, result.end_tick, execution_ticks=0, horizon=horizon)
    assert ledger.reconciles(), ledger
    assert ledger.total == horizon, ledger
