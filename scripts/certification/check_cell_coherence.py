#!/usr/bin/env python
"""Certification check L0.4 — agent+cell instance coherence (lab-grid lifecycle).

PROPOSED ledger row (FLOOR_CERTIFICATION.md, L0 — replication & determinism):
    ID:     L0.4
    Claim:  Agent+cell instance coherence — for N agents allocated through the
            REAL lab-grid allocation path, each agent's body, force, storage
            binding, and DB vision all refer to the SAME cell; the session DB
            contains rows ONLY for cells snapshotted this boot; release/reuse
            restores the bijection.
    How:    uv run python scripts/certification/check_cell_coherence.py
                --instance server_0 --agents 2 --path scenario
    Pass:   All seven invariants below hold with anti-vacuity floors met.
    Req:    live (lab-grid scenario)

This is the layer where CELL-1 lived untested (EVAL_ISSUE_TRACKER, field run
2026-06-11): agent body on cell_0 at (50,119), DB vision serving cell ~10's
iron at (334.5,229.5) — the agent reasoned correctly on another cell's data
and walked into force walls. CELL-2 (stale snapshot dir contaminating every
new session DB) made it fatal. This harness makes both failure modes
repeatable, parameterized for N agents, with cells chosen by the scenario's
OWN allocation (never hardcoded — the bug class is exactly "the system picked
a different cell than assumed").

INVARIANTS (all asserted, all two-sided):
    1. Allocation bijection — after each create via the real allocation path,
       lab_grid storage agent_cells/cell_agents are mutually consistent in
       BOTH directions for EVERY entry, and no cell holds two agents.
    2. Body placement — each agent's character position lies INSIDE its
       assigned cell's play-area bounds (bounds from lab_grid.get_cell_bounds,
       i.e. the scenario's own grid math) and OUTSIDE every other agent's.
    3. Force isolation — agent character force == lab_grid.get_cell_force of
       its cell == create result force_name; forces pairwise distinct.
    4. Vision scope = body cell (the CELL-1 invariant) — after creation +
       snapshot settle, a FRESH SnapshotLoader DB must show, per agent:
       (a) resource_tile rows in the agent's cell bounds whose count AND spot
           positions match a raw engine census of that cell (spots checked in
           BOTH directions: engine sample -> DB row exists; DB sample ->
           engine entity exists);
       (b) water_tile rows in-cell whose count and bounding box match the
           engine's water-tile census (region derived from the engine, not
           hand-derived from cell.lua offsets);
       (c) GLOBAL coherence (the CELL-2 invariant): every map_entity /
           resource_tile / water_tile row in the DB falls in a chunk that
           (i) has a chunk_snapshot_meta row, (ii) whose tick <= current game
           tick, (iii) is marked snapshotted in the in-game chunk lookup for
           THIS boot, (iv) lies inside some cell's play area (no gap-chunk
           rows), and (v) whose init files' mtimes fall inside this boot's
           wall-clock window (no previous-boot files).
    5. Cross-instance visibility — marker entities script-raised on agent A's
       force inside A's cell DO appear in the shared DB (it is one DB) — but
       at A's coords, with zero marker rows inside B's bounds, and B's cell
       census (engine and DB) unchanged; A's and B's cell contents disjoint
       by bounds. Markers are then destroyed, the cell re-snapshotted, and a
       fresh DB load must show them gone (mutating-probe protocol, CELL-2
       fix direction c).
    6. Release/reuse — destroy + unassign agent A: storage cleaned (A absent
       from agent_cells, A's cell absent from cell_agents, character gone from
       the engine). Create agent C (scenario's own choice — may reuse A's
       cell): bijection holds again, C's body/force coherent per 2-3.
    7. Cleanup verified — all agents created by this check destroyed and
       unassigned, marker entities removed, verified by engine census +
       storage dump (a cleanup that isn't verified is a vacuous cleanup).

ANTI-VACUITY FLOORS (BLOCKED/VACUOUS-RISK if unmet, never PASS):
    - N >= 2 agents (--agents < 2 is rejected at argparse level);
    - per cell: engine census >= 400 resource tiles (the 484-tile iron patch
      alone guarantees this on a healthy cell — a barren cell is the SNAP-1a
      failure, not a pass);
    - per cell: >= 100 water+ore rows in the DB;
    - >= 10 spot positions verified per direction per cell;
    - >= 3 marker entities placed for invariant 5;
    - every comparison asserted in both directions; zero `if exists:` guards —
      a missing table/file/interface is a FAILURE, not a skip.

ALLOCATION PATHS (--path):
    scenario      remote.call('lab_grid','create_agent_in_cell') over RCON —
                  the scenario's own allocation (find_empty_cell + force +
                  teleport + chart + re_snapshot_area, control.lua:145-225).
                  IMPLEMENTED.
    orchestrator  The Python eval path: Orchestrator._allocate_cell ->
                  LabGridAdapter.allocate_cell(cell_index, agent_id, ...) +
                  tier4.reload_snapshot_data() + the T0 coherence preflight
                  (orchestrator.py). IMPLEMENTED 2026-06-11 (post-CELL-1-fix,
                  da0cb2f): builds the REAL Environment stack (tiers 1-4,
                  FULL variant, in-process execution) attached to the running
                  instance and runs `--agents` sequential allocate -> verify
                  -> release cycles through env.orchestrator — the exact
                  calls run_task makes. No fv code is mocked; engine truth
                  still comes from this harness's own RCON connection, and
                  vision is asserted on the ORCHESTRATOR'S OWN session DB
                  through RemoteView.execute_raw (the unified query path,
                  CELL-1 item 6) — the surface the field run failed on.
                  Per cycle: O1 allocation+bijection, O2 body+force,
                  O3 vision (shared vision_battery), O4 honest-wait evidence
                  (cell chunks' lookup snapshot_tick >= pre-alloc tick),
                  O5 one-DB-truth (both DB holders content-equal on the same
                  SQL), O6 explicit preflight re-run stays silent,
                  O7 release unbinds; cycle 2+ is the reuse invariant.
                  NOT covered: concurrent allocation races, multi-env
                  same-process allocation, tier5/6 initial_state ordering
                  (that is the LIVE-1 #3 eval-path acceptance, not this).

AUDIT-GATE ANSWERS (as designed; the first executing runner re-validates
and includes these in its verdict per FLOOR_CERTIFICATION.md):
    Q1  Can it pass vacuously?  No: hard floors above; every set/count
        comparison is two-sided equality, not >= 0; missing snapshot files,
        empty tables, or absent remote interfaces raise failures (or BLOCKED
        before any mutation), never silent skips.
    Q2  Real layer or mock?  Real: live lab-grid scenario allocation over
        RCON, real fv_snapshot files on disk, real Stack-A SnapshotDatabase +
        SnapshotLoader into a fresh DuckDB file. No fv code is mocked. The
        orchestrator allocation path is explicitly NOT covered (exit 2), not
        silently approximated.
    Q3  Independent ground truth?  Engine truth comes from raw
        find_entities_filtered / count_tiles_filtered / character scans that
        share no code with the snapshot mod or the loader; expectations
        (marker specs, floors, disjointness) are hand-constructed here. Cell
        bounds come from the scenario's get_cell_bounds — the same math the
        scenario enforces with — and are cross-checked against engine
        character positions and chunk arithmetic derived from get_config.
    Q4  Assertions cover the row?  The proposed L0.4 row claims body/force/
        storage/vision coherence + boot-scoped DB + release/reuse; invariants
        1-6 map onto it one-to-one. NOT covered (row must not claim them):
        --path orchestrator allocation, concurrent allocation races,
        reset_cell semantics, agent-driven (non-script) mutations, snapshot
        continuity across save/load.

DRAFT-RUN NOTE (2026-06-11, honesty over tidiness): during what was meant to
be OFFLINE validation, the pytest wrapper's port probe found server_0 LIVE
(the diagnosis instance) and — by its own design — executed the full scenario
path against it. This violated the no-touch constraint of the drafting
session; the harness's verified cleanup ran clean (agents destroyed +
unassigned, markers removed + re-snapshotted, the pre-existing agent-1/cell-0
binding untouched), but snapshot init files for two cells were (re)written
and game.print chatter was emitted. Treat that run as a tainted-but-real
first execution: invariants 1-3, 4a, 4b, 5, 6, 7 all held (cells 1+2,
res 1459/1459 per cell, water 216/216, spots 50/50, markers 3/3 at A's
coords + 0 in B, reuse of A's cell with bijection restored); the ONLY
failures were from an over-strong draft assertion — "every chunk of an
agent's cell has DB rows" — which is false for engine-empty chunks (no
content -> no init file -> no rows). That assertion is now scoped to
content-bearing chunks (derived per-chunk from the engine census), two-sided
(content chunks must have rows AND row-bearing cell chunks must have engine
content). OQ1 (get_position shape) and OQ6 (destroy_agents list form)
incidentally checked out on that run; they remain listed for the clean
post-fix run to confirm.

OPEN-QUESTIONS for the first (clean) live run (offline draft cannot settle):
    OQ1  agent_<id>.get_position return shape is assumed {x=..,y=..} (or
         {position={..}}); the harness records the raw value — if the shape
         differs, fix the extractor, don't trust the failure.
    OQ2  Resource coord normalization: engine resources sit at tile+0.5,
         L1.1 normalized DB parity at tile coords. This harness floors both
         sides to tile ints for spot matching and uses 1-tile area probes for
         the DB->engine direction. Confirm no aliasing at patch edges.
    OQ3  Boot wall-clock window estimate (now - game_tick/60 - 300 s slack)
         assumes ~60 UPS and no long pauses. On a slow/paused server the
         window distorts; runner should cross-check against container start
         time before trusting an mtime-gate failure.
    OQ4  In-game chunk-lookup state survives save/load (L0.3), so a session
         booted from a SAVE may legitimately carry older snapshot ticks.
         This check assumes a fresh scenario boot; on a loaded save the
         CELL-2 gates need re-derivation.
    OQ5  RESOLVED 2026-06-11 (first clean-run audit): the inherited 'IDLE +
         pending stable across 5 polls' criterion was dishonest — the mod
         idles ~300 ticks before processing enqueued re_snapshots, so the
         stability window aliased the bootstrap wait and the DB was read
         mid-flight. Now wait_fresh: IDLE + pending==0 (reachable on
         lab-grid) + per-chunk lookup snapshot_tick >= ref tick; timeout
         is a recorded failure, never a silent proceed.
    OQ6  destroy_agents is called with an explicit {id} list (the nil/0
         destroy-ALL semantics and the ParamSpec sparse-table trap are both
         live, playbook §3); runner must confirm destroyed=[id] comes back.
    OQ7  Pre-existing agents (e.g. a parked diagnosis probe) make the
         bijection a GLOBAL assertion: a foreign inconsistent binding fails
         this check deliberately. Runner should report it as a real finding,
         not a harness bug.
    OQ8  chunk lookup interface name assumed 'map'.'get_chunk_lookup' as used
         by check_L1_10 on 2026-06-11; if renamed, the CELL-2 sub-check
         fails loudly — re-point it, don't soften it.
    OQ9  content-chunk attribution uses floor(position/32) engine-side; if
         the mod assigns boundary content to a neighboring chunk, the
         content-vs-DB chunk-set diff could flag false extras/missings even
         while in-cell counts match — compare actual positions before
         concluding.

Exit codes: 0 = PASS, 1 = FAIL, 2 = BLOCKED, 3 = VACUOUS-RISK.

Usage:
    uv run python scripts/certification/check_cell_coherence.py \
        --instance server_0 --agents 2 --path scenario
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import math
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

# ----------------------------------------------------------------------------
# Constants / instance plumbing
# ----------------------------------------------------------------------------
CHECK_ID = "L0.4"

RCON_HOST, RCON_PORT, RCON_PASS = "localhost", 27100, "factorio"
SNAP_ROOT = Path.home() / "Library/Application Support/factorio/script-output"

WATER_TILE_NAMES = "{'water','deepwater','water-green','deepwater-green'}"

MIN_AGENTS = 2
MIN_CELL_RESOURCE_TILES = 400   # the 484-tile iron patch alone clears this
MIN_DB_WATER_ORE_ROWS = 100     # per cell, in the loaded session DB
MIN_SPOT_CHECKS = 10            # per direction per cell
MIN_MARKERS = 3                 # invariant 5
SPOT_SAMPLE = 25
DRAIN_TIMEOUT_S = 120.0
BOOT_WINDOW_SLACK_S = 300.0     # OQ3

results: Dict[str, Any] = {"findings": [], "phases": {}}
ART: Path = REPO / ".fv-output" / "certification" / "unset" / CHECK_ID
PROGRESS: Path = ART / "progress.log"


def configure_instance(name: str) -> None:
    global RCON_PORT, SNAP_ROOT
    if name == "client":
        return
    if name.startswith("server_"):
        RCON_PORT = 27000 + int(name.split("_")[1])
        SNAP_ROOT = REPO / ".fv-output" / name
        return
    raise SystemExit(f"unknown instance {name!r}; use 'client' or 'server_N'")


def hb(msg: str) -> None:
    line = f"{datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')} {msg}"
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS, "a") as f:
        f.write(line + "\n")
    print(f"[hb] {line}", flush=True)


def finding(msg: str) -> None:
    results["findings"].append(msg)
    print(f"[FINDING] {msg}", flush=True)


def save(name: str, data: Any) -> None:
    (ART / name).write_text(json.dumps(data, indent=2, default=str))


# ----------------------------------------------------------------------------
# RCON helpers (RUNTIME_PLAYBOOK §2; envelope style from check_L2_5 first-run
# fix: non-table returns must be wrapped or table_to_json raises OUTSIDE the
# xpcall -> empty RCON response on the docker server)
# ----------------------------------------------------------------------------
def lua(rcon: Any, body: str) -> Any:
    wrapped = (
        "/c local ok, res = xpcall(function() "
        + body
        + " end, debug.traceback) "
        + "if ok then rcon.print(helpers.table_to_json({__v = res})) "
        + "else rcon.print(helpers.table_to_json({__lua_error = tostring(res)})) end"
    )
    out = rcon.send_command(wrapped)
    if out is None or out.strip() == "":
        return {"__lua_error": "empty RCON response (unwrapped error?)"}
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return {"__lua_error": f"non-JSON response: {out[:500]}"}
    if isinstance(data, dict) and "__lua_error" in data:
        return data
    if isinstance(data, dict):
        return data.get("__v", {"ok": True})
    return data


def lua_strict(rcon: Any, body: str) -> Any:
    res = lua(rcon, body)
    if isinstance(res, dict) and "__lua_error" in res:
        raise RuntimeError(f"Lua error: {res['__lua_error'][:800]}")
    return res


def as_list(v: Any) -> List[Any]:
    """helpers.table_to_json renders empty arrays as {} and sparse arrays as
    dicts; normalize to a Python list."""
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        return list(v.values())
    return []


def as_int_map(v: Any) -> Dict[int, int]:
    """Normalize a Lua table serialized as either JSON object (string keys)
    or JSON array (consecutive int keys; list index i -> Lua key i+1 — the
    check_L2_4/L2_5 serialization trap) into {int: int}."""
    if isinstance(v, list):
        return {i + 1: int(x) for i, x in enumerate(v) if x is not None}
    if isinstance(v, dict):
        return {int(k): int(x) for k, x in v.items() if x is not None}
    return {}


def bounds_lua(b: Dict) -> str:
    lt, rb = b["left_top"], b["right_bottom"]
    return (
        f"{{left_top={{x={lt['x']},y={lt['y']}}},"
        f"right_bottom={{x={rb['x']},y={rb['y']}}}}}"
    )


def in_bounds(x: float, y: float, b: Dict) -> bool:
    return (b["left_top"]["x"] <= x < b["right_bottom"]["x"]
            and b["left_top"]["y"] <= y < b["right_bottom"]["y"])


def cell_chunks(b: Dict) -> List[Tuple[int, int]]:
    """Chunk coords overlapping bounds (mirrors Map.lua bounds_to_chunks)."""
    lt, rb = b["left_top"], b["right_bottom"]
    return [(cx, cy)
            for cy in range(int(lt["y"]) // 32, (int(rb["y"]) - 1) // 32 + 1)
            for cx in range(int(lt["x"]) // 32, (int(rb["x"]) - 1) // 32 + 1)]


def chunk_in_some_play_area(cx: int, cy: int, cfg: Dict) -> bool:
    """Is chunk (cx, cy) inside SOME cell's play area? Derived from the
    scenario's own get_config values (cell_size/play_area_size/map_size),
    not hand constants."""
    chunk = int(cfg["chunk_size"])
    cell = int(cfg["cell_size"])
    play = int(cfg["play_area_size"])
    map_size = int(cfg["map_size"])
    x0, y0 = cx * chunk, cy * chunk
    if not (0 <= x0 < map_size and 0 <= y0 < map_size):
        return False
    return (x0 % cell) < play and (y0 % cell) < play


# ----------------------------------------------------------------------------
# Shared probes
# ----------------------------------------------------------------------------
def smoke(rcon: Any) -> Dict[str, Any]:
    rcon.send_command("/c rcon.print('ping')")
    assert "ping" in rcon.send_command("/c rcon.print('ping')"), "smoke ping failed"
    ifaces = json.loads(
        rcon.send_command("/c rcon.print(helpers.table_to_json(remote.interfaces))")
    )
    missing = [i for i in ("lab_grid", "agent", "map", "snapshot") if i not in ifaces]
    if missing:
        raise SystemExit(f"BLOCKED: missing remote interfaces {missing}")
    t1 = lua_strict(rcon, "return {tick=game.tick}")["tick"]
    time.sleep(1.5)
    t2 = lua_strict(rcon, "return {tick=game.tick}")["tick"]
    if t2 <= t1:
        finding(f"game.tick NOT advancing ({t1}->{t2}) — paused server distorts "
                "the boot-window gate (OQ3)")
    hb(f"smoke ok: {len(ifaces)} interfaces, tick {t1}->{t2}")
    return {"tick_start": t1, "wall_start": time.time()}


def get_storage(rcon: Any) -> Dict[str, Any]:
    """lab_grid storage with keys forced to strings Lua-side, so JSON shape
    is unambiguous regardless of the array/object serialization trap."""
    st = lua_strict(rcon, """
        local st = remote.call('lab_grid','get_storage')
        local ac, ca, cf = {}, {}, {}
        for k, v in pairs(st.agent_cells or {}) do ac[tostring(k)] = v end
        for k, v in pairs(st.cell_agents or {}) do ca[tostring(k)] = v end
        for k, v in pairs(st.cell_forces or {}) do cf[tostring(k)] = v end
        return {agent_cells=ac, cell_agents=ca, cell_forces=cf,
                initialized=st.initialized}
    """)
    return {
        "agent_cells": as_int_map(st.get("agent_cells")),
        "cell_agents": as_int_map(st.get("cell_agents")),
        "cell_forces": {int(k): v for k, v in (st.get("cell_forces") or {}).items()}
        if isinstance(st.get("cell_forces"), dict) else {},
        "initialized": st.get("initialized"),
        "raw": st,
    }


def assert_bijection(storage: Dict[str, Any], label: str, failures: List[str]) -> int:
    """Invariant 1, both directions over EVERY entry. Returns #entries."""
    ac, ca = storage["agent_cells"], storage["cell_agents"]
    for aid, ci in ac.items():
        if ca.get(ci) != aid:
            failures.append(
                f"BIJECTION[{label}] agent_cells[{aid}]={ci} but "
                f"cell_agents[{ci}]={ca.get(ci)!r}")
    for ci, aid in ca.items():
        if ac.get(aid) != ci:
            failures.append(
                f"BIJECTION[{label}] cell_agents[{ci}]={aid} but "
                f"agent_cells[{aid}]={ac.get(aid)!r}")
    cells = list(ac.values())
    if len(cells) != len(set(cells)):
        failures.append(f"BIJECTION[{label}] double-assigned cells: {sorted(cells)}")
    agents = list(ca.values())
    if len(agents) != len(set(agents)):
        failures.append(f"BIJECTION[{label}] one agent in multiple cells: {sorted(agents)}")
    return len(ac)


