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

# Fresh init state: pipe with the CORRECT neighbours (boiler + pipe)
PIPE_INIT = {
    "name": "pipe",
    "type": "pipe",
    "position": {"x": 109.5, "y": 67.5},
    "direction": 0,
    "pipe_data": {
        "pipe_neighbours": {
            "inputs": [
                {"name": "boiler", "position": {"x": 110, "y": 65.5}},
                {"name": "pipe", "position": {"x": 109.5, "y": 68.5}},
            ],
            "outputs": [],
        }
    },
}

# Stale build-tick upsert: predates the init snapshot, lists only [pipe]
STALE_UPDATE = {
    "op": "upsert",
    "tick": 64881,
    "sequence": 606,
    "entity": {
        "name": "pipe",
        "type": "pipe",
        "position": {"x": 109.5, "y": 67.5},
        "direction": 0,
        "pipe_data": {
            "pipe_neighbours": {
                "inputs": [{"name": "pipe", "position": {"x": 109.5, "y": 68.5}}],
                "outputs": [],
            }
        },
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
        """The exact L2.2 failure: stale pipe_neighbours must NOT win."""
        con, _ = loaded_db
        (raw,) = con.execute(
            "SELECT raw_data FROM map_entity WHERE entity_name = 'pipe'"
        ).fetchone()
        inputs = json.loads(raw)["pipe_data"]["pipe_neighbours"]["inputs"]
        names = sorted(n["name"] for n in inputs)
        assert names == ["boiler", "pipe"], (
            "stale build-tick update overwrote the fresher init snapshot"
        )

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
            inputs = json.loads(raw)["pipe_data"]["pipe_neighbours"]["inputs"]
            # No init tick to order against -> the update record applied
            assert [n["name"] for n in inputs] == ["pipe"]
        finally:
            db.close()
