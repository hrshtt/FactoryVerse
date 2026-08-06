#!/usr/bin/env python3
"""Certification check L1.14 — snapshot power reader is side-effect-free
(GLOBAL-NET-1).

The bug (found live 2026-07-11, terra-pro run): fv_snapshot's
Power.lua `get_global_power_statistics` called
`surface.create_global_electric_network()` whenever stats were missing —
on its nth_tick(300) timer. A surface with a global electric network
powers EVERY electric entity on it with no poles (Fulgora mechanic), so
the stats reader silently rewrote game physics on every snapshot-enabled
server within ~300 ticks of boot.

Phases (B–D mutate; run in an empty lab-grid cell, serially):
  A. static: deployed fv_snapshot mod contains no
     create_global_electric_network call; repo source matches.
  B. baseline: has_global_electric_network == false and STAYS false
     across >= 2 nth_tick(300) windows (the old code recreated it here).
  C. semantics A/B (this is also the executed verification of the
     "global net powers poleless entities" claim from the run report):
     poleless EEI + assembler rig -> assembler no_power;
     create_global_electric_network() -> assembler leaves no_power and
     shares the EEI's electric_network_id; the mod reader must NOT
     destroy the net across a 300-tick window (read-only both ways).
  D. destroy_global_electric_network() -> assembler back to no_power;
     has_global stays false across >= 2 more windows.
  E. cleanup: destroy rig, map.re_snapshot_area(cell bounds).

Run:  uv run python scripts/certification/check_L1_14.py --instance server_0
Exit: 0 PASS, 1 FAIL, 2 BLOCKED
"""

from __future__ import annotations

import datetime
import json
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from factorio_rcon import RCONClient  # noqa: E402

from FactoryVerse.infra.instance_manager import FactorioInstanceManager  # noqa: E402

DATE = datetime.datetime.now().strftime("%Y-%m-%d")
ART = REPO / ".fv-output" / "certification" / DATE / "L1.14"
ART.mkdir(parents=True, exist_ok=True)
PROGRESS = ART / "progress.log"

RIG_CELL = 60  # far empty cell; overridable via --cell

results: dict = {"check": "L1.14", "findings": []}


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


def probe(rcon) -> dict:
    return lua(rcon, "return {tick=game.tick, has_global=game.surfaces[1].has_global_electric_network}")


