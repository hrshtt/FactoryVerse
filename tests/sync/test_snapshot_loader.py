"""
Snapshot File Loading Tests

Tests the SnapshotLoader's ability to:
1. Load init files (entities-init.jsonl, ghosts-init.jsonl)
2. Replay update files (entities-updates.jsonl, ghosts-updates.jsonl)
3. Apply operations in correct sequence order
4. Handle various JSONL formats correctly
"""

import pytest
import json
import tempfile
from pathlib import Path

from FactoryVerse.agent.infra.snapshot.database import SnapshotDatabase
from FactoryVerse.agent.infra.snapshot.loader import SnapshotLoader


class TestSnapshotLoaderInit:
    """Tests for loading init files."""

    @pytest.fixture
    def temp_snapshot_dir(self):
        """Create a temporary snapshot directory structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create chunk directory structure
            chunk_dir = Path(tmpdir) / "factoryverse" / "snapshots" / "0" / "0"
            chunk_dir.mkdir(parents=True)
            yield Path(tmpdir)

    @pytest.fixture
    def db(self):
        """In-memory database."""
        database = SnapshotDatabase()
        database.ensure_schema()
        yield database
        database.close()

    def test_load_entities_init(self, temp_snapshot_dir, db):
        """Should load entities from entities-init.jsonl."""
        chunk_dir = temp_snapshot_dir / "factoryverse" / "snapshots" / "0" / "0"

        # Write entities-init.jsonl
        entities = [
            {
                "key": "inserter:5.5,10.5",
                "name": "inserter",
                "position": {"x": 5.5, "y": 10.5},
                "direction": 4,
            },
            {
                "key": "belt:6.5,10.5",
                "name": "transport-belt",
                "position": {"x": 6.5, "y": 10.5},
                "direction": 4,
            },
        ]
        with open(chunk_dir / "entities-init.jsonl", "w") as f:
            for e in entities:
                f.write(json.dumps(e) + "\n")

        loader = SnapshotLoader(db.connection, temp_snapshot_dir)
        result = loader.load_all()

        assert result.entity_count == 2

        # Verify entities in database
        count = db.connection.execute("SELECT COUNT(*) FROM map_entity").fetchone()[0]
        assert count == 2

    def test_load_ghosts_init(self, temp_snapshot_dir, db):
        """Should load ghosts from ghosts-init.jsonl."""
        chunk_dir = temp_snapshot_dir / "factoryverse" / "snapshots" / "0" / "0"

        # Write ghosts-init.jsonl
        ghosts = [
            {
                "key": "ghost:inserter:15.5,20.5",
                "ghost_name": "inserter",
                "position": {"x": 15.5, "y": 20.5},
            },
            {
                "key": "ghost:belt:16.5,20.5",
                "ghost_name": "transport-belt",
                "position": {"x": 16.5, "y": 20.5},
            },
        ]
        with open(chunk_dir / "ghosts-init.jsonl", "w") as f:
            for g in ghosts:
                f.write(json.dumps(g) + "\n")

        loader = SnapshotLoader(db.connection, temp_snapshot_dir)
        result = loader.load_all()

        assert result.ghost_count == 2

        # Verify ghosts in database
        count = db.connection.execute("SELECT COUNT(*) FROM ghost").fetchone()[0]
        assert count == 2


class TestSnapshotLoaderUpdates:
    """Tests for replaying update files."""

    @pytest.fixture
    def temp_snapshot_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            chunk_dir = Path(tmpdir) / "factoryverse" / "snapshots" / "0" / "0"
            chunk_dir.mkdir(parents=True)
            yield Path(tmpdir)

    @pytest.fixture
    def db(self):
        database = SnapshotDatabase()
        database.ensure_schema()
        yield database
        database.close()

    def test_replay_entity_upsert_operations(self, temp_snapshot_dir, db):
        """Should replay upsert operations from entities-updates.jsonl."""
        chunk_dir = temp_snapshot_dir / "factoryverse" / "snapshots" / "0" / "0"

        # Write entities-updates.jsonl
        operations = [
            {
                "op": "upsert",
                "tick": 100,
                "sequence": 1,
                "entity": {
                    "key": "inserter:5,5",
                    "name": "inserter",
                    "position": {"x": 5, "y": 5},
                },
            },
            {
                "op": "upsert",
                "tick": 101,
                "sequence": 2,
                "entity": {
                    "key": "belt:6,5",
                    "name": "transport-belt",
                    "position": {"x": 6, "y": 5},
                },
            },
        ]
        with open(chunk_dir / "entities-updates.jsonl", "w") as f:
            for op in operations:
                f.write(json.dumps(op) + "\n")

        loader = SnapshotLoader(db.connection, temp_snapshot_dir)
        last_seq = loader.replay_updates()

        assert last_seq == 2

        count = db.connection.execute("SELECT COUNT(*) FROM map_entity").fetchone()[0]
        assert count == 2

    def test_replay_entity_remove_operations(self, temp_snapshot_dir, db):
        """Should replay remove operations from entities-updates.jsonl."""
        chunk_dir = temp_snapshot_dir / "factoryverse" / "snapshots" / "0" / "0"

        # First insert an entity
        db.connection.execute(
            """INSERT INTO map_entity 
            (entity_key, entity_name, position_x, position_y, chunk_x, chunk_y)
            VALUES (?, ?, ?, ?, ?, ?)""",
            ["inserter:5,5", "inserter", 5, 5, 0, 0],
        )

        # Write remove operation
        operations = [
            {"op": "remove", "tick": 105, "sequence": 1, "key": "inserter:5,5"},
        ]
        with open(chunk_dir / "entities-updates.jsonl", "w") as f:
            for op in operations:
                f.write(json.dumps(op) + "\n")

        loader = SnapshotLoader(db.connection, temp_snapshot_dir)
        loader.replay_updates()

        count = db.connection.execute("SELECT COUNT(*) FROM map_entity").fetchone()[0]
        assert count == 0

    def test_replay_ghost_operations(self, temp_snapshot_dir, db):
        """Should replay ghost operations from ghosts-updates.jsonl."""
        chunk_dir = temp_snapshot_dir / "factoryverse" / "snapshots" / "0" / "0"

        # Write ghost operations
        operations = [
            {
                "op": "upsert",
                "tick": 100,
                "sequence": 1,
                "ghost": {
                    "key": "ghost:inserter:10,10",
                    "ghost_name": "inserter",
                    "position": {"x": 10, "y": 10},
                },
            },
            {
                "op": "upsert",
                "tick": 101,
                "sequence": 2,
                "ghost": {
                    "key": "ghost:belt:11,10",
                    "ghost_name": "transport-belt",
                    "position": {"x": 11, "y": 10},
                },
            },
            {"op": "remove", "tick": 102, "sequence": 3, "key": "ghost:inserter:10,10"},
        ]
        with open(chunk_dir / "ghosts-updates.jsonl", "w") as f:
            for op in operations:
                f.write(json.dumps(op) + "\n")

        loader = SnapshotLoader(db.connection, temp_snapshot_dir)
        last_seq = loader.replay_updates()

        assert last_seq == 3

        # Should have 1 ghost (second one, first was removed)
        count = db.connection.execute("SELECT COUNT(*) FROM ghost").fetchone()[0]
        assert count == 1

        ghost = db.connection.execute("SELECT ghost_name FROM ghost").fetchone()
        assert ghost[0] == "transport-belt"

    def test_replay_respects_sequence_order(self, temp_snapshot_dir, db):
        """Operations should be applied in sequence order, not file order."""
        chunk_dir = temp_snapshot_dir / "factoryverse" / "snapshots" / "0" / "0"

        # Write operations OUT of sequence order in file
        operations = [
            {"op": "remove", "tick": 102, "sequence": 3, "key": "inserter:5,5"},
            {
                "op": "upsert",
                "tick": 100,
                "sequence": 1,
                "entity": {
                    "key": "inserter:5,5",
                    "name": "inserter",
                    "position": {"x": 5, "y": 5},
                },
            },
            {
                "op": "upsert",
                "tick": 101,
                "sequence": 2,
                "entity": {
                    "key": "inserter:5,5",
                    "name": "inserter",
                    "position": {"x": 5, "y": 5},
                    "direction": 8,
                },
            },
        ]
        with open(chunk_dir / "entities-updates.jsonl", "w") as f:
            for op in operations:
                f.write(json.dumps(op) + "\n")

        loader = SnapshotLoader(db.connection, temp_snapshot_dir)
        loader.replay_updates()

        # Entity should NOT exist (was removed in seq 3)
        count = db.connection.execute("SELECT COUNT(*) FROM map_entity").fetchone()[0]
        assert count == 0


class TestSnapshotLoaderFromSequence:
    """Tests for partial replay from a given sequence."""

    @pytest.fixture
    def temp_snapshot_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            chunk_dir = Path(tmpdir) / "factoryverse" / "snapshots" / "0" / "0"
            chunk_dir.mkdir(parents=True)
            yield Path(tmpdir)

    @pytest.fixture
    def db(self):
        database = SnapshotDatabase()
        database.ensure_schema()
        yield database
        database.close()

    def test_replay_from_sequence(self, temp_snapshot_dir, db):
        """Should only replay operations after the given sequence."""
        chunk_dir = temp_snapshot_dir / "factoryverse" / "snapshots" / "0" / "0"

        operations = [
            {
                "op": "upsert",
                "tick": 100,
                "sequence": 1,
                "entity": {
                    "key": "inserter:1,1",
                    "name": "inserter",
                    "position": {"x": 1, "y": 1},
                },
            },
            {
                "op": "upsert",
                "tick": 101,
                "sequence": 2,
                "entity": {
                    "key": "inserter:2,2",
                    "name": "inserter",
                    "position": {"x": 2, "y": 2},
                },
            },
            {
                "op": "upsert",
                "tick": 102,
                "sequence": 3,
                "entity": {
                    "key": "inserter:3,3",
                    "name": "inserter",
                    "position": {"x": 3, "y": 3},
                },
            },
        ]
        with open(chunk_dir / "entities-updates.jsonl", "w") as f:
            for op in operations:
                f.write(json.dumps(op) + "\n")

        loader = SnapshotLoader(db.connection, temp_snapshot_dir)

        # Replay only operations after sequence 1
        last_seq = loader.replay_updates(from_sequence=1)

        assert last_seq == 3

        # Should have 2 entities (seq 2 and 3, not seq 1)
        count = db.connection.execute("SELECT COUNT(*) FROM map_entity").fetchone()[0]
        assert count == 2


class TestSnapshotLoaderEdgeCases:
    """Tests for edge cases in snapshot loading."""

    @pytest.fixture
    def db(self):
        database = SnapshotDatabase()
        database.ensure_schema()
        yield database
        database.close()

    def test_empty_directory(self, db):
        """Should handle empty snapshot directory gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = SnapshotLoader(db.connection, Path(tmpdir))
            result = loader.load_all()

            assert result.entity_count == 0
            assert result.ghost_count == 0

    def test_malformed_json_line(self, db):
        """Should skip malformed JSON lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chunk_dir = Path(tmpdir) / "factoryverse" / "snapshots" / "0" / "0"
            chunk_dir.mkdir(parents=True)

            # Write file with one valid and one invalid line
            with open(chunk_dir / "entities-init.jsonl", "w") as f:
                f.write(
                    '{"key": "valid:1,1", "name": "inserter", "position": {"x": 1, "y": 1}}\n'
                )
                f.write("not valid json\n")
                f.write(
                    '{"key": "valid:2,2", "name": "inserter", "position": {"x": 2, "y": 2}}\n'
                )

            loader = SnapshotLoader(db.connection, Path(tmpdir))
            result = loader.load_all()

            # Should load 2 entities, skip the bad line
            assert result.entity_count == 2

    def test_empty_lines_skipped(self, db):
        """Should skip empty lines in JSONL files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chunk_dir = Path(tmpdir) / "factoryverse" / "snapshots" / "0" / "0"
            chunk_dir.mkdir(parents=True)

            with open(chunk_dir / "entities-init.jsonl", "w") as f:
                f.write(
                    '{"key": "valid:1,1", "name": "inserter", "position": {"x": 1, "y": 1}}\n'
                )
                f.write("\n")
                f.write("   \n")
                f.write(
                    '{"key": "valid:2,2", "name": "inserter", "position": {"x": 2, "y": 2}}\n'
                )

            loader = SnapshotLoader(db.connection, Path(tmpdir))
            result = loader.load_all()

            assert result.entity_count == 2
