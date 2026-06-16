#!/usr/bin/env python3
"""Certification checks L4.1 / L4.2 / L4.4 — placement honesty battery.

L4.1  Placement honesty: engine can_place_entity(manual) prediction vs the
      actual outcome of placing through the AGENT path (agent_N.place_entity),
      over a ~22-cell grid spanning {clear, occupied, partially-overlapping}.
      Also surveys whether any agent-reachable pre-check affordance exists
      (tracker API-2).
L4.2  Placement failures explain themselves: deliberately fail agent-path
      placements (collision / out-of-reach / multi-tile overlap / bad
      direction); capture RCON error payloads verbatim; judge STRUCTURED vs
      RAW (tracker ERR-1).
L4.4  Geometry handoff: (a) burner-mining-drill drop_position fed back into
      place (raw fractional + tile-snapped) — KNOT-2; (b) PLACE-1 repro:
      placement_hints.get_fluid_connections for boiler -> steam-engine,
      place at first candidate if non-empty, engine-verify orientation +
      fluid connectivity.

Idempotent: clears its work area at start and end, destroys all agents at
the end (no-arg destroy_agents = destroy-all, fixed 2026-06-10 / L4.6).

Run:  uv run python scripts/certification/check_L4_placement.py --instance server_0
"""

from __future__ import annotations

import datetime
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from factorio_rcon import RCONClient  # noqa: E402

from FactoryVerse.game.scenarios.test_ground import TestGroundHelper  # noqa: E402

# ----------------------------------------------------------------------------
# Constants / instance config (configure_instance pattern from check_L1_sync.py)
# ----------------------------------------------------------------------------
DATE = "2026-06-10"
ART = REPO / ".fv-output" / "certification" / DATE / "L4.placement"
ART.mkdir(parents=True, exist_ok=True)
PROGRESS = ART / "progress.log"

RCON_HOST, RCON_PORT, RCON_PASS = "localhost", 27100, "factorio"


def configure_instance(name: str) -> None:
    """Point module globals at 'client' or 'server_N'."""
    global RCON_PORT
    if name == "client":
        return
    if name.startswith("server_"):
        n = int(name.split("_")[1])
        RCON_PORT = 27000 + n
        return
    raise SystemExit(f"unknown instance {name!r}; use 'client' or 'server_N'")


# Work area around agent spawn (0,0). All candidates within character reach.
WORK = {"left_top": {"x": -24, "y": -24}, "right_bottom": {"x": 24, "y": 24}}

# Obstacle field (placed via test_ground SCRIPT path — independent of agent):
#   F1 stone-furnace  @ (5, 0)      tiles x{4,5} y{-1,0}
#   C1 iron-chest     @ (2.5,-3.5)  tile (2,-4)
#   B1 transport-belt @ (-3.5,2.5)  tile (-4,2)
#   F2 stone-furnace  @ (-5,-3)     tiles x{-6,-5} y{-4,-3}
OBSTACLES = [
    ("stone-furnace", 5.0, 0.0, 0),
    ("iron-chest", 2.5, -3.5, 0),
    ("transport-belt", -3.5, 2.5, 4),
    ("stone-furnace", -5.0, -3.0, 0),
]

