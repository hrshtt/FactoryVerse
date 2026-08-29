"""Standing anti-mirage invariant (Task 6, power-impl-contracts.md build):
every TableDefinition group that schema_reference.py imports/documents to
the model must actually be CREATEd by database.py's DDL — the exact bug
class this build closes (ANALYTICS_TABLES existed in schema_definitions.py
but `database.py`'s `_create_tables` used `CORE_TABLES + COMPONENT_TABLES`
only, so a declared table could go undocumented-safe OR, worse, documented
and silently empty forever).

Also guards the opposite direction (2026-08-29): the polled feeds that
used to be tables — entity_status, power_samples, power_networks,
agent_production_statistics, and the older power_statistics — must not come
back as tables or reducers. They are read on demand (Constitution §10).

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


POLLED_TABLES = (
    "entity_status",
    "power_samples",
    "power_networks",
    "power_statistics",
    "agent_production_statistics",
)
POLLED_REDUCERS = ("apply_status_dump", "apply_power_sample", "apply_agent_production_sample")


class TestPolledFeedsAreNotTables:
    """Constitution §10 applied retroactively (API plan §4.6, 2026-08-29):
    entity status, power samples/networks and force production are polled —
    nothing raises an event when they change — so they left the database.
    Their files are read on demand through remote_view.status()/.power()/
    .production(). Nobody may quietly bring one back as a bare
    TableDefinition, a reducer, or a STATE_TABLES group."""

    @pytest.mark.parametrize("name", POLLED_TABLES)
    def test_polled_table_is_not_declared(self, name):
        assert name not in {t.name for t in sd.ALL_TABLES}

    @pytest.mark.parametrize("name", POLLED_TABLES)
    def test_polled_table_is_not_created(self, name, created_table_names):
        assert name not in created_table_names

    def test_no_state_tables_group(self):
        assert not hasattr(sd, "STATE_TABLES")
        assert "STATE_TABLES" not in sd.__all__

    @pytest.mark.parametrize("reducer", POLLED_REDUCERS)
    def test_no_reducer_for_polled_feeds(self, reducer):
        assert not hasattr(analytics_ops, reducer)

    def test_the_event_backed_analytics_table_is_created_and_reduced(self, created_table_names):
        assert "agent_manual_production_statistics" in created_table_names
        src = inspect.getsource(analytics_ops.apply_agent_manual_snapshot)
        assert "agent_manual_production_statistics" in src

    def test_the_readers_exist_where_the_plan_puts_them(self):
        from FactoryVerse.game.agent import status_dump, power_dump
        from FactoryVerse.game.agent.remote_view import RemoteView

        assert hasattr(status_dump, "StatusDumpReader")
        assert hasattr(power_dump, "PowerDumpReader")
        for name in ("status", "status_changed", "power", "production"):
            assert callable(getattr(RemoteView, name)), name
