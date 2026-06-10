#!/usr/bin/env python3
"""Certification check L1.1 — census parity (game ground truth vs snapshot DB).

Compares two independent views of the world:
  A. Census dump (`FactoryVerse.dev.census.dump_census`) — chunked
     find_entities_filtered over RCON, written to script-output JSONL.
     Ground truth, read channel #2 of the runtime playbook.
  B. Snapshot files loaded via the production Stack-A path
     (SnapshotDatabase + SnapshotLoader) into a FRESH temp DuckDB file.
     Never opens a live session DB; snapshot JSONL files are only read.

Parity = set-diff on (name, round(x,2), round(y,2)) in both directions,
split by category:
  - entities:  census non-resource (characters excluded) vs map_entity
  - resources: census type='resource' (ores) vs resource_tile

Anti-vacuity guard: VACUOUS-RISK if the census is empty while the surface
reports entities, or if both sides are empty.

READ-ONLY against the game: only find_entities_filtered + write_file into
factoryverse/dumps/. Safe to execute while other checks mutate the world —
but a PASS verdict is only meaningful when nothing mutates concurrently.

Run:  uv run python scripts/certification/check_L1_1.py --instance server_0
Exit: 0 PASS, 1 FAIL, 2 BLOCKED, 3 VACUOUS-RISK
"""

from __future__ import annotations

import datetime
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from factorio_rcon import RCONClient  # noqa: E402

from FactoryVerse.dev.census import (  # noqa: E402
    CensusError,
    direct_count,
    dump_census,
    parse_bounds,
)
from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase  # noqa: E402
from FactoryVerse.game.infra.duckdb.loader import SnapshotLoader  # noqa: E402
from FactoryVerse.infra.instance_manager import FactorioInstanceManager  # noqa: E402

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------
DATE = datetime.datetime.now().strftime("%Y-%m-%d")
ART = REPO / ".fv-output" / "certification" / DATE / "L1.1"
ART.mkdir(parents=True, exist_ok=True)
PROGRESS = ART / "progress.log"

MAX_DIFF_LINES = 200  # cap per-direction diff entries written into results.json

results: dict = {"check": "L1.1", "findings": []}


def hb(msg: str) -> None:
    line = f"{datetime.datetime.now().isoformat(timespec='seconds')} {msg}"
    with open(PROGRESS, "a") as f:
        f.write(line + "\n")
    print(f"[hb] {line}", flush=True)


def finding(msg: str) -> None:
    results["findings"].append(msg)
    print(f"[FINDING] {msg}", flush=True)


def key(name: str, x, y) -> tuple:
    return (name, round(float(x), 2), round(float(y), 2))


def tile_key(name: str, x, y) -> tuple:
    """Resource parity key: anchor tile coords.

    The mod snapshots resources as TILES (integer x/y per resource tile in
    resources-init.jsonl) while the game census reports entity positions
    (tile center, +0.5). Verified live 2026-06-11: census == resource_tile
    shifted by exactly +0.5 on both axes, 1459/1459 in lab-grid cell 0
    (incl. crude-oil). Floor both sides to the tile to compare like-for-like.
    """
    import math

    return (name, math.floor(float(x)), math.floor(float(y)))


