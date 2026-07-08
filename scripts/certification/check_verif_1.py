#!/usr/bin/env python3
"""Certification check VERIF-1 — verification feed liveness (runtime fidelity).

Field failure (engine_unit attempt 3, 2026-06-11): the production feed froze
at tick 404340 for 63 checks across turns 10-16 while game.tick advanced
360k->554k. Root cause: the fv_snapshot production poll dedups unchanged
stats with NO heartbeat, so the file tick freezes exactly when production
halts; the verifier then served the dead frame as a normal 0-rate reading.

Claims under test (all live against a running instance):
  A. heartbeat  — with production HALTED, production-statistics.jsonl's
                  last-line tick still advances within <=2 heartbeat windows
                  (HEARTBEAT_MAX_SKIPS=5 polls x 60 ticks = 300 game ticks),
                  AND dedup still bounds file growth (~1 line/300 ticks idle,
                  not 1 line/60).
  B. rcon tick  — RCONSource.get_force_production returns a real, advancing
                  game tick (the old map.get_game_tick remote never existed).
  C. live ok    — ThroughputVerifier over RCONSource: healthy feed is never
                  flagged feed_stale, measured ticks strictly advance.
  D. invariant  — negative control: a frozen feed (static copy of the stats
                  file) trips feed_stale=True within stale_after_seconds.

Run:  uv run python scripts/certification/check_verif_1.py --instance server_0
Precondition: instance running with fv mods synced AFTER the Agents.lua
heartbeat change (mod changes need a full restart), agent force idle
(fresh boot — no machines producing).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from factorio_rcon import RCONClient  # noqa: E402

from FactoryVerse.infra.rcon_helper import RconHelper  # noqa: E402
from FactoryVerse.game.tasks.base import VerificationCriteria  # noqa: E402
from FactoryVerse.game.tasks.sources import AgentSnapshotSource, RCONSource  # noqa: E402
from FactoryVerse.game.tasks.verification import ThroughputVerifier  # noqa: E402

DATE = datetime.date.today().isoformat()
ART = REPO / ".fv-output" / "certification" / DATE / "VERIF-1"
ART.mkdir(parents=True, exist_ok=True)

RCON_HOST, RCON_PASS = "localhost", "factorio"
HEARTBEAT_WINDOW_TICKS = 300  # HEARTBEAT_MAX_SKIPS(5) * poll interval(60)

results: dict = {"claims": {}, "findings": []}


def finding(msg: str) -> None:
    results["findings"].append(msg)
    print(f"[FINDING] {msg}", flush=True)


def hb(msg: str) -> None:
    print(f"[hb] {datetime.datetime.now().isoformat(timespec='seconds')} {msg}", flush=True)


def lua(rcon: RCONClient, body: str):
    wrapped = (
        "/c local ok, res = xpcall(function() "
        + body
        + " end, debug.traceback) "
        + "if ok then rcon.print(helpers.table_to_json(res == nil and {ok=true} or res)) "
        + "else rcon.print(helpers.table_to_json({error = tostring(res)})) end"
    )
    out = rcon.send_command(wrapped)
    if out is None or out.strip() == "":
        return {"error": "empty RCON response"}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"error": f"non-JSON response: {out[:500]}"}


def game_tick(rcon: RCONClient) -> int:
    return lua(rcon, "return {tick=game.tick}")["tick"]


def wait_game_ticks(rcon: RCONClient, n: int, timeout_s: float = 120.0) -> int:
    """Block until game.tick has advanced by >= n; returns the new tick."""
    start = game_tick(rcon)
    deadline = time.monotonic() + timeout_s
    while True:
        cur = game_tick(rcon)
        if cur - start >= n:
            return cur
        if time.monotonic() > deadline:
            raise TimeoutError(f"game.tick advanced only {cur - start}/{n} in {timeout_s}s")
        time.sleep(0.25)


def last_line_tick_and_count(path: Path) -> tuple[int, int]:
    last, count = None, 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                last, count = line, count + 1
    if last is None:
        return 0, 0
    return json.loads(last).get("tick", 0), count


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", default="server_0")
    ap.add_argument("--agent-id", type=int, default=1)
    args = ap.parse_args()

    if args.instance == "client":
        rcon_port = 27100
        script_output = Path.home() / "Library/Application Support/factorio/script-output"
    elif args.instance.startswith("server_"):
        n = int(args.instance.split("_")[1])
        rcon_port = 27000 + n
        script_output = REPO / ".fv-output" / args.instance
    else:
        raise SystemExit(f"unknown instance {args.instance!r}")

    rcon = RCONClient(RCON_HOST, rcon_port, RCON_PASS)
    rcon.connect()

    # Phase 0: smoke — game must be running and unpaused
    t1 = game_tick(rcon)
    time.sleep(1.0)
    t2 = game_tick(rcon)
    hb(f"smoke: game.tick {t1} -> {t2}")
    if t2 <= t1:
        finding("game.tick NOT advancing — instance paused? cannot certify")
        results["claims"] = {k: "BLOCKED" for k in "ABCD"}
        return finalize(2)

    # Phase 1: agent exists (creates one via the standalone path if absent)
    helper = RconHelper(rcon, auto_create_agent=True)
    agent_iface = f"agent_{args.agent_id}"
    if agent_iface not in (helper.interfaces or {}):
        finding(f"interface {agent_iface} absent after create_agent — cannot certify")
        results["claims"] = {k: "BLOCKED" for k in "ABCD"}
        return finalize(2)
    hb(f"agent interface {agent_iface} present")

    # Precondition for claim A: production halted (idle force)
    stats = lua(rcon, f"return remote.call('{agent_iface}','get_production_statistics')")
    if stats.get("error"):
        finding(f"get_production_statistics failed: {stats['error']}")
        results["claims"] = {k: "BLOCKED" for k in "ABCD"}
        return finalize(2)
    hb(f"production stats snapshot: input={stats.get('input')}, output={stats.get('output')}")

    # ---- Claim B: RCONSource returns a real, advancing tick ----
    src = RCONSource(helper, script_output)
    p1 = await src.get_force_production(args.agent_id)
    time.sleep(0.7)
    p2 = await src.get_force_production(args.agent_id)
    engine_now = game_tick(rcon)
    b_ok = p1["tick"] > 0 and p2["tick"] > p1["tick"] and abs(engine_now - p2["tick"]) < 600
    results["claims"]["B"] = {
        "pass": b_ok,
        "tick1": p1["tick"],
        "tick2": p2["tick"],
        "engine_tick": engine_now,
    }
    hb(f"claim B {'PASS' if b_ok else 'FAIL'}: RCONSource ticks {p1['tick']} -> {p2['tick']} (engine {engine_now})")
    if not b_ok:
        finding(f"RCONSource tick not live: {p1['tick']} -> {p2['tick']} vs engine {engine_now}")

    # ---- Claim A: heartbeat keeps the FILE feed tick advancing while idle ----
    stats_file = (
        script_output / "factoryverse" / "agent-snapshots" / str(args.agent_id)
        / "production-statistics.jsonl"
    )
    deadline = time.monotonic() + 30
    while not stats_file.exists() and time.monotonic() < deadline:
        time.sleep(0.5)
    if not stats_file.exists():
        finding(f"stats file never appeared: {stats_file}")
        results["claims"]["A"] = {"pass": False, "reason": "file absent"}
    else:
        tick_a0, lines_a0 = last_line_tick_and_count(stats_file)
        engine_a0 = game_tick(rcon)
        window = 2 * HEARTBEAT_WINDOW_TICKS + 100
        hb(f"claim A: file tick {tick_a0}, {lines_a0} lines; waiting {window} game ticks...")
        engine_a1 = wait_game_ticks(rcon, window)
        tick_a1, lines_a1 = last_line_tick_and_count(stats_file)
        elapsed_ticks = engine_a1 - engine_a0
        # liveness: last-line tick advanced; bounded growth: dedup still skips
        # most polls (allow 2x slack on the 1-per-300-ticks idle rate)
        max_lines = int(elapsed_ticks / HEARTBEAT_WINDOW_TICKS * 2) + 2
        lines_added = lines_a1 - lines_a0
        a_ok = tick_a1 > tick_a0 and 1 <= lines_added <= max_lines
        results["claims"]["A"] = {
            "pass": a_ok,
            "file_tick_before": tick_a0,
            "file_tick_after": tick_a1,
            "elapsed_game_ticks": elapsed_ticks,
            "lines_added": lines_added,
            "max_lines_allowed": max_lines,
        }
        hb(f"claim A {'PASS' if a_ok else 'FAIL'}: file tick {tick_a0} -> {tick_a1}, +{lines_added} lines over {elapsed_ticks} ticks")
        if not a_ok:
            if tick_a1 <= tick_a0:
                finding(f"heartbeat ABSENT: file tick frozen at {tick_a0} over {elapsed_ticks} idle game ticks")
            else:
                finding(f"dedup broken: {lines_added} lines added (max {max_lines}) — heartbeat writing too often")

    # ---- Claim C: live verifier over RCONSource never flags a healthy feed ----
    criteria = VerificationCriteria(
        target_item="iron-plate", quota=10, sustained_seconds=15.0, check_interval_seconds=5.0
    )
    verifier = ThroughputVerifier(criteria, stale_after_seconds=10.0)
    measured, stale_flags = [], []
    for _ in range(4):
        r = await verifier.check(src, args.agent_id, "verif1-live")
        measured.append(r.measured_at_tick)
        stale_flags.append(r.feed_stale)
        time.sleep(0.7)
    c_ok = not any(stale_flags) and all(b > a for a, b in zip(measured, measured[1:]))
    results["claims"]["C"] = {"pass": c_ok, "ticks": measured, "stale_flags": stale_flags}
    hb(f"claim C {'PASS' if c_ok else 'FAIL'}: live verifier ticks {measured}, stale {stale_flags}")
    if not c_ok:
        finding(f"live verifier unhealthy: ticks {measured}, stale flags {stale_flags}")

    # ---- Claim D: negative control — frozen feed trips the invariant ----
    d_ok = False
    if stats_file.exists():
        with tempfile.TemporaryDirectory() as td:
            frozen_root = Path(td)
            frozen_agent_dir = (
                frozen_root / "factoryverse" / "agent-snapshots" / str(args.agent_id)
            )
            frozen_agent_dir.mkdir(parents=True)
            shutil.copy(stats_file, frozen_agent_dir / "production-statistics.jsonl")
            frozen_src = AgentSnapshotSource(frozen_root)
            v2 = ThroughputVerifier(criteria, stale_after_seconds=2.0)
            r1 = await v2.check(frozen_src, args.agent_id, "verif1-frozen")
            time.sleep(2.5)
            r2 = await v2.check(frozen_src, args.agent_id, "verif1-frozen")
            d_ok = (not r1.feed_stale) and r2.feed_stale
            results["claims"]["D"] = {
                "pass": d_ok,
                "first_check_stale": r1.feed_stale,
                "second_check_stale": r2.feed_stale,
                "reason": r2.failure_reason,
            }
            hb(f"claim D {'PASS' if d_ok else 'FAIL'}: frozen copy -> stale={r2.feed_stale}")
            if not d_ok:
                finding(f"invariant did NOT fire on frozen feed: {r1.feed_stale}/{r2.feed_stale}")
    else:
        results["claims"]["D"] = {"pass": False, "reason": "no stats file to freeze"}

    all_pass = all(
        isinstance(c, dict) and c.get("pass") for c in results["claims"].values()
    )
    return finalize(0 if all_pass else 1)


def finalize(code: int) -> int:
    results["verdict"] = "PASS" if code == 0 else ("BLOCKED" if code == 2 else "FAIL")
    out = ART / "result.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\n=== VERIF-1 {results['verdict']} === ({out})", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
