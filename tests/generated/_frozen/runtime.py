"""FROZEN runner substrate for generated test families. Sub-agents MUST NOT edit.

This module is the frozen half of the template contract (tests/generated/README.md):
it fixes the truth channels, the snapshot-freshness ritual, and the failure
semantics. Test mechanics (rig layouts, per-column probes) live in the family
directories and may iterate freely; anything here changes only via the
orchestrator, and a change voids the family's audit-log entry.

Idioms are lifted from the certified harnesses (do not "improve" them here):
- lua envelope / as_list:        scripts/certification/check_cell_coherence.py (L0.4)
- wait_fresh criterion:          same file — IDLE + write_queue==0 + per-chunk
  lookup snapshot_tick >= trigger tick; timeout RAISES (the CELL-1 lying-wait
  class is a certification error, never a silent proceed)
- DB load:                       Stack-A SnapshotDatabase + SnapshotLoader only
- RCON conventions:              docs/RUNTIME_PLAYBOOK.md (xpcall envelope is
  mandatory — unwrapped /c errors return EMPTY on the docker server)

Failure semantics (three terminal states, see README):
- test passes                       -> GREEN
- assertion fails (spec faithful)   -> RED-FINDING (tracker candidate)
- SpecBug / AntiVacuityError raised -> SPEC-BUG (escalate; never reinterpret
  the claim to get past it)
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[3]

# ---------------------------------------------------------------------------
# Failure semantics
# ---------------------------------------------------------------------------


class SpecBug(Exception):
    """The claim cannot be executed as written (infra missing, ritual failed,
    rig unbuildable). Distinct from an assertion failure: this is the harness
    saying 'I could not measure', never 'the measurement failed'."""


class AntiVacuityError(SpecBug):
    """A floor was not met — the test observed too little to certify anything.
    A pass without the floor is the vacuous-green class the audit gate exists
    to kill."""


def require_floor(n: int, floor: int, what: str) -> None:
    if n < floor:
        raise AntiVacuityError(f"anti-vacuity floor unmet: {what} = {n} < {floor}")


# ---------------------------------------------------------------------------
# Instance plumbing (FV_INSTANCE env; matches --instance in scripts/certification)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Instance:
    name: str
    rcon_host: str
    rcon_port: int
    rcon_password: str
    snapshot_root: Path


def instance_from_env() -> Instance:
    name = os.environ.get("FV_INSTANCE", "server_0")
    if name == "client":
        return Instance(name, "localhost", 27100, "factorio",
                        Path.home() / "Library/Application Support/factorio/script-output")
    if name.startswith("server_"):
        n = int(name.split("_")[1])
        return Instance(name, "localhost", 27000 + n, "factorio",
                        REPO / ".fv-output" / name)
    raise SpecBug(f"unknown FV_INSTANCE {name!r}; use 'client' or 'server_N'")


def connect(inst: Instance):
    from factorio_rcon import RCONClient

    rcon = RCONClient(inst.rcon_host, inst.rcon_port, inst.rcon_password)
    rcon.send_command("/c rcon.print('ping')")  # first command may emit a warning
    if "ping" not in (rcon.send_command("/c rcon.print('ping')") or ""):
        raise SpecBug(f"smoke ping failed on {inst.name}")
    ifaces = json.loads(rcon.send_command(
        "/c rcon.print(helpers.table_to_json(remote.interfaces))"))
    missing = [i for i in ("lab_grid", "agent", "map", "snapshot") if i not in ifaces]
    if missing:
        raise SpecBug(f"BLOCKED: missing remote interfaces {missing} — wrong scenario?")
    return rcon


# ---------------------------------------------------------------------------
# Lua execution envelope
# ---------------------------------------------------------------------------


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
        raise SpecBug(f"Lua error: {res['__lua_error'][:800]}")
    return res


def as_list(v: Any) -> List[Any]:
    """helpers.table_to_json renders empty arrays as {} and sparse arrays as
    dicts; normalize to a Python list."""
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        return list(v.values())
    return []


def game_tick(rcon: Any) -> int:
    return int(lua_strict(rcon, "return {tick=game.tick}")["tick"])


# ---------------------------------------------------------------------------
# Lab-grid cell geometry (mirrors src/factorio/scenarios/lab-grid/grid.lua;
# verify_grid_config() asserts the mirror against the live scenario at session
# start so scenario drift becomes a loud SPEC-BUG, not silent wrong bounds)
# ---------------------------------------------------------------------------

CHUNK_SIZE = 32
PLAY_AREA_SIZE = 128
CELL_SIZE = 160
GRID_SIZE = 8
TOTAL_CELLS = 64


def cell_origin(cell_index: int) -> Tuple[int, int]:
    return (cell_index % GRID_SIZE) * CELL_SIZE, (cell_index // GRID_SIZE) * CELL_SIZE


def play_bounds(cell_index: int) -> Dict[str, Dict[str, int]]:
    ox, oy = cell_origin(cell_index)
    return {"left_top": {"x": ox, "y": oy},
            "right_bottom": {"x": ox + PLAY_AREA_SIZE, "y": oy + PLAY_AREA_SIZE}}


def bounds_lua(b: Dict) -> str:
    lt, rb = b["left_top"], b["right_bottom"]
    return (f"{{left_top={{x={lt['x']},y={lt['y']}}},"
            f"right_bottom={{x={rb['x']},y={rb['y']}}}}}")


def cell_chunks(b: Dict) -> List[Tuple[int, int]]:
    lt, rb = b["left_top"], b["right_bottom"]
    return [(cx, cy)
            for cy in range(int(lt["y"]) // 32, (int(rb["y"]) - 1) // 32 + 1)
            for cx in range(int(lt["x"]) // 32, (int(rb["x"]) - 1) // 32 + 1)]


def verify_grid_config(rcon: Any) -> None:
    cfg = lua_strict(rcon, "return remote.call('lab_grid','get_config')")
    mirror = {"chunk_size": CHUNK_SIZE, "play_area_size": PLAY_AREA_SIZE,
              "cell_size": CELL_SIZE, "grid_size": GRID_SIZE,
              "total_cells": TOTAL_CELLS}
    drift = {k: (v, cfg.get(k)) for k, v in mirror.items()
             if cfg.get(k) is not None and int(cfg[k]) != v}
    if drift:
        raise SpecBug(f"grid.lua config drifted from the frozen mirror: {drift}")


# ---------------------------------------------------------------------------
# Cell session lifecycle
# ---------------------------------------------------------------------------


@dataclass
class CellSession:
    cell_index: int
    agent_id: int
    force_name: str
    spawn: Dict[str, float]
    bounds: Dict[str, Dict[str, int]]
    allocated_at_tick: int


def allocate_cell(rcon: Any, cell_index: int) -> CellSession:
    """Allocate a FIXED cell (never find-empty: concurrent find-empty races are
    uncertified). create_agent_in_cell also charts the cell and triggers its
    re_snapshot (SNAP-1b), so a fresh allocation is already snapshot-pending."""
    tick = game_tick(rcon)
    res = lua_strict(
        rcon,
        f"return remote.call('lab_grid','create_agent_in_cell',{{cell_index={cell_index}}})",
    )
    if not res.get("success"):
        raise SpecBug(f"cell {cell_index} allocation failed: {res.get('error')}")
    return CellSession(
        cell_index=int(res["cell_index"]),
        agent_id=int(res["agent_id"]),
        force_name=str(res["force_name"]),
        spawn=res.get("spawn_position") or {},
        bounds=play_bounds(cell_index),
        allocated_at_tick=tick,
    )


def release_cell(rcon: Any, session: CellSession) -> None:
    """Full cleanup: reset the cell (clears entities, re-lays terrain/resources,
    re-snapshots — playbook §5: cleanup is not done until the re-snapshot ran),
    unassign the agent binding, destroy the agent character."""
    lua_strict(rcon, f"return remote.call('lab_grid','reset_cell',{session.cell_index},false)")
    lua(rcon, f"return remote.call('lab_grid','unassign_agent',{session.agent_id})")
    lua(rcon, f"return remote.call('agent','destroy_agents',{{{session.agent_id}}})")


# ---------------------------------------------------------------------------
# Snapshot freshness ritual
# ---------------------------------------------------------------------------

WAIT_TIMEOUT_S = 120.0


def lookup_snapshot_ticks(rcon: Any) -> Dict[Tuple[int, int], int]:
    lookup = lua(rcon, "return remote.call('map','get_chunk_lookup')")
    snapped: Dict[Tuple[int, int], int] = {}
    if isinstance(lookup, dict):
        for k, v in lookup.items():
            if isinstance(v, dict) and v.get("snapshot_tick") is not None:
                cx, cy = k.split(",")
                snapped[(int(cx), int(cy))] = int(v["snapshot_tick"])
    return snapped


def re_snapshot_and_wait(rcon: Any, bounds: Dict, trigger_tick: Optional[int] = None) -> int:
    """Trigger re_snapshot_area for `bounds` and block until every overlapped
    chunk's snapshot_tick >= trigger_tick with the writer IDLE and flushed.
    Returns the trigger tick. Timeout RAISES SpecBug — never proceeds.

    pending_chunks is deliberately not consulted: it counts never-requested
    chunks map-wide and idles >0 forever on busy boots (L0.4 harness lesson).
    """
    if trigger_tick is None:
        trigger_tick = game_tick(rcon)
    res = lua_strict(rcon, f"return remote.call('map','re_snapshot_area',{bounds_lua(bounds)})")
    if isinstance(res, dict) and res.get("success") is False:
        raise SpecBug(f"re_snapshot_area refused: {res}")
    want = {c: trigger_tick for c in cell_chunks(bounds)}
    deadline = time.time() + WAIT_TIMEOUT_S
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        st = lua(rcon, "return remote.call('map','get_snapshot_status')")
        last = {"phase": st.get("phase"), "write_queue": st.get("write_queue_size")}
        if last["phase"] == "IDLE" and last["write_queue"] == 0:
            snapped = lookup_snapshot_ticks(rcon)
            stale = [(c, snapped.get(c, -1)) for c, t in sorted(want.items())
                     if snapped.get(c, -1) < t]
            if not stale:
                return trigger_tick
        time.sleep(1.0)
    raise SpecBug(
        f"re_snapshot wait timed out after {WAIT_TIMEOUT_S:.0f}s (last={last}, "
        f"trigger_tick={trigger_tick}) — refusing to read a possibly-stale DB "
        "(CELL-1 lying-wait class)")


# ---------------------------------------------------------------------------
# DB truth channel (Stack A only)
# ---------------------------------------------------------------------------


def load_db(inst: Instance, current_game_tick: int):
    """Fresh in-memory Stack-A session DB loaded from the instance's snapshot
    dir. current_game_tick engages the loader's future-tick guard (CELL-2)."""
    import sys

    src = str(REPO / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase
    from FactoryVerse.game.infra.duckdb.loader import SnapshotLoader

    db = SnapshotDatabase(db_path=None)
    db.ensure_schema()
    con = db.connection
    snapshot_dir = inst.snapshot_root / "factoryverse" / "snapshots"
    if not snapshot_dir.exists():
        raise SpecBug(f"snapshot dir missing: {snapshot_dir}")
    SnapshotLoader(db=con, snapshot_dir=inst.snapshot_root).load_all(
        current_game_tick=current_game_tick)
    return con


# ---------------------------------------------------------------------------
# Engine truth channel (raw RCON; shares no code with the mod or the loader)
# ---------------------------------------------------------------------------


def engine_entities_in(rcon: Any, bounds: Dict, force: Optional[str] = None) -> List[Dict]:
    """Independent engine truth for built entities in bounds.

    Truth-channel semantics (adjudicated Phase B, 2026-07-08, raw-payload
    evidence):
    - direction / direction_int: the defines.direction NAME and raw int. The
      snapshot payload emits both; the loader lifts the INT into the VARCHAR
      column while the schema docs promise names — tests compare per the
      documented semantics (name) and per derivability (int).
    - selbox_* : LuaEntity.selection_box (orientation-aware). This is what the
      mod emits as "bounding_box" (Resource.lua pattern; confirmed empirically
      Phase B: furnace DB bbox = pos+-0.796875 = selection box; a belt's
      selection box coincidentally equals its tile box, which misled the first
      adjudication). It is NOT LuaEntity.bounding_box (collision box) and NOT
      the tile footprint. Doc-note candidate: the columns are NAMED bbox_*
      and described as "bounding box", which a Factorio-API-literate reader
      would take as collision box.
    """
    force_filter = f", force='{force}'" if force else ""
    res = lua_strict(rcon, f"""
        local dirname = {{}}
        for k, v in pairs(defines.direction) do dirname[v] = k end
        local out = {{}}
        for _, e in pairs(game.surfaces[1].find_entities_filtered{{
                area={bounds_lua(bounds)}{force_filter}}}) do
            if e.type ~= 'resource' and e.type ~= 'character'
               and e.type ~= 'entity-ghost' and e.type ~= 'item-on-ground' then
                local sb = e.selection_box
                out[#out+1] = {{
                    name = e.name, type = e.type,
                    x = e.position.x, y = e.position.y,
                    direction = dirname[e.direction],
                    direction_int = e.direction,
                    selbox_min_x = sb.left_top.x,
                    selbox_min_y = sb.left_top.y,
                    selbox_max_x = sb.right_bottom.x,
                    selbox_max_y = sb.right_bottom.y,
                    force = e.force.name,
                    electric_network_id = e.electric_network_id,
                }}
            end
        end
        return {{entities = out, tick = game.tick}}
    """)
    return as_list(res.get("entities"))


def place(rcon: Any, session: CellSession, name: str, x: float, y: float,
          direction: str = "north", extra: str = "") -> Dict:
    """Script-place one rig entity on the session's cell force, raising
    script_raised_built so the event pipeline sees it too. `extra` is raw Lua
    appended inside the create_entity table (e.g. ", recipe='iron-gear-wheel'").
    Truth for the test must still come from engine_entities_in / the DB, never
    from this return value."""
    res = lua_strict(rcon, f"""
        local e = game.surfaces[1].create_entity{{
            name='{name}', position={{x={x},y={y}}},
            direction=defines.direction.{direction},
            force='{session.force_name}', raise_built=true{extra}}}
        if e == nil then return {{success=false}} end
        return {{success=true, name=e.name, x=e.position.x, y=e.position.y}}
    """)
    if not res.get("success"):
        raise SpecBug(f"rig placement failed: {name} at ({x},{y}) in cell "
                      f"{session.cell_index} — adjust the rig, not the claim")
    return res