def lookup_snapshot_ticks(rcon: Any) -> Dict[Tuple[int, int], int]:
    """This boot's per-chunk snapshot ticks from map.get_chunk_lookup
    (shape live-verified 2026-06-11: dict keyed 'cx,cy', snapshot_tick int)."""
    lookup = lua(rcon, "return remote.call('map','get_chunk_lookup')")
    snapped: Dict[Tuple[int, int], int] = {}
    if isinstance(lookup, dict):
        for k, v in lookup.items():
            if isinstance(v, dict) and v.get("snapshot_tick") is not None:
                cx, cy = k.split(",")
                snapped[(int(cx), int(cy))] = int(v["snapshot_tick"])
    return snapped


def wait_fresh(rcon: Any, label: str, failures: List[str],
               want: Optional[Dict[Tuple[int, int], int]] = None
               ) -> List[Dict[str, Any]]:
    """Honest wait (the da0cb2f wait_for_cell_snapshot criterion, Stack-A
    edition). Timeout is a RECORDED FAILURE, never a silent proceed.

    Success criterion with `want` ((cx,cy)->min_tick): phase IDLE,
    write_queue_size == 0 (serialized AND flushed to disk), and every wanted
    chunk's lookup snapshot_tick >= min_tick. pending_chunks is deliberately
    NOT required to reach 0: it counts never-requested chunks map-wide, so
    it drains to 0 only on a fresh boot (first clean run) and idles >0
    forever once cell resets accumulate (live-observed 2026-06-11: stuck at
    54-63 for 120s while every wanted write had long landed) — the
    check_L2_5 premise holds on busy boots. Freshness of the chunks under
    test is the invariant; queue-wide drainage is not.

    Without `want`: phase IDLE + pending stable across 2 polls (legacy
    criterion, still honest because timeout records a failure).

    Replaces the OQ5 'IDLE + pending stable across 5 polls' criterion, which
    the first clean runs (2026-06-11) proved dishonest: the mod idles ~300
    ticks (5s) before processing enqueued re_snapshots, so 'stable
    pending=31' aliased the bootstrap window and the DB was read mid-flight
    (73 phantom failures run 1, 9 run 2; writes actually landed ~700+ ticks
    after create)."""
    timeline: List[Dict[str, Any]] = []
    stale: List[str] = []
    deadline = time.time() + DRAIN_TIMEOUT_S
    while time.time() < deadline:
        st = lua(rcon, "return remote.call('map','get_snapshot_status')")
        entry = {"t": round(time.time(), 1), "phase": st.get("phase"),
                 "pending": st.get("pending_chunks"),
                 "write_queue": st.get("write_queue_size")}
        timeline.append(entry)
        if want:
            if entry["phase"] == "IDLE" and entry["write_queue"] == 0:
                snapped = lookup_snapshot_ticks(rcon)
                stale = [f"({cx},{cy}) snapped@{snapped.get((cx, cy))} < {t}"
                         for (cx, cy), t in sorted(want.items())
                         if snapped.get((cx, cy), -1) < t]
                if not stale:
                    hb(f"wait_fresh ({label}): fresh+flushed after "
                       f"{len(timeline)} polls, last={timeline[-1]}")
                    return timeline
        else:
            tail = timeline[-2:]
            if (len(tail) == 2
                    and all(e["phase"] == "IDLE" for e in tail)
                    and len({e["pending"] for e in tail}) == 1):
                hb(f"wait_fresh ({label}): queue stable after "
                   f"{len(timeline)} polls, last={timeline[-1]}")
                return timeline
        time.sleep(1.0)
    detail = (f"{len(stale)} stale chunk(s): {stale[:8]}" if want
              else "queue never stabilized")
    failures.append(
        f"WAIT[{label}]: {DRAIN_TIMEOUT_S:.0f}s timeout — last={timeline[-1]}, "
        f"{detail} — wanted snapshot state never reached (the CELL-1 "
        "lying-wait class; downstream DB checks below may read mid-flight)")
    hb(f"wait_fresh ({label}): TIMEOUT after {len(timeline)} polls, "
       f"last={timeline[-1]}")
    return timeline


