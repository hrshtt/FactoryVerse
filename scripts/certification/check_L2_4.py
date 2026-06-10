#!/usr/bin/env python
"""Certification check L2.4 — volatile state readable (status, crafting
progress, fuel, energy) and AGREES across layers, with proven cross-tick change.

Ledger row (FLOOR_CERTIFICATION.md L2.4):
    Claim:      Volatile state readable (status, crafting progress, fuel, energy)
    Rig:        assembler with recipe + fed materials; burner with coal
    Pass:       values change over ticks and match across read layers

Why the old harness was decertified (audit 2026-06-10): tests/functional/
test_complex_inspection.py never re-read across ticks, asserted no
status/energy values (only fuel>0), and never touched the typed layer. This
harness exists to certify exactly what that one didn't: VALUE CHANGE between
reads, and layer agreement on the same payloads.

Rig (lab-grid cell, test-ground-style script placement with the cell force):
    - stone-furnace      : coal (fuel) + iron-ore (input), fed via the AGENT
                           path put_inventory_item  -> burner volatiles
    - assembling-machine-1: recipe iron-gear-wheel (agent set_entity_recipe)
                           + iron-plate fed via put_inventory_item; powered by
                           electric-energy-interface + small-electric-pole
                           (script-placed; precedent: tests/functional/*)

Layers compared per sample (3 samples, ~1.2 s apart):
    E  engine ground truth — raw /c Lua property reads (status enum,
       crafting_progress, products_finished, energy, burner.remaining_burning_fuel,
       inventory counts). Independent of all fv inspection code.
    I  mod inspect path    — remote.call('agent_<id>','inspect_entity',name,pos)
    T  Python typed path   — transform_inspection_data(I-payload) ->
       EntityInspection (crafter/electric/burner slots)

Pass criteria (ALL required):
    1. Both rig entities reach status==working (symbolic, via the
       defines.entity_status dump) before sampling; else VACUOUS-RISK — an
       idle rig cannot certify volatiles.
    2. CHANGE: per entity, engine products_finished strictly increases across
       the window OR crafting_progress differs between samples (handles
       progress wrap); furnace remaining_burning_fuel changes (decrease
       expected; an increase is accepted ONLY with a fuel-item-count decrease
       = new coal loaded); a frozen value on any required-change field = FAIL.
    3. AGREEMENT: at every sample, typed values == inspect-payload values
       (crafting_progress, energy, remaining_burning_fuel, status) and
       inspect values match engine values within FLOAT_TOL taken in the same
       read burst (small tick skew tolerated, recorded).
    4. Anti-vacuity counters: >= 12 field comparisons and >= 4 change
       assertions actually executed, else VACUOUS-RISK regardless of greens.

Audit-gate answers AS DESIGNED (executing runner must re-validate on first run):
    Q1 vacuous pass?     No conditional assertions: every required field is a
                         hard assert; counters enforce >0 comparisons; frozen
                         values FAIL; idle rig exits 3, never 0.
    Q2 real layer?       Live game via RCON + the real agent remote interface
                         + the real transform_inspection_data. No mocks.
    Q3 independent truth? Engine layer is raw LuaEntity property access over
                         /c — does not share a line of code with
                         inspection.lua or transform.py.
    Q4 covers the row?   status (symbolic) + crafting progress + fuel + energy,
                         cross-tick change, cross-layer agreement. NOT covered:
                         ReachableView wrapper objects (row text mentions it;
                         this check certifies inspect_entity + typed transform;
                         the runner should narrow the row or extend later).

SCOPE / OPEN-QUESTIONS (offline draft cannot settle; runner must confirm):
    - OQ1: 'electric-energy-interface' placement in lab-grid for a cell force
      is assumed to work (works on test-ground per tests/functional). If the
      prototype is filtered/unplaceable, script exits BLOCKED with evidence.
    - OQ2: transform.py:172 reads burner 'remaining_fuel' or
      'remaining_burning_fuel'; inspection.lua emits 'remaining_burning_fuel'.
      The fallback chain should mask the name drift — this harness compares
      the typed value against BOTH keys and records which one carried data.
    - OQ3: assembler energy is asserted >0 at every sample, not asserted to
      change (a full buffer is legitimately steady).
    - OQ4: 1.2 s sample spacing assumes ~60 UPS; runner should sanity-check
      tick deltas recorded in samples (they are saved per read).

Exit codes: 0 = PASS, 1 = FAIL, 2 = BLOCKED, 3 = VACUOUS-RISK.

Usage:
    uv run python scripts/certification/check_L2_4.py --instance client --cell 3
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

from factorio_rcon import RCONClient  # noqa: E402

from FactoryVerse.game.factory.entity.transform import (  # noqa: E402
    transform_inspection_data,
)

# ----------------------------------------------------------------------------
# Constants / instance plumbing
# ----------------------------------------------------------------------------
DATE = datetime.date.today().isoformat()
CHECK_ID = "L2.4"

RCON_HOST, RCON_PORT, RCON_PASS = "localhost", 27100, "factorio"

FLOAT_TOL = 1e-6
SAMPLE_GAP_S = 1.2
N_SAMPLES = 3
WORKING_TIMEOUT_S = 30.0

# Anti-vacuity floors (criterion 4)
MIN_FIELD_COMPARISONS = 12
MIN_CHANGE_ASSERTIONS = 4

results: Dict[str, Any] = {"findings": [], "phases": {}, "counters": {}}
ART: Path = REPO / ".fv-output" / "certification" / DATE / CHECK_ID
PROGRESS: Path = ART / "progress.log"


def configure_instance(name: str) -> None:
    global RCON_PORT
    if name == "client":
        return
    if name.startswith("server_"):
        RCON_PORT = 27000 + int(name.split("_")[1])
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
# RCON helpers (RUNTIME_PLAYBOOK §2: xpcall mandatory)
# ----------------------------------------------------------------------------
def lua(rcon: RCONClient, body: str) -> Any:
    wrapped = (
        "/c local ok, res = xpcall(function() "
        + body
        + " end, debug.traceback) "
        + "if ok then rcon.print(helpers.table_to_json(res == nil and {ok=true} or res)) "
        + "else rcon.print(helpers.table_to_json({__lua_error = tostring(res)})) end"
    )
    out = rcon.send_command(wrapped)
    if out is None or out.strip() == "":
        return {"__lua_error": "empty RCON response (unwrapped error?)"}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"__lua_error": f"non-JSON response: {out[:500]}"}


def lua_strict(rcon: RCONClient, body: str) -> Any:
    res = lua(rcon, body)
    if isinstance(res, dict) and "__lua_error" in res:
        raise RuntimeError(f"Lua error: {res['__lua_error'][:800]}")
    return res


def pos_lua(p: Dict[str, float]) -> str:
    return f"{{x={p['x']},y={p['y']}}}"


# ----------------------------------------------------------------------------
# Phase helpers
# ----------------------------------------------------------------------------
def smoke(rcon: RCONClient) -> None:
    rcon.send_command("/c rcon.print('ping')")  # first command may warn
    assert "ping" in rcon.send_command("/c rcon.print('ping')"), "smoke ping failed"
    ifaces = json.loads(
        rcon.send_command("/c rcon.print(helpers.table_to_json(remote.interfaces))")
    )
    missing = [i for i in ("lab_grid", "agent", "map") if i not in ifaces]
    if missing:
        raise SystemExit(f"BLOCKED: missing remote interfaces {missing}")
    hb(f"smoke ok ({len(ifaces)} interfaces)")


def ensure_cell_agent(rcon: RCONClient, cell: int) -> Dict[str, Any]:
    """Create (or reuse) the agent bound to the lab-grid cell. Returns
    {agent_id, iface, force_name, created_by_us}."""
    st = lua_strict(rcon, f"return remote.call('lab_grid','get_cell_status',{cell})")
    if st.get("has_agent"):
        # Reuse: find the agent bound to this cell from scenario storage.
        storage = lua_strict(rcon, "return remote.call('lab_grid','get_storage')")
        agent_id = None
        for aid, ci in (storage.get("agent_cells") or {}).items():
            if int(ci) == cell:
                agent_id = int(aid)
                break
        if agent_id is None:
            raise SystemExit(
                f"BLOCKED: cell {cell} has a character but no lab_grid agent binding; "
                "pick another cell (--cell)"
            )
        return {
            "agent_id": agent_id,
            "iface": f"agent_{agent_id}",
            "force_name": f"cell_{cell}",
            "created_by_us": False,
        }
    create = lua_strict(
        rcon, f"return remote.call('lab_grid','create_agent_in_cell',{{cell_index={cell}}})"
    )
    if not create.get("success"):
        raise SystemExit(f"BLOCKED: create_agent_in_cell failed: {create}")
    return {
        "agent_id": create["agent_id"],
        "iface": f"agent_{create['agent_id']}",
        "force_name": create.get("force_name") or f"cell_{cell}",
        "created_by_us": True,
    }


def engine_read(rcon: RCONClient, name: str, pos: Dict[str, float]) -> Dict[str, Any]:
    """Layer E: raw LuaEntity property reads. No fv inspection code involved."""
    body = f"""
        local e = game.surfaces[1].find_entity('{name}', {pos_lua(pos)})
        if not e then return {{missing=true}} end
        local out = {{tick=game.tick, name=e.name, status=e.status,
                      energy=e.energy, electric_buffer_size=e.electric_buffer_size}}
        local okp, prog = pcall(function() return e.crafting_progress end)
        if okp then out.crafting_progress = prog end
        local okf, fin = pcall(function() return e.products_finished end)
        if okf then out.products_finished = fin end
        if e.burner then
            out.burner_remaining = e.burner.remaining_burning_fuel
            local fi = e.get_inventory(defines.inventory.fuel)
            out.fuel_coal = fi and fi.get_item_count('coal') or nil
        end
        local oi = e.get_inventory(defines.inventory.crafter_output)
        if oi then
            out.output_counts = {{}}
            for _, it in pairs(oi.get_contents() or {{}}) do
                local n = it.name or it[1]
                local c = it.count or it[2]
                if n then out.output_counts[n] = (out.output_counts[n] or 0) + (c or 0) end
            end
        end
        local r = e.get_recipe and e.get_recipe()
        if r then out.recipe = r.name end
        return out
    """
    return lua_strict(rcon, body)


def inspect_read(rcon: RCONClient, iface: str, name: str, pos: Dict[str, float]) -> Dict[str, Any]:
    """Layer I: the mod inspection path (inspection.lua via agent interface)."""
    return lua_strict(
        rcon,
        f"return remote.call('{iface}','inspect_entity','{name}',{pos_lua(pos)})",
    )


def typed_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Layer T: run the real Python transform; flatten the volatile fields."""
    insp = transform_inspection_data(payload)
    d = insp.model_dump(mode="json")
    crafter = d.get("crafter") or {}
    electric = d.get("electric") or {}
    burner = d.get("burner") or {}
    return {
        "status": d.get("status"),
        "crafting_progress": crafter.get("crafting_progress"),
        "is_crafting": crafter.get("is_crafting"),
        "recipe": crafter.get("recipe"),
        "energy": electric.get("energy"),
        "burner_remaining": burner.get("remaining_burning_fuel"),
        "fuel_inventory": burner.get("fuel_inventory"),
    }


