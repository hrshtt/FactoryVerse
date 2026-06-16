"""Ground-truth entity census via chunked RCON iteration.

Dumps every entity on a force (plus neutral resources) to a JSONL file in
script-output via ``helpers.write_file``, then reads it back on the host.
This is read channel #2 from the runtime playbook (raw surface scan) made
scalable: RCON responses have buffer limits, so bulk data goes through the
file system, chunked 32x32-tile-chunk batches per RCON call.

Used by certification check L1.1 (census parity vs snapshot DuckDB).

Rules honored:
- NEVER references unit_number (entity_name + position only).
- Read-only against the game: only ``find_entities_filtered`` + file writes
  to ``factoryverse/dumps/`` inside script-output.
- All Lua is xpcall-wrapped; an empty RCON response is treated as an error.
"""

from __future__ import annotations

import datetime
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from factorio_rcon import RCONClient

from FactoryVerse.infra.instance_manager import FactorioInstance, FactorioInstanceManager

CHUNK_TILES = 32
DUMPS_REL_DIR = "factoryverse/dumps"

Bounds = Tuple[float, float, float, float]  # x1, y1, x2, y2 (half-open)


class CensusError(RuntimeError):
    """Census dump failed (Lua error, empty RCON response, missing file)."""


@dataclass
class CensusResult:
    """Result of a census dump."""

    rows: List[Dict[str, Any]]
    host_path: Path
    game_relative_path: str
    instance: str
    force: str
    include_resources: bool
    bounds: Optional[Bounds]
    tick: int
    chunk_count: int
    rcon_calls: int
    lua_written: int  # rows the Lua side claims it wrote (cross-check vs len(rows))
    counts_by_type: Dict[str, int] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.rows)

    def dataframe(self):
        """Rows as a pandas DataFrame (position flattened to x/y columns)."""
        import pandas as pd

        flat = [
            {
                "name": r["name"],
                "type": r["type"],
                "x": r["position"]["x"],
                "y": r["position"]["y"],
                "direction": r.get("direction", 0),
            }
            for r in self.rows
        ]
        return pd.DataFrame(flat, columns=["name", "type", "x", "y", "direction"])


def _resolve_instance(name: str) -> FactorioInstance:
    if name == "client":
        return FactorioInstanceManager.get_client()
    if name.startswith("server_"):
        return FactorioInstanceManager.get_server(int(name.split("_")[1]))
    raise ValueError(f"unknown instance {name!r}; expected 'client' or 'server_N'")


def _lua(rcon: RCONClient, body: str) -> Dict[str, Any]:
    """Run Lua body (must ``return <table>``), parse JSON. Raise on any error.

    Empty RCON response means the Lua errored outside our xpcall (playbook
    trap on docker servers) — surfaced as CensusError, never swallowed.
    """
    wrapped = (
        "/c local ok, res = xpcall(function() "
        + body
        + " end, debug.traceback) "
        + "if ok then rcon.print(helpers.table_to_json(res == nil and {ok=true} or res)) "
        + "else rcon.print(helpers.table_to_json({error = tostring(res)})) end"
    )
    out = rcon.send_command(wrapped)
    if out is None or out.strip() == "":
        raise CensusError("empty RCON response (Lua errored outside xpcall?)")
    try:
        res = json.loads(out)
    except json.JSONDecodeError as e:
        raise CensusError(f"non-JSON RCON response: {out[:500]}") from e
    if isinstance(res, dict) and "error" in res:
        raise CensusError(f"Lua error: {str(res['error'])[:1000]}")
    return res


def _chunks_from_bounds(bounds: Bounds) -> List[Tuple[int, int]]:
    import math

    x1, y1, x2, y2 = bounds
    cx1, cy1 = math.floor(x1 / CHUNK_TILES), math.floor(y1 / CHUNK_TILES)
    cx2, cy2 = math.ceil(x2 / CHUNK_TILES), math.ceil(y2 / CHUNK_TILES)
    return [(cx, cy) for cx in range(cx1, cx2) for cy in range(cy1, cy2)]