# Grid candidates: (entity, x, y, direction, case_label, designed_expectation)
CANDIDATES = [
    # -- clear 1x1 (wooden-chest), tile-centered ------------------------------
    ("wooden-chest", 1.5, 3.5, 0, "clear", True),
    ("wooden-chest", -1.5, -3.5, 0, "clear", True),
    ("wooden-chest", 3.5, 4.5, 0, "clear", True),
    ("wooden-chest", -6.5, 2.5, 0, "clear", True),
    ("wooden-chest", 0.5, -6.5, 0, "clear", True),
    ("wooden-chest", 7.5, -1.5, 0, "clear", True),
    ("wooden-chest", -7.5, -0.5, 0, "clear", True),
    ("wooden-chest", 2.5, 6.5, 0, "clear", True),
    # -- occupied 1x1 -----------------------------------------------------------
    # chest-on-chest: containers share fast_replaceable_group, so the engine
    # (and the agent path) treat this as placeable via fast-replace.
    ("wooden-chest", 2.5, -3.5, 0, "occupied(C1 iron-chest, fast-replaceable)", True),
    ("wooden-chest", 4.5, -0.5, 0, "occupied(F1 furnace tile)", False),
    ("wooden-chest", 5.5, 0.5, 0, "occupied(F1 furnace tile)", False),
    ("wooden-chest", -3.5, 2.5, 0, "occupied(B1 belt)", False),
    ("wooden-chest", -5.5, -3.5, 0, "occupied(F2 furnace tile)", False),
    ("wooden-chest", -4.5, -2.5, 0, "occupied(F2 furnace tile)", False),
    # -- partially overlapping: fractional 1x1 straddling into F1 --------------
    ("wooden-chest", 4.0, 0.5, 0, "partial(fractional, overlaps F1)", False),
    # collision boxes touch but do not overlap here -> engine says placeable
    ("wooden-chest", 5.0, 1.0, 0, "tangent(fractional, touches F1 box)", True),
    # -- clear 2x2 (stone-furnace), integer-centered ---------------------------
    ("stone-furnace", 0.0, 4.0, 0, "clear(2x2)", True),
    ("stone-furnace", -7.0, 4.0, 0, "clear(2x2)", True),
    # -- partially overlapping 2x2 ----------------------------------------------
    ("stone-furnace", 6.0, 1.0, 0, "partial(2x2 overlaps F1)", False),
    ("stone-furnace", 3.0, -3.0, 0, "partial(2x2 overlaps C1)", False),
    ("stone-furnace", -4.0, 3.0, 0, "partial(2x2 overlaps B1)", False),
    ("stone-furnace", -4.0, -2.0, 0, "partial(2x2 overlaps F2)", False),
]

INITIAL_INVENTORY = {
    "wooden-chest": 60,
    "stone-furnace": 30,
    "iron-chest": 10,
    "transport-belt": 20,
    "burner-mining-drill": 4,
    "boiler": 4,
    "steam-engine": 4,
    "pipe": 10,
}

results: dict = {"checks": {}, "findings": []}


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
    """Run Lua body (must `return <table>`) wrapped in xpcall; parsed JSON."""
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
        return {"error": f"non-JSON response: {out[:800]}"}


def raw_cmd(rcon: RCONClient, cmd: str) -> str:
    """Send a /c command WITHOUT xpcall and return the verbatim RCON response.

    This is exactly what an agent's RconHandler sees: JSON on success, the
    engine's error text (traceback and all) on failure.
    """
    out = rcon.send_command(cmd)
    return "" if out is None else out


def agent_place_verbatim(rcon: RCONClient, agent_id: int, entity: str,
                         x, y, direction) -> dict:
    """Place through the AGENT path; capture the verbatim agent-facing payload.

    Replicates RconHandler exactly (rcon_handler.py:99): /sc prefix, remote.call
    wrapped in xpcall(debug.traceback), errors returned as the JSON envelope
    {success=false, error="<lua error + traceback>"}. The returned 'verbatim'
    string is byte-for-byte what the Python agent's RCON layer receives.
    (Plain unwrapped /c errors come back as an EMPTY RCON response on the
    docker server — verified live 2026-06-10 — so this envelope IS the only
    agent-facing payload there is.)
    """
    if isinstance(direction, str):
        dir_lua = f"'{direction}'"
    else:
        dir_lua = str(direction)
    inner = (
        f"remote.call('agent_{agent_id}','place_entity', "
        f"{{entity_name='{entity}', position={{x={x},y={y}}}, direction={dir_lua}}})"
    )
    cmd = (
        f"/sc local success, result = xpcall(function() return {inner} end, debug.traceback); "
        f"if success then rcon.print(helpers.table_to_json(result)) "
        f"else rcon.print(helpers.table_to_json({{success=false, error=tostring(result)}})) end"
    )
    out = raw_cmd(rcon, cmd)
    try:
        parsed = json.loads(out)
        return {"success": bool(parsed.get("success")), "payload": parsed,
                "verbatim": out}
    except json.JSONDecodeError:
        return {"success": False, "payload": None, "verbatim": out}


def engine_can_place(rcon: RCONClient, entity: str, x, y, direction: int) -> bool:
    """Independent engine prediction: raw surface.can_place_entity, manual check."""
    res = lua(
        rcon,
        f"""
        local ok = game.surfaces[1].can_place_entity{{
            name='{entity}', position={{x={x},y={y}}}, direction={direction},
            force='player', build_check_type=defines.build_check_type.manual,
            forced=false}}
        return {{can_place = ok}}
        """,
    )
    if "error" in res:
        raise RuntimeError(f"can_place probe failed: {res['error']}")
    return bool(res.get("can_place"))


