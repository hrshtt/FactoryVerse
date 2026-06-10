#!/usr/bin/env python3
"""Certification check L1.10 / SNAP-1 — lab-grid session pipeline coherence.

Claim under test (ledger L1.10): in a real lab-grid session, water_tile /
resource_tile / map_entity in the session DuckDB are non-empty where the
surface is non-empty, and the snapshot tick advances.
Field failure 2026-06-10: water_tile always 0 rows, map_entity always [],
snapshot tick frozen at 660.

Pipeline layers checked, in order (so a failure attributes to ONE layer):
  gather  -> mod find/count in chunk        (ground truth vs files)
  enqueue -> map.snapshot_area / state machine skip-guard (H1 probe)
  write   -> JSONL files under <script-output>/factoryverse/snapshots
  load    -> SnapshotLoader -> fresh DuckDB (water_tile/resource_tile/map_entity)
  tick    -> chunk_lookup snapshot_tick freshness (in-game) + on-disk metadata

Run:  uv run python scripts/certification/check_L1_10.py --instance server_0 --cell 2
"""

from __future__ import annotations

import datetime
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from factorio_rcon import RCONClient  # noqa: E402

from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase  # noqa: E402
from FactoryVerse.game.infra.duckdb.loader import SnapshotLoader  # noqa: E402

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------
DATE = "2026-06-11"
ART = REPO / ".fv-output" / "certification" / DATE / "L1.10"
ART.mkdir(parents=True, exist_ok=True)
PROGRESS = ART / "progress.log"

RCON_HOST, RCON_PORT, RCON_PASS = "localhost", 27100, "factorio"
SNAP_ROOT = Path.home() / "Library/Application Support/factorio/script-output"

WATER_TILE_NAMES = ["water", "deepwater", "water-green", "deepwater-green"]

results: dict = {"findings": [], "phases": {}}


def configure_instance(name: str) -> None:
    global RCON_PORT, SNAP_ROOT
    if name == "client":
        return
    if name.startswith("server_"):
        n = int(name.split("_")[1])
        RCON_PORT = 27000 + n
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


# ----------------------------------------------------------------------------
# RCON helpers
# ----------------------------------------------------------------------------
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


def bounds_lua(b: dict) -> str:
    lt, rb = b["left_top"], b["right_bottom"]
    return (
        f"{{left_top={{x={lt['x']},y={lt['y']}}},"
        f"right_bottom={{x={rb['x']},y={rb['y']}}}}}"
    )


def snapshot_status(rcon) -> dict:
    return lua(rcon, "return remote.call('map','get_snapshot_status')")


def ground_truth(rcon, bounds: dict) -> dict:
    """Water tiles, resource entities (by kind), built entities in bounds."""
    res = lua(
        rcon,
        f"""
        local s = game.surfaces[1]
        local area = {bounds_lua(bounds)}
        local water = s.count_tiles_filtered{{area=area, name={{'water','deepwater','water-green','deepwater-green'}}}}
        local res_counts = {{}}
        local res_total = 0
        for _, e in pairs(s.find_entities_filtered{{area=area, type='resource'}}) do
            res_counts[e.name] = (res_counts[e.name] or 0) + 1
            res_total = res_total + 1
        end
        local built = {{}}
        for _, e in pairs(s.find_entities_filtered{{area=area}}) do
            if e.type ~= 'resource' and e.type ~= 'character' and e.type ~= 'entity-ghost'
               and e.type ~= 'item-on-ground' then
                table.insert(built, {{name=e.name, x=e.position.x, y=e.position.y, force=e.force.name}})
            end
        end
        return {{tick=game.tick, water=water, resource_total=res_total,
                 resource_counts=res_counts, built_n=#built, built=built}}
        """,
    )
    if "error" in res:
        raise RuntimeError(f"ground_truth failed: {res['error']}")
    if isinstance(res.get("built"), dict):
        res["built"] = list(res["built"].values())
    return res