def fresh_db(db_path: Path):
    """Fresh Stack-A DB loaded from the instance's snapshot dir."""
    from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase
    from FactoryVerse.game.infra.duckdb.loader import SnapshotLoader

    if db_path.exists():
        db_path.unlink()
    db = SnapshotDatabase(db_path=str(db_path))
    db.ensure_schema()
    con = db.connection
    load = SnapshotLoader(db=con, snapshot_dir=SNAP_ROOT).load_all()
    stats = {"entity_count": load.entity_count,
             "resource_count": load.resource_count,
             "water_count": load.water_count,
             "ghost_count": load.ghost_count}
    return con, stats


def cell_engine_census(rcon: Any, b: Dict) -> Dict[str, Any]:
    """Raw engine truth for one cell: resource counts by name + spread spot
    sample, water count + engine-derived water bounding box, built entities.
    Shares no code with the snapshot mod or the loader."""
    res = lua_strict(rcon, f"""
        local s = game.surfaces[1]
        local area = {bounds_lua(b)}
        local per_chunk = {{}}
        local function bump(x, y)
            local k = math.floor(x / 32) .. ',' .. math.floor(y / 32)
            per_chunk[k] = (per_chunk[k] or 0) + 1
        end
        local counts, total, spots = {{}}, 0, {{}}
        for _, e in pairs(s.find_entities_filtered{{area=area, type='resource'}}) do
            counts[e.name] = (counts[e.name] or 0) + 1
            total = total + 1
            bump(e.position.x, e.position.y)
            if total % 53 == 1 and #spots < {SPOT_SAMPLE} then
                spots[#spots+1] = {{name=e.name, x=e.position.x, y=e.position.y}}
            end
        end
        local water = s.count_tiles_filtered{{area=area, name={WATER_TILE_NAMES}}}
        local wbox = nil
        for _, t in pairs(s.find_tiles_filtered{{area=area, name={WATER_TILE_NAMES}}}) do
            local p = t.position
            bump(p.x, p.y)
            if not wbox then
                wbox = {{min_x=p.x, min_y=p.y, max_x=p.x, max_y=p.y}}
            else
                if p.x < wbox.min_x then wbox.min_x = p.x end
                if p.y < wbox.min_y then wbox.min_y = p.y end
                if p.x > wbox.max_x then wbox.max_x = p.x end
                if p.y > wbox.max_y then wbox.max_y = p.y end
            end
        end
        local built = {{}}
        for _, e in pairs(s.find_entities_filtered{{area=area}}) do
            if e.type ~= 'resource' and e.type ~= 'character'
               and e.type ~= 'entity-ghost' and e.type ~= 'item-on-ground' then
                built[#built+1] = {{name=e.name, x=e.position.x, y=e.position.y,
                                    force=e.force.name}}
                bump(e.position.x, e.position.y)
            end
        end
        local chars = {{}}
        for _, c in pairs(s.find_entities_filtered{{area=area, type='character'}}) do
            chars[#chars+1] = {{x=c.position.x, y=c.position.y, force=c.force.name}}
        end
        return {{tick=game.tick, resource_total=total, resource_counts=counts,
                 spots=spots, water=water, water_box=wbox,
                 built=built, characters=chars, chunk_content=per_chunk}}
    """)
    res["spots"] = as_list(res.get("spots"))
    res["built"] = as_list(res.get("built"))
    res["characters"] = as_list(res.get("characters"))
    if not isinstance(res.get("resource_counts"), dict):
        res["resource_counts"] = {}
    if not isinstance(res.get("chunk_content"), dict):
        res["chunk_content"] = {}
    return res


def engine_has_resources_at(rcon: Any, specs: List[Dict]) -> List[Dict]:
    """DB->engine direction of the spot check: for each {name, tile_x, tile_y}
    assert a resource of that name occupies that tile (1-tile area probe —
    robust to the tile-vs-tile+0.5 coord convention, see OQ2). Returns the
    misses."""
    spec_lua = ",".join(
        f"{{name='{s['name']}', x={s['tile_x']}, y={s['tile_y']}}}" for s in specs
    )
    res = lua_strict(rcon, f"""
        local s = game.surfaces[1]
        local miss = {{}}
        for _, spec in pairs({{{spec_lua}}}) do
            local found = s.find_entities_filtered{{
                area={{left_top={{x=spec.x, y=spec.y}},
                      right_bottom={{x=spec.x+1, y=spec.y+1}}}},
                type='resource'}}
            local ok = false
            for _, e in pairs(found) do
                if e.name == spec.name then ok = true end
            end
            if not ok then miss[#miss+1] = spec end
        end
        return {{missing=miss, checked={len(specs)}}}
    """)
    return as_list(res.get("missing"))


