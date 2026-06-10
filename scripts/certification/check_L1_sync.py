#!/usr/bin/env python3
"""Certification check L1.2 / L1.3 / L1.5 — live UDP sync battery (Stack A production path).

Tests exactly what Tier4 uses:
  - game/infra/duckdb/database.py  SnapshotDatabase (in-memory)
  - game/infra/duckdb/loader.py    SnapshotLoader (initial load from snapshot JSONL)
  - game/infra/duckdb/sync.py      SyncService    (UDP incremental sync)
  - infra/udp_dispatcher.py        UDPDispatcher

Battery:
  L1.2  removal syncs (row gone after destroy + flush)
  L1.3  rotation / config-change syncs (direction column / raw_data updated)
  L1.5  component + derived tables track post-load mutations (settle the
        recorded CONTRADICTION: AST analysis says incremental sync SQL only
        writes map_entity/resource_entity/ghost)

Idempotent: clears its work area (one chunk, tiles 64..96 / chunk (2,2)) at
start and end, restores the mod's snapshot UDP port, leaves no agents.

Run:  uv run python scripts/certification/check_L1_sync.py
"""

from __future__ import annotations

import asyncio
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
from FactoryVerse.game.infra.duckdb.sync import SyncService  # noqa: E402
from FactoryVerse.infra.udp_dispatcher import UDPDispatcher  # noqa: E402

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------
DATE = "2026-06-10"
ART = REPO / ".fv-output" / "certification" / DATE / "L1.sync"
ART.mkdir(parents=True, exist_ok=True)
PROGRESS = ART / "progress.log"
UDP_LOG = ART / "udp_payloads.jsonl"

RCON_HOST, RCON_PORT, RCON_PASS = "localhost", 27100, "factorio"
CHECK_UDP_PORT = 34571  # our standalone listener; mod port restored afterwards

SNAP_ROOT = Path.home() / "Library/Application Support/factorio/script-output"


def configure_instance(name: str) -> None:
    """Point module globals at 'client' or 'server_N'. Server script-output
    maps to host .fv-output/server_N (compose volume). NOTE: on servers the
    mod's UDP leaves the container via the udp_forwarder sidecar — whether a
    host listener on CHECK_UDP_PORT receives it is itself under test."""
    global RCON_PORT, SNAP_ROOT, CHECK_UDP_PORT
    if name == "client":
        return
    if name.startswith("server_"):
        n = int(name.split("_")[1])
        RCON_PORT = 27000 + n
        SNAP_ROOT = REPO / ".fv-output" / name
        # The socat sidecar only forwards specific container ports to the
        # host (34202-34211 agent + 34400 snapshot). An arbitrary port like
        # 34571 dies inside the container — verified empirically 2026-06-10.
        # So on servers we listen on the forwarded snapshot port itself.
        CHECK_UDP_PORT = 34400 + n
        return
    raise SystemExit(f"unknown instance {name!r}; use 'client' or 'server_N'")

# Work area: exactly chunk (2,2) → tiles [64,96)
WORK = {"left_top": {"x": 64, "y": 64}, "right_bottom": {"x": 96, "y": 96}}
WORK_CHUNK = (2, 2)

RIG = [
    # (entity_name, x, y, direction)
    ("burner-mining-drill", 70.0, 86.0, 4),
    ("transport-belt", 72.5, 68.5, 4),
    ("transport-belt", 73.5, 68.5, 4),
    ("transport-belt", 74.5, 68.5, 4),
    ("inserter", 75.5, 68.5, 4),
    ("iron-chest", 76.5, 68.5, 0),
    ("assembling-machine-1", 80.5, 72.5, 4),
]
ORE = ("iron-ore", 70, 86, 4, 5000)  # name, cx, cy, size, amount

MUT_CHEST = ("iron-chest", 68.5, 66.5)  # placed live in phase 4a, removed in 4b
ROT_BELT = ("transport-belt", 73.5, 68.5)  # middle belt, rotated in 4c
CFG_ASM = ("assembling-machine-1", 80.5, 72.5)  # recipe set in 4d

