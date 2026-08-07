from __future__ import annotations

import json

from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase
from FactoryVerse.game.infra.duckdb.sync import SyncService


def _write_status(root, tick: int, name: str) -> None:
    path = root / "factoryverse" / "status" / f"status-{tick}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"meta": True, "tick": tick, "count": 1})
        + "\n"
        + json.dumps(
            {"name": name, "status": "working", "x": 1.5, "y": 2.5}
        )
        + "\n",
        encoding="utf-8",
    )


def _service(root):
    database = SnapshotDatabase()
    database.ensure_schema()
    service = SyncService(
        database.connection,
        udp_dispatcher=object(),
        on_rebuild=lambda: None,
        snapshot_dir=root,
    )
    return database, service


def _notification(tick: int) -> dict:
    return {
        "event_type": "file_io",
        "file_type": "entity_status",
        "file_path": f"factoryverse/status/status-{tick}.jsonl",
        "tick": tick,
    }


def test_status_notifications_coalesce_and_recover_to_newest_retained_dump(tmp_path):
    database, service = _service(tmp_path)
    try:
        # status-60 has already rolled out of Lua's bounded file window while
        # both notifications wait for the next read-triggered flush.
        _write_status(tmp_path, 120, "burner-mining-drill")
        service._handle_file_io(_notification(60))
        service._handle_file_io(_notification(120))

        assert service.flush_pending() == 2
        assert database.connection.execute(
            "SELECT entity_name, tick FROM entity_status"
        ).fetchall() == [("burner-mining-drill", 120)]
    finally:
        database.close()


def test_missing_status_artifact_does_not_erase_last_good_state(tmp_path):
    database, service = _service(tmp_path)
    try:
        _write_status(tmp_path, 60, "assembling-machine-1")
        service._handle_file_io(_notification(60))
        assert service.flush_pending() == 1

        # The notified 120 dump is absent and only an older dump remains.
        # Recovery must fail atomically instead of replacing truth with stale
        # or empty data.
        service._handle_file_io(_notification(120))
        assert service.flush_pending() == 1
        assert service._pending_operations.qsize() == 1
        assert database.connection.execute(
            "SELECT entity_name, tick FROM entity_status"
        ).fetchall() == [("assembling-machine-1", 60)]

        # Recovery is bounded: three deferred attempts, then the last good
        # materialization remains without a permanently poisoned queue.
        service.flush_pending()
        service.flush_pending()
        service.flush_pending()
        assert service._pending_operations.qsize() == 0
        assert database.connection.execute(
            "SELECT entity_name, tick FROM entity_status"
        ).fetchall() == [("assembling-machine-1", 60)]
    finally:
        database.close()


def test_failed_entity_reducer_requests_log_rebuild_after_releasing_lock(tmp_path):
    database, service = _service(tmp_path)
    callback_observations = []

    def rebuild():
        acquired = service._db_lock.acquire(blocking=False)
        callback_observations.append(acquired)
        if acquired:
            service._db_lock.release()

    service._on_rebuild = rebuild
    service._apply_operation = lambda payload: (_ for _ in ()).throw(
        RuntimeError("synthetic reducer failure")
    )
    service._pending_operations.put_nowait(
        {
            "event_type": "entity_operation",
            "op": "upsert",
            "sequence": 1,
            "entity": {"name": "wooden-chest"},
        }
    )
    try:
        assert service.flush_pending() == 1
        assert callback_observations == [True]
        assert service._needs_rebuild is True
    finally:
        database.close()
