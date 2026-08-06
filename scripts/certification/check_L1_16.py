#!/usr/bin/env python3
"""Certification check L1.16 — the NEW per-network power sampler (contract C1).

Certifies fv_snapshot Power.lua `M._on_nth_tick_power_networks_sample` (the
per-network sampler that writes factoryverse/snapshots/power_networks.jsonl)
against ground truth on a LIVE server_0. This is the executed verification of
the frozen C1 contract (scratchpad/power-impl-contracts.md).

Isolation: works ONLY in lab-grid cell 54. Rigs use force 'player' and are
built via create_entity WITHOUT raise_built ON PURPOSE — this check exercises
the SAMPLER, which SCANS the surface (find_entities_filtered) and must see
RCON-built entities regardless of whether on_built events fired. All assertions
are filtered to networks whose anchor pole lies inside cell 54, so concurrent
rigs in cells 55 / 60+ (other agents) are recorded as "foreign" and ignored.

Phases:
  A. Static: repo AND deployed Power.lua contain the sampler and NO
     create_global_electric_network / destroy_global_electric_network call in
     CODE (comment mentions ignored).
  B. Heartbeat baseline: cell 54 empty -> new jsonl line each 300-tick window,
     tick-monotonic, our-cell networks == [] (foreign recorded).
  C. Two-network truth: rig A (EEI 10MW / 10MJ buffer, full) + rig B (EEI 30kW
     / 30kJ buffer) >=40 tiles apart. Newest steady-state line has exactly 2
     of-our-cell networks: pole_count=1, correct anchor name+pos, member>=3,
     rig A consumption ~77500 +/-10% (active craft) with production matching,
     rig B consumption clamped ~30000 +/-20% (low_power). production keyed
     'electric-energy-interface'.
  D. Merge: bridge A->B with small poles at 7-tile spacing -> 1 of-our-cell
     network, pole_count == 2 + bridge_count, anchor deterministic across two
     consecutive samples.
  E. Split: destroy bridge poles -> 2 networks again. RECORD (not assert)
     network_id lineage before/after (ids are ephemeral — PWR-NETID-1).
  F. Ingestion (boot-load path): SnapshotDatabase(None)+SnapshotLoader.load_all
     against .fv-output/server_0; power_samples rows == distinct jsonl ticks;
     power_networks rows for the phase-C 2-network tick match the jsonl values
     (spot-check production_w/consumption_w + anchor columns). Read-only.
  G. Passivity regression: has_global_electric_network false at every probe.
  H. Cleanup: destroy all created entities, re_snapshot_area cell 54, verify
     non-resource count back to 0, final heartbeat line still flowing.

Run:  uv run python scripts/certification/check_L1_16.py --instance server_0
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
ART = REPO / ".fv-output" / "certification" / DATE / "L1.16"
ART.mkdir(parents=True, exist_ok=True)
PROGRESS = ART / "progress.log"

CELL = 54  # HARD RULE: work ONLY here (55 and 60+ belong to other agents)
WINDOW = 300  # nth_tick(300) sampler cadence

# Numeric tolerances (also recorded into results.json)
TOL = {
    "rigA_consumption_w_expected": 77500.0,
    "rigA_consumption_rel_tol": 0.10,  # +/-10% active craft
    "rigB_consumption_w_expected": 30000.0,
    "rigB_consumption_rel_tol": 0.20,  # +/-20% low_power clamp
    "production_matches_consumption_rel_tol": 0.15,
    "anchor_pos_epsilon": 0.05,
    "bridge_spacing_tiles": 7.0,
}

results: dict = {
    "check": "L1.16",
    "contract": "C1 (per-network power sampler)",
    "cell": CELL,
    "raise_built": False,
    "raise_built_note": (
        "rigs built via create_entity WITHOUT raise_built ON PURPOSE — this "
        "check tests the sampler's surface SCAN, which must see RCON-built "
        "entities regardless of whether on_built events fired"
    ),
    "tolerances": TOL,
    "phases": {},
    "has_global_probes": [],
    "findings": [],
}


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


def probe_has_global(rcon, label: str) -> bool:
    r = lua(rcon, "return {tick=game.tick, has_global=game.surfaces[1].has_global_electric_network}")
    entry = {"label": label, **r}
    results["has_global_probes"].append(entry)
    if r.get("has_global") is not False:
        finding(f"G passivity: has_global not False at {label}: {r}")
    return r.get("has_global") is False


# ---------------------------------------------------------------------------
# jsonl helpers
# ---------------------------------------------------------------------------
JSONL = REPO / ".fv-output" / "server_0" / "factoryverse" / "snapshots" / "power_networks.jsonl"


def read_jsonl_lines() -> list[dict]:
    if not JSONL.exists():
        return []
    out = []
    for ln in JSONL.read_text().splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            pass
    return out


CELL_BOUNDS: dict = {}


def in_cell(pos: dict) -> bool:
    lt = CELL_BOUNDS["left_top"]
    rb = CELL_BOUNDS["right_bottom"]
    return lt["x"] <= pos.get("x", 1e18) <= rb["x"] and lt["y"] <= pos.get("y", 1e18) <= rb["y"]


def our_nets(line: dict) -> list[dict]:
    """Networks whose anchor pole lies inside cell 54 (ours)."""
    return [n for n in (line.get("networks") or [])
            if in_cell((n.get("anchor_pole") or {}).get("position") or {})]


def foreign_nets(line: dict) -> list[dict]:
    return [n for n in (line.get("networks") or [])
            if not in_cell((n.get("anchor_pole") or {}).get("position") or {})]


def game_tick(rcon) -> int:
    r = lua(rcon, "return {tick=game.tick}")
    return int(r.get("tick", 0))


def wait_for_line_tick(rcon, min_tick: int, label: str, timeout_s: float = 60.0) -> dict | None:
    """Poll the jsonl until a line with tick >= min_tick is present; return it."""
    hb(f"{label}: waiting for jsonl line tick >= {min_tick}")
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        lines = read_jsonl_lines()
        cand = [ln for ln in lines if int(ln.get("tick", -1)) >= min_tick]
        if cand:
            last = cand[-1]
            return last
        time.sleep(2)
    finding(f"{label}: TIMEOUT waiting for jsonl tick >= {min_tick} (last file tick "
            f"{lines[-1].get('tick') if lines else 'none'})")
    return None


def finish(status: str, code: int) -> int:
    results["status"] = status
    (ART / "results.json").write_text(json.dumps(results, indent=2, default=str))
    hb(f"=== check_L1_16 end: {status} ===")
    print(f"\nSTATUS: {status}")
    print(f"ARTIFACTS: {ART}")
    return code


# ---------------------------------------------------------------------------
# Lua rig builder / probes
# ---------------------------------------------------------------------------
def build_rig(rcon, ex: float, ey: float, prod_j_per_tick: str, buffer_j: float) -> dict:
    """EEI + one small-electric-pole + assembling-machine-1(iron-gear-wheel,
    200 iron plates). Returns actual snapped positions and network ids."""
    # Compact row so the single small-electric-pole's 5x5 supply area (radius 2.5)
    # covers BOTH the 2x2 EEI (to its left) and the 3x3 assembler (to its right)
    # with a 2-tile overlap each. Edge-touching collision boxes are legal.
    #   EEI center ex        (2x2 -> occupies ex-1 .. ex+1)
    #   pole center ex+1.5   (supply ex-1 .. ex+4)
    #   asm center  ex+3.5   (3x3 -> occupies ex+2 .. ex+5, overlaps supply ex+2..ex+4)
    # electric_network_id is nil (JSON-omitted) for an entity outside every pole's
    # supply area — the caller treats a missing 'net' as "not connected".
    return lua(rcon, f"""
      local s = game.surfaces[1]
      local eei = s.create_entity{{name='electric-energy-interface',
        position={{x={ex}, y={ey}}}, force='player'}}
      if not eei then return {{error='EEI create failed'}} end
      eei.power_production = {prod_j_per_tick}
      eei.power_usage = 0
      eei.electric_buffer_size = {buffer_j}
      eei.energy = {buffer_j}
      local pole = s.create_entity{{name='small-electric-pole',
        position={{x={ex + 1.5}, y={ey}}}, force='player'}}
      if not pole then return {{error='pole create failed'}} end
      local asm = s.create_entity{{name='assembling-machine-1',
        position={{x={ex + 3.5}, y={ey}}}, force='player'}}
      if not asm then return {{error='assembler create failed'}} end
      asm.set_recipe('iron-gear-wheel')
      asm.insert{{name='iron-plate', count=200}}
      return {{
        eei = {{pos={{x=eei.position.x, y=eei.position.y}}, net=eei.electric_network_id}},
        pole = {{name=pole.name, pos={{x=pole.position.x, y=pole.position.y}}, net=pole.electric_network_id}},
        asm = {{pos={{x=asm.position.x, y=asm.position.y}}, net=asm.electric_network_id}},
      }}
    """)


def direct_flow_probe(rcon, pole_x: float, pole_y: float) -> dict:
    """Direct RCON get_flow_count on the pole at (pole_x,pole_y) — used to
    distinguish a sampler bug from engine timing when a wattage assert fails."""
    return lua(rcon, f"""
      local s = game.surfaces[1]
      local p = s.find_entities_filtered{{type='electric-pole',
        position={{x={pole_x}, y={pole_y}}}, radius=1}}[1]
      if not p then return {{error='pole not found'}} end
      local st = p.electric_network_statistics
      local FIVE = defines.flow_precision_index.five_seconds
      local out = {{network_id=p.electric_network_id, input={{}}, output={{}}}}
      for proto in pairs(st.input_counts) do
        out.input[proto] = st.get_flow_count{{name=proto, category='input', precision_index=FIVE}} * 60
      end
      for proto in pairs(st.output_counts) do
        out.output[proto] = st.get_flow_count{{name=proto, category='output', precision_index=FIVE}} * 60
      end
      return out
    """)


# ---------------------------------------------------------------------------
def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", default="server_0", help="client or server_N")
    args = ap.parse_args()

    hb(f"=== check_L1_16 start (instance={args.instance}, cell={CELL}) ===")

    # === A. static guard ====================================================
    repo_src = REPO / "src" / "fv_snapshot" / "game_state" / "Power.lua"
    deployed = (
        Path.home() / "Library" / "Application Support" / "factorio" / "mods"
        / "fv_snapshot_0.1.0" / "game_state" / "Power.lua"
    )
    FORBIDDEN = ("create_global_electric_network", "destroy_global_electric_network")
    SAMPLER = "_on_nth_tick_power_networks_sample"
    static = {}
    static_ok = True
    for label, p in (("repo", repo_src), ("deployed", deployed)):
        if not p.exists():
            finding(f"static: {label} Power.lua missing at {p}")
            results["phases"]["A_static"] = {"ok": False, "detail": f"{label} missing"}
            return finish("BLOCKED", 2)
        # strip Lua line-comments (everything after -- on a line) before scanning
        code_only = "\n".join(re.sub(r"--.*$", "", ln) for ln in p.read_text().splitlines())
        forbidden_hits = {f: len(re.findall(f + r"\s*\(", code_only)) for f in FORBIDDEN}
        has_sampler = SAMPLER in code_only
        static[label] = {
            "path": str(p),
            "forbidden_calls_in_code": forbidden_hits,
            "has_sampler": has_sampler,
        }
        if any(forbidden_hits.values()):
            finding(f"static: {label} Power.lua CALLS a forbidden global-net fn in code: {forbidden_hits}")
            static_ok = False
        if not has_sampler:
            finding(f"static: {label} Power.lua missing sampler {SAMPLER}")
            static_ok = False
    results["phases"]["A_static"] = {"ok": static_ok, **static}
    if not static_ok:
        return finish("FAIL", 1)
    hb("A ok: sampler present, no forbidden global-net calls in code (repo + deployed)")

    # === connect ============================================================
    if args.instance == "client":
        inst = FactorioInstanceManager.get_client()
    else:
        inst = FactorioInstanceManager.get_server(int(args.instance.split("_")[1]))
    results["instance"] = inst.name
    try:
        rcon = RCONClient(inst.rcon_host, inst.rcon_port, inst.rcon_password)
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

    cb = lua(rcon, f"return remote.call('lab_grid','get_cell_bounds',{CELL})")
    if "error" in cb or "left_top" not in cb:
        finding(f"get_cell_bounds({CELL}) failed: {cb}")
        return finish("BLOCKED", 2)
    CELL_BOUNDS.update(cb)
    results["cell_bounds"] = cb

    # verify cell empty of non-resource entities before we touch it
    empty = lua(rcon, f"""
      local b = remote.call('lab_grid','get_cell_bounds',{CELL})
      local s = game.surfaces[1]
      local es = s.find_entities_filtered{{area={{{{b.left_top.x,b.left_top.y}},{{b.right_bottom.x,b.right_bottom.y}}}}}}
      local n = 0; local names = {{}}
      for _, e in pairs(es) do
        if e.type ~= 'resource' and e.type ~= 'character' then
          n = n + 1; names[e.name] = (names[e.name] or 0) + 1
        end
      end
      return {{count=n, names=names}}
    """)
    results["cell_empty_precheck"] = empty
    if empty.get("count", -1) != 0:
        finding(f"cell {CELL} NOT empty of non-resource entities before start: {empty}")
        return finish("BLOCKED", 2)
    probe_has_global(rcon, "start")
    hb(f"connected; cell {CELL} bounds {cb}; cell empty confirmed")

    # === B. heartbeat baseline =============================================
    t0 = game_tick(rcon)
    base_line0 = read_jsonl_lines()
    base_last_tick0 = int(base_line0[-1]["tick"]) if base_line0 else -1
    # wait past 2 windows
    b_target = ((t0 // WINDOW) + 2) * WINDOW + 5
    b_lines_seen: list[dict] = []
    hb(f"B baseline: from tick {t0}, collecting jsonl lines through tick >= {b_target}")
    deadline = time.time() + 60
    while time.time() < deadline:
        lines = read_jsonl_lines()
        b_lines_seen = [ln for ln in lines if int(ln.get("tick", -1)) > base_last_tick0]
        if lines and int(lines[-1]["tick"]) >= b_target:
            break
        time.sleep(2)
    b_ticks = [int(ln["tick"]) for ln in b_lines_seen]
    monotonic = all(b_ticks[i] < b_ticks[i + 1] for i in range(len(b_ticks) - 1))
    spacing_ok = all(b_ticks[i + 1] - b_ticks[i] == WINDOW for i in range(len(b_ticks) - 1))
    foreign_seen = {}
    our_nonempty = []
    for ln in b_lines_seen:
        for fn in foreign_nets(ln):
            foreign_seen[fn.get("network_id")] = (fn.get("anchor_pole") or {})
        if our_nets(ln):
            our_nonempty.append(ln)
    b_ok = len(b_lines_seen) >= 2 and monotonic and spacing_ok and not our_nonempty
    results["phases"]["B_baseline"] = {
        "ok": b_ok,
        "new_lines": len(b_lines_seen),
        "ticks": b_ticks,
        "monotonic": monotonic,
        "spacing_300": spacing_ok,
        "our_cell_networks_empty": not our_nonempty,
        "foreign_networks_recorded": foreign_seen,
    }
    if foreign_seen:
        hb(f"B: FOREIGN networks present (other agents' cells) — recorded, filtered out: {list(foreign_seen)}")
    if not b_ok:
        finding(f"B baseline broken: lines={len(b_lines_seen)} monotonic={monotonic} "
                f"spacing300={spacing_ok} our_nonempty={our_nonempty}")
    probe_has_global(rcon, "after_B")
    hb(f"B done ok={b_ok}: {len(b_lines_seen)} new heartbeat line(s), monotonic={monotonic}")

    # === C. two-network truth ==============================================
    lt = cb["left_top"]
    ax, ay = lt["x"] + 15, lt["y"] + 20          # rig A base
    bx, by = ax + 45, ay                         # rig B base (45 tiles east, >=40)
    hb(f"C: building rig A EEI@({ax},{ay}) and rig B EEI@({bx},{by})")

    rigA = build_rig(rcon, ax, ay, "10000000/60", 10000000)
    rigB = build_rig(rcon, bx, by, "30000/60", 30000)
    results["phases"]["C_rigs"] = {"rigA": rigA, "rigB": rigB}
    if rigA.get("error") or rigB.get("error"):
        finding(f"C rig build failed: A={rigA} B={rigB}")
        return finish("BLOCKED", 2)
    # connectivity sanity: each rig's 3 entities must share one network id.
    # A missing/nil 'net' (JSON-omitted) means the entity is outside the pole's
    # supply area -> geometry problem, not a sampler bug.
    a_nets = {rigA["eei"].get("net"), rigA["pole"].get("net"), rigA["asm"].get("net")}
    b_nets = {rigB["eei"].get("net"), rigB["pole"].get("net"), rigB["asm"].get("net")}
    if None in a_nets or None in b_nets or len(a_nets) != 1 or len(b_nets) != 1:
        finding(f"C rig connectivity BROKEN (rig entities not in one network): "
                f"A nets={a_nets} B nets={b_nets} — geometry problem, not sampler")
        results["phases"]["C_rigs"]["connectivity"] = {"a_nets": list(a_nets), "b_nets": list(b_nets)}
        # cleanup then bail
        _cleanup(rcon)
        return finish("BLOCKED", 2)
    poleA = rigA["pole"]["pos"]
    poleB = rigB["pole"]["pos"]
    hb(f"C rigs built: poleA@{poleA} net{rigA['pole']['net']}, poleB@{poleB} net{rigB['pole']['net']}")
    probe_has_global(rcon, "after_build")

    # wait for a steady-state line at least 2 full windows past build
    build_tick = game_tick(rcon)
    c_min = ((build_tick // WINDOW) + 2) * WINDOW + 5
    c_line = wait_for_line_tick(rcon, c_min, "C steady-state", timeout_s=90)
    if c_line is None:
        _cleanup(rcon)
        return finish("FAIL", 1)
    c_our = our_nets(c_line)
    c_foreign = foreign_nets(c_line)
    results["phases"]["C_sample"] = {
        "tick": c_line["tick"],
        "our_network_count": len(c_our),
        "foreign_network_count": len(c_foreign),
        "our_networks": c_our,
        "raw_line": c_line,
    }
    c_ok = True
    if len(c_our) != 2:
        finding(f"C: expected exactly 2 of-our-cell networks, got {len(c_our)}: {c_our}")
        c_ok = False

    # match networks to rig A / rig B by anchor pole position
    def match(net_list, pole):
        for n in net_list:
            ap = (n.get("anchor_pole") or {}).get("position") or {}
            if abs(ap.get("x", 1e18) - pole["x"]) <= TOL["anchor_pos_epsilon"] and \
               abs(ap.get("y", 1e18) - pole["y"]) <= TOL["anchor_pos_epsilon"]:
                return n
        return None

    netA = match(c_our, poleA)
    netB = match(c_our, poleB)
    c_detail = {}
    for tag, net, pole, exp_c, tol_c in (
        ("rigA", netA, poleA, TOL["rigA_consumption_w_expected"], TOL["rigA_consumption_rel_tol"]),
        ("rigB", netB, poleB, TOL["rigB_consumption_w_expected"], TOL["rigB_consumption_rel_tol"]),
    ):
        d = {}
        if net is None:
            finding(f"C {tag}: no network with anchor at pole {pole}")
            c_ok = False
            c_detail[tag] = {"matched": False}
            continue
        d["network_id"] = net.get("network_id")
        d["pole_count"] = net.get("pole_count")
        d["member_count"] = net.get("member_count")
        d["anchor_pole"] = net.get("anchor_pole")
        d["consumption_w"] = net.get("consumption_w")
        d["production_w"] = net.get("production_w")
        d["consumption_by_prototype"] = net.get("consumption_w_by_prototype")
        d["production_by_prototype"] = net.get("production_w_by_prototype")

        if net.get("pole_count") != 1:
            finding(f"C {tag}: pole_count {net.get('pole_count')} != 1")
            c_ok = False
        if (net.get("anchor_pole") or {}).get("name") != "small-electric-pole":
            finding(f"C {tag}: anchor pole name {(net.get('anchor_pole') or {}).get('name')!r} "
                    f"!= 'small-electric-pole'")
            c_ok = False
        if (net.get("member_count") or 0) < 3:
            finding(f"C {tag}: member_count {net.get('member_count')} < 3")
            c_ok = False
        # consumption assertion (assembling-machine-1)
        cons_asm = (net.get("consumption_w_by_prototype") or {}).get("assembling-machine-1")
        d["consumption_asm_w"] = cons_asm
        if cons_asm is None:
            finding(f"C {tag}: no 'assembling-machine-1' key in consumption_w_by_prototype: "
                    f"{net.get('consumption_w_by_prototype')}")
            c_ok = False
        else:
            rel = abs(cons_asm - exp_c) / exp_c
            d["consumption_rel_err"] = rel
            if rel > tol_c:
                probe = direct_flow_probe(rcon, pole["x"], pole["y"])
                d["direct_flow_probe"] = probe
                finding(f"C {tag}: assembler consumption {cons_asm} W off expected {exp_c} W "
                        f"(rel {rel:.3f} > tol {tol_c}). Raw line tick {c_line['tick']}. "
                        f"Direct get_flow_count probe: {probe}")
                c_ok = False
        # production keyed on electric-energy-interface
        prod_by = net.get("production_w_by_prototype") or {}
        if "electric-energy-interface" not in prod_by:
            finding(f"C {tag}: production_w_by_prototype not keyed 'electric-energy-interface': {prod_by}")
            c_ok = False
        # production matches consumption
        pw, cw = net.get("production_w"), net.get("consumption_w")
        if pw is not None and cw and cw > 0:
            prel = abs(pw - cw) / cw
            d["prod_vs_cons_rel_err"] = prel
            if prel > TOL["production_matches_consumption_rel_tol"]:
                finding(f"C {tag}: production_w {pw} does not match consumption_w {cw} "
                        f"(rel {prel:.3f} > {TOL['production_matches_consumption_rel_tol']})")
                c_ok = False
        c_detail[tag] = d
    results["phases"]["C_sample"]["detail"] = c_detail
    results["phases"]["C_sample"]["ok"] = c_ok
    # stash the phase-C 2-network tick + line for phase F cross-check
    c_tick = int(c_line["tick"])
    hb(f"C done ok={c_ok}: tick {c_tick}, our nets {len(c_our)} (rigA cons "
       f"{c_detail.get('rigA', {}).get('consumption_asm_w')}, rigB cons "
       f"{c_detail.get('rigB', {}).get('consumption_asm_w')})")
    probe_has_global(rcon, "after_C")

    # === D. merge ==========================================================
    # bridge poles from pole A to pole B at ~7-tile spacing along x (same y)
    spacing = TOL["bridge_spacing_tiles"]
    x = poleA["x"] + spacing
    bridge_positions = []
    while x < poleB["x"] - 1.0:
        bridge_positions.append({"x": round(x, 1), "y": poleA["y"]})
        x += spacing
    hb(f"D merge: placing {len(bridge_positions)} bridge poles at {spacing}-tile spacing")
    posjson = "{" + ",".join(f"{{x={p['x']},y={p['y']}}}" for p in bridge_positions) + "}"
    bridge = lua(rcon, f"""
      local s = game.surfaces[1]
      local placed = 0
      for _, p in pairs({posjson}) do
        local e = s.create_entity{{name='small-electric-pole', position=p, force='player'}}
        if e then placed = placed + 1 end
      end
      return {{placed=placed}}
    """)
    bridge_count = int(bridge.get("placed", 0))
    results["phases"]["D_merge"] = {"bridge_requested": len(bridge_positions), "bridge_placed": bridge_count}
    if bridge_count != len(bridge_positions):
        finding(f"D: only placed {bridge_count}/{len(bridge_positions)} bridge poles")

    d_tick0 = game_tick(rcon)
    d_min = ((d_tick0 // WINDOW) + 2) * WINDOW + 5
    d_line = wait_for_line_tick(rcon, d_min, "D merged", timeout_s=90)
    if d_line is None:
        _cleanup(rcon)
        return finish("FAIL", 1)
    # a second consecutive sample for anchor determinism
    d_line2 = wait_for_line_tick(rcon, int(d_line["tick"]) + WINDOW, "D merged-2", timeout_s=90)
    d_our = our_nets(d_line)
    d_our2 = our_nets(d_line2) if d_line2 else []
    d_ok = True
    if len(d_our) != 1:
        finding(f"D: after merge expected 1 of-our-cell network, got {len(d_our)}: "
                f"{[n.get('network_id') for n in d_our]}")
        d_ok = False
    expected_pc = 2 + bridge_count
    merged_pc = d_our[0].get("pole_count") if d_our else None
    if merged_pc != expected_pc:
        finding(f"D: merged pole_count {merged_pc} != 2+bridge({bridge_count})={expected_pc}")
        d_ok = False
    anchor1 = (d_our[0].get("anchor_pole") if d_our else {}) or {}
    anchor2 = (d_our2[0].get("anchor_pole") if d_our2 else {}) or {}
    anchor_stable = bool(d_our and d_our2) and anchor1 == anchor2
    if not anchor_stable:
        finding(f"D: anchor NOT deterministic across 2 samples: {anchor1} vs {anchor2}")
        d_ok = False
    # anchor should be the leftmost pole = rig A's pole
    if d_our:
        ap = anchor1.get("position") or {}
        if not (abs(ap.get("x", 1e18) - poleA["x"]) <= TOL["anchor_pos_epsilon"] and
                abs(ap.get("y", 1e18) - poleA["y"]) <= TOL["anchor_pos_epsilon"]):
            finding(f"D: merged anchor {ap} is not rig A pole {poleA} (expected leftmost)")
            d_ok = False
    results["phases"]["D_merge"].update({
        "ok": d_ok,
        "merged_network_id": d_our[0].get("network_id") if d_our else None,
        "expected_pole_count": expected_pc,
        "observed_pole_count": merged_pc,
        "anchor_sample1": anchor1,
        "anchor_sample2": anchor2,
        "anchor_deterministic": anchor_stable,
        "sample1_tick": d_line["tick"],
        "sample2_tick": d_line2["tick"] if d_line2 else None,
    })
    hb(f"D done ok={d_ok}: 1 network pole_count {merged_pc} (=2+{bridge_count}), "
       f"anchor stable={anchor_stable}")
    probe_has_global(rcon, "after_D")

    # === E. split + id ephemerality ========================================
    merged_id = d_our[0].get("network_id") if d_our else None
    split = lua(rcon, f"""
      local s = game.surfaces[1]
      local n = 0
      for _, p in pairs({posjson}) do
        local es = s.find_entities_filtered{{name='small-electric-pole', position=p, radius=1}}
        for _, e in pairs(es) do e.destroy(); n = n + 1 end
      end
      return {{destroyed=n}}
    """)
    e_tick0 = game_tick(rcon)
    e_min = ((e_tick0 // WINDOW) + 2) * WINDOW + 5
    e_line = wait_for_line_tick(rcon, e_min, "E split", timeout_s=90)
    if e_line is None:
        _cleanup(rcon)
        return finish("FAIL", 1)
    e_our = our_nets(e_line)
    e_ids = sorted(n.get("network_id") for n in e_our)
    e_ok = len(e_our) == 2
    if not e_ok:
        finding(f"E: after split expected 2 of-our-cell networks, got {len(e_our)}: {e_ids}")
    # id lineage evidence (RECORDED, not asserted — PWR-NETID-1)
    results["phases"]["E_split"] = {
        "ok": e_ok,
        "bridge_destroyed": split.get("destroyed"),
        "PWR-NETID-1_note": (
            "engine network_id is EPHEMERAL — it renumbers on merge/split. "
            "anchor_pole is the durable per-network reference. IDs below are "
            "recorded as lineage evidence, NOT asserted."
        ),
        "id_lineage": {
            "phaseC_rigA_id": (netA or {}).get("network_id"),
            "phaseC_rigB_id": (netB or {}).get("network_id"),
            "phaseD_merged_id": merged_id,
            "phaseE_split_ids": e_ids,
        },
        "split_networks": e_our,
        "split_tick": e_line["tick"],
    }
    hb(f"E done ok={e_ok}: split -> {len(e_our)} networks, ids {e_ids} "
       f"(merged was {merged_id}; ids ephemeral by design)")
    probe_has_global(rcon, "after_E")

    # === F. ingestion (boot-load path, read-only) ==========================
    hb("F ingestion: fresh in-process SnapshotDatabase(None)+SnapshotLoader.load_all")
    f_ok = True
    try:
        from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase
        from FactoryVerse.game.infra.duckdb.loader import SnapshotLoader

        server_root = REPO / ".fv-output" / "server_0"
        db = SnapshotDatabase(None)  # in-memory
        db.ensure_schema()
        loader = SnapshotLoader(db.connection, server_root)
        t_load = time.time()
        load_res = loader.load_all()
        load_secs = round(time.time() - t_load, 1)

        jsonl_now = read_jsonl_lines()
        distinct_ticks = {int(ln["tick"]) for ln in jsonl_now}
        ps_count = db.connection.execute("SELECT count(*) FROM power_samples").fetchone()[0]
        f_detail = {
            "load_seconds": load_secs,
            "jsonl_distinct_ticks": len(distinct_ticks),
            "power_samples_rows": ps_count,
        }
        if ps_count < len(distinct_ticks):
            finding(f"F: power_samples rows {ps_count} < distinct jsonl ticks {len(distinct_ticks)}")
            f_ok = False

        # spot-check the phase-C 2-network tick's rows vs the jsonl line
        pn_rows = db.connection.execute(
            """SELECT network_id, anchor_pole_name, anchor_pole_x, anchor_pole_y,
                      pole_count, member_count, production_w, consumption_w
               FROM power_networks WHERE tick = ?""",
            [c_tick],
        ).fetchall()
        f_detail["power_networks_rows_at_phaseC_tick"] = len(pn_rows)
        f_detail["phaseC_tick"] = c_tick
        # find our rigA row (anchor at poleA) in DB and compare to jsonl netA
        db_rigA = None
        for r in pn_rows:
            if abs(float(r[2]) - poleA["x"]) <= TOL["anchor_pos_epsilon"] and \
               abs(float(r[3]) - poleA["y"]) <= TOL["anchor_pos_epsilon"]:
                db_rigA = r
                break
        if db_rigA is None or netA is None:
            finding(f"F: could not cross-check rig A row (db_rigA={db_rigA}, jsonl netA present={netA is not None})")
            f_ok = False
        else:
            db_cmp = {
                "network_id": db_rigA[0], "anchor_pole_name": db_rigA[1],
                "anchor_pole_x": db_rigA[2], "anchor_pole_y": db_rigA[3],
                "pole_count": db_rigA[4], "member_count": db_rigA[5],
                "production_w": db_rigA[6], "consumption_w": db_rigA[7],
            }
            f_detail["db_rigA"] = db_cmp
            f_detail["jsonl_rigA"] = {
                "network_id": netA.get("network_id"),
                "anchor_pole_name": (netA.get("anchor_pole") or {}).get("name"),
                "production_w": netA.get("production_w"),
                "consumption_w": netA.get("consumption_w"),
            }
            mismatches = []
            if db_cmp["anchor_pole_name"] != (netA.get("anchor_pole") or {}).get("name"):
                mismatches.append("anchor_pole_name")
            if abs((db_cmp["production_w"] or 0) - (netA.get("production_w") or 0)) > 1.0:
                mismatches.append("production_w")
            if abs((db_cmp["consumption_w"] or 0) - (netA.get("consumption_w") or 0)) > 1.0:
                mismatches.append("consumption_w")
            if mismatches:
                finding(f"F: DB power_networks row does not match jsonl for rig A: {mismatches} "
                        f"(db={db_cmp}, jsonl netA prod={netA.get('production_w')} "
                        f"cons={netA.get('consumption_w')})")
                f_ok = False
            f_detail["mismatches"] = mismatches
        f_detail["ok"] = f_ok
        results["phases"]["F_ingestion"] = f_detail
        db.close() if hasattr(db, "close") else None
    except Exception as e:
        import traceback
        finding(f"F ingestion raised: {e}\n{traceback.format_exc()}")
        results["phases"]["F_ingestion"] = {"ok": False, "error": str(e)}
        f_ok = False
    hb(f"F done ok={f_ok}")

    # === G. passivity summary ==============================================
    g_ok = all(p.get("has_global") is False for p in results["has_global_probes"])
    results["phases"]["G_passivity"] = {
        "ok": g_ok,
        "probe_count": len(results["has_global_probes"]),
        "all_false": g_ok,
    }
    if not g_ok:
        finding("G: has_global_electric_network was TRUE at some probe (sampler mutated physics)")

    # === H. cleanup ========================================================
    hb("H cleanup: destroying all created entities in cell, re_snapshot_area")
    _cleanup(rcon)
    post = lua(rcon, f"""
      local b = remote.call('lab_grid','get_cell_bounds',{CELL})
      local s = game.surfaces[1]
      local es = s.find_entities_filtered{{area={{{{b.left_top.x,b.left_top.y}},{{b.right_bottom.x,b.right_bottom.y}}}}}}
      local n = 0
      for _, e in pairs(es) do
        if e.type ~= 'resource' and e.type ~= 'character' then n = n + 1 end
      end
      return {{count=n}}
    """)
    # final heartbeat: a NEW line after cleanup, our nets empty again
    h_tick0 = game_tick(rcon)
    h_min = ((h_tick0 // WINDOW) + 1) * WINDOW + 5
    h_line = wait_for_line_tick(rcon, h_min, "H final heartbeat", timeout_s=60)
    h_our = our_nets(h_line) if h_line else None
    h_ok = post.get("count") == 0 and h_line is not None and not h_our
    results["phases"]["H_cleanup"] = {
        "ok": h_ok,
        "nonresource_count_after": post.get("count"),
        "final_line_tick": h_line["tick"] if h_line else None,
        "final_our_networks_empty": (not h_our) if h_line else None,
    }
    if post.get("count") != 0:
        finding(f"H: cell {CELL} not clean after cleanup: {post}")
    if h_line is None:
        finding("H: sampler heartbeat NOT flowing after cleanup (no new line)")
    elif h_our:
        finding(f"H: our-cell networks not empty after cleanup: {h_our}")
    probe_has_global(rcon, "after_H")
    hb(f"H done ok={h_ok}: nonresource_count={post.get('count')}, final line "
       f"tick {h_line['tick'] if h_line else None}")

    # === verdict ============================================================
    all_ok = (static_ok and b_ok and c_ok and d_ok and e_ok and f_ok and g_ok and h_ok)
    results["phase_verdicts"] = {
        "A_static": static_ok, "B_baseline": b_ok, "C_two_network": c_ok,
        "D_merge": d_ok, "E_split": e_ok, "F_ingestion": f_ok,
        "G_passivity": g_ok, "H_cleanup": h_ok,
    }
    print("\n========== SUMMARY ==========")
    print(json.dumps(results["phase_verdicts"], indent=2))
    return finish("PASS" if all_ok else "FAIL", 0 if all_ok else 1)


def _cleanup(rcon) -> None:
    """Destroy every non-resource, non-character force='player' entity in cell 54,
    then re_snapshot_area the cell so the DB view matches."""
    r = lua(rcon, f"""
      local b = remote.call('lab_grid','get_cell_bounds',{CELL})
      local s = game.surfaces[1]
      local es = s.find_entities_filtered{{area={{{{b.left_top.x,b.left_top.y}},{{b.right_bottom.x,b.right_bottom.y}}}}}}
      local n = 0
      for _, e in pairs(es) do
        if e.valid and e.type ~= 'resource' and e.type ~= 'character' then
          e.destroy(); n = n + 1
        end
      end
      return {{destroyed=n, lt=b.left_top, rb=b.right_bottom}}
    """)
    results.setdefault("cleanup_calls", []).append(r)
    if isinstance(r, dict) and "lt" in r:
        lt, rb = r["lt"], r["rb"]
        resnap = lua(rcon, (
            "return remote.call('map','re_snapshot_area',"
            f"{{left_top={{x={lt['x']},y={lt['y']}}},"
            f"right_bottom={{x={rb['x']},y={rb['y']}}}}},50)"
        ))
        results.setdefault("cleanup_resnap", []).append(resnap)
    hb(f"cleanup: {r}")


if __name__ == "__main__":
    sys.exit(main())
