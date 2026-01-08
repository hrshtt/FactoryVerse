"""RemoteView - Facade for map-wide entity queries.

Composes database, loader, sync, and query modules into a single interface.
This is the main entry point for agents to query map data.

Usage:
    view = RemoteView(snapshot_dir, udp_dispatcher=dispatcher)
    view.load()
    await view.start()  # Begin sync

    # Query entities
    entities = view.get_entities("SELECT * FROM map_entity LIMIT 10")

    # Query ghosts
    ghosts = view.get_ghosts("SELECT * FROM ghost WHERE ghost_name = 'inserter'")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from FactoryVerse.infra.udp_dispatcher import UDPDispatcher
    from FactoryVerse.factory.resource.remote_view_resource import RemoteViewResource
    from FactoryVerse.factory.entity.base_entity import BaseEntity

from .database import SnapshotDatabase
from .loader import SnapshotLoader
from .sync import SyncService
from .query import QueryExecutor
from .types import LoadResult, SyncState

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
        >>> view = RemoteView(snapshot_dir)
        >>> view.load()
        >>> await view.start()
        >>> drills = view.get_entities('''
        ...     SELECT * FROM map_entity
        ...     WHERE entity_name = 'burner-mining-drill'
        ... ''')
    """

    def __init__(
        self,
        snapshot_dir: Path,
        db_path: Optional[Path] = None,
        udp_dispatcher: Optional["UDPDispatcher"] = None,
    ):
        """Initialize RemoteView.

        Args:
            snapshot_dir: Path to snapshot directory (or script-output root)
            db_path: Path for persistent DB. None = in-memory (default).
            udp_dispatcher: UDP dispatcher for real-time sync. None = no sync.
        """
        self._snapshot_dir = Path(snapshot_dir)
        self._udp_dispatcher = udp_dispatcher

        # Core components
        self._database = SnapshotDatabase(db_path)

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

    def load(self) -> LoadResult:
        """Load snapshot files into database.

        Must be called before querying. Can be called again to reload.

        Returns:
            LoadResult with counts and last sequence number
        """
        # Ensure schema exists
        self._database.ensure_schema()

        # Initialize components
        self._loader = SnapshotLoader(
            self._database.connection,
            self._snapshot_dir,
        )
        self._query = QueryExecutor(self._database.connection)

        # Load data
        result = self._loader.load_all()
        self._last_sequence = result.last_sequence
        self._database.set_last_sequence(result.last_sequence)

        self._loaded = True
        logger.info(f"RemoteView loaded: {result}")
        return result

    def rebuild(self) -> LoadResult:
        """Clear and reload from files.

        Called when sync detects a sequence gap.
        """
        logger.info("RemoteView rebuild triggered")
        self._database.reset()
        return self.load()

    async def start(self) -> None:
        """Start background sync.

        Must call load() first to establish initial state.
        """
        if not self._loaded:
            raise RuntimeError("Must call load() before start()")

        if self._udp_dispatcher is None:
            logger.info("No UDP dispatcher - sync disabled")
            return

        self._sync = SyncService(
            db=self._database.connection,
            udp_dispatcher=self._udp_dispatcher,
            on_rebuild=self._handle_rebuild_needed,
            initial_sequence=self._last_sequence,
        )
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

    def get_resources(self, sql: str) -> List["RemoteViewResource"]:
        """Execute SQL, return resource instances.

        Query should select from resource_tile or resource_entity tables.

        Args:
            sql: SQL query against resource tables

        Returns:
            List of RemoteViewResource instances

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
    # Internal
    # =========================================================================

    def _ensure_query_ready(self) -> None:
        """Ensure query executor is initialized."""
        if not self._loaded or self._query is None:
            raise RuntimeError("RemoteView not loaded. Call load() first.")


__all__ = ["RemoteView"]