def entity_at(rcon: RCONClient, entity: str, x, y, radius=0.4):
    """Engine ground truth: is the named entity present at/near position?"""
    res = lua(
        rcon,
        f"""
        local e = game.surfaces[1].find_entities_filtered{{name='{entity}',
            position={{x={x},y={y}}}, radius={radius}}}[1]
        if not e then return {{found=false}} end
        return {{found=true, x=e.position.x, y=e.position.y, direction=e.direction}}
        """,
    )
    return res


def destroy_at(rcon: RCONClient, entity: str, x, y) -> dict:
    return lua(
        rcon,
        f"""
        local e = game.surfaces[1].find_entities_filtered{{name='{entity}',
            position={{x={x},y={y}}}, radius=0.4}}[1]
        if not e then return {{destroyed=false, reason='not found'}} end
        e.destroy{{raise_destroy=true}}
        return {{destroyed=true}}
        """,
    )


def reset_character(rcon: RCONClient) -> dict:
    """Teleport the single agent character back to (0,0) for controlled probes."""
    return lua(
        rcon,
        """
        local chars = game.surfaces[1].find_entities_filtered{type='character'}
        if #chars ~= 1 then return {error='expected 1 character, got '..#chars} end
        local ok = chars[1].teleport({x=0, y=0})
        return {teleported = ok}
        """,
    )


def census(rcon: RCONClient) -> list:
    """Player-force non-character entities in the work area (engine truth)."""
    lt, rb = WORK["left_top"], WORK["right_bottom"]
    res = lua(
        rcon,
        f"""
        local out = {{}}
        local ents = game.surfaces[1].find_entities_filtered{{
            area={{left_top={{x={lt['x']},y={lt['y']}}},
                   right_bottom={{x={rb['x']},y={rb['y']}}}}}, force='player'}}
        for _, e in ipairs(ents) do
            if e.type ~= 'character' then
                table.insert(out, {{name=e.name, x=e.position.x, y=e.position.y}})
            end
        end
        return {{n=#out, entities=out}}
        """,
    )
    if "error" in res:
        raise RuntimeError(f"census failed: {res['error']}")
    ents = res.get("entities", [])
    if isinstance(ents, dict):
        ents = list(ents.values())
    return ents


