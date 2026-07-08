"""Fetch + split the machine-readable Factorio Lua API docs for piecewise sub-agent checkout.

Search once, use many times: downloads the versioned runtime-api.json and
prototype-api.json from lua-api.factorio.com, splits them into one file per
class/event/concept/prototype/type, and writes an INDEX.md so a sub-agent can
grep the index and read ONLY the file it needs instead of web-searching.

Usage:
    uv run python scripts/fetch_factorio_api.py 2.0.76
    uv run python scripts/fetch_factorio_api.py 2.0.76 --skip-fetch  # re-split existing downloads

Output layout (resources/factorio-api/<version>/):
    runtime-api.json / prototype-api.json   -- full originals (kept for re-splits)
    runtime/classes/<LuaClass>.json         -- 1 file per runtime class
    runtime/events/<event>.json             -- 1 file per event
    runtime/concepts/<Concept>.json         -- 1 file per concept
    runtime/defines.json                    -- all defines (small, one file)
    prototype/prototypes/<Prototype>.json   -- 1 file per prototype
    prototype/types/<Type>.json             -- 1 file per prototype type
    INDEX.md                                -- name -> path -> first-sentence description
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

BASE_URL = "https://lua-api.factorio.com/{version}/{name}"
REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = REPO_ROOT / "resources" / "factorio-api"


def fetch(version: str, name: str, dest: Path) -> None:
    url = BASE_URL.format(version=version, name=name)
    print(f"fetching {url}")
    with urllib.request.urlopen(url) as resp:
        dest.write_bytes(resp.read())


def first_sentence(desc: str | None, limit: int = 140) -> str:
    if not desc:
        return ""
    line = re.split(r"(?<=[.!?])\s", desc.strip().replace("\n", " "), maxsplit=1)[0]
    return (line[: limit - 1] + "…") if len(line) > limit else line


def split_items(items: list[dict], out_dir: Path) -> list[tuple[str, str, str]]:
    """Write one JSON file per item; return (name, relpath, description) index rows."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for item in items:
        name = item["name"]
        path = out_dir / f"{name}.json"
        path.write_text(json.dumps(item, indent=1))
        rows.append((name, str(path.relative_to(out_dir.parent.parent)), first_sentence(item.get("description"))))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("version", help="Factorio version, e.g. 2.0.76 (must match the certified engine image)")
    ap.add_argument("--skip-fetch", action="store_true", help="re-split already-downloaded JSONs")
    args = ap.parse_args()

    vdir = OUT_ROOT / args.version
    vdir.mkdir(parents=True, exist_ok=True)

    for fname in ("runtime-api.json", "prototype-api.json"):
        if not args.skip_fetch or not (vdir / fname).exists():
            fetch(args.version, fname, vdir / fname)

    runtime = json.loads((vdir / "runtime-api.json").read_text())
    proto = json.loads((vdir / "prototype-api.json").read_text())
    assert runtime["application_version"] == args.version, runtime["application_version"]
    assert proto["application_version"] == args.version, proto["application_version"]

    sections: list[tuple[str, list[tuple[str, str, str]]]] = []
    sections.append(("Runtime classes", split_items(runtime["classes"], vdir / "runtime" / "classes")))
    sections.append(("Runtime events", split_items(runtime["events"], vdir / "runtime" / "events")))
    sections.append(("Runtime concepts", split_items(runtime["concepts"], vdir / "runtime" / "concepts")))
    (vdir / "runtime" / "defines.json").write_text(json.dumps(runtime["defines"], indent=1))
    sections.append(("Prototypes", split_items(proto["prototypes"], vdir / "prototype" / "prototypes")))
    sections.append(("Prototype types", split_items(proto["types"], vdir / "prototype" / "types")))

    index = vdir / "INDEX.md"
    with index.open("w") as f:
        f.write(
            f"# Factorio {args.version} Lua API — piecewise index\n\n"
            f"Source: lua-api.factorio.com/{args.version} (runtime api_version {runtime['api_version']}). "
            f"Regenerate: `uv run python scripts/fetch_factorio_api.py {args.version}`.\n\n"
            "Sub-agent protocol: grep this index for the entity/concept you need, then Read ONLY that file. "
            "`runtime/defines.json` holds all defines in one file. Do not web-search what is answerable here.\n"
        )
        for title, rows in sections:
            f.write(f"\n## {title} ({len(rows)})\n\n")
            for name, rel, desc in sorted(rows):
                f.write(f"- `{name}` — {rel}" + (f" — {desc}\n" if desc else "\n"))

    total = sum(len(r) for _, r in sections)
    print(f"split {total} items into {vdir} + defines.json; index at {index}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
