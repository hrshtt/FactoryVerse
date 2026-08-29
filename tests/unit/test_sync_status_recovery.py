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


def test_polled_file_types_are_ignored_not_enqueued(tmp_path):
    """entity_status / power_networks / agent_production_statistics are not
    tables (Constitution §10): their file_io notifications are dropped at
    the door, and flushing writes nothing."""
    database, service = _service(tmp_path)
    try:
        _write_status(tmp_path, 120, "burner-mining-drill")
        service._handle_file_io(_notification(120))
        service._handle_file_io({"event_type": "file_io", "file_type": "power_networks",
                                 "file_path": "factoryverse/snapshots/power_networks.jsonl", "tick": 120})
        service._handle_file_io({"event_type": "file_io", "file_type": "agent_production_statistics",
                                 "file_path": "factoryverse/agent-snapshots/1/production-statistics.jsonl", "agent_id": 1})
        assert service._pending_operations.qsize() == 0
        assert service.flush_pending() == 0
        names = {r[0] for r in database.connection.execute(
            "SELECT table_name FROM information_schema.tables").fetchall()}
        assert "entity_status" not in names
        # ...and the file is still there for the on-demand reader.
        from FactoryVerse.game.agent.status_dump import StatusDumpReader
        assert StatusDumpReader(tmp_path / "factoryverse" / "status").current().tick == 120
    finally:
        database.close()


def test_chunk_init_complete_advances_the_freshness_marker(tmp_path):
    """chunk_snapshot_meta.tick used to be boot-only while the schema notes told
    the agent to trust it as a freshness marker. A chunk_init_complete
    datagram now moves it."""
    database, service = _service(tmp_path)
    try:
        service._handle_chunk_init({"event_type": "chunk_init_complete", "chunk": {"x": 3, "y": -2}, "tick": 900})
        assert service.flush_pending() == 1
        assert database.connection.execute(
            "SELECT chunk_x, chunk_y, tick FROM chunk_snapshot_meta").fetchall() == [(3, -2, 900)]
        service._handle_chunk_init({"event_type": "chunk_init_complete", "chunk": {"x": 3, "y": -2}, "tick": 1500})
        service.flush_pending()
        assert database.connection.execute(
            "SELECT tick FROM chunk_snapshot_meta WHERE chunk_x = 3 AND chunk_y = -2").fetchone() == (1500,)
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
