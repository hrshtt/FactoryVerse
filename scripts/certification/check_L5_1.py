#!/usr/bin/env python3
"""L5.1 certification check: namespace completeness (OFFLINE).

Every callable/object name the agent-facing docs promise must exist in the
DSL execution namespace the agent's generated code actually runs in
(the PROMPT-1 `factoriopedia` bug class).

NAMESPACE side (ground truth, from the real assembly code path):
    Tier4Runtime.execute_code() in environment/tiers/tier4_runtime.py builds
    `builtin_names` and exec()s agent code against it. The top-level name SET
    is extracted by AST-parsing that exact dict literal (not hand-copied).
    Classes behind each accessor are resolved by following the module's own
    `self._x = ClassName(...)` assignments + import statements (AST), then
    importing those classes. Instances are NOT created -> no live server
    needed; method existence is checked by class introspection
    (dir + __init__ self.X assignments + dataclass fields), same approach as
    StaticAttributeValidator.

DOCS side (what agents are told), three surfaces:
    1. LIVE generated API reference: utils/docs/generator.generate_api_reference()
       (this is what the runtime system prompt embeds via {DSL_DOCUMENTATION};
       per L5.5 the registry is the truth). Parsed for accessor headers,
       method headers, overview/pre-imported tables and python code fences.
    2. System prompt template docs/system-prompt/factoryverse-system-prompt-
       v3-template.md: the "Available Types"/"Available Objects" bullet lists
       and python code fences.
    3. Checked-in docs/for-llms/api_reference.md: known stale (L5.5). Checked
       the same way but reported as DRIFT separately -- it is not what agents
       see at runtime, so it does not gate PASS/FAIL.

Classification of misses on the live surface:
    missing-top-level   docs name not a key of builtin_names
    missing-method      accessor exists but class lacks the attribute
    unverifiable        accessor exists but no class could be resolved
                        offline (reported, does not fail)

Code-fence free-name classification (an example's free variable is not
automatically a namespace promise -- examples carry "Preconditions:" prose):
    GATES: PascalCase free name used as a value/constructor (a type the agent
           is shown constructing, e.g. TilePosition(x=5, y=10)); lowercase
           free name never bound by any fence in the corpus but used as a
           method-call base (the literal `factoriopedia.entity(...)` PROMPT-1
           shape).
    WARNS: annotation-only names (List in `x: List[ItemStack]` signature
           fences); lowercase names bound by another fence in the corpus
           (example-local idiom, e.g. `chest` defined two examples earlier);
           lowercase never-bound names used only as plain values
           (`source_pole=existing_pole`).

Non-vacuous guards:
    - namespace top-level names extracted > 10
    - top-level doc names checked > 10
    - accessor methods checked > 30
    - python code fences parsed > 10

Exit codes: 0 PASS / 1 FAIL / 2 BLOCKED
Artifacts: .fv-output/certification/2026-06-11/L5.1/
"""

import argparse
import ast
import builtins
import importlib
import inspect
import json
import re
import sys
import traceback
from dataclasses import is_dataclass, fields as dc_fields
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

TIER4_PATH = REPO_ROOT / "src/FactoryVerse/environment/tiers/tier4_runtime.py"
TEMPLATE_PATH = (
    REPO_ROOT / "docs/system-prompt/factoryverse-system-prompt-v3-template.md"
)
CHECKED_IN_API_REF = REPO_ROOT / "docs/for-llms/api_reference.md"
ART_DIR = REPO_ROOT / ".fv-output/certification/2026-06-11/L5.1"
ART_DIR.mkdir(parents=True, exist_ok=True)

PY_BUILTINS = set(dir(builtins)) | {"__builtins__", "__name__", "__doc__", "self"}

