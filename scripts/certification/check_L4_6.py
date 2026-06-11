#!/usr/bin/env python
"""L4.6 — Connection cues CONNECT (pipes, item-drop, inserters, poles).

THE CLAIM UNDER TEST (Harshit's design intent, 2026-06-11): the
placement_hints connection queries are connection-GUARANTEEING placement
cues — like the game GUI's snap experience. Asking "where do I place a
boiler so it connects to this offshore pump?" returns positions(+directions)
such that PLACING AT THE CUE yields entities the ENGINE considers connected.
L4.4 certified strictly less: that cues exist and are placeable. Nobody has
ever asserted the connection itself — and the 2026-06-11 finale field run
showed the cost (agent hand-placed a steam engine flush against a boiler's
WATER port: physically adjacent, fluid-dead).

WHAT THIS CHECKS, PER CASE: create a real source rig (script create_entity,
force player, in an unallocated lab-grid cell), call the remote connection
query EXACTLY as the agent's Python wrapper does (positional args), then for
EVERY returned cue (capped at MAX_CUES_PER_CASE): can_place must hold
(manual build check), place the target at cue position+direction, and assert
the ENGINE connection truth:

    fluid     source.fluidbox.get_pipe_connections(i)[j].target.owner ==
              target — i.e. a live fluidbox linkage, not adjacency. For
              boiler→steam-engine additionally: the connecting source
              fluidbox must be production_type == 'output' (the steam port;
              a cue that connects the engine to a WATER port is a FAILURE
              even though it "connects").
    itemdrop  source.drop_target == placed target (engine resolution).
    inserter  inserter.pickup_target == A AND inserter.drop_target == B.
    pole      source.electric_network_id == target.electric_network_id.

ANTI-VACUITY FLOORS (BLOCKED/VACUOUS-RISK, never PASS):
    - every case must return >= its expected_min cues (axis-reflection
      completeness where the geometry has it: a pump's output admits TWO
      boiler positions, one per water input; a boiler's single steam port
      admits exactly ONE inline engine — floors encode the real geometry);
    - across the battery >= MIN_TOTAL_CUES cues actually placed+asserted;
    - a cue that cannot even be placed (can_place false) is a failure of the
      cue contract itself ("valid = true" lied), not a skip.

KNOWN-SUSPECT INVENTORY (from code reading 2026-06-11, to be confirmed or
cleared by execution — list them in the verdict either way):
    LUA-1  fluid legacy fallback (connections/init.lua:374-427) emits
           direction-less cues validated only by can_place adjacency.
    LUA-2  no post-placement connection guarantee anywhere (this harness IS
           that guarantee, retroactively).
    LUA-3  inserter reach check is distance-to-CENTER with 1.5-tile
           tolerance (init.lua:525-530), not footprint-based.
    LUA-4  pole supply-area count filters force='player' (cosmetic here).
    PY-1   placement_hints.py:_get_fluid_pipe_positions drops direction==0
           (north) cues to None — falsy-zero bug (tested at the unit layer,
           tests/unit/test_connection_positions.py, not here).
    PY-2   _get_item_drop_positions hardcodes direction=None.

AUDIT-GATE ANSWERS:
    Q1 vacuous pass?  No: per-case expected_min floors + battery-wide
       MIN_TOTAL_CUES + every cue must place AND connect (two distinct
       engine asserts); empty cue lists are failures, not skips.
    Q2 real layer or mock?  Real: live fv_placement_hints remote interface
       over RCON on a running lab-grid server, real create_entity placements,
       engine fluidbox/drop_target/network ids as ground truth. The Python
       wrapper layer is NOT exercised here (its parsing bugs are unit-tested
       separately — PY-1/PY-2).
    Q3 independent ground truth?  The connection asserts read engine state
       (fluidbox linkage, drop_target, electric_network_id) that shares no
       code with the cue computation under test.
    Q4 row coverage?  The L4.6 row claims cue→connection for fluid,
       item-drop, inserter, pole on the tested pairs ONLY. NOT covered:
       underground belts/pipes, ghosts (options.ghost=true), splitters,
       multi-fluidbox machines beyond boiler/engine (refinery, chem plant),
       circuit wires, cross-force cues, cues under space constraints
       (walled-in sources), and the Python wrapper layer.

CLEANUP CONTRACT (playbook §5): every created entity is destroyed
(raise_destroyed=true) before exit, pass or fail; the work area is
re-snapshotted; the runner verifies zero leftovers and reports it.

Exit codes: 0 = PASS, 1 = FAIL, 2 = BLOCKED, 3 = VACUOUS-RISK.
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

CHECK_ID = "L4.6"
RCON_HOST, RCON_PORT, RCON_PASS = "localhost", 27000, "factorio"

MAX_CUES_PER_CASE = 8
MIN_TOTAL_CUES = 12

ART: Path = REPO / ".fv-output" / "certification" / "unset" / CHECK_ID
PROGRESS: Path = ART / "progress.log"


def hb(msg: str) -> None:
    line = f"{datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')} {msg}"
    print(f"[hb] {line}", flush=True)
    with PROGRESS.open("a") as f:
        f.write(line + "\n")


def save(name: str, data: Any) -> None:
    (ART / name).write_text(json.dumps(data, indent=2, default=str))


# ----------------------------------------------------------------------------
# RCON envelope (check_cell_coherence conventions)
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
    """table_to_json renders empty arrays as {}; normalize."""
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        return [v[k] for k in sorted(v, key=lambda s: int(s) if str(s).isdigit() else 0)]
    return []


def pos_lua(p: Dict[str, float]) -> str:
    return f"{{x={p['x']},y={p['y']}}}"


# ----------------------------------------------------------------------------
# Engine-truth connection asserts (share NO code with the cue computation)
# ----------------------------------------------------------------------------
FLUID_CONNECTED_FN = """
local function find_at(name, p)
    local s = game.surfaces[1]
    local found = s.find_entities_filtered{name=name,
        area={{p.x-0.6, p.y-0.6}, {p.x+0.6, p.y+0.6}}}
    return found[1]
