"""The agent-facing documentation must not lie, and the checks must not be vacuous.

Constitution §14: a check can pass while testing nothing. Every test here
asserts the thing it checked was non-empty before asserting it was clean.

Four surfaces are covered:

1. Coverage in BOTH directions. `documented -> exists` was already checked;
   `exists -> documented` was not, which is how `events` sat in the namespace
   for months untaught. Reasoned exemptions are allowed, and are themselves
   checked so they cannot rot.
2. The generated accessor table names only classes that exist (it once shipped
   `Verification`, a class that never existed).
3. Every SQL example the model is shown runs against the real DDL (the join
   examples used a column, `entity_key`, that exists in no table), and the
   schema the model reads is the schema the database creates.
4. Prose fields (descriptions, notes, decision points, preconditions, error
   cases) are attribute-checked like code examples are.
"""

from __future__ import annotations

import re
from typing import Dict, List, Set, Tuple

import pytest

from FactoryVerse.utils.docs.reference import register_all_documentation
from FactoryVerse.utils.docs.registry import get_registry, reset_registry
from FactoryVerse.utils.docs.validators import (
    CoverageValidator,
    NamespaceCoverageValidator,
    ProseReferenceValidator,
)


@pytest.fixture()
def registry():
    reset_registry()
    register_all_documentation()
    return get_registry()


# ---------------------------------------------------------------------------
# 1. Coverage, both directions
# ---------------------------------------------------------------------------

def test_coverage_exemptions_are_live(registry):
    """Each exemption names a real, discovered, still-undocumented method."""
    validator = CoverageValidator(registry)
    assert len(validator.COVERAGE_EXEMPTIONS) > 0
    validator.assert_exemptions_live()


def test_every_namespace_accessor_is_taught_or_exempt(registry):
    validator = NamespaceCoverageValidator(registry)
    accessors = validator.agent_namespace_accessors()
    assert len(accessors) >= 10, accessors  # the parse must find the real namespace
    assert {"walking", "inventory", "reachable_view", "remote_view"} <= set(accessors)
    problems = validator.validate()
    assert problems == [], "\n".join(problems)


def test_namespace_exemptions_are_live(registry):
    """An exemption that names nothing, or names something now documented, fails."""
    validator = NamespaceCoverageValidator(registry)
    assert len(validator.NAMESPACE_EXEMPTIONS) > 0
    accessors = validator.agent_namespace_accessors()
    documented = {c.accessor_name for c in registry.get_all_classes()}
    for name, reason in validator.NAMESPACE_EXEMPTIONS.items():
        assert reason.strip(), name
        assert name in accessors, f"stale exemption: {name} not in namespace"
        assert name not in documented, f"exemption {name} is now documented"


# ---------------------------------------------------------------------------
# 2. The accessor table cannot name a phantom class
# ---------------------------------------------------------------------------

def test_accessor_table_names_only_real_classes(registry):
    from FactoryVerse.utils.docs.generator import MarkdownGenerator

    table = MarkdownGenerator(registry)._generate_accessor_table()
    rows = re.findall(r"^\| `(\w+)` \| (\w+) \|", table, re.M)
    assert len(rows) >= 10, table
    for accessor, class_name in rows:
        cls = registry.get_class_object(class_name)
        assert cls is not None, f"table names class {class_name!r} for `{accessor}` but no such class is registered"
        assert cls.__name__ == class_name
    assert "Verification" not in table  # the phantom that motivated this


# ---------------------------------------------------------------------------
# 3. Schema examples run; documented schema == created schema
# ---------------------------------------------------------------------------

def _fresh_db():
    from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase

    db = SnapshotDatabase(None)
    db.ensure_schema()
    return db.connection


def _statements(block: str) -> List[str]:
    """Split a block of example SQL into statements, dropping comment lines.

    Examples are separated by `-- comment` lines, not semicolons, so a
    statement starts wherever a SELECT/WITH begins a line.
    """
    body = "\n".join(l for l in block.splitlines() if not l.strip().startswith("--"))
    parts = re.split(r"(?m)^(?=\s*(?:SELECT|WITH|EXPLAIN|DESCRIBE|SHOW)\b)", body)
    return [p.strip().rstrip(";") for p in parts if p.strip()]


