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
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from FactoryVerse.game.factory.types import MapPosition
    from FactoryVerse.infra.udp_dispatcher import UDPDispatcher
    from FactoryVerse.game.factory.resource.base import BaseResource
    from FactoryVerse.game.factory.entity.base_entity import BaseEntity
    from FactoryVerse.game.agent.embodied_actions.walking import MovementAction
    from FactoryVerse.game.agent.embodied_actions.entity_operations import EntityOperationsAction
    from FactoryVerse.game.agent.embodied_actions.place_entity import PlacementAction
    from FactoryVerse.game.agent.embodied_actions.mining import MiningAction
    from factorio_rcon import RCONClient

from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase
from FactoryVerse.game.infra.duckdb.loader import SnapshotLoader
from FactoryVerse.game.infra.duckdb.sync import SyncService
from FactoryVerse.game.infra.duckdb.query import QueryExecutor
from FactoryVerse.game.snapshot.types import LoadResult, SyncState
from FactoryVerse.infra.udp_dispatcher import get_udp_dispatcher

logger = logging.getLogger(__name__)


# =============================================================================
# Power UX typed results (WS4)
# =============================================================================


@dataclass
class PowerNetworkCensus:
    """One live electric network from the latest power sample.

    Returned inside :class:`PowerNetworksReport` by
    :meth:`RemoteView.get_power_networks`. The durable per-network reference is
    the anchor pole (``anchor_pole_name`` + ``anchor_pole_position``); the
    engine ``network_id`` is a per-sample handle only (it renumbers on
    merge/split — see the power_networks table notes).

    ``low_power_count`` / ``no_power_count`` are computed by joining
    entity_status to map_entity on (name, position) to recover each entity's
    ``electric_network_id``. That id is AS-OF the last entity write, not the
    sample instant, so on a network that just merged/split the counts can lag
    the wattages by up to one entity-write cycle.
    """

    network_id: Optional[int]
    anchor_pole_name: Optional[str]
    anchor_pole_position: Optional[Dict[str, float]]
    pole_count: int
    member_count: int
    production_w: float
    consumption_w: float
    storage_j: float
    headroom_ratio: Optional[float]
    production_by_prototype: Dict[str, float]
    consumption_by_prototype: Dict[str, float]
    low_power_count: int
    no_power_count: int
    sample_tick: int


@dataclass
class PowerNetworksReport:
    """Census of every live electric network at one power sample.

    ``networks`` is ordered by anchor-pole position (stable across samples of
    an unchanged network). ``sample_tick`` is None only when no power sample
    has been ingested yet. ``freshness_note`` documents the sample's age and
    the as-of-write staleness of the entity_status join.
    """

    networks: List[PowerNetworkCensus]
    sample_tick: Optional[int]
    freshness_note: str
    # DIGEST-2: no_power entities that attribute to NO network (their
    # electric_network_id is nil — e.g. not covered by any pole, the sickest
    # case). They appear in entity_status/diagnose_power but in no network's
    # per-net counts, so without this field the report (and the Task Progress
    # digest built from it) under-reports exactly the machines that are worst
    # off. Network-independent count, straight from entity_status.
    unattributed_no_power: int = 0