def db_cell_rows(con, b: Dict) -> Dict[str, Any]:
    box = [b["left_top"]["x"], b["right_bottom"]["x"],
           b["left_top"]["y"], b["right_bottom"]["y"]]

    def count(table: str) -> int:
        return con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE position_x >= ? AND position_x < ? "
            f"AND position_y >= ? AND position_y < ?", box).fetchone()[0]

    res_by_name = dict(con.execute(
        "SELECT name, COUNT(*) FROM resource_tile WHERE position_x >= ? "
        "AND position_x < ? AND position_y >= ? AND position_y < ? GROUP BY name",
        box).fetchall())
    res_sample = con.execute(
        "SELECT name, position_x, position_y FROM resource_tile "
        "WHERE position_x >= ? AND position_x < ? AND position_y >= ? "
        "AND position_y < ? ORDER BY position_x, position_y LIMIT ?",
        box + [SPOT_SAMPLE]).fetchall()
    res_tiles = {(r[0], math.floor(float(r[1])), math.floor(float(r[2])))
                 for r in con.execute(
                     "SELECT name, position_x, position_y FROM resource_tile "
                     "WHERE position_x >= ? AND position_x < ? AND position_y >= ? "
                     "AND position_y < ?", box).fetchall()}
    water_box = con.execute(
        "SELECT MIN(position_x), MIN(position_y), MAX(position_x), MAX(position_y) "
        "FROM water_tile WHERE position_x >= ? AND position_x < ? "
        "AND position_y >= ? AND position_y < ?", box).fetchone()
    entities = con.execute(
        "SELECT entity_name, position_x, position_y FROM map_entity "
        "WHERE position_x >= ? AND position_x < ? AND position_y >= ? "
        "AND position_y < ?", box).fetchall()
    return {
        "resource_count": count("resource_tile"),
        "water_count": count("water_tile"),
        "resource_by_name": res_by_name,
        "resource_sample": [{"name": r[0], "x": float(r[1]), "y": float(r[2])}
                            for r in res_sample],
        "resource_tile_set": res_tiles,
        "water_box": None if water_box[0] is None else {
            "min_x": float(water_box[0]), "min_y": float(water_box[1]),
            "max_x": float(water_box[2]), "max_y": float(water_box[3])},
        "entities": [{"name": r[0], "x": float(r[1]), "y": float(r[2])}
                     for r in entities],
    }


def vision_battery(rcon: Any, ci: int, census: Dict[str, Any],
                   db: Dict[str, Any], failures: List[str]) -> int:
    """The CELL-1 vision invariant, shared by both paths: anti-vacuity
    floors, two-sided count equality, spot positions both directions,
    water count + bounding box. Returns spot checks performed. Extracted
    verbatim from the scenario path's phase 4 (clean-run green dbe4cd4)."""
    spots_done = 0

    # anti-vacuity floors
    if census["resource_total"] < MIN_CELL_RESOURCE_TILES:
        failures.append(
            f"FLOOR cell {ci}: engine census {census['resource_total']} "
            f"resource tiles < {MIN_CELL_RESOURCE_TILES} — barren cell "
            "(SNAP-1a class), nothing here can certify vision")
    if db["resource_count"] + db["water_count"] < MIN_DB_WATER_ORE_ROWS:
        failures.append(
            f"FLOOR cell {ci}: DB water+ore rows "
            f"{db['resource_count'] + db['water_count']} < "
            f"{MIN_DB_WATER_ORE_ROWS} — the CELL-1 emptiness signature")

    # 4a. counts, both directions (exact equality)
    if db["resource_count"] != census["resource_total"]:
        failures.append(f"VISION cell {ci}: resource_tile DB "
                        f"{db['resource_count']} != engine "
                        f"{census['resource_total']}")
    for name, n in sorted(census["resource_counts"].items()):
        if db["resource_by_name"].get(name, 0) != n:
            failures.append(f"VISION cell {ci}: {name} DB "
                            f"{db['resource_by_name'].get(name, 0)} != "
                            f"engine {n}")
    for name, n in sorted(db["resource_by_name"].items()):
        if census["resource_counts"].get(name, 0) != n:
            failures.append(f"VISION cell {ci}: DB has {n} {name} rows, "
                            f"engine has {census['resource_counts'].get(name, 0)}")

    # 4a. spot positions, engine -> DB (floored tile coords, OQ2)
    engine_spots = census["spots"]
    if len(engine_spots) < MIN_SPOT_CHECKS:
        failures.append(f"FLOOR cell {ci}: only {len(engine_spots)} engine "
                        f"spot samples (< {MIN_SPOT_CHECKS})")
    for sp in engine_spots:
        key = (sp["name"], math.floor(float(sp["x"])), math.floor(float(sp["y"])))
        if key not in db["resource_tile_set"]:
            failures.append(f"VISION cell {ci}: engine resource {key} has "
                            "NO resource_tile row in DB")
    spots_done += len(engine_spots)

    # 4a. spot positions, DB -> engine
    db_specs = [{"name": s["name"],
                 "tile_x": math.floor(s["x"]), "tile_y": math.floor(s["y"])}
                for s in db["resource_sample"]]
    if len(db_specs) < MIN_SPOT_CHECKS:
        failures.append(f"FLOOR cell {ci}: only {len(db_specs)} DB spot "
                        f"samples (< {MIN_SPOT_CHECKS})")
    if db_specs:
        misses = engine_has_resources_at(rcon, db_specs)
        for m in misses:
            failures.append(f"VISION cell {ci}: DB resource_tile "
                            f"{m} has NO engine resource at that tile "
                            "(stale/foreign row — CELL-1/CELL-2 signature)")
        spots_done += len(db_specs)

    # 4b. water: count + engine-derived bounding box
    if census["water"] == 0:
        failures.append(f"VISION cell {ci}: engine reports 0 water tiles — "
                        "broken cell layout (SNAP-1a class)")
    if db["water_count"] != census["water"]:
        failures.append(f"VISION cell {ci}: water_tile DB {db['water_count']} "
                        f"!= engine {census['water']}")
    ebox, dbox = census.get("water_box"), db.get("water_box")
    if ebox and not dbox:
        failures.append(f"VISION cell {ci}: engine water box {ebox} but DB "
                        "has no water rows in-cell")
    elif ebox and dbox:
        for k in ("min_x", "min_y", "max_x", "max_y"):
            if math.floor(float(dbox[k])) != math.floor(float(ebox[k])):
                failures.append(f"VISION cell {ci}: water box {k} DB "
                                f"{dbox[k]} != engine {ebox[k]}")
    hb(f"cell {ci} vision: res {db['resource_count']}/{census['resource_total']} "
       f"water {db['water_count']}/{census['water']} "
       f"spots {len(engine_spots)}+{len(db_specs)}")
    return spots_done


def rv_conn(remote_view: Any) -> Any:
    """db_cell_rows-compatible shim over RemoteView.execute_raw — the
    UNIFIED agent query path (CELL-1 item 6: same connection, lock and
    flush-before-read as remote_view.query/execute_duckdb). Numeric
    placeholders are inlined because execute_raw takes SQL only."""
    class _Res:
        def __init__(self, rows): self._rows = rows
        def fetchall(self): return self._rows
        def fetchone(self): return self._rows[0] if self._rows else (None,)

    class _Conn:
        def execute(self, sql: str, params: Optional[List[Any]] = None) -> "_Res":
            for p in (params or []):
                lit = repr(float(p)) if isinstance(p, float) else str(int(p))
                sql = sql.replace("?", lit, 1)
            return _Res(remote_view.execute_raw(sql))

    return _Conn()


