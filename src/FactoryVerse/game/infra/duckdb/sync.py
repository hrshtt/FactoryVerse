"""UDP sync service for incremental updates.

Single responsibility: Subscribe to UDP, apply updates to DB.
On sequence gap, signal rebuild needed.

Design philosophy:
- Trust the mod's updates
- Apply them directly to DB
- On any confusion (sequence gap), trigger rebuild
- No complex state tracking - simple and reliable
"""

from __future__ import annotations

import json
import logging
import math
import queue
import threading
from typing import Callable, Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb
    from FactoryVerse.infra.udp_dispatcher import UDPDispatcher

from FactoryVerse.game.snapshot.types import SyncState

logger = logging.getLogger(__name__)


class SyncService:
    """Background sync via UDP.

    Responsibilities:
    - Subscribe to UDP entity/ghost operations
    - Apply operations directly to database
    - Track sequence numbers
    - Trigger rebuild when sequence gap detected

    Does NOT:
    - Manage database connection (receives it)
    - Do initial load (loader.py does that)
    - Handle queries (query.py does that)

    Important: This service processes updates regardless of system phase (bootstrap or maintenance).
    UDP payloads for updates and update files can be sent and written to disk even during
    bootstrap mode (INITIAL_SNAPSHOTTING). Phases are NOT mutually exclusive for data flow.
    """

    def __init__(
        self,
        db: "duckdb.DuckDBPyConnection",
        udp_dispatcher: "UDPDispatcher",
        on_rebuild: Callable[[], None],
        initial_sequence: int = 0,
        db_lock: Optional[threading.Lock] = None,
    ):
        """Initialize sync service.

        Args:
            db: DuckDB connection to update
            udp_dispatcher: UDP dispatcher for subscriptions
            on_rebuild: Called when full rebuild is needed (sequence gap)
            initial_sequence: Starting sequence number (from initial load)
            db_lock: Shared lock for database access (creates new if None)
        """
        self._db = db
        self._udp = udp_dispatcher
        self._on_rebuild = on_rebuild
        self._last_sequence = initial_sequence
        self._running = False
        self._needs_rebuild = False

        # Thread-safe write buffer
        self._pending_operations = queue.Queue(maxsize=10000)
        self._db_lock = db_lock if db_lock is not None else threading.Lock()
        self._sequence_lock = threading.Lock()  # Separate lock for sequence checking

    @property
    def state(self) -> SyncState:
        """Get current sync state."""
        return SyncState(
            last_sequence=self._last_sequence,
            is_running=self._running,
            needs_rebuild=self._needs_rebuild,
            pending_updates=0,
        )

    async def start(self) -> None:
        """Start listening for UDP updates."""
        if self._running:
            logger.warning("SyncService already running")
            return

        # Ensure UDP dispatcher is running
        if not self._udp.is_running():
            await self._udp.start()

        # Subscribe to events
        self._udp.subscribe("entity_operation", self._handle_entity_operation)
        self._udp.subscribe("ghost_operation", self._handle_ghost_operation)
        self._udp.subscribe("chunk_init_complete", self._handle_chunk_init)

        self._running = True
        logger.info(f"SyncService started, last_sequence={self._last_sequence}")

    async def stop(self) -> None:
        """Stop listening."""
        if not self._running:
            return

        self._udp.unsubscribe("entity_operation", self._handle_entity_operation)
        self._udp.unsubscribe("ghost_operation", self._handle_ghost_operation)
        self._udp.unsubscribe("chunk_init_complete", self._handle_chunk_init)

        self._running = False
        logger.info("SyncService stopped")

    def set_last_sequence(self, sequence: int) -> None:
        """Update last sequence (e.g., after rebuild)."""
        self._last_sequence = sequence
        self._needs_rebuild = False

    # =========================================================================
    # UDP Handlers
    # =========================================================================

    def _handle_entity_operation(self, payload: Dict[str, Any]) -> None:
        """Handle entity operation from UDP.

        Enqueues operation for later processing (flush-before-read pattern).
        UDP thread does NOT access database directly.
        """
        try:
            # Check sequence (with separate lock)
            sequence = payload.get("sequence", 0)
            if not self._check_sequence(sequence):
                return  # Rebuild triggered

            # Enqueue operation for later processing (non-blocking)
            try:
                self._pending_operations.put_nowait(payload)
                logger.debug(
                    f"Enqueued entity_operation: op={payload.get('op')}, name={payload.get('name')}, position={payload.get('position')}"
                )
            except queue.Full:
                logger.error(
                    f"Write buffer full ({self._pending_operations.maxsize} operations)! "
                    "Triggering rebuild to clear backlog."
                )
                self._needs_rebuild = True
                self._on_rebuild()

        except Exception as e:
            logger.error(f"Error enqueueing entity operation: {e}", exc_info=True)

    def _handle_ghost_operation(self, payload: Dict[str, Any]) -> None:
        """Handle ghost operation from UDP.

        Enqueues operation for later processing (flush-before-read pattern).
        """
        try:
            sequence = payload.get("sequence", 0)
            if not self._check_sequence(sequence):
                return

            # Enqueue for later processing
            try:
                self._pending_operations.put_nowait(payload)
                logger.debug(f"Enqueued ghost_operation: op={payload.get('op')}")
            except queue.Full:
                logger.error("Write buffer full! Triggering rebuild.")
                self._needs_rebuild = True
                self._on_rebuild()

        except Exception as e:
            logger.error(f"Error enqueueing ghost operation: {e}", exc_info=True)

    def _handle_chunk_init(self, payload: Dict[str, Any]) -> None:
        """Handle chunk init complete notification.

        This is informational - we don't need to do anything special,
        as the loader will pick up the files when needed.
        """
        chunk = payload.get("chunk", {})
        logger.debug(f"Chunk init complete: ({chunk.get('x')}, {chunk.get('y')})")

    # =========================================================================
    # Sequence Checking
    # =========================================================================

    def _check_sequence(self, sequence: int) -> bool:
        """Check if sequence is valid, trigger rebuild if gap detected.

        Thread-safe sequence checking with dedicated lock.

        Returns:
            True if sequence is valid and processing should continue
            False if rebuild was triggered
        """
        with self._sequence_lock:
            # First operation or sequence matches expected
            if self._last_sequence == 0 or sequence == self._last_sequence + 1:
                self._last_sequence = sequence
                return True

            # Sequence is older than what we've seen - duplicate, ignore
            if sequence <= self._last_sequence:
                logger.debug(
                    f"Ignoring old sequence {sequence} (last={self._last_sequence})"
                )
                return False

            # Gap detected - we missed some updates!
            gap_size = sequence - self._last_sequence - 1
            logger.warning(
                f"Sequence gap detected! Expected {self._last_sequence + 1}, got {sequence}. "
                f"Missing {gap_size} updates. Triggering rebuild."
            )

            self._needs_rebuild = True
            self._on_rebuild()
            return False

    # =========================================================================
    # Flush Mechanism (called before reads)
    # =========================================================================

    def flush_pending(self) -> int:
        """Flush all pending operations to database.

        This is called before every query to ensure read consistency.
        Drains the operation queue and applies all buffered writes.

        Returns:
            Number of operations flushed
        """
        queue_size = self._pending_operations.qsize()
        logger.debug(f"flush_pending() called, queue size: {queue_size}")
        operations_flushed = 0

        with self._db_lock:
            while not self._pending_operations.empty():
                try:
                    payload = self._pending_operations.get_nowait()
                    self._apply_operation(payload)
                    operations_flushed += 1
                except queue.Empty:
                    break
                except Exception as e:
                    logger.error(f"Error flushing operation: {e}", exc_info=True)
                    # Continue processing remaining operations

        if operations_flushed > 0:
            # CRITICAL: Explicitly commit to ensure changes are persisted
            # DuckDB auto-commit may not be reliable with multiple operations
            try:
                self._db.commit()
                # Force DuckDB to start a new transaction for next read
                self._db.begin()
            except Exception as e:
                logger.error(f"Error committing flush: {e}", exc_info=True)

            logger.debug(f"Flushed {operations_flushed} pending operations")

        return operations_flushed

    def _apply_operation(self, payload: Dict[str, Any]) -> None:
        """Apply a single buffered operation to database.

        MUST be called with _db_lock held.
        """
        op = payload.get("op")
        is_ghost = payload.get("is_ghost", False)

        if op == "created" or op == "upsert":
            if is_ghost:
                self._apply_ghost_upsert(payload)
            else:
                self._apply_entity_upsert(payload)
        elif op == "destroyed" or op == "remove":
            if is_ghost:
                self._apply_ghost_remove(payload)
            else:
                self._apply_entity_remove(payload)
        elif op == "rotated":
            if is_ghost:
                self._apply_ghost_rotation(payload)
            else:
                self._apply_entity_rotation(payload)
        elif op == "configuration_changed":
            if is_ghost:
                self._apply_ghost_config_change(payload)
            else:
                self._apply_entity_config_change(payload)
        else:
            logger.warning(f"Unknown operation type: {op}")

    # =========================================================================
    # Database Write Operations (called by _apply_operation)
    # =========================================================================

    def _apply_entity_upsert(self, payload: Dict[str, Any]) -> None:
        """Apply entity upsert to database."""
        entity_data = payload.get("entity", {})
        if not entity_data:
            logger.warning("Entity upsert missing entity data")
            return

        chunk = payload.get("chunk", {})
        chunk_x = chunk.get("x", 0)
        chunk_y = chunk.get("y", 0)

        position = entity_data.get("position", {})
        pos_x = float(position.get("x", 0))
        pos_y = float(position.get("y", 0))

        entity_name = entity_data.get("name", "")
        bbox = entity_data.get("bounding_box", {})

        # Extract builder metadata
        builder = entity_data.get("builder", {})
        agent_id = builder.get("agent_id") if builder else None
        player_id = builder.get("player_id") if builder else None
        label = builder.get("label") if builder else None
        placed_tick = builder.get("placed_tick") if builder else payload.get("tick")

        self._db.execute(
            """
            INSERT OR REPLACE INTO map_entity 
            (entity_name, position_x, position_y, chunk_x, chunk_y,
             direction, bbox_min_x, bbox_min_y, bbox_max_x, bbox_max_y,
             agent_id, player_id, label, placed_tick, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                entity_name,
                pos_x,
                pos_y,
                chunk_x,
                chunk_y,
                entity_data.get("direction"),
                bbox.get("min_x"),
                bbox.get("min_y"),
                bbox.get("max_x"),
                bbox.get("max_y"),
                agent_id,
                player_id,
                label,
                placed_tick,
                json.dumps(entity_data),
            ],
        )

        logger.debug(f"Applied entity upsert: ({entity_name}, {pos_x}, {pos_y})")

    def _apply_entity_remove(self, payload: Dict[str, Any]) -> None:
        """Apply entity remove to database."""
        # Extract entity name and position from payload
        entity_name = payload.get("name", "")
        position = payload.get("position", {})
        pos_x = float(position.get("x", 0))
        pos_y = float(position.get("y", 0))

        if not entity_name:
            logger.warning("Entity remove missing entity name")
            return

        # Delete from both tables since we don't know which one it's in
        # Resources (trees, rocks) are in resource_entity
        # Regular entities (furnaces, assemblers) are in map_entity
        
        # Check if entity exists before deleting (for better logging)
        map_exists = self._db.execute(
            "SELECT COUNT(*) FROM map_entity WHERE entity_name = ? AND position_x = ? AND position_y = ?",
            [entity_name, pos_x, pos_y],
        ).fetchone()[0] > 0
        
        resource_exists = self._db.execute(
            "SELECT COUNT(*) FROM resource_entity WHERE name = ? AND position_x = ? AND position_y = ?",
            [entity_name, pos_x, pos_y],
        ).fetchone()[0] > 0

        # Perform deletions
        self._db.execute(
            "DELETE FROM map_entity WHERE entity_name = ? AND position_x = ? AND position_y = ?",
            [entity_name, pos_x, pos_y],
        )
        self._db.execute(
            "DELETE FROM resource_entity WHERE name = ? AND position_x = ? AND position_y = ?",
            [entity_name, pos_x, pos_y],
        )
        
        # Log results
        if map_exists or resource_exists:
            print(f"[DELETE] Removed ({entity_name}, {pos_x}, {pos_y}) from {'map_entity' if map_exists else ''} {'resource_entity' if resource_exists else ''}")
            logger.debug(f"Applied entity remove: ({entity_name}, {pos_x}, {pos_y})")
        else:
            # Entity didn't exist - this could indicate a duplicate remove event
            print(f"[DELETE] WARNING: Attempted to delete non-existent entity ({entity_name}, {pos_x}, {pos_y})")
            logger.warning(
                f"Attempted to delete non-existent entity: {entity_name} at ({pos_x}, {pos_y}). "
                "This may indicate a duplicate remove event or stale database state."
            )

    def _apply_ghost_upsert(self, payload: Dict[str, Any]) -> None:
        """Apply ghost upsert to database."""
        # Handle payloads from both ghost_operation and entity_operation
        ghost_data = payload.get("ghost") or payload.get("entity")
        if not ghost_data:
            logger.warning("Ghost upsert missing ghost/entity data")
            return

        position = ghost_data.get("position", {})
        pos_x = float(position.get("x", 0))
        pos_y = float(position.get("y", 0))

        ghost_name = ghost_data.get("ghost_name") or ghost_data.get("name", "")

        chunk_x = math.floor(pos_x / 32)
        chunk_y = math.floor(pos_y / 32)

        self._db.execute(
            """
            INSERT OR REPLACE INTO ghost
            (ghost_name, position_x, position_y, chunk_x, chunk_y,
             direction, placed_tick, placed_by, label, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ghost_name,
                pos_x,
                pos_y,
                chunk_x,
                chunk_y,
                ghost_data.get("direction"),
                ghost_data.get("placed_tick") or payload.get("tick"),
                ghost_data.get("placed_by"),
                ghost_data.get("label"),
                json.dumps(ghost_data),
            ],
        )

        logger.debug(f"Applied ghost upsert: ({ghost_name}, {pos_x}, {pos_y})")

    def _apply_ghost_remove(self, payload: Dict[str, Any]) -> None:
        """Apply ghost remove to database."""
        ghost_name = payload.get("name", "")
        position = payload.get("position", {})
        pos_x = float(position.get("x", 0))
        pos_y = float(position.get("y", 0))

        if not ghost_name:
            logger.warning("Ghost remove missing ghost name")
            return

        self._db.execute(
            "DELETE FROM ghost WHERE ghost_name = ? AND position_x = ? AND position_y = ?",
            [ghost_name, pos_x, pos_y],
        )
        logger.debug(f"Applied ghost remove: ({ghost_name}, {pos_x}, {pos_y})")

    def _apply_entity_rotation(self, payload: Dict[str, Any]) -> None:
        """Apply entity rotation update to database."""
        entity_name = payload.get("name", "")
        position = payload.get("position", {})
        pos_x = float(position.get("x", 0))
        pos_y = float(position.get("y", 0))

        if not entity_name:
            logger.warning("Entity rotation missing entity name")
            return

        direction = payload.get("direction")

        # Update only the direction field
        self._db.execute(
            "UPDATE map_entity SET direction = ? WHERE entity_name = ? AND position_x = ? AND position_y = ?",
            [direction, entity_name, pos_x, pos_y],
        )
        logger.debug(
            f"Applied entity rotation: ({entity_name}, {pos_x}, {pos_y}) -> direction={direction}"
        )

    def _apply_ghost_rotation(self, payload: Dict[str, Any]) -> None:
        """Apply ghost rotation update to database."""
        ghost_name = payload.get("name", "")
        position = payload.get("position", {})
        pos_x = float(position.get("x", 0))
        pos_y = float(position.get("y", 0))

        if not ghost_name:
            logger.warning("Ghost rotation missing ghost name")
            return

        direction = payload.get("direction")

        # Update only the direction field
        self._db.execute(
            "UPDATE ghost SET direction = ? WHERE ghost_name = ? AND position_x = ? AND position_y = ?",
            [direction, ghost_name, pos_x, pos_y],
        )
        logger.debug(
            f"Applied ghost rotation: ({ghost_name}, {pos_x}, {pos_y}) -> direction={direction}"
        )

    def _apply_entity_config_change(self, payload: Dict[str, Any]) -> None:
        """Apply entity configuration change to database.

        Configuration changes include recipe changes, filter changes, etc.
        We upsert the entire entity data since configuration may affect multiple fields.
        """
        entity_data = payload.get("entity", {})
        if not entity_data:
            logger.warning("Entity config change missing entity data")
            return

        # Re-use entity upsert since config change sends full entity data
        self._apply_entity_upsert(payload)
        logger.debug(f"Applied entity config change: {entity_data.get('key')}")

    def _apply_ghost_config_change(self, payload: Dict[str, Any]) -> None:
        """Apply ghost configuration change to database.

        Configuration changes for ghosts (e.g., recipe presets on ghost assemblers).
        We upsert the entire ghost data since configuration may affect multiple fields.
        """
        ghost_data = payload.get("entity") or payload.get("ghost", {})
        if not ghost_data:
            logger.warning("Ghost config change missing ghost data")
            return

        # Re-use ghost upsert since config change sends full ghost data
        self._apply_ghost_upsert(payload)
        logger.debug(f"Applied ghost config change: {ghost_data.get('key')}")


__all__ = ["SyncService"]
