"""FROZEN spec for the db_column_liveness family. Sub-agents MUST NOT edit.

THE CLAIM (ledger row L1.11, pending): every table/column that
schema_reference.py documents to the model is LIVE — populated with
engine-true values whenever the engine has corresponding state. A documented
column that is structurally NULL/empty is a MIRAGE (a surface that teaches
false world-facts) and must show up here as a RED-FINDING until the surface
is reconciled (populated, or dropped from schema + docs).

The case matrix is ENUMERATED from schema_definitions.py at import time —
the same collections database.py CREATEs and schema_reference.py documents —
so coverage is generated from data, never recalled. Adding a column to the
schema automatically adds an un-grouped case, which fails the completeness
assertion below until a group (and therefore a test) owns it.

Expectations encode today's KNOWN state, verified by exploration 2026-07-08
(loader.py:512-516 INSERT column list; database.py:156 CREATE set):
- LIVE: the loader lifts it; tests assert DB == engine truth (+ floors).
- DEAD_DOCUMENTED: documented to the model but never populated. Tests assert
  liveness and are expected to FAIL — marked strict-xfail so the suite is
  green only while the mirage persists AND red the moment someone fixes it
  without reconciling this spec + the ledger (the forcing function).
- Agent analytics are outside this per-column map; their file/DB parity is
  covered by the dedicated production-statistics contract.
"""

from __future__ import annotations

import enum
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, Tuple

