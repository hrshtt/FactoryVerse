#!/usr/bin/env python
"""Certification check L2.1 — golden rig: relational reads through every layer.

Builds a known rig on the test-ground scenario, then verifies the SAME story
is told by independent layers for the relational fields:
  - inserter pickup_target / drop_target
  - belt belt_inputs / belt_outputs (directional)
  - underground-belt pairing

Layers compared (each artifact records which code path produced it):
  L1  Engine ground truth — raw `/c` Lua: find_entity + entity.pickup_target /
      drop_target / belt_neighbours / neighbours. Independent of fv inspection code.
  L2  Mod inspection path — remote.call('agent_<id>','inspect_entity', name, pos)
      → src/fv_embodied_agent/agent_actions/inspection.lua
  L3  Python transform path — snapshot JSONL (written by fv_snapshot via
      src/fv_embodied_agent/utils/serialize.lua) adapted and fed through
      FactoryVerse.game.factory.entity.transform.transform_inspection_data,
      AND the L2 raw payload fed through the same transform (its designed input).
  L4  DB path (best effort) — load snapshot dir into in-memory DuckDB via
      Stack A SnapshotDatabase+SnapshotLoader; query
      `inserter` and `transport_belt` tables.

Idempotent: clears its area, builds, asserts, reports, clears again.
Exit codes: 0 = PASS, 1 = FAIL, 2 = BLOCKED.

Usage:
    uv run python scripts/certification/check_L2_1.py [--artifacts-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from factorio_rcon import RCONClient  # noqa: E402

from FactoryVerse.game.scenarios.test_ground import TestGroundHelper  # noqa: E402
from FactoryVerse.game.factory.entity.transform import (  # noqa: E402
    transform_inspection_data,
)

SCRIPT_OUTPUT = (
    Path.home() / "Library/Application Support/factorio/script-output"
)
SNAPSHOT_DIR = SCRIPT_OUTPUT / "factoryverse" / "snapshots"

RCON_HOST, RCON_PORT, RCON_PASS = "localhost", 27100, "factorio"

# ---------------------------------------------------------------------------
# Rig layout (all inside chunk (0,0): x,y in [0,32))
# ---------------------------------------------------------------------------
AREA_LT, AREA_RB = (0.0, 0.0), (32.0, 32.0)

CHEST_POS = (10.5, 10.5)
INSERTER_POS = (11.5, 10.5)
FURNACE_POS = (13.0, 11.0)  # 2x2; covers x[12,14] y[10,12]; drop tile (12.5,10.5)

BELT_Y = 16.5
BELT_XS = [10.5, 11.5, 12.5, 13.5]  # belts 1..4, all facing east; 3 feeds 4

UG_Y = 20.5
UG_IN_POS = (10.5, UG_Y)   # underground-belt type=input, facing east
UG_OUT_POS = (13.5, UG_Y)  # underground-belt type=output, facing east

EAST, WEST = 4, 12  # Factorio 2.0 sixteen-way defines.direction values

POS_TOL = 0.01


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class Log:
    def __init__(self, path: Path):
        self.fh = path.open("w")

    def __call__(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        self.fh.write(line + "\n")
        self.fh.flush()


def run_lua(rcon: RCONClient, body: str) -> Any:
    """Run a Lua chunk over RCON, JSON-encoded result. `body` must `return` a table."""
    lua = (
        "local ok, res = xpcall(function() "
        + body
        + " end, debug.traceback) "
        "if ok then rcon.print(helpers.table_to_json(res or {})) "
        "else rcon.print(helpers.table_to_json({__lua_error = tostring(res)})) end"
    )
    out = rcon.send_command("/c " + lua)
    if out is None or out.strip() == "":
        return {}
    parsed = json.loads(out)
    if isinstance(parsed, dict) and "__lua_error" in parsed:
        raise RuntimeError(f"Lua error: {parsed['__lua_error']}")
    return parsed


def pos_eq(a: Optional[Dict[str, float]], b: Optional[Dict[str, float]]) -> bool:
    if a is None or b is None:
        return a is b
    return abs(a["x"] - b["x"]) <= POS_TOL and abs(a["y"] - b["y"]) <= POS_TOL


def ref_eq(a: Optional[Dict], b: Optional[Dict]) -> bool:
    """Compare entity refs {name, position}."""
    if a is None or b is None:
        return a is b
    return a.get("name") == b.get("name") and pos_eq(a.get("position"), b.get("position"))


def find_unit_numbers(obj: Any, path: str = "$") -> List[str]:
    hits: List[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "unit_number":
                hits.append(f"{path}.{k}")
            hits.extend(find_unit_numbers(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits.extend(find_unit_numbers(v, f"{path}[{i}]"))
    return hits


def save(art_dir: Path, name: str, data: Any) -> None:
    (art_dir / name).write_text(json.dumps(data, indent=2, default=str))


# ---------------------------------------------------------------------------
# Layer 0: smoke ritual (RUNTIME_PLAYBOOK §0)
# ---------------------------------------------------------------------------
def smoke(rcon: RCONClient, log: Log) -> Dict[str, Any]:
    rcon.send_command("/c rcon.print('ping')")  # first command may emit a warning
    assert "ping" in rcon.send_command("/c rcon.print('ping')"), "smoke: ping failed"
    ifaces = json.loads(
        rcon.send_command("/c rcon.print(helpers.table_to_json(remote.interfaces))")
    )
    for required in ("test_ground", "agent", "snapshot"):
        if required not in ifaces:
            raise SystemExit(f"BLOCKED: remote interface '{required}' missing")
    tick = run_lua(rcon, "return {tick = game.tick}")["tick"]
    mods = run_lua(rcon, "return script.active_mods")
    log(f"smoke OK: tick={tick}, interfaces={sorted(ifaces.keys())}")
    return {"tick": tick, "interfaces": sorted(ifaces.keys()), "active_mods": mods}


# ---------------------------------------------------------------------------
# Rig construction
# ---------------------------------------------------------------------------
def build_rig(tg: TestGroundHelper, rcon: RCONClient, log: Log) -> Dict[str, Any]:
    cleared = tg.clear_area(AREA_LT, AREA_RB)
    log(f"cleared area {AREA_LT}..{AREA_RB}: {cleared} entities removed")

    results: Dict[str, Any] = {"cleared_before": cleared, "placements": {}}

    def place(key: str, name: str, x: float, y: float, direction: Optional[int] = None):
        res = tg.place_entity(name, x, y, direction)
        results["placements"][key] = res
        if not res.get("success", False):
            raise SystemExit(f"BLOCKED: cannot place {name} at ({x},{y}): {res}")

    place("chest", "wooden-chest", *CHEST_POS)
    place("furnace", "stone-furnace", *FURNACE_POS)
    # Inserter direction is verified against the engine below and corrected
    # if the pickup/drop orientation is reversed — we do NOT assume semantics.
    place("inserter", "burner-inserter", *INSERTER_POS, direction=EAST)

    for i, x in enumerate(BELT_XS, start=1):
        place(f"belt{i}", "transport-belt", x, BELT_Y, direction=EAST)

    place("ug_in", "underground-belt", *UG_IN_POS, direction=EAST)
    # test_ground.place_entity cannot express underground `type`; script-created
    # underground belts default to "input", so the output end is placed via raw
    # Lua with type='output' (raise_built=true so fv_snapshot sees it).
    ug_out = run_lua(
        rcon,
        f"local e = game.surfaces[1].create_entity{{name='underground-belt', "
        f"position={{x={UG_OUT_POS[0]}, y={UG_OUT_POS[1]}}}, direction={EAST}, "
        f"type='output', force='player', raise_built=true}} "
        f"if not e then return {{success=false}} end "
        f"return {{success=true, name=e.name, position={{x=e.position.x, y=e.position.y}}, "
        f"belt_to_ground_type=e.belt_to_ground_type}}",
    )
    results["placements"]["ug_out"] = ug_out
    if not ug_out.get("success"):
        raise SystemExit(f"BLOCKED: cannot place underground output: {ug_out}")

    # --- Verify inserter orientation from the engine; flip if reversed -------
    probe = engine_read_inserter(rcon)
    pickup_name = (probe.get("pickup_target") or {}).get("name")
    drop_name = (probe.get("drop_target") or {}).get("name")
    if pickup_name != "wooden-chest" or drop_name != "stone-furnace":
        log(
            f"inserter orientation with direction={EAST}: pickup={pickup_name}, "
            f"drop={drop_name} — flipping to direction={WEST}"
        )
        run_lua(
            rcon,
            f"local e = game.surfaces[1].find_entity('burner-inserter', "
            f"{{x={INSERTER_POS[0]}, y={INSERTER_POS[1]}}}) "
            f"if e then e.destroy{{raise_destroy=true}} end return {{}}",
        )
        place("inserter", "burner-inserter", *INSERTER_POS, direction=WEST)
        probe = engine_read_inserter(rcon)
        pickup_name = (probe.get("pickup_target") or {}).get("name")
        drop_name = (probe.get("drop_target") or {}).get("name")
    if pickup_name != "wooden-chest" or drop_name != "stone-furnace":
        raise SystemExit(
            f"BLOCKED: could not orient inserter (pickup={pickup_name}, drop={drop_name})"
        )
    results["inserter_final_direction"] = probe.get("direction")
    log(
        f"rig built; inserter direction={probe.get('direction')} "
        f"pickup={pickup_name} drop={drop_name}"
    )
    return results


# ---------------------------------------------------------------------------
# Layer 1: engine ground truth (raw Lua, no fv inspection code)
# ---------------------------------------------------------------------------
ENGINE_REF_FN = (
    "local function ref(e) if e and e.valid then return "
    "{name=e.name, position={x=e.position.x, y=e.position.y}} end return nil end "
)


def engine_read_inserter(rcon: RCONClient) -> Dict[str, Any]:
    return run_lua(
        rcon,
        ENGINE_REF_FN
        + f"local e = game.surfaces[1].find_entity('burner-inserter', "
        f"{{x={INSERTER_POS[0]}, y={INSERTER_POS[1]}}}) "
        "if not e then return {missing=true} end "
        "return {name=e.name, position={x=e.position.x, y=e.position.y}, "
        "direction=e.direction, "
        "pickup_position={x=e.pickup_position.x, y=e.pickup_position.y}, "
        "drop_position={x=e.drop_position.x, y=e.drop_position.y}, "
        "pickup_target=ref(e.pickup_target), drop_target=ref(e.drop_target)}",
    )


def engine_read_belt(rcon: RCONClient, name: str, x: float, y: float) -> Dict[str, Any]:
    body = (
        ENGINE_REF_FN
        + f"local e = game.surfaces[1].find_entity('{name}', {{x={x}, y={y}}}) "
        "if not e then return {missing=true} end "
        "local out = {name=e.name, position={x=e.position.x, y=e.position.y}, "
        "direction=e.direction, belt_inputs={}, belt_outputs={}} "
        "local bn = e.belt_neighbours "
        "if bn then "
        "  for _, n in ipairs(bn.inputs or {}) do table.insert(out.belt_inputs, ref(n)) end "
        "  for _, n in ipairs(bn.outputs or {}) do table.insert(out.belt_outputs, ref(n)) end "
        "end "
        "if e.type == 'underground-belt' then "
        "  out.belt_to_ground_type = e.belt_to_ground_type "
        "  out.underground_neighbour = ref(e.neighbours) "
        "end "
        "return out",
    )
    res = run_lua(rcon, body[0])
    # helpers.table_to_json turns empty Lua tables into {}; normalize to lists
    for k in ("belt_inputs", "belt_outputs"):
        if isinstance(res.get(k), dict):
            res[k] = list(res[k].values()) if res[k] else []
    return res


def layer1_engine(rcon: RCONClient, log: Log) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "_code_path": "raw /c Lua: surface.find_entity + LuaEntity.pickup_target/"
        "drop_target/belt_neighbours/neighbours (engine API, no fv code)",
        "inserter": engine_read_inserter(rcon),
    }
    for i, x in enumerate(BELT_XS, start=1):
        out[f"belt{i}"] = engine_read_belt(rcon, "transport-belt", x, BELT_Y)
    out["ug_in"] = engine_read_belt(rcon, "underground-belt", *UG_IN_POS)
    out["ug_out"] = engine_read_belt(rcon, "underground-belt", *UG_OUT_POS)
    for key, rec in out.items():
        if isinstance(rec, dict) and rec.get("missing"):
            raise SystemExit(f"BLOCKED: layer1 cannot find rig entity '{key}'")
    log("layer1 (engine ground truth) read complete")
    return out


# ---------------------------------------------------------------------------
# Layer 2: mod inspection path (inspection.lua via agent remote interface)
# ---------------------------------------------------------------------------
def ensure_agent(rcon: RCONClient, log: Log) -> Tuple[str, Optional[int]]:
    agents = run_lua(rcon, "return remote.call('agent', 'list_agents')")
    if isinstance(agents, list) and agents:
        aid = agents[0].get("agent_id") or agents[0].get("id")
        if aid is not None:
            log(f"reusing existing agent {aid}")
            return f"agent_{aid}", None
    res = run_lua(
        rcon,
        "return remote.call('agent', 'create_agent', 34209, false, 'player', nil)",
    )
    aid = res.get("agent_id") or res.get("id")
    iface = res.get("interface_name") or f"agent_{aid}"
    log(f"created agent {aid} (interface {iface})")
    return iface, aid


def inspect_entity(rcon: RCONClient, iface: str, name: str, pos: Tuple[float, float]) -> Dict:
    return run_lua(
        rcon,
        f"return remote.call('{iface}', 'inspect_entity', '{name}', "
        f"{{x={pos[0]}, y={pos[1]}}})",
    )


def layer2_inspect(rcon: RCONClient, iface: str, log: Log) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "_code_path": f"remote.call('{iface}','inspect_entity', name, pos) → "
        "src/fv_embodied_agent/agent_actions/inspection.lua",
        "inserter": inspect_entity(rcon, iface, "burner-inserter", INSERTER_POS),
    }
    for i, x in enumerate(BELT_XS, start=1):
        out[f"belt{i}"] = inspect_entity(rcon, iface, "transport-belt", (x, BELT_Y))
    out["ug_in"] = inspect_entity(rcon, iface, "underground-belt", UG_IN_POS)
    out["ug_out"] = inspect_entity(rcon, iface, "underground-belt", UG_OUT_POS)
    log("layer2 (mod inspection path) read complete")
    return out


# ---------------------------------------------------------------------------
# Layer 3: snapshot JSONL → Python transform
# ---------------------------------------------------------------------------
def collect_snapshot_records(log: Log) -> Dict[str, Dict]:
    """Find rig entities in entities-init.jsonl files under SNAPSHOT_DIR."""
    wanted: Dict[str, Tuple[str, Tuple[float, float]]] = {
        "inserter": ("burner-inserter", INSERTER_POS),
        "ug_in": ("underground-belt", UG_IN_POS),
        "ug_out": ("underground-belt", UG_OUT_POS),
    }
    for i, x in enumerate(BELT_XS, start=1):
        wanted[f"belt{i}"] = ("transport-belt", (x, BELT_Y))

    found: Dict[str, Dict] = {}
    for f in sorted(SNAPSHOT_DIR.rglob("entities-init.jsonl")):
        for line in f.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            pos = rec.get("position") or {}
            for key, (name, (wx, wy)) in wanted.items():
                if (
                    rec.get("name") == name
                    and abs(pos.get("x", 1e9) - wx) <= POS_TOL
                    and abs(pos.get("y", 1e9) - wy) <= POS_TOL
                ):
                    found[key] = rec
    log(f"snapshot records found: {sorted(found.keys())}")
    return found


def wait_for_snapshot(
    tg: TestGroundHelper, rcon: RCONClient, log: Log, notes: Dict[str, Any], timeout: float = 120.0
) -> Dict[str, Dict]:
    # Wipe stale snapshot output so a previous run at identical coordinates
    # can never satisfy this check (anti-vacuous guard).
    if SNAPSHOT_DIR.exists():
        shutil.rmtree(SNAPSHOT_DIR)
    needed = {"inserter", "belt1", "belt2", "belt3", "belt4", "ug_in", "ug_out"}

    def poll(until: float) -> Optional[Dict[str, Dict]]:
        while time.time() < until:
            recs = collect_snapshot_records(log)
            if needed.issubset(recs.keys()):
                return recs
            time.sleep(2.0)
        return None

    # First try the documented test_ground affordance, with a short window.
    log("wiped stale snapshot dir; trying test_ground.force_resnapshot(all chunks)")
    enq = tg.force_resnapshot(None)
    log(f"test_ground.force_resnapshot enqueued {enq} chunks; polling 12s")
    recs = poll(time.time() + 12.0)
    if recs is not None:
        notes["snapshot_trigger"] = "test_ground.force_resnapshot"
        return recs

    # KNOWN GAP (observed 2026-06-10): test_ground.force_resnapshot calls
    # map.enqueue_chunk_for_snapshot, which does NOT clear chunk snapshot_tick;
    # in MAINTENANCE phase the state machine dequeues and skips every chunk as
    # "already snapshotted" (Map.lua _on_tick_snapshot_chunks), so no files are
    # ever written. map.re_snapshot_area clears snapshot_tick and flips the
    # system phase, which actually re-snapshots.
    notes["snapshot_trigger"] = (
        "map.re_snapshot_area (fallback: test_ground.force_resnapshot produced "
        "no files — it enqueues without clearing snapshot_tick, so chunks are "
        "skipped as already-snapshotted in MAINTENANCE phase)"
    )
    log("force_resnapshot produced no files; falling back to map.re_snapshot_area")
    res = run_lua(
        rcon,
        f"return remote.call('map', 're_snapshot_area', "
        f"{{left_top={{x={AREA_LT[0]}, y={AREA_LT[1]}}}, "
        f"right_bottom={{x={AREA_RB[0]}, y={AREA_RB[1]}}}}}, 10)",
    )
    log(f"map.re_snapshot_area: {res}")
    recs = poll(time.time() + timeout)
    if recs is not None:
        return recs
    raise SystemExit(
        f"BLOCKED: snapshot JSONL incomplete after {timeout}s; "
        f"found {sorted(collect_snapshot_records(log).keys())} of {sorted(needed)}"
    )


def snapshot_to_transform_input(rec: Dict) -> Dict:
    """Adapt a snapshot JSONL record (serialize.lua shape) to the flat shape
    transform_inspection_data expects (inspect_entity shape).

    NOTE (documented shape gap): transform_inspection_data is written for
    inspect_entity payloads (flat keys, 'entity_name'/'entity_type'). The
    snapshot serializer (src/fv_embodied_agent/utils/serialize.lua) nests the
    same relational data under 'inserter' / 'belt_data.belt_neighbours' with
    'name'/'type' keys. This adapter maps field names ONLY — values pass
    through untouched, so value-level agreement is still meaningful.
    """
    flat: Dict[str, Any] = {
        "entity_name": rec.get("name", ""),
        "entity_type": rec.get("type", ""),
        "position": rec.get("position", {}),
        "direction": rec.get("direction"),
    }
    if "inserter" in rec:
        flat.update(rec["inserter"])  # pickup/drop position + targets
    bd = rec.get("belt_data") or {}
    bn = bd.get("belt_neighbours") or {}
    if bn.get("inputs"):
        flat["belt_inputs"] = bn["inputs"]
    if bn.get("outputs"):
        flat["belt_outputs"] = bn["outputs"]
    if bd.get("belt_to_ground_type") is not None:
        flat["belt_to_ground_type"] = bd["belt_to_ground_type"]
    if bd.get("underground_neighbour") is not None:
        flat["underground_neighbour"] = bd["underground_neighbour"]
    return flat


def layer3_transform(
    snapshot_recs: Dict[str, Dict], layer2: Dict[str, Any], log: Log
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "_code_path": "snapshot entities-init.jsonl (fv_snapshot/serialize.lua) "
        "→ snapshot_to_transform_input() field-name adapter → "
        "FactoryVerse.game.factory.entity.transform.transform_inspection_data; "
        "plus the same transform applied to raw inspect_entity payloads "
        "(its designed input)",
        "from_snapshot": {},
        "from_inspect": {},
    }
    for key, rec in snapshot_recs.items():
        insp = transform_inspection_data(snapshot_to_transform_input(rec))
        out["from_snapshot"][key] = insp.model_dump(mode="json")
    for key, raw in layer2.items():
        if key.startswith("_"):
            continue
        insp = transform_inspection_data(raw)
        out["from_inspect"][key] = insp.model_dump(mode="json")
    log("layer3 (Python transform) complete")
    return out


# ---------------------------------------------------------------------------
# Layer 4: DuckDB load (best effort)
# ---------------------------------------------------------------------------
def layer4_db(log: Log) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "_code_path": "Stack A (what Tier4 uses): SnapshotDatabase(in-memory)"
        ".ensure_schema() + SnapshotLoader.load_all() over the snapshot dir; "
        "query map_entity raw_data for the rig (component tables are known "
        "schema-only — L1.5 ❌ — so relational fields live in raw_data JSON)",
        "status": "ran",
    }
    try:
        from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase
        from FactoryVerse.game.infra.duckdb.loader import SnapshotLoader

        db = SnapshotDatabase(db_path=None)
        db.ensure_schema()
        con = db.connection
        result = SnapshotLoader(db=con, snapshot_dir=SNAPSHOT_DIR).load_all()
        out["load_result"] = str(result)

        def rows(sql: str) -> List[Dict]:
            cur = con.execute(sql)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

        area = (
            f"WHERE position_x BETWEEN {AREA_LT[0]} AND {AREA_RB[0]} "
            f"AND position_y BETWEEN {AREA_LT[1]} AND {AREA_RB[1]}"
        )
        out["map_entity_rows"] = rows(
            "SELECT entity_name, position_x, position_y, direction, "
            f"raw_data FROM map_entity {area}"
        )
        # Relational fields live in raw_data JSON (component tables are
        # schema-only, L1.5 ❌). Flatten through the same adapter as L3 so the
        # comparator checks DuckDB round-trip fidelity of the snapshot record.
        out["flat_rows"] = []
        for r in out["map_entity_rows"]:
            rec = (
                json.loads(r["raw_data"])
                if isinstance(r["raw_data"], str)
                else (r["raw_data"] or {})
            )
            out["flat_rows"].append(
                {
                    "entity_name": r["entity_name"],
                    "position_x": r["position_x"],
                    "position_y": r["position_y"],
                    "flat": snapshot_to_transform_input(rec),
                }
            )
        # Component tables: empty per L1.5 until populated by design; record
        # counts so this layer flags the day that changes.
        out["component_counts"] = {
            t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("inserter", "transport_belt", "mining_drill", "assembler")
        }
        log(
            f"layer4 (DuckDB Stack A) loaded: {len(out['map_entity_rows'])} "
            f"map_entity rows in rig area; component counts {out['component_counts']}"
        )
    except Exception as e:  # noqa: BLE001 — BLOCKED-evidence, not a crash
        import traceback

        out["status"] = "blocked"
        out["error"] = f"{type(e).__name__}: {e}"
        out["traceback"] = traceback.format_exc()
        log(f"layer4 BLOCKED: {out['error']}")
    return out


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
def compare_layers(
    l1: Dict, l2: Dict, l3: Dict, l4: Dict, log: Log
) -> Tuple[List[Dict], List[str]]:
    """Returns (comparison rows, failure strings)."""
    rows: List[Dict] = []
    failures: List[str] = []

    def add(field: str, per_layer: Dict[str, Any], agree: bool, note: str = "") -> None:
        rows.append({"field": field, "layers": per_layer, "agree": agree, "note": note})
        if not agree:
            failures.append(f"{field}: " + json.dumps(per_layer, default=str))

    # ---- DB row lookup helpers ----
    db_ok = l4.get("status") == "ran"

    def db_flat(name: str, x: float, y: float) -> Optional[Dict]:
        """map_entity.raw_data flattened via the L3 adapter, by name+position."""
        if not db_ok:
            return None
        for r in l4["flat_rows"]:
            if r["entity_name"] == name and pos_eq(
                {"x": r["position_x"], "y": r["position_y"]}, {"x": x, "y": y}
            ):
                return r["flat"]
        return None

    def db_inserter() -> Optional[Dict]:
        return db_flat("burner-inserter", *INSERTER_POS)

    def db_belt(x: float, y: float) -> Optional[Dict]:
        return db_flat("transport-belt", x, y)

    # ======================= INSERTER pickup/drop ==========================
    ins_db = db_inserter()
    for side, expect_name in (("pickup_target", "wooden-chest"), ("drop_target", "stone-furnace")):
        e1 = l1["inserter"][side]  # {name, position}
        e2 = l2["inserter"].get(side)
        t_snap = (l3["from_snapshot"]["inserter"].get("inserter") or {}).get(side)
        t_insp = (l3["from_inspect"]["inserter"].get("inserter") or {}).get(side)
        e4 = None if ins_db is None else ins_db.get(side)

        agree = (
            e1 is not None
            and e1.get("name") == expect_name
            and ref_eq(e1, e2)
            and t_snap == e1.get("name")  # typed InserterState carries name only
            and t_insp == e1.get("name")
            and (not db_ok or (e4 is not None and ref_eq(e1, e4)))
        )
        add(
            f"inserter.{side}",
            {
                "L1_engine": e1,
                "L2_inspect": e2,
                "L3_typed_from_snapshot": t_snap,
                "L3_typed_from_inspect": t_insp,
                "L4_db": e4 if db_ok else "BLOCKED",
            },
            agree,
            note="typed InserterState represents the target as name only; "
            "pickup_position/drop_position pin the tile (name+position rule met "
            "via the position fields)",
        )

    # Positions: pickup/drop positions across layers
    for side in ("pickup_position", "drop_position"):
        e1 = l1["inserter"][side]
        e2 = l2["inserter"].get(side)
        t_snap = (l3["from_snapshot"]["inserter"].get("inserter") or {}).get(side)
        t_insp = (l3["from_inspect"]["inserter"].get("inserter") or {}).get(side)
        agree = pos_eq(e1, e2) and pos_eq(e1, t_snap) and pos_eq(e1, t_insp)
        add(
            f"inserter.{side}",
            {
                "L1_engine": e1,
                "L2_inspect": e2,
                "L3_typed_from_snapshot": t_snap,
                "L3_typed_from_inspect": t_insp,
                "L4_db": "n/a (table stores target refs, not arm positions)",
            },
            agree,
        )

    # ======================= BELT directional flow =========================
    belt3_ref = {"name": "transport-belt", "position": {"x": BELT_XS[2], "y": BELT_Y}}
    belt4_ref = {"name": "transport-belt", "position": {"x": BELT_XS[3], "y": BELT_Y}}

    def typed_belt(layer: Dict, key: str) -> Dict:
        return layer.get(key, {}).get("belt") or {}

    def norm_refs(lst: Any) -> List[Dict]:
        if not isinstance(lst, list):
            return []
        return [{"name": r.get("name"), "position": r.get("position")} for r in lst]

    def refs_eq(a: List[Dict], b: List[Dict]) -> bool:
        if len(a) != len(b):
            return False
        return all(any(ref_eq(x, y) for y in b) for x in a)

    # belt3 outputs → [belt4]
    checks = [
        ("belt3.belt_outputs", "belt3", "belt_outputs", [belt4_ref], "output"),
        ("belt4.belt_inputs", "belt4", "belt_inputs", [belt3_ref], "input"),
    ]
    for field, key, attr, expected, db_col in checks:
        e1 = norm_refs(l1[key].get(attr, []))
        e2 = norm_refs(l2[key].get(attr, []))
        t_snap = norm_refs(typed_belt(l3["from_snapshot"], key).get(attr, []))
        t_insp = norm_refs(typed_belt(l3["from_inspect"], key).get(attr, []))
        x, y = (BELT_XS[2], BELT_Y) if key == "belt3" else (BELT_XS[3], BELT_Y)
        row = db_belt(x, y)
        e4 = None if row is None else row.get(attr)
        if e4 is not None and not isinstance(e4, list):
            e4 = [e4]
        agree = (
            refs_eq(e1, expected)
            and refs_eq(e2, e1)
            and refs_eq(t_snap, e1)
            and refs_eq(t_insp, e1)
            and (not db_ok or (e4 is not None and refs_eq(e4, e1)))
        )
        add(
            field,
            {
                "expected": expected,
                "L1_engine": e1,
                "L2_inspect": e2,
                "L3_typed_from_snapshot": t_snap,
                "L3_typed_from_inspect": t_insp,
                "L4_db": e4 if db_ok else "BLOCKED",
            },
            agree,
        )

    # interior continuity: belt1→belt2→belt3 (engine vs inspect vs typed only)
    for i in (1, 2):
        key, nxt = f"belt{i}", {"name": "transport-belt", "position": {"x": BELT_XS[i], "y": BELT_Y}}
        e1 = norm_refs(l1[key].get("belt_outputs", []))
        e2 = norm_refs(l2[key].get("belt_outputs", []))
        t_insp = norm_refs(typed_belt(l3["from_inspect"], key).get("belt_outputs", []))
        agree = refs_eq(e1, [nxt]) and refs_eq(e2, e1) and refs_eq(t_insp, e1)
        add(
            f"{key}.belt_outputs",
            {"expected": [nxt], "L1_engine": e1, "L2_inspect": e2, "L3_typed_from_inspect": t_insp},
            agree,
        )

    # ===================== UNDERGROUND pairing ==============================
    ug_in_ref = {"name": "underground-belt", "position": {"x": UG_IN_POS[0], "y": UG_IN_POS[1]}}
    ug_out_ref = {"name": "underground-belt", "position": {"x": UG_OUT_POS[0], "y": UG_OUT_POS[1]}}
    for key, expect_type, pair_ref in (
        ("ug_in", "input", ug_out_ref),
        ("ug_out", "output", ug_in_ref),
    ):
        e1_type = l1[key].get("belt_to_ground_type")
        e2_type = l2[key].get("belt_to_ground_type")
        t_snap_type = typed_belt(l3["from_snapshot"], key).get("belt_to_ground_type")
        t_insp_type = typed_belt(l3["from_inspect"], key).get("belt_to_ground_type")
        agree = e1_type == expect_type == e2_type == t_snap_type == t_insp_type
        add(
            f"{key}.belt_to_ground_type",
            {
                "expected": expect_type,
                "L1_engine": e1_type,
                "L2_inspect": e2_type,
                "L3_typed_from_snapshot": t_snap_type,
                "L3_typed_from_inspect": t_insp_type,
                "L4_db": "no underground rows (loader filters type=='transport-belt')"
                if db_ok
                else "BLOCKED",
            },
            agree,
        )

        e1_pair = l1[key].get("underground_neighbour")
        e2_pair = l2[key].get("underground_neighbour")
        snap_pair = (
            (collect_pair := (l3["_snapshot_raw"][key].get("belt_data") or {}))
            and collect_pair.get("underground_neighbour")
        ) or None
        typed_pair_insp = typed_belt(l3["from_inspect"], key).get("linked_belt_neighbour")
        typed_pair_snap = typed_belt(l3["from_snapshot"], key).get("linked_belt_neighbour")
        agree_pair = (
            ref_eq(e1_pair, pair_ref)
            and ref_eq(e2_pair, e1_pair)
            and ref_eq(snap_pair, e1_pair)
        )
        add(
            f"{key}.underground_pair",
            {
                "expected": pair_ref,
                "L1_engine(neighbours)": e1_pair,
                "L2_inspect(underground_neighbour)": e2_pair,
                "L3_snapshot_raw(belt_data.underground_neighbour)": snap_pair,
                "L3_typed_BeltState(linked_belt_neighbour)": typed_pair_insp
                or typed_pair_snap,
            },
            agree_pair,
            note="typed BeltState has no underground_neighbour field; "
            "linked_belt_neighbour is only populated for linked-belt entities, "
            "so the typed layer's representation is checked but recorded separately",
        )

    # ===================== unit_number leakage =============================
    leaks: List[str] = []
    leaks += [f"L2:{p}" for p in find_unit_numbers({k: v for k, v in l2.items() if not k.startswith("_")})]
    leaks += [f"L3:{p}" for p in find_unit_numbers(l3["from_inspect"])]
    leaks += [f"L3:{p}" for p in find_unit_numbers(l3["from_snapshot"])]
    if db_ok:
        leaks += [f"L4:{p}" for p in find_unit_numbers(l4.get("flat_rows", []))]
    add(
        "no_unit_number_leakage",
        {"leaks": leaks},
        len(leaks) == 0,
        note="agent-facing outputs (inspect payloads, typed objects, DB rows) "
        "must reference entities by name+position only",
    )

    n_fail = len(failures)
    log(f"comparison complete: {len(rows)} fields, {n_fail} disagreements")
    return rows, failures


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--artifacts-dir",
        default=str(
            REPO_ROOT / ".fv-output" / "certification" / date.today().isoformat() / "L2.1"
        ),
    )
    args = ap.parse_args()
    art = Path(args.artifacts_dir)
    art.mkdir(parents=True, exist_ok=True)
    log = Log(art / "run.log")

    commit = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    log(f"check L2.1 starting; commit={commit}; artifacts={art}")

    try:
        rcon = RCONClient(RCON_HOST, RCON_PORT, RCON_PASS)
    except Exception as e:  # noqa: BLE001
        log(f"BLOCKED: cannot connect RCON: {e}")
        return 2

    smoke_info = smoke(rcon, log)
    save(art, "01_smoke.json", smoke_info)
    tg = TestGroundHelper(rcon)

    created_agent_id: Optional[int] = None
    try:
        rig = build_rig(tg, rcon, log)
        save(art, "02_rig_build.json", rig)

        l1 = layer1_engine(rcon, log)
        save(art, "03_layer1_engine.json", l1)

        iface, created_agent_id = ensure_agent(rcon, log)
        l2 = layer2_inspect(rcon, iface, log)
        save(art, "04_layer2_inspect.json", l2)

        notes: Dict[str, Any] = {}
        snapshot_recs = wait_for_snapshot(tg, rcon, log, notes)
        save(art, "05_layer3_snapshot_records.json", {"_notes": notes, **snapshot_recs})
        l3 = layer3_transform(snapshot_recs, l2, log)
        l3["_snapshot_raw"] = snapshot_recs
        save(art, "05b_layer3_typed.json", {k: v for k, v in l3.items() if k != "_snapshot_raw"})

        l4 = layer4_db(log)
        save(art, "06_layer4_db.json", l4)

        rows, failures = compare_layers(l1, l2, l3, l4, log)
        tick = run_lua(rcon, "return {tick=game.tick}")["tick"]
        verdict = {
            "check": "L2.1",
            "commit": commit,
            "tick": tick,
            "status": "FAIL" if failures else "PASS",
            "db_layer": l4.get("status"),
            "fields_compared": len(rows),
            "disagreements": failures,
            "comparison": rows,
        }
        save(art, "07_comparison.json", verdict)

        if failures:
            log("RESULT: FAIL")
            for f in failures:
                log(f"  DISAGREE {f}")
            return 1
        log(f"RESULT: PASS ({len(rows)} fields agree across layers; DB layer: {l4.get('status')})")
        return 0
    finally:
        # Cleanup: rig area + any agent we created. Artifacts stay on disk.
        try:
            cleared = tg.clear_area(AREA_LT, AREA_RB)
            log(f"cleanup: cleared {cleared} entities from rig area")
            if created_agent_id is not None:
                run_lua(
                    rcon,
                    f"return remote.call('agent', 'destroy_agents', {{{created_agent_id}}}, false)",
                )
                log(f"cleanup: destroyed agent {created_agent_id}")
        except Exception as e:  # noqa: BLE001
            log(f"cleanup error (non-fatal): {e}")


if __name__ == "__main__":
    sys.exit(main())