def finish(status: str, code: int) -> int:
    results["status"] = status
    (ART / "results.json").write_text(json.dumps(results, indent=2, default=str))
    hb(f"=== check_L1_1 end: {status} ===")
    print(f"\nSTATUS: {status}")
    print(f"ARTIFACTS: {ART}")
    return code


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", default="client", help="client or server_N")
    ap.add_argument("--bounds", help="tile bounds x1,y1,x2,y2 (default: whole map)")
    ap.add_argument(
        "--force",
        default="player",
        help="force whose entities to census (lab-grid cells use per-cell forces, "
        "e.g. cell_0; neutral resources are always included)",
    )
    args = ap.parse_args()
    bounds = parse_bounds(args.bounds)

    hb(f"=== check_L1_1 start (instance={args.instance}, bounds={bounds}, force={args.force}) ===")

    if args.instance == "client":
        inst = FactorioInstanceManager.get_client()
    else:
        inst = FactorioInstanceManager.get_server(int(args.instance.split("_")[1]))
    results["instance"] = inst.name

    # --- 0. smoke ritual ------------------------------------------------------
    hb("smoke: connecting RCON, verifying snapshot interface")
    try:
        rcon = RCONClient(inst.rcon_host, inst.rcon_port, inst.rcon_password)
        rcon.send_command("/c rcon.print('ping')")
        assert "ping" in rcon.send_command("/c rcon.print('ping')"), "smoke ping failed"
        ifaces = json.loads(
            rcon.send_command("/c rcon.print(helpers.table_to_json(remote.interfaces))")
        )
    except Exception as e:
        hb(f"SMOKE FAIL: {e}")
        print(f"BLOCKED: no RCON at {inst.rcon_host}:{inst.rcon_port} ({e})")
        return finish("BLOCKED", 2)
    missing = [i for i in ("snapshot", "map", "entities") if i not in ifaces]
    if missing:
        hb(f"SMOKE FAIL: missing interfaces {missing}")
        print(f"BLOCKED: missing interfaces {missing}")
        return finish("BLOCKED", 2)
    results["smoke"] = {"interfaces": sorted(ifaces.keys())}
    hb("smoke ok")

    # --- 1. census dump (ground truth, side A) --------------------------------
    hb("phase 1: census dump via dev.census (chunked, read-only)")
    try:
        census = dump_census(instance=inst.name, bounds=bounds, force=args.force, rcon=rcon)
    except CensusError as e:
        finding(f"census dump failed: {e}")
        return finish("BLOCKED", 2)
    results["census"] = {
        "tick": census.tick,
        "rows": len(census),
        "chunks": census.chunk_count,
        "rcon_calls": census.rcon_calls,
        "counts_by_type": census.counts_by_type,
        "jsonl": str(census.host_path),
    }
    shutil.copy(census.host_path, ART / "census.jsonl")
    hb(f"phase 1 done: {len(census)} rows @ tick {census.tick} -> {ART/'census.jsonl'}")

    # Independent count for the anti-vacuity guard (single-call path, not the
    # chunked dumper under test).
    surface_n = direct_count(instance=inst.name, bounds=bounds, force=args.force, rcon=rcon)
    results["surface_direct_count"] = surface_n

    census_entities = {
        key(r["name"], r["position"]["x"], r["position"]["y"])
        for r in census.rows
        if r["type"] not in ("resource", "character")
    }
    census_resources = {
        tile_key(r["name"], r["position"]["x"], r["position"]["y"])
        for r in census.rows
        if r["type"] == "resource"
    }

    # --- 2. snapshot DB (side B): fresh temp DuckDB file, production loader ---
    snap_dir = inst.script_output_dir / "factoryverse" / "snapshots"
    hb(f"phase 2: loading snapshots from {snap_dir} into fresh temp DuckDB")
    if not snap_dir.exists():
        finding(f"snapshot directory does not exist: {snap_dir}")
    db_path = ART / f"parity-{datetime.datetime.now().strftime('%H%M%S')}.duckdb"
    if db_path.exists():
        db_path.unlink()
    db = SnapshotDatabase(db_path)
    db.ensure_schema()
    con = db.connection
    loader = SnapshotLoader(db=con, snapshot_dir=inst.script_output_dir)
    load_result = loader.load_all()
    results["snapshot_load"] = {
        "db_path": str(db_path),
        "entity_count": load_result.entity_count,
        "resource_count": load_result.resource_count,
        "ghost_count": load_result.ghost_count,
        "last_sequence": load_result.last_sequence,
        "chunks_loaded": len(load_result.chunks),
    }
    hb(
        f"phase 2 done: loaded entities={load_result.entity_count} "
        f"resources={load_result.resource_count} chunks={len(load_result.chunks)}"
    )

    def in_bounds_sql(prefix: str = "") -> tuple[str, list]:
        if bounds is None:
            return "1=1", []
        x1, y1, x2, y2 = bounds
        return (
            f"{prefix}position_x >= ? AND {prefix}position_x < ? "
            f"AND {prefix}position_y >= ? AND {prefix}position_y < ?",
            [x1, x2, y1, y2],
        )

    where, params = in_bounds_sql()
    db_entities = {
        key(r[0], r[1], r[2])
        for r in con.execute(
            f"SELECT entity_name, position_x, position_y FROM map_entity WHERE {where}",
            params,
        ).fetchall()
    }
    db_resources = {
        tile_key(r[0], r[1], r[2])
        for r in con.execute(
            f"SELECT name, position_x, position_y FROM resource_tile WHERE {where}",
            params,
        ).fetchall()
    }
    con.close()

    # --- 3. anti-vacuity guard -------------------------------------------------
    if len(census) == 0 and surface_n > 0:
        finding(
            f"VACUOUS: census returned 0 rows but surface reports {surface_n} "
            f"entities — the dumper saw nothing, parity would be meaningless"
        )
        return finish("VACUOUS-RISK", 3)
    if len(census) == 0 and not db_entities and not db_resources:
        finding("VACUOUS: both census and snapshot DB are empty — nothing was compared")
        return finish("VACUOUS-RISK", 3)

    # --- 4. set-diff both directions --------------------------------------------
    hb("phase 4: set-diff (name, round(x,2), round(y,2)) both directions")
    diffs = {}
    ok = True
    for label, a, b in (
        ("entities", census_entities, db_entities),
        ("resources", census_resources, db_resources),
    ):
        only_census = sorted(a - b)
        only_db = sorted(b - a)
        diffs[label] = {
            "census_count": len(a),
            "db_count": len(b),
            "only_in_census": only_census[:MAX_DIFF_LINES],
            "only_in_census_total": len(only_census),
            "only_in_db": only_db[:MAX_DIFF_LINES],
            "only_in_db_total": len(only_db),
            "exact_match": not only_census and not only_db,
        }
        if only_census or only_db:
            ok = False
        hb(
            f"  {label}: census={len(a)} db={len(b)} "
            f"only_census={len(only_census)} only_db={len(only_db)}"
        )
    results["parity"] = diffs
    (ART / "diffs.json").write_text(json.dumps(diffs, indent=2, default=str))

    print("\n========== SUMMARY ==========")
    print(json.dumps({k: v for k, v in results.items() if k != "parity"}, indent=2, default=str))
    for label, d in diffs.items():
        print(
            f"{label}: census={d['census_count']} db={d['db_count']} "
            f"match={d['exact_match']} "
            f"(+{d['only_in_census_total']} census-only / +{d['only_in_db_total']} db-only)"
        )

    return finish("PASS" if ok else "FAIL", 0 if ok else 1)


if __name__ == "__main__":
    sys.exit(main())
