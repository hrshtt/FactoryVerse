"""
Sync domain fixtures.

Provides fixtures for testing UDP sync, snapshot files, and DuckDB synchronization.
"""

import pytest
import json
import socket
from pathlib import Path
from typing import Generator, Any, Dict, List, Optional
from dataclasses import dataclass

from FactoryVerse.environment.config import FactoryVerseConfig
from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase
from FactoryVerse.game.infra.duckdb.loader import SnapshotLoader


@dataclass
class CapturedUDPMessage:
    """A captured UDP message for test verification."""

    event_type: str
    op: Optional[str]
    entity_key: Optional[str]
    is_ghost: bool
    sequence: int
    raw_payload: Dict[str, Any]


class UDPCapture:
    """Captures UDP messages for testing."""

    def __init__(self, port: Optional[int] = None):
        if port is None:
            from FactoryVerse.environment.config import get_config

            port = get_config().snapshot_port_base  # Use server 0 default for tests
        self.port = port
        self.messages: List[CapturedUDPMessage] = []
        self._socket: Optional[socket.socket] = None
        self._running = False

    def start(self) -> None:
        """Start capturing UDP messages."""
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", self.port))
        self._socket.settimeout(0.1)  # Non-blocking with short timeout
        self._running = True

    def stop(self) -> None:
        """Stop capturing UDP messages."""
        self._running = False
        if self._socket:
            self._socket.close()
            self._socket = None

    def poll(self, timeout: float = 0.5) -> None:
        """Poll for new messages for a specified duration."""
        import time

        start = time.time()
        while time.time() - start < timeout:
            self._receive_one()

    def _receive_one(self) -> None:
        """Attempt to receive one message."""
        if not self._socket or not self._running:
            return

        try:
            data, _ = self._socket.recvfrom(65535)
            payload = json.loads(data.decode("utf-8"))

            msg = CapturedUDPMessage(
                event_type=payload.get("event_type", ""),
                op=payload.get("op"),
                entity_key=payload.get("entity_key"),
                is_ghost=payload.get("is_ghost", False),
                sequence=payload.get("sequence", 0),
                raw_payload=payload,
            )
            self.messages.append(msg)
        except socket.timeout:
            pass
        except json.JSONDecodeError:
            pass

    def get_entity_operations(
        self, entity_key: Optional[str] = None
    ) -> List[CapturedUDPMessage]:
        """Get all entity_operation messages, optionally filtered by entity_key."""
        ops = [m for m in self.messages if m.event_type == "entity_operation"]
        if entity_key:
            ops = [m for m in ops if m.entity_key == entity_key]
        return ops

    def get_ghost_operations(self) -> List[CapturedUDPMessage]:
        """Get all ghost entity operations."""
        return [
            m
            for m in self.messages
            if m.event_type == "entity_operation" and m.is_ghost
        ]

    def get_real_entity_operations(self) -> List[CapturedUDPMessage]:
        """Get all non-ghost entity operations."""
        return [
            m
            for m in self.messages
            if m.event_type == "entity_operation" and not m.is_ghost
        ]

    def clear(self) -> None:
        """Clear all captured messages."""
        self.messages.clear()

    def find_by_op(
        self, op: str, is_ghost: Optional[bool] = None
    ) -> List[CapturedUDPMessage]:
        """Find messages by operation type."""
        matches = [m for m in self.messages if m.op == op]
        if is_ghost is not None:
            matches = [m for m in matches if m.is_ghost == is_ghost]
        return matches


@pytest.fixture(scope="function")
def snapshot_db() -> Generator[SnapshotDatabase, None, None]:
    """In-memory DuckDB for sync tests."""
    db = SnapshotDatabase()
    db.ensure_schema()
    yield db
    db.close()


@pytest.fixture(scope="function")
def udp_capture() -> Generator[UDPCapture, None, None]:
    """UDP message capture fixture.

    Note: This requires the game to be running and sending UDP to port 34400.
    For unit tests that don't use a real game, use mock_udp_messages instead.
    """
    capture = UDPCapture()
    capture.start()
    yield capture
    capture.stop()


@pytest.fixture(scope="function")
def snapshot_dir(rcon) -> Path:
    """Get the snapshot directory from the active Factorio instance.

    Note: Tests run against a Docker server which writes to
    .fv-output/output_0/factoryverse/snapshots/ per docker-compose.yml.
    """
    config = FactoryVerseConfig()
    # Docker container mounts its script-output to .fv-output/output_0
    return config.fv_output_dir / "output_0" / "factoryverse" / "snapshots"


@pytest.fixture(scope="function")
def snapshot_loader(snapshot_db, snapshot_dir) -> SnapshotLoader:
    """Snapshot loader for the current test."""
    return SnapshotLoader(snapshot_db.connection, snapshot_dir)


@dataclass
class GhostTestContext:
    """Context for ghost synchronization tests."""

    db: SnapshotDatabase
    loader: SnapshotLoader
    snapshot_dir: Path
    rcon: Any  # RconConnection
    agent: Any  # AgentInterface
    test_ground: Any  # TestGround
    admin: Any  # AdminInterface

    @property
    def agent_id(self) -> int:
        """Extract agent ID from interface name (e.g., 'agent_1' -> 1)."""
        return int(self.agent.interface_name.split("_")[1])

    def count_ghosts(self) -> int:
        """Count ghosts in the database."""
        result = self.db.connection.execute("SELECT COUNT(*) FROM ghost").fetchone()
        return result[0] if result else 0

    def count_entities(self) -> int:
        """Count entities in the database."""
        result = self.db.connection.execute(
            "SELECT COUNT(*) FROM map_entity"
        ).fetchone()
        return result[0] if result else 0

    def find_ghost(self, ghost_name: str, position: tuple) -> Optional[Dict]:
        """Find a ghost by name and position."""
        result = self.db.connection.execute(
            """
            SELECT * FROM ghost 
            WHERE ghost_name = ? AND position_x = ? AND position_y = ?
            """,
            [ghost_name, position[0], position[1]],
        ).fetchone()
        if not result:
            return None
        columns = [desc[0] for desc in self.db.connection.description]
        return dict(zip(columns, result))

    def find_entity(self, entity_name: str, position: tuple) -> Optional[Dict]:
        """Find an entity by name and position."""
        result = self.db.connection.execute(
            """
            SELECT * FROM map_entity 
            WHERE entity_name = ? AND position_x = ? AND position_y = ?
            """,
            [entity_name, position[0], position[1]],
        ).fetchone()
        if not result:
            return None
        columns = [desc[0] for desc in self.db.connection.description]
        return dict(zip(columns, result))

    def reload_from_files(self) -> int:
        """Reload all data from snapshot files."""
        self.db.reset()
        result = self.loader.load_all()
        return result.ghost_count


@pytest.fixture(scope="function")
def ghost_test_ctx(
    snapshot_db, snapshot_loader, snapshot_dir, rcon, agent, test_ground, admin
) -> GhostTestContext:
    """Complete context for ghost synchronization tests."""
    return GhostTestContext(
        db=snapshot_db,
        loader=snapshot_loader,
        snapshot_dir=snapshot_dir,
        rcon=rcon,
        agent=agent,
        test_ground=test_ground,
        admin=admin,
    )
