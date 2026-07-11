"""Single reducer for entity/ghost snapshot ops.

These functions are the ONLY writers to `map_entity` and `ghost`. Both
transports normalize their envelopes and call them:

- ``SnapshotLoader`` — file replay (boot, rebuild-from-gap, tests)
- ``SyncService``   — live UDP during a session

Having one reducer is the single-reducer discipline from the event-sourcing
pattern this pipeline implements (JSONL ops = the log, DuckDB = the
materialized view, UDP = log shipping): transports are dumb pipes; identical
logical ops must produce identical rows regardless of which path delivered
them. Path agreement is certified by ledger L1.13
(scripts/certification/check_replay_parity.py).

PROVENANCE FOLD RULE (part of the record contract):
    Provenance fields (map_entity: agent_id, player_id, label, placed_tick;
    ghost: placed_tick, placed_by, label) change ONLY when an op carries a
    non-empty ``builder`` block. An op without one — config-change
    re-serializations, partial updates — PRESERVES the existing row's
    provenance. A present builder block is authoritative for ALL provenance
    fields; this is deliberately what lets a full re-gather stamp
    "pre-existing" (the PROV-1 soft-claim epoch: provenance completeness is
    conditional on boot epoch + no re-gather, tracked, not plumbed away).

    Corollary for any consumer of the raw JSONL: an entity's provenance is
    the FOLD of its op history under this rule, not the last line's values.

Labels are write-once by contract: set at creation, changed only by an
explicit relabel op (a builder-carrying line), destroyed with the entity.
A remove deletes the row, so a later same-key build starts clean — no
resurrection of a mined entity's label onto its replacement.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, Optional, Tuple

ENTITY_PROVENANCE_COLS = ("agent_id", "player_id", "label", "placed_tick")
GHOST_PROVENANCE_COLS = ("placed_tick", "placed_by", "label")


def _builder_block(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The op's builder block, or None. Lua serializes an empty table as {} —
    treat empty as absent (no provenance authority)."""
    builder = data.get("builder")
    if isinstance(builder, dict) and builder:
        return builder
    return None


def _existing_provenance(
    db, table: str, name_col: str, name: str, x: float, y: float, cols: Tuple[str, ...]
) -> Optional[Tuple]:
    row = db.execute(
        f"SELECT {', '.join(cols)} FROM {table} "
        f"WHERE {name_col} = ? AND position_x = ? AND position_y = ?",
        [name, x, y],
    ).fetchone()
    return row