def _generated_chunks(rcon: RCONClient, rel_chunks_path: str, host_chunks_path: Path) -> List[Tuple[int, int]]:
    """Enumerate generated chunks. List can be thousands of entries → goes
    through a script-output file, not the RCON return (buffer limits)."""
    res = _lua(
        rcon,
        f"""
        local s = game.surfaces[1]
        local parts = {{}}
        local n = 0
        for c in s.get_chunks() do
            n = n + 1
            parts[#parts+1] = '[' .. c.x .. ',' .. c.y .. ']'
        end
        helpers.write_file('{rel_chunks_path}', '[' .. table.concat(parts, ',') .. ']', false)
        return {{n = n}}
        """,
    )
    expected = int(res.get("n", 0))
    deadline = time.time() + 15
    while time.time() < deadline:
        if host_chunks_path.exists():
            try:
                chunks = json.loads(host_chunks_path.read_text())
                if len(chunks) == expected:
                    return [(int(c[0]), int(c[1])) for c in chunks]
            except (json.JSONDecodeError, OSError):
                pass  # partially flushed; retry
        time.sleep(0.5)
    raise CensusError(
        f"chunk list file not readable within 15s: {host_chunks_path} (expected {expected} chunks)"
    )


def _batch_lua(
    rel_path: str,
    force: str,
    include_resources: bool,
    chunk_batch: List[Tuple[int, int]],
    bounds: Optional[Bounds],
) -> str:
    """Lua for one RCON call: scan a batch of chunks, append JSONL lines.

    Entities are attributed to the chunk that contains their *position*
    (find_entities_filtered matches bbox overlap → an entity spanning a
    chunk border would otherwise be emitted twice).
    """
    chunk_list = ",".join(f"{{{cx},{cy}}}" for cx, cy in chunk_batch)
    if bounds is not None:
        x1, y1, x2, y2 = bounds
        clamp = (
            f"ax1 = math.max(ax1, {x1}); ay1 = math.max(ay1, {y1}); "
            f"ax2 = math.min(ax2, {x2}); ay2 = math.min(ay2, {y2}); "
        )
    else:
        clamp = ""
    resource_block = ""
    if include_resources:
        # Guard avoids double-count if force itself is 'neutral'.
        resource_block = f"""
            for _, e in ipairs(s.find_entities_filtered{{area = area, type = 'resource'}}) do
                if e.force.name ~= '{force}' then emit(e) end
            end"""
    return f"""
        local s = game.surfaces[1]
        local lines = {{}}
        local emitted = {{}}
        local ax1, ay1, ax2, ay2
        local function emit(e)
            local p = e.position
            if p.x >= ax1 and p.x < ax2 and p.y >= ay1 and p.y < ay2 then
                lines[#lines+1] = helpers.table_to_json({{
                    name = e.name, type = e.type,
                    position = {{x = p.x, y = p.y}},
                    direction = e.direction,
                }})
            end
        end
        for _, c in ipairs({{{chunk_list}}}) do
            ax1, ay1 = c[1] * {CHUNK_TILES}, c[2] * {CHUNK_TILES}
            ax2, ay2 = ax1 + {CHUNK_TILES}, ay1 + {CHUNK_TILES}
            {clamp}
            if ax1 < ax2 and ay1 < ay2 then
                local area = {{{{ax1, ay1}}, {{ax2, ay2}}}}
                for _, e in ipairs(s.find_entities_filtered{{area = area, force = '{force}'}}) do
                    emit(e)
                end
                {resource_block}
            end
        end
        if #lines > 0 then
            helpers.write_file('{rel_path}', table.concat(lines, '\\n') .. '\\n', true)
        end
        return {{written = #lines}}
    """