_SRC = str(Path(__file__).resolve().parents[3] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from FactoryVerse.game.infra.duckdb.schema_definitions import (  # noqa: E402
    ANALYTICS_TABLES,
    COMPONENT_TABLES,
    CORE_TABLES,
)


class Liveness(enum.Enum):
    LIVE = "live"
    MISREPRESENTED = "misrepresented"     # value present + engine-true, but in a
                                          # representation the docs contradict
    DEAD_DOCUMENTED = "dead_documented"   # the mirage class
    DEAD_DECLARED = "dead_declared"       # schema-only, uncreated, undocumented


@dataclass(frozen=True)
class ColumnCase:
    table: str
    column: str
    liveness: Liveness
    group: str
    tracker: str = ""   # tracker/ledger anchor for known-dead cases
    note: str = ""


# --- known-dead registry (the natural plants; every entry MUST turn out red) --

# value is engine-true but the representation contradicts the docs — found by
# the Phase B pilot run (raw payload: mod emits BOTH direction=12 and
# direction_name="west"; loader lifts the int; docs promise "NORTH, EAST, ...")
_MISREPRESENTED_COLUMNS: Dict[Tuple[str, str], Tuple[str, str]] = {
    ("map_entity", "direction"): (
        "NEW-2026-07-08", "VARCHAR column holds raw defines.direction ints ('12'); "
                          "docs teach names; emitted direction_name is ignored by the loader"),
    ("ghost", "direction"): (
        "NEW-2026-07-08", "same class (L2.5 'coerced' around this drift)"),
}

_DEAD_COLUMNS: Dict[Tuple[str, str], Tuple[str, str]] = {
    ("map_entity", "electric_network_id"): (
        "MIRAGE-2", "documented column, absent from loader INSERT list -> always NULL; "
                    "value exists only inside raw_data JSON"),
    ("map_entity", "tile_x"): (
        "NEW-2026-07-08", "declared + queried live (remote_view get_entities_at_anchor_tile) "
                          "but never lifted -> always NULL"),
    ("map_entity", "tile_y"): (
        "NEW-2026-07-08", "same as tile_x"),
    # ghost builder-lift asymmetry (MIRAGE-4), found by the Phase C ghost group.
    # label + placed_tick FIXED 2026-07-08 (loader/sync made builder-aware) and
    # reclassified LIVE; placed_by remains dead pending Harshit's alias-vs-drop
    # design call (no write path emits that key at any level).
    ("ghost", "placed_by"): (
        "MIRAGE-4", "docs promise 'who placed this ghost'; no write path emits "
                    "placed_by (builder.agent_id/player_id exist; alias-vs-drop pending)"),
}

_DEAD_TABLES: Dict[str, Tuple[str, str]] = {
    "inserter": ("MIRAGE-1/L1.5", "documented with worked JOIN examples; loader never inserts -> 0 rows"),
    "transport_belt": ("MIRAGE-1/L1.5", "same class"),
    "mining_drill": ("MIRAGE-1/L1.5", "same class"),
    "assembler": ("MIRAGE-1/L1.5", "same class"),
    "footprint_tiles": (
        "NEW-2026-07-08", "documented core table, 0 rows, AND queried live by remote_view "
                          "(is_tile_occupied always False, get_entity_at_tile always None)"),
}

# --- group assignment (fan-out boundaries; one sub-agent per group) ----------

GROUPS: Dict[str, FrozenSet[Tuple[str, str]]] = {
    # Phase B pilot row (orchestrator-authored)
    "map_entity_core": frozenset({
        ("map_entity", c) for c in (
            "entity_name", "position_x", "position_y", "chunk_x", "chunk_y",
            "direction", "bbox_min_x", "bbox_min_y", "bbox_max_x", "bbox_max_y")
    }),
    "map_entity_builder": frozenset({
        ("map_entity", c) for c in
        ("agent_id", "player_id", "force", "label", "placed_tick", "raw_data")
    }),
    "map_entity_dead": frozenset({
        ("map_entity", c) for c in ("electric_network_id", "tile_x", "tile_y")
    }),
    "ghost": frozenset({
        ("ghost", c) for c in (
            "ghost_name", "position_x", "position_y", "chunk_x", "chunk_y",
            "direction", "placed_tick", "placed_by", "label", "raw_data")
    }),
    "terrain_and_meta": frozenset(
        {("resource_tile", c) for c in ("name", "position_x", "position_y",
                                        "chunk_x", "chunk_y", "amount")}
        | {("water_tile", c) for c in ("position_x", "position_y", "chunk_x", "chunk_y")}
        | {("chunk_snapshot_meta", c) for c in ("chunk_x", "chunk_y", "tick")}
    ),
    "resource_entity": frozenset({
        ("resource_entity", c) for c in (
            "name", "entity_type", "position_x", "position_y",
            "chunk_x", "chunk_y", "raw_data")
    }),
    # everything in a dead table, plus the documented-surface probes
    "dead_tables_and_docs": frozenset(
        {(t.name, c.name) for t in COMPONENT_TABLES for c in t.columns}
        | {("footprint_tiles", c) for c in (
            "tile_x", "tile_y", "entity_name",
            "entity_position_x", "entity_position_y", "is_ghost")}
    ),
}


def _classify(table: str, column: str) -> Tuple[Liveness, str, str]:
    if table in _DEAD_TABLES:
        tracker, note = _DEAD_TABLES[table]
        return Liveness.DEAD_DOCUMENTED, tracker, note
    if (table, column) in _DEAD_COLUMNS:
        tracker, note = _DEAD_COLUMNS[(table, column)]
        return Liveness.DEAD_DOCUMENTED, tracker, note
    if (table, column) in _MISREPRESENTED_COLUMNS:
        tracker, note = _MISREPRESENTED_COLUMNS[(table, column)]
        return Liveness.MISREPRESENTED, tracker, note
    return Liveness.LIVE, "", ""


def _build_matrix() -> Dict[Tuple[str, str], ColumnCase]:
    group_of: Dict[Tuple[str, str], str] = {}
    for gname, members in GROUPS.items():
        for key in members:
            if key in group_of:
                raise AssertionError(f"{key} assigned to two groups: {group_of[key]}, {gname}")
            group_of[key] = gname

    matrix: Dict[Tuple[str, str], ColumnCase] = {}
    for tdef in list(CORE_TABLES) + list(COMPONENT_TABLES):
        for col in tdef.columns:
            key = (tdef.name, col.name)
            liveness, tracker, note = _classify(*key)
            group = group_of.get(key)
            if group is None:
                # completeness gate: schema grew a documented column nobody owns
                raise AssertionError(
                    f"UNGROUPED documented column {key} — the schema changed; "
                    "assign it to a group in liveness_spec.py (orchestrator edit)")
            matrix[key] = ColumnCase(tdef.name, col.name, liveness, group, tracker, note)

    orphaned = set(group_of) - set(matrix)
    if orphaned:
        raise AssertionError(
            f"GROUPS reference columns absent from the schema: {sorted(orphaned)}")
    return matrix


MATRIX: Dict[Tuple[str, str], ColumnCase] = _build_matrix()

# Analytics tables are not part of the spatial per-column matrix. They are
# created and ingested from agent snapshot feeds; this family pins catalog
# presence while the domain live suite proves actual file/DB parity.
INGESTED_ANALYTICS_TABLES = tuple(t.name for t in ANALYTICS_TABLES)

# Documented-surface probes with no column of their own:
# - the schema_reference JOIN examples use m.entity_key / d.entity_key /
#   i.entity_key — no such column exists on ANY table (status_loader.py:300).
#   The taught JOIN is non-executable even if component tables had rows.
DOCUMENTED_PHANTOM_JOIN_KEY = "entity_key"

# --- anti-vacuity floors ------------------------------------------------------

MIN_RIG_ENTITIES = 5          # a liveness rig must place at least this many
MIN_ROWS_PER_LIVE_COLUMN = 3  # >= this many rows with engine truth compared
MIN_NON_DEFAULT_VALUES = 2    # of which >= this many must be non-default
                              # (a column of all-NULL/all-0 proves nothing)


def cases_for_group(group: str) -> Tuple[ColumnCase, ...]:
    return tuple(sorted((c for c in MATRIX.values() if c.group == group),
                        key=lambda c: (c.table, c.column)))
