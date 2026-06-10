#!/usr/bin/env python3
"""Generate the verification coverage matrix for FLOOR_CERTIFICATION.md.

Emits docs/certification/COVERAGE_MATRIX.md by pure offline introspection:

1. PROPERTIES   - every capability/implementation state model field
                  (pydantic models + dataclasses, discovered by import).
2. TYPE-SYSTEM  - every public method/property on the agent-facing surface
                  (documentation registry + direct class introspection).
3. SYNC PATHS   - UDP operation types (AST-extracted from sync.py dispatch)
                  x synced/component/derived tables (regex over SQL strings),
                  plus snapshot JSONL file kinds consumed by the loaders.
4. LUA EMISSION - table keys emitted by inspection.lua, per inspect function
                  (BEST-EFFORT regex extraction).

Run:  uv run python scripts/certification/gen_matrix.py
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
import pkgutil
import re
import subprocess
import sys
import typing
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = REPO_ROOT / "docs" / "certification" / "COVERAGE_MATRIX.md"

STATUS_UNCHECKED = "⬜"  # white square
STATUS_STUB = "KNOWN-STUB"


# =============================================================================
# 1. PROPERTIES - capability/implementation state models
# =============================================================================

STATE_PACKAGES = [
    "FactoryVerse.game.factory.entity.capabilities",
    "FactoryVerse.game.factory.entity.implementations",
]


def _is_optional(annotation: Any) -> bool:
    origin = typing.get_origin(annotation)
    if origin is typing.Union or str(origin) == "types.UnionType":
        return type(None) in typing.get_args(annotation)
    return False


def _fmt_annotation(annotation: Any) -> str:
    if annotation is None:
        return "Any"
    if isinstance(annotation, type):
        return annotation.__name__
    text = str(annotation)
    text = text.replace("typing.", "")
    text = re.sub(r"\b[\w.]+\.(\w+)", r"\1", text)
    return text


def collect_state_classes() -> List[Dict[str, Any]]:
    """Discover pydantic models / dataclasses defined in the state packages."""
    try:
        from pydantic import BaseModel
    except ImportError:  # pragma: no cover
        BaseModel = None  # type: ignore[assignment]

    results: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    for pkg_name in STATE_PACKAGES:
        pkg = importlib.import_module(pkg_name)
        module_names = [pkg_name] + [
            f"{pkg_name}.{m.name}" for m in pkgutil.iter_modules(pkg.__path__)
        ]
        for mod_name in module_names:
            mod = importlib.import_module(mod_name)
            for _, cls in inspect.getmembers(mod, inspect.isclass):
                if cls.__module__ != mod_name or cls.__qualname__ in seen:
                    continue
                is_pydantic = (
                    BaseModel is not None
                    and issubclass(cls, BaseModel)
                    and cls is not BaseModel
                )
                is_dc = dataclasses.is_dataclass(cls)
                if not (is_pydantic or is_dc):
                    continue
                seen.add(cls.__qualname__)

                doc = (inspect.getdoc(cls) or "").lower()
                is_stub = "stub" in doc

                fields: List[Dict[str, Any]] = []
                if is_pydantic:
                    for fname, finfo in cls.model_fields.items():
                        ann = finfo.annotation
                        fields.append(
                            {
                                "name": fname,
                                "type": _fmt_annotation(ann),
                                "optional": _is_optional(ann)
                                or not finfo.is_required(),
                            }
                        )
                else:
                    for f in dataclasses.fields(cls):
                        fields.append(
                            {
                                "name": f.name,
                                "type": _fmt_annotation(f.type),
                                "optional": _is_optional(f.type)
                                or f.default is not dataclasses.MISSING
                                or f.default_factory is not dataclasses.MISSING,  # type: ignore[misc]
                            }
                        )

                results.append(
                    {
                        "class": cls.__name__,
                        "module": mod_name,
                        "kind": "pydantic" if is_pydantic else "dataclass",
                        "is_stub": is_stub,
                        "fields": fields,
                    }
                )

    results.sort(key=lambda r: (not r["module"].endswith(r["class"]), r["class"]))
    results.sort(key=lambda r: r["class"])
    return results


# =============================================================================
# 2. TYPE-SYSTEM API - agent-facing surface
# =============================================================================

# Modules whose *Action / view / builder / hints classes form the agent-facing
# surface. Classes and methods are discovered, not listed.
SURFACE_MODULES = [
    "FactoryVerse.game.agent.embodied_actions",
    "FactoryVerse.game.agent.reachable_view",
    "FactoryVerse.game.agent.remote_view",
    "FactoryVerse.game.agent.ghost_builder",
    "FactoryVerse.game.agent.placement_hints",
]

SURFACE_CLASS_PATTERN = re.compile(
    r"(Action|Inventory|View|Builder|Hints)$"
)


def _registry_documented_methods() -> Set[str]:
    """'Class.method' keys known to the documentation registry."""
    try:
        from FactoryVerse.utils.docs.reference import register_all_documentation
        from FactoryVerse.utils.docs.registry import get_registry

        register_all_documentation()
        return set(get_registry()._methods.keys())
    except Exception as exc:  # pragma: no cover
        print(f"warning: documentation registry unavailable: {exc}", file=sys.stderr)
        return set()


def collect_api_surface() -> Tuple[List[Dict[str, Any]], Set[str]]:
    documented = _registry_documented_methods()
    classes: Dict[str, Dict[str, Any]] = {}

    for mod_path in SURFACE_MODULES:
        mod = importlib.import_module(mod_path)
        module_names = [mod_path]
        if hasattr(mod, "__path__"):
            module_names += [
                f"{mod_path}.{m.name}" for m in pkgutil.iter_modules(mod.__path__)
            ]
        for mod_name in module_names:
            m = importlib.import_module(mod_name)
            for _, cls in inspect.getmembers(m, inspect.isclass):
                if cls.__module__ != mod_name:
                    continue
                if not SURFACE_CLASS_PATTERN.search(cls.__name__):
                    continue
                if cls.__name__ in classes:
                    continue
                members: List[Dict[str, Any]] = []
                for name, member in vars(cls).items():
                    if name.startswith("_"):
                        continue
                    if isinstance(member, property):
                        kind = "property"
                    elif inspect.iscoroutinefunction(member):
                        kind = "async method"
                    elif inspect.isfunction(member):
                        kind = "method"
                    elif isinstance(member, (staticmethod, classmethod)):
                        kind = (
                            "staticmethod"
                            if isinstance(member, staticmethod)
                            else "classmethod"
                        )
                    else:
                        continue
                    members.append(
                        {
                            "name": name,
                            "kind": kind,
                            "documented": f"{cls.__name__}.{name}" in documented,
                        }
                    )
                if not members:
                    continue
                members.sort(key=lambda x: x["name"])
                classes[cls.__name__] = {
                    "class": cls.__name__,
                    "module": cls.__module__,
                    "members": members,
                }

    return sorted(classes.values(), key=lambda c: c["class"]), documented


# =============================================================================
# 3. SYNC PATHS - operations x tables, snapshot JSONL kinds
# =============================================================================

SYNC_PY = REPO_ROOT / "src/FactoryVerse/game/infra/duckdb/sync.py"
STACK_A_LOADER = REPO_ROOT / "src/FactoryVerse/game/infra/duckdb/loader.py"
STATUS_LOADER = REPO_ROOT / "src/FactoryVerse/game/infra/duckdb/status_loader.py"
# The parallel `db/` stack (create_schema/load_all/derived_loader) was dead
# code, deleted 2026-06-10 by design decision: belt aggregation = labels on
# primitives + Python graph functions on top; derived tables are off-design.

# Case-sensitive on purpose: SQL keywords are uppercase in this codebase,
# while docstrings/log strings use sentence case ("Update only the...").
SQL_TABLE_RE = re.compile(
    r"(?:INSERT\s+(?:OR\s+REPLACE\s+)?INTO|DELETE\s+FROM|UPDATE)\s+([a-z_][a-z0-9_]*)\b"
)
CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z0-9_]*)\b"
)
JSONL_RE = re.compile(r"['\"]([\w*\-./]*?[\w*\-]+\.jsonl)['\"]")


def extract_sync_dispatch() -> List[Dict[str, Any]]:
    """AST-extract (op aliases, target, handler) triples from _apply_operation."""
    tree = ast.parse(SYNC_PY.read_text())
    dispatch: List[Dict[str, Any]] = []

    def op_strings(test: ast.expr) -> List[str]:
        ops: List[str] = []
        for node in ast.walk(test):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                ops.append(node.value)
        return ops

    def handlers_in(body: List[ast.stmt]) -> List[str]:
        found: List[str] = []
        for stmt in body:
            for n in ast.walk(stmt):
                if (
                    isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr.startswith("_apply_")
                ):
                    found.append(n.func.attr)
        return list(dict.fromkeys(found))

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_apply_operation":
            # Walk the top-level if/elif chain: each branch's test holds the
            # op string aliases; each branch body holds the entity/ghost
            # handler calls (without descending into sibling elif branches,
            # which live in `orelse`).
            chain: List[ast.If] = [s for s in node.body if isinstance(s, ast.If)]
            while chain:
                branch = chain.pop(0)
                ops = op_strings(branch.test)
                if ops:
                    for handler in handlers_in(branch.body):
                        target = "ghost" if "ghost" in handler else "entity"
                        dispatch.append(
                            {"ops": ops, "target": target, "handler": handler}
                        )
                chain.extend(s for s in branch.orelse if isinstance(s, ast.If))
            break

    return dispatch


def extract_handler_tables() -> Dict[str, Set[str]]:
    """Map each _apply_* handler in sync.py to the tables its SQL touches."""
    tree = ast.parse(SYNC_PY.read_text())
    handler_tables: Dict[str, Set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_apply_"):
            tables: Set[str] = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    tables.update(SQL_TABLE_RE.findall(sub.value))
            handler_tables[node.name] = tables
    return handler_tables


def collect_tables() -> Dict[str, Set[str]]:
    """Discover table inventories from schema defs, db/schema.py, loaders."""
    from FactoryVerse.game.infra.duckdb import schema_definitions as sd

    core = {t.name for t in sd.CORE_TABLES}
    component = {t.name for t in sd.COMPONENT_TABLES}
    analytics = {t.name for t in sd.ANALYTICS_TABLES}

    # Stack B deleted (see note at top): derived/schema_created universes are
    # empty by design now. Keys kept so downstream set algebra is stable.
    schema_created: Set[str] = set()
    derived: Set[str] = set()

    loader_written: Set[str] = set()
    for py in (STACK_A_LOADER, STATUS_LOADER):
        if py.exists():
            loader_written |= set(SQL_TABLE_RE.findall(py.read_text()))

    return {
        "core": core,
        "component": component,
        "analytics": analytics,
        "schema_created": schema_created,
        "derived": derived,
        "loader_written": loader_written,
    }


def collect_jsonl_kinds() -> List[str]:
    kinds: Set[str] = set()
    sources = [
        STACK_A_LOADER,
        STATUS_LOADER,
        REPO_ROOT / "src/FactoryVerse/game/infra/duckdb/sync.py",
    ]
    for py in sources:
        if not py.exists():
            continue
        for match in JSONL_RE.findall(py.read_text()):
            kinds.add(match.split("/")[-1])
    return sorted(kinds)


def build_sync_cells() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    dispatch = extract_sync_dispatch()
    handler_tables = extract_handler_tables()
    tables = collect_tables()

    # Tables that should reflect live entity/ghost mutations: tables sync
    # writes directly + component tables + derived tables. Analytics and
    # tile-init tables are loader-only by design and excluded mechanically.
    sync_written: Set[str] = set()
    for ts in handler_tables.values():
        sync_written |= ts
    candidate = (
        sync_written
        | tables["component"]
        | tables["derived"]
        | tables["schema_created"]
    )
    candidate -= tables["analytics"]
    # Terrain-only tables have no entity-mutation path (mechanical exclusion:
    # terrain never appears in an entity/ghost UDP op). resource_tile stays:
    # mining depletes it.
    candidate -= {"water_tile", "water_patch"}

    ghost_tables = sorted(t for t in candidate if t.startswith("ghost"))
    entity_tables = sorted(candidate - set(ghost_tables))

    # Surface naming discrepancies between schema sources (e.g. `assembler`
    # in schema_definitions.py vs `assemblers` in db/schema.py).
    name_conflicts = sorted(
        f"`{t}`/`{t}s`" for t in candidate if f"{t}s" in candidate
    )

    cells: List[Dict[str, Any]] = []
    for d in dispatch:
        op_label = "/".join(d["ops"])
        target_tables = ghost_tables if d["target"] == "ghost" else entity_tables
        touched = handler_tables.get(d["handler"], set())
        for table in target_tables:
            cells.append(
                {
                    "operation": op_label,
                    "target": d["target"],
                    "handler": d["handler"],
                    "table": table,
                    "direct_write": table in touched,
                }
            )

    meta = {
        "dispatch": dispatch,
        "handler_tables": handler_tables,
        "tables": tables,
        "entity_tables": entity_tables,
        "ghost_tables": ghost_tables,
        "name_conflicts": name_conflicts,
    }
    return cells, meta


# =============================================================================
# 4. LUA EMISSION - inspection.lua emitted keys (BEST-EFFORT)
# =============================================================================

INSPECTION_LUA = REPO_ROOT / "src/fv_embodied_agent/agent_actions/inspection.lua"

# Top-level (column-0) functions only: nested helpers like `local function
# refs(list)` inside an inspect_* body must not steal key attribution.
LUA_FUNC_RE = re.compile(r"^(?:local\s+)?function\s+([\w.]+)\s*\(")
# Anywhere on the line (catches `if ... then data.x = v end`); `(?!=)` avoids
# matching comparisons (`data.x == v`).
LUA_DOTTED_RE = re.compile(
    r"\b(?:data|result|state|info|payload)\.([a-zA-Z_][a-zA-Z0-9_.]*)\s*=(?!=)"
)
LUA_TABLE_KEY_RE = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(.+?)\s*$")
LUA_NOISE_KEYS = {"local"}


def collect_lua_emission() -> List[Dict[str, Any]]:
    """Best-effort regex extraction of emitted table keys per Lua function."""
    lines = INSPECTION_LUA.read_text().splitlines()
    current_fn = "<module>"
    per_fn: Dict[str, Set[str]] = {}

    for i, line in enumerate(lines):
        stripped = line.split("--")[0].rstrip()
        if not stripped:
            continue
        m = LUA_FUNC_RE.match(stripped)
        if m:
            current_fn = m.group(1)
            continue
        keys = per_fn.setdefault(current_fn, set())

        dotted = LUA_DOTTED_RE.findall(stripped)
        if dotted:
            keys.update(dotted)
            continue

        m = LUA_TABLE_KEY_RE.match(stripped)
        if m and m.group(1) not in LUA_NOISE_KEYS:
            key, value = m.group(1), m.group(2)
            # Only count bare keys that look like table-constructor entries:
            # they end with ',' '{' or '}' (vs local var mutation like
            # 'slot = slot + 1').
            if value.endswith((",", "{", "}")) or value.rstrip(",").endswith("}"):
                # skip self-referential mutations
                if not re.match(rf"^{re.escape(key)}\b", value):
                    keys.add(key)

    return [
        {"function": fn, "keys": sorted(keys)}
        for fn, keys in sorted(per_fn.items())
        if keys
    ]


# =============================================================================
# Markdown emission
# =============================================================================


def git_short_hash() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def md_escape(text: str) -> str:
    return text.replace("|", "\\|")


def main() -> None:
    state_classes = collect_state_classes()
    api_classes, _documented = collect_api_surface()
    sync_cells, sync_meta = build_sync_cells()
    jsonl_kinds = collect_jsonl_kinds()
    lua_fns = collect_lua_emission()

    n_prop_fields = sum(len(c["fields"]) for c in state_classes)
    n_stub_classes = sum(1 for c in state_classes if c["is_stub"])
    n_api = sum(len(c["members"]) for c in api_classes)
    n_lua_keys = sum(len(f["keys"]) for f in lua_fns)

    out: List[str] = []
    w = out.append

    w("# Verification Coverage Matrix")
    w("")
    w(
        f"Generated by `scripts/certification/gen_matrix.py` on {date.today().isoformat()} "
        f"at commit `{git_short_hash()}`. **Do not edit cells by hand except the STATUS "
        f"column** — regenerate after structural changes (regeneration resets STATUS)."
    )
    w("")
    w(
        "Companion to [`docs/FLOOR_CERTIFICATION.md`](../FLOOR_CERTIFICATION.md): "
        "this is the complete, programmatically-derived cell inventory for the L2 "
        "(properties) and L4 (interactions) layers. Coverage = verified cells / total cells."
    )
    w("")
    w(f"STATUS legend: {STATUS_UNCHECKED} = needs a live check · `{STATUS_STUB}` = "
      "class is documented as a stub (no live check expected yet) · replace with "
      "`✅ date @ commit` / `❌ date @ commit` when executed.")
    w("")

    # ---- Summary ----
    w("## Summary")
    w("")
    w("| Category | Cells | Detail |")
    w("|---|---|---|")
    w(
        f"| 1. Property fields | **{n_prop_fields}** | across {len(state_classes)} "
        f"state classes ({n_stub_classes} stub classes) |"
    )
    w(f"| 2. Type-system API members | **{n_api}** | across {len(api_classes)} classes |")
    w(
        f"| 3. Sync (operation × table) cells | **{len(sync_cells)}** | "
        f"{len(sync_meta['dispatch'])} op handlers × "
        f"{len(sync_meta['entity_tables'])} entity tables / "
        f"{len(sync_meta['ghost_tables'])} ghost tables |"
    )
    w(f"| 3b. Snapshot JSONL file kinds | **{len(jsonl_kinds)}** | consumed by loaders |")
    w(
        f"| 4. Lua emission keys (BEST-EFFORT) | **{n_lua_keys}** | across "
        f"{len(lua_fns)} inspection.lua functions |"
    )
    total = n_prop_fields + n_api + len(sync_cells) + len(jsonl_kinds) + n_lua_keys
    w(f"| **Total** | **{total}** | |")
    w("")

    # ---- 1. Properties ----
    w("## 1. Properties — capability/implementation state fields (L2)")
    w("")
    w(
        "Source: pydantic models and dataclasses discovered by importing "
        "`FactoryVerse.game.factory.entity.capabilities` and `...entity.implementations`. "
        "Each field is one cell: a live check must build a rig and assert the field "
        "agrees across RCON `inspect_entity`, the DuckDB row, and the typed object."
    )
    w("")
    for cls in state_classes:
        stub_note = " — **KNOWN-STUB** (docstring marks this class as a stub)" if cls["is_stub"] else ""
        w(f"### {cls['class']} ({cls['kind']}, `{cls['module'].split('.')[-1]}.py`){stub_note}")
        w("")
        w("| Field | Type | Optional | STATUS |")
        w("|---|---|---|---|")
        status = f"`{STATUS_STUB}`" if cls["is_stub"] else STATUS_UNCHECKED
        for f in cls["fields"]:
            w(
                f"| `{f['name']}` | `{md_escape(f['type'])}` | "
                f"{'yes' if f['optional'] else 'no'} | {status} |"
            )
        w("")

    # ---- 2. API ----
    w("## 2. Type-system API — agent-facing surface (L2/L4)")
    w("")
    w(
        "Source: classes matching `*Action|*Inventory|*View|*Builder|*Hints` defined in "
        "`game/agent/embodied_actions/`, `reachable_view.py`, `remote_view.py`, "
        "`ghost_builder.py`, `placement_hints.py`; public members via introspection. "
        "`Doc?` = registered in the documentation registry "
        "(`register_all_documentation()`). Each member is one cell: a live check must "
        "invoke it and verify its contract."
    )
    w("")
    for cls in api_classes:
        w(f"### {cls['class']} (`{cls['module']}`)")
        w("")
        w("| Member | Kind | Doc? | STATUS |")
        w("|---|---|---|---|")
        for mbr in cls["members"]:
            w(
                f"| `{mbr['name']}` | {mbr['kind']} | "
                f"{'yes' if mbr['documented'] else 'no'} | {STATUS_UNCHECKED} |"
            )
        w("")

    # ---- 3. Sync ----
    w("## 3. Sync paths — UDP operations × tables (L1/L4)")
    w("")
    w(
        "Operations AST-extracted from `_apply_operation` dispatch in "
        "`game/infra/duckdb/sync.py`; tables from `schema_definitions.py`, "
        "`db/schema.py` CREATE TABLE statements, and loader SQL. Analytics and "
        "terrain-only tables (`water_tile`, `water_patch`, statistics) are excluded "
        "mechanically — they have no entity-mutation path. `Direct write?` = sync.py "
        "handler contains SQL touching that table; **no** means the table can only go "
        "stale (derived/loader-only) and the cell verifies staleness handling."
    )
    w("")
    w("Handlers discovered:")
    w("")
    for d in sync_meta["dispatch"]:
        touched = sorted(sync_meta["handler_tables"].get(d["handler"], set()))
        w(
            f"- `{'/'.join(d['ops'])}` ({d['target']}) → `{d['handler']}` "
            f"(writes: {', '.join(f'`{t}`' for t in touched) if touched else 'none/delegates'})"
        )
    w("")
    if sync_meta["name_conflicts"]:
        w(
            "**Naming discrepancy detected between schema sources** (likely the "
            "same logical table with diverging names): "
            + ", ".join(sync_meta["name_conflicts"])
            + "."
        )
        w("")
    w("| Operation | Target | Table | Direct write? | STATUS |")
    w("|---|---|---|---|---|")
    for cell in sync_cells:
        w(
            f"| `{cell['operation']}` | {cell['target']} | `{cell['table']}` | "
            f"{'yes' if cell['direct_write'] else 'no'} | {STATUS_UNCHECKED} |"
        )
    w("")
    w("### 3b. Snapshot JSONL file kinds (loader inputs)")
    w("")
    w("Each kind is one cell: verify the loader ingests it and the resulting rows match game truth.")
    w("")
    w("| JSONL kind | STATUS |")
    w("|---|---|")
    for kind in jsonl_kinds:
        w(f"| `{kind}` | {STATUS_UNCHECKED} |")
    w("")

    # ---- 4. Lua ----
    w("## 4. Lua emission — inspection.lua keys (BEST-EFFORT)")
    w("")
    w(
        "Regex extraction of table keys set in "
        "`src/fv_embodied_agent/agent_actions/inspection.lua`, grouped by function. "
        "**BEST-EFFORT**: regex over Lua, not a parser — keys may be missing or "
        "over-included. Use to cross-check Lua-emits vs Python-parses vs DB-stores "
        "alignment per field."
    )
    w("")
    for fn in lua_fns:
        w(f"### `{fn['function']}`")
        w("")
        w("| Emitted key | STATUS |")
        w("|---|---|")
        for key in fn["keys"]:
            w(f"| `{key}` | {STATUS_UNCHECKED} |")
        w("")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text("\n".join(out) + "\n")

    print(f"Wrote {OUTPUT_PATH.relative_to(REPO_ROOT)}")
    print(
        f"  property fields : {n_prop_fields:4d} across {len(state_classes)} classes "
        f"({n_stub_classes} stubs)"
    )
    print(f"  API members     : {n_api:4d} across {len(api_classes)} classes")
    print(f"  sync cells      : {len(sync_cells):4d}")
    print(f"  jsonl kinds     : {len(jsonl_kinds):4d}")
    print(f"  lua keys        : {n_lua_keys:4d} across {len(lua_fns)} functions")
    print(f"  TOTAL cells     : {total:4d}")


if __name__ == "__main__":
    main()
