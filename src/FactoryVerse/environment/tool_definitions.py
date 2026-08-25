"""The agent's tool surface, defined exactly once.

The model reads these descriptions before every call, so they are part of the
harness's honesty budget: anything stated here that is not true of the live
execution path is a lie the agent cannot check. Constitution §8 — what the
arguments cannot promise, the surface must say.

Tool NAMES are frozen (`execute_dsl`, `execute_duckdb`, `respond`): trajectory
comparability across runs depends on them.

This module deliberately imports nothing from FactoryVerse. Every runtime that
serves tools to a model imports it, so it must be safe to import from anywhere.
"""

import re
from typing import Any, Dict, List, Optional

__all__ = [
    "EXECUTE_DSL_DESCRIPTION",
    "EXECUTE_DUCKDB_DESCRIPTION",
    "RESPOND_DESCRIPTION",
    "READ_ONLY_PREFIXES",
    "check_read_only",
    "leading_keyword",
    "get_tool_definitions",
]


EXECUTE_DSL_DESCRIPTION = (
    "Run Python in the agent's body. The namespace PERSISTS across calls: a "
    "variable or function defined by a block that runs cleanly is still there "
    "in the next block. A block that raises does not update the namespace, "
    "though whatever it already did to the world stands. "
    "`await` works directly at top level. The agent objects (walking, crafting, "
    "mining, research, inventory, placement, entity_ops, reachable_view, "
    "remote_view, placement_hints, events) are already loaded — do not import "
    "them. Nothing is returned implicitly; print() what you want to see. "
    "Exceptions are NOT raised to you: a failing block comes back as text "
    "naming the failing line, together with whatever it printed before it "
    "failed — that earlier work already happened and is not rolled back. Long "
    "output is truncated. This is the only channel to live entity state."
)

EXECUTE_DUCKDB_DESCRIPTION = (
    "Read-only SQL (DuckDB dialect) over the map model: a snapshot-backed "
    "record of what exists, where, and how it is configured. One statement "
    "per call; SELECT, WITH, EXPLAIN, DESCRIBE and SHOW only — anything that "
    "writes is refused, and the refusal is returned as text. This is NOT live "
    "simulation state: volatile per-entity facts (inventory contents, machine "
    "status) are read through execute_dsl, not here. Results come back as a "
    "text table with column headers and a row count, truncated if large."
)

RESPOND_DESCRIPTION = (
    "Send a text message to the user. Use this to answer or report; it does "
    "nothing in the game world."
)


# Statement keywords the tool description promises. Enforcement lives beside
# the promise on purpose: if one is edited, the other is in the same diff.
READ_ONLY_PREFIXES = frozenset(
    {"SELECT", "WITH", "EXPLAIN", "DESCRIBE", "DESC", "SHOW", "TABLE", "FROM", "PRAGMA"}
)

_ALLOWED_STATEMENT_TYPES = frozenset({"SELECT", "EXPLAIN"})

_REFUSAL = (
    "Refused: execute_duckdb is read-only — it did not run and the map model "
    "is unchanged. {reason} Allowed: a single SELECT, WITH, EXPLAIN, DESCRIBE "
    "or SHOW statement. To change the world, act through execute_dsl."
)


def leading_keyword(sql: str) -> str:
    """The first SQL keyword, upper-cased, with comments stripped ('' if none)."""
    stripped = _strip_sql_comments(sql).strip().lstrip("(").strip()
    if not stripped:
        return ""
    return re.split(r"[\s(;]+", stripped, maxsplit=1)[0].upper()


def check_read_only(query: str) -> Optional[str]:
    """Refuse anything that could write through the agent's query tool.

    Returns None when the statement may run, otherwise a refusal string meant
    to be handed back to the model as data (never raised — a refusal is a
    result, per Constitution §12).
    """
    stripped = _strip_sql_comments(query).strip().rstrip(";").strip()
    if not stripped:
        return _REFUSAL.format(reason="The query was empty.")

    try:
        import duckdb

        statements = duckdb.extract_statements(stripped)
    except ImportError:
        statements = None
    except Exception:
        # Not parseable here — fall back to the keyword prefix so a dialect
        # quirk cannot block a legitimate read. The real connection will
        # report the syntax error.
        statements = None

    if statements is None:
        first = leading_keyword(stripped)
        if first not in READ_ONLY_PREFIXES:
            return _REFUSAL.format(reason=f"'{first}' is not a read statement.")
        return None

    if len(statements) == 0:
        return _REFUSAL.format(reason="No SQL statement was found.")
    if len(statements) > 1:
        return _REFUSAL.format(
            reason=f"{len(statements)} statements were given; one call runs one statement."
        )

    kind = statements[0].type.name
    if kind not in _ALLOWED_STATEMENT_TYPES:
        return _REFUSAL.format(reason=f"This parses as a {kind} statement.")
    return None


def _strip_sql_comments(sql: str) -> str:
    """Remove -- and /* */ comments, leaving string literals intact."""
    out: list = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            while i < n:
                out.append(sql[i])
                if sql[i] == quote:
                    # Doubled quote is an escaped quote, not a terminator.
                    if i + 1 < n and sql[i + 1] == quote:
                        out.append(sql[i + 1])
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            out.append(" ")
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _function_tool(name: str, description: str, param: str, param_description: str) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    param: {"type": "string", "description": param_description},
                },
                "required": [param],
            },
        },
    }


def get_tool_definitions(mode: str = "autonomous") -> List[Dict[str, Any]]:
    """OpenAI-compatible tool definitions for the agent-facing tool surface.

    Args:
        mode: 'autonomous' (execute_dsl + execute_duckdb) or 'assisted'
            (adds `respond`).

    Returns:
        A fresh list of tool definitions (callers may mutate their copy).
    """
    tools = [
        _function_tool(
            "execute_dsl",
            EXECUTE_DSL_DESCRIPTION,
            "code",
            "Python source to run in the persistent namespace.",
        ),
        _function_tool(
            "execute_duckdb",
            EXECUTE_DUCKDB_DESCRIPTION,
            "query",
            "A single read-only SQL statement (DuckDB dialect).",
        ),
    ]

    if mode == "assisted":
        tools.append(
            _function_tool(
                "respond",
                RESPOND_DESCRIPTION,
                "message",
                "The message to send to the user.",
            )
        )

    return tools