# Namespace values that are not `self._x = ClassName(...)` assignments.
# The NAMES still come from the AST of builtin_names; only the backing type
# for method introspection is resolved here, with the source noted.
SPECIAL_VALUE_TYPES = {
    "agent_id": ("builtins", "str"),  # self._agent_id is a str agent id
    "rcon_client": ("factorio_rcon", "RCONClient"),  # tier3.rcon -> Optional[RCONClient]
    "json": ("MODULE", "json"),
    "asyncio": ("MODULE", "asyncio"),
    "runtime": (None, None),  # local RuntimeProxy shim (only ._listener)
}


# --------------------------------------------------------------------------
# Namespace extraction (AST of tier4_runtime.py execute_code)
# --------------------------------------------------------------------------

def _collect_import_map(tree: ast.AST) -> dict:
    """name -> (module, original_name) for every import anywhere in the file."""
    imap = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imap[alias.asname or alias.name] = (node.module, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imap[alias.asname or alias.name] = ("MODULE", alias.name)
    return imap


def _find_builtin_names_dict(tree: ast.AST) -> ast.Dict:
    """Locate `builtin_names = {...}` inside Tier4Runtime.execute_code."""
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef) and cls.name == "Tier4Runtime":
            for fn in cls.body:
                if (
                    isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef))
                    and fn.name == "execute_code"
                ):
                    for node in ast.walk(fn):
                        if isinstance(node, ast.Assign):
                            for t in node.targets:
                                if (
                                    isinstance(t, ast.Name)
                                    and t.id == "builtin_names"
                                    and isinstance(node.value, ast.Dict)
                                ):
                                    return node.value
    raise RuntimeError(
        "builtin_names dict not found in Tier4Runtime.execute_code -- "
        "namespace assembly moved; check is BLOCKED until updated"
    )


def _collect_self_attr_classes(tree: ast.AST) -> dict:
    """attr ('_movement') -> set of class names from `self._x = ClassName(...)`."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            cls_name = None
            if isinstance(func, ast.Name):
                cls_name = func.id
            elif isinstance(func, ast.Attribute):
                cls_name = func.attr
            if cls_name is None:
                continue
            for t in node.targets:
                if (
                    isinstance(t, ast.Attribute)
                    and isinstance(t.value, ast.Name)
                    and t.value.id == "self"
                ):
                    out.setdefault(t.attr, set()).add(cls_name)
    return out


def _resolve_class(name: str, import_map: dict):
    """Import the class `name` using the file's own import statements."""
    if name not in import_map:
        return None
    module, orig = import_map[name]
    try:
        if module == "MODULE":
            return importlib.import_module(orig)
        mod = importlib.import_module(module)
        return getattr(mod, orig, None)
    except Exception:
        return None


def extract_namespace():
    """Return (names: set, accessor_classes: dict name -> list of classes,
    notes: list)."""
    src = TIER4_PATH.read_text()
    tree = ast.parse(src)
    import_map = _collect_import_map(tree)
    self_attr_classes = _collect_self_attr_classes(tree)
    dict_node = _find_builtin_names_dict(tree)

    names = set()
    accessor_classes = {}
    notes = []

    for key_node, val_node in zip(dict_node.keys, dict_node.values):
        if not (isinstance(key_node, ast.Constant) and isinstance(key_node.value, str)):
            notes.append(f"non-constant key skipped: {ast.dump(key_node)}")
            continue
        key = key_node.value
        names.add(key)

        resolved = []
        if key in SPECIAL_VALUE_TYPES:
            module, cname = SPECIAL_VALUE_TYPES[key]
            if module == "builtins":
                resolved = [getattr(builtins, cname)]
            elif module == "MODULE":
                try:
                    resolved = [importlib.import_module(cname)]
                except Exception:
                    resolved = []
            elif module:
                try:
                    mod = importlib.import_module(module)
                    obj = getattr(mod, cname, None)
                    resolved = [obj] if obj else []
                except Exception:
                    resolved = []
        elif isinstance(val_node, ast.Name):
            cls = _resolve_class(val_node.id, import_map)
            resolved = [cls] if cls else []
        elif (
            isinstance(val_node, ast.Attribute)
            and isinstance(val_node.value, ast.Name)
            and val_node.value.id == "self"
        ):
            for cls_name in sorted(self_attr_classes.get(val_node.attr, ())):
                cls = _resolve_class(cls_name, import_map)
                if cls is not None:
                    resolved.append(cls)
        if resolved:
            accessor_classes[key] = resolved
        else:
            notes.append(f"no class resolved for namespace name '{key}'")
    return names, accessor_classes, notes