COMPONENT_TABLES = ["inserter", "transport_belt", "mining_drill", "assembler"]
DERIVED_TABLES = ["belt_line", "belt_line_segment", "electric_pole", "resource_patch"]

results: dict = {"phases": {}, "findings": []}


def hb(msg: str) -> None:
    line = f"{datetime.datetime.now().isoformat(timespec='seconds')} {msg}"
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
    """Run a Lua expression body (must `return <table>`), get parsed JSON."""
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


def census(rcon: RCONClient) -> list:
    """Ground truth: player-force entities in the work area (no characters)."""
    res = lua(
        rcon,
        f"""
        local out = {{}}
        local ents = game.surfaces[1].find_entities_filtered{{area={bounds_lua(WORK)}, force='player'}}
        for _, e in ipairs(ents) do
            if e.type ~= 'character' then
                table.insert(out, {{name=e.name, x=e.position.x, y=e.position.y, direction=e.direction}})
            end
        end
        return {{n=#out, entities=out}}
        """,
    )
    if "error" in res:
        raise RuntimeError(f"census failed: {res['error']}")
    ents = res.get("entities", [])
    # table_to_json turns empty table into {} not []
    if isinstance(ents, dict):
        ents = list(ents.values())
    return ents


# ----------------------------------------------------------------------------
# DB helpers
# ----------------------------------------------------------------------------
def table_names(con) -> list:
    rows = con.execute(
        "SELECT table_name FROM information_schema.tables ORDER BY table_name"
    ).fetchall()
    return [r[0] for r in rows]


