"""Single reducer for the event-backed agent statistics feed.

This extends the PROV-2 single-reducer discipline to the one analytics
table that lawfully exists: ``agent_manual_production_statistics``, a
cumulative snapshot aggregated from the agent's crafting and mining
*event* files (one line per completion). Both transports call the same
function: ``SnapshotLoader`` at boot, ``SyncService`` on each file_io
notification.

What is deliberately NOT here (Constitution §10, API plan §4.6): reducers for
entity status, power samples and force production statistics. Those feeds
are polled — nothing raises an event when a machine runs short of
ingredients or a network's load changes — so they never enter the database.
They are read on demand from their files through
``remote_view.status()`` / ``.status_changed()`` / ``.power()`` /
``.production()`` (see ``game/agent/status_dump.py`` and
``game/agent/power_dump.py``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Tuple


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


__all__ = [
    "aggregate_product_events",
    "apply_agent_manual_files",
    "apply_agent_manual_snapshot",
]
