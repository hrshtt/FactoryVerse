"""A full chunk rewrite removes resource rows that lack individual events."""

import json

from FactoryVerse.game.infra.duckdb import apply_ops
from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase
from FactoryVerse.game.infra.duckdb.sync import SyncService


def test_trees_rocks_file_io_replaces_the_whole_chunk(tmp_path):
    database = SnapshotDatabase()
    database.ensure_schema()
    for x in (1.0, 2.0):
        apply_ops.upsert_resource_entity(
            database.connection,
            {"name": "tree-01", "type": "tree", "position": {"x": x, "y": 3}},
            0,
            0,
        )

    path = tmp_path / "factoryverse" / "snapshots" / "0" / "0" / "trees_rocks-init.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "name": "tree-01",
                "type": "tree",
                "position": {"x": 2.0, "y": 3.0},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    sync = SyncService(
        database.connection,
        udp_dispatcher=object(),
        on_rebuild=lambda: None,
        snapshot_dir=tmp_path,
    )
    sync._handle_file_io(
        {
            "event_type": "file_io",
            "file_type": "trees_rocks",
            "file_path": "factoryverse/snapshots/0/0/trees_rocks-init.jsonl",
            "chunk": {"x": 0, "y": 0},
        }
    )

    assert sync.flush_pending() == 1
    assert database.connection.execute(
        "SELECT position_x, position_y FROM resource_entity"
    ).fetchall() == [(2.0, 3.0)]
