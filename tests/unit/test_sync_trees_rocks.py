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


def test_exact_destroy_records_tick_indexed_duckdb_removal():
    database = SnapshotDatabase()
    database.ensure_schema()
    apply_ops.upsert_resource_entity(
        database.connection,
        {"name": "tree-07", "type": "tree", "position": {"x": -9.25, "y": 47}},
        -1,
        1,
    )
    sync = SyncService(
        database.connection,
        udp_dispatcher=object(),
        on_rebuild=lambda: None,
    )

    sync._apply_entity_remove(
        {
            "event_type": "entity_operation",
            "op": "destroyed",
            "name": "tree-07",
            "position": {"x": -9.25, "y": 47},
            "tick": 3914,
            "sequence": 7,
        }
    )

    assert sync.get_applied_resource_removal("tree-07", -9.25, 47) == {
        "snapshot_destroy_event_tick": 3914,
        "duckdb_delete_tick": 3914,
        "destroy_event_sequence": 7,
        "destroy_action_id": None,
        "remove_payload_rows_removed": 1,
        "resource_row_existed_at_remove_apply": True,
    }


def test_resource_reappearance_invalidates_cached_removal(tmp_path):
    database = SnapshotDatabase()
    database.ensure_schema()
    sync = SyncService(
        database.connection,
        udp_dispatcher=object(),
        on_rebuild=lambda: None,
        snapshot_dir=tmp_path,
    )
    key = ("tree-07", -9.25, 47.0)
    sync._applied_resource_removals[key] = {"snapshot_destroy_event_tick": 10}

    sync._apply_entity_upsert(
        {
            "entity": {
                "name": "tree-07",
                "type": "tree",
                "position": {"x": -9.25, "y": 47},
            },
            "chunk": {"x": -1, "y": 1},
        }
    )
    assert sync.get_applied_resource_removal(*key) is None

    sync._applied_resource_removals[key] = {"snapshot_destroy_event_tick": 11}
    path = tmp_path / "trees.jsonl"
    path.write_text(
        json.dumps(
            {
                "name": "tree-07",
                "type": "tree",
                "position": {"x": -9.25, "y": 47},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    sync._apply_trees_rocks_file(path, {"x": -1, "y": 1})
    assert sync.get_applied_resource_removal(*key) is None
