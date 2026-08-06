"""Standing anti-mirage invariant (Task 6, power-impl-contracts.md build):
every TableDefinition group that schema_reference.py imports/documents to
the model must actually be CREATEd by database.py's DDL — the exact bug
class this build closes (ANALYTICS_TABLES existed in schema_definitions.py
but `database.py`'s `_create_tables` used `CORE_TABLES + COMPONENT_TABLES`
only, so a declared table could go undocumented-safe OR, worse, documented
and silently empty forever).

Also asserts the 3 NEW STATE_TABLES (power_samples/power_networks/
entity_status) are both (a) created and (b) backed by a reducer in
analytics_ops — and that `power_statistics` cannot silently come back as a
bare declaration without an ingestion path (regression guard: that pattern
is exactly what got deleted in this build).

NOTE ON PLACEMENT/NAMING: the task brief for this build named this file
`tests/unit/test_dead_tables_and_docs.py`. That basename already exists at
tests/generated/db_column_liveness/test_dead_tables_and_docs.py — a
different, live-rig-only suite (requires rcon/cell/instance fixtures) from
the frozen test-factory. Neither tests/unit/ nor tests/generated/
db_column_liveness/ has an __init__.py, so pytest's default (rootless)
import mode would raise "import file mismatch" the moment both are
collected in the same session (e.g. a bare `pytest` over the whole tree).
Using a distinct name here avoids that collision while covering the same
standing invariant, fully offline.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import List, Set

import pytest

from FactoryVerse.game.infra.duckdb import schema_definitions as sd
from FactoryVerse.game.infra.duckdb import analytics_ops
from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase
from FactoryVerse.infra.llm.prompts import schema_reference as schema_reference_module


def _documented_table_group_names() -> List[str]:
    """AST-parse schema_reference.py's own
    `from ...schema_definitions import (...)` statement to find which
    schema_definitions.py *_TABLES groups it documents to the model. Not
    hardcoded, so it can't silently go stale if schema_reference.py starts
    (or stops) importing a group."""
    src = Path(inspect.getfile(schema_reference_module)).read_text()
    tree = ast.parse(src)
    names: List[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.endswith("schema_definitions")
        ):
            for alias in node.names:
                if alias.name.endswith("_TABLES"):
                    names.append(alias.name)
    return names


@pytest.fixture(scope="module")
def created_table_names() -> Set[str]:
    """Ground truth: actually run database.py's DDL against an in-memory
    DuckDB and ask its own catalog what exists — not a text/AST guess about
    `_create_tables`'s source."""
    db = SnapshotDatabase(db_path=None)
    db.ensure_schema()
    rows = db.connection.execute(
        "SELECT table_name FROM information_schema.tables"
    ).fetchall()
    names = {r[0] for r in rows}
    db.close()
    return names


class TestDocumentedGroupsAreCreated:
    def test_documented_groups_found(self):
        """Floor: the AST parse must actually find something, so a broken
        parse fails loudly (SPEC-BUG) instead of vacuously passing below."""
        groups = _documented_table_group_names()
        assert len(groups) >= 1, (
            "schema_reference.py imports no *_TABLES group from "
            "schema_definitions — either the AST parse broke or "
            "schema_reference.py changed its import shape"
        )

    def test_every_documented_table_is_created(self, created_table_names):
        groups = _documented_table_group_names()
        missing = []
        for group_name in groups:
            group = getattr(sd, group_name)
            for table in group:
                if table.name not in created_table_names:
                    missing.append(f"{group_name}.{table.name}")
        assert not missing, (
            "schema_reference.py documents these tables to the model, but "
            f"database.py never CREATEs them: {missing} — this is the exact "
            "mirage class this build closes (agent is taught a table "
            "exists, every query against it returns nothing, forever)"
        )


class TestNewStateTablesWiredEndToEnd:
    """Task 3/C3: the 3 new STATE_TABLES must be BOTH created (the literal
    missing line this whole bug class came from) AND have a reducer in
    analytics_ops (C4 single-reducer rule)."""

    @pytest.mark.parametrize("table", sd.STATE_TABLES, ids=lambda t: t.name)
    def test_state_table_is_created(self, table, created_table_names):
        assert table.name in created_table_names, (
            f"STATE_TABLES table {table.name!r} is declared in "
            "schema_definitions.py but database.py's _create_tables does "
            "not create it"
        )

    def test_power_samples_and_power_networks_share_one_reducer(self):
        assert hasattr(analytics_ops, "apply_power_sample")
        src = inspect.getsource(analytics_ops.apply_power_sample)
        assert "power_samples" in src
        assert "power_networks" in src

    def test_entity_status_has_reducer(self):
        assert hasattr(analytics_ops, "apply_status_dump")
        src = inspect.getsource(analytics_ops.apply_status_dump)
        assert "entity_status" in src


class TestPowerStatisticsResurrectionGuard:
    """Regression guard: `power_statistics` (the old global-network table)
    was DELETED — superseded by power_samples/power_networks. Nobody may
    quietly bring back a bare TableDefinition/table for it without wiring a
    real ingestion path; that omission is exactly the bug class this build
    fixes for power_samples/power_networks/entity_status."""

    def test_power_statistics_definition_removed_from_module(self):
        assert not hasattr(sd, "POWER_STATISTICS")
        assert "POWER_STATISTICS" not in sd.__all__

    def test_power_statistics_not_in_any_table_collection(self):
        names = {t.name for t in sd.ALL_TABLES}
        assert "power_statistics" not in names

    def test_power_statistics_table_does_not_exist(self, created_table_names):
        assert "power_statistics" not in created_table_names