# --------------------------------------------------------------------------
# Class attribute introspection (mirrors StaticAttributeValidator approach)
# --------------------------------------------------------------------------

def class_attributes(cls) -> set:
    attrs = {n for n in dir(cls) if not n.startswith("_")}
    init = getattr(cls, "__init__", None)
    if init is not None:
        try:
            src = inspect.getsource(init)
            for m in re.finditer(r"self\.(\w+)\s*=", src):
                if not m.group(1).startswith("_"):
                    attrs.add(m.group(1))
        except Exception:
            pass
    try:
        if is_dataclass(cls):
            attrs |= {f.name for f in dc_fields(cls)}
    except Exception:
        pass
    return attrs


# --------------------------------------------------------------------------
# Docs-side extraction
# --------------------------------------------------------------------------

MD_ACCESSOR_HEADER = re.compile(r"^### `(\w+)`\s*$", re.M)
MD_ACCESSOR_LINE = re.compile(r"^\*\*Accessor:\*\* `(\w+)`\s*$", re.M)
MD_METHOD_HEADER = re.compile(r"^#### `(\w+)\.(\w+)`\s*$", re.M)
MD_OVERVIEW_ROW = re.compile(r"^\| `(\w+)` \| \w+ \|", re.M)
# pre-imported types table rows only: second column is a dotted module path
# (plain `float`/`str` rows are dataclass field tables, not promises)
MD_TYPE_ROW = re.compile(r"^\| `(\w+)` \| `\w+(?:\.\w+)+` \|", re.M)
TEMPLATE_BULLET = re.compile(r"^- \*\*`(\w+)")
CODE_FENCE = re.compile(r"```python\n(.*?)```", re.S)


MD_QUICKREF_BULLET = re.compile(r"^- `(?:async )?(\w+)[(:]")


def parse_markdown_promises(md: str, source: str):
    """Return (top_level: dict name -> where, methods: set (acc, meth, where),
    fences: list of (code, where))."""
    top = {}
    methods = set()

    for rx in (MD_ACCESSOR_HEADER, MD_ACCESSOR_LINE, MD_OVERVIEW_ROW, MD_TYPE_ROW):
        for m in rx.finditer(md):
            top.setdefault(m.group(1), f"{source}:{rx.pattern[:20]}")
    for m in MD_METHOD_HEADER.finditer(md):
        top.setdefault(m.group(1), f"{source}:method-header")
        methods.add((m.group(1), m.group(2), f"{source}:method-header"))

    # Quick Reference: method/property bullets under each `### `accessor``
    # header. Some accessors (entity_ops, mining, placement) appear ONLY
    # here -- the detailed sections filter to a hardcoded accessor subset.
    current_accessor = None
    for line in md.splitlines():
        hm = MD_ACCESSOR_HEADER.match(line)
        if hm:
            current_accessor = hm.group(1)
            continue
        if line.startswith(("## ", "### ")):
            current_accessor = None
            continue
        if current_accessor:
            bm = MD_QUICKREF_BULLET.match(line)
            if bm:
                methods.add(
                    (current_accessor, bm.group(1), f"{source}:quick-ref-bullet")
                )

    fences = [(m.group(1), source) for m in CODE_FENCE.finditer(md)]
    return top, methods, fences


