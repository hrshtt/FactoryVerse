from FactoryVerse.game.snapshot.adapter import SnapshotStatus


def test_snapshot_status_accepts_live_lua_field_names():
    status = SnapshotStatus.from_dict(
        {
            "system_phase": "MAINTENANCE",
            "phase": "WRITE",
            "completed_chunks": 12,
            "pending_chunks": 3,
        }
    )

    assert status.chunks_snapshotted == 12
    assert status.chunks_pending == 3
    assert status.chunks_processing == 1
    assert status.total_chunks_tracked == 15


def test_snapshot_status_marks_idle_writer_as_not_processing():
    status = SnapshotStatus.from_dict(
        {
            "system_phase": "MAINTENANCE",
            "phase": "IDLE",
            "completed_chunks": 4,
            "pending_chunks": 0,
        }
    )

    assert status.chunks_processing == 0