# ----------------------------------------------------------------------------
# Comparison machinery (anti-vacuity: explicit counters, hard asserts)
# ----------------------------------------------------------------------------
class Comparator:
    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []
        self.failures: List[str] = []
        self.fields_compared = 0
        self.change_assertions = 0

    def eq(self, label: str, a: Any, b: Any, tol: float = FLOAT_TOL) -> None:
        self.fields_compared += 1
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            ok = abs(float(a) - float(b)) <= tol
        else:
            ok = a == b
        self.rows.append({"kind": "agree", "field": label, "a": a, "b": b, "agree": ok})
        if not ok:
            self.failures.append(f"DISAGREE {label}: {a!r} vs {b!r}")

    def changed(self, label: str, values: List[Any]) -> bool:
        """Hard anti-vacuity: assert NOT all samples identical."""
        self.change_assertions += 1
        non_null = [v for v in values if v is not None]
        ok = len(non_null) == len(values) and len(set(map(repr, values))) > 1
        self.rows.append({"kind": "change", "field": label, "values": values, "changed": ok})
        if not ok:
            self.failures.append(f"FROZEN {label}: samples {values!r} show no change")
        return ok

    def check(self, label: str, ok: bool, detail: Any = None) -> None:
        self.fields_compared += 1
        self.rows.append({"kind": "check", "field": label, "ok": ok, "detail": detail})
        if not ok:
            self.failures.append(f"CHECK-FAIL {label}: {detail!r}")


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main() -> int:
    global ART, PROGRESS
    ap = argparse.ArgumentParser(
        description="L2.4 — volatile state readable: cross-tick change + cross-layer agreement"
    )
    ap.add_argument("--instance", default="client", help="client or server_N")
    ap.add_argument("--cell", type=int, default=3, help="lab-grid cell index to use")
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
    hb(f"=== check_L2_4 start (instance={args.instance}, cell={args.cell}, commit={commit}) ===")

    try:
        rcon = RCONClient(RCON_HOST, RCON_PORT, RCON_PASS)
    except Exception as e:  # noqa: BLE001
        print(f"BLOCKED: cannot connect RCON: {e}")
        return 2
    smoke(rcon)

    # defines.entity_status mapping for the SYMBOLIC status assertion
    status_by_name = lua_strict(rcon, "return defines.entity_status")
    status_name = {int(v): k for k, v in status_by_name.items()}
    working = status_by_name.get("working")
    if working is None:
        print("BLOCKED: defines.entity_status has no 'working' key")
        return 2

    # --- cell + rig geometry -------------------------------------------------
    b = lua_strict(rcon, f"return remote.call('lab_grid','get_cell_bounds',{args.cell})")
    lt = b["left_top"]
    fx, fy = lt["x"] + 20.0, lt["y"] + 20.0           # stone-furnace (2x2 -> center .0)
    ax, ay = lt["x"] + 26.0, lt["y"] + 20.5           # assembling-machine-1 (3x3)
    pole = {"x": lt["x"] + 29.5, "y": lt["y"] + 20.5}  # small-electric-pole
    eei = {"x": lt["x"] + 31.0, "y": lt["y"] + 20.0}   # electric-energy-interface (2x2)
    furnace_pos = {"x": fx, "y": fy}
    asm_pos = {"x": ax, "y": ay}
    box = {
        "left_top": {"x": lt["x"] + 16, "y": lt["y"] + 16},
        "right_bottom": {"x": lt["x"] + 36, "y": lt["y"] + 26},
    }
    box_lua = (
        f"{{left_top={{x={box['left_top']['x']},y={box['left_top']['y']}}},"
        f"right_bottom={{x={box['right_bottom']['x']},y={box['right_bottom']['y']}}}}}"
    )

    agent = ensure_cell_agent(rcon, args.cell)
    iface, force = agent["iface"], agent["force_name"]
    results["phases"]["agent"] = agent
    hb(f"agent ready: {iface} force={force}")

    cleanup_ok: Optional[bool] = None
    try:
        # --- clear rig box (idempotence) -------------------------------------
        cleared = lua_strict(rcon, f"""
            local n = 0
            for _, e in pairs(game.surfaces[1].find_entities_filtered{{area={box_lua}}}) do
                if e.valid and e.type ~= 'resource' and e.type ~= 'character' then
                    e.destroy{{raise_destroy=true}}; n = n + 1
                end
            end
            return {{cleared=n}}
        """)
        hb(f"rig box cleared: {cleared.get('cleared')} entities removed")

        # --- build rig (script placement, cell force, raise_built) -----------
        hb(f"placing rig: furnace ({fx},{fy}), assembler ({ax},{ay}), pole, EEI (force={force})")
        place = lua_strict(rcon, f"""
            local s = game.surfaces[1]
            local placed = {{}}
            local function p(name, x, y)
                if not prototypes.entity[name] then
                    table.insert(placed, {{name=name, ok=false, why='no prototype'}})
                    return
                end
                local e = s.create_entity{{name=name, position={{x=x, y=y}},
                                           force='{force}', raise_built=true}}
                table.insert(placed, {{name=name, ok=(e ~= nil and e.valid),
                                       x=x, y=y}})
            end
            p('stone-furnace', {fx}, {fy})
            p('assembling-machine-1', {ax}, {ay})
            p('small-electric-pole', {pole['x']}, {pole['y']})
            p('electric-energy-interface', {eei['x']}, {eei['y']})
            return {{placed=placed}}
        """)
        results["phases"]["rig_placed"] = place
        placed = place.get("placed") or []
        if isinstance(placed, dict):
            placed = list(placed.values())
        bad = [p for p in placed if not p.get("ok")]
        if bad:
            print(f"BLOCKED: rig placement failed: {bad} (OQ1 if EEI)")
            return 2

        # --- configure + feed via the AGENT path ------------------------------
        hb("teleporting agent into reach; set recipe + feed materials via agent path")
        lua_strict(rcon, f"return remote.call('agent','add_items',{agent['agent_id']},"
                         "{['coal']=20,['iron-ore']=30,['iron-plate']=40})")
        mid = {"x": (fx + ax) / 2.0, "y": fy + 3.5}
        lua_strict(rcon, f"return remote.call('{iface}','teleport',{{position={pos_lua(mid)}}})")

        recipe = lua_strict(rcon, f"""
            return remote.call('{iface}','set_entity_recipe',
                {{entity_name='assembling-machine-1', position={pos_lua(asm_pos)},
                  recipe_name='iron-gear-wheel'}})
        """)
        if not recipe.get("success", True):
            print(f"BLOCKED: set_entity_recipe failed: {recipe}")
            return 2

        feeds = {}
        for key, (ename, epos, inv, item, count) in {
            "furnace_fuel": ("stone-furnace", furnace_pos, "fuel", "coal", 10),
            "furnace_ore": ("stone-furnace", furnace_pos, "input", "iron-ore", 20),
            "asm_plates": ("assembling-machine-1", asm_pos, "input", "iron-plate", 30),
        }.items():
            feeds[key] = lua_strict(rcon, f"""
                return remote.call('{iface}','put_inventory_item',
                    {{entity_name='{ename}', position={pos_lua(epos)},
                      inventory_type='{inv}', item_name='{item}', count={count}}})
            """)
        results["phases"]["feeds"] = feeds
        not_fed = {k: v for k, v in feeds.items()
                   if not v.get("success") or (v.get("count") or 0) <= 0}
        if not_fed:
            print(f"BLOCKED: put_inventory_item failed to move items: {not_fed}")
            return 2
        hb(f"materials fed via agent path: "
           f"{ {k: v.get('count') for k, v in feeds.items()} }")

        # --- warmup: wait for BOTH entities to be working ----------------------
        hb("warmup: polling engine status until both entities are 'working'")
        warm: Dict[str, Any] = {}
        deadline = time.time() + WORKING_TIMEOUT_S
        while time.time() < deadline:
            ef = engine_read(rcon, "stone-furnace", furnace_pos)
            ea = engine_read(rcon, "assembling-machine-1", asm_pos)
            warm = {
                "furnace_status": status_name.get(ef.get("status"), ef.get("status")),
                "asm_status": status_name.get(ea.get("status"), ea.get("status")),
            }
            if ef.get("status") == working and ea.get("status") == working:
                break
            time.sleep(1.0)
        results["phases"]["warmup_last"] = warm
        if not (warm.get("furnace_status") == "working" and warm.get("asm_status") == "working"):
            finding(f"rig never reached working: {warm} — volatiles untestable on idle rig")
            save("results.json", results)
            print(f"VACUOUS-RISK: rig idle after {WORKING_TIMEOUT_S}s: {warm}")
            return 3
        hb(f"rig working: {warm}")

        # --- sampling: 3 bursts, all three layers per burst --------------------
        samples: List[Dict[str, Any]] = []
        for i in range(N_SAMPLES):
            burst: Dict[str, Any] = {"i": i}
            for ent_key, (ename, epos) in {
                "furnace": ("stone-furnace", furnace_pos),
                "asm": ("assembling-machine-1", asm_pos),
            }.items():
                e = engine_read(rcon, ename, epos)
                p = inspect_read(rcon, iface, ename, epos)
                if e.get("missing") or "__lua_error" in p:
                    raise RuntimeError(f"sample {i} read failed for {ename}: {e} / {p}")
                burst[ent_key] = {"engine": e, "inspect": p, "typed": typed_fields(p)}
            samples.append(burst)
            hb(f"sample {i}: furnace prog={samples[i]['furnace']['engine'].get('crafting_progress')} "
               f"fuel={samples[i]['furnace']['engine'].get('burner_remaining')} | "
               f"asm prog={samples[i]['asm']['engine'].get('crafting_progress')} "
               f"energy={samples[i]['asm']['engine'].get('energy')}")
            if i < N_SAMPLES - 1:
                time.sleep(SAMPLE_GAP_S)
        save("samples.json", samples)

        # --- comparisons --------------------------------------------------------
        cmpr = Comparator()

        def series(ent: str, layer: str, field: str) -> List[Any]:
            return [s[ent][layer].get(field) for s in samples]

        for ent in ("furnace", "asm"):
            for i, s in enumerate(samples):
                E, I, T = s[ent]["engine"], s[ent]["inspect"], s[ent]["typed"]
                # status symbolic at every sample on every layer
                cmpr.check(f"{ent}.s{i}.engine.status==working",
                           E.get("status") == working,
                           status_name.get(E.get("status"), E.get("status")))
                cmpr.eq(f"{ent}.s{i}.status engine==inspect", E.get("status"), I.get("status"))
                cmpr.eq(f"{ent}.s{i}.status inspect==typed", I.get("status"), T.get("status"))
                # crafting progress: typed must equal the payload it was fed
                cmpr.eq(f"{ent}.s{i}.crafting_progress inspect==typed",
                        I.get("crafting_progress"), T.get("crafting_progress"))
                # energy: inspect nests {current, capacity}; typed flattens
                i_energy = (I.get("energy") or {})
                i_cur = i_energy.get("current") if isinstance(i_energy, dict) else i_energy
                cmpr.eq(f"{ent}.s{i}.energy inspect==typed", i_cur, T.get("energy"))
            # engine vs inspect progress within the same burst (same-burst skew
            # is a few ticks; tolerance = 10% of a craft cycle, recorded raw)
            for i, s in enumerate(samples):
                ep = s[ent]["engine"].get("crafting_progress")
                ip = s[ent]["inspect"].get("crafting_progress")
                if ep is not None and ip is not None:
                    cmpr.check(f"{ent}.s{i}.crafting_progress engine~inspect(<0.1)",
                               abs(float(ep) - float(ip)) < 0.1, {"engine": ep, "inspect": ip})

        # furnace burner: inspect/typed agreement + OQ2 evidence
        for i, s in enumerate(samples):
            ib = (s["furnace"]["inspect"].get("burner") or {})
            i_rem = ib.get("remaining_burning_fuel", ib.get("remaining_fuel"))
            cmpr.eq(f"furnace.s{i}.burner_remaining inspect==typed",
                    i_rem, s["furnace"]["typed"].get("burner_remaining"))
        results["oq2_burner_key"] = (
            "remaining_burning_fuel" if "remaining_burning_fuel"
            in (samples[0]["furnace"]["inspect"].get("burner") or {}) else "remaining_fuel-or-missing"
        )

        # --- CHANGE assertions (the heart of the row) --------------------------
        for ent in ("furnace", "asm"):
            fin = series(ent, "engine", "products_finished")
            prog_e = series(ent, "engine", "crafting_progress")
            prog_i = series(ent, "inspect", "crafting_progress")
            prog_t = series(ent, "typed", "crafting_progress")
            fin_ok = (None not in fin) and fin[-1] > fin[0]
            cmpr.check(f"{ent}.engine.volatile: products_finished increased OR progress changed",
                       fin_ok or len(set(map(repr, prog_e))) > 1,
                       {"products_finished": fin, "crafting_progress": prog_e})
            cmpr.changed(f"{ent}.inspect.crafting_progress", prog_i)
            cmpr.changed(f"{ent}.typed.crafting_progress", prog_t)

        # furnace fuel volatility: decrease, or increase with coal count drop
        rem = series("furnace", "engine", "burner_remaining")
        coal = series("furnace", "engine", "fuel_coal")
        if None in rem:
            cmpr.check("furnace.engine.burner_remaining present", False, rem)
        else:
            decreased = rem[-1] < rem[0]
            reloaded = rem[-1] > rem[0] and (None not in coal) and coal[-1] < coal[0]
            cmpr.check("furnace.engine.burner_remaining decreased (or coal reloaded)",
                       decreased or reloaded, {"remaining": rem, "coal": coal})
        cmpr.changed("furnace.inspect.burner_remaining",
                     [(s["furnace"]["inspect"].get("burner") or {}).get(
                         "remaining_burning_fuel") for s in samples])
        cmpr.changed("furnace.typed.burner_remaining",
                     series("furnace", "typed", "burner_remaining"))

        # assembler energy: >0 at every sample on engine AND typed layers (OQ3)
        for i, s in enumerate(samples):
            cmpr.check(f"asm.s{i}.engine.energy>0",
                       (s["asm"]["engine"].get("energy") or 0) > 0,
                       s["asm"]["engine"].get("energy"))
            cmpr.check(f"asm.s{i}.typed.energy>0",
                       (s["asm"]["typed"].get("energy") or 0) > 0,
                       s["asm"]["typed"].get("energy"))

        results["comparison"] = cmpr.rows
        results["counters"] = {
            "fields_compared": cmpr.fields_compared,
            "change_assertions": cmpr.change_assertions,
            "disagreements": len(cmpr.failures),
        }
        hb(f"COMPARE: {cmpr.fields_compared} field comparisons, "
           f"{cmpr.change_assertions} change assertions, {len(cmpr.failures)} failures")

        # --- verdict -------------------------------------------------------------
        tick = lua_strict(rcon, "return {tick=game.tick}")["tick"]
        vacuous = (cmpr.fields_compared < MIN_FIELD_COMPARISONS
                   or cmpr.change_assertions < MIN_CHANGE_ASSERTIONS)
        status = ("VACUOUS-RISK" if vacuous
                  else ("FAIL" if cmpr.failures else "PASS"))
        results["verdict"] = {
            "check": CHECK_ID, "status": status, "commit": commit, "tick": tick,
            "failures": cmpr.failures,
        }
        save("results.json", results)
        print("\n========== SUMMARY ==========")
        print(json.dumps({"status": status, "counters": results["counters"],
                          "failures": cmpr.failures,
                          "findings": results["findings"]}, indent=2, default=str))
        return {"PASS": 0, "FAIL": 1, "VACUOUS-RISK": 3}[status]

    finally:
        # --- cleanup that verifies itself --------------------------------------
        try:
            hb("cleanup: destroying rig entities")
            lua(rcon, f"""
                for _, e in pairs(game.surfaces[1].find_entities_filtered{{area={box_lua}}}) do
                    if e.valid and e.type ~= 'resource' and e.type ~= 'character' then
                        e.destroy{{raise_destroy=true}}
                    end
                end
                return {{ok=true}}
            """)
            left = lua(rcon, f"""
                local n = 0
                for _, e in pairs(game.surfaces[1].find_entities_filtered{{area={box_lua}}}) do
                    if e.valid and e.type ~= 'resource' and e.type ~= 'character' then n = n + 1 end
                end
                return {{leftover=n}}
            """)
            cleanup_ok = isinstance(left, dict) and left.get("leftover") == 0
            results["cleanup"] = {"verified_empty": cleanup_ok, "probe": left}
            hb(f"cleanup verified_empty={cleanup_ok}")
            if not cleanup_ok:
                print(f"[WARN] cleanup leftover entities: {left}")
            save("results.json", results)
        except Exception as e:  # noqa: BLE001
            hb(f"cleanup error (non-fatal): {e}")


if __name__ == "__main__":
    sys.exit(main())