def parse_template_promises(md: str):
    top = {}
    in_avail = False
    for line in md.splitlines():
        if line.startswith("### Available"):
            in_avail = True
            continue
        if line.startswith(("### ", "## ", "---")) and not line.startswith(
            "### Available"
        ):
            in_avail = False
        if in_avail:
            m = TEMPLATE_BULLET.match(line)
            if m:
                top[m.group(1)] = "template:available-list"
    fences = [(m.group(1), "template") for m in CODE_FENCE.finditer(md)]
    return top, fences


class FenceNames(ast.NodeVisitor):
    """Collect loaded top-level names and accessor.attr accesses in a fence.

    Distinguishes value-context loads from annotation-context loads
    (`x: List[ItemStack]` mentions List/ItemStack but does not execute them).
    """

    def __init__(self):
        self.value_loaded = set()
        self.annotation_loaded = set()
        self.bound = set()
        self.attr_pairs = set()  # (base_name, attr)
        self._in_annotation = False

    def _visit_annotation(self, node):
        if node is None:
            return
        prev = self._in_annotation
        self._in_annotation = True
        self.visit(node)
        self._in_annotation = prev

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load):
            if self._in_annotation:
                self.annotation_loaded.add(node.id)
            else:
                self.value_loaded.add(node.id)
        else:
            self.bound.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Name) and not self._in_annotation:
            self.attr_pairs.add((node.value.id, node.attr))
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        self._visit_annotation(node.annotation)
        if node.value is not None:
            self.visit(node.value)
        self.visit(node.target)

    def visit_arg(self, node):
        self.bound.add(node.arg)
        self._visit_annotation(node.annotation)

    def visit_FunctionDef(self, node):
        if node.name != "_f_":  # our own wrapper
            self.bound.add(node.name)
        self._visit_annotation(node.returns)
        for child in ast.iter_child_nodes(node):
            if child is not node.returns:
                self.visit(child)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ExceptHandler(self, node):
        if node.name:
            self.bound.add(node.name)
        self.generic_visit(node)

    def visit_comprehension(self, node):
        for n in ast.walk(node.target):
            if isinstance(n, ast.Name):
                self.bound.add(n.id)
        self.visit(node.iter)
        for cond in node.ifs:
            self.visit(cond)

    def visit_Import(self, node):
        for alias in node.names:
            self.bound.add((alias.asname or alias.name).split(".")[0])

    def visit_ImportFrom(self, node):
        for alias in node.names:
            self.bound.add(alias.asname or alias.name)


SIGNATURE_LINE = re.compile(r"^(async )?\w+(\(.*\))?(\s*->\s*.+)?$")


def looks_like_signature_fence(code: str) -> bool:
    """Generated method-signature fences (`craft(recipe: str = ...) -> X`)
    are not executable examples; they are expected to be unparseable."""
    lines = [l for l in code.splitlines() if l.strip()]
    return len(lines) == 1 and bool(SIGNATURE_LINE.match(lines[0].strip()))


def analyze_fence(code: str):
    """Parse a python fence (wrapping for top-level await). Returns
    FenceNames or None if unparseable."""
    tree = None
    try:
        tree = ast.parse(code)
    except SyntaxError:
        try:
            wrapped = "async def _f_():\n" + "\n".join(
                "    " + l for l in code.splitlines()
            )
            tree = ast.parse(wrapped)
        except SyntaxError:
            return None
    v = FenceNames()
    v.visit(tree)
    return v


# --------------------------------------------------------------------------
# Main comparison
# --------------------------------------------------------------------------

