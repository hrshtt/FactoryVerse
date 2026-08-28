"""Offline test: replay_updates must not apply update records that predate
their chunk's init snapshot tick (SNAP-5 / L2.2 stale-pipe_neighbours finding,
2026-06-11).

Field failure being pinned: a pipe's build-tick update record (sequence 606,
tick 64881, listing only [pipe] as neighbours) was replayed OVER the fresher
re_snapshot init state (tick ~78k, correctly listing [boiler, pipe]) —
the DB then reported stale connectivity. Evidence:
.fv-output/certification/2026-06-11/L2.2/13_layer4_db.json + 16_diff_table.md.

No Factorio needed: writes a synthetic snapshot dir (chunk_meta line + init
line + updates file) and loads it with the real SnapshotDatabase/SnapshotLoader.
"""

import json

import pytest

from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase
from FactoryVerse.game.infra.duckdb.loader import SnapshotLoader


INIT_TICK = 78000

# Fresh init state: the pipe as serialized AFTER the init snapshot. The
# discriminator is a field the stale record lacks. (Until 2026-08-29 this fixture
# used `pipe_neighbours.inputs == [boiler, pipe]`, whose expected value was itself
# the serializer's dx>0 fabrication — TRANSPORT §8.1. The serializer now emits
# engine ports; the fixture just needs two distinguishable payloads.)
PIPE_INIT = {
    "name": "pipe",
    "type": "pipe",
    "position": {"x": 109.5, "y": 67.5},
    "direction": 0,
    "pipe_data": {
        "ports": [
            {"fluidbox_index": 1, "index": 1, "position": {"x": 109.5, "y": 67.5},
             "target_position": {"x": 109.5, "y": 66.5}, "flow_direction": "input-output",
             "connection_type": "normal"},
            {"fluidbox_index": 1, "index": 2, "position": {"x": 109.5, "y": 67.5},
             "target_position": {"x": 109.5, "y": 68.5}, "flow_direction": "input-output",
             "connection_type": "normal"},
        ]
    },
    "snapshot_origin": "init",
}

# Stale build-tick upsert: predates the init snapshot
STALE_UPDATE = {
    "op": "upsert",
    "tick": 64881,
    "sequence": 606,
    "entity": {
        "name": "pipe",
        "type": "pipe",
        "position": {"x": 109.5, "y": 67.5},
        "direction": 0,
        "pipe_data": {"ports": None},
        "snapshot_origin": "stale-build-tick",
    },
}

# Fresh upsert: newer than the init snapshot, must apply
FRESH_UPDATE = {
    "op": "upsert",
    "tick": 80000,
    "sequence": 700,
    "entity": {
        "name": "wooden-chest",
        "type": "container",
        "position": {"x": 100.5, "y": 70.5},
        "direction": 0,
    },
}

# Legacy record without tick metadata: current behavior preserved (applied)
TICKLESS_UPDATE = {
    "op": "upsert",
    "sequence": 800,
    "entity": {
        "name": "iron-chest",
        "type": "container",
        "position": {"x": 101.5, "y": 70.5},
        "direction": 0,
    },
}


@pytest.fixture
def snapshot_dir(tmp_path):
    """Synthetic chunk (3,2) — positions above fall in chunk x=3, y=2."""
    chunk_dir = tmp_path / "3" / "2"
    chunk_dir.mkdir(parents=True)

    meta = {"kind": "chunk_meta", "chunk_x": 3, "chunk_y": 2, "tick": INIT_TICK}
    (chunk_dir / "entities-init.jsonl").write_text(
        json.dumps(meta) + "\n" + json.dumps(PIPE_INIT) + "\n"
    )
    (chunk_dir / "entities-updates.jsonl").write_text(
        "\n".join(
            json.dumps(rec) for rec in (STALE_UPDATE, FRESH_UPDATE, TICKLESS_UPDATE)
        )
        + "\n"
    )
    return tmp_path


@pytest.fixture
def loaded_db(snapshot_dir):
    db = SnapshotDatabase()  # in-memory
    db.ensure_schema()
    loader = SnapshotLoader(db.connection, snapshot_dir)
    result = loader.load_all()
    yield db.connection, result
    db.close()