@dataclass
class PowerDiagnosis:
    """Result of :meth:`RemoteView.diagnose_power` — a one-shot power triage.

    ``verdict`` is one of: 'working', 'not_covered_by_any_pole',
    'network_has_no_generation', 'network_undersupplied',
    'upstream_generator_starved', 'no_status_data', 'entity_not_found',
    'non_electric_or_no_issue'. ``explanation`` is human-readable and encodes
    the live-learned caveats (poles report nil status; a starved producer
    still reports 'working'; Factorio's single status can mask low_power
    behind a logistics status) where they apply.
    """

    verdict: str
    explanation: str
    entity_name: str
    position: Dict[str, float]
    status_name: Optional[str] = None
    network_id: Optional[int] = None
    production_w: Optional[float] = None
    consumption_w: Optional[float] = None
    covering_pole_name: Optional[str] = None
    covering_pole_position: Optional[Dict[str, float]] = None
    sample_tick: Optional[int] = None


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
            from FactoryVerse.game.snapshot import MapSnapshotInterface
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
                # Lets SyncService resolve the container-relative file_path
                # carried by power_networks/entity_status file_io UDP
                # payloads (power-impl-contracts.md Task 4).
                snapshot_dir=self._snapshot_dir,
            )
        else:
            self._sync = None

        # Initialize components
        self._loader = SnapshotLoader(
            self._database.connection,
            self._snapshot_dir,
        )

        # NOTE: entity_status is now a real persistent table (see
        # schema_definitions.ENTITY_STATUS), populated via
        # analytics_ops.apply_status_dump by both SnapshotLoader.load_all()
        # (boot) and SyncService (live). The old on-demand status_dir/
        # status_loader.py path is gone (Task 5) — QueryExecutor no longer
        # takes a status_dir argument.
        self._query = QueryExecutor(
            self._database.connection,
            entity_ops=self._entity_ops,
            place_ops=self._place_ops,
            walking_action=self._walking_action,
            mining_action=self._mining_action,
            sync_service=self._sync,
            db_lock=self._db_lock,
        )

        # Load data (with lock to prevent concurrent access)
        # current_game_tick guards against previous-boot files whose ticks
        # are "from the future" (CELL-2a)
        current_game_tick = self._current_game_tick()
        logger.info(
            f"Loading snapshot data from disk (game tick guard: {current_game_tick})..."
        )
        with self._db_lock:
            result = self._loader.load_all(current_game_tick=current_game_tick)

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

        # Fetch tick OUTSIDE the lock (RCON call); guards stale-boot files
        current_game_tick = self._current_game_tick()

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
            
            # Re-initialize query executor if needed
            if self._query is None:
                self._query = QueryExecutor(
                    self._database.connection,
                    entity_ops=self._entity_ops,
                    place_ops=self._place_ops,
                    walking_action=self._walking_action,
                    mining_action=self._mining_action,
                    sync_service=self._sync,
                    db_lock=self._db_lock,
                )

            # Load data synchronously (already holding lock)
            result = self._loader.load_all(current_game_tick=current_game_tick)
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

    def execute_raw(self, sql: str) -> List[tuple]:
        """Execute SQL on the view's DuckDB, return raw fetchall() tuples.

        This is the unification point for the `execute_duckdb` tool path
        (CELL-1 item 6): it reads the SAME connection as query()/get_entities(),
        with the same flush-before-read and lock discipline, so the two agent
        query paths can never serve different truths.

        Unlike query(), the SQL is not restricted to SELECT (preserves the
        legacy execute_duckdb behavior) and rows are tuples, not dicts.
        """
        if not self._loaded:
            raise RuntimeError("RemoteView not loaded. Call load() first.")

        # Flush pending UDP-synced writes before reading (same as QueryExecutor)
        if self._sync:
            self._sync.flush_pending()

        with self._db_lock:
            return self._database.connection.execute(sql).fetchall()

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

    async def wait_for_resource_depletion(
        self,
        entity_name: str,
        position_x: float,
        position_y: float,
        timeout: float = 5.0,
    ) -> Dict[str, Any]:
        """Wait until an awaited depletion is visible in the owned database.

        Action completion and snapshot mutations use separate UDP transports,
        so draining only the mutations already queued at query time is not a
        causal barrier. This method hides that transport race below the actor
        API: once ``mine()`` returns, the next query cannot observe the exact
        depleted tree or rock.
        """
        if not self._loaded:
            raise RuntimeError("RemoteView not loaded. Call load() first.")

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            if self._sync:
                self._sync.flush_pending()
            with self._db_lock:
                remaining = self._database.connection.execute(
                    """
                    SELECT count(*) FROM resource_entity
                    WHERE name = ? AND position_x = ? AND position_y = ?
                    """,
                    [entity_name, float(position_x), float(position_y)],
                ).fetchone()[0]
            if remaining == 0:
                removal_fact = (
                    self._sync.get_applied_resource_removal(
                        entity_name, float(position_x), float(position_y)
                    )
                    if self._sync
                    else None
                )
                if removal_fact and removal_fact.get("duckdb_rows_removed") == 1:
                    return removal_fact
            if loop.time() >= deadline:
                raise TimeoutError(
                    "Depleted resource did not become visible in DuckDB: "
                    f"{entity_name} at ({position_x}, {position_y})"
                )
            await asyncio.sleep(0.01)

    def wait_for_placement(
        self,
        entity_name: str,
        position_x: float,
        position_y: float,
        ghost: bool,
        label: Optional[str] = None,
        timeout: float = 5.0,
    ) -> None:
        """Wait until a completed placement is atomically visible to reads.

        The placement RCON call and snapshot mutation use separate transports.
        The UDP dispatcher runs on its own thread, so this synchronous barrier
        can drain those mutations before returning from the synchronous actor
        placement API. A real placement is complete only when its exact entity
        row exists and any ghost at that identity is absent.
        """
        if not self._loaded:
            raise RuntimeError("RemoteView not loaded. Call load() first.")

        deadline = time.monotonic() + timeout
        while True:
            if self._sync:
                self._sync.flush_pending()
            with self._db_lock:
                if ghost:
                    visible = self._database.connection.execute(
                        """
                        SELECT count(*) FROM ghost
                        WHERE ghost_name = ?
                          AND position_x = ? AND position_y = ?
                          AND (? IS NULL OR label = ?)
                        """,
                        [
                            entity_name,
                            float(position_x),
                            float(position_y),
                            label,
                            label,
                        ],
                    ).fetchone()[0]
                    complete = visible == 1
                else:
                    visible = self._database.connection.execute(
                        """
                        SELECT count(*) FROM map_entity
                        WHERE entity_name = ?
                          AND position_x = ? AND position_y = ?
                          AND (? IS NULL OR label = ?)
                        """,
                        [
                            entity_name,
                            float(position_x),
                            float(position_y),
                            label,
                            label,
                        ],
                    ).fetchone()[0]
                    remaining_ghosts = self._database.connection.execute(
                        """
                        SELECT count(*) FROM ghost
                        WHERE ghost_name = ?
                          AND position_x = ? AND position_y = ?
                        """,
                        [entity_name, float(position_x), float(position_y)],
                    ).fetchone()[0]
                    complete = visible == 1 and remaining_ghosts == 0
            if complete:
                return
            if time.monotonic() >= deadline:
                state = "ghost" if ghost else "real entity with no remaining ghost"
                raise TimeoutError(
                    f"Placed {state} did not become visible in DuckDB: "
                    f"{entity_name} at ({position_x}, {position_y}), label={label!r}"
                )
            time.sleep(0.01)

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

    def find_water(
        self,
        near: Optional["MapPosition"] = None,
        radius: Optional[float] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """Find water tiles on the map (not validated offshore-pump anchors).

        Terrain affordance: answers "where is water?" from the snapshot DB
        without probing placements (AFFORD-1 — never use place/pickup as a
        terrain scanner). Returned positions are unwalkable water-tile centers,
        not offshore-pump anchors or walking destinations.

        Args:
            near: If given, results are ordered by distance to this position
                and each row includes a 'distance' field
            radius: With `near`, only tiles within this many tiles
            limit: Max rows returned (default 500)

        Returns:
            List of dicts: {'x': float, 'y': float[, 'distance': float]},
            empty list if the map truly has no water in range. If the whole
            map unexpectedly returns [], check snapshot freshness via
            `query("SELECT MAX(tick) FROM chunk_snapshot_meta")` before
            concluding water does not exist.

        Before travelling or placing, use
        ``placement_hints.find_offshore_pump_sites`` around one of these tiles
        to obtain engine-validated pump anchors, directions, and standable
        approach positions.
        """
        self._ensure_query_ready()
        limit = int(limit)
        if near is not None:
            nx, ny = float(near.x), float(near.y)
            dist_expr = (
                f"sqrt((position_x - {nx})*(position_x - {nx}) + "
                f"(position_y - {ny})*(position_y - {ny}))"
            )
            where = f"WHERE {dist_expr} <= {float(radius)}" if radius is not None else ""
            sql = (
                f"SELECT position_x AS x, position_y AS y, {dist_expr} AS distance "
                f"FROM water_tile {where} ORDER BY distance LIMIT {limit}"
            )
        else:
            sql = (
                f"SELECT position_x AS x, position_y AS y "
                f"FROM water_tile ORDER BY position_y, position_x LIMIT {limit}"
            )
        return self._query.query(sql)

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
    # Power UX (WS4)
    # =========================================================================

    @staticmethod
    def _parse_json_dict(raw: Any) -> Dict[str, float]:
        """Parse a JSON-column value (DuckDB returns JSON as a str) to a dict."""
        if raw is None:
            return {}
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                return {}
        else:
            parsed = raw
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _pos_xy(position: Any) -> Tuple[float, float]:
        """Normalize a position argument to (x, y).

        Accepts a MapPosition (``.x``/``.y``), a dict ``{'x','y'}``, or a
        ``(x, y)`` tuple/list.
        """
        if hasattr(position, "x") and hasattr(position, "y"):
            return float(position.x), float(position.y)
        if isinstance(position, dict):
            return float(position["x"]), float(position["y"])
        if isinstance(position, (tuple, list)) and len(position) >= 2:
            return float(position[0]), float(position[1])
        raise TypeError(
            f"Unsupported position {position!r}; expected MapPosition, "
            f"{{'x','y'}} dict, or (x, y) tuple"
        )

    def _latest_power_tick(self, as_of_tick: Optional[int]) -> Optional[int]:
        """Sample tick to read: as_of_tick if given, else max(power_samples.tick)."""
        if as_of_tick is not None:
            return int(as_of_tick)
        rows = self.execute_raw("SELECT max(tick) FROM power_samples")
        if rows and rows[0][0] is not None:
            return int(rows[0][0])
        return None

    def _power_freshness_note(self, sample_tick: int) -> str:
        """Describe the sample's age and the entity_status join staleness.

        Cheap DB-only reads: newest power sample tick and the entity_status
        freshness marker (sync_state key 'entity_status_last_tick'). No RCON.
        """
        newest = self.execute_raw("SELECT max(tick) FROM power_samples")
        newest_tick = newest[0][0] if newest and newest[0][0] is not None else sample_tick
        parts = [f"power sample at tick {sample_tick}"]
        if newest_tick is not None and int(newest_tick) != int(sample_tick):
            parts.append(f"newest sample is tick {int(newest_tick)} (Δ{int(newest_tick) - int(sample_tick)} ticks)")
        status_rows = self.execute_raw(
            "SELECT value FROM sync_state WHERE key = 'entity_status_last_tick'"
        )
        if status_rows and status_rows[0][0] is not None:
            status_tick = int(status_rows[0][0])
            parts.append(
                f"low_power/no_power counts joined via entity_status dump at tick "
                f"{status_tick} (Δ{status_tick - int(sample_tick)} vs sample) using "
                f"map_entity.electric_network_id which is as-of last entity write — "
                f"membership can lag on a just-merged/split network"
            )
        else:
            parts.append("no entity_status dump ingested yet — low_power/no_power counts are 0")
        return "; ".join(parts)

    def get_power_networks(
        self, as_of_tick: Optional[int] = None
    ) -> PowerNetworksReport:
        """Per-network power census from the latest power sample.

        Reads the latest power_networks sample (or the sample at ``as_of_tick``)
        and, for each live electric network, returns its anchor pole, pole /
        member counts, production / consumption / storage, a headroom ratio
        (production / consumption; None when consumption is 0), the per-prototype
        production and consumption breakdowns (parsed dicts, not raw JSON), and
        the count of low_power / no_power entities on that network.

        The low_power/no_power counts come from joining entity_status to
        map_entity on (entity_name, position) to recover each entity's
        electric_network_id, then matching the sample's ``network_id``. That id
        is AS OF the last entity write, not the sample instant, so on a network
        that just merged/split the counts can lag the wattages by one
        entity-write cycle (see ``freshness_note`` on the returned report).

        Args:
            as_of_tick: Read this sample tick instead of the latest.

        Returns:
            PowerNetworksReport. ``sample_tick`` is None (and ``networks`` empty)
            only when no power sample has been ingested yet.

        Example:
            >>> report = remote_view.get_power_networks()
            >>> for net in report.networks:
            ...     print(net.anchor_pole_name, net.production_w, net.consumption_w)
        """
        self._ensure_query_ready()

        sample_tick = self._latest_power_tick(as_of_tick)
        if sample_tick is None:
            return PowerNetworksReport(
                networks=[],
                sample_tick=None,
                freshness_note=(
                    "no power sample ingested yet (power_samples is empty) — the "
                    "sampler has not run, which is different from 'no networks'"
                ),
            )

        # Per-network low_power/no_power counts, one grouped pass.
        counts: Dict[int, Tuple[int, int]] = {}
        for r in self.query(
            """
            SELECT me.electric_network_id AS nid,
                   SUM(CASE WHEN es.status_name = 'low_power' THEN 1 ELSE 0 END) AS lp,
                   SUM(CASE WHEN es.status_name = 'no_power' THEN 1 ELSE 0 END) AS np
            FROM entity_status es
            JOIN map_entity me
              ON es.entity_name = me.entity_name
             AND es.position_x = me.position_x
             AND es.position_y = me.position_y
            WHERE me.electric_network_id IS NOT NULL
            GROUP BY me.electric_network_id
            """
        ):
            counts[r["nid"]] = (int(r["lp"] or 0), int(r["np"] or 0))

        net_rows = self.query(
            f"""
            SELECT network_id, anchor_pole_name, anchor_pole_x, anchor_pole_y,
                   pole_count, member_count, production_w, consumption_w, storage_j,
                   production_by_prototype, consumption_by_prototype
            FROM power_networks
            WHERE tick = {int(sample_tick)}
            ORDER BY anchor_pole_x, anchor_pole_y, network_id
            """
        )

        networks: List[PowerNetworkCensus] = []
        for r in net_rows:
            prod = float(r["production_w"] or 0.0)
            cons = float(r["consumption_w"] or 0.0)
            headroom = (prod / cons) if cons > 0 else None
            low, no = counts.get(r["network_id"], (0, 0))
            anchor_pos = (
                {"x": r["anchor_pole_x"], "y": r["anchor_pole_y"]}
                if r["anchor_pole_x"] is not None
                else None
            )
            networks.append(
                PowerNetworkCensus(
                    network_id=r["network_id"],
                    anchor_pole_name=r["anchor_pole_name"],
                    anchor_pole_position=anchor_pos,
                    pole_count=int(r["pole_count"] or 0),
                    member_count=int(r["member_count"] or 0),
                    production_w=prod,
                    consumption_w=cons,
                    storage_j=float(r["storage_j"] or 0.0),
                    headroom_ratio=headroom,
                    production_by_prototype=self._parse_json_dict(r["production_by_prototype"]),
                    consumption_by_prototype=self._parse_json_dict(r["consumption_by_prototype"]),
                    low_power_count=low,
                    no_power_count=no,
                    sample_tick=int(sample_tick),
                )
            )

        # DIGEST-2: no_power entities with no network attribution (nil
        # electric_network_id, or no map_entity row at all). These are the
        # not-covered-by-any-pole cases — they must not vanish from the report
        # just because the per-network join has no bucket for them.
        orphan_rows = self.query(
            """
            SELECT COUNT(*) AS n
            FROM entity_status es
            LEFT JOIN map_entity me
              ON es.entity_name = me.entity_name
             AND es.position_x = me.position_x
             AND es.position_y = me.position_y
            WHERE es.status_name = 'no_power'
              AND me.electric_network_id IS NULL
            """
        )
        unattributed = int(orphan_rows[0]["n"] or 0) if orphan_rows else 0

        return PowerNetworksReport(
            networks=networks,
            sample_tick=int(sample_tick),
            freshness_note=self._power_freshness_note(int(sample_tick)),
            unattributed_no_power=unattributed,
        )

    def _find_covering_pole(self, x: float, y: float) -> Optional[Dict[str, Any]]:
        """Nearest electric pole whose (square) supply area covers (x, y).

        Poles are read from map_entity (there is no type column, so we filter
        by the known pole prototype names); each pole's supply_area_distance
        comes from the offline prototype pipeline (same source ElectricPole
        uses). Returns the covering pole with the smallest center distance, or
        None if no pole covers the point.
        """
        from FactoryVerse.game.agent.placement_hints import (
            ELECTRIC_POLE_ENTITIES,
            _pole_prototype_distances,
        )

        names = "', '".join(sorted(ELECTRIC_POLE_ENTITIES))
        poles = self.query(
            f"""
            SELECT entity_name, position_x, position_y, electric_network_id
            FROM map_entity
            WHERE entity_name IN ('{names}')
            """
        )
        best: Optional[Dict[str, Any]] = None
        best_d2 = None
        for p in poles:
            try:
                _wire, supply = _pole_prototype_distances(p["entity_name"])
            except ValueError:
                continue
            px, py = p["position_x"], p["position_y"]
            # get_supply_area() is a square box of ±supply_area_distance.
            if abs(x - px) <= supply and abs(y - py) <= supply:
                d2 = (x - px) ** 2 + (y - py) ** 2
                if best_d2 is None or d2 < best_d2:
                    best_d2 = d2
                    best = p
        return best

    def _network_at_tick(
        self, network_id: Optional[int], tick: int
    ) -> Optional[Dict[str, Any]]:
        """The power_networks row for network_id at a sample tick, or None."""
        if network_id is None:
            return None
        rows = self.query(
            f"""
            SELECT network_id, anchor_pole_name, anchor_pole_x, anchor_pole_y,
                   production_w, consumption_w
            FROM power_networks
            WHERE tick = {int(tick)} AND network_id = {int(network_id)}
            LIMIT 1
            """
        )
        return rows[0] if rows else None

    def _upstream_starved(self, network_id: Optional[int]) -> List[Dict[str, Any]]:
        """no_fuel entities on the same network (generator starvation)."""
        if network_id is None:
            return []
        return self.query(
            f"""
            SELECT es.entity_name, es.position_x AS x, es.position_y AS y
            FROM entity_status es
            JOIN map_entity me
              ON es.entity_name = me.entity_name
             AND es.position_x = me.position_x
             AND es.position_y = me.position_y
            WHERE me.electric_network_id = {int(network_id)}
              AND es.status_name = 'no_fuel'
            LIMIT 5
            """
        )

    def diagnose_power(
        self,
        entity_name: str,
        position: Any,
        as_of_tick: Optional[int] = None,
    ) -> PowerDiagnosis:
        """Diagnose why an entity is unpowered (or confirm it is fine).

        Encodes the manual power-diagnosis walk (status → pole coverage →
        network generation → undersupply → upstream starvation) as one call.
        Map-wide reads only (entity_status, map_entity, power_networks) — lives
        on RemoteView because that is exactly the data it needs.

        Walk:
          1. Locate the entity in map_entity (name + position). Absent →
             'entity_not_found'.
          2. Read its status from entity_status. No status row → 'no_status_data'
             (or 'non_electric_or_no_issue' for a pole, which reports nil status).
          3. status 'working' → 'working' (with the caveat that a starved
             producer also reports 'working').
          4. status 'no_power': is any pole's supply area covering it? No →
             'not_covered_by_any_pole'. Covered but the network has no
             generation → 'network_has_no_generation'; a no_fuel member on the
             network → 'upstream_generator_starved'.
          5. status 'low_power' → 'network_undersupplied' (production vs
             consumption), or 'upstream_generator_starved' if a generator is
             starved.

        Caveat (documented in the explanation where it applies): Factorio
        reports a single status per entity, so a low_power condition can be
        masked behind a logistics status; the network wattages are the ground
        truth. The entity_status × map_entity join uses map_entity's as-of-write
        electric_network_id.

        Args:
            entity_name: Factorio entity name.
            position: MapPosition, {'x','y'} dict, or (x, y) tuple.
            as_of_tick: Read this power sample instead of the latest.

        Returns:
            PowerDiagnosis with a ``verdict``, human-readable ``explanation``,
            and the supporting numbers.

        Example:
            >>> diag = remote_view.diagnose_power("assembling-machine-1", pos)
            >>> print(diag.verdict, diag.explanation)
        """
        from FactoryVerse.game.agent.placement_hints import ELECTRIC_POLE_ENTITIES

        self._ensure_query_ready()
        x, y = self._pos_xy(position)
        pos_dict = {"x": x, "y": y}
        sample_tick = self._latest_power_tick(as_of_tick)

        def _mk(verdict: str, explanation: str, **kw: Any) -> PowerDiagnosis:
            return PowerDiagnosis(
                verdict=verdict,
                explanation=explanation,
                entity_name=entity_name,
                position=pos_dict,
                sample_tick=sample_tick,
                **kw,
            )

        me_rows = self.query(
            f"""
            SELECT entity_name, position_x, position_y, electric_network_id
            FROM map_entity
            WHERE entity_name = '{entity_name}'
              AND position_x BETWEEN {x - 0.6} AND {x + 0.6}
              AND position_y BETWEEN {y - 0.6} AND {y + 0.6}
            LIMIT 1
            """
        )
        if not me_rows:
            return _mk(
                "entity_not_found",
                f"No entity '{entity_name}' near ({x}, {y}) in map_entity. It may "
                f"never have been placed, or the map view is stale.",
            )
        entity_nid = me_rows[0]["electric_network_id"]

        st_rows = self.query(
            f"""
            SELECT status_name FROM entity_status
            WHERE entity_name = '{entity_name}'
              AND position_x BETWEEN {x - 0.6} AND {x + 0.6}
              AND position_y BETWEEN {y - 0.6} AND {y + 0.6}
            LIMIT 1
            """
        )
        status = st_rows[0]["status_name"] if st_rows else None

        net = self._network_at_tick(entity_nid, sample_tick) if sample_tick is not None else None
        prod = float(net["production_w"] or 0.0) if net else None
        cons = float(net["consumption_w"] or 0.0) if net else None
        starved = self._upstream_starved(entity_nid)

        def _net_fields() -> Dict[str, Any]:
            return {"network_id": entity_nid, "production_w": prod, "consumption_w": cons}

        # -- no status row -----------------------------------------------------
        if status is None:
            if entity_name in ELECTRIC_POLE_ENTITIES:
                return _mk(
                    "non_electric_or_no_issue",
                    f"'{entity_name}' is an electric pole, which reports no Factorio "
                    f"status (nil-status); poles are never in entity_status. Read the "
                    f"network's power flow in power_networks / get_power_networks().",
                    **_net_fields(),
                )
            return _mk(
                "no_status_data",
                f"No status row for '{entity_name}' at ({x}, {y}) in the latest "
                f"status dump — the status feed may be stale or the entity is not in "
                f"the tracked set. Cannot diagnose power without a status.",
                **_net_fields(),
            )

        # -- working -----------------------------------------------------------
        if status == "working":
            return _mk(
                "working",
                f"'{entity_name}' reports 'working'. Caveat: a starved producer "
                f"(e.g. a boiler/generator out of fuel) also reports 'working', and "
                f"Factorio's single-valued status can mask a low_power condition — if "
                f"output looks low, cross-check the network wattages.",
                status_name=status,
                **_net_fields(),
            )

        # -- no_power ----------------------------------------------------------
        if status == "no_power":
            covering = self._find_covering_pole(x, y)
            if covering is None:
                return _mk(
                    "not_covered_by_any_pole",
                    f"'{entity_name}' is no_power and no electric pole's supply area "
                    f"covers ({x}, {y}). Place a pole within supply range.",
                    status_name=status,
                    **_net_fields(),
                )
            cov_nid = covering["electric_network_id"]
            cov_pos = {"x": covering["position_x"], "y": covering["position_y"]}
            cov_net = self._network_at_tick(cov_nid, sample_tick) if sample_tick is not None else None
            cov_prod = float(cov_net["production_w"] or 0.0) if cov_net else 0.0
            cov_cons = float(cov_net["consumption_w"] or 0.0) if cov_net else 0.0
            cov_starved = self._upstream_starved(cov_nid)
            common = dict(
                status_name=status,
                network_id=cov_nid,
                production_w=cov_prod,
                consumption_w=cov_cons,
                covering_pole_name=covering["entity_name"],
                covering_pole_position=cov_pos,
            )
            if cov_starved:
                names = ", ".join(sorted({s["entity_name"] for s in cov_starved}))
                return _mk(
                    "upstream_generator_starved",
                    f"'{entity_name}' is no_power. It is covered by "
                    f"{covering['entity_name']} at ({cov_pos['x']}, {cov_pos['y']}), but "
                    f"a producer on that network is out of fuel ({names}), so the "
                    f"network produces {cov_prod:.0f}W. Note: a fuel-starved generator "
                    f"still reports 'working' — check its fuel inventory, not its status.",
                    **common,
                )
            if cov_prod <= 0.0:
                return _mk(
                    "network_has_no_generation",
                    f"'{entity_name}' is no_power. It is covered by "
                    f"{covering['entity_name']} at ({cov_pos['x']}, {cov_pos['y']}), but "
                    f"that pole's network produces {cov_prod:.0f}W — there is no "
                    f"generator feeding it (or the generator is off/disconnected).",
                    **common,
                )
            # Covered, network has generation, not starved — likely a just-merged
            # network whose as-of-write membership still lags, or a transient.
            return _mk(
                "network_undersupplied",
                f"'{entity_name}' is no_power despite being covered by "
                f"{covering['entity_name']} whose network produces {cov_prod:.0f}W for "
                f"{cov_cons:.0f}W of load. The pole membership (electric_network_id) is "
                f"as-of last entity write and may lag a recent merge/split; re-check "
                f"after the next sample.",
                **common,
            )

        # -- low_power ---------------------------------------------------------
        if status == "low_power":
            if starved:
                names = ", ".join(sorted({s["entity_name"] for s in starved}))
                return _mk(
                    "upstream_generator_starved",
                    f"'{entity_name}' is low_power and a producer on its network is out "
                    f"of fuel ({names}). A fuel-starved generator still reports "
                    f"'working' — check its fuel inventory.",
                    status_name=status,
                    **_net_fields(),
                )
            p = prod if prod is not None else 0.0
            c = cons if cons is not None else 0.0
            ratio = f"{(p / c):.2f}" if c > 0 else "n/a"
            return _mk(
                "network_undersupplied",
                f"'{entity_name}' is low_power: its network produces {p:.0f}W for "
                f"{c:.0f}W of demand (headroom {ratio}). Add generation or reduce load.",
                status_name=status,
                **_net_fields(),
            )

        # -- any other status --------------------------------------------------
        if prod is not None and cons is not None and cons > 0 and prod < cons:
            return _mk(
                "network_undersupplied",
                f"'{entity_name}' reports '{status}', but its network is undersupplied "
                f"({prod:.0f}W produced for {cons:.0f}W demand). Factorio reports a "
                f"single status per entity, so a low_power condition can be masked "
                f"behind this logistics status — the network wattages are the ground "
                f"truth.",
                status_name=status,
                **_net_fields(),
            )
        return _mk(
            "non_electric_or_no_issue",
            f"'{entity_name}' reports '{status}' and its network shows no power "
            f"shortfall; any problem is not power-related.",
            status_name=status,
            **_net_fields(),
        )

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

    def state_fingerprint(self) -> Dict[str, Any]:
        """Return a compact, deterministic identity digest for restore checks.

        The digest intentionally covers entity identity and placement rather
        than volatile inventories or resource amounts, which may legitimately
        change while a continuously-running freeplay server resumes.
        """
        if not self._loaded:
            raise RuntimeError("RemoteView not loaded. Call load() first.")

        if self._sync:
            self._sync.flush_pending()

        with self._db_lock:
            row = self._database.connection.execute(
                """
                SELECT
                    count(*) AS entity_count,
                    coalesce(
                        bit_xor(hash(
                            entity_name,
                            position_x,
                            position_y,
                            coalesce(direction, ''),
                            coalesce(force, '')
                        )),
                        0
                    ) AS entity_digest
                FROM map_entity
                """
            ).fetchone()
            sequence = self._database.get_last_sequence()

        return {
            "entity_count": int(row[0] if row else 0),
            "entity_digest": str(row[1] if row else 0),
            "last_sequence": int(sequence),
        }

    def checkpoint_database(self, destination: Path) -> Path:
        """Create a consistent DuckDB evidence copy at ``destination``.

        The live database may be in-memory. DuckDB's database-to-database copy
        runs while the RemoteView write lock is held, so checkpoint evidence
        cannot interleave with pending UDP updates.
        """
        if not self._loaded:
            raise RuntimeError("RemoteView not loaded. Call load() first.")

        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(f"Checkpoint database already exists: {destination}")

        if self._sync:
            self._sync.flush_pending()

        escaped_path = str(destination).replace("'", "''")
        with self._db_lock:
            connection = self._database.connection
            source_name = str(connection.execute("SELECT current_database()").fetchone()[0])
            quoted_source = '"' + source_name.replace('"', '""') + '"'
            source_tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT table_name FROM duckdb_tables() "
                    "WHERE database_name = ? AND schema_name = 'main'",
                    [source_name],
                ).fetchall()
            }
            if not source_tables:
                raise RuntimeError("Live RemoteView database has no tables to checkpoint")
            database_paths = {
                str(row[1]): str(row[2] or "")
                for row in connection.execute("PRAGMA database_list").fetchall()
            }
            source_path = database_paths.get(source_name, "")

            if source_path:
                # Production eval databases are file-backed.  While the
                # RemoteView lock excludes writers, checkpoint the live WAL
                # into its main file and copy that immutable image.  This is
                # more reliable than attaching a second file to a connection
                # that is simultaneously serving live-sync queries.
                connection.execute(f"CHECKPOINT {quoted_source}").fetchall()
                shutil.copy2(source_path, destination)
            else:
                # Unit/in-memory runtimes have no source file, so use DuckDB's
                # database-to-database copy and fully consume DETACH.
                connection.execute(f"ATTACH '{escaped_path}' AS fv_checkpoint").fetchall()
                try:
                    connection.execute(
                        f"COPY FROM DATABASE {quoted_source} TO fv_checkpoint"
                    ).fetchall()
                    copied_tables = {
                        str(row[0])
                        for row in connection.execute(
                            "SELECT table_name FROM duckdb_tables() "
                            "WHERE database_name = 'fv_checkpoint' "
                            "AND schema_name = 'main'"
                        ).fetchall()
                    }
                    if copied_tables != source_tables:
                        missing = sorted(source_tables - copied_tables)
                        extra = sorted(copied_tables - source_tables)
                        raise RuntimeError(
                            "DuckDB checkpoint schema verification failed "
                            f"(missing={missing}, extra={extra})"
                        )
                    connection.execute("CHECKPOINT fv_checkpoint").fetchall()
                finally:
                    connection.execute("DETACH fv_checkpoint").fetchall()

        # Verify the detached file using a fresh connection.  This catches a
        # superficially non-empty 12 KiB DuckDB catalog with no copied schema,
        # which is not valid checkpoint evidence.
        import duckdb

        with duckdb.connect(str(destination), read_only=True) as verification:
            detached_tables = {
                str(row[0])
                for row in verification.execute(
                    "SELECT table_name FROM duckdb_tables() "
                    "WHERE schema_name = 'main'"
                ).fetchall()
            }
        if detached_tables != source_tables:
            raise RuntimeError(
                "Detached DuckDB checkpoint failed verification: "
                f"expected {len(source_tables)} tables, found {len(detached_tables)}"
            )

        return destination

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

    def _current_game_tick(self) -> Optional[int]:
        """Current game tick via RCON, or None if unavailable.

        Used as the loader's future-tick guard (CELL-2a): init files /
        update records with tick > now are previous-boot leftovers.
        None disables the guard (old behavior) rather than failing the load.
        """
        if self._rcon_client is None:
            return None
        try:
            result = self._rcon_client.send_command("/c rcon.print(game.tick)")
            return int(result.strip()) if result and result.strip() else None
        except Exception as e:
            logger.warning(f"Could not fetch game tick for load guard: {e}")
            return None

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


__all__ = [
    "RemoteView",
    "PowerNetworkCensus",
    "PowerNetworksReport",
    "PowerDiagnosis",
]
