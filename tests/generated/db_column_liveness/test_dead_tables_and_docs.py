"""dead_tables_and_docs group: the mirage register — the 4 component tables
(inserter/transport_belt/mining_drill/assembler), footprint_tiles, and the
phantom `entity_key` JOIN key taught in worked examples.

Claim (frozen, liveness_spec, cases_for_group("dead_tables_and_docs")):
schema_reference.py documents inserter/transport_belt/mining_drill/assembler
and footprint_tiles as live, queryable tables with worked JOIN examples.
database.py CREATEs all of them (CORE_TABLES + COMPONENT_TABLES), but
loader.py never INSERTs into any of the 5 (MIRAGE-1/L1.5 for the four
component tables; NEW-2026-07-08 for footprint_tiles) — the tables exist and
are permanently empty. The worked JOIN examples additionally join on
`m.entity_key = d.entity_key` / `i.entity_key`; no table has an `entity_key`
column (status_loader.py:300), so the documented SQL is non-executable even
once/if the component tables gain rows. Every documented-liveness assertion
below is therefore a strict-xfail RED-FINDING: it must fail while the mirage
persists and go red (XPASS) the moment someone fixes the underlying surface
without reconciling spec + ledger (README failure semantics).

The agent analytics tables are now created, documented, and fed through the
same boot/live reducer path. This family pins their catalog presence; the
free-play domain contract verifies non-empty file/DB parity after crafting.

Each xfail test establishes its engine-truth/rig precondition as a floor
(runtime.require_floor) BEFORE the failing assertion, so a broken rig ERRORs
as SPEC-BUG instead of xfailing vacuously.
"""

from __future__ import annotations

import json
import math

import pytest

from _frozen import runtime
from _frozen.liveness_spec import (
    INGESTED_ANALYTICS_TABLES,
    DOCUMENTED_PHANTOM_JOIN_KEY,
    cases_for_group,
)

CASES = cases_for_group("dead_tables_and_docs")
CASE_BY_TABLE = {}
for _c in CASES:
    CASE_BY_TABLE.setdefault(_c.table, _c)


def _reason(table: str) -> str:
    c = CASE_BY_TABLE[table]
    return f"RED-FINDING {c.tracker}: {c.note}"


# Rig: one entity of each documented component-table kind. Offsets relative
# to the cell origin, in the same band test_map_entity_core.py/dead.py use
# successfully (clear of the cell's fixed resource patches, Phase B). This
# group runs in its own cell (FV_CELL_INDEX=15) so there is no cross-group
# placement conflict.
RIG = [
    # (name, dx, dy, direction, extra_lua)
    ("inserter", 70.0, 90.0, "south", ""),
    ("transport-belt", 72.5, 90.5, "west", ""),
    ("burner-mining-drill", 75.0, 90.0, "east", ""),
    ("assembling-machine-1", 79.0, 91.0, "north", ", recipe='iron-gear-wheel'"),
]

# Maps a documented component table name to the rig entity that should
# populate it, per schema_reference.py's own description of each table.
COMPONENT_TABLE_ENTITY = {
    "inserter": "inserter",
    "transport_belt": "transport-belt",
    "mining_drill": "burner-mining-drill",
    "assembler": "assembling-machine-1",
}

# schema_reference.py's own documented JOIN worked example, copied verbatim
# (src/FactoryVerse/infra/llm/prompts/schema_reference.py:320-325, the
# "Get drills with their mining targets" example under "Join Component
# Tables"). Read-only reference — do not "fix" the SQL to make it executable.
DOCUMENTED_JOIN_SQL = """
    SELECT m.entity_name, m.position_x, m.position_y, d.mining_target
    FROM map_entity m
    JOIN mining_drill d ON m.entity_key = d.entity_key
"""


