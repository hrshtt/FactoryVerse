#!/usr/bin/env python
"""Read-only lens into a running FactoryVerse session. Safe to run anytime,
concurrently with anything (playbook §5: read-only probes don't conflict).

Usage:
    uv run python scripts/certification/observe.py            # one shot
    uv run python scripts/certification/observe.py --watch 5  # re-probe every 5s

Shows: game tick, entity census by name (player force), test-ground bounds
and rig area contents if that scenario is loaded, freshest snapshot file,
and recent certification runner heartbeats.
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from factorio_rcon import RCONClient

REPO_ROOT = Path(__file__).resolve().parents[2]
CERT_DIR = REPO_ROOT / ".fv-output" / "certification"
SCRIPT_OUTPUT = Path.home() / "Library/Application Support/factorio/script-output"


def resolve_instance(name: str) -> tuple[int, Path]:
    """(rcon_port, script_output_root) for 'client' or 'server_N'.
    Server script-output maps to host .fv-output/server_N (compose volume)."""
    if name == "client":
        return 27100, Path.home() / "Library/Application Support/factorio/script-output"
    if name.startswith("server_"):
        return 27000 + int(name.split("_")[1]), REPO_ROOT / ".fv-output" / name
    raise SystemExit(f"unknown instance {name!r}; use 'client' or 'server_N'")

CENSUS_LUA = """
local ok, res = xpcall(function()
  local s = game.surfaces[1]
  local by_name = {}
  local n = 0
  for _, e in pairs(s.find_entities_filtered{force='player'}) do
    by_name[e.name] = (by_name[e.name] or 0) + 1
    n = n + 1
  end
  local out = {tick = game.tick, total = n, by_name = by_name, interfaces = {}}
  for name, _ in pairs(remote.interfaces) do table.insert(out.interfaces, name) end
  return out
end, debug.traceback)
if ok then rcon.print(helpers.table_to_json(res))
else rcon.print(helpers.table_to_json({err = tostring(res)})) end
"""

BOUNDS_LUA = """
local ok, res = xpcall(function()
  return remote.call('test_ground', 'get_test_bounds')
end, debug.traceback)
if ok then rcon.print(helpers.table_to_json(res))
else rcon.print(helpers.table_to_json({err = tostring(res)})) end
"""


def lua(rcon: RCONClient, code: str) -> dict:
    return json.loads(rcon.send_command("/c " + code.strip()))


def freshest(root: Path, pattern: str) -> str:
    files = sorted(root.rglob(pattern), key=lambda p: p.stat().st_mtime, reverse=True) if root.exists() else []
    if not files:
        return "none"
    f = files[0]
    age = time.time() - f.stat().st_mtime
    return f"{f.relative_to(root)} ({age:.0f}s ago)"


def heartbeats() -> list[str]:
    lines = []
    if CERT_DIR.exists():
        for log in sorted(CERT_DIR.rglob("progress.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]:
            tail = log.read_text().strip().splitlines()[-3:]
            age = time.time() - log.stat().st_mtime
            lines.append(f"{log.parent.name} ({age:.0f}s ago): " + " | ".join(tail))
    return lines or ["no runner heartbeats"]


def probe(rcon: RCONClient) -> None:
    now = datetime.now().strftime("%H:%M:%S")
    census = lua(rcon, CENSUS_LUA)
    print(f"[{now}] tick={census.get('tick')} entities(player)={census.get('total')}")
    for name, count in sorted((census.get("by_name") or {}).items()):
        print(f"    {count:5d}  {name}")
    if "test_ground" in (census.get("interfaces") or []):
        print(f"    test_ground bounds: {lua(rcon, BOUNDS_LUA)}")
    print(f"    freshest snapshot file: {freshest(SCRIPT_OUTPUT / 'factoryverse', '*.jsonl')}")
    for hb in heartbeats():
        print(f"    heartbeat: {hb}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", type=float, default=0, help="re-probe every N seconds")
    ap.add_argument("--instance", default="client", help="client or server_N")
    args = ap.parse_args()

    global SCRIPT_OUTPUT
    port, SCRIPT_OUTPUT = resolve_instance(args.instance)
    rcon = RCONClient("localhost", port, "factorio")
    rcon.send_command("/c rcon.print('ping')")
    while True:
        probe(rcon)
        if not args.watch:
            break
        time.sleep(args.watch)


if __name__ == "__main__":
    sys.exit(main())
