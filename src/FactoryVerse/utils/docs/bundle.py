"""Build a routed, granular documentation bundle for coding harnesses."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Dict


_ACCESSOR_RE = re.compile(r"^\*\*Accessor:\*\* `([^`]+)`$", re.MULTILINE)
_CLASS_RE = re.compile(r"^### (?!`)(.+)$", re.MULTILINE)
_H2_RE = re.compile(r"^## (.+)$", re.MULTILINE)
_METHOD_RE = re.compile(r"^#### `([^`]+)`$", re.MULTILINE)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _class_sections(markdown: str) -> Dict[str, str]:
    """Return detailed class sections keyed by their runtime accessor."""
    matches = list(_CLASS_RE.finditer(markdown))
    sections: Dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        section = markdown[match.start():end].strip()
        accessor = _ACCESSOR_RE.search(section)
        if accessor:
            sections[accessor.group(1)] = section
    return sections


def _h2_sections(markdown: str) -> Dict[str, str]:
    matches = list(_H2_RE.finditer(markdown))
    sections: Dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections[_slug(match.group(1))] = markdown[match.start():end].strip()
    return sections


def _method_sections(class_section: str) -> Dict[str, str]:
    matches = list(_METHOD_RE.finditer(class_section))
    sections: Dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(class_section)
        symbol = match.group(1)
        method = symbol.rsplit(".", 1)[-1]
        sections[_slug(method)] = class_section[match.start():end].strip()
    return sections


def write_reference_bundle(
    api_source: Path,
    schema_source: Path,
    destination: Path,
) -> Dict[str, str]:
    """Write focused files plus an index while preserving monolithic fallbacks.

    Returns a mapping from bundle-relative path to SHA-256 digest.
    """
    api_text = Path(api_source).read_text(encoding="utf-8")
    schema_text = Path(schema_source).read_text(encoding="utf-8")
    destination = Path(destination)
    api_dir = destination / "api"
    schema_dir = destination / "schema"
    api_dir.mkdir(parents=True, exist_ok=True)
    schema_dir.mkdir(parents=True, exist_ok=True)

    files: Dict[str, str] = {
        "api_reference.md": api_text,
        "schema_reference.md": schema_text,
    }
    accessors = _class_sections(api_text)
    for accessor, section in sorted(accessors.items()):
        files[f"api/{accessor}.md"] = (
            f"# FactoryVerse `{accessor}` API\n\n{section}\n"
        )
        for method, method_section in sorted(_method_sections(section).items()):
            files[f"api/{accessor}/{method}.md"] = (
                f"# FactoryVerse `{accessor}.{method}`\n\n{method_section}\n"
            )
    for slug, section in sorted(_h2_sections(schema_text).items()):
        files[f"schema/{slug}.md"] = f"# FactoryVerse schema: {slug}\n\n{section}\n"

    routes = {
        "move, navigate, walk": "api/walking.md",
        "craft, recipe, hand-crafting queue": "api/crafting.md",
        "inventory, item stacks, await_item": "api/inventory.md",
        "nearby, reachable, entities as objects": "api/reachable_view.md",
        "map, SQL, resource search, water tiles, base-wide status/power/production": "api/remote_view.md",
        "hold an item: footprint, can_place, connection cues, coverage, pump sites": "api/entity_reference.md",
        "research state and queue": "api/research.md",
    }
    index_lines = [
        "# FactoryVerse Reference Router",
        "",
        "Load only the files relevant to the current question. Use the monolithic",
        "references only if a routed file is insufficient.",
        "",
        "## Task routes",
        "",
    ]
    for task, path in routes.items():
        availability = "" if path in files else " (detail currently unavailable)"
        index_lines.append(f"- {task}: `{path}`{availability}")
    index_lines.extend(
        [
            "",
            "## Data and types",
            "",
            "- SQL safety and limits: `schema/query-constraints.md`",
            "- Returned object shapes: `schema/return-types.md`",
            "- DuckDB tables: `schema/table-reference.md`",
            "- Query examples: `schema/common-query-patterns.md`",
            "- End-to-end query flow: `schema/complete-workflow-example.md`",
            "",
            "## Complete fallbacks",
            "",
            "- `api_reference.md`",
            "- `schema_reference.md`",
            "",
            "## Bundle provenance",
            "",
            f"- API source SHA-256: `{_sha256(api_text)}`",
            f"- Schema source SHA-256: `{_sha256(schema_text)}`",
            "",
        ]
    )
    files["INDEX.md"] = "\n".join(index_lines)

    digests: Dict[str, str] = {}
    for relative, content in files.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        digests[relative] = _sha256(content)
    return digests
