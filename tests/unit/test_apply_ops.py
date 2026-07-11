"""Unit tests for the shared op reducer (apply_ops) — the provenance fold rule.

The rule (record contract): provenance fields change ONLY via ops carrying a
non-empty builder block; builder-less ops preserve the existing row's
provenance; a present builder is authoritative for ALL provenance fields.
Live path-agreement is certified by L1.13 (check_replay_parity.py); these
tests pin the fold semantics offline.
"""

from __future__ import annotations

import pytest

from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase
from FactoryVerse.game.infra.duckdb import apply_ops


@pytest.fixture()
def db():
    d = SnapshotDatabase(db_path=None)
    d.ensure_schema()
    return d.connection


def _entity(name="iron-chest", x=10.5, y=20.5, builder=None, direction=0,
            extra=None):
    data = {
        "name": name,
        "position": {"x": x, "y": y},
        "direction": direction,
        "bounding_box": {"min_x": x - 0.4, "min_y": y - 0.4,
                         "max_x": x + 0.4, "max_y": y + 0.4},
    }
    if builder is not None:
        data["builder"] = builder
    if extra:
        data.update(extra)
    return data


def _row(db, name="iron-chest", x=10.5, y=20.5):
    return db.execute(
        "SELECT agent_id, player_id, label, placed_tick, direction FROM map_entity "
        "WHERE entity_name = ? AND position_x = ? AND position_y = ?",
        [name, x, y],
    ).fetchone()


BUILDER = {"agent_id": 3, "player_id": None, "label": "plan-a", "placed_tick": 111}


def test_builder_op_sets_provenance(db):
    apply_ops.upsert_entity(db, _entity(builder=BUILDER), 0, 0)
    assert _row(db)[:4] == (3, None, "plan-a", 111)


def test_builderless_upsert_preserves_provenance(db):
    """The PROV-2 fix: a config-change re-serialization (no builder block)
    must not squash label/agent/tick."""
    apply_ops.upsert_entity(db, _entity(builder=BUILDER), 0, 0)
    apply_ops.upsert_entity(
        db, _entity(direction=4, extra={"recipe": "iron-gear-wheel"}), 0, 0,
        default_tick=999)
    agent_id, player_id, label, placed_tick, direction = _row(db)
    assert (agent_id, label, placed_tick) == (3, "plan-a", 111)
    assert direction == "4"  # non-provenance fields updated (VARCHAR col, REPR-1)


def test_empty_builder_table_is_absent(db):
    """Lua serializes an empty table as {} — it must NOT count as authority."""
    apply_ops.upsert_entity(db, _entity(builder=BUILDER), 0, 0)
    apply_ops.upsert_entity(db, _entity(builder={}), 0, 0, default_tick=999)
    assert _row(db)[:4] == (3, None, "plan-a", 111)


def test_present_builder_is_authoritative(db):
    """A later builder-carrying op (relabel, re-gather stamp) overwrites ALL
    provenance fields — including to None (PROV-1 epoch semantics)."""
    apply_ops.upsert_entity(db, _entity(builder=BUILDER), 0, 0)
    apply_ops.upsert_entity(
        db, _entity(builder={"label": "pre-existing"}), 0, 0, default_tick=500)
    agent_id, player_id, label, placed_tick, _ = _row(db)
    assert (agent_id, label) == (None, "pre-existing")
    assert placed_tick == 500  # builder present without tick -> op tick


def test_remove_clears_no_resurrection(db):
    """Same-key re-place: a mined entity's label must not resurrect onto an
    unlabeled replacement at the same coordinates."""
    apply_ops.upsert_entity(db, _entity(builder=BUILDER), 0, 0)
    assert apply_ops.remove_entity(db, "iron-chest", 10.5, 20.5) == 1
    apply_ops.upsert_entity(db, _entity(), 0, 0, default_tick=999)
    assert _row(db)[:4] == (None, None, None, None)


def test_rotate_preserves_provenance(db):
    apply_ops.upsert_entity(db, _entity(builder=BUILDER), 0, 0)
    apply_ops.rotate_entity(db, "iron-chest", 10.5, 20.5, 8)
    agent_id, _, label, placed_tick, direction = _row(db)
    assert (agent_id, label, placed_tick) == (3, "plan-a", 111)
    assert direction == "8"


def test_builder_placed_tick_falls_back_to_op_tick(db):
    """Unified across both transports (was the L1.13 first-run divergence:
    sync used payload tick, loader wrote NULL)."""
    apply_ops.upsert_entity(
        db, _entity(builder={"agent_id": 7, "label": "x"}), 0, 0, default_tick=42)
    assert _row(db)[3] == 42


# --- ghost table ---------------------------------------------------------


def _ghost(name="transport-belt", x=5.5, y=6.5, builder=None):
    data = {"ghost_name": name, "position": {"x": x, "y": y}, "direction": 0}
    if builder is not None:
        data["builder"] = builder
    return data


def _ghost_row(db, name="transport-belt", x=5.5, y=6.5):
    return db.execute(
        "SELECT placed_tick, placed_by, label FROM ghost "
        "WHERE ghost_name = ? AND position_x = ? AND position_y = ?",
        [name, x, y],
    ).fetchone()


def test_ghost_fold_preserve_and_remove(db):
    apply_ops.upsert_ghost(db, _ghost(builder={"label": "g-plan", "placed_tick": 7}))
    assert _ghost_row(db) == (7, None, "g-plan")
    # builder-less ghost re-serialization preserves
    apply_ops.upsert_ghost(db, _ghost(), default_tick=999)
    assert _ghost_row(db) == (7, None, "g-plan")
    # rotation preserves
    apply_ops.rotate_ghost(db, "transport-belt", 5.5, 6.5, 4)
    assert _ghost_row(db) == (7, None, "g-plan")
    # remove clears; re-place starts clean
    assert apply_ops.remove_ghost(db, "transport-belt", 5.5, 6.5) == 1
    apply_ops.upsert_ghost(db, _ghost(), default_tick=999)
    assert _ghost_row(db) == (None, None, None)
