"""RemoteView - Facade for map-wide entity queries.

Composes database, loader, sync, and query modules into a single interface.
This is the main entry point for agents to query map data.

Usage:
    view = RemoteView(snapshot_dir, rcon_client=rcon, udp_dispatcher=dispatcher)
    await view.load()  # Waits for bootstrap to complete by default
    await view.start()  # Begin sync

    # Query entities
    entities = view.get_entities("SELECT * FROM map_entity LIMIT 10")

    # Query ghosts
    ghosts = view.get_ghosts("SELECT * FROM ghost WHERE ghost_name = 'inserter'")
"""

from __future__ import annotations

import logging
import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Optional, List, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from FactoryVerse.infra.udp_dispatcher import UDPDispatcher
    from FactoryVerse.factory.resource.base import BaseResource
    from FactoryVerse.factory.entity.base_entity import BaseEntity
    from FactoryVerse.agent.embodied_actions.walking import MovementAction
    from FactoryVerse.agent.embodied_actions.entity_operations import EntityOperationsAction
    from FactoryVerse.agent.embodied_actions.place_entity import PlacementAction
    from FactoryVerse.agent.embodied_actions.mining import MiningAction
    from factorio_rcon import RCONClient

from FactoryVerse.agent.infra.snapshot.database import SnapshotDatabase
from FactoryVerse.agent.infra.snapshot.loader import SnapshotLoader
from FactoryVerse.agent.infra.snapshot.sync import SyncService
from FactoryVerse.agent.infra.snapshot.query import QueryExecutor
from FactoryVerse.agent.infra.snapshot.types import LoadResult, SyncState
from FactoryVerse.infra.udp_dispatcher import get_udp_dispatcher

logger = logging.getLogger(__name__)