end
local function fluid_link(a, b)
    -- returns the SOURCE fluidbox index linking a->b, plus its
    -- production_type, or nil
    if not (a and a.valid and b and b.valid and a.fluidbox) then return nil end
    for i = 1, #a.fluidbox do
        local ok, pcs = pcall(function() return a.fluidbox.get_pipe_connections(i) end)
        if ok and pcs then
            for _, pc in ipairs(pcs) do
                if pc.target then
                    local owner = pc.target.owner
                    if owner and owner.valid and owner == b then
                        local ptype = nil
                        local ok2, proto = pcall(function() return a.fluidbox.get_prototype(i) end)
                        if ok2 and proto then
                            -- get_prototype may return one proto or an array
                            if proto.production_type then ptype = proto.production_type
                            elseif proto[1] and proto[1].production_type then ptype = proto[1].production_type end
                        end
                        return {index = i, production_type = ptype}
                    end
                end
            end
        end
    end
    return nil
end
"""


# ----------------------------------------------------------------------------
# The battery
# ----------------------------------------------------------------------------
def run_check(instance: str = "server_0", cell: int = 3,
              artifacts_dir: Optional[str] = None) -> Dict[str, Any]:
    global ART, PROGRESS, RCON_PORT
    if instance.startswith("server_"):
        RCON_PORT = 27000 + int(instance.split("_")[1])
    elif instance == "client":
        RCON_PORT = 27100
    else:
        return {"status": "BLOCKED", "blocked_reason": f"unknown instance {instance!r}",
                "failures": [], "counters": {}}

    date = datetime.date.today().isoformat()
    ART = Path(artifacts_dir) if artifacts_dir else (
        REPO / ".fv-output" / "certification" / date / CHECK_ID / instance)
    ART.mkdir(parents=True, exist_ok=True)
    PROGRESS = ART / "progress.log"

    commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    hb(f"=== check_L4_6 start (instance={instance}, cell={cell}, commit={commit}) ===")

    from factorio_rcon import RCONClient
    try:
        rcon = RCONClient(RCON_HOST, RCON_PORT, RCON_PASS)
    except Exception as e:  # noqa: BLE001
        return {"status": "BLOCKED",
                "blocked_reason": f"cannot connect RCON {RCON_HOST}:{RCON_PORT}: {e}",
                "failures": [], "counters": {}}

    ifaces = lua_strict(rcon, "local t={} for n,_ in pairs(remote.interfaces) do "
                              "table.insert(t,n) end return t")
    if "placement_hints" not in as_list(ifaces) or "lab_grid" not in as_list(ifaces):
        return {"status": "BLOCKED",
                "blocked_reason": f"missing remote interfaces in {as_list(ifaces)}",
                "failures": [], "counters": {}}

    # cell must be UNALLOCATED (we share the boot with eval debris in cell 0)
    storage = lua_strict(rcon, "return remote.call('lab_grid','get_storage_state')") \
        if False else {}
    b = lua_strict(rcon, f"return remote.call('lab_grid','get_cell_bounds',{cell})")
    ox, oy = b["left_top"]["x"], b["left_top"]["y"]
    hb(f"cell {cell} origin ({ox},{oy})")

    # in-cell layout anchors (identical per cell; verified live in LIVE-1C:
    # iron centroid +(14.5,69.5), water box +(108-119, 70-87))
    open_anchor = {"x": ox + 44, "y": oy + 28}      # flat empty ground
    open_anchor2 = {"x": ox + 70, "y": oy + 28}     # second rig area
    iron_anchor = {"x": ox + 14, "y": oy + 69}      # inside the iron patch
    water_min_y, water_max_y = oy + 70, oy + 87
    water_left_x = ox + 108

    failures: List[str] = []
    counters: Dict[str, Any] = {"cases": 0, "cues_returned": 0, "cues_tested": 0,
                                "connected": 0, "created": 0, "destroyed": 0}
    case_reports: List[Dict[str, Any]] = []

    def create(name: str, p: Dict[str, float], direction: Optional[int] = None) -> bool:
        dir_part = f", direction={direction}" if direction is not None else ""
        r = lua(rcon, f"""
            local s = game.surfaces[1]
            local e = s.create_entity{{name='{name}', position={pos_lua(p)}{dir_part},
                force='player', raise_built=true, create_build_effect_smoke=false}}
            return {{ok = e ~= nil and e.valid}}
        """)
        ok = isinstance(r, dict) and r.get("ok") is True
        if ok:
            counters["created"] += 1
        return ok

    def destroy(name: str, p: Dict[str, float]) -> None:
        r = lua(rcon, f"""
            local s = game.surfaces[1]
            local found = s.find_entities_filtered{{name='{name}',
                area={{{{{p['x']}-0.7, {p['y']}-0.7}}, {{{p['x']}+0.7, {p['y']}+0.7}}}}}}
            local n = 0
            for _, e in ipairs(found) do e.destroy{{raise_destroy=true}} n = n + 1 end
            return {{n = n}}
        """)
        if isinstance(r, dict):
            counters["destroyed"] += int(r.get("n") or 0)

    def place_offshore_pump() -> Optional[Dict[str, float]]:
        """Engine-truth brute force along the west water edge."""
        r = lua(rcon, f"""
            local s = game.surfaces[1]
            for y = {water_min_y}, {water_max_y} do
                for dx = -2, 2 do
                    for _, d in ipairs({{0, 4, 8, 12}}) do
                        local p = {{x = {water_left_x} + dx + 0.5, y = y + 0.5}}
                        if s.can_place_entity{{name='offshore-pump', position=p,
                            direction=d, force='player',
                            build_check_type=defines.build_check_type.manual}} then
                            local e = s.create_entity{{name='offshore-pump', position=p,
                                direction=d, force='player', raise_built=true,
                                create_build_effect_smoke=false}}
                            if e and e.valid then
                                return {{x = e.position.x, y = e.position.y, dir = e.direction}}
                            end
                        end
                    end
                end
            end
            return {{fail = true}}
        """)
        if isinstance(r, dict) and not r.get("fail") and "x" in r:
            counters["created"] += 1
            return {"x": r["x"], "y": r["y"]}
        return None

    def fluid_case(label: str, source_name: str, source_pos: Dict[str, float],
                   target_name: str, expected_min: int,
                   require_source_ptype: Optional[str] = None) -> None:
        """Call get_fluid_connections; place every cue; assert engine linkage."""
        counters["cases"] += 1
        rep: Dict[str, Any] = {"case": label, "cues": []}
        res = lua(rcon, f"return remote.call('placement_hints','get_fluid_connections',"
                        f"'{source_name}',{pos_lua(source_pos)},'{target_name}',"
                        f"{{max_results=20}})")
        if isinstance(res, dict) and "__lua_error" in res:
            failures.append(f"{label}: remote call ERRORED: {res['__lua_error'][:300]}")
            case_reports.append(rep)
            return
        cues = as_list(res.get("positions"))
        rep["returned"] = len(cues)
        counters["cues_returned"] += len(cues)
        if len(cues) < expected_min:
            failures.append(f"{label}: only {len(cues)} cue(s), expected >= "
                            f"{expected_min} (option set incomplete — axis "
                            f"reflection missing?) raw={json.dumps(res)[:300]}")
        for cue in cues[:MAX_CUES_PER_CASE]:
            cp = cue.get("position") or {}
            cdir = cue.get("direction")
            crep = {"position": cp, "direction": cdir}
            rep["cues"].append(crep)
            counters["cues_tested"] += 1
            if cdir is None:
                failures.append(f"{label}: cue at ({cp.get('x')},{cp.get('y')}) has "
                                "NO direction — direction-less cue (LUA-1 fallback "
                                "class); a rotatable target placed here is a coin flip")
                crep["verdict"] = "no-direction"
                continue
            dir_part = f", direction={int(cdir)}"
            r = lua(rcon, FLUID_CONNECTED_FN + f"""
                local s = game.surfaces[1]
                local src = find_at('{source_name}', {pos_lua(source_pos)})
                if not src then return {{err = 'source vanished'}} end
                local can = s.can_place_entity{{name='{target_name}',
                    position={pos_lua(cp)}{dir_part}, force='player',
                    build_check_type=defines.build_check_type.manual}}
                if not can then return {{can_place = false}} end
                local t = s.create_entity{{name='{target_name}', position={pos_lua(cp)}{dir_part},
                    force='player', raise_built=true, create_build_effect_smoke=false}}
                if not (t and t.valid) then return {{can_place = true, created = false}} end
                local link = fluid_link(src, t)
                local out = {{can_place = true, created = true,
                              connected = link ~= nil,
                              src_fluidbox = link and link.index or nil,
                              src_ptype = link and link.production_type or nil,
                              t_dir = t.direction}}
                t.destroy{{raise_destroy = true}}
                return out
            """)
            if not isinstance(r, dict) or "__lua_error" in r:
                failures.append(f"{label}: cue test lua error: {r}")
                crep["verdict"] = "lua-error"
                continue
            if r.get("can_place") is False:
                failures.append(f"{label}: cue ({cp.get('x')},{cp.get('y')},d={cdir}) "
                                "claims valid=true but can_place is FALSE — the cue "
                                "contract lied")
                crep["verdict"] = "unplaceable"
                continue
            if r.get("created"):
                counters["destroyed"] += 1
            if not r.get("connected"):
                failures.append(f"{label}: cue ({cp.get('x')},{cp.get('y')},d={cdir}) "
                                "placed CLEANLY but is NOT fluid-connected — "
                                "adjacency-not-connection (the field-run failure class)")
                crep["verdict"] = "not-connected"
                continue
            if require_source_ptype and r.get("src_ptype") != require_source_ptype:
                failures.append(f"{label}: cue ({cp.get('x')},{cp.get('y')},d={cdir}) "
                                f"connected via source fluidbox "
                                f"#{r.get('src_fluidbox')} production_type="
                                f"{r.get('src_ptype')!r}, REQUIRED "
                                f"{require_source_ptype!r} — wrong port (water-port "
                                "steam engine class)")
                crep["verdict"] = f"wrong-port:{r.get('src_ptype')}"
                continue
            counters["connected"] += 1
            crep["verdict"] = "connected"
        hb(f"{label}: {rep['returned']} cues, "
           f"{sum(1 for c in rep['cues'] if c.get('verdict') == 'connected')} connected")
        case_reports.append(rep)

    def itemdrop_case(label: str, source_name: str, source_pos: Dict[str, float],
                      target_name: str, expected_min: int) -> None:
        counters["cases"] += 1
        rep: Dict[str, Any] = {"case": label, "cues": []}
        res = lua(rcon, f"return remote.call('placement_hints','get_item_drop_connections',"
                        f"'{source_name}',{pos_lua(source_pos)},'{target_name}',"
                        f"{{max_results=20}})")
        if isinstance(res, dict) and "__lua_error" in res:
            failures.append(f"{label}: remote call ERRORED: {res['__lua_error'][:300]}")
            case_reports.append(rep)
            return
        cues = as_list(res.get("positions"))
        rep["returned"] = len(cues)
        counters["cues_returned"] += len(cues)
        if len(cues) < expected_min:
            failures.append(f"{label}: only {len(cues)} cue(s), expected >= {expected_min}"
                            f" raw={json.dumps(res)[:300]}")
        for cue in cues[:MAX_CUES_PER_CASE]:
            cp = cue.get("position") or {}
            crep = {"position": cp}
            rep["cues"].append(crep)
            counters["cues_tested"] += 1
            # two-phase: drop_target resolution can be deferred past the
            # placing tick, and RCON cannot span ticks — place in call A,
            # read+destroy in call B after real ticks have passed
            ra = lua(rcon, FLUID_CONNECTED_FN + f"""
                local s = game.surfaces[1]
                local can = s.can_place_entity{{name='{target_name}',
                    position={pos_lua(cp)}, force='player',
                    build_check_type=defines.build_check_type.manual}}
                if not can then return {{can_place = false}} end
                local t = s.create_entity{{name='{target_name}', position={pos_lua(cp)},
                    force='player', raise_built=true, create_build_effect_smoke=false}}
                return {{can_place = true, created = (t ~= nil and t.valid)}}
            """)
            time.sleep(1.0)  # drop_target resolves only once the drill works
            r = lua(rcon, FLUID_CONNECTED_FN + f"""
                local src = find_at('{source_name}', {pos_lua(source_pos)})
                local t = find_at('{target_name}', {pos_lua(cp)})
                if not src then return {{err = 'source vanished'}} end
                if not t then return {{err = 'target vanished'}} end
                local out = {{connected = (src.drop_target ~= nil and src.drop_target == t),
                              drop_target_name = src.drop_target and src.drop_target.name or nil,
                              engine_drop_pos = src.drop_position}}
                t.destroy{{raise_destroy = true}}
                return out
            """)
            if isinstance(ra, dict):
                r = {**(r if isinstance(r, dict) else {}), **{k: v for k, v in ra.items()}}
            if not isinstance(r, dict) or "__lua_error" in r:
                failures.append(f"{label}: cue test lua error: {r}")
                crep["verdict"] = "lua-error"
                continue
            if r.get("can_place") is False:
                failures.append(f"{label}: cue ({cp.get('x')},{cp.get('y')}) "
                                "claims valid but can_place FALSE")
                crep["verdict"] = "unplaceable"
                continue
            if r.get("created"):
                counters["destroyed"] += 1
            if not r.get("connected"):
                failures.append(f"{label}: cue ({cp.get('x')},{cp.get('y')}) placed but "
                                "drop_target does NOT resolve to it — items would "
                                "spill on ground")
                crep["verdict"] = "not-connected"
                continue
            counters["connected"] += 1
            crep["verdict"] = "connected"
        hb(f"{label}: {rep['returned']} cues, "
           f"{sum(1 for c in rep['cues'] if c.get('verdict') == 'connected')} connected")
        case_reports.append(rep)

    def inserter_case(label: str, pickup_name: str, pickup_pos: Dict[str, float],
                      drop_name: str, drop_pos: Dict[str, float],
                      expected_min: int) -> None:
        counters["cases"] += 1
        rep: Dict[str, Any] = {"case": label, "cues": []}
        res = lua(rcon, f"return remote.call('placement_hints','get_inserter_placements',"
                        f"'{pickup_name}',{pos_lua(pickup_pos)},"
                        f"'{drop_name}',{pos_lua(drop_pos)},'inserter')")
        if isinstance(res, dict) and "__lua_error" in res:
            failures.append(f"{label}: remote call ERRORED: {res['__lua_error'][:300]}")
            case_reports.append(rep)
            return
        cues = as_list(res.get("positions"))
        rep["returned"] = len(cues)
        counters["cues_returned"] += len(cues)
        if len(cues) < expected_min:
            failures.append(f"{label}: only {len(cues)} cue(s), expected >= {expected_min}"
                            f" raw={json.dumps(res)[:300]}")
        for cue in cues[:MAX_CUES_PER_CASE]:
            cp, cdir = cue.get("position") or {}, cue.get("direction")
            crep = {"position": cp, "direction": cdir}
            rep["cues"].append(crep)
            counters["cues_tested"] += 1
            if cdir is None:
                failures.append(f"{label}: inserter cue without direction")
                crep["verdict"] = "no-direction"
                continue
            # two-phase (same tick-deferral caveat as item drop)
            ra = lua(rcon, f"""
                local s = game.surfaces[1]
                local can = s.can_place_entity{{name='inserter',
                    position={pos_lua(cp)}, direction={int(cdir)}, force='player',
                    build_check_type=defines.build_check_type.manual}}
                if not can then return {{can_place = false}} end
                local t = s.create_entity{{name='inserter', position={pos_lua(cp)},
                    direction={int(cdir)}, force='player', raise_built=true,
                    create_build_effect_smoke=false}}
                return {{can_place = true, created = (t ~= nil and t.valid)}}
            """)
            time.sleep(0.3)
            r = lua(rcon, FLUID_CONNECTED_FN + f"""
                local a = find_at('{pickup_name}', {pos_lua(pickup_pos)})
                local b = find_at('{drop_name}', {pos_lua(drop_pos)})
                local t = find_at('inserter', {pos_lua(cp)})
                if not (a and b) then return {{err = 'rig vanished'}} end
                if not t then return {{err = 'inserter vanished'}} end
                local out = {{pickup_ok = (t.pickup_target ~= nil and t.pickup_target == a),
                              drop_ok = (t.drop_target ~= nil and t.drop_target == b),
                              engine_pickup = t.pickup_position,
                              engine_drop = t.drop_position,
                              pickup_target_name = t.pickup_target and t.pickup_target.name or nil,
                              drop_target_name = t.drop_target and t.drop_target.name or nil}}
                t.destroy{{raise_destroy = true}}
                return out
            """)
            if isinstance(ra, dict):
                r = {**(r if isinstance(r, dict) else {}), **{k: v for k, v in ra.items()}}
            if not isinstance(r, dict) or "__lua_error" in r:
                failures.append(f"{label}: cue test lua error: {r}")
                crep["verdict"] = "lua-error"
                continue
            if r.get("can_place") is False:
                failures.append(f"{label}: cue ({cp.get('x')},{cp.get('y')},d={cdir}) "
                                "claims valid but can_place FALSE")
                crep["verdict"] = "unplaceable"
                continue
            if r.get("created"):
                counters["destroyed"] += 1
            if not (r.get("pickup_ok") and r.get("drop_ok")):
                failures.append(f"{label}: cue ({cp.get('x')},{cp.get('y')},d={cdir}) "
                                f"placed but pickup_ok={r.get('pickup_ok')} "
                                f"drop_ok={r.get('drop_ok')} — inserter does not "
                                "bridge the pair (LUA-3 center-distance heuristic?)")
                crep["verdict"] = "not-connected"
                continue
            counters["connected"] += 1
            crep["verdict"] = "connected"
        hb(f"{label}: {rep['returned']} cues, "
           f"{sum(1 for c in rep['cues'] if c.get('verdict') == 'connected')} connected")
        case_reports.append(rep)

    def pole_case(label: str, source_pos: Dict[str, float], pole: str,
                  expected_min: int) -> None:
        counters["cases"] += 1
        rep: Dict[str, Any] = {"case": label, "cues": []}
        area = (f"{{left_top={{x={source_pos['x']-8},y={source_pos['y']-8}}},"
                f"right_bottom={{x={source_pos['x']+8},y={source_pos['y']+8}}}}}")
        res = lua(rcon, f"return remote.call('placement_hints','get_pole_connections',"
                        f"'{pole}',{pos_lua(source_pos)},'{pole}',{area},"
                        f"{{max_results=10}})")
        if isinstance(res, dict) and "__lua_error" in res:
            failures.append(f"{label}: remote call ERRORED: {res['__lua_error'][:300]}")
            case_reports.append(rep)
            return
        cues = as_list(res.get("positions"))
        rep["returned"] = len(cues)
        counters["cues_returned"] += len(cues)
        if len(cues) < expected_min:
            failures.append(f"{label}: only {len(cues)} cue(s), expected >= {expected_min}"
                            f" raw={json.dumps(res)[:300]}")
        for cue in cues[:5]:
            cp = cue.get("position") or {}
            crep = {"position": cp}
            rep["cues"].append(crep)
            counters["cues_tested"] += 1
            r = lua(rcon, FLUID_CONNECTED_FN + f"""
                local s = game.surfaces[1]
                local a = find_at('{pole}', {pos_lua(source_pos)})
                if not a then return {{err = 'source vanished'}} end
                local can = s.can_place_entity{{name='{pole}', position={pos_lua(cp)},
                    force='player', build_check_type=defines.build_check_type.manual}}
                if not can then return {{can_place = false}} end
                local t = s.create_entity{{name='{pole}', position={pos_lua(cp)},
                    force='player', raise_built=true, create_build_effect_smoke=false}}
                if not (t and t.valid) then return {{can_place = true, created = false}} end
                local out = {{can_place = true, created = true,
                              connected = (a.electric_network_id ~= nil and
                                           a.electric_network_id == t.electric_network_id)}}
                t.destroy{{raise_destroy = true}}
                return out
            """)
            if not isinstance(r, dict) or "__lua_error" in r:
                failures.append(f"{label}: cue test lua error: {r}")
                crep["verdict"] = "lua-error"
                continue
            if r.get("can_place") is False:
                failures.append(f"{label}: cue ({cp.get('x')},{cp.get('y')}) "
                                "claims valid but can_place FALSE")
                crep["verdict"] = "unplaceable"
                continue
            if r.get("created"):
                counters["destroyed"] += 1
            if not r.get("connected"):
                failures.append(f"{label}: cue ({cp.get('x')},{cp.get('y')}) placed but "
                                "poles share NO electric network — wire did not attach")
                crep["verdict"] = "not-connected"
                continue
            counters["connected"] += 1
            crep["verdict"] = "connected"
        hb(f"{label}: {rep['returned']} cues, "
           f"{sum(1 for c in rep['cues'] if c.get('verdict') == 'connected')} connected")
        case_reports.append(rep)

    created_rigs: List[tuple] = []  # (name, pos) for final cleanup sweep
    try:
        # ---- FLUID: boiler -> steam-engine (the marquee case) -------------
        boiler_pos = {"x": open_anchor["x"] + 0.5, "y": open_anchor["y"] + 0.0}
        if not create("boiler", boiler_pos, direction=4):  # EAST
            failures.append("SETUP: cannot create east-facing boiler on open ground")
        else:
            created_rigs.append(("boiler", boiler_pos))
            # one steam port, engine mates inline only -> exactly 1 cue is
            # geometrically complete (first-run finding: floor=2 was wrong
            # GAME knowledge, not a cue gap; the axis-reflected PAIR lives on
            # the pump->boiler water-input case below)
            fluid_case("FLUID boiler(E)->steam-engine", "boiler", boiler_pos,
                       "steam-engine", expected_min=1,
                       require_source_ptype="output")
            fluid_case("FLUID boiler(E)->pipe", "boiler", boiler_pos,
                       "pipe", expected_min=3)
            destroy("boiler", boiler_pos)
            created_rigs.pop()

        # north-facing boiler: direction=0 cues exist (the PY-1 falsy-zero
        # class lives downstream, but the LUA layer must emit dir=0 cleanly)
        boiler_pos_n = {"x": open_anchor["x"] + 0.0, "y": open_anchor["y"] + 0.5}
        if not create("boiler", boiler_pos_n, direction=0):  # NORTH
            failures.append("SETUP: cannot create north-facing boiler")
        else:
            created_rigs.append(("boiler", boiler_pos_n))
            fluid_case("FLUID boiler(N)->steam-engine", "boiler", boiler_pos_n,
                       "steam-engine", expected_min=1,
                       require_source_ptype="output")
            destroy("boiler", boiler_pos_n)
            created_rigs.pop()

        # ---- FLUID: steam-engine -> pipe -----------------------------------
        se_pos = {"x": open_anchor2["x"] + 0.5, "y": open_anchor2["y"] + 0.0}
        if not create("steam-engine", se_pos, direction=4):
            failures.append("SETUP: cannot create steam-engine")
        else:
            created_rigs.append(("steam-engine", se_pos))
            fluid_case("FLUID steam-engine(E)->pipe", "steam-engine", se_pos,
                       "pipe", expected_min=2)
            destroy("steam-engine", se_pos)
            created_rigs.pop()

        # ---- FLUID: offshore-pump -> boiler / pipe -------------------------
        pump_pos = place_offshore_pump()
        if pump_pos is None:
            failures.append("SETUP: could not place an offshore pump anywhere on the "
                            "west water edge (engine brute force) — pump cases BLOCKED")
        else:
            created_rigs.append(("offshore-pump", pump_pos))
            fluid_case("FLUID offshore-pump->pipe", "offshore-pump", pump_pos,
                       "pipe", expected_min=1)
            fluid_case("FLUID offshore-pump->boiler", "offshore-pump", pump_pos,
                       "boiler", expected_min=1)
            destroy("offshore-pump", pump_pos)
            created_rigs.pop()

        # ---- ITEM DROP: drill on iron -> chest / belt ----------------------
        # 2x2 snaps to integer centers; FUEL it — drop_target resolves
        # lazily, only once the drill actually works (live-probed 2026-06-11:
        # unfueled drill keeps drop_target nil forever with a chest squarely
        # on its drop position; fueled, it resolves AND delivers ore)
        drill_pos = {"x": iron_anchor["x"] + 1.0, "y": iron_anchor["y"] + 1.0}
        if not create("burner-mining-drill", drill_pos, direction=4):
            failures.append("SETUP: cannot create burner-mining-drill on iron patch")
        else:
            lua(rcon, f"""
                local s = game.surfaces[1]
                local d = s.find_entities_filtered{{name='burner-mining-drill',
                    area={{{{{drill_pos['x']}-1.2,{drill_pos['y']}-1.2}},
                          {{{drill_pos['x']}+1.2,{drill_pos['y']}+1.2}}}}}}[1]
                if d then d.get_fuel_inventory().insert({{name='coal', count=10}}) end
                return {{ok = d ~= nil}}
            """)
            created_rigs.append(("burner-mining-drill", drill_pos))
            itemdrop_case("DROP drill(E)->wooden-chest", "burner-mining-drill",
                          drill_pos, "wooden-chest", expected_min=1)
            itemdrop_case("DROP drill(E)->transport-belt", "burner-mining-drill",
                          drill_pos, "transport-belt", expected_min=1)
            destroy("burner-mining-drill", drill_pos)
            created_rigs.pop()

        # ---- INSERTER: chest -> furnace ------------------------------------
        chest_pos = {"x": open_anchor["x"] + 0.5, "y": open_anchor["y"] + 10.5}
        furn_pos = {"x": open_anchor["x"] + 3.0, "y": open_anchor["y"] + 11.0}
        if create("wooden-chest", chest_pos) and create("stone-furnace", furn_pos):
            created_rigs.append(("wooden-chest", chest_pos))
            created_rigs.append(("stone-furnace", furn_pos))
            inserter_case("INSERTER chest->furnace", "wooden-chest", chest_pos,
                          "stone-furnace", furn_pos, expected_min=1)
            destroy("wooden-chest", chest_pos)
            destroy("stone-furnace", furn_pos)
            created_rigs.clear()
        else:
            failures.append("SETUP: cannot create chest+furnace rig")

        # ---- POLES ---------------------------------------------------------
        pole_pos = {"x": open_anchor["x"] + 0.5, "y": open_anchor["y"] + 16.5}
        if create("small-electric-pole", pole_pos):
            created_rigs.append(("small-electric-pole", pole_pos))
            pole_case("POLE small->small", pole_pos, "small-electric-pole",
                      expected_min=2)
            destroy("small-electric-pole", pole_pos)
            created_rigs.pop()
        else:
            failures.append("SETUP: cannot create small-electric-pole")

    except Exception as e:  # noqa: BLE001
        import traceback
        failures.append(f"UNHANDLED: {type(e).__name__}: {e}")
        (ART / "traceback.txt").write_text(traceback.format_exc())
    finally:
        # cleanup sweep: anything of ours left standing in the cell
        for name, p in created_rigs:
            destroy(name, p)
        sweep = lua(rcon, f"""
            local s = game.surfaces[1]
            local names = {{'boiler','steam-engine','offshore-pump','pipe',
                'wooden-chest','transport-belt','burner-mining-drill','inserter',
                'stone-furnace','small-electric-pole'}}
            local leftover = {{}}
            for _, n in ipairs(names) do
                for _, e in ipairs(s.find_entities_filtered{{name=n, force='player',
                    area={{{{{ox},{oy}}},{{{ox}+128,{oy}+128}}}}}}) do
                    table.insert(leftover, {{name=n, x=e.position.x, y=e.position.y}})
                    e.destroy{{raise_destroy=true}}
                end
            end
            remote.call('map','re_snapshot_area',
                {{left_top={{x={ox},y={oy}}}, right_bottom={{x={ox}+128,y={oy}+128}}}}, 50)
            return {{leftover = leftover}}
        """)
        leftovers = as_list(sweep.get("leftover")) if isinstance(sweep, dict) else []
        if leftovers:
            hb(f"cleanup: destroyed {len(leftovers)} leftovers: {leftovers[:6]}")
        else:
            hb("cleanup verified: zero leftovers")

    counters["failures"] = len(failures)
    now_tick = lua(rcon, "return game.tick")
    if not failures and counters["cues_tested"] < MIN_TOTAL_CUES:
        status = "VACUOUS-RISK"
    else:
        status = "PASS" if not failures else "FAIL"
    verdict = {"status": status, "failures": failures, "counters": counters,
               "commit": commit, "tick": now_tick}
    save("results.json", {"verdict": verdict, "cases": case_reports})
    hb(f"=== check_L4_6 end: {status}, {counters['connected']}/"
       f"{counters['cues_tested']} cues connected ===")
    return verdict


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--instance", default="server_0")
    ap.add_argument("--cell", type=int, default=3,
                    help="unallocated lab-grid cell to test in (default 3)")
    ap.add_argument("--artifacts-dir", default=None)
    args = ap.parse_args()
    verdict = run_check(instance=args.instance, cell=args.cell,
                        artifacts_dir=args.artifacts_dir)
    print("\n========== SUMMARY ==========")
    print(json.dumps(verdict, indent=2, default=str))
    return {"PASS": 0, "FAIL": 1, "BLOCKED": 2, "VACUOUS-RISK": 3}[verdict["status"]]


if __name__ == "__main__":
    sys.exit(main())
