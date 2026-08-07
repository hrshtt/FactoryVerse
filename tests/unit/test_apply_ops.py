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


# --- MIRAGE-2 lift: electric_network_id + force round-trip ---------------


def test_entity_electric_network_id_and_force_round_trip(db):
    """apply_ops.upsert_entity must lift electric_network_id and force from
    entity_data into their map_entity columns (MIRAGE-2: the INSERT column
    list previously omitted electric_network_id though the payload carried
    it; force is a new column populated the same way)."""
    apply_ops.upsert_entity(
        db, _entity(extra={"electric_network_id": 42, "force": "player"}), 0, 0)
    row = db.execute(
        "SELECT electric_network_id, force FROM map_entity "
        "WHERE entity_name = ? AND position_x = ? AND position_y = ?",
        ["iron-chest", 10.5, 20.5],
    ).fetchone()
    assert row == (42, "player")


def test_entity_electric_network_id_and_force_absent_stay_null(db):
    """Entities with no network membership (unpowered) or no force key in
    the payload must not error and must store NULL, not crash on .get()."""
    apply_ops.upsert_entity(db, _entity(), 0, 0)
    row = db.execute(
        "SELECT electric_network_id, force FROM map_entity "
        "WHERE entity_name = ? AND position_x = ? AND position_y = ?",
        ["iron-chest", 10.5, 20.5],
    ).fetchone()
    assert row == (None, None)


@pytest.mark.parametrize(
    ("entity_type", "name", "extra", "table"),
    [
        (
            "inserter",
            "inserter",
            {
                "inserter": {
                    "pickup_position": {"x": 10.5, "y": 19.5},
                    "drop_position": {"x": 10.5, "y": 21.5},
                }
            },
            "inserter",
        ),
        (
            "transport-belt",
            "transport-belt",
            {"belt_speed": 0.03125},
            "transport_belt",
        ),
        (
            "mining-drill",
            "burner-mining-drill",
            {"mining_target": "stone"},
            "mining_drill",
        ),
        (
            "assembling-machine",
            "assembling-machine-1",
            {"crafting_speed": 0.5},
            "assembler",
        ),
    ],
)
def test_upsert_materializes_footprint_and_component(
    db, entity_type, name, extra, table
):
    payload = _entity(
        name=name,
        extra={
            "type": entity_type,
            "tile_width": 1,
            "tile_height": 1,
            "footprint_tiles": [{"x": 10, "y": 20}],
            **extra,
        },
    )
    apply_ops.upsert_entity(db, payload, 0, 0)

    assert db.execute(
        "SELECT entity_name FROM footprint_tiles WHERE tile_x=10 AND tile_y=20"
    ).fetchone() == (name,)
    if table == "transport_belt":
        assert db.execute("SELECT belt_speed FROM transport_belt").fetchone() == (
            0.03125,
        )
    if table == "mining_drill":
        assert db.execute("SELECT mining_target FROM mining_drill").fetchone() == (
            "stone",
        )
    if table == "assembler":
        assert db.execute("SELECT crafting_speed FROM assembler").fetchone() == (
            0.5,
        )
    assert db.execute(
        f"SELECT entity_name FROM {table} WHERE entity_name=? "
        "AND position_x=10.5 AND position_y=20.5",
        [name],
    ).fetchone() == (name,)


def test_upsert_replaces_stale_footprint_and_component_values(db):
    first = _entity(
        name="burner-mining-drill",
        extra={
            "type": "mining-drill",
            "footprint_tiles": [{"x": 9, "y": 20}, {"x": 10, "y": 20}],
            "mining_target": "stone",
        },
    )
    second = _entity(
        name="burner-mining-drill",
        direction=4,
        extra={
            "type": "mining-drill",
            "footprint_tiles": [{"x": 10, "y": 20}, {"x": 10, "y": 21}],
            "mining_target": "iron-ore",
        },
    )
    apply_ops.upsert_entity(db, first, 0, 0)
    apply_ops.upsert_entity(db, second, 0, 0)

    footprints = db.execute(
        "SELECT tile_x, tile_y FROM footprint_tiles "
        "WHERE entity_name='burner-mining-drill' ORDER BY tile_x, tile_y"
    ).fetchall()
    assert footprints == [(10, 20), (10, 21)]
    assert db.execute(
        "SELECT direction, mining_target FROM mining_drill"
    ).fetchone() == ("4", "iron-ore")


def test_remove_deletes_base_footprint_and_component(db):
    payload = _entity(
        name="transport-belt",
        extra={
            "type": "transport-belt",
            "footprint_tiles": [{"x": 10, "y": 20}],
        },
    )
    apply_ops.upsert_entity(db, payload, 0, 0)
    apply_ops.remove_entity(db, "transport-belt", 10.5, 20.5)

    assert db.execute("SELECT count(*) FROM map_entity").fetchone() == (0,)
    assert db.execute("SELECT count(*) FROM footprint_tiles").fetchone() == (0,)
    assert db.execute("SELECT count(*) FROM transport_belt").fetchone() == (0,)


def test_remove_base_and_derivatives_succeeds_in_one_transaction(db):
    payload = _entity(
        name="transport-belt",
        extra={
            "type": "transport-belt",
            "footprint_tiles": [{"x": 10, "y": 20}],
        },
    )
    apply_ops.upsert_entity(db, payload, 0, 0)

    db.execute("BEGIN TRANSACTION")
    apply_ops.remove_entity(db, "transport-belt", 10.5, 20.5)
    db.execute("COMMIT")

    assert db.execute("SELECT count(*) FROM map_entity").fetchone() == (0,)
    assert db.execute("SELECT count(*) FROM footprint_tiles").fetchone() == (0,)
    assert db.execute("SELECT count(*) FROM transport_belt").fetchone() == (0,)


def test_rotate_recomputes_asymmetric_footprint_and_component_direction(db):
    payload = _entity(
        name="transport-belt",
        x=10.0,
        extra={
            "type": "transport-belt",
            "tile_width": 1,
            "tile_height": 2,
            "footprint_tiles": [{"x": 10, "y": 19}, {"x": 10, "y": 20}],
        },
    )
    apply_ops.upsert_entity(db, payload, 0, 0)
    apply_ops.rotate_entity(db, "transport-belt", 10.0, 20.5, 4)

    assert db.execute(
        "SELECT tile_x, tile_y FROM footprint_tiles ORDER BY tile_x, tile_y"
    ).fetchall() == [(9, 20), (10, 20)]
    assert db.execute(
        "SELECT direction FROM transport_belt"
    ).fetchone() == ("4",)


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