# ----------------------------------------------------------------------------
# The orchestrator path (the CELL-1 field-run path, driven for real)
# ----------------------------------------------------------------------------
async def _orchestrator_cycles(rcon: Any, agents: int, instance: str,
                               failures: List[str],
                               counters: Dict[str, Any]) -> List[Dict[str, Any]]:
    """`agents` sequential allocate->verify->release cycles through the REAL
    Environment stack — env.orchestrator._allocate_cell/_release_cell, the
    exact calls run_task makes. Engine truth via this harness's own RCON;
    vision via the orchestrator's OWN session DB through the unified
    RemoteView.execute_raw path."""
    from FactoryVerse.environment.environment import Environment, Tier
    from FactoryVerse.environment.config import (
        EnvironmentConfig, ExecutionMode, InfraConfig, InfraMode,
        PythonConfig, RuntimeConfig, RuntimeVariant, SettingsConfig)

    hb(f"PHASE O0: building the REAL Environment stack (tiers 1-4, "
       f"instance={instance}, variant=FULL, in-process execution)")
    env = Environment(config=EnvironmentConfig(
        # EXTERNAL: attach to the running instance, manage NO lifecycles.
        # The default (CLIENT) made tier1 adopt + SIGTERM a pre-existing
        # client on shutdown; SERVER would have cleared the RUNNING boot's
        # snapshot dirs (CELL-2b clear fires in start_server) and claimed
        # compose-down ownership of the live server. Both live-observed
        # or traced 2026-06-11.
        tier1=InfraConfig(mode=InfraMode.EXTERNAL),
        tier2=SettingsConfig(scenario="lab-grid"),
        tier3=PythonConfig(instance=instance),
        tier4=RuntimeConfig(variant=RuntimeVariant.FULL,
                            agent_id="agent_1",
                            execution_mode=ExecutionMode.INPROCESS),
    ))
    cycles: List[Dict[str, Any]] = []
    try:
        await env.initialize(up_to=Tier.RUNTIME)
        tier4 = env.tier4
        orch = env.orchestrator
        if tier4 is None or tier4.scenario is None:
            failures.append("O0: tier4/scenario is None after RUNTIME init — "
                            "adapter never built")
            return cycles
        aid = int((tier4.config.agent_id or "agent_1").split("_")[1])

        for cyc in range(1, agents + 1):
            cycle: Dict[str, Any] = {"cycle": cyc}
            tick_before = int(lua_strict(rcon, "return game.tick"))
            cycle["tick_before"] = tick_before
            hb(f"PHASE O1 (cycle {cyc}/{agents}): orchestrator._allocate_cell "
               f"(tick_before={tick_before}) — run_task's exact call")

            # O1 + O6 (first half): _allocate_cell includes the honest wait,
            # the post-allocation reload AND the T0 preflight — it raising
            # IS the failure signal, never a silent wrong state.
            try:
                cell = await orch._allocate_cell(None)
            except Exception as e:  # noqa: BLE001
                failures.append(f"O1 cycle {cyc}: _allocate_cell raised: "
                                f"{type(e).__name__}: {e}")
                break
            if cell is None:
                failures.append(f"O1 cycle {cyc}: _allocate_cell returned None "
                                "on a lab-grid runtime (adapter missing?)")
                break
            cycle["cell"] = cell
            counters["alloc_cycles"] += 1
            counters["cells_touched"].append(cell)
            hb(f"O1: allocated cell {cell} for agent {aid}")

            b = lua_strict(rcon,
                           f"return remote.call('lab_grid','get_cell_bounds',{cell})")
            storage = get_storage(rcon)
            assert_bijection(storage, f"O1-cycle{cyc}", failures)
            if storage["agent_cells"].get(aid) != cell:
                failures.append(f"O1 cycle {cyc}: orchestrator says cell {cell} "
                                f"but storage agent_cells[{aid}]="
                                f"{storage['agent_cells'].get(aid)!r}")
            if storage["cell_agents"].get(cell) != aid:
                failures.append(f"O1 cycle {cyc}: storage cell_agents[{cell}]="
                                f"{storage['cell_agents'].get(cell)!r}, "
                                f"expected {aid}")

            # O2: body placement + force isolation (engine truth)
            census = cell_engine_census(rcon, b)
            cell_force = lua_strict(
                rcon, f"return remote.call('lab_grid','get_cell_force',{cell})")
            cell_force = (cell_force if isinstance(cell_force, str)
                          else str(cell_force))
            chars = census["characters"]
            if len(chars) != 1:
                failures.append(f"O2 cycle {cyc}: expected exactly 1 character in "
                                f"cell {cell}, engine sees {len(chars)}: {chars}")
            else:
                ch = chars[0]
                if not in_bounds(ch["x"], ch["y"], b):
                    failures.append(f"O2 cycle {cyc}: body ({ch['x']},{ch['y']}) "
                                    f"OUTSIDE cell {cell} bounds — the CELL-1 "
                                    "body half")
                if ch["force"] != cell_force:
                    failures.append(f"O2 cycle {cyc}: character force "
                                    f"{ch['force']!r} != cell force "
                                    f"{cell_force!r}")

            # O4: honest-wait evidence. _allocate_cell already awaited the
            # per-cell wait; if any cell chunk's lookup tick predates the
            # allocation, that wait lied (the field-run class).
            snapped = lookup_snapshot_ticks(rcon)
            stale = [f"({cx},{cy}) snapped@{snapped.get((cx, cy))} < {tick_before}"
                     for (cx, cy) in cell_chunks(b)
                     if snapped.get((cx, cy), -1) < tick_before]
            if stale:
                failures.append(f"O4 cycle {cyc}: wait_for_cell_snapshot returned "
                                f"but {len(stale)} cell chunk(s) are stale: "
                                f"{stale[:6]} — the lying-wait class")

            # O3: vision on the orchestrator's OWN session DB via the
            # unified RemoteView.execute_raw path (the field-failure surface)
            rv = tier4.remote_view
            if rv is None or not rv.is_loaded:
                failures.append(f"O3 cycle {cyc}: tier4.remote_view is "
                                f"{'None' if rv is None else 'not loaded'} "
                                "post-allocation — session DB uninspectable")
            else:
                db = db_cell_rows(rv_conn(rv), b)
                cycle["db"] = {k: v for k, v in db.items()
                               if k != "resource_tile_set"}
                counters["spot_checks"] += vision_battery(
                    rcon, cell, census, db, failures)

                # O5: one DB truth (CELL-1 item 6). The design is two holders
                # (tier4's SnapshotDatabase + RemoteView's) reloaded from the
                # same files in the same reload, with the agent-facing
                # execute_duckdb routed through execute_raw — so the honest
                # assertion is content equality across both connections.
                sql = ("SELECT (SELECT COUNT(*) FROM resource_tile), "
                       "(SELECT COUNT(*) FROM water_tile), "
                       "(SELECT COUNT(*) FROM map_entity)")
                via_rv = rv.execute_raw(sql)
                via_db = tier4.database.execute(sql).fetchall()
                if via_rv != via_db:
                    failures.append(f"O5 cycle {cyc}: execute_raw {via_rv} != "
                                    f"tier4.database {via_db} on the same SQL "
                                    "— two DB truths (CELL-1 item 6 regressed)")
                counters["db_truth_checks"] += 1

            # O6 (second half): explicit preflight re-run must stay silent
            try:
                orch._verify_cell_coherence(cell, aid)
            except Exception as e:  # noqa: BLE001
                failures.append(f"O6 cycle {cyc}: T0 preflight raised on a "
                                f"settled allocation: {e}")

            # O7: release unbinds (engine truth); next cycle re-allocates —
            # that IS the reuse invariant.
            hb(f"PHASE O7 (cycle {cyc}): orchestrator._release_cell({cell})")
            await orch._release_cell(cell, reset=True)
            storage = get_storage(rcon)
            if storage["agent_cells"].get(aid) is not None:
                failures.append(f"O7 cycle {cyc}: agent {aid} still bound to "
                                f"{storage['agent_cells'].get(aid)} after "
                                "release")
            if storage["cell_agents"].get(cell) is not None:
                failures.append(f"O7 cycle {cyc}: cell {cell} still holds agent "
                                f"{storage['cell_agents'].get(cell)} after "
                                "release")
            assert_bijection(storage, f"O7-cycle{cyc}", failures)
            cycles.append(cycle)
    finally:
        try:
            await env.shutdown()
            hb("PHASE O8: env.shutdown() clean")
        except Exception as e:  # noqa: BLE001
            failures.append(f"O8: env.shutdown() raised: {e}")
    return cycles


def run_check_orchestrator(instance: str, agents: int,
                           artifacts_dir: Optional[str]) -> Dict[str, Any]:
    """--path orchestrator entry: same verdict contract as run_check."""
    global ART, PROGRESS
    configure_instance(instance)
    date = datetime.date.today().isoformat()
    if artifacts_dir:
        ART = Path(artifacts_dir)
    else:
        ART = REPO / ".fv-output" / "certification" / date / CHECK_ID
        if instance != "client":
            ART = ART / instance
    ART.mkdir(parents=True, exist_ok=True)
    PROGRESS = ART / "progress_orchestrator.log"

    commit = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True).stdout.strip()
    hb(f"=== check_cell_coherence start (instance={instance}, agents={agents}, "
       f"path=orchestrator, commit={commit}) ===")

    from factorio_rcon import RCONClient
    try:
        rcon = RCONClient(RCON_HOST, RCON_PORT, RCON_PASS)
    except Exception as e:  # noqa: BLE001
        return {"status": "BLOCKED",
                "blocked_reason": f"cannot connect RCON {RCON_HOST}:{RCON_PORT}: {e}",
                "failures": [], "counters": {}}

    failures: List[str] = []
    counters: Dict[str, Any] = {"alloc_cycles": 0, "cells_touched": [],
                                "spot_checks": 0, "db_truth_checks": 0}
    try:
        boot = smoke(rcon)
        results["smoke"] = boot
        pre_storage = get_storage(rcon)
        if pre_storage["agent_cells"]:
            finding(f"pre-existing agent bindings: {pre_storage['agent_cells']} "
                    "(OQ7: bijection is asserted globally)")
        results["phases"]["orchestrator_cycles"] = asyncio.run(
            _orchestrator_cycles(rcon, agents, instance, failures, counters))
    except Exception as e:  # noqa: BLE001
        import traceback
        failures.append(f"UNHANDLED: {type(e).__name__}: {e}")
        (ART / "traceback_orchestrator.txt").write_text(traceback.format_exc())

    counters["failures"] = len(failures)
    # anti-vacuity: a PASS that never completed its cycles is vacuous
    if not failures and counters["alloc_cycles"] < agents:
        status = "VACUOUS-RISK"
    elif not failures and counters["spot_checks"] < MIN_SPOT_CHECKS * agents:
        status = "VACUOUS-RISK"
    else:
        status = "PASS" if not failures else "FAIL"
    now_tick = lua(rcon, "return game.tick")
    verdict = {"status": status, "failures": failures, "counters": counters,
               "commit": commit, "tick": now_tick, "path": "orchestrator"}
    results["verdict"] = verdict
    save("results_orchestrator.json", results)
    hb("=== check_cell_coherence end (orchestrator) ===")
    return verdict