def db_state(con) -> dict:
    """Row counts for every table + work-area map_entity rows + component rows."""
    state = {"counts": {}, "work_map_entity": [], "component_rows": {}}
    for t in table_names(con):
        try:
            state["counts"][t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except Exception as e:
            state["counts"][t] = f"ERR {e}"
    rows = con.execute(
        """SELECT entity_name, position_x, position_y, direction
           FROM map_entity
           WHERE position_x >= ? AND position_x < ? AND position_y >= ? AND position_y < ?
           ORDER BY entity_name, position_x, position_y""",
        [WORK["left_top"]["x"], WORK["right_bottom"]["x"],
         WORK["left_top"]["y"], WORK["right_bottom"]["y"]],
    ).fetchall()
    state["work_map_entity"] = [
        {"name": r[0], "x": r[1], "y": r[2], "direction": r[3]} for r in rows
    ]
    for t in COMPONENT_TABLES:
        try:
            state["component_rows"][t] = con.execute(f"SELECT * FROM {t}").fetchall()
        except Exception as e:
            state["component_rows"][t] = f"ERR {e}"
    return state


def me_row(con, name: str, x: float, y: float):
    return con.execute(
        "SELECT entity_name, position_x, position_y, direction, raw_data "
        "FROM map_entity WHERE entity_name=? AND position_x=? AND position_y=?",
        [name, x, y],
    ).fetchall()


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
async def live_phase(rcon: RCONClient, con, initial_sequence: int) -> None:
    captured: list = []
    rebuilds: list = []

    def on_udp(payload):
        rec = {"recv_time": time.time(), "payload": payload}
        captured.append(rec)
        with open(UDP_LOG, "a") as f:
            f.write(json.dumps(rec) + "\n")

    def wait_for(pred, timeout=12.0):
        """Wait until a captured payload matches pred; return it or None."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            for rec in captured:
                if pred(rec["payload"]):
                    return rec["payload"]
            time.sleep(0.25)
        return None

    # --- 3. stand up dispatcher + sync, repoint mod UDP -----------------------
    hb("udp setup: reading current mod snapshot UDP port")
    old_port = lua(rcon, "return {port = remote.call('snapshot','get_udp_port')}")
    old_port_val = old_port.get("port")
    results["old_udp_port"] = old_port_val
    if not isinstance(old_port_val, int):
        raise RuntimeError(f"could not read mod UDP port: {old_port}")

    dispatcher = UDPDispatcher(host="127.0.0.1", port=CHECK_UDP_PORT)
    await dispatcher.start()
    dispatcher.subscribe("*", on_udp)

    sync = SyncService(
        db=con,
        udp_dispatcher=dispatcher,
        on_rebuild=lambda: rebuilds.append(time.time()),
        initial_sequence=initial_sequence,
    )
    await sync.start()

    set_res = lua(
        rcon,
        f"remote.call('snapshot','set_udp_port', {CHECK_UDP_PORT}) return {{ok=true}}",
    )
    if "error" in set_res:
        raise RuntimeError(f"set_udp_port failed: {set_res['error']}")
    hb(f"udp setup done: mod port {old_port_val} -> {CHECK_UDP_PORT}, "
       f"SyncService initial_sequence={initial_sequence}")

    try:
        # === 4a. PLACE =========================================================
        name, x, y = MUT_CHEST
        hb(f"mutation 4a: placing {name} at ({x},{y}) via test_ground.place_entity")
        res = lua(
            rcon,
            f"return remote.call('test_ground','place_entity','{name}',{{x={x},y={y}}},0,'player')",
        )
        place_path = "test_ground.place_entity (script, raise_built=true)"
        if not res.get("success"):
            raise RuntimeError(f"place failed: {res}")

        pl = wait_for(
            lambda p: p.get("event_type") == "entity_operation"
            and p.get("op") in ("created", "upsert")
            and p.get("name") == name,
            timeout=12.0,
        )
        if pl is None:
            finding(
                "NO UDP entity_operation within 12s for script-placed entity "
                "(test_ground.place_entity with raise_built=true) — script-placed "
                "event coverage gap"
            )
        n = sync.flush_pending()
        rows = me_row(con, name, x, y)
        results["phases"]["4a_place"] = {
            "path": place_path,
            "udp_payload_seen": pl is not None,
            "udp_payload": pl,
            "ops_flushed": n,
            "db_rows_after": [r[:4] for r in rows],
            "pass": len(rows) == 1,
        }
        hb(f"mutation 4a done: udp={'yes' if pl else 'NO'}, flushed={n}, "
           f"db rows for new chest={len(rows)}")

        comp_after_place = {
            t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in COMPONENT_TABLES
        }
        results["phases"]["4a_component_counts"] = comp_after_place

        # === 4b. REMOVE (L1.2) =================================================
        hb(f"mutation 4b: destroying {name} at ({x},{y}) via entity.destroy{{raise_destroy=true}}")
        res = lua(
            rcon,
            f"""
            local e = game.surfaces[1].find_entities_filtered{{name='{name}',
                position={{x={x},y={y}}}, radius=0.2}}[1]
            if not e then return {{error='entity not found'}} end
            e.destroy{{raise_destroy=true}}
            return {{ok=true}}
            """,
        )
        if "error" in res:
            raise RuntimeError(f"destroy failed: {res}")
        pl = wait_for(
            lambda p: p.get("event_type") == "entity_operation"
            and p.get("op") in ("destroyed", "remove")
            and p.get("name") == name,
            timeout=12.0,
        )
        if pl is None:
            finding("NO UDP entity_operation (destroy) within 12s for script destroy with raise_destroy=true")
        n = sync.flush_pending()
        rows = me_row(con, name, x, y)
        results["phases"]["4b_remove"] = {
            "udp_payload_seen": pl is not None,
            "udp_payload": pl,
            "ops_flushed": n,
            "db_rows_after": [r[:4] for r in rows],
            "pass": pl is not None and len(rows) == 0,
        }
        hb(f"mutation 4b done: udp={'yes' if pl else 'NO'}, flushed={n}, "
           f"residual rows={len(rows)} (want 0)")

        # === 4c. ROTATE (L1.3) =================================================
        name, x, y = ROT_BELT
        before_rows = me_row(con, name, x, y)
        dir_before_db = before_rows[0][3] if before_rows else None
        hb(f"mutation 4c: rotating {name} at ({x},{y}) via remote entities.rotate")
        res = lua(
            rcon,
            f"return {{result = remote.call('entities','rotate','{name}',{{x={x},y={y}}})}}",
        )
        rotate_path = "remote entities.rotate (EntityInterface custom event)"
        if "error" in res:
            finding(f"entities.rotate errored: {str(res['error'])[:300]}")
            # fallback: player rotate (raises on_player_rotated_entity)
            rotate_path = "entity.rotate{by_player=players[1]}"
            res = lua(
                rcon,
                f"""
                local e = game.surfaces[1].find_entities_filtered{{name='{name}',
                    position={{x={x},y={y}}}, radius=0.2}}[1]
                if not e then return {{error='belt not found'}} end
                local p = game.players[1]
                if not p then return {{error='no player for by_player rotate'}} end
                local ok2 = e.rotate{{by_player=p}}
                return {{rotated=ok2, new_direction=e.direction}}
                """,
            )
            if "error" in res:
                raise RuntimeError(f"both rotate paths failed: {res}")
        game_dir = lua(
            rcon,
            f"""
            local e = game.surfaces[1].find_entities_filtered{{name='{name}',
                position={{x={x},y={y}}}, radius=0.2}}[1]
            if not e then return {{error='belt not found'}} end
            return {{direction=e.direction}}
            """,
        )
        pl = wait_for(
            lambda p: p.get("event_type") == "entity_operation"
            and p.get("op") == "rotated"
            and p.get("name") == name,
            timeout=12.0,
        )
        if pl is None:
            finding(f"NO UDP rotated payload within 12s (path: {rotate_path})")
        n = sync.flush_pending()
        rows = me_row(con, name, x, y)
        dir_after_db = rows[0][3] if rows else None
        belt_comp = con.execute(
            "SELECT * FROM transport_belt WHERE position_x=? AND position_y=?", [x, y]
        ).fetchall()
        results["phases"]["4c_rotate"] = {
            "path": rotate_path,
            "udp_payload_seen": pl is not None,
            "udp_payload": pl,
            "ops_flushed": n,
            "game_direction_after": game_dir.get("direction"),
            "db_direction_before": dir_before_db,
            "db_direction_after": dir_after_db,
            "transport_belt_component_rows": belt_comp,
            "pass": pl is not None
            and dir_after_db is not None
            and str(dir_after_db) != str(dir_before_db),
        }
        hb(f"mutation 4c done: udp={'yes' if pl else 'NO'}, db direction "
           f"{dir_before_db!r} -> {dir_after_db!r}, game dir={game_dir.get('direction')}")

        # === 4d. CONFIG CHANGE (recipe) (L1.3/L1.5) ============================
        name, x, y = CFG_ASM
        hb(f"mutation 4d: set_recipe iron-gear-wheel on {name} at ({x},{y})")
        res = lua(
            rcon,
            f"return {{result = remote.call('entities','set_recipe','{name}',{{x={x},y={y}}},'iron-gear-wheel',true)}}",
        )
        cfg_err = res.get("error")
        if cfg_err:
            finding(f"entities.set_recipe errored: {str(cfg_err)[:300]}")
        pl = wait_for(
            lambda p: p.get("event_type") == "entity_operation"
            and p.get("op") == "configuration_changed"
            and p.get("name") == name,
            timeout=12.0,
        )
        if pl is None:
            finding("NO UDP configuration_changed payload within 12s for set_recipe")
        n = sync.flush_pending()
        rows = me_row(con, name, x, y)
        raw_has_recipe = bool(rows) and rows[0][4] is not None and "iron-gear-wheel" in rows[0][4]
        asm_comp = con.execute("SELECT * FROM assembler").fetchall()
        game_recipe = lua(
            rcon,
            f"""
            local e = game.surfaces[1].find_entities_filtered{{name='{name}',
                position={{x={x},y={y}}}, radius=0.2}}[1]
            if not e then return {{error='asm not found'}} end
            local r = e.get_recipe()
            return {{recipe = r and r.name or 'none'}}
            """,
        )
        results["phases"]["4d_config"] = {
            "set_recipe_error": cfg_err,
            "udp_payload_seen": pl is not None,
            "udp_payload": pl,
            "ops_flushed": n,
            "game_recipe": game_recipe.get("recipe"),
            "map_entity_raw_data_has_recipe": raw_has_recipe,
            "assembler_component_rows": asm_comp,
            "pass": pl is not None and raw_has_recipe,
        }
        hb(f"mutation 4d done: udp={'yes' if pl else 'NO'}, game recipe="
           f"{game_recipe.get('recipe')}, raw_data has recipe={raw_has_recipe}")

        # component + derived table verdict data after all mutations
        results["phases"]["component_counts_final"] = {
            t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in COMPONENT_TABLES
        }
        existing = table_names(con)
        results["phases"]["derived_tables_exist_in_stack_a"] = {
            t: (t in existing) for t in DERIVED_TABLES
        }
        results["rebuild_callbacks"] = len(rebuilds)
        results["udp_payload_count"] = len(captured)

    finally:
        hb(f"udp teardown: restoring mod snapshot UDP port to {old_port_val}")
        try:
            lua(rcon, f"remote.call('snapshot','set_udp_port', {old_port_val}) return {{ok=true}}")
        except Exception as e:
            finding(f"FAILED to restore UDP port {old_port_val}: {e}")
        await sync.stop()
        await dispatcher.stop()
        hb("udp teardown done")


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", default="client", help="client or server_N")
    configure_instance(ap.parse_args().instance)

    hb("=== check_L1_sync start ===")

    # --- 0. smoke ritual -------------------------------------------------------
    hb("smoke: connecting RCON, verifying interfaces")
    rcon = RCONClient(RCON_HOST, RCON_PORT, RCON_PASS)
    rcon.send_command("/c rcon.print('ping')")
    assert "ping" in rcon.send_command("/c rcon.print('ping')"), "smoke ping failed"
    ifaces = json.loads(
        rcon.send_command("/c rcon.print(helpers.table_to_json(remote.interfaces))")
    )
    needed = ["test_ground", "snapshot", "map", "entities", "agent"]
    missing = [i for i in needed if i not in ifaces]
    if missing:
        hb(f"SMOKE FAIL: missing interfaces {missing}")
        print(f"BLOCKED: missing interfaces {missing}")
        return 2
    tick = lua(rcon, "return {tick=game.tick}").get("tick")
    results["smoke"] = {"tick": tick, "interfaces": sorted(ifaces.keys())}
    hb(f"smoke ok: tick={tick}")

    # --- 1. clear work area ------------------------------------------------------
    hb(f"phase 1: clearing work area chunk {WORK_CHUNK} (tiles 64..96)")
    res = lua(rcon, f"return remote.call('test_ground','clear_area',{bounds_lua(WORK)},true)")
    if not res.get("success"):
        raise RuntimeError(f"clear_area failed: {res}")
    hb(f"phase 1 done: cleared {res.get('cleared_count')} entities")

    # --- 2. build rig + snapshot + initial load ---------------------------------
    hb("phase 2: placing rig (ore patch, drill, 3 belts, inserter, chest, assembler)")
    rname, cx, cy, size, amount = ORE
    res = lua(
        rcon,
        f"return remote.call('test_ground','place_resource_patch','{rname}',{cx},{cy},{size},{amount})",
    )
    if not res.get("success"):
        raise RuntimeError(f"place_resource_patch failed: {res}")
    for name, x, y, d in RIG:
        res = lua(
            rcon,
            f"return remote.call('test_ground','place_entity','{name}',{{x={x},y={y}}},{d},'player')",
        )
        if not res.get("success"):
            raise RuntimeError(f"place {name}@({x},{y}) failed: {res}")
    ents = census(rcon)
    if len(ents) != len(RIG):
        raise RuntimeError(f"rig census mismatch: expected {len(RIG)}, got {len(ents)}: {ents}")
    hb(f"phase 2 rig placed, {len(ents)} entities verified present")

    hb("phase 2: re_snapshot_area + waiting for fresh entities-init.jsonl")
    t_snap = time.time()
    res = lua(rcon, f"return remote.call('map','re_snapshot_area',{bounds_lua(WORK)},100)")
    if not res.get("success"):
        raise RuntimeError(f"re_snapshot_area failed: {res}")
    init_file = SNAP_ROOT / "factoryverse/snapshots" / str(WORK_CHUNK[0]) / str(WORK_CHUNK[1]) / "entities-init.jsonl"
    deadline = time.time() + 60
    fresh = False
    while time.time() < deadline:
        if init_file.exists() and init_file.stat().st_mtime >= t_snap - 1:
            content = init_file.read_text()
            if "assembling-machine-1" in content and "burner-mining-drill" in content:
                fresh = True
                break
        time.sleep(1.0)
    if not fresh:
        raise RuntimeError(f"snapshot init file not refreshed within 60s: {init_file}")
    hb("phase 2: snapshot files fresh; loading via SnapshotLoader into in-memory SnapshotDatabase")

    db = SnapshotDatabase(None)  # in-memory, like docs say is ok
    db.ensure_schema()
    con = db.connection
    loader = SnapshotLoader(db=con, snapshot_dir=SNAP_ROOT)
    load_result = loader.load_all()
    initial = db_state(con)
    results["initial_load"] = {
        "entity_count": load_result.entity_count,
        "resource_count": load_result.resource_count,
        "ghost_count": load_result.ghost_count,
        "last_sequence": load_result.last_sequence,
        "db_state": {
            "counts": initial["counts"],
            "work_map_entity": initial["work_map_entity"],
            "component_counts": {t: len(initial["component_rows"][t])
                                 if isinstance(initial["component_rows"][t], list) else initial["component_rows"][t]
                                 for t in COMPONENT_TABLES},
        },
    }
    (ART / "initial_db_state.json").write_text(json.dumps(initial, indent=2, default=str))
    hb(f"phase 2 done: loaded entities={load_result.entity_count}, "
       f"work map_entity rows={len(initial['work_map_entity'])}, "
       f"component counts={results['initial_load']['db_state']['component_counts']}, "
       f"last_sequence={load_result.last_sequence}")

    # --- 3+4. live UDP sync phase ----------------------------------------------
    asyncio.run(live_phase(rcon, con, initial_sequence=0))

    # --- 5. final census parity ---------------------------------------------------
    hb("phase 5: final census parity (game find_entities_filtered vs map_entity)")
    game_ents = census(rcon)
    game_set = {(e["name"], round(float(e["x"]), 2), round(float(e["y"]), 2)) for e in game_ents}
    rows = con.execute(
        """SELECT entity_name, position_x, position_y FROM map_entity
           WHERE position_x >= ? AND position_x < ? AND position_y >= ? AND position_y < ?""",
        [WORK["left_top"]["x"], WORK["right_bottom"]["x"],
         WORK["left_top"]["y"], WORK["right_bottom"]["y"]],
    ).fetchall()
    db_set = {(r[0], round(float(r[1]), 2), round(float(r[2]), 2)) for r in rows}
    parity = {
        "game_count": len(game_set),
        "db_count": len(db_set),
        "only_in_game": sorted(game_set - db_set),
        "only_in_db": sorted(db_set - game_set),
        "exact_match": game_set == db_set,
    }
    results["census_parity"] = parity
    hb(f"phase 5 done: game={len(game_set)} db={len(db_set)} exact_match={parity['exact_match']}")

    # final DB dump artifacts
    final = db_state(con)
    (ART / "final_db_state.json").write_text(json.dumps(final, indent=2, default=str))
    for t in ["map_entity"] + COMPONENT_TABLES:
        try:
            con.execute(f"COPY (SELECT * FROM {t}) TO '{ART}/final_{t}.csv' (HEADER)")
        except Exception:
            pass

    # --- 6. cleanup ----------------------------------------------------------------
    hb("phase 6: cleanup — clearing work area")
    res = lua(rcon, f"return remote.call('test_ground','clear_area',{bounds_lua(WORK)},true)")
    hb(f"phase 6 done: cleared {res.get('cleared_count')} entities; no agents were created")

    (ART / "results.json").write_text(json.dumps(results, indent=2, default=str))
    hb("=== check_L1_sync end ===")

    print("\n========== SUMMARY ==========")
    print(json.dumps({k: v for k, v in results.items() if k != "phases"}, indent=2, default=str)[:2000])
    for k, v in results["phases"].items():
        p = v.get("pass") if isinstance(v, dict) else None
        print(f"{k}: pass={p}" if p is not None else f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
