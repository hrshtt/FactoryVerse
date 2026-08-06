"""Single reducers for file-backed analytics and state feeds.

This extends the PROV-2 single-reducer discipline to every file family.

These functions are the only writers to the agent analytics, power, and
entity-status tables. Both transports normalize their envelopes and call them:

- ``SnapshotLoader`` — boot-time file replay (reads the bounded
  power_networks.jsonl file in full, and the newest status-<tick>.jsonl dump)
- ``SyncService``   — live UDP during a session (reads the last line of
  power_networks.jsonl / the full latest status dump on each file_io
  notification)

Having one reducer means identical logical input (a parsed jsonl line, or a
parsed status dump) produces identical rows regardless of which path
delivered it — the same discipline apply_ops.py established for
map_entity/ghost.

power_samples/power_networks (C1 line shape):
    {"tick": N, "networks": [{"network_id":..., "anchor_pole": {...},
     "pole_count":..., "member_count":..., "production_w":...,
     "consumption_w":..., "storage_j":...,
     "production_w_by_prototype": {...}, "consumption_w_by_prototype": {...}}]}
    Idempotent on re-apply of the same tick: power_samples uses INSERT OR
    REPLACE keyed on tick; power_networks has no primary key (it is a history
    table) so re-applying the same tick DELETEs that tick's rows first.

entity_status (C2 dump shape): first line {"meta": true, "tick": N,
    "count": M}, then M lines of {"name", "status", "x", "y"}. FULL REPLACE:
    every ingested dump is a complete statement of current statuses, so
    ingestion deletes all rows then inserts the dump's rows. A freshness
    marker (the dump's tick) is written to sync_state under the key
    'entity_status_last_tick' so "a dump WAS applied" is observable even for
    an all-meta, zero-entity dump (count=0) — the table being empty is
    otherwise indistinguishable from "never ingested anything".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


def apply_agent_production_sample(db, line: Dict[str, Any]) -> int:
    """Apply one complete force-level production snapshot for an agent."""
    if "agent_id" not in line or "tick" not in line:
        raise ValueError("production sample requires agent_id and tick")
    agent_id = int(line["agent_id"])
    tick = int(line["tick"])
    statistics = {
        "input": line.get("input") or {},
        "output": line.get("output") or {},
    }
    db.execute(
        """
        INSERT OR REPLACE INTO agent_production_statistics
        (agent_id, tick, statistics) VALUES (?, ?, ?)
        """,
        [agent_id, tick, json.dumps(statistics, sort_keys=True)],
    )
    return tick


def apply_agent_manual_snapshot(
    db,
    *,
    agent_id: int,
    crafted: Dict[str, int],
    mined: Dict[str, int],
    tick: int,
) -> int:
    """Write one cumulative manual-production snapshot, idempotently."""
    db.execute(
        """
        INSERT OR REPLACE INTO agent_manual_production_statistics
        (agent_id, tick, crafted, mined) VALUES (?, ?, ?, ?)
        """,
        [
            int(agent_id),
            int(tick),
            json.dumps(crafted, sort_keys=True),
            json.dumps(mined, sort_keys=True),
        ],
    )
    return int(tick)


def aggregate_product_events(path: Path) -> Tuple[Dict[str, int], int, int | None]:
    """Aggregate product counts from a crafting or mining event JSONL file."""
    totals: Dict[str, int] = {}
    latest_tick = 0
    agent_id = None
    if not path.exists():
        return totals, latest_tick, agent_id
    with open(path, "r", encoding="utf-8") as handle:
        for raw in handle:
            raw = raw.strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                # A live reader can race a final append; the next file_io
                # notification retries from the complete file.
                continue
            if event.get("agent_id") is not None:
                agent_id = int(event["agent_id"])
            latest_tick = max(latest_tick, int(event.get("tick", 0)))
            for item_name, count in (event.get("products") or {}).items():
                key = str(item_name)
                totals[key] = totals.get(key, 0) + int(count)
    return totals, latest_tick, agent_id


def apply_agent_manual_files(db, agent_dir: Path, agent_id: int | None = None) -> int:
    """Rebuild cumulative crafting/mining statistics from both event files."""
    crafted, crafted_tick, crafting_agent = aggregate_product_events(
        agent_dir / "crafting-statistics.jsonl"
    )
    mined, mined_tick, mining_agent = aggregate_product_events(
        agent_dir / "mining-statistics.jsonl"
    )
    resolved_agent = agent_id or crafting_agent or mining_agent
    if resolved_agent is None:
        try:
            resolved_agent = int(agent_dir.name)
        except ValueError as exc:
            raise ValueError(f"cannot infer agent id from {agent_dir}") from exc
    tick = max(crafted_tick, mined_tick)
    if tick == 0 and not crafted and not mined:
        return 0
    return apply_agent_manual_snapshot(
        db,
        agent_id=resolved_agent,
        crafted=crafted,
        mined=mined,
        tick=tick,
    )


def apply_power_sample(db, line: Dict[str, Any]) -> int:
    """Apply one power_networks.jsonl line (heartbeat or with networks).

    Writes one power_samples row (INSERT OR REPLACE on tick) and replaces
    that tick's power_networks rows (DELETE then INSERT — power_networks has
    no primary key, it is an append-style history table, so re-applying the
    same tick must not duplicate rows).

    Args:
        db: DuckDB connection (schema must already exist).
        line: parsed JSON line, e.g. {"tick": 12345, "networks": [...]}.

    Returns:
        Number of network rows written for this tick.
    """
    tick = int(line.get("tick", 0))
    networks = line.get("networks") or []

    db.execute(
        "INSERT OR REPLACE INTO power_samples (tick, network_count) VALUES (?, ?)",
        [tick, len(networks)],
    )

    db.execute("DELETE FROM power_networks WHERE tick = ?", [tick])

    for net in networks:
        anchor = net.get("anchor_pole") or {}
        anchor_pos = anchor.get("position") or {}
        db.execute(
            """
            INSERT INTO power_networks
            (tick, network_id, anchor_pole_name, anchor_pole_x, anchor_pole_y,
             pole_count, member_count, production_w, consumption_w, storage_j,
             production_by_prototype, consumption_by_prototype)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON, ?::JSON)
            """,
            [
                tick,
                net.get("network_id"),
                anchor.get("name"),
                anchor_pos.get("x"),
                anchor_pos.get("y"),
                net.get("pole_count"),
                net.get("member_count"),
                net.get("production_w"),
                net.get("consumption_w"),
                net.get("storage_j"),
                json.dumps(net.get("production_w_by_prototype") or {}),
                json.dumps(net.get("consumption_w_by_prototype") or {}),
            ],
        )

    return len(networks)


def apply_status_dump(db, lines: List[Dict[str, Any]]) -> int:
    """Apply one full entity_status dump (C2): FULL REPLACE.

    Args:
        db: DuckDB connection (schema must already exist).
        lines: parsed JSON lines from a status-<tick>.jsonl file. lines[0]
            MUST be the meta line ``{"meta": true, "tick": N, "count": M}``;
            lines[1:] are ``{"name", "status", "x", "y"}`` entity records.

    Returns:
        Number of entity rows written (0 for an all-meta, zero-entity dump).

    Raises:
        ValueError: if lines is empty or lines[0] is not a valid meta line —
            a malformed dump must fail loudly rather than silently wiping
            entity_status on garbage input.
    """
    if not lines:
        raise ValueError("apply_status_dump: empty lines (missing meta line)")

    meta = lines[0]
    if not (isinstance(meta, dict) and meta.get("meta") is True and "tick" in meta):
        raise ValueError(
            f"apply_status_dump: first line is not a valid meta line: {meta!r}"
        )
    tick = int(meta["tick"])
    entity_lines = lines[1:]

    db.execute("DELETE FROM entity_status;")
    for rec in entity_lines:
        name = rec.get("name", "")
        status_name = rec.get("status", "")
        x = float(rec.get("x", 0))
        y = float(rec.get("y", 0))
        db.execute(
            """
            INSERT OR REPLACE INTO entity_status
            (entity_name, position_x, position_y, status_name, tick)
            VALUES (?, ?, ?, ?, ?)
            """,
            [name, x, y, status_name, tick],
        )

    # Freshness marker (design decision, see module docstring): reuses the
    # existing sync_state key/value table (already created by database.py
    # for 'last_sequence') rather than inventing a new one-row table.
    db.execute(
        "INSERT OR REPLACE INTO sync_state (key, value) VALUES ('entity_status_last_tick', ?)",
        [tick],
    )

    return len(entity_lines)


__all__ = [
    "aggregate_product_events",
    "apply_agent_manual_files",
    "apply_agent_manual_snapshot",
    "apply_agent_production_sample",
    "apply_power_sample",
    "apply_status_dump",
]