class RemoteView:
    """DuckDB-backed map queries with implicit sync.

    RemoteView provides read-only access to entities across the entire map.
    Data is loaded from snapshot files and kept in sync via UDP.

    Architecture:
    - SnapshotDatabase: Manages DuckDB connection and schema
    - SnapshotLoader: Reads JSONL files into database
    - SyncService: Applies UDP updates in real-time
    - QueryExecutor: Validates and executes SQL queries

    This class is a thin facade that composes these components.

    Example:
        >>> view = RemoteView(snapshot_dir, rcon_client=rcon)
        >>> await view.load()  # Waits for bootstrap by default
        >>> await view.start()
        >>> drills = view.get_entities('''
        ...     SELECT * FROM map_entity
        ...     WHERE entity_name = 'burner-mining-drill'
        ... ''')
    """

    def __init__(
        self,
        snapshot_dir: Path,
        entity_ops: "EntityOperationsAction",
        place_ops: "PlacementAction",
        walking_action: "MovementAction",
        mining_action: "MiningAction",
        db_path: Optional[Path] = None,
        udp_dispatcher: Optional["UDPDispatcher"] = None,
        rcon_client: Optional["RCONClient"] = None,
    ):
        """Initialize RemoteView.

        Args:
            snapshot_dir: Path to snapshot directory (or script-output root)
            entity_ops: Entity operations action for inspection
            place_ops: Placement action for ghost operations
            walking_action: Movement action for navigation
            mining_action: Mining action (required for resources)
            db_path: Path for persistent DB. None = in-memory (default).
            udp_dispatcher: UDP dispatcher for real-time sync. None = no sync.
            rcon_client: RCON client for polling snapshot status. Required for bootstrap waiting.
        """
        self._snapshot_dir = Path(snapshot_dir)
        self._udp_dispatcher = udp_dispatcher
        self._rcon_client = rcon_client
        self._entity_ops = entity_ops
        self._place_ops = place_ops
        self._walking_action = walking_action
        self._mining_action = mining_action

        # Remote interface adapter for snapshot status polling
        self._map_api = None
        if rcon_client is not None:
            from FactoryVerse.infra.remote_adapters import MapSnapshotInterface
            self._map_api = MapSnapshotInterface(rcon_client)

        # Core components
        self._database = SnapshotDatabase(db_path)

        # Thread-safe coordination
        self._db_lock = threading.Lock()

        # Lazy-initialized components (after load())
        self._loader: Optional[SnapshotLoader] = None
        self._sync: Optional[SyncService] = None
        self._query: Optional[QueryExecutor] = None

        # State
        self._loaded = False
        self._last_sequence = 0

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def load(
        self, wait_for_bootstrap: bool = True, bootstrap_timeout: float = 120.0
    ) -> LoadResult:
        """Load snapshot files into database.

        If wait_for_bootstrap=True and rcon_client is provided, waits for the snapshot
        system to transition from INITIAL_SNAPSHOTTING to MAINTENANCE mode before loading.
        This ensures all bootstrap data is available.

        Must be called before querying. Can be called again to reload.

        Args:
            wait_for_bootstrap: If True, wait for bootstrap to complete before loading
            bootstrap_timeout: Maximum time to wait for bootstrap (seconds)

        Returns:
            LoadResult with counts and last sequence number
        """
        # Wait for bootstrap completion if requested
        if wait_for_bootstrap and self._rcon_client:
            await self._wait_for_bootstrap_complete(timeout=bootstrap_timeout)

        # Ensure schema exists
        self._database.ensure_schema()

        # Create sync service FIRST (before QueryExecutor needs it)
        # This allows QueryExecutor to reference it for flush-before-read
        if self._udp_dispatcher is not None:
            self._sync = SyncService(
                db=self._database.connection,
                udp_dispatcher=self._udp_dispatcher,
                on_rebuild=self._handle_rebuild_needed,
                initial_sequence=0,  # Will be updated after load
                db_lock=self._db_lock,
            )
        else:
            self._sync = None

        # Initialize components
        self._loader = SnapshotLoader(
            self._database.connection,
            self._snapshot_dir,
        )
        
        # Status directory is at snapshot_dir/factoryverse/status
        status_dir = self._snapshot_dir / "factoryverse" / "status"
        
        self._query = QueryExecutor(
            self._database.connection,
            entity_ops=self._entity_ops,
            place_ops=self._place_ops,
            walking_action=self._walking_action,
            mining_action=self._mining_action,
            sync_service=self._sync,
            db_lock=self._db_lock,
            status_dir=status_dir,
        )

        # Load data (with lock to prevent concurrent access)
        logger.info("Loading snapshot data from disk...")
        with self._db_lock:
            result = self._loader.load_all()

        self._last_sequence = result.last_sequence
        self._database.set_last_sequence(result.last_sequence)

        # Update sync service's sequence if it exists
        if self._sync:
            self._sync.set_last_sequence(result.last_sequence)

        self._loaded = True
        logger.info(f"RemoteView loaded: {result}")
        return result

    def rebuild(self) -> LoadResult:
        """Clear and reload from files.

        Called when sync detects a sequence gap.
        Does NOT wait for bootstrap (assumes we're already in maintenance mode).
        This is synchronous because it's called from sync service callbacks.
        """
        logger.info("RemoteView rebuild triggered")

        with self._db_lock:
            self._database.reset()
            # Use synchronous load path (no bootstrap wait needed for rebuilds)
            self._database.ensure_schema()

            # Re-initialize loader if needed
            if self._loader is None:
                self._loader = SnapshotLoader(
                    self._database.connection,
                    self._snapshot_dir,
                )
            
            # Re-initialize query executor if needed (with status_dir)
            if self._query is None:
                status_dir = self._snapshot_dir / "factoryverse" / "status"
                self._query = QueryExecutor(
                    self._database.connection,
                    entity_ops=self._entity_ops,
                    place_ops=self._place_ops,
                    walking_action=self._walking_action,
                    mining_action=self._mining_action,
                    sync_service=self._sync,
                    db_lock=self._db_lock,
                    status_dir=status_dir,
                )

            # Load data synchronously (already holding lock)
            result = self._loader.load_all()
            self._last_sequence = result.last_sequence
            self._database.set_last_sequence(result.last_sequence)

        logger.info(f"RemoteView rebuilt: {result}")
        return result

    async def start(self) -> None:
        """Start background sync.

        Must call load() first to establish initial state.
        """
        if not self._loaded:
            raise RuntimeError("Must call load() before start()")

        if self._udp_dispatcher is None:
            logger.info("No UDP dispatcher - sync disabled")
            return

        if self._sync is None:
            logger.warning(
                "Sync service not initialized (should have been created in load())"
            )
            return

        # Start listening for UDP updates
        await self._sync.start()

    async def stop(self) -> None:
        """Stop sync and close resources."""
        if self._sync:
            await self._sync.stop()
            self._sync = None

        self._database.close()

    def _handle_rebuild_needed(self) -> None:
        """Callback when sync detects sequence gap."""
        result = self.rebuild()
        if self._sync:
            self._sync.set_last_sequence(result.last_sequence)

    # =========================================================================
    # Query API
    # =========================================================================

    def query(self, sql: str) -> List[Dict[str, Any]]:
        """Execute raw SQL query, return list of dicts.

        Query must be SELECT (read-only). Use for custom queries
        not covered by get_entities/get_ghosts.

        Args:
            sql: SQL query (must be SELECT)

        Returns:
            List of row dictionaries

        Example:
            >>> results = view.query('''
            ...     SELECT entity_name, COUNT(*) as count
            ...     FROM map_entity
            ...     GROUP BY entity_name
            ...     ORDER BY count DESC
            ... ''')
        """
        self._ensure_query_ready()
        return self._query.query(sql)

    def get_entities(self, sql: str) -> List["BaseEntity"]:
        """Execute SQL, return entity instances with REMOTE view.

        Query should select from map_entity table (or joins with it).
        Each row is converted to a BaseEntity with REMOTE view (read-only).

        Args:
            sql: SQL query against map_entity table

        Returns:
            List of BaseEntity instances with REMOTE view

        Example:
            >>> drills = view.get_entities('''
            ...     SELECT * FROM map_entity
            ...     WHERE entity_name = 'burner-mining-drill'
            ...     AND chunk_x = 0 AND chunk_y = 0
            ... ''')
        """
        self._ensure_query_ready()
        return self._query.get_entities(sql)

    def get_entity(self, sql: str) -> Optional["BaseEntity"]:
        """Execute SQL with LIMIT 1, return single entity.

        Convenience method when you expect at most one result.

        Args:
            sql: SQL query (LIMIT 1 added if not present)

        Returns:
            Single BaseEntity with REMOTE view or None
        """
        self._ensure_query_ready()
        return self._query.get_entity(sql)

    def get_resources(self, sql: str) -> List["BaseResource"]:
        """Execute SQL, return resource instances with REMOTE view.

        Query should select from resource_tile or resource_entity tables.
        Each row is converted to a resource object with REMOTE view.

        Args:
            sql: SQL query against resource tables

        Returns:
            List of BaseResource instances with REMOTE view

        Example:
            >>> iron = view.get_resources('''
            ...     SELECT * FROM resource_tile
            ...     WHERE name = 'iron-ore'
            ... ''')
        """
        self._ensure_query_ready()
        return self._query.get_resources(sql)

    def get_ghosts(self, sql: str) -> List["BaseEntity"]:
        """Execute SQL against ghost table, return ghost entities with REMOTE view.

        Ghosts are tracked separately from regular entities.
        Each ghost has is_ghost=True.

        Args:
            sql: SQL query against ghost table

        Returns:
            List of BaseEntity instances (with is_ghost=True)

        Example:
            >>> pending = view.get_ghosts('''
            ...     SELECT * FROM ghost
            ...     WHERE ghost_name = 'assembling-machine-1'
            ... ''')
        """
        self._ensure_query_ready()
        return self._query.get_ghosts(sql)

    # =========================================================================
    # Convenience Methods
    # =========================================================================

    def count_entities(self, entity_name: Optional[str] = None) -> int:
        """Count entities, optionally filtered by name.

        Args:
            entity_name: Optional filter by entity name

        Returns:
            Count of matching entities
        """
        self._ensure_query_ready()
        if entity_name:
            result = self.query(
                f"SELECT COUNT(*) as c FROM map_entity WHERE entity_name = '{entity_name}'"
            )
        else:
            result = self.query("SELECT COUNT(*) as c FROM map_entity")
        return result[0]["c"] if result else 0

    def count_ghosts(self, ghost_name: Optional[str] = None) -> int:
        """Count ghosts, optionally filtered by name."""
        self._ensure_query_ready()
        if ghost_name:
            result = self.query(
                f"SELECT COUNT(*) as c FROM ghost WHERE ghost_name = '{ghost_name}'"
            )
        else:
            result = self.query("SELECT COUNT(*) as c FROM ghost")
        return result[0]["c"] if result else 0

    # =========================================================================
    # Tile-Based Spatial Queries
    # =========================================================================

    def get_entity_at_tile(self, tile_x: int, tile_y: int) -> Optional["BaseEntity"]:
        """Get entity occupying a specific tile.

        Uses the footprint_tiles table for O(1) tile lookup.
        Returns the entity whose footprint includes this tile.

        Args:
            tile_x: Tile X coordinate (integer)
            tile_y: Tile Y coordinate (integer)

        Returns:
            BaseEntity if tile is occupied, None otherwise

        Example:
            >>> entity = view.get_entity_at_tile(5, 10)
            >>> if entity:
            ...     print(f"Tile occupied by {entity.name}")
        """
        self._ensure_query_ready()

        # Query footprint_tiles to find entity at this tile
        result = self.query(f"""
            SELECT ft.entity_name, ft.entity_position_x, ft.entity_position_y, ft.is_ghost
            FROM footprint_tiles ft
            WHERE ft.tile_x = {tile_x} AND ft.tile_y = {tile_y}
            LIMIT 1
        """)

        if not result:
            return None

        row = result[0]
        is_ghost = row.get("is_ghost", False)

        if is_ghost:
            # Query ghost table
            return self.get_entity(f"""
                SELECT * FROM ghost
                WHERE ghost_name = '{row["entity_name"]}'
                AND position_x = {row["entity_position_x"]}
                AND position_y = {row["entity_position_y"]}
            """)
        else:
            # Query map_entity table
            return self.get_entity(f"""
                SELECT * FROM map_entity
                WHERE entity_name = '{row["entity_name"]}'
                AND position_x = {row["entity_position_x"]}
                AND position_y = {row["entity_position_y"]}
            """)

    def is_tile_occupied(self, tile_x: int, tile_y: int) -> bool:
        """Check if a tile is occupied by any entity.

        Fast O(1) check using footprint_tiles table index.

        Args:
            tile_x: Tile X coordinate (integer)
            tile_y: Tile Y coordinate (integer)

        Returns:
            True if tile is occupied, False otherwise

        Example:
            >>> if not view.is_tile_occupied(5, 10):
            ...     # Safe to place entity here
        """
        self._ensure_query_ready()
        result = self.query(f"""
            SELECT 1 FROM footprint_tiles
            WHERE tile_x = {tile_x} AND tile_y = {tile_y}
            LIMIT 1
        """)
        return len(result) > 0

    def get_entities_in_tile_area(
        self,
        min_tile_x: int,
        min_tile_y: int,
        max_tile_x: int,
        max_tile_y: int,
        entity_name: Optional[str] = None,
    ) -> List["BaseEntity"]:
        """Get all entities with footprints overlapping a tile area.

        Uses tile-based indexing for efficient rectangular area queries.
        Much faster than geometry-based queries for tile-aligned areas.

        Args:
            min_tile_x: Minimum tile X coordinate (inclusive)
            min_tile_y: Minimum tile Y coordinate (inclusive)
            max_tile_x: Maximum tile X coordinate (inclusive)
            max_tile_y: Maximum tile Y coordinate (inclusive)
            entity_name: Optional filter by entity name

        Returns:
            List of BaseEntity instances in the area

        Example:
            >>> # Get all entities in a 10x10 tile area
            >>> entities = view.get_entities_in_tile_area(0, 0, 9, 9)
            >>> # Get only inserters in the area
            >>> inserters = view.get_entities_in_tile_area(0, 0, 9, 9, "inserter")
        """
        self._ensure_query_ready()

        # Find unique entities with footprints in the tile area
        name_filter = f"AND ft.entity_name = '{entity_name}'" if entity_name else ""

        result = self.query(f"""
            SELECT DISTINCT ft.entity_name, ft.entity_position_x, ft.entity_position_y, ft.is_ghost
            FROM footprint_tiles ft
            WHERE ft.tile_x >= {min_tile_x} AND ft.tile_x <= {max_tile_x}
            AND ft.tile_y >= {min_tile_y} AND ft.tile_y <= {max_tile_y}
            {name_filter}
        """)

        if not result:
            return []

        # Separate ghosts and regular entities
        entities = []
        ghosts = []
        for row in result:
            if row.get("is_ghost", False):
                ghosts.append(row)
            else:
                entities.append(row)

        all_entities: List["BaseEntity"] = []

        # Fetch regular entities
        if entities:
            # Build IN clause for efficient batch query
            entity_conditions = " OR ".join([
                f"(entity_name = '{r['entity_name']}' AND position_x = {r['entity_position_x']} AND position_y = {r['entity_position_y']})"
                for r in entities
            ])
            all_entities.extend(self.get_entities(f"""
                SELECT * FROM map_entity WHERE {entity_conditions}
            """))

        # Fetch ghosts
        if ghosts:
            ghost_conditions = " OR ".join([
                f"(ghost_name = '{r['entity_name']}' AND position_x = {r['entity_position_x']} AND position_y = {r['entity_position_y']})"
                for r in ghosts
            ])
            all_entities.extend(self.get_ghosts(f"""
                SELECT * FROM ghost WHERE {ghost_conditions}
            """))

        return all_entities

    def get_entities_at_anchor_tile(
        self, tile_x: int, tile_y: int
    ) -> List["BaseEntity"]:
        """Get entities whose anchor tile (center) is at a specific tile.

        Unlike get_entity_at_tile which checks footprint overlap,
        this returns only entities centered on the specified tile.

        Args:
            tile_x: Tile X coordinate (integer)
            tile_y: Tile Y coordinate (integer)

        Returns:
            List of BaseEntity instances with anchor at this tile

        Example:
            >>> # Find entities centered at tile (5, 10)
            >>> entities = view.get_entities_at_anchor_tile(5, 10)
        """
        self._ensure_query_ready()
        return self.get_entities(f"""
            SELECT * FROM map_entity
            WHERE tile_x = {tile_x} AND tile_y = {tile_y}
        """)

    @property
    def sync_state(self) -> SyncState:
        """Get current sync state."""
        if self._sync:
            return self._sync.state
        return SyncState(
            last_sequence=self._last_sequence,
            is_running=False,
            needs_rebuild=False,
        )

    @property
    def is_loaded(self) -> bool:
        """True if load() has been called."""
        return self._loaded

    # =========================================================================
    # Debugging and Manual Control
    # =========================================================================

    def flush(self) -> int:
        """Manually flush all pending write operations.

        For debugging: Call this before queries if you suspect stale data.
        This is automatically called by query methods, but can be invoked manually.

        Returns:
            Number of operations flushed
        """
        if self._sync:
            return self._sync.flush_pending()
        return 0

    def debug_info(self) -> Dict[str, Any]:
        """Get diagnostic information about RemoteView state.

        Returns:
            Dict with internal state for debugging
        """
        info = {
            "loaded": self._loaded,
            "last_sequence": self._last_sequence,
            "sync_exists": self._sync is not None,
            "sync_running": self._sync._running if self._sync else False,
            "pending_operations": self._sync._pending_operations.qsize()
            if self._sync
            else 0,
            "query_executor_has_sync": self._query._sync_service is not None
            if self._query
            else False,
        }

        # Try to get counts from DB
        try:
            if self._loaded:
                info["entity_count"] = self.count_entities()
                info["resource_entity_count"] = self.query(
                    "SELECT COUNT(*) as c FROM resource_entity"
                )[0]["c"]
        except Exception as e:
            info["db_error"] = str(e)

        return info

    # =========================================================================
    # Internal
    # =========================================================================

    async def _wait_for_bootstrap_complete(self, timeout: float = 120.0) -> None:
        """Wait for bootstrap phase to complete (INITIAL_SNAPSHOTTING → MAINTENANCE).

        Uses a dual approach for reliability:
        1. Subscribes to UDP `system_phase_changed` events for immediate notification
        2. Polls `get_snapshot_status` via RCON as a fallback (in case UDP is missed)

        This ensures we don't miss the critical transition from bootstrap to maintenance mode.

        Args:
            timeout: Maximum time to wait for bootstrap (seconds, default 120s = 2 minutes)

        Raises:
            asyncio.TimeoutError: If bootstrap doesn't complete within timeout
        """
        if not self._rcon_client:
            logger.warning("No RCON client provided - skipping bootstrap wait")
            return

        start_time = time.time()
        check_interval = 1.0  # Check every second

        # Event to signal bootstrap completion
        bootstrap_complete = asyncio.Event()
        phase_received = {"phase": None, "stats": None}

        # Subscribe to UDP system_phase_changed events for immediate notification
        udp_dispatcher = get_udp_dispatcher()
        if not udp_dispatcher.is_running():
            await udp_dispatcher.start()

        def handle_phase_change(payload: dict) -> None:
            """Handle system_phase_changed UDP event."""
            phase = payload.get("phase")
            if phase == "MAINTENANCE":
                phase_received["phase"] = phase
                phase_received["stats"] = payload.get("stats", {})
                bootstrap_complete.set()
                logger.info("📡 Received system_phase_changed UDP event: MAINTENANCE")

        # Subscribe to phase change events
        udp_dispatcher.subscribe("system_phase_changed", handle_phase_change)

        try:
            logger.info("⏳ Waiting for snapshot system bootstrap to complete...")
            print("⏳ Waiting for snapshot system bootstrap to complete...")

            while True:
                # Check if timeout exceeded
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    raise asyncio.TimeoutError(
                        f"Bootstrap did not complete within {timeout}s. "
                        "System may still be in INITIAL_SNAPSHOTTING phase."
                    )

                # Check if UDP event already signaled completion
                if bootstrap_complete.is_set():
                    stats = phase_received.get("stats", {})
                    completed = stats.get("chunks_snapshotted", 0) if stats else 0
                    logger.info(
                        "✅ Bootstrap complete! Transitioned to MAINTENANCE mode (via UDP)."
                    )
                    logger.info(f"✅ {completed} chunks snapshotted during bootstrap.")
                    print(f"✅ Bootstrap complete! {completed} chunks snapshotted.")
                    return

                # Poll snapshot system status via adapter as fallback
                try:
                    if self._map_api is None:
                        logger.debug("No map_api available, retrying...")
                        await asyncio.sleep(check_interval)
                        continue

                    status = self._map_api.get_snapshot_status()

                    if status.system_phase == "MAINTENANCE":
                        # Bootstrap complete! (detected via polling)
                        logger.info(
                            "✅ Bootstrap complete! Transitioned to MAINTENANCE mode (via polling)."
                        )
                        logger.info(
                            f"✅ {status.chunks_snapshotted} chunks snapshotted during bootstrap."
                        )
                        print(f"✅ Bootstrap complete! {status.chunks_snapshotted} chunks snapshotted.")
                        return

                    elif status.system_phase == "INITIAL_SNAPSHOTTING":
                        # Still bootstrapping
                        if int(elapsed) % 5 == 0:  # Log every 5 seconds
                            logger.debug(
                                f"Processing chunks: {status.chunks_pending} pending, "
                                f"{status.chunks_snapshotted} completed"
                            )
                            print(
                                f"  📦 Processing: {status.chunks_pending} pending, "
                                f"{status.chunks_snapshotted} completed"
                            )

                except Exception as e:
                    logger.warning(f"Error checking bootstrap status: {e}")
                    # Continue waiting, don't fail on transient errors

                # Wait before next check (or until UDP event)
                try:
                    await asyncio.wait_for(
                        bootstrap_complete.wait(), timeout=check_interval
                    )
                    # If we get here, event was set
                    continue
                except asyncio.TimeoutError:
                    # Timeout is expected - continue polling
                    pass
        finally:
            # Unsubscribe from UDP events
            udp_dispatcher.unsubscribe("system_phase_changed", handle_phase_change)

    def _ensure_query_ready(self) -> None:
        """Ensure query executor is initialized."""
        if not self._loaded or self._query is None:
            raise RuntimeError("RemoteView not loaded. Call load() first.")


__all__ = ["RemoteView"]