class TestStaleUpdateReplay:
    def test_init_state_loaded(self, loaded_db):
        con, result = loaded_db
        assert result.entity_count == 1  # non-vacuous: the init line did load
        rows = con.execute(
            "SELECT raw_data FROM map_entity WHERE entity_name = 'pipe'"
        ).fetchall()
        assert len(rows) == 1

    def test_stale_update_not_replayed_over_fresher_init(self, loaded_db):
        """The exact L2.2 failure: a stale build-tick update must NOT win."""
        con, _ = loaded_db
        (raw,) = con.execute(
            "SELECT raw_data FROM map_entity WHERE entity_name = 'pipe'"
        ).fetchone()
        data = json.loads(raw)
        assert data["snapshot_origin"] == "init", (
            "stale build-tick update overwrote the fresher init snapshot"
        )
        assert len(data["pipe_data"]["ports"]) == 2

    def test_newer_than_init_update_applies(self, loaded_db):
        con, result = loaded_db
        rows = con.execute(
            "SELECT entity_name FROM map_entity WHERE entity_name = 'wooden-chest'"
        ).fetchall()
        assert len(rows) == 1
        assert result.last_sequence == 800  # both non-stale ops replayed

    def test_tickless_update_keeps_current_behavior(self, loaded_db):
        con, _ = loaded_db
        rows = con.execute(
            "SELECT entity_name FROM map_entity WHERE entity_name = 'iron-chest'"
        ).fetchall()
        assert len(rows) == 1

    def test_chunk_meta_recorded(self, loaded_db):
        """The filter's ground truth must actually be in-DB."""
        con, _ = loaded_db
        (tick,) = con.execute(
            "SELECT tick FROM chunk_snapshot_meta WHERE chunk_x = 3 AND chunk_y = 2"
        ).fetchone()
        assert tick == INIT_TICK


class TestNoMetaFallback:
    def test_without_chunk_meta_all_updates_apply(self, tmp_path):
        """Chunks without a meta line keep the old replay-everything behavior."""
        chunk_dir = tmp_path / "3" / "2"
        chunk_dir.mkdir(parents=True)
        (chunk_dir / "entities-init.jsonl").write_text(json.dumps(PIPE_INIT) + "\n")
        (chunk_dir / "entities-updates.jsonl").write_text(
            json.dumps(STALE_UPDATE) + "\n"
        )

        db = SnapshotDatabase()
        db.ensure_schema()
        try:
            SnapshotLoader(db.connection, tmp_path).load_all()
            (raw,) = db.connection.execute(
                "SELECT raw_data FROM map_entity WHERE entity_name = 'pipe'"
            ).fetchone()
            # No init tick to order against -> the update record applied
            assert json.loads(raw)["snapshot_origin"] == "stale-build-tick"
        finally:
            db.close()


# =============================================================================
# CELL-2a: future-tick guard — previous-boot files are "from the future"
# =============================================================================
#
# Field failure class being pinned (CELL-1/CELL-2, 2026-06-11): the snapshot
# dir persists across boots, so a fresh boot (low game tick) can inherit a
# previous boot's files whose chunk_meta/record ticks are HIGHER than the
# running game's tick — "from the future". Such records can never be
# superseded by tick-ordering and resurrect destroyed rigs (the eval session
# replayed cell_10's 4 destroyed probe chests this way).
# loader.load_all/replay_updates(current_game_tick=...) must SKIP them.

CURRENT_TICK = 20000  # the running game's tick at load time

# Init file from THIS boot (tick < current): must load
FRESH_BOOT_CHEST = {
    "name": "steel-chest",
    "type": "container",
    "position": {"x": 109.5, "y": 67.5},  # chunk (3, 2)
    "direction": 0,
}

# Init file from a PREVIOUS boot (tick > current): must be skipped
PHANTOM_CHEST = {
    "name": "wooden-chest",
    "type": "container",
    "position": {"x": 141.5, "y": 67.5},  # chunk (4, 2)
    "direction": 0,
}

# Update record from a previous boot (tick > current): must be skipped
FUTURE_UPDATE = {
    "op": "upsert",
    "tick": 1500000,
    "sequence": 5,
    "entity": {
        "name": "burner-inserter",
        "type": "inserter",
        "position": {"x": 110.5, "y": 67.5},
        "direction": 0,
    },
}


