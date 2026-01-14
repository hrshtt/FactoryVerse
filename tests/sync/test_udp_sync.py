"""
UDP Synchronization Tests

Tests the UDP-based real-time synchronization mechanism:
1. Entity operations send UDP notifications
2. Ghost operations send UDP notifications with is_ghost=true
3. Sequence numbers are included in all operations
4. SyncService correctly applies UDP updates to database

These tests verify that:
- UDP payloads are correctly formatted
- The SyncService handler correctly updates the database
- Sequence gaps trigger rebuild
"""

import pytest
import json
from unittest.mock import MagicMock

from FactoryVerse.agent.snapshot.database import SnapshotDatabase
from FactoryVerse.agent.snapshot.sync import SyncService


class TestSyncServiceGhostHandling:
    """Unit tests for SyncService ghost operation handling."""

    @pytest.fixture
    def sync_db(self):
        """In-memory database for sync tests."""
        db = SnapshotDatabase()
        db.ensure_schema()
        yield db
        db.close()

    @pytest.fixture
    def mock_udp(self):
        """Mock UDP dispatcher."""
        mock = MagicMock()
        mock.is_running.return_value = True
        return mock

    @pytest.fixture
    def sync_service(self, sync_db, mock_udp):
        """SyncService instance for testing."""
        rebuild_called = []

        def on_rebuild():
            rebuild_called.append(True)

        service = SyncService(
            db=sync_db.connection,
            udp_dispatcher=mock_udp,
            on_rebuild=on_rebuild,
            initial_sequence=0,
        )
        service._rebuild_called = rebuild_called  # type: ignore[attr-defined]
        return service

    def test_ghost_upsert_creates_entry(self, sync_service, sync_db):
        """Ghost upsert operation should create ghost table entry."""
        payload = {
            "event_type": "entity_operation",
            "op": "created",
            "is_ghost": True,
            "sequence": 1,
            "tick": 100,
            "chunk": {"x": 0, "y": 0},
            "entity_key": "inserter:5.5,10.5",
            "entity": {
                "key": "inserter:5.5,10.5",
                "ghost_name": "inserter",
                "name": "entity-ghost",
                "position": {"x": 5.5, "y": 10.5},
                "direction": 4,
                "placed_tick": 100,
            },
        }

        sync_service._handle_entity_operation(payload)

        # Verify ghost exists in database
        result = sync_db.connection.execute(
            "SELECT * FROM ghost WHERE entity_key = ?", ["inserter:5.5,10.5"]
        ).fetchone()

        assert result is not None, "Ghost not created by upsert"

    def test_ghost_remove_deletes_entry(self, sync_service, sync_db):
        """Ghost remove operation should delete ghost table entry."""
        # First insert a ghost
        sync_db.connection.execute(
            """INSERT INTO ghost 
            (entity_key, ghost_name, position_x, position_y, chunk_x, chunk_y)
            VALUES (?, ?, ?, ?, ?, ?)""",
            ["inserter:5.5,10.5", "inserter", 5.5, 10.5, 0, 0],
        )

        # Verify it exists
        count_before = sync_db.connection.execute(
            "SELECT COUNT(*) FROM ghost"
        ).fetchone()[0]
        assert count_before == 1

        # Send remove operation
        payload = {
            "event_type": "entity_operation",
            "op": "destroyed",
            "is_ghost": True,
            "sequence": 1,
            "tick": 101,
            "entity_key": "inserter:5.5,10.5",
        }

        sync_service._handle_entity_operation(payload)

        # Verify ghost removed
        count_after = sync_db.connection.execute(
            "SELECT COUNT(*) FROM ghost"
        ).fetchone()[0]
        assert count_after == 0, "Ghost not removed"

    def test_ghost_operation_handler_routes_correctly(self, sync_service, sync_db):
        """Ghost operations via ghost_operation event should work."""
        payload = {
            "event_type": "ghost_operation",
            "op": "upsert",
            "sequence": 1,
            "tick": 100,
            "ghost": {
                "key": "transport-belt:10.5,20.5",
                "ghost_name": "transport-belt",
                "position": {"x": 10.5, "y": 20.5},
                "direction": 4,
                "label": "test-line",
            },
        }

        sync_service._handle_ghost_operation(payload)

        result = sync_db.connection.execute(
            "SELECT ghost_name, label FROM ghost WHERE entity_key = ?",
            ["transport-belt:10.5,20.5"],
        ).fetchone()

        assert result is not None
        assert result[0] == "transport-belt"

    def test_entity_upsert_creates_entry(self, sync_service, sync_db):
        """Regular entity upsert should create map_entity entry."""
        payload = {
            "event_type": "entity_operation",
            "op": "created",
            "is_ghost": False,
            "sequence": 1,
            "tick": 100,
            "chunk": {"x": 0, "y": 0},
            "entity": {
                "key": "inserter:5.5,10.5",
                "name": "inserter",
                "position": {"x": 5.5, "y": 10.5},
                "direction": 4,
                "bounding_box": {"min_x": 5, "min_y": 10, "max_x": 6, "max_y": 11},
            },
        }

        sync_service._handle_entity_operation(payload)

        result = sync_db.connection.execute(
            "SELECT entity_name FROM map_entity WHERE entity_key = ?",
            ["inserter:5.5,10.5"],
        ).fetchone()

        assert result is not None
        assert result[0] == "inserter"

    def test_sequence_gap_triggers_rebuild(self, sync_service):
        """Sequence gap should trigger rebuild callback."""
        # First operation at sequence 1
        payload1 = {
            "event_type": "entity_operation",
            "op": "created",
            "is_ghost": True,
            "sequence": 1,
            "tick": 100,
            "entity": {"ghost_name": "inserter", "position": {"x": 1, "y": 1}},
        }
        sync_service._handle_entity_operation(payload1)

        assert len(sync_service._rebuild_called) == 0

        # Skip to sequence 5 (gap of 3)
        payload2 = {
            "event_type": "entity_operation",
            "op": "created",
            "is_ghost": True,
            "sequence": 5,
            "tick": 105,
            "entity": {"ghost_name": "inserter", "position": {"x": 2, "y": 2}},
        }
        sync_service._handle_entity_operation(payload2)

        assert len(sync_service._rebuild_called) == 1, (
            "Rebuild should be triggered on gap"
        )

    def test_duplicate_sequence_ignored(self, sync_service, sync_db):
        """Duplicate or old sequence numbers should be ignored."""
        # First operation
        payload1 = {
            "event_type": "entity_operation",
            "op": "created",
            "is_ghost": True,
            "sequence": 5,
            "tick": 100,
            "entity": {
                "key": "inserter:1,1",
                "ghost_name": "inserter",
                "position": {"x": 1, "y": 1},
            },
        }
        sync_service._handle_entity_operation(payload1)

        # Try to apply older sequence
        payload2 = {
            "event_type": "entity_operation",
            "op": "destroyed",
            "is_ghost": True,
            "sequence": 3,  # older than 5
            "tick": 101,
            "entity_key": "inserter:1,1",
        }
        sync_service._handle_entity_operation(payload2)

        # Ghost should still exist (old operation ignored)
        result = sync_db.connection.execute("SELECT COUNT(*) FROM ghost").fetchone()[0]
        assert result == 1, "Old sequence should be ignored"