def cell_chunks(bounds: dict) -> list:
    """Chunk coords overlapping cell bounds (mirrors Map.lua bounds_to_chunks)."""
    lt, rb = bounds["left_top"], bounds["right_bottom"]
    out = []
    for cy in range(int(lt["y"]) // 32, (int(rb["y"]) - 1) // 32 + 1):
        for cx in range(int(lt["x"]) // 32, (int(rb["x"]) - 1) // 32 + 1):
            out.append((cx, cy))
    return out


def snap_dir() -> Path:
    return SNAP_ROOT / "factoryverse" / "snapshots"


def file_inventory(chunks: list) -> dict:
    """mtime + line count of every snapshot file for the given chunks."""
    inv = {}
    for cx, cy in chunks:
        d = snap_dir() / str(cx) / str(cy)
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if f.is_file():
                inv[f"{cx}/{cy}/{f.name}"] = {
                    "mtime": f.stat().st_mtime,
                    "lines": sum(1 for line in f.open() if line.strip()),
                }
    return inv


def wait_queue_drain(rcon, timeout=90.0, label="") -> list:
    """Poll get_snapshot_status until pending==0 and phase IDLE; return timeline."""
    timeline = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = snapshot_status(rcon)
        entry = {
            "t": round(time.time(), 1),
            "phase": st.get("phase"),
            "system_phase": st.get("system_phase"),
            "pending": st.get("pending_chunks"),
            "completed": st.get("completed_chunks"),
        }
        timeline.append(entry)
        if entry["pending"] == 0 and entry["phase"] == "IDLE" and len(timeline) > 2:
            break
        time.sleep(1.0)
    hb(f"queue drain ({label}): {len(timeline)} polls, last={timeline[-1]}")
    return timeline


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", default="client", help="client or server_N")
    ap.add_argument("--cell", type=int, default=2, help="lab-grid cell index to use")
    args = ap.parse_args()
    configure_instance(args.instance)
    cell = args.cell

    hb(f"=== check_L1_10 start (instance={args.instance}, cell={cell}) ===")

    # --- 0. smoke ------------------------------------------------------------
    rcon = RCONClient(RCON_HOST, RCON_PORT, RCON_PASS)
    rcon.send_command("/c rcon.print('ping')")
    assert "ping" in rcon.send_command("/c rcon.print('ping')"), "smoke ping failed"
    ifaces = json.loads(
        rcon.send_command("/c rcon.print(helpers.table_to_json(remote.interfaces))")
    )
    needed = ["lab_grid", "map", "snapshot", "agent"]
    missing = [i for i in needed if i not in ifaces]
    if missing:
        hb(f"SMOKE FAIL: missing interfaces {missing}")
        print(f"BLOCKED: missing interfaces {missing}")
        return 2
    t1 = lua(rcon, "return {tick=game.tick}")["tick"]
    time.sleep(1.5)
    t2 = lua(rcon, "return {tick=game.tick}")["tick"]
    results["smoke"] = {"tick1": t1, "tick2": t2, "game_tick_advancing": t2 > t1}
    if t2 <= t1:
        finding("game.tick NOT advancing — server paused?")
    hb(f"smoke ok: tick {t1}->{t2}, interfaces present")

    # --- 1. ground truth (pre-session) ----------------------------------------
    b = lua(rcon, f"return remote.call('lab_grid','get_cell_bounds',{cell})")
    if "error" in b:
        raise RuntimeError(f"get_cell_bounds failed: {b}")
    chunks = cell_chunks(b)
    gt_pre = ground_truth(rcon, b)
    results["cell"] = {"index": cell, "bounds": b, "chunks": chunks}
    results["ground_truth_pre"] = gt_pre
    hb(f"ground truth cell {cell}: water={gt_pre['water']} resources={gt_pre['resource_total']} "
       f"built={gt_pre['built_n']} (tick {gt_pre['tick']})")
    if gt_pre["water"] == 0 and gt_pre["resource_total"] == 0:
        finding(f"cell {cell} surface is EMPTY — check would be vacuous; pick another cell")

    # surface-wide sanity (the 'where the surface is non-empty' clause)
    surf = lua(rcon, """
        local s = game.surfaces[1]
        return {water_all=s.count_tiles_filtered{name={'water','deepwater','water-green','deepwater-green'}},
                resources_all=s.count_entities_filtered{type='resource'}}
    """)
    results["surface_totals"] = surf

    # --- 2. real session path: create_agent_in_cell ---------------------------
    pre_status = snapshot_status(rcon)
    pre_files = file_inventory(chunks)
    results["pre_session"] = {"status": pre_status, "files": pre_files}
    cell_st = lua(rcon, f"return remote.call('lab_grid','get_cell_status',{cell})")
    hb(f"SESSION: cell {cell} has_agent={cell_st.get('has_agent')}; "
       f"pre completed_chunks={pre_status.get('completed_chunks')}")

    if cell_st.get("has_agent"):
        finding(f"cell {cell} already occupied — falling back to map.snapshot_area "
                "(same call create_agent_in_cell makes, control.lua:208)")
        create = lua(rcon, f"return remote.call('map','snapshot_area',{bounds_lua(b)},10)")
    else:
        create = lua(rcon, f"return remote.call('lab_grid','create_agent_in_cell',{{cell_index={cell}}})")
        if not create.get("success"):
            raise RuntimeError(f"create_agent_in_cell failed: {create}")
    results["phases"]["session_trigger"] = create
    hb(f"session triggered: {json.dumps(create)[:200]}")

    timeline1 = wait_queue_drain(rcon, label="session snapshot")
    results["phases"]["session_timeline"] = timeline1
    files_after_session = file_inventory(chunks)
    results["phases"]["files_after_session"] = files_after_session
    new_files = sorted(set(files_after_session) - set(pre_files))
    hb(f"files after session snapshot: {len(files_after_session)} total, new: {new_files}")

    # layer verdicts for resources/water (init path)
    water_lines = sum(v["lines"] for k, v in files_after_session.items() if "water-init" in k)
    res_lines = sum(v["lines"] for k, v in files_after_session.items() if "resources-init" in k)
    results["phases"]["written_counts"] = {"water_lines": water_lines, "resources_lines": res_lines}
    if gt_pre["water"] > 0 and water_lines == 0:
        finding(f"WRITE LAYER DROP: {gt_pre['water']} water tiles on surface, 0 water-init lines")
    if gt_pre["resource_total"] > 0 and res_lines == 0:
        finding(f"WRITE LAYER DROP: {gt_pre['resource_total']} resources on surface, 0 resources-init lines")

    # --- 3. mutation + H1 probe ------------------------------------------------
    lt = b["left_top"]
    markers = [
        ("iron-chest", lt["x"] + 5.5, lt["y"] + 5.5),
        ("stone-furnace", lt["x"] + 10.0, lt["y"] + 6.0),
        ("wooden-chest", lt["x"] + 40.5, lt["y"] + 40.5),
    ]
    force_name = create.get("force_name") or f"cell_{cell}"
    hb(f"H1 probe: placing {len(markers)} marker entities (force={force_name}, raise_built=true)")
    place = lua(rcon, f"""
        local s = game.surfaces[1]
        local placed = {{}}
        for _, spec in pairs({{
            {{name='{markers[0][0]}', x={markers[0][1]}, y={markers[0][2]}}},
            {{name='{markers[1][0]}', x={markers[1][1]}, y={markers[1][2]}}},
            {{name='{markers[2][0]}', x={markers[2][1]}, y={markers[2][2]}}},
        }}) do
            local e = s.create_entity{{name=spec.name, position={{x=spec.x, y=spec.y}},
                                       force='{force_name}', raise_built=true}}
            table.insert(placed, {{name=spec.name, ok=(e~=nil and e.valid)}})
        end
        return {{placed=placed}}
    """)
    results["phases"]["markers_placed"] = place
    if "error" in place:
        raise RuntimeError(f"marker placement failed: {place}")

    # 3a. plain snapshot_area on already-snapshotted chunks (the session-path call)
    time.sleep(10)  # give event-driven update files a chance to appear
    files_after_place = file_inventory(chunks)
    results["phases"]["files_after_place"] = files_after_place

    hb("H1 probe: calling PLAIN map.snapshot_area on the same (already-snapshotted) cell")
    snap2 = lua(rcon, f"return remote.call('map','snapshot_area',{bounds_lua(b)},10)")
    results["phases"]["snapshot_area_2nd"] = snap2
    timeline2 = wait_queue_drain(rcon, timeout=45, label="2nd snapshot_area")
    results["phases"]["snapshot_area_2nd_timeline"] = timeline2
    files_after_snap2 = file_inventory(chunks)
    results["phases"]["files_after_snap2"] = files_after_snap2

    def marker_in_files(inv: dict) -> bool:
        for key in inv:
            if "entities-init" in key or "entities-updates" in key:
                f = snap_dir() / key
                if f.exists() and "wooden-chest" in f.read_text():
                    return True
        return False

    marker_after_snap2 = marker_in_files(files_after_snap2)
    refreshed = {k for k, v in files_after_snap2.items()
                 if k in files_after_session and v["mtime"] > files_after_session[k]["mtime"]}
    results["phases"]["h1_probe"] = {
        "chunks_queued_2nd": snap2.get("chunks_queued"),
        "files_refreshed_by_2nd_snapshot_area": sorted(refreshed),
        "marker_visible_after_2nd_snapshot_area": marker_after_snap2,
    }
    if snap2.get("chunks_queued", 0) > 0 and not refreshed and not marker_after_snap2:
        finding("H1 CONFIRMED LIVE: 2nd plain snapshot_area queued chunks but state machine "
                "skipped all (Map.lua:1740 chunk_needs_snapshot guard) — zero files written, "
                "new entity invisible to snapshot")

    # 3b. re_snapshot_area (known-working path) — should pick up markers
    hb("H1 probe: calling map.re_snapshot_area (clears snapshot_tick) on same cell")
    resnap = lua(rcon, f"return remote.call('map','re_snapshot_area',{bounds_lua(b)},50)")
    results["phases"]["re_snapshot"] = resnap
    timeline3 = wait_queue_drain(rcon, timeout=60, label="re_snapshot_area")
    results["phases"]["re_snapshot_timeline"] = timeline3
    files_after_resnap = file_inventory(chunks)
    results["phases"]["files_after_resnap"] = files_after_resnap
    marker_after_resnap = marker_in_files(files_after_resnap)
    results["phases"]["h1_probe"]["marker_visible_after_re_snapshot_area"] = marker_after_resnap
    hb(f"H1 probe done: marker after plain snapshot_area={marker_after_snap2}, "
       f"after re_snapshot_area={marker_after_resnap}")

    # --- 4. ground truth (post-mutation) ---------------------------------------
    gt_post = ground_truth(rcon, b)
    results["ground_truth_post"] = gt_post
    hb(f"ground truth post: water={gt_post['water']} resources={gt_post['resource_total']} "
       f"built={gt_post['built_n']}")

    # --- 5. tick freshness ------------------------------------------------------
    # 5a. on-disk: scan snapshot files/dirs for any tick metadata
    tick_metadata_on_disk = []
    for cx, cy in chunks:
        d = snap_dir() / str(cx) / str(cy)
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if f.is_file():
                head = f.open().readline()
                if '"tick"' in head or "snapshot_tick" in head:
                    tick_metadata_on_disk.append(str(f))
    results["phases"]["tick_metadata_on_disk"] = tick_metadata_on_disk
    if not tick_metadata_on_disk:
        finding("NO tick metadata exists on disk (init JSONL has only kind/x/y/amount; "
                "no per-chunk tick file) — snapshot-tick freshness is UNFALSIFIABLE from "
                "disk alone; only file mtimes and in-game chunk_lookup carry recency")

    # 5b. in-game: chunk_lookup snapshot_tick for the cell's chunks
    cl = lua(rcon, "return remote.call('map','get_chunk_lookup')")
    now_tick = lua(rcon, "return {tick=game.tick}")["tick"]
    ticks = {}
    if isinstance(cl, dict) and "error" not in cl:
        for cx, cy in chunks:
            entry = cl.get(f"{cx},{cy}")
            if entry:
                ticks[f"{cx},{cy}"] = entry.get("snapshot_tick")
    fresh = [v for v in ticks.values() if isinstance(v, (int, float))]
    results["phases"]["chunk_snapshot_ticks"] = {"now": now_tick, "ticks": ticks}
    tick_advanced = bool(fresh) and max(fresh) > (results["smoke"]["tick1"])
    results["phases"]["snapshot_tick_advanced"] = tick_advanced
    hb(f"chunk snapshot_ticks: {len(fresh)} chunks marked, max={max(fresh) if fresh else None}, "
       f"now={now_tick}, advanced_past_session_start={tick_advanced}")

    # --- 6. load into fresh DuckDB via SnapshotLoader ---------------------------
    db_path = ART / "session_check.duckdb"
    if db_path.exists():
        db_path.unlink()
    db = SnapshotDatabase(db_path=str(db_path))
    db.ensure_schema()
    con = db.connection
    loader = SnapshotLoader(db=con, snapshot_dir=SNAP_ROOT)
    resolved = str(loader._snapshot_dir)
    results["phases"]["loader_resolved_dir"] = resolved
    hb(f"loader: snapshot_dir arg={SNAP_ROOT} resolved={resolved}")
    if not Path(resolved).is_dir():
        finding(f"H3 CONFIRMED: loader resolved dir does not exist: {resolved}")
    load_result = loader.load_all()
    results["phases"]["load_result"] = {
        "entity_count": load_result.entity_count,
        "resource_count": load_result.resource_count,
        "water_count": load_result.water_count,
        "ghost_count": load_result.ghost_count,
        "last_sequence": load_result.last_sequence,
    }
    hb(f"loader done: entities={load_result.entity_count} resources={load_result.resource_count} "
       f"water={load_result.water_count}")

    # --- 7. compare DB vs ground truth in cell bounds ---------------------------
    lt, rb = b["left_top"], b["right_bottom"]
    args_box = [lt["x"], rb["x"], lt["y"], rb["y"]]

    def in_box(table, xcol="position_x", ycol="position_y"):
        return con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {xcol} >= ? AND {xcol} < ? "
            f"AND {ycol} >= ? AND {ycol} < ?", args_box).fetchone()[0]

    db_water = in_box("water_tile")
    db_resource = in_box("resource_tile")
    db_entities = con.execute(
        "SELECT entity_name, position_x, position_y FROM map_entity "
        "WHERE position_x >= ? AND position_x < ? AND position_y >= ? AND position_y < ?",
        args_box).fetchall()
    db_res_by_name = dict(con.execute(
        "SELECT name, COUNT(*) FROM resource_tile WHERE position_x >= ? AND position_x < ? "
        "AND position_y >= ? AND position_y < ? GROUP BY name", args_box).fetchall())

    gt_built_set = {(e["name"], round(float(e["x"]), 2), round(float(e["y"]), 2))
                    for e in gt_post["built"]}
    db_built_set = {(r[0], round(float(r[1]), 2), round(float(r[2]), 2)) for r in db_entities}

    compare = {
        "water_tile": {"db": db_water, "ground_truth": gt_post["water"],
                       "match": db_water == gt_post["water"]},
        "resource_tile": {"db": db_resource, "ground_truth": gt_post["resource_total"],
                          "match": db_resource == gt_post["resource_total"],
                          "db_by_name": db_res_by_name,
                          "gt_by_name": gt_post["resource_counts"]},
        "map_entity": {"db": len(db_built_set), "ground_truth": len(gt_built_set),
                       "match": db_built_set == gt_built_set,
                       "only_in_game": sorted(gt_built_set - db_built_set),
                       "only_in_db": sorted(db_built_set - gt_built_set)},
        "snapshot_tick_advanced_in_game": tick_advanced,
        "tick_freshness_on_disk": "UNFALSIFIABLE (no metadata)" if not tick_metadata_on_disk else "present",
    }
    results["compare"] = compare
    hb(f"COMPARE: water {db_water}/{gt_post['water']} resource {db_resource}/{gt_post['resource_total']} "
       f"map_entity {len(db_built_set)}/{len(gt_built_set)} tick_advanced={tick_advanced}")

    claim_pass = (
        compare["water_tile"]["match"]
        and compare["resource_tile"]["match"]
        and compare["map_entity"]["match"]
        and gt_post["water"] > 0 and gt_post["resource_total"] > 0 and len(gt_built_set) > 0
        and tick_advanced
    )
    results["claim_pass"] = claim_pass

    # --- 8. cleanup (preserve files/DB evidence) --------------------------------
    hb("cleanup: destroying marker entities + agents created by this check")
    cleanup = lua(rcon, f"""
        local s = game.surfaces[1]
        local removed = 0
        for _, e in pairs(s.find_entities_filtered{{area={bounds_lua(b)}}}) do
            if e.valid and e.type ~= 'resource' and e.type ~= 'character' then
                e.destroy()
                removed = removed + 1
            end
        end
        local agents_destroyed = nil
        if remote.interfaces.agent and remote.interfaces.agent.destroy_agents then
            agents_destroyed = remote.call('agent','destroy_agents')
        end
        return {{removed=removed, agents_destroyed=agents_destroyed}}
    """)
    results["cleanup"] = cleanup
    # unassign any agent bindings for this cell
    lua(rcon, f"""
        local st = remote.call('lab_grid','get_storage')
        for agent_id, ci in pairs(st.agent_cells or {{}}) do
            remote.call('lab_grid','unassign_agent', agent_id)
        end
        return {{ok=true}}
    """)
    hb(f"cleanup done: {json.dumps(cleanup)[:200]}")

    (ART / "results.json").write_text(json.dumps(results, indent=2, default=str))
    hb(f"=== check_L1_10 end: claim_pass={claim_pass} ===")

    print("\n========== SUMMARY ==========")
    print(json.dumps({"claim_pass": claim_pass, "compare": compare,
                      "findings": results["findings"]}, indent=2, default=str))
    return 0 if claim_pass else 1


if __name__ == "__main__":
    sys.exit(main())