# ----------------------------------------------------------------------------
# Error payload judging (L4.2)
# ----------------------------------------------------------------------------
def judge_payload(verbatim: str) -> dict:
    """Judge the agent-facing error payload (the RconHandler JSON envelope).

    The envelope itself is always JSON; what matters for ERR-1 is the `error`
    field an LLM has to act on. Traceback inside it = RAW even if a cause
    string is buried at the head. STRUCTURED requires a machine-readable
    reason (dedicated reason fields / clean cause, no Lua internals).
    """
    error_text = verbatim
    envelope = None
    try:
        envelope = json.loads(verbatim)
        if isinstance(envelope, dict) and isinstance(envelope.get("error"), str):
            error_text = envelope["error"]
    except (json.JSONDecodeError, ValueError):
        pass
    low = error_text.lower()
    has_traceback = ("stack traceback" in low) or (".lua:" in low and "in function" in low)
    cause_markers = [
        "out of reach", "collid", "occupied", "blocked", "insufficient",
        "unknown entity", "requires", "must be nil or a number", "invalid direction",
    ]
    cause = next((m for m in cause_markers if m in low), None)
    structured_fields = isinstance(envelope, dict) and any(
        k in envelope for k in ("reason", "can_place", "collisions", "blocking_entity"))
    if structured_fields and not has_traceback:
        verdict = "STRUCTURED"
        rationale = "machine-readable reason fields in payload"
    elif has_traceback:
        verdict = "RAW"
        rationale = (
            "Lua traceback in error field; cause string "
            + (f"buried at head: {cause!r}" if cause else "ABSENT (no reason stated at all)")
        )
    elif cause:
        verdict = "SEMI-STRUCTURED"
        rationale = f"plain-text cause ({cause!r}) without traceback, but no structured fields"
    else:
        verdict = "RAW"
        rationale = "no traceback but no actionable cause either"
    return {"verdict": verdict, "rationale": rationale,
            "has_traceback": has_traceback, "cause_marker": cause}


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", default="client", help="client or server_N")
    instance = ap.parse_args().instance
    configure_instance(instance)
    results["instance"] = instance

    hb("=== check_L4_placement start ===")

    # --- 0. smoke ritual ------------------------------------------------------
    hb("smoke: connecting RCON, verifying interfaces")
    rcon = RCONClient(RCON_HOST, RCON_PORT, RCON_PASS)
    rcon.send_command("/c rcon.print('ping')")
    assert "ping" in rcon.send_command("/c rcon.print('ping')"), "smoke ping failed"
    ifaces = json.loads(
        rcon.send_command("/c rcon.print(helpers.table_to_json(remote.interfaces))")
    )
    needed = ["test_ground", "agent", "placement_hints"]
    missing = [i for i in needed if i not in ifaces]
    if missing:
        hb(f"SMOKE FAIL: missing interfaces {missing}")
        print(f"BLOCKED: missing interfaces {missing}")
        return 2
    tick = lua(rcon, "return {tick=game.tick}").get("tick")
    results["smoke"] = {"tick": tick, "interfaces": sorted(ifaces.keys())}
    results["placement_hints_methods"] = sorted(ifaces.get("placement_hints", {}).keys()) \
        if isinstance(ifaces.get("placement_hints"), dict) else ifaces.get("placement_hints")
    hb(f"smoke ok: tick={tick}")

    tg = TestGroundHelper(rcon)

    # --- 1. clean work area + create agent -------------------------------------
    hb("phase 1: clearing work area (-24..24)^2, destroying stray agents")
    lua(rcon, "remote.call('agent','destroy_agents') return {ok=true}")
    cleared = tg.clear_area((WORK["left_top"]["x"], WORK["left_top"]["y"]),
                            (WORK["right_bottom"]["x"], WORK["right_bottom"]["y"]))
    # NOTE: create_agent named-table dispatch is broken — ParamSpec
    # normalize_varargs builds positionals with table.insert(positional, value)
    # which SKIPS nil values, so {initial_inventory=...} collapses into
    # udp_port (verified live 2026-06-10: list_agents showed the inventory
    # table as udp_port). Workaround: no-arg create + agent.add_items.
    res = lua(rcon, "return remote.call('agent','create_agent')")
    if "error" in res or not res.get("agent_id"):
        raise RuntimeError(f"create_agent failed: {res}")
    agent_id = res["agent_id"]
    results["agent"] = res
    inv_lua = "{" + ", ".join(f"['{k}']={v}" for k, v in INITIAL_INVENTORY.items()) + "}"
    added = lua(rcon, f"return remote.call('agent','add_items', {agent_id}, {inv_lua})")
    if not added.get("success"):
        raise RuntimeError(f"add_items failed: {added}")
    pos = lua(rcon, f"return remote.call('agent_{agent_id}','get_position')")
    hb(f"phase 1 done: cleared {cleared} entities, agent_{agent_id} created at {pos}, "
       f"inventory stocked: {added.get('items_added')}")

    # ==========================================================================
    # L4.1 — placement honesty
    # ==========================================================================
    hb("L4.1 phase 2: placing obstacle field (script path)")
    for name, x, y, d in OBSTACLES:
        r = tg.place_entity(name, x, y, d)
        if not r.get("success"):
            raise RuntimeError(f"obstacle place {name}@({x},{y}) failed: {r}")
    field = census(rcon)
    if len(field) != len(OBSTACLES):
        raise RuntimeError(f"obstacle census mismatch: {len(field)} != {len(OBSTACLES)}: {field}")
    hb(f"L4.1 phase 2 done: {len(field)} obstacles verified present")

    hb(f"L4.1 phase 3: grid sweep, {len(CANDIDATES)} candidates "
       f"(predict via raw can_place_entity(manual), act via agent_{agent_id}.place_entity)")

    def restore_field() -> None:
        """Re-place any obstacle a fast-replace style success knocked out.

        Side-finding from first run: agent fast-replace drops the displaced
        entity as item-on-ground (NOT into the agent inventory), and that
        item blocks script re-placement — mop those up first.
        """
        for oname, ox, oy, od in OBSTACLES:
            probe = entity_at(rcon, oname, ox, oy)
            if not probe.get("found"):
                lua(rcon, f"""
                    for _, it in ipairs(game.surfaces[1].find_entities_filtered{{
                        type='item-entity', position={{x={ox},y={oy}}}, radius=1.5}}) do
                        it.destroy()
                    end
                    return {{ok=true}}
                    """)
                rr = tg.place_entity(oname, ox, oy, od)
                if not rr.get("success"):
                    raise RuntimeError(f"field restore {oname}@({ox},{oy}) failed: {rr}")
                finding(f"field restore: re-placed {oname}@({ox},{oy}) after a "
                        f"candidate displaced it (fast_replace drops the old "
                        f"entity as item-on-ground, not into agent inventory)")

    grid_rows = []
    disagreements = []
    n_pred_true = n_pred_false = 0
    for i, (name, x, y, d, case, designed) in enumerate(CANDIDATES):
        rc = reset_character(rcon)
        if "error" in rc:
            raise RuntimeError(f"character reset failed: {rc}")
        predicted = engine_can_place(rcon, name, x, y, d)
        n_pred_true += int(predicted)
        n_pred_false += int(not predicted)
        attempt = agent_place_verbatim(rcon, agent_id, name, x, y, d)
        placed = attempt["success"]
        # engine-verify at the position the API CLAIMS it placed at (create_entity
        # snaps fractional requests — requested vs claimed is geometry evidence)
        claimed = (attempt.get("payload") or {}).get("position") if placed else None
        vx, vy = (claimed["x"], claimed["y"]) if claimed else (x, y)
        verify = entity_at(rcon, name, vx, vy) if placed else None
        if placed:
            if not (verify and verify.get("found")):
                finding(f"candidate {i} {name}@({x},{y}): place reported success at "
                        f"{claimed} but engine does not find the entity — DOUBLE DISHONESTY")
            if claimed and (claimed["x"] != x or claimed["y"] != y):
                finding(f"candidate {i} {name}: requested ({x},{y}) snapped by engine "
                        f"to ({claimed['x']},{claimed['y']}) — honest (claimed position "
                        f"is real), but caller's coordinates are not where it landed")
            destroy_at(rcon, name, vx, vy)
            restore_field()
        agree = predicted == placed
        if not agree:
            disagreements.append({"index": i, "case": case, "entity": name,
                                  "position": [x, y], "predicted": predicted,
                                  "placed": placed, "verbatim": attempt["verbatim"]})
        grid_rows.append({
            "index": i, "entity": name, "x": x, "y": y, "direction": d,
            "case": case, "designed_expectation": designed,
            "engine_predicted": predicted, "agent_place_succeeded": placed,
            "claimed_position": claimed,
            "engine_verified_present": bool(verify and verify.get("found")) if placed else None,
            "agree": agree,
            "payload_excerpt": attempt["verbatim"][:300],
        })
        if designed != predicted:
            finding(f"candidate {i} ({case}) {name}@({x},{y}): designed expectation "
                    f"{designed} != engine prediction {predicted} — rig design note, not a failure")
    (ART / "L4.1_grid.json").write_text(json.dumps(grid_rows, indent=2))
    with open(ART / "L4.1_grid.csv", "w") as f:
        f.write("index,entity,x,y,case,designed,predicted,placed,agree\n")
        for r in grid_rows:
            f.write(f"{r['index']},{r['entity']},{r['x']},{r['y']},\"{r['case']}\","
                    f"{r['designed_expectation']},{r['engine_predicted']},"
                    f"{r['agent_place_succeeded']},{r['agree']}\n")
    vacuous = n_pred_true < 5 or n_pred_false < 5
    results["checks"]["L4.1"] = {
        "candidates": len(CANDIDATES),
        "predicted_true": n_pred_true,
        "predicted_false": n_pred_false,
        "disagreements": disagreements,
        "vacuity_guard_ok": not vacuous,
        "pass": (not vacuous) and len(disagreements) == 0,
    }
    hb(f"L4.1 phase 3 done: {len(CANDIDATES)} cells, predicted_true={n_pred_true}, "
       f"predicted_false={n_pred_false}, disagreements={len(disagreements)}")

    # API-2 affordance survey (live side; code side recorded by the runner)
    hb("L4.1 phase 4: API-2 survey — live probe of placement_hints validate/cue")
    # blocked probe on a furnace tile (NOT chest-on-chest, which is honestly
    # placeable via fast-replace)
    probe_block = lua(rcon, "return remote.call('placement_hints','validate_placement',"
                            "{entity_name='wooden-chest', position={x=4.5,y=-0.5}})")
    probe_clear = lua(rcon, "return remote.call('placement_hints','validate_placement',"
                            "{entity_name='wooden-chest', position={x=1.5,y=3.5}})")
    probe_cue = lua(rcon, "return remote.call('placement_hints','get_placement_cue',"
                          "{entity_name='wooden-chest', position={x=4.5,y=-0.5}})")
    results["checks"]["L4.1"]["api2_survey"] = {
        "placement_hints_methods": results["placement_hints_methods"],
        "validate_placement_on_blocked_cell": probe_block,
        "validate_placement_on_clear_cell": probe_clear,
        "get_placement_cue_on_blocked_cell": probe_cue,
    }
    hb(f"L4.1 phase 4 done: validate_placement blocked={probe_block} clear={probe_clear} "
       f"cue={json.dumps(probe_cue)[:200]}")

    # ==========================================================================
    # L4.2 — placement failures explain themselves
    # ==========================================================================
    hb("L4.2 phase 5: deliberate failures through the agent path, verbatim payload capture")
    # NOTE case (a): chest-on-iron-chest is NOT a failure case — containers
    # share a fast_replaceable_group, so can_place(manual) says true and the
    # agent path fast-replaces. Collision case uses a furnace-occupied tile.
    err_cases = [
        ("a_collision_chest_on_furnace_tile", "wooden-chest", 4.5, -0.5, 0),
        ("b_out_of_reach", "wooden-chest", 40.5, 40.5, 0),
        ("c_furnace_overlapping_furnace", "stone-furnace", 6.0, 1.0, 0),
        ("d_bad_direction_99", "wooden-chest", 1.5, 3.5, 99),
        ("d2_bad_direction_string", "wooden-chest", 1.5, 3.5, "north"),
    ]
    payloads = {}
    judged = {}
    for label, name, x, y, d in err_cases:
        reset_character(rcon)
        att = agent_place_verbatim(rcon, agent_id, name, x, y, d)
        payloads[label] = att["verbatim"]
        if att["success"]:
            judged[label] = {"verdict": "DID-NOT-FAIL",
                             "rationale": "placement unexpectedly succeeded",
                             "payload": att["payload"]}
            finding(f"L4.2 case {label}: expected failure but place SUCCEEDED — "
                    f"silent acceptance of bad input")
            destroy_at(rcon, name, x, y)
        else:
            judged[label] = judge_payload(att["verbatim"])
        hb(f"L4.2 case {label}: {judged[label]['verdict']}")
    (ART / "L4.2_error_payloads.json").write_text(json.dumps(
        {"payloads_verbatim": payloads, "judgements": judged}, indent=2))
    # majority over the 4 primary cases (a, b, c, d)
    primary = ["a_collision_chest_on_furnace_tile", "b_out_of_reach",
               "c_furnace_overlapping_furnace", "d_bad_direction_99"]
    n_raw = sum(1 for k in primary if judged[k]["verdict"] == "RAW")
    n_structured = sum(1 for k in primary if judged[k]["verdict"] == "STRUCTURED")
    results["checks"]["L4.2"] = {
        "judgements": judged,
        "primary_raw_count": n_raw,
        "primary_structured_count": n_structured,
        "pass": n_raw < 2,  # majority-raw = FAIL
    }
    hb(f"L4.2 phase 5 done: RAW={n_raw}/4 primary cases")

    # ==========================================================================
    # L4.4 — geometry handoff
    # ==========================================================================
    hb("L4.4 phase 6: clearing field, placing ore patch + drill for drop_position test")
    tg.clear_area((WORK["left_top"]["x"], WORK["left_top"]["y"]),
                  (WORK["right_bottom"]["x"], WORK["right_bottom"]["y"]))
    r = tg.place_resource_patch("iron-ore", 6, 6, 3, 5000)
    if not r.get("success"):
        raise RuntimeError(f"ore patch failed: {r}")
    reset_character(rcon)
    drill = agent_place_verbatim(rcon, agent_id, "burner-mining-drill", 6.0, 6.0, 4)
    if not drill["success"]:
        raise RuntimeError(f"drill place failed: {drill['verbatim'][:400]}")
    inspect = lua(rcon, f"return remote.call('agent_{agent_id}','inspect_entity',"
                        f"'burner-mining-drill', {{x=6,y=6}})")
    engine_drop = lua(rcon, """
        local e = game.surfaces[1].find_entities_filtered{name='burner-mining-drill',
            position={x=6,y=6}, radius=0.4}[1]
        if not e then return {error='drill not found'} end
        return {drop_position = {x=e.drop_position.x, y=e.drop_position.y}}
        """)
    drop = None
    if isinstance(inspect, dict):
        drop = inspect.get("drop_position") or (inspect.get("data") or {}).get("drop_position")
    if not drop:
        drop = engine_drop.get("drop_position")
        finding(f"inspect_entity did not surface drop_position (inspect keys: "
                f"{sorted(inspect.keys()) if isinstance(inspect, dict) else inspect}); "
                f"fell back to raw engine read")
    if not drop:
        raise RuntimeError(f"no drop_position from either channel: {inspect} / {engine_drop}")
    dx, dy = float(drop["x"]), float(drop["y"])
    hb(f"L4.4a: drill placed, drop_position=({dx},{dy}) (engine read: {engine_drop})")

    # attempt 1: feed RAW fractional drop_position straight back into place
    reset_character(rcon)
    att_raw = agent_place_verbatim(rcon, agent_id, "wooden-chest", dx, dy, 0)
    raw_claimed = (att_raw.get("payload") or {}).get("position")
    raw_actual = None
    if att_raw["success"]:
        rx, ry = (raw_claimed["x"], raw_claimed["y"]) if raw_claimed else (dx, dy)
        raw_actual = entity_at(rcon, "wooden-chest", rx, ry)
        destroy_at(rcon, "wooden-chest", rx, ry)
    # attempt 2: tile-snap (the rounding an agent would have to invent)
    tx, ty = math.floor(dx) + 0.5, math.floor(dy) + 0.5
    reset_character(rcon)
    att_snap = agent_place_verbatim(rcon, agent_id, "wooden-chest", tx, ty, 0)
    snap_actual = entity_at(rcon, "wooden-chest", tx, ty) if att_snap["success"] else None
    if att_snap["success"]:
        # destroy BEFORE the helper probe — an occupied drop tile would
        # confound get_item_drop_connections (it can_place-filters candidates)
        destroy_at(rcon, "wooden-chest", tx, ty)
    # helper survey: does the mod-level item-drop helper produce candidates?
    helper = lua(rcon, "return remote.call('placement_hints','get_item_drop_connections',"
                       "{source_name='burner-mining-drill', source_position={x=6,y=6},"
                       " target_name='wooden-chest'})")
    results["checks"]["L4.4a"] = {
        "inspect_drop_position": drop,
        "engine_drop_position": engine_drop.get("drop_position"),
        "raw_fractional_attempt": {"requested": [dx, dy],
                                   "succeeded": att_raw["success"],
                                   "claimed_position": raw_claimed,
                                   "verbatim": att_raw["verbatim"],
                                   "engine_found_at": raw_actual},
        "tile_snapped_attempt": {"requested": [tx, ty],
                                 "succeeded": att_snap["success"],
                                 "claimed_position": (att_snap.get("payload") or {}).get("position"),
                                 "verbatim": att_snap["verbatim"],
                                 "engine_found_at": snap_actual},
        "get_item_drop_connections_result": helper,
    }
    hb(f"L4.4a done: raw-fractional accepted={att_raw['success']}, "
       f"tile-snapped accepted={att_snap['success']}, "
       f"item_drop_connections count={helper.get('count') if isinstance(helper, dict) else '?'}")

    # --- L4.4b: PLACE-1 reproduction -------------------------------------------
    hb("L4.4b phase 7: boiler placement + placement_hints fluid connection candidates")
    reset_character(rcon)
    boiler = agent_place_verbatim(rcon, agent_id, "boiler", -2.5, 6.0, 0)
    if not boiler["success"]:
        raise RuntimeError(f"boiler place failed: {boiler['verbatim'][:400]}")
    fluid = lua(rcon, "return remote.call('placement_hints','get_fluid_connections',"
                      "{source_name='boiler', source_position={x=-2.5,y=6},"
                      " target_name='steam-engine'})")
    # result shape: {source_name, source_position, target_name, positions, count}
    candidates = fluid.get("positions", []) if isinstance(fluid, dict) else []
    if isinstance(candidates, dict):  # table_to_json: empty/array-as-map quirks
        candidates = list(candidates.values())
    nonempty = len(candidates) > 0
    # Non-vacuity controls: prove the helper machinery itself is alive — the
    # boiler must be found and the same call must yield candidates for 'pipe'.
    ctrl_points = lua(rcon, "return remote.call('placement_hints','get_fluid_connection_points',"
                            "{entity_name='boiler', position={x=-2.5,y=6}})")
    ctrl_pipe = lua(rcon, "return remote.call('placement_hints','get_fluid_connections',"
                          "{source_name='boiler', source_position={x=-2.5,y=6},"
                          " target_name='pipe'})")
    ctrl_pipe_n = ctrl_pipe.get("count") if isinstance(ctrl_pipe, dict) else None
    results["checks"]["L4.4b"] = {
        "get_fluid_connections_verbatim": fluid,
        "nonempty": nonempty,
        "control_connection_points": ctrl_points,
        "control_pipe_candidate_count": ctrl_pipe_n,
        "control_pipe_verbatim": ctrl_pipe,
    }
    hb(f"L4.4b: boiler->steam-engine count={fluid.get('count') if isinstance(fluid, dict) else '?'}; "
       f"controls: boiler found={isinstance(ctrl_points, dict) and ctrl_points.get('entity_found')}, "
       f"boiler->pipe count={ctrl_pipe_n}")
    if nonempty:
        first = candidates[0]
        cpos, cdir = first.get("position"), first.get("direction", 0)
        hb(f"L4.4b: placing steam-engine at first candidate {first}")
        reset_character(rcon)
        se = agent_place_verbatim(rcon, agent_id, "steam-engine",
                                  cpos["x"], cpos["y"], cdir)
        verify = None
        if se["success"]:
            verify = lua(rcon, f"""
                local se = game.surfaces[1].find_entities_filtered{{name='steam-engine',
                    position={{x={cpos['x']},y={cpos['y']}}}, radius=0.6}}[1]
                if not se then return {{error='steam-engine not found'}} end
                local n_conn = 0
                local okc, conns = pcall(function() return se.fluidbox.get_connections(1) end)
                if okc and conns then n_conn = #conns end
                local n_pipes = 0
                local okp, pc = pcall(function() return se.fluidbox.get_pipe_connections(1) end)
                local connected_pos = nil
                if okp and pc then
                    n_pipes = #pc
                end
                return {{direction = se.direction, position = se.position,
                        fluidbox_connections = n_conn, pipe_connection_defs = n_pipes}}
                """)
        results["checks"]["L4.4b"].update({
            "first_candidate": first,
            "steam_engine_place_succeeded": se["success"],
            "steam_engine_place_verbatim": se["verbatim"],
            "engine_verify": verify,
        })
        hb(f"L4.4b: steam-engine placed={se['success']}, verify={verify}")
    else:
        finding("PLACE-1 REPRODUCED at floor level: get_fluid_connections("
                "boiler -> steam-engine) returned empty/error: " + json.dumps(fluid)[:400])

    # L4.4 verdict: (a) emitted positions are accepted back (directly or with
    # documented snapping the API itself performs) AND (b) hints non-empty+placeable
    a_ok = att_raw["success"] or att_snap["success"]
    b_ok = nonempty and results["checks"]["L4.4b"].get("steam_engine_place_succeeded", False)
    results["checks"]["L4.4"] = {
        "a_drop_position_roundtrip_ok": a_ok,
        "a_raw_fractional_accepted": att_raw["success"],
        "b_place1_fixed": b_ok,
        "pass": a_ok and b_ok,
    }

    # --- 8. cleanup -------------------------------------------------------------
    hb("phase 8: cleanup — destroy agents, clear work area, final census")
    destroyed = lua(rcon, "return remote.call('agent','destroy_agents')")
    tg.clear_area((WORK["left_top"]["x"], WORK["left_top"]["y"]),
                  (WORK["right_bottom"]["x"], WORK["right_bottom"]["y"]))
    final = census(rcon)
    chars = lua(rcon, "return {n = #game.surfaces[1].find_entities_filtered{type='character'}}")
    results["cleanup"] = {"destroy_agents": destroyed, "final_census_n": len(final),
                          "final_census": final, "characters_left": chars.get("n")}
    hb(f"phase 8 done: agents destroyed={destroyed}, final census={len(final)} "
       f"entities, characters left={chars.get('n')}")

    (ART / "results.json").write_text(json.dumps(results, indent=2, default=str))
    hb("=== check_L4_placement end ===")

    print("\n========== SUMMARY ==========")
    print(json.dumps({k: {kk: vv for kk, vv in v.items()
                          if kk not in ("judgements", "api2_survey", "disagreements")}
                      if isinstance(v, dict) else v
                      for k, v in results["checks"].items()}, indent=2, default=str))
    print(f"findings: {json.dumps(results['findings'], indent=2)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