@pytest.fixture(scope="module")
def rig(rcon, cell, instance):
    placed = []
    for name, dx, dy, direction, extra in RIG:
        ox, oy = runtime.cell_origin(cell.cell_index)
        res = runtime.place(rcon, cell, name, ox + dx, oy + dy, direction, extra)
        placed.append({"name": name, "x": res["x"], "y": res["y"]})
    runtime.require_floor(len(placed), len(RIG), "rig entities placed (one per component-table kind)")

    tick = runtime.re_snapshot_and_wait(rcon, cell.bounds)
    engine = runtime.engine_entities_in(rcon, cell.bounds, force=cell.force_name)
    runtime.require_floor(len(engine), len(RIG), "engine-truth entities")

    con = runtime.load_db(instance, current_game_tick=runtime.game_tick(rcon))
    b = cell.bounds
    rows = con.execute(
        "SELECT entity_name, position_x, position_y, raw_data FROM map_entity "
        "WHERE position_x >= ? AND position_x < ? AND position_y >= ? AND position_y < ?",
        [b["left_top"]["x"], b["right_bottom"]["x"],
         b["left_top"]["y"], b["right_bottom"]["y"]]).fetchall()
    db = [dict(zip(("entity_name", "position_x", "position_y", "raw_data"), r))
          for r in rows]
    runtime.require_floor(len(db), len(RIG), "map_entity rows present for the rig (proves the pipeline saw them)")
    return {"placed": placed, "engine": engine, "db": db, "tick": tick, "con": con}


def _require_entity_seen(rig, entity_name: str) -> None:
    """Floor for a single component-table test: the entity is confirmed both
    by independent engine truth AND by map_entity, so an empty component
    table can only be attributed to the component-table lift, not to a rig
    or pipeline failure."""
    in_engine = [e for e in rig["engine"] if e["name"] == entity_name]
    in_db = [d for d in rig["db"] if d["entity_name"] == entity_name]
    runtime.require_floor(len(in_engine), 1, f"{entity_name} present via engine_entities_in")
    runtime.require_floor(len(in_db), 1, f"{entity_name} present as a map_entity row")


# ---------------------------------------------------------------------------
# A. Component tables (MIRAGE-1 / L1.5): one xfail test per table so each
#    column-set's death is individually registered.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason=_reason("inserter"))
def test_inserter_table_documented_liveness(rig):
    _require_entity_seen(rig, COMPONENT_TABLE_ENTITY["inserter"])
    n = rig["con"].execute("SELECT COUNT(*) FROM inserter").fetchone()[0]
    assert n > 0, "inserter table has 0 rows while the rig contains an inserter"


@pytest.mark.xfail(strict=True, reason=_reason("transport_belt"))
def test_transport_belt_table_documented_liveness(rig):
    _require_entity_seen(rig, COMPONENT_TABLE_ENTITY["transport_belt"])
    n = rig["con"].execute("SELECT COUNT(*) FROM transport_belt").fetchone()[0]
    assert n > 0, "transport_belt table has 0 rows while the rig contains a transport-belt"


@pytest.mark.xfail(strict=True, reason=_reason("mining_drill"))
def test_mining_drill_table_documented_liveness(rig):
    _require_entity_seen(rig, COMPONENT_TABLE_ENTITY["mining_drill"])
    n = rig["con"].execute("SELECT COUNT(*) FROM mining_drill").fetchone()[0]
    assert n > 0, "mining_drill table has 0 rows while the rig contains a burner-mining-drill"


@pytest.mark.xfail(strict=True, reason=_reason("assembler"))
def test_assembler_table_documented_liveness(rig):
    _require_entity_seen(rig, COMPONENT_TABLE_ENTITY["assembler"])
    n = rig["con"].execute("SELECT COUNT(*) FROM assembler").fetchone()[0]
    assert n > 0, "assembler table has 0 rows while the rig contains an assembling-machine-1"


