#!/usr/bin/env python3
"""Certification check L1.15 — eval-path vision is LIVE (DB-VISION-1).

The bug (terra-pro run 2026-07-11, docs/runs/): the agent's execute_duckdb
saw `[]` from map_entity for its own 40-entity standing factory ALL RUN,
while water/resource init data was present. Root cause (code + console-log
confirmed 2026-07-12): `tier4_runtime._load_remote_view` passed
`udp_dispatcher=None` believing RemoteView falls back to a global
dispatcher — it doesn't (load() sets _sync=None; start() logs "sync
disabled" and returns). Second layer: the only dispatcher that existed
bound the CLIENT snapshot port (34500) while server_0 ops arrive on 34400
(the only socat-forwarded snapshot port). Vision on the eval path was a
boot-time photograph.

This check drives the REAL eval stack (EXTERNAL-mode Environment, tiers
1-4, FULL variant — the exact stack `fv eval` composes) and asserts:

  S. structural: after tier4 init, RemoteView has a live SyncService and
     its dispatcher is bound to the instance's snapshot port.
  1. allocate a lab-grid cell via orchestrator._allocate_cell (run_task's
     exact call, includes honest wait + post-allocation reload).
  2. baseline: marker entity absent from map_entity (anti-vacuity).
  3. place a marker entity in-cell via RCON `create_entity{raise_built}`
     → the op must appear in remote_view.query(map_entity) WITHOUT any
     reload/rebuild call, within TIMEOUT (UDP op → SyncService apply).
  4. destroy the marker (`raise_destroyed`) → row must disappear, again
     with no manual reload.
  5. release the cell (reset=True re-snapshots — playbook §5 cleanup).

Run:  uv run python scripts/certification/check_L1_15.py --instance server_0
Exit: 0 PASS, 1 FAIL, 2 BLOCKED
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

from FactoryVerse.infra.instance_manager import FactorioInstanceManager  # noqa: E402

DATE = datetime.datetime.now().strftime("%Y-%m-%d")
ART = REPO / ".fv-output" / "certification" / DATE / "L1.15"
ART.mkdir(parents=True, exist_ok=True)
PROGRESS = ART / "progress.log"

MARKER = "iron-chest"
SYNC_TIMEOUT_S = 30.0

results: dict = {"check": "L1.15", "findings": []}


def hb(msg: str) -> None:
    line = f"{datetime.datetime.now().isoformat(timespec='seconds')} {msg}"
    with open(PROGRESS, "a") as f:
        f.write(line + "\n")
    print(f"[hb] {line}", flush=True)


def finding(msg: str) -> None:
    results["findings"].append(msg)
    print(f"[FINDING] {msg}", flush=True)


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


def finish(status: str, code: int) -> int:
    results["status"] = status
    (ART / "results.json").write_text(json.dumps(results, indent=2, default=str))
    hb(f"=== check_L1_15 end: {status} ===")
    print(f"\nSTATUS: {status}")
    print(f"ARTIFACTS: {ART}")
    return code


def marker_rows(remote_view, x: float, y: float):
    return remote_view.execute_raw(
        f"SELECT entity_name, position_x, position_y FROM map_entity "
        f"WHERE entity_name = '{MARKER}' "
        f"AND position_x BETWEEN {x - 0.6} AND {x + 0.6} "
        f"AND position_y BETWEEN {y - 0.6} AND {y + 0.6}"
    )


async def run(instance: str) -> int:
    from FactoryVerse.environment.environment import Environment, Tier
    from FactoryVerse.environment.config import (
        EnvironmentConfig, ExecutionMode, InfraConfig, InfraMode,
        PythonConfig, RuntimeConfig, RuntimeVariant, SettingsConfig)

    inst = FactorioInstanceManager.get_server(int(instance.split("_")[1]))
    rcon = RCONClient(inst.rcon_host, inst.rcon_port, inst.rcon_password)
    rcon.send_command("/c rcon.print('ping')")
    ifaces = json.loads(rcon.send_command(
        "/c rcon.print(helpers.table_to_json(remote.interfaces))"))
    if "lab_grid" not in ifaces:
        finding("lab_grid interface missing — wrong scenario")
        return finish("BLOCKED", 2)

    hb("phase 0: building REAL Environment stack (EXTERNAL, tiers 1-4, FULL)")
    env = Environment(config=EnvironmentConfig(
        tier1=InfraConfig(mode=InfraMode.EXTERNAL),
        tier2=SettingsConfig(scenario="lab-grid"),
        tier3=PythonConfig(instance=instance),
        tier4=RuntimeConfig(variant=RuntimeVariant.FULL,
                            agent_id="agent_1",
                            execution_mode=ExecutionMode.INPROCESS),
    ))
    cell = None
    try:
        await env.initialize(up_to=Tier.RUNTIME)
        tier4 = env.tier4
        orch = env.orchestrator
        rv = tier4.remote_view if hasattr(tier4, "remote_view") else tier4._remote_view
        if rv is None:
            finding("tier4 has no RemoteView after RUNTIME init")
            return finish("BLOCKED", 2)

        # --- S. structural: sync service exists and dispatcher on snapshot port
        expected_port = env.config.infra_config.get_snapshot_port(instance)
        sync = rv._sync
        disp = rv._udp_dispatcher
        results["structural"] = {
            "expected_snapshot_port": expected_port,
            "sync_service_present": sync is not None,
            "dispatcher_port": getattr(disp, "port", None),
            "dispatcher_running": bool(disp and disp.is_running()),
        }
        hb(f"S: {results['structural']}")
        if sync is None:
            finding("DB-VISION-1 STILL PRESENT: RemoteView has no SyncService "
                    "on the eval path (udp_dispatcher was None)")
            return finish("FAIL", 1)
        if getattr(disp, "port", None) != expected_port:
            finding(f"sync dispatcher bound to {getattr(disp, 'port', None)}, "
                    f"expected snapshot port {expected_port} — ops arrive on "
                    f"the forwarded port only")
            return finish("FAIL", 1)

        # --- 1. allocate cell through the orchestrator (run_task's call) ------
        hb("phase 1: orchestrator._allocate_cell")
        cell = await orch._allocate_cell(None)
        if cell is None:
            finding("_allocate_cell returned None")
            return finish("BLOCKED", 2)
        b = lua(rcon, f"return remote.call('lab_grid','get_cell_bounds',{cell})")
        force = lua(rcon, f"return remote.call('lab_grid','get_cell_force',{cell})")
        force_name = force if isinstance(force, str) else force.get("ok") or "player"
        lt = b["left_top"]
        mx, my = lt["x"] + 20.5, lt["y"] + 20.5
        results["cell"] = {"index": cell, "bounds": b, "force": force_name,
                          "marker_pos": [mx, my]}
        hb(f"phase 1 done: cell {cell}, marker target ({mx},{my}), force {force_name}")

        # --- 2. baseline: marker absent (anti-vacuity both ways) ---------------
        base = marker_rows(rv, mx, my)
        results["baseline_rows"] = base
        if base:
            finding(f"baseline already has marker rows at target: {base}")
            return finish("BLOCKED", 2)
        # DB must be non-trivially loaded (cell init data present) or the
        # "live" claim is vacuous
        n_water = rv.execute_raw("SELECT count(*) FROM water_tile")[0][0]
        n_res = rv.execute_raw("SELECT count(*) FROM resource_tile")[0][0]
        results["baseline_load"] = {"water_tiles": n_water, "resource_tiles": n_res}
        if (n_water or 0) == 0 and (n_res or 0) == 0:
            finding("VACUOUS-RISK: DB has zero water AND zero resource tiles "
                    "after allocation — initial load itself is broken")
            return finish("FAIL", 1)

        # --- 3. place marker via engine event path; NO manual reload -----------
        hb(f"phase 3: create_entity {MARKER} raise_built at ({mx},{my})")
        placed = lua(rcon, f"""
          local s = game.surfaces[1]
          local e = s.create_entity{{name='{MARKER}', position={{x={mx}, y={my}}},
            force='{force_name}', raise_built=true}}
          if not e then return {{error='create failed'}} end
          return {{tick=game.tick, x=e.position.x, y=e.position.y}}
        """)
        if placed.get("error"):
            finding(f"marker placement failed: {placed}")
            return finish("BLOCKED", 2)
        results["placed"] = placed

        t0 = time.time()
        seen = None
        while time.time() - t0 < SYNC_TIMEOUT_S:
            rows = marker_rows(rv, mx, my)
            if rows:
                seen = rows
                break
            await asyncio.sleep(0.5)
        dt_appear = round(time.time() - t0, 2)
        results["appear"] = {"rows": seen, "seconds": dt_appear}
        hb(f"phase 3 result: rows={seen} after {dt_appear}s")
        if not seen:
            finding(f"LIVE-SYNC FAIL: marker never appeared in map_entity within "
                    f"{SYNC_TIMEOUT_S}s (no reload issued — the DB-VISION-1 class)")
            return finish("FAIL", 1)

        # --- 4. destroy -> row disappears, still no reload ---------------------
        hb("phase 4: destroy marker (raise_destroyed)")
        destroyed = lua(rcon, f"""
          local s = game.surfaces[1]
          local e = s.find_entities_filtered{{name='{MARKER}',
            position={{x={mx}, y={my}}}, radius=1}}[1]
          if not e then return {{error='marker not found in engine'}} end
          e.destroy{{raise_destroy=true}}
          return {{tick=game.tick}}
        """)
        results["destroyed"] = destroyed
        t0 = time.time()
        gone = False
        while time.time() - t0 < SYNC_TIMEOUT_S:
            if not marker_rows(rv, mx, my):
                gone = True
                break
            await asyncio.sleep(0.5)
        dt_gone = round(time.time() - t0, 2)
        results["disappear"] = {"gone": gone, "seconds": dt_gone}
        hb(f"phase 4 result: gone={gone} after {dt_gone}s")
        if not gone:
            finding(f"removal never synced within {SYNC_TIMEOUT_S}s")
            return finish("FAIL", 1)

        return finish("PASS", 0)
    finally:
        try:
            if cell is not None and env.orchestrator is not None:
                hb(f"cleanup: releasing cell {cell} (reset=True re-snapshots)")
                await env.orchestrator._release_cell(cell, reset=True)
        except Exception as e:  # noqa: BLE001
            hb(f"cleanup release_cell failed: {e}")
        try:
            await env.shutdown()
        except Exception as e:  # noqa: BLE001
            hb(f"env shutdown failed: {e}")


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", default="server_0")
    args = ap.parse_args()
    hb(f"=== check_L1_15 start (instance={args.instance}) ===")
    try:
        return asyncio.run(run(args.instance))
    except Exception as e:  # noqa: BLE001
        import traceback
        finding(f"unhandled: {type(e).__name__}: {e}")
        (ART / "traceback.txt").write_text(traceback.format_exc())
        return finish("BLOCKED", 2)


if __name__ == "__main__":
    sys.exit(main())