def _sql_examples_shown_to_the_model() -> List[Tuple[str, str]]:
    """Every SQL string the schema reference puts in front of the model."""
    from FactoryVerse.game.infra.duckdb import schema_definitions as sd
    from FactoryVerse.infra.llm.prompts.schema_reference import generate_schema_reference

    found: List[Tuple[str, str]] = []
    for group_name in ("CORE_TABLES", "COMPONENT_TABLES", "ANALYTICS_TABLES", "STATE_TABLES"):
        for table in getattr(sd, group_name):
            for q in (table.example_queries or ([table.example_query] if table.example_query else [])):
                for j, stmt in enumerate(_statements(q)):
                    found.append((f"{table.name}.example[{j}]", stmt))
    text = generate_schema_reference()
    # ```sql fenced blocks
    for i, block in enumerate(re.findall(r"```sql\n(.*?)```", text, re.S)):
        for j, stmt in enumerate(_statements(block)):
            found.append((f"sql-fence[{i}][{j}]", stmt))
    # SQL passed to remote_view.* inside python fences
    for i, q in enumerate(re.findall(r"remote_view\.(?:query|get_entities|get_resources|get_ghosts)\(\s*(?:'''|\"\"\"|\"|')(.*?)(?:'''|\"\"\"|\"|')\s*\)", text, re.S)):
        for j, stmt in enumerate(_statements(q)):
            found.append((f"python-fence[{i}][{j}]", stmt))
    return found


def test_every_sql_example_runs_against_the_real_ddl():
    examples = _sql_examples_shown_to_the_model()
    assert len(examples) >= 15, examples  # the extraction must find the real corpus
    con = _fresh_db()
    failures = []
    for where, sql in examples:
        # Placeholders that the prose uses for "your values here" are not SQL.
        sql = sql.replace("?", "0")
        try:
            cur = con.execute(sql)
            assert cur is not None, "not a statement"
            cur.fetchall()
        except Exception as e:  # noqa: BLE001 — any failure is a lie to the model
            failures.append(f"{where}: {type(e).__name__}: {str(e).splitlines()[0]}\n    {sql.strip()[:160]}")
    assert failures == [], "\n".join(failures)


def _documented_schema() -> Dict[str, Set[str]]:
    from FactoryVerse.infra.llm.prompts.schema_reference import _generate_table_reference

    text = _generate_table_reference()
    tables: Dict[str, Set[str]] = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"^#### `(\w+)`", line)
        if m:
            current = m.group(1)
            tables[current] = set()
            continue
        m = re.match(r"^\| `(\w+)` \| `", line)
        if m and current:
            tables[current].add(m.group(1))
    return tables


def test_documented_schema_matches_created_schema():
    documented = _documented_schema()
    assert len(documented) >= 10, documented
    con = _fresh_db()
    created: Dict[str, Set[str]] = {}
    for (table, column) in con.execute(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'main'"
    ).fetchall():
        created.setdefault(table, set()).add(column)

    # Infrastructure the agent never queries and is not told about.
    undocumented_by_design = {"sync_state"}

    missing_in_ddl = {t: cols for t, cols in documented.items() if t not in created}
    assert missing_in_ddl == {}, f"documented but never created: {missing_in_ddl}"
    undocumented = set(created) - set(documented) - undocumented_by_design
    assert undocumented == set(), f"created but not documented: {undocumented}"
    assert undocumented_by_design <= set(created)

    column_drift = {}
    for t, cols in documented.items():
        if cols != created[t]:
            column_drift[t] = {"documented-only": cols - created[t], "created-only": created[t] - cols}
    assert column_drift == {}, column_drift


# ---------------------------------------------------------------------------
# 4. Prose is attribute-checked
# ---------------------------------------------------------------------------

def test_prose_method_references_resolve(registry):
    validator = ProseReferenceValidator(registry)
    problems = validator.validate()
    assert validator.tokens_checked >= 10, "prose scan found almost nothing — regex or fields broken"
    assert problems == [], "\n".join(problems)