# ---------------------------------------------------------------------------
# B. footprint_tiles (NEW-2026-07-08)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason=_reason("footprint_tiles"))
def test_footprint_tiles_documented_liveness(rig):
    runtime.require_floor(len(rig["db"]), len(RIG),
                          "map_entity rows whose entities occupy known tiles")
    con = rig["con"]
    tiles = [(math.floor(float(d["position_x"])), math.floor(float(d["position_y"])))
             for d in rig["db"]]
    hits = 0
    for tx, ty in tiles:
        hits += con.execute(
            "SELECT COUNT(*) FROM footprint_tiles WHERE tile_x = ? AND tile_y = ?",
            [tx, ty]).fetchone()[0]
    assert hits > 0, f"footprint_tiles has 0 rows for any rig entity's occupied anchor tile {tiles}"


def test_footprint_tiles_present_in_raw_data(rig):
    """Non-xfail companion: the mod DOES compute+ship per-entity footprint
    tiles (serialize.lua: out.footprint_tiles = tiles, a list of {x, y}
    covering the entity's full multi-tile extent) inside raw_data — the data
    is not missing, only the footprint_tiles table-lift is. Verified
    empirically here before asserting PASS (per instructions): if raw_data
    lacked it too, this test would need to report that instead."""
    hits = []
    for d in rig["db"]:
        raw = json.loads(d["raw_data"]) if d["raw_data"] else {}
        footprint = raw.get("footprint_tiles")
        assert footprint, f"{d['entity_name']}: raw_data has no footprint_tiles array either"
        anchor = (math.floor(float(d["position_x"])), math.floor(float(d["position_y"])))
        coords = {(t["x"], t["y"]) for t in footprint}
        assert anchor in coords, (
            f"{d['entity_name']}: anchor tile {anchor} not among raw_data "
            f"footprint_tiles {sorted(coords)}")
        hits.append(d["entity_name"])
    assert len(hits) == len(rig["db"]), (
        f"footprint_tiles present+correct in raw_data for only "
        f"{len(hits)}/{len(rig['db'])} rig rows")


# ---------------------------------------------------------------------------
# C. Phantom JOIN key (NEW-2026-07-08): the documented worked JOIN example
#    itself is non-executable — no table has an entity_key column.
# ---------------------------------------------------------------------------


def test_documented_join_sql_really_uses_entity_key():
    """Floor: the SQL under test really is the docs' own copied text, not a
    strawman rewritten to fail."""
    assert DOCUMENTED_PHANTOM_JOIN_KEY in DOCUMENTED_JOIN_SQL
    assert "entity_key" in DOCUMENTED_JOIN_SQL


@pytest.mark.xfail(strict=True, reason="RED-FINDING NEW-2026-07-08: "
                   "schema_reference.py's own worked JOIN example "
                   "(mining_drill, lines ~320-325) joins on m.entity_key = "
                   "d.entity_key; no table in the schema has an entity_key "
                   "column (status_loader.py:300), so the documented SQL "
                   "cannot execute")
def test_documented_join_executes(rig):
    con = rig["con"]
    try:
        con.execute(DOCUMENTED_JOIN_SQL)
    except Exception as exc:  # noqa: BLE001 - re-raised below as the evidence
        raise AssertionError(
            f"documented JOIN example failed to execute: "
            f"{type(exc).__name__}: {exc}") from exc


# ---------------------------------------------------------------------------
# D. Analytics tables: created and backed by the agent-statistics reducers.
# ---------------------------------------------------------------------------


def test_ingested_analytics_tables_exist(rig):
    runtime.require_floor(len(INGESTED_ANALYTICS_TABLES), 1, "INGESTED_ANALYTICS_TABLES entries")
    con = rig["con"]
    missing = []
    for table in INGESTED_ANALYTICS_TABLES:
        n = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
            [table]).fetchone()[0]
        if n == 0:
            missing.append(table)
    assert not missing, f"ingested analytics tables missing from DB catalog: {missing}"
