#!/usr/bin/env python
"""Certification check L1.13 — replay-derived DB ≡ live-synced DB (all columns,
provenance included).

THE CLAIM: the two writers — SnapshotLoader (file replay: boot, rebuild, tests)
and SyncService (live UDP) — produce IDENTICAL map_entity/ghost rows for the
same logical op stream. This is the single-reducer conformance test: the DB
must not be path-dependent. It certifies, in one assertion:
  - lifecycle-completeness of the disk record (every agent-path mutation lands
    in the files, not just on the wire), and
  - writer agreement (the provenance fold rule + every column's semantics are
    the same on both paths).

Built RED-FIRST (2026-07-11 design session): pre-refactor, the writers are two
hand-rolled INSERTs with known divergences (placed_tick fallback: sync uses
payload tick, loader writes NULL; remove deletes different table sets) and
both squash provenance on builder-less upserts (PROV-2 — correctness is N6's
gate in the accessor family; THIS check gates path-agreement).

Procedure:
  1. allocate a fixed lab-grid cell; DRAIN the allocation's chunk-init
     re-snapshot before any rig op (recipe-group lesson, 2026-07-11)
  2. live DB: fresh in-memory Stack-A schema, load_all() baseline, then a
     SyncService fed by the mod's real UDP (port 34400, socat-forwarded;
     never repointed) applying ops during the churn
  3. churn via the AGENT path (remote interface, builder info flows): labeled
     + unlabeled places, set_recipe / set_filter / set_inventory_limit /
     rotate (config ops on labeled entities = the PROV-2 surface), inventory
     put, ghost place/rotate/remove, pickup, and the same-key re-place case
     (mine a labeled chest, re-place same name at the exact coordinates)
  4. replay DB: fresh schema + load_all() from the files alone
  5. symmetric all-column diff over map_entity + ghost within the cell
     bounds, raw_data JSON-normalized
  6. anti-vacuity plant: a seeded single-cell divergence MUST be caught by
     the same differ (else BLOCKED, the diff is vacuous)

Exit codes: 0 = PASS, 1 = FAIL (parity broken — expected pre-refactor),
2 = BLOCKED (could not measure).

Usage:
    uv run python scripts/certification/check_replay_parity.py \
        [--instance server_0] [--cell 21]
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests" / "generated"))

from _frozen import runtime  # noqa: E402  (audited harness substrate)
from _frozen.accessor_spec import wait_ops_flushed  # noqa: E402

from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase  # noqa: E402
from FactoryVerse.game.infra.duckdb.loader import SnapshotLoader  # noqa: E402
from FactoryVerse.game.infra.duckdb.sync import SyncService  # noqa: E402
from FactoryVerse.infra.udp_dispatcher import UDPDispatcher  # noqa: E402

ART = REPO / ".fv-output" / "certification" / str(date.today()) / "L1.13"
ART.mkdir(parents=True, exist_ok=True)
PROGRESS = ART / "progress.log"

SNAPSHOT_UDP_PORT = 34400  # mod default; the ONLY snapshot port socat forwards


def hb(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with PROGRESS.open("a") as f:
        f.write(line + "\n")


# ---------------------------------------------------------------------------
# Row capture + diff (pure; the plant validates it)
# ---------------------------------------------------------------------------

ENTITY_COLS = ("entity_name", "position_x", "position_y", "chunk_x", "chunk_y",
               "direction", "bbox_min_x", "bbox_min_y", "bbox_max_x",
               "bbox_max_y", "agent_id", "player_id", "label", "placed_tick",
               "raw_data")
GHOST_COLS = ("ghost_name", "position_x", "position_y", "chunk_x", "chunk_y",
              "direction", "placed_tick", "placed_by", "label", "raw_data")


def capture_rows(con, bounds: Dict) -> Dict[str, Dict[str, Any]]:
    """All map_entity + ghost rows inside bounds, keyed table:name@x,y,
    values = column dict with raw_data parsed."""
    lt, rb = bounds["left_top"], bounds["right_bottom"]
    out: Dict[str, Dict[str, Any]] = {}
    for table, cols, name_col in (("map_entity", ENTITY_COLS, "entity_name"),
                                  ("ghost", GHOST_COLS, "ghost_name")):
        rows = con.execute(
            f"SELECT {', '.join(cols)} FROM {table} "
            "WHERE position_x >= ? AND position_x < ? "
            "AND position_y >= ? AND position_y < ?",
            [lt["x"], rb["x"], lt["y"], rb["y"]],
        ).fetchall()
        for r in rows:
            rec = dict(zip(cols, r))
            try:
                rec["raw_data"] = json.loads(rec["raw_data"]) if rec["raw_data"] else None
            except (TypeError, json.JSONDecodeError):
                pass  # keep as-is; a non-JSON raw_data will diff loudly
            key = f"{table}:{rec[name_col]}@{rec['position_x']},{rec['position_y']}"
            out[key] = rec
    return out


def diff_rows(a: Dict[str, Dict], b: Dict[str, Dict]) -> List[Dict[str, Any]]:
    """Symmetric diff: rows only in one side + per-column mismatches."""
    diffs: List[Dict[str, Any]] = []
    for key in sorted(set(a) | set(b)):
        if key not in a:
            diffs.append({"key": key, "kind": "only_in_replay"})
        elif key not in b:
            diffs.append({"key": key, "kind": "only_in_live"})
        else:
            for col in a[key]:
                if a[key][col] != b[key].get(col):
                    diffs.append({"key": key, "kind": "column_mismatch",
                                  "column": col,
                                  "live": a[key][col], "replay": b[key].get(col)})
    return diffs


def max_file_sequence(snapshot_root: Path) -> int:
    """Highest op sequence currently on disk — seeds SyncService so the live
    path starts gap-free (a mid-churn rebuild would contaminate it with
    file-replay rows)."""
    best = 0
    snap = snapshot_root / "factoryverse" / "snapshots"
    if not snap.exists():
        return 0
    for path in snap.rglob("*.jsonl"):
        try:
            with path.open() as f:
                for line in f:
                    if '"sequence"' not in line:
                        continue
                    try:
                        seq = json.loads(line).get("sequence")
                        if isinstance(seq, int) and seq > best:
                            best = seq
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue
    return best


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------

async def run_check(instance_name: str, cell_index: int) -> int:
    from FactoryVerse.game.agent.infra.rcon_handler import RconHandler
    from FactoryVerse.game.agent.embodied_actions.entity_operations import (
        EntityOperationsAction)
    from FactoryVerse.game.agent.embodied_actions.place_entity import PlacementAction
    from FactoryVerse.game.agent.embodied_actions.walking import MovementAction
    from FactoryVerse.game.factory.types import MapPosition

    inst = runtime.Instance(
        name=instance_name, rcon_host="localhost",
        rcon_port=27000 + int(instance_name.split("_")[1]),
        rcon_password="factorio",
        snapshot_root=REPO / ".fv-output" / instance_name,
    ) if instance_name.startswith("server_") else runtime.instance_from_env()

    rcon = runtime.connect(inst)
    runtime.verify_grid_config(rcon)
    sess = runtime.allocate_cell(rcon, cell_index)
    hb(f"cell {cell_index} allocated (agent {sess.agent_id}); draining init re-snapshot")

    rebuilds: List[float] = []
    dispatcher: Optional[UDPDispatcher] = None
    sync: Optional[SyncService] = None
    verdict = 2
    try:
        # 1. drain the allocation-triggered chunk-init snapshot BEFORE any rig op
        wait_ops_flushed(rcon, timeout_s=90.0)

        # 2. live DB: schema + baseline load, then live sync on the real port
        live_db = SnapshotDatabase(db_path=None)
        live_db.ensure_schema()
        live_con = live_db.connection
        tick0 = runtime.game_tick(rcon)
        SnapshotLoader(db=live_con, snapshot_dir=inst.snapshot_root).load_all(
            current_game_tick=tick0)
        initial_seq = max_file_sequence(inst.snapshot_root)
        hb(f"live DB baseline loaded @tick {tick0}; initial_sequence={initial_seq}")

        dispatcher = UDPDispatcher(host="127.0.0.1", port=SNAPSHOT_UDP_PORT)
        await dispatcher.start()
        sync = SyncService(db=live_con, udp_dispatcher=dispatcher,
                           on_rebuild=lambda: rebuilds.append(time.time()),
                           initial_sequence=initial_seq)
        await sync.start()
        hb(f"SyncService live on :{SNAPSHOT_UDP_PORT}")

        # 3. agent-path churn
        handler = RconHandler(rcon, f"agent_{sess.agent_id}")
        ops = EntityOperationsAction(handler)
        movement = MovementAction(handler, async_listener=None)
        placement = PlacementAction(handler, ops, movement)

        runtime.lua_strict(
            rcon,
            f"return remote.call('agent','add_items',{sess.agent_id},"
            "{['iron-chest']=3,['assembling-machine-1']=1,['inserter']=1,"
            "['iron-plate']=12,['transport-belt']=2})")

        sx, sy = sess.spawn["x"], sess.spawn["y"]
        P = {
            "chest":   {"x": sx - 3.5, "y": sy + 0.5},
            "asm":     {"x": sx + 4.0, "y": sy - 3.0},   # 3x3 -> whole coords
            "inserter": {"x": sx - 1.5, "y": sy - 3.5},
            "ghost1":  {"x": sx + 0.5, "y": sy + 3.5},
            "ghost2":  {"x": sx + 1.5, "y": sy + 3.5},
            "rekey":   {"x": sx - 3.5, "y": sy + 2.5},
        }

        async def op(desc, fn, *a, **kw):
            hb(f"churn: {desc}")
            res = fn(*a, **kw)
            if hasattr(res, "success") and not res.success:
                raise RuntimeError(f"churn op failed: {desc}: {res}")
            await asyncio.sleep(0.6)  # let the loop drain datagrams
            return res

        # labeled + unlabeled builds
        await op("place labeled chest", placement.place, "iron-chest",
                 P["chest"], label="parity-chest")
        await op("place labeled asm", placement.place, "assembling-machine-1",
                 P["asm"], label="parity-asm")
        await op("place unlabeled inserter", placement.place, "inserter",
                 P["inserter"])
        # config ops (the PROV-2 surface: on labeled where possible)
        await op("set_recipe on labeled asm", ops.set_entity_recipe,
                 "assembling-machine-1", "iron-gear-wheel",
                 position=MapPosition(**P["asm"]))
        await op("set_filter on inserter", ops.set_entity_filter,
                 "inserter", MapPosition(**P["inserter"]), "inserter_filter",
                 filter_index=1, filter_item="iron-plate")
        await op("set_inventory_limit on labeled chest", ops.set_inventory_limit,
                 "iron-chest", "chest", 10, position=MapPosition(**P["chest"]))
        await op("rotate inserter", ops.rotate_entity, "inserter",
                 position=MapPosition(**P["inserter"]), direction=4)
        # inventory transfer (upsert-free op class on the wire? included for coverage)
        from FactoryVerse.game.factory.item.create_item import create_item_stack
        await op("put 5 iron-plate into chest", ops.put_inventory_item,
                 "iron-chest", "chest",
                 create_item_stack("iron-plate", 5, placement=placement),
                 position=MapPosition(**P["chest"]))
        # ghosts: labeled place, rotate, remove one
        await op("place labeled ghost belt #1", placement.place, "transport-belt",
                 P["ghost1"], ghost=True, label="parity-ghost")
        await op("place labeled ghost belt #2", placement.place, "transport-belt",
                 P["ghost2"], ghost=True, label="parity-ghost")
        await op("rotate ghost #1", ops.rotate_entity, "transport-belt",
                 position=MapPosition(**P["ghost1"]), direction=4, is_ghost=True)
        await op("remove ghost #2", placement.remove_ghost, "transport-belt",
                 MapPosition(**P["ghost2"]))
        # same-key re-place: labeled chest -> pickup -> unlabeled same name+pos
        await op("place labeled rekey chest", placement.place, "iron-chest",
                 P["rekey"], label="parity-rekey")
        await op("pickup rekey chest", ops.pickup_entity, "iron-chest",
                 position=MapPosition(**P["rekey"]))
        await op("re-place same key unlabeled", placement.place, "iron-chest",
                 P["rekey"])

        # 4. settle: disk flushed + wire drained
        wait_ops_flushed(rcon, timeout_s=90.0)
        await asyncio.sleep(2.0)
        if hasattr(sync, "flush_pending"):
            sync.flush_pending()
        await asyncio.sleep(1.0)

        live_rows = capture_rows(live_con, sess.bounds)
        hb(f"live rows captured: {len(live_rows)} (rebuilds during churn: {len(rebuilds)})")

        # 5. replay DB from files alone
        replay_db = SnapshotDatabase(db_path=None)
        replay_db.ensure_schema()
        replay_con = replay_db.connection
        SnapshotLoader(db=replay_con, snapshot_dir=inst.snapshot_root).load_all(
            current_game_tick=runtime.game_tick(rcon))
        replay_rows = capture_rows(replay_con, sess.bounds)
        hb(f"replay rows captured: {len(replay_rows)}")

        # 6. anti-vacuity plant BEFORE the verdict: differ must catch a seeded
        # divergence
        if not replay_rows:
            hb("BLOCKED: replay DB has zero rows in cell bounds — nothing measured")
            return 2
        planted = copy.deepcopy(replay_rows)
        planted[next(iter(planted))]["label"] = "__L113_PLANT__"
        if not diff_rows(live_rows, planted):
            hb("BLOCKED: differ failed to catch a seeded divergence (vacuous diff)")
            return 2
        hb("plant OK: differ catches seeded divergence")

        diffs = diff_rows(live_rows, replay_rows)
        (ART / "rows_live.json").write_text(json.dumps(live_rows, indent=1, default=str))
        (ART / "rows_replay.json").write_text(json.dumps(replay_rows, indent=1, default=str))
        (ART / "diff.json").write_text(json.dumps(diffs, indent=1, default=str))

        if rebuilds:
            hb(f"BLOCKED: {len(rebuilds)} sync rebuild(s) fired mid-churn — live "
               "path contaminated by file replay; re-run")
            return 2
        if diffs:
            hb(f"FAIL: {len(diffs)} divergence(s) between live and replay paths "
               f"(see {ART / 'diff.json'})")
            for d in diffs[:12]:
                hb(f"  {d}")
            return 1
        hb(f"PASS: {len(live_rows)} rows identical across both paths, all columns")
        return 0
    finally:
        if sync is not None:
            try:
                await sync.stop()
            except Exception:
                pass
        if dispatcher is not None:
            try:
                await dispatcher.stop()
            except Exception:
                pass
        runtime.release_cell(rcon, sess)
        hb(f"cell {cell_index} released")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", default="server_0")
    ap.add_argument("--cell", type=int, default=21)
    args = ap.parse_args()
    return asyncio.run(run_check(args.instance, args.cell))


if __name__ == "__main__":
    raise SystemExit(main())
