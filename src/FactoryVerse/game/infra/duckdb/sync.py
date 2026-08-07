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
import queue
import threading
from pathlib import Path
from typing import Callable, Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb
    from FactoryVerse.infra.udp_dispatcher import UDPDispatcher

from FactoryVerse.game.snapshot.types import SyncState
from FactoryVerse.game.infra.duckdb import apply_ops
from FactoryVerse.game.infra.duckdb import analytics_ops

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
        snapshot_dir: Optional["Path"] = None,
    ):
        """Initialize sync service.

        Args:
            db: DuckDB connection to update
            udp_dispatcher: UDP dispatcher for subscriptions
            on_rebuild: Called when full rebuild is needed (sequence gap)
            initial_sequence: Starting sequence number (from initial load)
            db_lock: Shared lock for database access (creates new if None)
            snapshot_dir: Script-output ROOT (the same path RemoteView passes
                to SnapshotLoader, NOT the loader's normalized
                .../factoryverse/snapshots dir) — needed to resolve the
                container-relative ``file_path`` carried by power_networks/
                entity_status file_io UDP payloads (Task 4). Optional and
                None by default so existing callers that construct
                SyncService without it keep working; live sync of the
                power/status "state" tables degrades to a logged no-op
                (files simply never get resolved/applied) until a caller
                passes this in. See analytics build final report for the
                one-line change RemoteView needs to wire this end-to-end.
        """
        self._db = db
        self._udp = udp_dispatcher
        self._on_rebuild = on_rebuild
        self._last_sequence = initial_sequence
        self._running = False
        self._needs_rebuild = False
        self._snapshot_dir = Path(snapshot_dir) if snapshot_dir is not None else None

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
        # power_networks/entity_status file writes both notify under
        # event_type="file_io" (udp_payloads.file_appended), differentiated
        # by the payload's file_type field — see _handle_file_io.
        self._udp.subscribe("file_io", self._handle_file_io)

        self._running = True
        logger.info(f"SyncService started, last_sequence={self._last_sequence}")

    async def stop(self) -> None:
        """Stop listening."""
        if not self._running:
            return

        self._udp.unsubscribe("entity_operation", self._handle_entity_operation)
        self._udp.unsubscribe("ghost_operation", self._handle_ghost_operation)
        self._udp.unsubscribe("chunk_init_complete", self._handle_chunk_init)
        self._udp.unsubscribe("file_io", self._handle_file_io)

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

    def _handle_file_io(self, payload: Dict[str, Any]) -> None:
        """Handle a file_io UDP notification (Task 4).

        State and agent-statistics writes notify under
        event_type="file_io" (udp_payloads.file_appended), differentiated by
        payload["file_type"]. These are INDEPENDENT feeds from the entity-op
        sequence log by design (judgment call, per spec): they carry no
        payload data of their own to replay — the reducer re-reads the file
        at flush time — so a "gap" here just means "re-read the file", which
        analytics_ops' reducers already handle idempotently (power) or
        latest-wins (status). Routing them through _check_sequence would
        wrongly couple two unrelated sequence spaces and could trigger
        spurious full entity-rebuilds. The per-agent feeds use the same
        independent rule: flush re-reads a complete snapshot or cumulative
        event history, making replay idempotent.

        Enqueues for flush-time processing (flush_pending, called before
        every read) — the UDP thread itself never touches the DB or
        filesystem, mirroring _handle_entity_operation.
        """
        file_type = payload.get("file_type")
        if file_type not in (
            "power_networks",
            "entity_status",
            "trees_rocks",
            "agent_production_statistics",
            "agent_crafting_statistics",
            "agent_mining_statistics",
        ):
            return

        try:
            self._pending_operations.put_nowait(payload)
            logger.debug(
                f"Enqueued file_io: file_type={file_type}, "
                f"path={payload.get('file_path')}"
            )
        except queue.Full:
            logger.error(
                "Write buffer full while enqueueing file_io! Triggering rebuild."
            )
            self._needs_rebuild = True
            self._on_rebuild()

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
        pending = []
        while True:
            try:
                pending.append(self._pending_operations.get_nowait())
            except queue.Empty:
                break

        # entity_status dumps are complete latest-wins snapshots. At game
        # speed 8 they arrive faster than a read-triggered flush and the Lua
        # rolling window can delete older referenced files before Python gets
        # to them. Applying only the newest notification is equivalent state,
        # prevents stale replacement, and keeps recovery bounded to one file.
        latest_status = None
        operations = []
        def _payload_tick(value: Any) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return -1

        for payload in pending:
            if (
                payload.get("event_type") == "file_io"
                and payload.get("file_type") == "entity_status"
            ):
                if latest_status is None or _payload_tick(
                    payload.get("tick")
                ) >= _payload_tick(latest_status.get("tick")):
                    latest_status = payload
            else:
                operations.append(payload)
        if latest_status is not None:
            operations.append(latest_status)

        rebuild_required = False
        with self._db_lock:
            for payload in operations:
                try:
                    # One UDP/logical operation is the atomic unit. In
                    # particular, a map_entity mutation and all of its derived
                    # rows must become visible together or not at all.
                    self._db.execute("BEGIN TRANSACTION")
                    self._apply_operation(payload)
                    self._db.execute("COMMIT")
                except Exception as e:
                    try:
                        self._db.execute("ROLLBACK")
                    except Exception:
                        pass
                    logger.error(f"Error flushing operation: {e}", exc_info=True)
                    if (
                        payload.get("event_type") == "file_io"
                        and payload.get("file_type") == "entity_status"
                    ):
                        retries = int(payload.get("_sync_retry_count", 0))
                        if retries < 3:
                            retry = dict(payload)
                            retry["_sync_retry_count"] = retries + 1
                            self._pending_operations.put_nowait(retry)
                            logger.warning(
                                "Deferred entity_status artifact recovery "
                                "(attempt %d/3): %s",
                                retries + 1,
                                payload.get("file_path"),
                            )
                    elif payload.get("event_type") in (
                        "entity_operation",
                        "ghost_operation",
                    ):
                        # The append-only JSONL log remains authoritative. A
                        # reducer failure must not silently lose a mutation;
                        # request one rebuild after releasing the DB lock.
                        rebuild_required = True

        if rebuild_required:
            self._needs_rebuild = True
            self._on_rebuild()

        if pending:
            logger.debug(
                "Flushed %d pending notifications as %d atomic operations",
                len(pending),
                len(operations),
            )

        return len(pending)

    def _apply_operation(self, payload: Dict[str, Any]) -> None:
        """Apply a single buffered operation to database.

        MUST be called with _db_lock held.
        """
        if payload.get("event_type") == "file_io":
            self._apply_file_io(payload)
            return

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
        """Apply entity upsert to database (shared reducer — see apply_ops)."""
        entity_data = payload.get("entity", {})
        if not entity_data:
            logger.warning("Entity upsert missing entity data")
            return

        chunk = payload.get("chunk", {})
        apply_ops.upsert_entity(
            self._db, entity_data, chunk.get("x", 0), chunk.get("y", 0),
            default_tick=payload.get("tick"))
        logger.debug(f"Applied entity upsert: {entity_data.get('name', '')}")

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

        # Perform deletions (shared reducer)
        apply_ops.remove_entity(self._db, entity_name, pos_x, pos_y)
        apply_ops.remove_resource_entity(self._db, entity_name, pos_x, pos_y)
        
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

        apply_ops.upsert_ghost(self._db, ghost_data, default_tick=payload.get("tick"))
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

        apply_ops.remove_ghost(self._db, ghost_name, pos_x, pos_y)
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

        # Update only the direction field (shared reducer)
        apply_ops.rotate_entity(self._db, entity_name, pos_x, pos_y, direction)
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

        # Update only the direction field (shared reducer)
        apply_ops.rotate_ghost(self._db, ghost_name, pos_x, pos_y, direction)
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

    # =========================================================================
    # power_networks / entity_status file_io (Task 4)
    # =========================================================================

    def _resolve_file_io_path(self, file_path: str) -> Optional[Path]:
        """Map a container-relative file_io path (e.g.
        "factoryverse/snapshots/power_networks.jsonl" or
        "factoryverse/status/status-12345.jsonl") to the host-side path
        under this instance's snapshot base dir.

        Returns None if this SyncService was constructed without
        snapshot_dir — callers must treat that as "cannot apply, log and
        skip", not crash.
        """
        if self._snapshot_dir is None or not file_path:
            return None
        # snapshot_dir may be either the script-output root or the
        # "<root>/factoryverse/snapshots" dir (tier4 passes the latter via
        # get_snapshot_dir()). The mod's file_path already carries the
        # "factoryverse/..." prefix, so derive the root before joining —
        # otherwise the segment duplicates and live sync silently no-ops.
        root = self._snapshot_dir
        if root.name == "snapshots" and root.parent.name == "factoryverse":
            root = root.parent.parent
        elif root.name == "factoryverse":
            root = root.parent
        return root / str(file_path).lstrip("/")

    def _apply_file_io(self, payload: Dict[str, Any]) -> None:
        """Dispatch a buffered file_io payload to the right file reader."""
        file_type = payload.get("file_type")
        file_path = payload.get("file_path")

        path = self._resolve_file_io_path(file_path)
        if path is None:
            logger.warning(
                f"Cannot resolve file_io path (file_type={file_type}, "
                f"file_path={file_path!r}) — SyncService has no "
                "snapshot_dir; live sync of this table is a no-op until "
                "the caller passes snapshot_dir="
            )
            return

        if file_type == "power_networks":
            self._apply_power_networks_file(path)
        elif file_type == "entity_status":
            self._apply_entity_status_file(path, notified_tick=payload.get("tick"))
        elif file_type == "trees_rocks":
            self._apply_trees_rocks_file(path, payload.get("chunk") or {})
        elif file_type == "agent_production_statistics":
            self._apply_agent_production_file(path)
        elif file_type in ("agent_crafting_statistics", "agent_mining_statistics"):
            self._apply_agent_manual_files(path.parent, payload.get("agent_id"))
        else:
            logger.debug(f"Ignoring file_io of unhandled file_type={file_type}")

    def _apply_agent_production_file(self, path: Path) -> None:
        """Apply the newest complete cumulative production sample."""
        if not path.exists():
            logger.warning(f"agent production file not found for live sync: {path}")
            return
        last_line = self._read_last_nonblank_line(path)
        if not last_line:
            return
        try:
            analytics_ops.apply_agent_production_sample(self._db, json.loads(last_line))
        except Exception as exc:
            logger.error(
                f"Failed to apply live agent production sample: {exc}", exc_info=True
            )

    def _apply_trees_rocks_file(self, path: Path, chunk: Dict[str, Any]) -> None:
        """Apply an authoritative full-chunk tree/rock rewrite."""
        if not path.exists():
            logger.warning(f"trees/rocks file not found for live sync: {path}")
            return
        if chunk.get("x") is None or chunk.get("y") is None:
            logger.warning(f"trees/rocks file_io missing chunk coordinates: {path}")
            return
        try:
            resources = []
            with open(path, "r", encoding="utf-8") as handle:
                for raw in handle:
                    raw = raw.strip()
                    if raw:
                        resources.append(json.loads(raw))
            apply_ops.replace_resource_entity_chunk(
                self._db, resources, int(chunk["x"]), int(chunk["y"])
            )
        except Exception as exc:
            logger.error(
                f"Failed to apply live trees/rocks snapshot: {exc}", exc_info=True
            )

    def _apply_agent_manual_files(self, agent_dir: Path, agent_id: Any) -> None:
        """Rebuild cumulative crafting/mining counts after either append."""
        try:
            analytics_ops.apply_agent_manual_files(
                self._db,
                agent_dir,
                agent_id=int(agent_id) if agent_id is not None else None,
            )
        except Exception as exc:
            logger.error(
                f"Failed to apply live agent manual statistics: {exc}", exc_info=True
            )

    def _apply_power_networks_file(self, path: Path) -> None:
        """Read the LAST line of power_networks.jsonl and apply it.

        Heartbeats (one line per 300-tick window, ALWAYS written — even with
        zero networks) make last-line-only replay safe: any samples skipped
        between two UDP notifications are lost, but the next notification's
        last line is still a complete, self-contained, idempotent-to-apply
        state for its own tick (per C1/C4).
        """
        if not path.exists():
            logger.warning(f"power_networks file not found for live sync: {path}")
            return
        last_line = self._read_last_nonblank_line(path)
        if not last_line:
            return
        try:
            data = json.loads(last_line)
            analytics_ops.apply_power_sample(self._db, data)
            logger.debug(f"Applied live power_networks sample (tick={data.get('tick')})")
        except Exception as e:
            logger.error(f"Failed to apply live power_networks sample: {e}", exc_info=True)

    @staticmethod
    def _status_tick(path: Path) -> int:
        try:
            return int(path.stem.rsplit("-", 1)[1])
        except (IndexError, ValueError):
            return -1

    def _apply_entity_status_file(
        self, path: Path, notified_tick: Optional[int] = None
    ) -> None:
        """Read the full status dump at the notified path and apply it
        (FULL REPLACE — see analytics_ops.apply_status_dump).

        If Lua's bounded rolling window removed the exact file while the
        notification waited in Python's flush-before-read queue, recover only
        to a dump at least as new as the notification. An older dump would
        regress a latest-wins table and is therefore rejected.
        """
        if not path.exists():
            candidates = list(path.parent.glob("status-*.jsonl"))
            newest = max(candidates, key=self._status_tick) if candidates else None
            minimum_tick = (
                int(notified_tick)
                if notified_tick is not None
                else self._status_tick(path)
            )
            if newest is None or self._status_tick(newest) < minimum_tick:
                raise FileNotFoundError(
                    "entity_status artifact unavailable after bounded recovery: "
                    f"notified={path}, notified_tick={minimum_tick}, "
                    f"newest={newest}"
                )
            logger.info(
                "Recovered missing entity_status artifact %s with newer dump %s",
                path,
                newest,
            )
            path = newest
        try:
            lines = []
            with open(path, "r", encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if raw:
                        lines.append(json.loads(raw))
            if lines:
                count = analytics_ops.apply_status_dump(self._db, lines)
                logger.debug(f"Applied live entity_status dump: {count} rows")
        except Exception:
            # Let flush_pending roll back this logical operation. A malformed
            # or partially visible full dump must never wipe the prior table.
            raise

    @staticmethod
    def _read_last_nonblank_line(path: Path) -> Optional[str]:
        """Last non-blank line of a file. power_networks.jsonl is bounded
        (~12 lines/min of uptime), so a simple full read is fine — no need
        for seek-from-end tricks."""
        last = None
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    last = line
        return last


__all__ = ["SyncService"]