def _write_chunk(tmp_path, chunk_x, chunk_y, tick, entity):
    chunk_dir = tmp_path / str(chunk_x) / str(chunk_y)
    chunk_dir.mkdir(parents=True, exist_ok=True)
    meta = {"kind": "chunk_meta", "chunk_x": chunk_x, "chunk_y": chunk_y, "tick": tick}
    (chunk_dir / "entities-init.jsonl").write_text(
        json.dumps(meta) + "\n" + json.dumps(entity) + "\n"
    )
    return chunk_dir


@pytest.fixture
def mixed_boot_snapshot_dir(tmp_path):
    """Two chunks: (3,2) from this boot, (4,2) from a previous boot."""
    chunk_dir = _write_chunk(tmp_path, 3, 2, tick=15000, entity=FRESH_BOOT_CHEST)
    _write_chunk(tmp_path, 4, 2, tick=1500000, entity=PHANTOM_CHEST)
    # Previous-boot update record alongside this boot's chunk
    (chunk_dir / "entities-updates.jsonl").write_text(
        json.dumps(FUTURE_UPDATE) + "\n"
    )
    return tmp_path


def _load(snapshot_dir, current_game_tick):
    db = SnapshotDatabase()
    db.ensure_schema()
    loader = SnapshotLoader(db.connection, snapshot_dir)
    result = loader.load_all(current_game_tick=current_game_tick)
    return db, result


class TestFutureTickGuard:
    def test_future_tick_chunk_skipped(self, mixed_boot_snapshot_dir):
        """Init file with chunk_meta tick > game tick must NOT load."""
        db, _ = _load(mixed_boot_snapshot_dir, current_game_tick=CURRENT_TICK)
        try:
            rows = db.connection.execute(
                "SELECT entity_name FROM map_entity WHERE entity_name = 'wooden-chest'"
            ).fetchall()
            assert rows == [], "previous-boot phantom chest loaded as live data"
            # Its chunk_meta must not be recorded either
            meta = db.connection.execute(
                "SELECT tick FROM chunk_snapshot_meta WHERE chunk_x = 4 AND chunk_y = 2"
            ).fetchall()
            assert meta == []
        finally:
            db.close()

    def test_normal_chunk_loads_with_guard_on(self, mixed_boot_snapshot_dir):
        """This boot's chunk (tick <= game tick) loads normally."""
        db, _ = _load(mixed_boot_snapshot_dir, current_game_tick=CURRENT_TICK)
        try:
            rows = db.connection.execute(
                "SELECT entity_name FROM map_entity WHERE entity_name = 'steel-chest'"
            ).fetchall()
            assert len(rows) == 1
            (tick,) = db.connection.execute(
                "SELECT tick FROM chunk_snapshot_meta WHERE chunk_x = 3 AND chunk_y = 2"
            ).fetchone()
            assert tick == 15000
        finally:
            db.close()

    def test_future_update_record_skipped(self, mixed_boot_snapshot_dir):
        """replay_updates drops records with tick > game tick (the
        resurrected-destroyed-chests mechanism of the CELL-1 field run)."""
        db, _ = _load(mixed_boot_snapshot_dir, current_game_tick=CURRENT_TICK)
        try:
            rows = db.connection.execute(
                "SELECT entity_name FROM map_entity WHERE entity_name = 'burner-inserter'"
            ).fetchall()
            assert rows == [], "previous-boot update record was replayed"
        finally:
            db.close()

    def test_none_keeps_old_behavior(self, mixed_boot_snapshot_dir):
        """current_game_tick=None loads everything (old behavior)."""
        db, _ = _load(mixed_boot_snapshot_dir, current_game_tick=None)
        try:
            names = {
                r[0]
                for r in db.connection.execute(
                    "SELECT entity_name FROM map_entity"
                ).fetchall()
            }
            assert {"steel-chest", "wooden-chest", "burner-inserter"} <= names
        finally:
            db.close()

    def test_equal_tick_is_not_future(self, tmp_path):
        """tick == current game tick is this boot's freshest data: loads."""
        _write_chunk(tmp_path, 3, 2, tick=CURRENT_TICK, entity=FRESH_BOOT_CHEST)
        db, _ = _load(tmp_path, current_game_tick=CURRENT_TICK)
        try:
            rows = db.connection.execute(
                "SELECT entity_name FROM map_entity WHERE entity_name = 'steel-chest'"
            ).fetchall()
            assert len(rows) == 1
        finally:
            db.close()