def wait_past_windows(rcon, n_windows: int, expect_has_global: bool, label: str) -> tuple[bool, dict]:
    """Wait until game.tick crosses n_windows more nth_tick(300) boundaries,
    polling has_global; returns (held, last_probe)."""
    p0 = probe(rcon)
    target = ((p0["tick"] // 300) + n_windows) * 300 + 30
    hb(f"{label}: tick {p0['tick']} -> waiting past tick {target} "
       f"(expect has_global=={expect_has_global} throughout)")
    while True:
        time.sleep(2)
        p = probe(rcon)
        if "error" in p:
            return False, p
        if p["has_global"] != expect_has_global:
            return False, p
        if p["tick"] >= target:
            return True, p


def finish(status: str, code: int) -> int:
    results["status"] = status
    (ART / "results.json").write_text(json.dumps(results, indent=2, default=str))
    hb(f"=== check_L1_14 end: {status} ===")
    print(f"\nSTATUS: {status}")
    print(f"ARTIFACTS: {ART}")
    return code


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", default="server_0", help="client or server_N")
    ap.add_argument("--cell", type=int, default=RIG_CELL, help="lab-grid cell for the rig")
    args = ap.parse_args()

    hb(f"=== check_L1_14 start (instance={args.instance}, cell={args.cell}) ===")

    # --- A. static guard on deployed + repo mod source -------------------------
    repo_src = REPO / "src" / "fv_snapshot" / "game_state" / "Power.lua"
    deployed = (
        Path.home() / "Library" / "Application Support" / "factorio" / "mods"
        / "fv_snapshot_0.1.0" / "game_state" / "Power.lua"
    )
    static = {}
    for label, p in (("repo", repo_src), ("deployed", deployed)):
        if not p.exists():
            finding(f"static: {label} Power.lua missing at {p}")
            return finish("BLOCKED", 2)
        text = p.read_text()
        calls = re.findall(r"create_global_electric_network\s*\(", text)
        static[label] = {"path": str(p), "create_calls": len(calls)}
        if calls:
            finding(f"static: {label} Power.lua still calls create_global_electric_network")
    results["static"] = static
    if any(v["create_calls"] for v in static.values()):
        return finish("FAIL", 1)
    hb("A static ok: no create_global_electric_network call in repo or deployed mod")

    # --- smoke ------------------------------------------------------------------
    if args.instance == "client":
        inst = FactorioInstanceManager.get_client()
    else:
        inst = FactorioInstanceManager.get_server(int(args.instance.split("_")[1]))
    results["instance"] = inst.name
    try:
        rcon = RCONClient(inst.rcon_host, inst.rcon_port, inst.rcon_password)
        rcon.send_command("/c rcon.print('ping')")
        assert "ping" in rcon.send_command("/c rcon.print('ping')")
        ifaces = json.loads(rcon.send_command(
            "/c rcon.print(helpers.table_to_json(remote.interfaces))"))
    except Exception as e:
        print(f"BLOCKED: no RCON at {inst.rcon_host}:{inst.rcon_port} ({e})")
        return finish("BLOCKED", 2)
    missing = [i for i in ("snapshot", "map", "lab_grid") if i not in ifaces]
    if missing:
        finding(f"missing interfaces {missing} (lab_grid scenario required)")
        return finish("BLOCKED", 2)

    # --- B. baseline: has_global false and holds across 2 windows ---------------
    p0 = probe(rcon)
    results["baseline"] = p0
    if p0.get("has_global"):
        finding(f"baseline: has_global already TRUE at tick {p0['tick']} — "
                f"something created a global net on this boot (old mod deployed, "
                f"or another writer)")
        return finish("FAIL", 1)
    held, p = wait_past_windows(rcon, 2, False, "B baseline hold")
    results["baseline_hold"] = p
    if not held:
        finding(f"baseline hold BROKEN: {p} — reader recreated the global net")
        return finish("FAIL", 1)
    hb(f"B ok: has_global false held through 2 windows (tick {p['tick']})")

    # --- C. semantics rig --------------------------------------------------------
    cell_bounds = lua(rcon, f"return remote.call('lab_grid','get_cell_bounds',{args.cell})")
    if "error" in cell_bounds:
        finding(f"get_cell_bounds({args.cell}) failed: {cell_bounds}")
        return finish("BLOCKED", 2)
    results["cell_bounds"] = cell_bounds
    lt = cell_bounds.get("left_top") or cell_bounds.get("lt") or {}
    cx = (lt.get("x", 0)) + 8
    cy = (lt.get("y", 0)) + 8
    hb(f"C rig: EEI at ({cx},{cy}), assembler at ({cx + 6},{cy}), no poles, cell {args.cell}")

    rig = lua(rcon, f"""
      local s = game.surfaces[1]
      local eei = s.create_entity{{name='electric-energy-interface',
        position={{x={cx}, y={cy}}}, force='player'}}
      if not eei then return {{error='EEI create failed'}} end
      eei.power_production = 10000000/60
      eei.electric_buffer_size = 10000000
      eei.energy = 10000000
      local asm = s.create_entity{{name='assembling-machine-1',
        position={{x={cx + 6}, y={cy}}}, force='player'}}
      if not asm then return {{error='assembler create failed'}} end
      asm.set_recipe('iron-gear-wheel')
      asm.insert{{name='iron-plate', count=100}}
      return {{ok=true}}
    """)
    if rig.get("error"):
        finding(f"rig build failed: {rig}")
        return finish("BLOCKED", 2)

    def rig_state():
        return lua(rcon, f"""
          local s = game.surfaces[1]
          local names = {{}}
          for k, v in pairs(defines.entity_status) do names[v] = k end
          local eei = s.find_entities_filtered{{name='electric-energy-interface',
            position={{x={cx}, y={cy}}}, radius=2}}[1]
          local asm = s.find_entities_filtered{{name='assembling-machine-1',
            position={{x={cx + 6}, y={cy}}}, radius=2}}[1]
          if not (eei and asm) then return {{error='rig entity missing'}} end
          return {{tick=game.tick, has_global=s.has_global_electric_network,
            asm_status=names[asm.status] or asm.status,
            eei_net=eei.electric_network_id, asm_net=asm.electric_network_id}}
        """)

    time.sleep(1)
    pre = rig_state()
    results["c_pre_net"] = pre
    hb(f"C pre-net rig state: {pre}")
    if pre.get("asm_status") != "no_power":
        finding(f"pre-net assembler status is {pre.get('asm_status')!r}, expected no_power "
                f"— poleless consumer is drawing power with NO global net?!")
        # keep going; cleanup at end, but this is a FAIL
    ok_c1 = pre.get("asm_status") == "no_power"

    created = lua(rcon, "game.surfaces[1].create_global_electric_network() return {ok=true}")
    time.sleep(2)
    post = rig_state()
    results["c_post_net"] = post
    hb(f"C post-net rig state: {post}")
    ok_c2 = (
        post.get("has_global") is True
        and post.get("asm_status") != "no_power"
        and post.get("eei_net") is not None
        and post.get("eei_net") == post.get("asm_net")
    )
    if not ok_c2:
        finding(f"semantics A/B failed on create: {post} (expected shared network id "
                f"and assembler leaving no_power)")

    # mod reader must not destroy/alter the net either
    held_c, pc = wait_past_windows(rcon, 1, True, "C reader-passivity hold (net present)")
    results["c_hold"] = pc
    if not held_c:
        finding(f"reader destroyed/lost the global net while it existed: {pc}")

    # --- D. destroy -> no_power; stays destroyed --------------------------------
    lua(rcon, "game.surfaces[1].destroy_global_electric_network() return {ok=true}")
    time.sleep(2)
    postd = rig_state()
    results["d_post_destroy"] = postd
    hb(f"D post-destroy rig state: {postd}")
    ok_d1 = postd.get("has_global") is False and postd.get("asm_status") == "no_power"
    if not ok_d1:
        finding(f"post-destroy state wrong: {postd} (expected has_global=false, no_power)")
    held_d, pd = wait_past_windows(rcon, 2, False, "D destroyed hold")
    results["d_hold"] = pd
    if not held_d:
        finding(f"THE BUG: global net came back after destroy: {pd}")

    # --- E. cleanup ---------------------------------------------------------------
    hb("E cleanup: destroying rig, re_snapshot_area on cell")
    cleanup = lua(rcon, f"""
      local s = game.surfaces[1]
      local n = 0
      for _, e in pairs(s.find_entities_filtered{{
          name={{'electric-energy-interface','assembling-machine-1'}},
          area={{{{{cx - 4},{cy - 4}}},{{{cx + 10},{cy + 4}}}}}}}) do
        e.destroy(); n = n + 1
      end
      return {{destroyed=n}}
    """)
    results["cleanup"] = cleanup
    lt_, rb_ = cell_bounds["left_top"], cell_bounds["right_bottom"]
    resnap = lua(rcon, (
        "return remote.call('map','re_snapshot_area',"
        f"{{left_top={{x={lt_['x']},y={lt_['y']}}},"
        f"right_bottom={{x={rb_['x']},y={rb_['y']}}}}},50)"
    ))
    results["cleanup_resnap"] = resnap
    hb(f"E cleanup done: {cleanup} resnap={resnap}")

    ok = ok_c1 and ok_c2 and held_c and ok_d1 and held_d
    print("\n========== SUMMARY ==========")
    print(json.dumps(results, indent=2, default=str))
    return finish("PASS" if ok else "FAIL", 0 if ok else 1)


if __name__ == "__main__":
    sys.exit(main())