# ----------------------------------------------------------------------------
# The check
# ----------------------------------------------------------------------------
def run_check(instance: str = "server_0", agents: int = 2,
              path: str = "scenario",
              artifacts_dir: Optional[str] = None) -> Dict[str, Any]:
    """Core entry point (also used by tests/live/test_cell_coherence.py).

    Returns a verdict dict: {"status": PASS|FAIL|BLOCKED|VACUOUS-RISK,
    "failures": [...], "counters": {...}, "blocked_reason": ...}.
    """
    global ART, PROGRESS
    if agents < MIN_AGENTS:
        return {"status": "BLOCKED",
                "blocked_reason": f"--agents {agents} < {MIN_AGENTS} "
                                  "(anti-vacuity floor)",
                "failures": [], "counters": {}}
    if path == "orchestrator":
        return run_check_orchestrator(instance=instance, agents=agents,
                                      artifacts_dir=artifacts_dir)
    if path != "scenario":
        return {"status": "BLOCKED",
                "blocked_reason": f"unknown --path {path!r}",
                "failures": [], "counters": {}}

    configure_instance(instance)
    date = datetime.date.today().isoformat()
    if artifacts_dir:
        ART = Path(artifacts_dir)
    else:
        ART = REPO / ".fv-output" / "certification" / date / CHECK_ID
        if instance != "client":
            ART = ART / instance
    ART.mkdir(parents=True, exist_ok=True)
    PROGRESS = ART / "progress.log"

    commit = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True).stdout.strip()
    hb(f"=== check_cell_coherence start (instance={instance}, agents={agents}, "
       f"path={path}, commit={commit}) ===")

    from factorio_rcon import RCONClient
    try:
        rcon = RCONClient(RCON_HOST, RCON_PORT, RCON_PASS)
    except Exception as e:  # noqa: BLE001
        return {"status": "BLOCKED",
                "blocked_reason": f"cannot connect RCON {RCON_HOST}:{RCON_PORT}: {e}",
                "failures": [], "counters": {}}

    failures: List[str] = []
    created: List[Dict[str, Any]] = []   # our agents, in creation order
    markers_placed: List[Dict[str, Any]] = []
    marker_cell_bounds: Optional[Dict] = None

    try:
        boot = smoke(rcon)
        results["smoke"] = boot
        cfg = lua_strict(rcon, "return remote.call('lab_grid','get_config')")
        results["grid_config"] = cfg

        pre_storage = get_storage(rcon)
        results["phases"]["pre_storage"] = {k: v for k, v in pre_storage.items()
                                            if k != "raw"}
        if pre_storage["agent_cells"]:
            finding(f"pre-existing agent bindings: {pre_storage['agent_cells']} "
                    "(OQ7: bijection is asserted globally)")

        # ---- Invariant 1: allocation via the scenario's own path ------------
        hb(f"PHASE 1: creating {agents} agents via "
           "lab_grid.create_agent_in_cell (no cell_index — scenario allocates)")
        for i in range(agents):
            r = lua_strict(rcon, """
                local before = game.tick
                local res = remote.call('lab_grid','create_agent_in_cell')
                return {tick_before=before, create=res, tick_after=game.tick}
            """)
            create = r.get("create") or {}
            if not create.get("success"):
                save("results.json", results)
                return {"status": "BLOCKED",
                        "blocked_reason": f"create #{i + 1} failed: {create}",
                        "failures": failures, "counters": {}}
            ci = int(create["cell_index"])
            aid = int(create["agent_id"])
            b = lua_strict(rcon, f"return remote.call('lab_grid','get_cell_bounds',{ci})")
            created.append({"agent_id": aid, "cell_index": ci,
                            "force_name": create.get("force_name"),
                            "spawn_position": create.get("spawn_position"),
                            "bounds": b, "tick_before": r["tick_before"],
                            "tick_after": r["tick_after"]})
            hb(f"created agent {aid} -> cell {ci} (force {create.get('force_name')}, "
               f"tick {r['tick_before']}->{r['tick_after']})")
            storage = get_storage(rcon)
            assert_bijection(storage, f"after-create-{aid}", failures)
            if storage["agent_cells"].get(aid) != ci:
                failures.append(f"ALLOC agent {aid}: create returned cell {ci} but "
                                f"storage says {storage['agent_cells'].get(aid)!r}")
            if storage["cell_agents"].get(ci) != aid:
                failures.append(f"ALLOC cell {ci}: expected agent {aid}, storage says "
                                f"{storage['cell_agents'].get(ci)!r}")
        results["phases"]["created"] = [
            {k: v for k, v in c.items() if k != "bounds"} for c in created]
        our_cells = [c["cell_index"] for c in created]
        if len(set(our_cells)) != len(our_cells):
            failures.append(f"ALLOC: scenario assigned duplicate cells: {our_cells}")

        # ---- Invariants 2+3: body placement + force isolation ----------------
        hb("PHASE 2/3: body placement + force isolation")
        body_checks = []
        for c in created:
            aid, ci, b = c["agent_id"], c["cell_index"], c["bounds"]
            raw_pos = lua(rcon, f"return remote.call('agent_{aid}','get_position')")
            pos = raw_pos.get("position", raw_pos) if isinstance(raw_pos, dict) else {}
            px, py = pos.get("x"), pos.get("y")  # OQ1
            if px is None or py is None:
                failures.append(f"BODY agent {aid}: cannot extract position from "
                                f"{json.dumps(raw_pos)[:200]} (OQ1)")
            else:
                if not in_bounds(px, py, b):
                    failures.append(f"BODY agent {aid}: position ({px},{py}) is "
                                    f"OUTSIDE its cell {ci} bounds {b} — the CELL-1 "
                                    "body half")
                for other in created:
                    if other["agent_id"] != aid and in_bounds(px, py, other["bounds"]):
                        failures.append(f"BODY agent {aid}: position ({px},{py}) "
                                        f"inside agent {other['agent_id']}'s cell "
                                        f"{other['cell_index']}")
            cell_force = lua_strict(
                rcon, f"return remote.call('lab_grid','get_cell_force',{ci})")
            cell_force = cell_force if isinstance(cell_force, str) else str(cell_force)
            census = cell_engine_census(rcon, b)
            c["census"] = census
            chars = census["characters"]
            if len(chars) != 1:
                failures.append(f"BODY agent {aid}: expected exactly 1 character in "
                                f"cell {ci}, engine sees {len(chars)}: {chars}")
            else:
                ch = chars[0]
                if ch["force"] != cell_force:
                    failures.append(f"FORCE agent {aid}: character force "
                                    f"{ch['force']!r} != cell force {cell_force!r}")
                if c["force_name"] and ch["force"] != c["force_name"]:
                    failures.append(f"FORCE agent {aid}: character force "
                                    f"{ch['force']!r} != create result "
                                    f"{c['force_name']!r}")
                if px is not None and (abs(ch["x"] - px) > 2 or abs(ch["y"] - py) > 2):
                    failures.append(f"BODY agent {aid}: get_position ({px},{py}) "
                                    f"disagrees with engine character "
                                    f"({ch['x']},{ch['y']}) by >2 tiles")
            body_checks.append({"agent_id": aid, "cell": ci, "raw_pos": raw_pos,
                                "cell_force": cell_force,
                                "characters": chars})
        forces = [c["force_name"] for c in created]
        if len(set(forces)) != len(forces):
            failures.append(f"FORCE: forces not pairwise distinct: {forces}")
        results["phases"]["body_force"] = body_checks

        # ---- Invariant 4: vision scope = body cell (CELL-1) -------------------
        hb("PHASE 4: snapshot settle + fresh DB load (CELL-1 invariant)")
        want_fresh: Dict[Tuple[int, int], int] = {}
        for c in created:
            for ch in cell_chunks(c["bounds"]):
                want_fresh[ch] = max(want_fresh.get(ch, 0),
                                     int(c["tick_before"]))
        wait_fresh(rcon, "post-create settle", failures, want=want_fresh)
        con, load_stats = fresh_db(ART / "session_postcreate.duckdb")
        results["phases"]["db_load_postcreate"] = load_stats
        hb(f"DB loaded: {load_stats}")

        spot_checks_total = 0
        for c in created:
            aid, ci, b = c["agent_id"], c["cell_index"], c["bounds"]
            census = c["census"]
            db = db_cell_rows(con, b)
            c["db_postcreate"] = {k: v for k, v in db.items()
                                  if k != "resource_tile_set"}

            spot_checks_total += vision_battery(rcon, ci, census, db, failures)

        # 4c. GLOBAL coherence (CELL-2): every DB row in a this-boot, charted,
        # play-area chunk.
        hb("PHASE 4c: global DB scope (CELL-2 invariant)")
        now_tick = lua_strict(rcon, "return {tick=game.tick}")["tick"]
        db_chunks = con.execute("""
            SELECT chunk_x, chunk_y, SUM(n) FROM (
                SELECT chunk_x, chunk_y, COUNT(*) n FROM map_entity GROUP BY 1,2
                UNION ALL
                SELECT chunk_x, chunk_y, COUNT(*) FROM resource_tile GROUP BY 1,2
                UNION ALL
                SELECT chunk_x, chunk_y, COUNT(*) FROM water_tile GROUP BY 1,2
            ) GROUP BY 1, 2 ORDER BY 1, 2
        """).fetchall()
        meta = {(int(r[0]), int(r[1])): int(r[2]) for r in con.execute(
            "SELECT chunk_x, chunk_y, tick FROM chunk_snapshot_meta").fetchall()}
        if not meta:
            failures.append("CELL-2: chunk_snapshot_meta is EMPTY while DB has "
                            f"{len(db_chunks)} populated chunks — freshness "
                            "unfalsifiable (SNAP-1c regressed?)")
        lookup_raw = lua_strict(rcon, "return remote.call('map','get_chunk_lookup')")
        if not isinstance(lookup_raw, dict):
            failures.append(f"CELL-2: get_chunk_lookup returned "
                            f"{type(lookup_raw).__name__}, cannot verify boot scope "
                            "(OQ8)")
            lookup_raw = {}
        ingame_snapped = {}
        for k, v in lookup_raw.items():
            if isinstance(v, dict) and v.get("snapshot_tick") is not None:
                cx, cy = k.split(",")
                ingame_snapped[(int(cx), int(cy))] = v["snapshot_tick"]

        boot_wall_floor = (boot["wall_start"]
                           - boot["tick_start"] / 60.0
                           - BOOT_WINDOW_SLACK_S)
        cell2_report = []
        for cx, cy, nrows in db_chunks:
            cx, cy = int(cx), int(cy)
            row = {"chunk": [cx, cy], "rows": int(nrows)}
            if not chunk_in_some_play_area(cx, cy, cfg):
                failures.append(f"CELL-2: chunk ({cx},{cy}) holds {nrows} DB rows "
                                "but lies in NO cell play area (gap/out-of-grid)")
            mtick = meta.get((cx, cy))
            row["meta_tick"] = mtick
            if mtick is None:
                if meta:
                    failures.append(f"CELL-2: chunk ({cx},{cy}) has {nrows} DB rows "
                                    "but NO chunk_snapshot_meta tick")
            elif mtick > now_tick:
                failures.append(f"CELL-2: chunk ({cx},{cy}) meta tick {mtick} > "
                                f"current game tick {now_tick} — previous-boot "
                                "file (future-tick signature)")
            row["ingame_tick"] = ingame_snapped.get((cx, cy))
            if lookup_raw and (cx, cy) not in ingame_snapped:
                failures.append(f"CELL-2: chunk ({cx},{cy}) has {nrows} DB rows but "
                                "this boot's chunk lookup never snapshotted it — "
                                "stale-dir contamination (the CELL-2 field failure)")
            d = SNAP_ROOT / "factoryverse" / "snapshots" / str(cx) / str(cy)
            mtimes = ([f.stat().st_mtime for f in d.iterdir()
                       if f.is_file() and "-init" in f.name] if d.is_dir() else [])
            row["oldest_init_mtime"] = min(mtimes) if mtimes else None
            if not mtimes:
                failures.append(f"CELL-2: chunk ({cx},{cy}) has DB rows but no init "
                                "files on disk")
            elif min(mtimes) < boot_wall_floor:
                failures.append(
                    f"CELL-2: chunk ({cx},{cy}) init file mtime "
                    f"{datetime.datetime.fromtimestamp(min(mtimes)).isoformat()} "
                    f"predates this boot's window (floor "
                    f"{datetime.datetime.fromtimestamp(boot_wall_floor).isoformat()}, "
                    "OQ3) — previous-boot file")
            cell2_report.append(row)
        # two-sided, scoped to CONTENT-BEARING chunks: engine-empty chunks
        # legitimately produce no init files and no DB rows (settled by the
        # 2026-06-11 draft run — see DRAFT-RUN NOTE in the module docstring).
        db_chunk_set = {(int(r[0]), int(r[1])) for r in db_chunks}
        for c in created:
            content_chunks = {
                tuple(int(v) for v in k.split(","))
                for k, n in c["census"]["chunk_content"].items() if n > 0
            }
            if not content_chunks:
                failures.append(f"CELL-2: agent {c['agent_id']} cell "
                                f"{c['cell_index']} engine census found NO "
                                "content-bearing chunks — barren cell, "
                                "vision unfalsifiable")
            missing = sorted(content_chunks - db_chunk_set)
            if missing:
                failures.append(f"CELL-2: agent {c['agent_id']} cell "
                                f"{c['cell_index']} content chunks {missing} have "
                                "ZERO DB rows — its vision never landed "
                                "(CELL-1 DB half)")
            extra = sorted((set(cell_chunks(c["bounds"])) & db_chunk_set)
                           - content_chunks)
            if extra:
                failures.append(f"CELL-2: agent {c['agent_id']} cell "
                                f"{c['cell_index']} chunks {extra} hold DB rows "
                                "but the engine sees NO content there — stale "
                                "rows (CELL-2 signature)")
            no_meta = sorted(ch for ch in content_chunks if ch not in meta)
            if meta and no_meta:
                failures.append(f"CELL-2: agent {c['agent_id']} cell "
                                f"{c['cell_index']} content chunks {no_meta} "
                                "lack chunk_snapshot_meta ticks")
            mticks = [meta.get(ch) for ch in cell_chunks(c["bounds"])]
            stale = [t for t in mticks if t is not None and t < c["tick_before"]]
            if stale:
                failures.append(f"CELL-2: agent {c['agent_id']} cell "
                                f"{c['cell_index']} has chunk meta ticks {stale} "
                                f"OLDER than its create (tick {c['tick_before']}) — "
                                "create's re_snapshot never landed")
        results["phases"]["cell2"] = {"now_tick": now_tick,
                                      "boot_wall_floor": boot_wall_floor,
                                      "chunks": cell2_report}
        con.close()

        # ---- Invariant 5: cross-instance visibility ---------------------------
        a, bgt = created[0], created[1]
        marker_cell_bounds = a["bounds"]
        lt = a["bounds"]["left_top"]
        markers = [
            {"name": "iron-chest", "x": lt["x"] + 6.5, "y": lt["y"] + 6.5},
            {"name": "stone-furnace", "x": lt["x"] + 10.0, "y": lt["y"] + 7.0},
            {"name": "wooden-chest", "x": lt["x"] + 14.5, "y": lt["y"] + 6.5},
        ]
        assert len(markers) >= MIN_MARKERS
        hb(f"PHASE 5: placing {len(markers)} markers in cell {a['cell_index']} "
           f"(force {a['force_name']}, raise_built=true)")
        spec_lua = ",".join(f"{{name='{m['name']}', x={m['x']}, y={m['y']}}}"
                            for m in markers)
        place = lua_strict(rcon, f"""
            local s = game.surfaces[1]
            local placed = {{}}
            for _, spec in pairs({{{spec_lua}}}) do
                local e = s.create_entity{{name=spec.name,
                    position={{x=spec.x, y=spec.y}},
                    force='{a["force_name"]}', raise_built=true}}
                placed[#placed+1] = {{name=spec.name,
                    ok=(e ~= nil and e.valid),
                    x=(e and e.position.x or nil), y=(e and e.position.y or nil)}}
            end
            return {{placed=placed}}
        """)
        placed = [p for p in as_list(place.get("placed")) if p.get("ok")]
        markers_placed = placed
        results["phases"]["markers"] = place
        if len(placed) < MIN_MARKERS:
            failures.append(f"MARKERS: only {len(placed)}/{len(markers)} placed "
                            f"(< {MIN_MARKERS}) — invariant 5 cannot be certified")
        resnap_tick = lua_strict(rcon, "return game.tick")
        lua_strict(rcon, "return remote.call('map','re_snapshot_area',"
                         f"{bounds_lua(a['bounds'])},50)")
        wait_fresh(rcon, "marker snapshot", failures,
                   want={ch: int(resnap_tick)
                         for ch in cell_chunks(a["bounds"])})
        con2, load2 = fresh_db(ART / "session_postmarker.duckdb")
        results["phases"]["db_load_postmarker"] = load2
        db_a = db_cell_rows(con2, a["bounds"])
        db_b = db_cell_rows(con2, bgt["bounds"])
        marker_names = {m["name"] for m in markers}
        a_rows = {(e["name"], round(e["x"], 1), round(e["y"], 1))
                  for e in db_a["entities"] if e["name"] in marker_names}
        for m in placed:
            key = (m["name"], round(float(m["x"]), 1), round(float(m["y"]), 1))
            if key not in a_rows:
                failures.append(f"XCELL: marker {key} placed in cell "
                                f"{a['cell_index']} missing from DB at A's coords")
        b_marker_rows = [e for e in db_b["entities"] if e["name"] in marker_names]
        if b_marker_rows:
            failures.append(f"XCELL: marker-named rows inside cell "
                            f"{bgt['cell_index']} (B) bounds: {b_marker_rows} — "
                            "vision bleed (CELL-1 signature)")
        bgt_census2 = cell_engine_census(rcon, bgt["bounds"])
        if len(db_b["entities"]) != len(bgt_census2["built"]):
            failures.append(f"XCELL: cell {bgt['cell_index']} DB has "
                            f"{len(db_b['entities'])} map_entity rows, engine has "
                            f"{len(bgt_census2['built'])} — B's cell changed or DB "
                            "drifted while only A was mutated")
        # bounds disjointness (engine truth)
        a_set = {(e["name"], round(e["x"], 1), round(e["y"], 1))
                 for e in cell_engine_census(rcon, a["bounds"])["built"]}
        b_set = {(e["name"], round(e["x"], 1), round(e["y"], 1))
                 for e in bgt_census2["built"]}
        if a_set & b_set:
            failures.append(f"XCELL: engine entity sets of cells "
                            f"{a['cell_index']}/{bgt['cell_index']} overlap: "
                            f"{a_set & b_set}")
        if not a_set:
            failures.append("XCELL: A's cell engine census shows no built entities "
                            "even though markers were placed — vacuous disjointness")
        con2.close()
        hb(f"XCELL done: A rows={len(a_rows)}/{len(placed)}, "
           f"B marker rows={len(b_marker_rows)}")

        # marker cleanup + verify (mutating-probe protocol: re-snapshot after)
        hb("PHASE 5 cleanup: destroying markers + re-snapshot + fresh DB check")
        cleanup = lua_strict(rcon, f"""
            local s = game.surfaces[1]
            local removed = 0
            for _, e in pairs(s.find_entities_filtered{{
                    area={bounds_lua(a["bounds"])}}}) do
                if e.valid and e.type ~= 'resource' and e.type ~= 'character'
                   and e.type ~= 'item-on-ground' then
                    e.destroy{{raise_destroy=true}}
                    removed = removed + 1
                end
            end
            return {{removed=removed}}
        """)
        results["phases"]["marker_cleanup"] = cleanup
        cleanup_tick = lua_strict(rcon, "return game.tick")
        lua_strict(rcon, "return remote.call('map','re_snapshot_area',"
                         f"{bounds_lua(a['bounds'])},50)")
        wait_fresh(rcon, "marker cleanup snapshot", failures,
                   want={ch: int(cleanup_tick)
                         for ch in cell_chunks(a["bounds"])})
        con3, _ = fresh_db(ART / "session_postcleanup.duckdb")
        leftover = db_cell_rows(con3, a["bounds"])["entities"]
        con3.close()
        leftover_markers = [e for e in leftover if e["name"] in marker_names]
        if leftover_markers:
            failures.append(f"CLEANUP: destroyed markers still in fresh DB: "
                            f"{leftover_markers} (SNAP-3/CELL-2 class)")
        markers_placed = []  # cleaned

        # ---- Invariant 6: release / reuse -------------------------------------
        hb(f"PHASE 6: destroy+unassign agent {a['agent_id']}, then create agent C")
        destroy = lua_strict(
            rcon, "return remote.call('agent','destroy_agents',"
                  f"{{{a['agent_id']}}})")
        results["phases"]["destroy_A"] = destroy
        destroyed_ids = [int(x) for x in as_list(destroy.get("destroyed"))]
        if a["agent_id"] not in destroyed_ids:
            failures.append(f"RELEASE: destroy_agents({{{a['agent_id']}}}) returned "
                            f"destroyed={destroyed_ids} — silent no-op class (OQ6)")
        mid_storage = get_storage(rcon)
        results["phases"]["storage_after_destroy_only"] = {
            "agent_cells": mid_storage["agent_cells"]}
        lua_strict(rcon, "return remote.call('lab_grid','unassign_agent',"
                         f"{a['agent_id']})")
        post_storage = get_storage(rcon)
        if a["agent_id"] in post_storage["agent_cells"]:
            failures.append(f"RELEASE: agent {a['agent_id']} still in agent_cells "
                            "after destroy+unassign")
        if post_storage["cell_agents"].get(a["cell_index"]) is not None:
            failures.append(f"RELEASE: cell {a['cell_index']} still bound to "
                            f"{post_storage['cell_agents'].get(a['cell_index'])} "
                            "after destroy+unassign")
        assert_bijection(post_storage, "after-release", failures)
        chars_a = cell_engine_census(rcon, a["bounds"])["characters"]
        if chars_a:
            failures.append(f"RELEASE: characters remain in cell "
                            f"{a['cell_index']} after destroy: {chars_a}")

        rC = lua_strict(rcon, """
            local res = remote.call('lab_grid','create_agent_in_cell')
            return {create=res, tick=game.tick}
        """)
        createC = rC.get("create") or {}
        if not createC.get("success"):
            failures.append(f"REUSE: create agent C failed: {createC}")
        else:
            cid = int(createC["agent_id"])
            cci = int(createC["cell_index"])
            cb = lua_strict(rcon, "return remote.call('lab_grid',"
                                  f"'get_cell_bounds',{cci})")
            created.append({"agent_id": cid, "cell_index": cci,
                            "force_name": createC.get("force_name"),
                            "bounds": cb, "tick_before": rC["tick"],
                            "tick_after": rC["tick"], "is_C": True})
            reused = (cci == a["cell_index"])
            results["phases"]["reuse"] = {"agent_C": cid, "cell": cci,
                                          "reused_As_cell": reused}
            hb(f"agent C={cid} -> cell {cci} (reused A's cell: {reused})")
            final_storage = get_storage(rcon)
            assert_bijection(final_storage, "after-reuse", failures)
            if final_storage["agent_cells"].get(cid) != cci:
                failures.append(f"REUSE: storage binding for C ({cid}) is "
                                f"{final_storage['agent_cells'].get(cid)!r}, "
                                f"expected {cci}")
            chars_c = cell_engine_census(rcon, cb)["characters"]
            if len(chars_c) != 1:
                failures.append(f"REUSE: expected 1 character in C's cell {cci}, "
                                f"engine sees {len(chars_c)}")
            elif chars_c[0]["force"] != createC.get("force_name"):
                failures.append(f"REUSE: C's character force {chars_c[0]['force']!r} "
                                f"!= create result {createC.get('force_name')!r}")

        # ---- counters / verdict ------------------------------------------------
        counters = {
            "agents_created": len(created),
            "cells_touched": sorted({c["cell_index"] for c in created}),
            "spot_checks": spot_checks_total,
            "markers_placed": len(placed),
            "db_loads": 3,
            "failures": len(failures),
        }
        results["counters"] = counters
        vacuous = (spot_checks_total < MIN_SPOT_CHECKS * 2
                   or len(created) < MIN_AGENTS)
        if vacuous:
            finding("comparison volume below floors — refusing PASS")
        status = ("VACUOUS-RISK" if vacuous and not failures
                  else ("FAIL" if failures else "PASS"))
        tick = lua_strict(rcon, "return {tick=game.tick}")["tick"]
        results["verdict"] = {"check": CHECK_ID, "status": status,
                              "commit": commit, "tick": tick,
                              "failures": failures}
        return {"status": status, "failures": failures, "counters": counters,
                "commit": commit, "tick": tick}

    except SystemExit as e:
        return {"status": "BLOCKED", "blocked_reason": str(e),
                "failures": failures, "counters": {}}
    except Exception as e:  # noqa: BLE001
        import traceback
        results["error"] = {"type": type(e).__name__, "msg": str(e),
                            "traceback": traceback.format_exc()}
        hb(f"ERROR: {type(e).__name__}: {e}")
        failures.append(f"CRASH: {type(e).__name__}: {e}")
        return {"status": "FAIL", "failures": failures, "counters": {}}

    finally:
        # ---- Invariant 7: cleanup, verified ---------------------------------
        try:
            hb("PHASE 7: final cleanup (agents + any leftover markers)")
            our_ids = sorted({c["agent_id"] for c in created})
            if our_ids:
                ids_lua = ",".join(str(i) for i in our_ids)
                final_destroy = lua(rcon, "return remote.call('agent',"
                                          f"'destroy_agents',{{{ids_lua}}})")
                results["phases"]["final_destroy"] = final_destroy
                for aid in our_ids:
                    lua(rcon, f"return remote.call('lab_grid','unassign_agent',{aid})")
            if markers_placed and marker_cell_bounds:
                lua(rcon, f"""
                    local s = game.surfaces[1]
                    for _, e in pairs(s.find_entities_filtered{{
                            area={bounds_lua(marker_cell_bounds)}}}) do
                        if e.valid and e.type ~= 'resource'
                           and e.type ~= 'character' then e.destroy() end
                    end
                    return {{ok=true}}
                """)
            # verification: storage has none of our ids; no characters left
            end_storage = get_storage(rcon)
            stale_ids = [aid for aid in our_ids
                         if aid in end_storage["agent_cells"]]
            leftover_chars = []
            for c in created:
                leftover_chars += cell_engine_census(rcon, c["bounds"])["characters"]
            results["cleanup_verified"] = {
                "our_agent_ids": our_ids,
                "stale_storage_ids": stale_ids,
                "leftover_characters": leftover_chars,
                "clean": not stale_ids and not leftover_chars,
            }
            hb(f"cleanup verified: clean={not stale_ids and not leftover_chars} "
               f"(stale_ids={stale_ids}, leftover_chars={len(leftover_chars)})")
            if stale_ids or leftover_chars:
                finding(f"CLEANUP NOT CLEAN: stale storage ids {stale_ids}, "
                        f"{len(leftover_chars)} characters left — next check "
                        "inherits this junk (playbook §5)")
        except Exception as ce:  # noqa: BLE001
            finding(f"cleanup crashed: {type(ce).__name__}: {ce}")
        save("results.json", results)
        hb("=== check_cell_coherence end ===")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="L0.4 — agent+cell instance coherence: allocation bijection, "
                    "body placement, force isolation, vision scope (CELL-1), "
                    "boot-scoped DB (CELL-2), cross-cell disjointness, "
                    "release/reuse. See module docstring.")
    ap.add_argument("--instance", default="server_0",
                    help="client or server_N (default server_0)")
    ap.add_argument("--agents", type=int, default=2,
                    help="number of agents to allocate (>= 2; default 2; cells "
                         "are chosen by the scenario's own allocation, never "
                         "hardcoded)")
    ap.add_argument("--path", choices=["scenario", "orchestrator"],
                    default="scenario",
                    help="allocation path under test: scenario = "
                         "lab_grid.create_agent_in_cell over RCON; orchestrator "
                         "= the REAL Environment stack driving "
                         "Orchestrator._allocate_cell/_release_cell cycles "
                         "(run_task's exact calls; --agents = cycle count)")
    ap.add_argument("--artifacts-dir", default=None, help="override evidence dir")
    args = ap.parse_args()

    if args.agents < MIN_AGENTS:
        ap.error(f"--agents must be >= {MIN_AGENTS} (anti-vacuity floor)")

    verdict = run_check(instance=args.instance, agents=args.agents,
                        path=args.path, artifacts_dir=args.artifacts_dir)
    print("\n========== SUMMARY ==========")
    print(json.dumps(verdict, indent=2, default=str))
    return {"PASS": 0, "FAIL": 1, "BLOCKED": 2, "VACUOUS-RISK": 3}[verdict["status"]]


if __name__ == "__main__":
    sys.exit(main())