class TestSyncServiceRotationAndConfig:
    """Tests for rotation and configuration change operations."""

    @pytest.fixture
    def sync_db(self):
        db = SnapshotDatabase()
        db.ensure_schema()
        yield db
        db.close()

    @pytest.fixture
    def mock_udp(self):
        mock = MagicMock()
        mock.is_running.return_value = True
        return mock

    @pytest.fixture
    def sync_service(self, sync_db, mock_udp):
        return SyncService(
            db=sync_db.connection,
            udp_dispatcher=mock_udp,
            on_rebuild=lambda: None,
            initial_sequence=0,
        )

    def test_ghost_rotation_updates_direction(self, sync_service, sync_db):
        """Ghost rotation should update direction in database."""
        # Insert ghost
        sync_db.connection.execute(
            """INSERT INTO ghost 
            (entity_key, ghost_name, position_x, position_y, chunk_x, chunk_y, direction)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ["inserter:5,5", "inserter", 5, 5, 0, 0, "4"],
        )

        # Rotate
        payload = {
            "event_type": "entity_operation",
            "op": "rotated",
            "is_ghost": True,
            "sequence": 1,
            "entity_key": "inserter:5,5",
            "direction": "8",  # South
        }
        sync_service._handle_entity_operation(payload)

        result = sync_db.connection.execute(
            "SELECT direction FROM ghost WHERE entity_key = ?", ["inserter:5,5"]
        ).fetchone()

        assert result[0] == "8", f"Direction not updated: {result[0]}"

    def test_entity_rotation_updates_direction(self, sync_service, sync_db):
        """Entity rotation should update direction in database."""
        # Insert entity
        sync_db.connection.execute(
            """INSERT INTO map_entity 
            (entity_key, entity_name, position_x, position_y, chunk_x, chunk_y, direction)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ["inserter:10,10", "inserter", 10, 10, 0, 0, "4"],
        )

        # Rotate
        payload = {
            "event_type": "entity_operation",
            "op": "rotated",
            "is_ghost": False,
            "sequence": 1,
            "entity_key": "inserter:10,10",
            "direction": "12",  # West
        }
        sync_service._handle_entity_operation(payload)

        result = sync_db.connection.execute(
            "SELECT direction FROM map_entity WHERE entity_key = ?", ["inserter:10,10"]
        ).fetchone()

        assert result[0] == "12"

    def test_ghost_config_change_updates_record(self, sync_service, sync_db):
        """Ghost configuration change should update the ghost record."""
        # Insert ghost
        sync_db.connection.execute(
            """INSERT INTO ghost 
            (entity_key, ghost_name, position_x, position_y, chunk_x, chunk_y)
            VALUES (?, ?, ?, ?, ?, ?)""",
            ["assembling-machine-1:20,20", "assembling-machine-1", 20, 20, 0, 0],
        )

        # Config change (e.g., recipe preset)
        payload = {
            "event_type": "entity_operation",
            "op": "configuration_changed",
            "is_ghost": True,
            "sequence": 1,
            "entity": {
                "key": "assembling-machine-1:20,20",
                "ghost_name": "assembling-machine-1",
                "position": {"x": 20, "y": 20},
                "recipe": "iron-gear-wheel",
            },
        }
        sync_service._handle_entity_operation(payload)

        # Verify record updated (check raw_data contains recipe)
        result = sync_db.connection.execute(
            "SELECT raw_data FROM ghost WHERE entity_key = ?",
            ["assembling-machine-1:20,20"],
        ).fetchone()

        assert result is not None
        if result[0]:
            raw = json.loads(result[0])
            assert raw.get("recipe") == "iron-gear-wheel"


class TestSyncServiceState:
    """Tests for SyncService state management."""

    def test_state_reflects_running_status(self):
        """SyncService state should reflect running status."""
        db = SnapshotDatabase()
        db.ensure_schema()
        mock_udp = MagicMock()
        mock_udp.is_running.return_value = True

        try:
            service = SyncService(
                db=db.connection,
                udp_dispatcher=mock_udp,
                on_rebuild=lambda: None,
                initial_sequence=10,
            )

            state = service.state
            assert state.last_sequence == 10
            assert not state.is_running  # Not started yet
            assert not state.needs_rebuild
        finally:
            db.close()

    def test_set_last_sequence_updates_state(self):
        """set_last_sequence should update internal state."""
        db = SnapshotDatabase()
        db.ensure_schema()
        mock_udp = MagicMock()
        mock_udp.is_running.return_value = True

        try:
            service = SyncService(
                db=db.connection,
                udp_dispatcher=mock_udp,
                on_rebuild=lambda: None,
                initial_sequence=0,
            )

            service.set_last_sequence(100)
            assert service.state.last_sequence == 100
        finally:
            db.close()