def run(args):
    findings = {
        "missing_top_level": [],
        "missing_method": [],
        "unverifiable": [],
        "unparseable_fences": [],
        "signature_fences_skipped": 0,
        "type_mentions_not_injected": [],   # WARN: annotation-only
        "example_locals": [],               # WARN: bound by another fence
        "example_free_values": [],          # WARN: never bound, plain value use
        "stale_file_drift": [],
        "notes": [],
    }
    counters = {
        "namespace_top_level_names": 0,
        "doc_top_level_names_checked": 0,
        "doc_methods_checked": 0,
        "fences_parsed": 0,
        "fence_names_checked": 0,
        "fence_attr_pairs_checked": 0,
    }

    # ---- namespace (ground truth) ----
    ns_names, accessor_classes, ns_notes = extract_namespace()
    findings["notes"].extend(ns_notes)
    counters["namespace_top_level_names"] = len(ns_names)

    attr_cache = {}

    def accessor_has(name: str, attr: str):
        """True / False / None (None = unverifiable offline)."""
        classes = accessor_classes.get(name)
        if not classes:
            return None
        if name not in attr_cache:
            s = set()
            for c in classes:
                if inspect.ismodule(c):
                    s |= {n for n in dir(c) if not n.startswith("_")}
                else:
                    s |= class_attributes(c)
            attr_cache[name] = s
        return attr in attr_cache[name]

    # ---- docs: live-generated API reference (what the system prompt embeds)
    from FactoryVerse.utils.docs.generator import generate_api_reference

    live_md = generate_api_reference()
    (ART_DIR / "live_api_reference.md").write_text(live_md)
    live_top, live_methods, live_fences = parse_markdown_promises(live_md, "live-api-ref")

    # ---- docs: system prompt template
    tpl_md = TEMPLATE_PATH.read_text()
    tpl_top, tpl_fences = parse_template_promises(tpl_md)

    # promised top-level names on the runtime-facing surface
    promised_top = dict(tpl_top)
    promised_top.update(live_top)
    promised_methods = set(live_methods)

    # ---- code fences (live api ref examples + template examples) ----
    # Two passes: first collect every fence's analysis to build the
    # corpus-wide bound-name set (examples legitimately reuse locals defined
    # in earlier examples, signposted by "Preconditions:" prose).
    analyses = []
    for code, where in live_fences + tpl_fences:
        if looks_like_signature_fence(code):
            findings["signature_fences_skipped"] += 1
            continue
        res = analyze_fence(code)
        if res is None:
            findings["unparseable_fences"].append({"where": where, "code": code[:300]})
            continue
        counters["fences_parsed"] += 1
        analyses.append((res, where))

    corpus_bound = set()
    for res, _w in analyses:
        corpus_bound |= res.bound

    for res, where in analyses:
        free_values = res.value_loaded - res.bound - PY_BUILTINS
        ann_only = (
            res.annotation_loaded - res.value_loaded - res.bound - PY_BUILTINS
        )
        attr_bases = {b for b, _a in res.attr_pairs}
        for n in sorted(ann_only):
            if n not in ns_names:
                findings["type_mentions_not_injected"].append(
                    {"name": n, "where": f"{where}:annotation"}
                )
        for n in sorted(free_values):
            counters["fence_names_checked"] += 1
            if n in ns_names:
                continue
            if n[0].isupper():
                # a type the agent is shown using as a value -> hard promise
                findings["missing_top_level"].append(
                    {"name": n, "where": f"{where}:code-fence (type used as value)"}
                )
            elif n in corpus_bound:
                findings["example_locals"].append({"name": n, "where": where})
            elif n in attr_bases:
                # ambient accessor never produced anywhere: PROMPT-1 shape
                findings["missing_top_level"].append(
                    {"name": n, "where": f"{where}:code-fence (ambient accessor)"}
                )
            else:
                findings["example_free_values"].append({"name": n, "where": where})
        for base, attr in sorted(res.attr_pairs):
            if base in ns_names:
                counters["fence_attr_pairs_checked"] += 1
                promised_methods.add((base, attr, f"{where}:code-fence"))

    # ---- compare top-level
    for name, where in sorted(promised_top.items()):
        counters["doc_top_level_names_checked"] += 1
        if name not in ns_names:
            findings["missing_top_level"].append({"name": name, "where": where})

    # ---- compare methods
    seen_pairs = set()
    for acc, meth, where in sorted(promised_methods):
        if (acc, meth) in seen_pairs:
            continue
        seen_pairs.add((acc, meth))
        if acc not in ns_names:
            continue  # already reported as missing top-level
        counters["doc_methods_checked"] += 1
        has = accessor_has(acc, meth)
        if has is False:
            findings["missing_method"].append(
                {"accessor": acc, "method": meth, "where": where}
            )
        elif has is None:
            findings["unverifiable"].append(
                {"accessor": acc, "method": meth, "where": where}
            )

    # ---- stale checked-in api_reference.md (drift report only)
    if CHECKED_IN_API_REF.exists():
        stale_md = CHECKED_IN_API_REF.read_text()
        s_top, s_methods, _ = parse_markdown_promises(stale_md, "checked-in-file")
        for name in sorted(s_top):
            if name not in ns_names:
                findings["stale_file_drift"].append({"missing_top_level": name})
        for acc, meth, _w in sorted(s_methods):
            if acc in ns_names and accessor_has(acc, meth) is False:
                findings["stale_file_drift"].append({"missing_method": f"{acc}.{meth}"})

    # ---- anti-vacuity guards ----
    guards = [
        ("namespace_top_level_names", 10),
        ("doc_top_level_names_checked", 10),
        ("doc_methods_checked", 30),
        ("fences_parsed", 10),
    ]
    vacuity_failures = [
        f"{k}={counters[k]} (need >{v})" for k, v in guards if counters[k] <= v
    ]

    # ---- artifacts ----
    report = {
        "namespace_names": sorted(ns_names),
        "accessor_classes": {
            k: [getattr(c, "__name__", str(c)) for c in v]
            for k, v in accessor_classes.items()
        },
        "promised_top_level": promised_top,
        "promised_methods": sorted(
            f"{a}.{m} [{w}]" for a, m, w in promised_methods
        ),
        "counters": counters,
        "findings": findings,
        "vacuity_failures": vacuity_failures,
    }
    (ART_DIR / "report.json").write_text(json.dumps(report, indent=2))

    # ---- verdict ----
    hard_misses = findings["missing_top_level"] + findings["missing_method"]
    print(f"namespace top-level names: {counters['namespace_top_level_names']}")
    print(f"doc top-level names checked: {counters['doc_top_level_names_checked']}")
    print(f"doc methods checked: {counters['doc_methods_checked']}")
    print(f"code fences parsed: {counters['fences_parsed']}")
    print(f"fence attr pairs folded in: {counters['fence_attr_pairs_checked']}")
    print(f"missing top-level: {len(findings['missing_top_level'])}")
    print(f"missing methods: {len(findings['missing_method'])}")
    print(f"unverifiable (no class resolved): {len(findings['unverifiable'])}")
    print(f"signature fences skipped: {findings['signature_fences_skipped']}")
    print(f"unparseable non-signature fences: {len(findings['unparseable_fences'])}")
    print(
        "warns: type-mentions={} example-locals={} example-free-values={}".format(
            len(findings["type_mentions_not_injected"]),
            len(findings["example_locals"]),
            len(findings["example_free_values"]),
        )
    )
    print(f"stale checked-in file drift entries: {len(findings['stale_file_drift'])}")
    for f in hard_misses:
        print(f"  MISS: {f}")
    for f in findings["unverifiable"]:
        print(f"  UNVERIFIABLE: {f['accessor']}.{f['method']} [{f['where']}]")

    if vacuity_failures:
        print(f"VACUOUS-RISK: {vacuity_failures}")
        return 2
    if hard_misses:
        print("STATUS: FAIL")
        return 1
    print("STATUS: PASS")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--instance",
        default=None,
        help="Unused (offline check); accepted for harness uniformity",
    )
    args = parser.parse_args()
    try:
        sys.exit(run(args))
    except Exception:
        traceback.print_exc()
        (ART_DIR / "crash.txt").write_text(traceback.format_exc())
        sys.exit(2)
