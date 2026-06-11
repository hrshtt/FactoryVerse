#!/usr/bin/env python
"""Certification check L2.5 — ghost reads agree across every layer.

Ledger row (FLOOR_CERTIFICATION.md L2.5):
    Claim:      Ghost reads — place ghosts; read via both views
    Pass:       Ghost table + reachable ghosts agree

Why the old harness was decertified (audit 2026-06-10): tests/sync/
test_ghost_snapshot.py was 11/11 ERROR at setup (undefined fixtures), and even
its dead body wrapped core verifications in `if updates_file.exists():` — the
canonical vacuous pattern. L2.5 has never had executable coverage. This
harness places ghosts through the real AGENT ghost path and demands an
EMPTY DIFF across three independently-constructed ghost reads.

Ghost path under test (read before drafting):
    - agent place_entity(..., ghost=true): placement.lua:291 swaps
      name='entity-ghost', inner_name=<entity>, raise_built=true (no reach
      check for ghosts — placement.lua:59), so fv_snapshot's event path sees it
      (Entities.lua write_entity_snapshot is_ghost branch -> ghosts-updates.jsonl)
      and chunk re-snapshots gather ghosts into ghosts-init.jsonl (Map.lua).
    - Python-side GhostBuilderAction (game/agent/ghost_builder.py) drives the
      same remote place_entity(ghost=True) call; this harness calls the remote
      directly so it runs without the Tier-4 runtime.

Layers compared (set of (ghost_name, x, y) + direction as secondary field):
    L1 raw RCON census   — find_entities_filtered{area, type='entity-ghost'}
                           (engine ground truth, no fv code)
    L2 reachable read    — remote.call('agent_<id>','get_reachable', true)
                           .ghosts (agent teleported to rig center first)
    L3 snapshot DB       — map.re_snapshot_area over the rig chunks, then a
                           FRESH SnapshotDatabase + SnapshotLoader.load_all()
                           (game/infra/duckdb — Stack A; Stack B is deleted),
                           SELECT from the `ghost` table.

Pass criteria (ALL required):
    1. Non-emptiness guard: >= 3 ghosts of >= 2 distinct ghost_name types
       successfully placed (we place 5 of 4 types); fewer = BLOCKED, never PASS.
    2. placed set == L1 == (L2 restricted to rig box) == L3, empty diff in
       BOTH directions for each pair.
    3. Direction agreement per ghost across L1/L2/L3 (counted comparisons).
    4. Cleanup VERIFIED: after agent remove_ghost on every placed ghost,
       L1 census in the box == 0 (hard assert) AND a second re-snapshot +
       fresh DB load shows 0 ghost rows in the box (hard assert). A cleanup
       that isn't verified is a vacuous cleanup.

Audit-gate answers AS DESIGNED (executing runner re-validates):
    Q1 vacuous pass?     Non-emptiness guard (>=3 ghosts, >=2 types) is a hard
                         gate; zero `if exists:` wrappers — a missing snapshot
                         file/row is a FAIL, not a skip; diff counts asserted
                         both directions.
    Q2 real layer?       Live game, real agent remote interface, real snapshot
                         files, real Stack-A loader into a real DuckDB file.
    Q3 independent truth? L1 is a raw engine scan sharing no code with the
                         snapshot mod or the loader; the placed-set expectation
                         is hand-constructed in this script.
    Q4 covers the row?   "Ghost table + reachable ghosts agree" — both views
                         read, plus the raw census the row implies. NOT
                         covered: ghost building (ghost->real entity), ghost
                         rotation sync, RemoteView SQL wrapper objects.

SCOPE / OPEN-QUESTIONS (offline draft cannot settle; runner must confirm):
    - OQ1: whether ghost placement DIRECTION survives each layer for 1x1
      entities (engine may normalize); direction mismatches are recorded as
      failures — if the engine normalizes legitimately, runner downgrades
      those rows with evidence and notes it in the verdict.
    - OQ2: whether event-driven ghosts-updates.jsonl alone would have been
      sufficient (no re-snapshot). This harness intentionally re-snapshots
      (the certified delivery path; force_resnapshot is a known no-op) and
      only RECORDS whether ghosts-updates.jsonl contained the upserts.
    - OQ3: get_reachable reach radius is assumed to cover a ±5-tile rig from
      its center; if reachable misses ghosts the raw census sees AT this
      range, that is a real disagreement and a legitimate FAIL — runner
      should confirm radius semantics before downgrading.
    - OQ4: snapshot queue drain timeout (90 s) assumes an otherwise-idle
      instance (playbook §5: one writer per area).

Exit codes: 0 = PASS, 1 = FAIL, 2 = BLOCKED, 3 = VACUOUS-RISK.

Usage:
    uv run python scripts/certification/check_L2_5.py --instance client --cell 4
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from factorio_rcon import RCONClient  # noqa: E402

from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase  # noqa: E402
from FactoryVerse.game.infra.duckdb.loader import SnapshotLoader  # noqa: E402

# ----------------------------------------------------------------------------
# Constants / instance plumbing
# ----------------------------------------------------------------------------
DATE = datetime.date.today().isoformat()
CHECK_ID = "L2.5"

RCON_HOST, RCON_PORT, RCON_PASS = "localhost", 27100, "factorio"
SNAP_ROOT = Path.home() / "Library/Application Support/factorio/script-output"

POS_TOL = 0.01
MIN_GHOSTS, MIN_TYPES = 3, 2
DRAIN_TIMEOUT_S = 90.0

results: Dict[str, Any] = {"findings": [], "phases": {}}
ART: Path = REPO / ".fv-output" / "certification" / DATE / CHECK_ID
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
    with open(PROGRESS, "a") as f:
        f.write(line + "\n")
    print(f"[hb] {line}", flush=True)


def finding(msg: str) -> None:
    results["findings"].append(msg)
    print(f"[FINDING] {msg}", flush=True)


def save(name: str, data: Any) -> None:
    (ART / name).write_text(json.dumps(data, indent=2, default=str))


# ----------------------------------------------------------------------------
# RCON helpers (RUNTIME_PLAYBOOK §2)
# ----------------------------------------------------------------------------
def lua(rcon: RCONClient, body: str) -> Any:
    # HARNESS-FIX 2026-06-11 (first run, same as check_L2_4): non-table returns
    # (teleport -> boolean) raised in table_to_json OUTSIDE the xpcall -> empty
    # RCON response on the docker server. Serialize an envelope table instead.
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


def lua_strict(rcon: RCONClient, body: str) -> Any:
    res = lua(rcon, body)
    if isinstance(res, dict) and "__lua_error" in res:
        raise RuntimeError(f"Lua error: {res['__lua_error'][:800]}")
    return res


def pos_lua(p: Dict[str, float]) -> str:
    return f"{{x={p['x']},y={p['y']}}}"


def as_list(v: Any) -> List[Any]:
    """helpers.table_to_json renders empty arrays as {} and sparse arrays as
    dicts; normalize to a Python list."""
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        return list(v.values())
    return []


# ----------------------------------------------------------------------------
# Phases
# ----------------------------------------------------------------------------
def smoke(rcon: RCONClient) -> None:
    rcon.send_command("/c rcon.print('ping')")
    assert "ping" in rcon.send_command("/c rcon.print('ping')"), "smoke ping failed"
    ifaces = json.loads(
        rcon.send_command("/c rcon.print(helpers.table_to_json(remote.interfaces))")
    )
    missing = [i for i in ("lab_grid", "agent", "map", "snapshot") if i not in ifaces]
    if missing:
        raise SystemExit(f"BLOCKED: missing remote interfaces {missing}")
    hb(f"smoke ok ({len(ifaces)} interfaces)")


def ensure_cell_agent(rcon: RCONClient, cell: int) -> Dict[str, Any]:
    st = lua_strict(rcon, f"return remote.call('lab_grid','get_cell_status',{cell})")
    if st.get("has_agent"):
        storage = lua_strict(rcon, "return remote.call('lab_grid','get_storage')")
        agent_id = None
        ac = storage.get("agent_cells") or {}
        # HARNESS-FIX 2026-06-11 (same as check_L2_4): consecutive-int-keyed
        # Lua tables serialize as JSON arrays; list index i -> agent_id i+1.
        if isinstance(ac, list):
            ac = {i + 1: v for i, v in enumerate(ac) if v is not None}
        for aid, ci in ac.items():
            if int(ci) == cell:
                agent_id = int(aid)
                break
        if agent_id is None:
            raise SystemExit(f"BLOCKED: cell {cell} occupied but unbound; pick another --cell")
        return {"agent_id": agent_id, "iface": f"agent_{agent_id}",
                "force_name": f"cell_{cell}", "created_by_us": False}
    create = lua_strict(
        rcon, f"return remote.call('lab_grid','create_agent_in_cell',{{cell_index={cell}}})"
    )
    if not create.get("success"):
        raise SystemExit(f"BLOCKED: create_agent_in_cell failed: {create}")
    return {"agent_id": create["agent_id"], "iface": f"agent_{create['agent_id']}",
            "force_name": create.get("force_name") or f"cell_{cell}",
            "created_by_us": True}


def ghost_census(rcon: RCONClient, box_lua: str) -> List[Dict[str, Any]]:
    """L1: raw engine scan — independent of all fv code."""
    res = lua_strict(rcon, f"""
        local out = {{}}
        for _, g in pairs(game.surfaces[1].find_entities_filtered{{
                area={box_lua}, type='entity-ghost'}}) do
            table.insert(out, {{ghost_name=g.ghost_name,
                                x=g.position.x, y=g.position.y,
                                direction=g.direction, force=g.force.name}})
        end
        return {{ghosts=out, tick=game.tick}}
    """)
    return as_list(res.get("ghosts"))


def wait_queue_drain(rcon: RCONClient, label: str) -> List[Dict[str, Any]]:
    # HARNESS-FIX 2026-06-11 (first run): `pending_chunks` counts EVERY
    # never-snapshotted chunk in the tracker (29 exist map-wide on lab-grid),
    # so `pending == 0` is unreachable and the loop always burned the full
    # timeout. New drain criterion: phase IDLE with pending stable across 5
    # consecutive polls = our queued chunks have been worked off.
    timeline = []
    deadline = time.time() + DRAIN_TIMEOUT_S
    while time.time() < deadline:
        st = lua(rcon, "return remote.call('map','get_snapshot_status')")
        entry = {"t": round(time.time(), 1), "phase": st.get("phase"),
                 "pending": st.get("pending_chunks")}
        timeline.append(entry)
        tail = timeline[-5:]
        if (len(tail) == 5
                and all(e["phase"] == "IDLE" for e in tail)
                and len({e["pending"] for e in tail}) == 1):
            break
        time.sleep(1.0)
    hb(f"queue drain ({label}): {len(timeline)} polls, last={timeline[-1]}")
    return timeline


def load_fresh_db(db_path: Path, box: Dict) -> Tuple[List[Tuple], Dict[str, Any]]:
    """L3: fresh Stack-A DB; returns ghost rows in box + load stats."""
    if db_path.exists():
        db_path.unlink()
    db = SnapshotDatabase(db_path=str(db_path))
    db.ensure_schema()
    con = db.connection
    load = SnapshotLoader(db=con, snapshot_dir=SNAP_ROOT).load_all()
    rows = con.execute(
        "SELECT ghost_name, position_x, position_y, direction FROM ghost "
        "WHERE position_x >= ? AND position_x < ? AND position_y >= ? AND position_y < ?",
        [box["left_top"]["x"], box["right_bottom"]["x"],
         box["left_top"]["y"], box["right_bottom"]["y"]],
    ).fetchall()
    stats = {"ghost_count_total": load.ghost_count, "rows_in_box": len(rows)}
    return rows, stats


def key_set(items: List[Dict[str, Any]]) -> Set[Tuple[str, float, float]]:
    return {(it["ghost_name"], round(float(it["x"]), 2), round(float(it["y"]), 2))
            for it in items}


def diff(label: str, a: Set, b: Set, failures: List[str]) -> Dict[str, Any]:
    only_a, only_b = sorted(a - b), sorted(b - a)
    row = {"pair": label, "only_in_first": only_a, "only_in_second": only_b,
           "agree": not only_a and not only_b}
    if only_a or only_b:
        failures.append(f"DIFF {label}: only_first={only_a} only_second={only_b}")
    return row


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main() -> int:
    global ART, PROGRESS
    ap = argparse.ArgumentParser(
        description="L2.5 — ghost reads: raw census vs reachable vs snapshot DB, empty diff"
    )
    ap.add_argument("--instance", default="client", help="client or server_N")
    ap.add_argument("--cell", type=int, default=4, help="lab-grid cell index to use")
    ap.add_argument("--artifacts-dir", default=None, help="override evidence dir")
    args = ap.parse_args()
    configure_instance(args.instance)

    if args.artifacts_dir:
        ART = Path(args.artifacts_dir)
    elif args.instance != "client":
        ART = ART / args.instance
    ART.mkdir(parents=True, exist_ok=True)
    PROGRESS = ART / "progress.log"

    commit = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()
    hb(f"=== check_L2_5 start (instance={args.instance}, cell={args.cell}, commit={commit}) ===")

    try:
        rcon = RCONClient(RCON_HOST, RCON_PORT, RCON_PASS)
    except Exception as e:  # noqa: BLE001
        print(f"BLOCKED: cannot connect RCON: {e}")
        return 2
    smoke(rcon)

    b = lua_strict(rcon, f"return remote.call('lab_grid','get_cell_bounds',{args.cell})")
    lt = b["left_top"]
    cx, cy = lt["x"] + 24.0, lt["y"] + 24.0  # rig center, well inside play area
    box = {"left_top": {"x": cx - 8, "y": cy - 8},
           "right_bottom": {"x": cx + 8, "y": cy + 8}}
    box_lua = (
        f"{{left_top={{x={box['left_top']['x']},y={box['left_top']['y']}}},"
        f"right_bottom={{x={box['right_bottom']['x']},y={box['right_bottom']['y']}}}}}"
    )

    # Ghost rig: 5 ghosts, 4 types, all within ~5 tiles of the agent stand point.
    EAST, WEST = 4, 12
    GHOSTS = [
        {"name": "transport-belt", "pos": {"x": cx + 0.5, "y": cy - 3.5}, "dir": EAST},
        {"name": "transport-belt", "pos": {"x": cx + 1.5, "y": cy - 3.5}, "dir": EAST},
        {"name": "stone-furnace", "pos": {"x": cx + 4.0, "y": cy + 1.0}, "dir": None},
        {"name": "iron-chest", "pos": {"x": cx - 3.5, "y": cy + 0.5}, "dir": None},
        {"name": "burner-inserter", "pos": {"x": cx + 0.5, "y": cy + 3.5}, "dir": WEST},
    ]

    agent = ensure_cell_agent(rcon, args.cell)
    iface = agent["iface"]
    results["phases"]["agent"] = agent

    try:
        # --- 0. clear rig box of entities AND ghosts (idempotence) -----------
        cleared = lua_strict(rcon, f"""
            local n = 0
            for _, e in pairs(game.surfaces[1].find_entities_filtered{{area={box_lua}}}) do
                if e.valid and e.type ~= 'resource' and e.type ~= 'character' then
                    e.destroy{{raise_destroy=true}}; n = n + 1
                end
            end
            return {{cleared=n}}
        """)
        hb(f"rig box cleared: {cleared.get('cleared')} entities/ghosts removed")
        pre = ghost_census(rcon, box_lua)
        if pre:
            raise SystemExit(f"BLOCKED: box still has {len(pre)} ghosts after clear: {pre}")

        # --- 1. teleport agent, place ghosts via the AGENT ghost path ---------
        lua_strict(rcon, f"return remote.call('{iface}','teleport',"
                         f"{{position={pos_lua({'x': cx, 'y': cy})}}})")
        hb(f"placing {len(GHOSTS)} ghosts via agent place_entity(ghost=true)")
        placements = []
        for g in GHOSTS:
            # HARNESS-FIX 2026-06-11 (first run): omitting `direction` from the
            # named-table call made the DEPLOYED mod shift ghost=true into the
            # direction slot ("Invalid direction true") — the playbook §3
            # sparse-named-table trap is live for place_entity. Keep the table
            # dense: explicit direction=0 (defines.direction.north, the
            # engine default) for direction-less ghosts.
            dir_part = f", direction={g['dir'] if g['dir'] is not None else 0}"
            res = lua(rcon, f"""
                return remote.call('{iface}','place_entity',
                    {{entity_name='{g['name']}', position={pos_lua(g['pos'])}{dir_part},
                      ghost=true}})
            """)
            placements.append({"spec": g, "result": res})
        results["phases"]["placements"] = placements
        placed = [p["spec"] for p in placements
                  if isinstance(p["result"], dict) and p["result"].get("success")]
        placed_types = {g["name"] for g in placed}
        hb(f"placed {len(placed)} ghosts of {len(placed_types)} types")
        # Non-emptiness guard (audit Q1): too few ghosts cannot certify the row.
        if len(placed) < MIN_GHOSTS or len(placed_types) < MIN_TYPES:
            save("results.json", results)
            print(f"BLOCKED: only {len(placed)} ghosts / {len(placed_types)} types placed "
                  f"(need >= {MIN_GHOSTS} of >= {MIN_TYPES}): "
                  f"{[p['result'] for p in placements]}")
            return 2
        placed_set = {(g["name"], round(g["pos"]["x"], 2), round(g["pos"]["y"], 2))
                      for g in placed}

        # --- 2. L1 raw census ---------------------------------------------------
        l1 = ghost_census(rcon, box_lua)
        results["phases"]["l1_census"] = l1
        hb(f"L1 raw census: {len(l1)} ghosts")

        # --- 3. L2 reachable ghosts ----------------------------------------------
        reach = lua_strict(rcon, f"return remote.call('{iface}','get_reachable', true)")
        all_reach_ghosts = [
            {"ghost_name": g.get("ghost_name"), "x": g["position"]["x"],
             "y": g["position"]["y"], "direction": g.get("direction")}
            for g in as_list(reach.get("ghosts"))
        ]
        l2 = [g for g in all_reach_ghosts
              if box["left_top"]["x"] <= g["x"] < box["right_bottom"]["x"]
              and box["left_top"]["y"] <= g["y"] < box["right_bottom"]["y"]]
        results["phases"]["l2_reachable"] = {"in_box": l2, "total": len(all_reach_ghosts)}
        hb(f"L2 reachable: {len(l2)} ghosts in box ({len(all_reach_ghosts)} total)")

        # --- 4. L3 snapshot -> fresh DB -------------------------------------------
        hb("re-snapshotting rig chunks (map.re_snapshot_area; force_resnapshot is a known no-op)")
        snap = lua_strict(rcon, f"return remote.call('map','re_snapshot_area',{box_lua},50)")
        results["phases"]["re_snapshot"] = snap
        results["phases"]["drain"] = wait_queue_drain(rcon, "ghost snapshot")
        rows, stats = load_fresh_db(ART / "ghosts_check.duckdb", box)
        l3 = [{"ghost_name": r[0], "x": r[1], "y": r[2], "direction": r[3]} for r in rows]
        results["phases"]["l3_db"] = {"rows": l3, "stats": stats}
        hb(f"L3 DB: {stats['rows_in_box']} ghost rows in box "
           f"({stats['ghost_count_total']} loaded total)")

        # OQ2 evidence only (no conditional assertion): did event-driven
        # updates carry the upserts before the re-snapshot?
        upd_files = sorted((SNAP_ROOT / "factoryverse" / "snapshots").rglob("ghosts-*.jsonl")) \
            if (SNAP_ROOT / "factoryverse" / "snapshots").is_dir() else []
        results["phases"]["ghost_files_seen"] = [str(p) for p in upd_files]

        # --- 5. empty-diff comparison ----------------------------------------------
        failures: List[str] = []
        s1, s2, s3 = key_set(l1), key_set(l2), key_set(l3)
        comparison = [
            diff("placed vs L1_census", placed_set, s1, failures),
            diff("L1_census vs L2_reachable(box)", s1, s2, failures),
            diff("L1_census vs L3_db", s1, s3, failures),
            diff("placed vs L3_db", placed_set, s3, failures),
        ]
        # direction agreement (secondary field, counted)
        dir_rows = []
        l1_by_key = {k: g for g, k in ((g, (g["ghost_name"], round(float(g["x"]), 2),
                                            round(float(g["y"]), 2))) for g in l1)}
        # HARNESS-FIX 2026-06-11 (first run): the DB `ghost.direction` column is
        # VARCHAR (schema_definitions.py:209) while engine/reachable return the
        # numeric defines.direction — coerce to int for comparison; raw values
        # are still recorded in dir_rows so a real value drift stays visible.
        def _dir_norm(v: Any) -> Any:
            try:
                return int(float(v))
            except (TypeError, ValueError):
                return v

        for layer_name, layer in (("L2", l2), ("L3", l3)):
            for g in layer:
                k = (g["ghost_name"], round(float(g["x"]), 2), round(float(g["y"]), 2))
                ref = l1_by_key.get(k)
                if ref is None:
                    continue  # already counted as a set diff above
                agree = (_dir_norm(g.get("direction")) == _dir_norm(ref.get("direction")))
                dir_rows.append({"layer": layer_name, "ghost": k,
                                 "l1_dir": ref.get("direction"),
                                 "dir": g.get("direction"), "agree": agree})
                if not agree:
                    failures.append(f"DIR {layer_name} {k}: {g.get('direction')} "
                                    f"vs L1 {ref.get('direction')} (see OQ1)")
        results["comparison"] = {"sets": comparison, "directions": dir_rows}
        fields_compared = len(comparison) * 2 + len(dir_rows)
        results["counters"] = {"fields_compared": fields_compared,
                               "ghosts_placed": len(placed),
                               "types_placed": len(placed_types),
                               "disagreements": len(failures)}
        hb(f"COMPARE: {len(comparison)} set-diffs + {len(dir_rows)} direction checks, "
           f"{len(failures)} failures")

        # --- 6. cleanup that verifies itself ----------------------------------------
        hb("cleanup: agent remove_ghost on every placed ghost")
        removals = []
        for g in placed:
            removals.append(lua(rcon, f"""
                return remote.call('{iface}','remove_ghost',
                    {{entity_name='{g['name']}', position={pos_lua(g['pos'])}}})
            """))
        results["phases"]["removals"] = removals
        post_census = ghost_census(rcon, box_lua)
        cleanup_census_ok = len(post_census) == 0
        if not cleanup_census_ok:
            failures.append(f"CLEANUP raw census still has {len(post_census)} ghosts: {post_census}")

        hb("cleanup verification 2: re-snapshot + fresh DB must show 0 ghost rows")
        lua_strict(rcon, f"return remote.call('map','re_snapshot_area',{box_lua},50)")
        wait_queue_drain(rcon, "post-cleanup snapshot")
        rows2, stats2 = load_fresh_db(ART / "ghosts_after_cleanup.duckdb", box)
        cleanup_db_ok = len(rows2) == 0
        if not cleanup_db_ok:
            failures.append(f"CLEANUP DB still has {len(rows2)} ghost rows in box: {rows2}")
        results["cleanup"] = {"census_empty": cleanup_census_ok,
                              "db_empty": cleanup_db_ok, "db_stats": stats2}
        hb(f"cleanup verified: census_empty={cleanup_census_ok} db_empty={cleanup_db_ok}")

        # --- 7. verdict -----------------------------------------------------------------
        tick = lua_strict(rcon, "return {tick=game.tick}")["tick"]
        # Vacuity floor: every layer must have actually produced ghosts pre-cleanup.
        vacuous = (len(l1) == 0 or len(l2) == 0 or len(l3) == 0)
        if vacuous:
            finding("one or more layers returned ZERO ghosts while placement claimed "
                    "success — comparisons would be empty-vs-empty")
        status = ("VACUOUS-RISK" if vacuous and not failures
                  else ("FAIL" if failures else "PASS"))
        results["verdict"] = {"check": CHECK_ID, "status": status, "commit": commit,
                              "tick": tick, "failures": failures}
        save("results.json", results)
        print("\n========== SUMMARY ==========")
        print(json.dumps({"status": status, "counters": results.get("counters"),
                          "failures": failures, "findings": results["findings"]},
                         indent=2, default=str))
        return {"PASS": 0, "FAIL": 1, "VACUOUS-RISK": 3}[status]

    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        import traceback
        results["error"] = {"type": type(e).__name__, "msg": str(e),
                            "traceback": traceback.format_exc()}
        save("results.json", results)
        hb(f"ERROR: {type(e).__name__}: {e}")
        print(f"FAIL (crash): {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