def upsert_entity(
    db,
    entity_data: Dict[str, Any],
    chunk_x: int,
    chunk_y: int,
    default_tick: Optional[int] = None,
) -> None:
    """Insert or replace a map_entity row, folding provenance per the rule.

    Args:
        entity_data: the serialized entity (the op's ``entity`` payload)
        chunk_x/chunk_y: chunk coordinates from the op envelope
        default_tick: the op's tick — used as placed_tick ONLY when a builder
            block is present but carries no placed_tick of its own (the build
            event's tick is the placement tick). Never applied to
            builder-less ops; those preserve.
    """
    position = entity_data.get("position", {})
    pos_x = float(position.get("x", 0))
    pos_y = float(position.get("y", 0))
    entity_name = entity_data.get("name", "")
    bbox = entity_data.get("bounding_box", {})

    builder = _builder_block(entity_data)
    if builder is not None:
        agent_id = builder.get("agent_id")
        player_id = builder.get("player_id")
        label = builder.get("label")
        placed_tick = builder.get("placed_tick", default_tick)
    else:
        existing = _existing_provenance(
            db, "map_entity", "entity_name", entity_name, pos_x, pos_y,
            ENTITY_PROVENANCE_COLS)
        if existing is not None:
            agent_id, player_id, label, placed_tick = existing
        else:
            agent_id = player_id = label = placed_tick = None

    db.execute(
        """
        INSERT OR REPLACE INTO map_entity
        (entity_name, position_x, position_y, chunk_x, chunk_y,
         direction, bbox_min_x, bbox_min_y, bbox_max_x, bbox_max_y,
         agent_id, player_id, label, placed_tick, raw_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            entity_name,
            pos_x,
            pos_y,
            chunk_x,
            chunk_y,
            entity_data.get("direction"),
            bbox.get("min_x"),
            bbox.get("min_y"),
            bbox.get("max_x"),
            bbox.get("max_y"),
            agent_id,
            player_id,
            label,
            placed_tick,
            json.dumps(entity_data),
        ],
    )


def remove_entity(db, entity_name: str, pos_x: float, pos_y: float) -> int:
    """Delete a map_entity row. Returns rows removed (0 or 1)."""
    before = db.execute(
        "SELECT COUNT(*) FROM map_entity WHERE entity_name = ? AND position_x = ? AND position_y = ?",
        [entity_name, pos_x, pos_y],
    ).fetchone()[0]
    db.execute(
        "DELETE FROM map_entity WHERE entity_name = ? AND position_x = ? AND position_y = ?",
        [entity_name, pos_x, pos_y],
    )
    return int(before)


def rotate_entity(db, entity_name: str, pos_x: float, pos_y: float,
                  direction: Any) -> None:
    """Partial update: direction only. Provenance untouched by construction."""
    db.execute(
        "UPDATE map_entity SET direction = ? WHERE entity_name = ? AND position_x = ? AND position_y = ?",
        [direction, entity_name, pos_x, pos_y],
    )


def remove_resource_entity(db, name: str, pos_x: float, pos_y: float) -> int:
    """Delete a resource_entity (tree/rock) row. Returns rows removed."""
    before = db.execute(
        "SELECT COUNT(*) FROM resource_entity WHERE name = ? AND position_x = ? AND position_y = ?",
        [name, pos_x, pos_y],
    ).fetchone()[0]
    db.execute(
        "DELETE FROM resource_entity WHERE name = ? AND position_x = ? AND position_y = ?",
        [name, pos_x, pos_y],
    )
    return int(before)


def upsert_ghost(
    db,
    ghost_data: Dict[str, Any],
    default_tick: Optional[int] = None,
) -> None:
    """Insert or replace a ghost row, folding provenance per the rule.

    Ghost chunk coords are derived from position (ghost ops carry no chunk
    envelope on every path; floor(pos/32) is the canonical mapping both
    writers already used).
    """
    position = ghost_data.get("position", {})
    pos_x = float(position.get("x", 0))
    pos_y = float(position.get("y", 0))
    ghost_name = ghost_data.get("ghost_name") or ghost_data.get("name", "")
    chunk_x = math.floor(pos_x / 32)
    chunk_y = math.floor(pos_y / 32)

    builder = _builder_block(ghost_data)
    if builder is not None:
        placed_tick = builder.get("placed_tick",
                                  ghost_data.get("placed_tick", default_tick))
        label = builder.get("label", ghost_data.get("label"))
        # placed_by: no write path emits it yet (MIRAGE-4 residual, design
        # call pending) — read as-emitted so the column goes live the moment
        # the mod emits it, without a loader edit
        placed_by = builder.get("placed_by", ghost_data.get("placed_by"))
    else:
        existing = _existing_provenance(
            db, "ghost", "ghost_name", ghost_name, pos_x, pos_y,
            GHOST_PROVENANCE_COLS)
        if existing is not None:
            placed_tick, placed_by, label = existing
        else:
            placed_tick = placed_by = label = None

    db.execute(
        """
        INSERT OR REPLACE INTO ghost
        (ghost_name, position_x, position_y, chunk_x, chunk_y,
         direction, placed_tick, placed_by, label, raw_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ghost_name,
            pos_x,
            pos_y,
            chunk_x,
            chunk_y,
            ghost_data.get("direction"),
            placed_tick,
            placed_by,
            label,
            json.dumps(ghost_data),
        ],
    )


def remove_ghost(db, ghost_name: str, pos_x: float, pos_y: float) -> int:
    """Delete a ghost row. Returns rows removed."""
    before = db.execute(
        "SELECT COUNT(*) FROM ghost WHERE ghost_name = ? AND position_x = ? AND position_y = ?",
        [ghost_name, pos_x, pos_y],
    ).fetchone()[0]
    db.execute(
        "DELETE FROM ghost WHERE ghost_name = ? AND position_x = ? AND position_y = ?",
        [ghost_name, pos_x, pos_y],
    )
    return int(before)


def rotate_ghost(db, ghost_name: str, pos_x: float, pos_y: float,
                 direction: Any) -> None:
    """Partial update: direction only. Provenance untouched by construction."""
    db.execute(
        "UPDATE ghost SET direction = ? WHERE ghost_name = ? AND position_x = ? AND position_y = ?",
        [direction, ghost_name, pos_x, pos_y],
    )