def dump_census(
    instance: str = "client",
    force: str = "player",
    include_resources: bool = True,
    bounds: Optional[Bounds] = None,
    chunks_per_call: int = 64,
    rcon: Optional[RCONClient] = None,
) -> CensusResult:
    """Dump a ground-truth entity census to JSONL and read it back.

    Args:
        instance: 'client' or 'server_N'.
        force: force whose entities to enumerate (default 'player').
        include_resources: also enumerate type='resource' (neutral ores).
        bounds: optional (x1, y1, x2, y2) half-open tile bounds; default =
            every generated chunk.
        chunks_per_call: 32x32 chunks scanned per RCON call.
        rcon: reuse an existing connection (else one is created).

    Returns:
        CensusResult with parsed rows and the host JSONL path.
    """
    inst = _resolve_instance(instance)
    own_rcon = rcon is None
    if rcon is None:
        rcon = RCONClient(inst.rcon_host, inst.rcon_port, inst.rcon_password)
        rcon.send_command("/c rcon.print('ping')")  # first command may warn

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    rel_path = f"{DUMPS_REL_DIR}/census-{stamp}.jsonl"
    rel_chunks_path = f"{DUMPS_REL_DIR}/census-{stamp}.chunks.json"
    host_path = inst.script_output_dir / rel_path
    host_chunks_path = inst.script_output_dir / rel_chunks_path

    try:
        tick = int(_lua(rcon, "return {tick = game.tick}")["tick"])

        if bounds is not None:
            chunks = _chunks_from_bounds(bounds)
        else:
            chunks = _generated_chunks(rcon, rel_chunks_path, host_chunks_path)

        # Truncate/create the dump file (append=false), then batches append.
        _lua(rcon, f"helpers.write_file('{rel_path}', '', false) return {{ok = true}}")

        rcon_calls = 1
        lua_written = 0
        for i in range(0, len(chunks), chunks_per_call):
            batch = chunks[i : i + chunks_per_call]
            res = _lua(rcon, _batch_lua(rel_path, force, include_resources, batch, bounds))
            lua_written += int(res.get("written", 0))
            rcon_calls += 1
    finally:
        if own_rcon:
            try:
                rcon.close()
            except Exception:
                pass

    # Read the file back from host script-output (volume/file flush may lag).
    rows: List[Dict[str, Any]] = []
    deadline = time.time() + 30
    while time.time() < deadline:
        if host_path.exists():
            rows = [
                json.loads(line)
                for line in host_path.read_text().splitlines()
                if line.strip()
            ]
            if len(rows) >= lua_written:
                break
        time.sleep(0.5)
    if not host_path.exists():
        if lua_written == 0:
            rows = []  # legitimately empty census; write_file('') may not flush a file
        else:
            raise CensusError(f"census file never appeared on host: {host_path}")
    if len(rows) != lua_written:
        raise CensusError(
            f"row count mismatch: Lua wrote {lua_written}, host file has {len(rows)} ({host_path})"
        )

    counts_by_type: Dict[str, int] = {}
    for r in rows:
        counts_by_type[r["type"]] = counts_by_type.get(r["type"], 0) + 1

    return CensusResult(
        rows=rows,
        host_path=host_path,
        game_relative_path=rel_path,
        instance=inst.name,
        force=force,
        include_resources=include_resources,
        bounds=bounds,
        tick=tick,
        chunk_count=len(chunks),
        rcon_calls=rcon_calls,
        lua_written=lua_written,
        counts_by_type=counts_by_type,
    )


def direct_count(
    instance: str = "client",
    force: str = "player",
    include_resources: bool = True,
    bounds: Optional[Bounds] = None,
    rcon: Optional[RCONClient] = None,
) -> int:
    """Independent single-call count with the same semantics as dump_census
    (position-inside-bounds, force + neutral resources). For cross-checking
    the chunked dump — does NOT share the chunk-iteration code path.
    """
    inst = _resolve_instance(instance)
    own_rcon = rcon is None
    if rcon is None:
        rcon = RCONClient(inst.rcon_host, inst.rcon_port, inst.rcon_password)
        rcon.send_command("/c rcon.print('ping')")

    if bounds is not None:
        x1, y1, x2, y2 = bounds
        area_arg = f"area = {{{{{x1}, {y1}}}, {{{x2}, {y2}}}}}, "
        pos_filter = f"p.x >= {x1} and p.x < {x2} and p.y >= {y1} and p.y < {y2}"
    else:
        area_arg = ""
        pos_filter = "true"
    resource_block = ""
    if include_resources:
        resource_block = f"""
        for _, e in ipairs(s.find_entities_filtered{{{area_arg}type = 'resource'}}) do
            local p = e.position
            if e.force.name ~= '{force}' and ({pos_filter}) then n = n + 1 end
        end"""
    try:
        res = _lua(
            rcon,
            f"""
            local s = game.surfaces[1]
            local n = 0
            for _, e in ipairs(s.find_entities_filtered{{{area_arg}force = '{force}'}}) do
                local p = e.position
                if {pos_filter} then n = n + 1 end
            end
            {resource_block}
            return {{n = n}}
            """,
        )
    finally:
        if own_rcon:
            try:
                rcon.close()
            except Exception:
                pass
    return int(res["n"])


def parse_bounds(text: Optional[str]) -> Optional[Bounds]:
    """Parse 'x1,y1,x2,y2' CLI bounds."""
    if not text:
        return None
    parts = [float(p) for p in text.split(",")]
    if len(parts) != 4:
        raise ValueError("--bounds expects x1,y1,x2,y2")
    x1, y1, x2, y2 = parts
    if x1 >= x2 or y1 >= y2:
        raise ValueError("--bounds must satisfy x1<x2 and y1<y2")
    return (x1, y1, x2, y2)
