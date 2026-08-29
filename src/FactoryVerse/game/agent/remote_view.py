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
import math
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
from FactoryVerse.game.agent.status_dump import StatusBlock, StatusChange, StatusDumpReader
from FactoryVerse.game.agent.power_dump import PowerDumpReader, PowerSample

# MINE-BLOCK-1: the two tables natural resources live in. Trees and rocks are
# entities; ore deposits are tiles whose amount decrements as they are mined.
# Any causal proof about a mined resource must name the right one.
RESOURCE_ENTITY_TABLE = "resource_entity"
RESOURCE_TILE_TABLE = "resource_tile"

logger = logging.getLogger(__name__)


# =============================================================================
# Power UX typed results (WS4)
# =============================================================================


@dataclass
class PowerNetworkCensus:
    """One live electric network from the latest power sample.

    Returned inside :class:`PowerNetworksReport` by :meth:`RemoteView.power`.
    The durable per-network reference is the anchor pole (``anchor_pole_name``
    + ``anchor_pole_position``); the engine ``network_id`` is a per-sample
    handle only (it renumbers on merge/split).

    ``low_power_count`` / ``no_power_count`` come from the newest status dump
    (``status_dump:<tick>``) joined to map_entity on (name, position) to
    recover each entity's ``electric_network_id``. That id is AS-OF the last
    entity write, not the sample instant, so on a network that just
    merged/split the counts can lag the wattages by up to one entity-write
    cycle.
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
    exists on disk yet. ``freshness_note`` documents the sample's age and the
    as-of-write staleness of the status join. ``source`` names the sample
    block this was read from (``power_dump:<tick>``) and ``status_source`` the
    status block (``status_dump:<tick>``) — Constitution §11: a read that can
    draw from either half of the map surface says which it used.
    """

    networks: List[PowerNetworkCensus]
    sample_tick: Optional[int]
    freshness_note: str
    source: str = "power_dump:none"
    status_source: str = "status_dump:none"
    # DIGEST-2: no_power entities that attribute to NO network (their
    # electric_network_id is nil — e.g. not covered by any pole, the sickest
    # case). They appear in the status dump/diagnose_power but in no network's
    # per-net counts, so without this field the report (and the Task Progress
    # digest built from it) under-reports exactly the machines that are worst
    # off. Network-independent count, straight from the status dump.
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



@dataclass(frozen=True)
class StatusGroup:
    """One status value seen across the base: how many, and roughly where."""

    status: str
    count: int
    entities: List[Tuple[str, float, float]]  # (name, x, y), at most the requested number
    more: int  # entities beyond the ones listed


@dataclass
class StatusSummary:
    """The base-wide status read — the per-entity fact seen at scale.

    Built from the newest status dump block on disk (``source`` =
    ``status_dump:<tick>``), never from a database table: entity status has no
    event backing (Constitution §10), so it is read on demand and stamped with
    the block it came from (§11). ``age_ticks`` is how far the world has moved
    since that block, when the current tick is readable; None otherwise.
    """

    tick: Optional[int]
    source: str
    groups: Dict[str, StatusGroup]
    total: int
    age_ticks: Optional[int] = None

    def count(self, status: str) -> int:
        group = self.groups.get(status)
        return group.count if group else 0


@dataclass
class ProductionReport:
    """Force production plus this agent's hand-crafted/hand-mined counts.

    ``produced``/``consumed`` are the force's cumulative item production
    statistics, read live over RCON (``source`` = ``live:<tick>``) — a polled
    engine counter that is never stored in the map model. ``hand_crafted`` and
    ``hand_mined`` come from the agent's event-driven crafting/mining records
    (``agent_manual_production_statistics``), which are lawfully in the
    database. Automated production is ``produced`` minus ``hand_crafted``.
    """

    tick: Optional[int]
    source: str
    produced: Dict[str, int]
    consumed: Dict[str, int]
    hand_crafted: Dict[str, int]
    hand_mined: Dict[str, int]
    agent_id: Optional[int] = None

    def automated(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for name, count in self.produced.items():
            auto = int(count) - int(self.hand_crafted.get(name, 0)) - int(self.hand_mined.get(name, 0))
            if auto > 0:
                out[name] = auto
        return out


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
        # On-demand readers over the dump files (Constitution §10/§11): status
        # and power are polled simulation state and never enter the database.
        self._status_reader: Optional[StatusDumpReader] = None
        self._power_reader: Optional[PowerDumpReader] = None
        self._agent_id: Optional[int] = None
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
                # carried by file_io UDP payloads (trees/rocks chunk rewrites,
                # agent crafting/mining records).
                snapshot_dir=self._snapshot_dir,
            )
        else:
            self._sync = None

        # Initialize components
        self._loader = SnapshotLoader(
            self._database.connection,
            self._snapshot_dir,
        )

        # NOTE: entity status and power flow are NOT tables. They are read on
        # demand from the dump files through self._status_dump() /
        # self._power_dump() (Constitution §10: no event backs them).
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

    def capture_resource_depletion_baseline(
        self,
        entity_name: str,
        position_x: float,
        position_y: float,
    ) -> Dict[str, Any]:
        """Capture pre-action row presence and the entity-event sequence floor.

        MINE-BLOCK-1: natural resources live in two tables. Trees and rocks are
        rows in ``resource_entity``; ore deposits are rows in ``resource_tile``.
        This baseline used to query ``resource_entity`` unconditionally, so an
        ore target could never be proven to exist, ``resource_rows_at_start``
        came back 0, and every attempt to hand-mine ore was rejected before it
        began — while trees mined normally. The barrier that exists to keep
        mining honest was making the game's most basic action impossible.

        The lookup now follows the resource to whichever table holds it and
        reports that table, so the post-completion wait proves depletion
        against the same rows this baseline measured.
        """
        if not self._loaded:
            raise RuntimeError("RemoteView not loaded. Call load() first.")

        if self._sync:
            self._sync.flush_pending()

        located = self._locate_resource_row(
            entity_name, float(position_x), float(position_y)
        )
        resource_table, row_x, row_y, rows_at_start = located

        baseline: Dict[str, Any] = {
            "resource_rows_at_start": rows_at_start,
            "resource_table": resource_table,
            # The coordinates that actually identify the row, which are not
            # always the coordinates the caller passed (see _locate_resource_row).
            "resource_position_x": row_x,
            "resource_position_y": row_y,
            "entity_sequence_floor": (
                self._sync.get_entity_sequence() if self._sync else None
            ),
        }

        # An ore tile is not consumed by a single mine() — its amount
        # decrements and the row survives until exhausted. Record the starting
        # amount so a partial mine has something to reconcile against; the
        # row-removal proof below still governs the depleted case.
        if resource_table == RESOURCE_TILE_TABLE and rows_at_start:
            with self._db_lock:
                amount = self._database.connection.execute(
                    f"""
                    SELECT amount FROM {RESOURCE_TILE_TABLE}
                    WHERE name = ? AND position_x = ? AND position_y = ?
                    """,
                    [entity_name, row_x, row_y],
                ).fetchone()
            baseline["resource_amount_at_start"] = amount[0] if amount else None

        return baseline

    def _locate_resource_row(
        self, entity_name: str, position_x: float, position_y: float
    ) -> Tuple[str, float, float, int]:
        """Find which table and which coordinates identify this resource.

        Two conventions meet here, and mismatching them is invisible until a
        causal proof silently finds nothing:

        * ``resource_entity`` (trees, rocks) stores exact entity positions.
        * ``resource_tile`` (ore) stores **integer tile coordinates**, while the
          Factorio resource entities themselves live at tile *centres*. The
          query layer adds 0.5 when it hydrates a typed resource, so a position
          that came back from the engine — or from a hydrated resource object —
          is a centre and can never equal the stored integer.

        Returns the table, the coordinates that actually match a row, and the
        row count. A miss returns the entity table with the caller's own
        coordinates and a count of 0, which is what the barrier rejects on.
        """

        def _count(table: str, x: float, y: float) -> int:
            with self._db_lock:
                return self._database.connection.execute(
                    f"""
                    SELECT count(*) FROM {table}
                    WHERE name = ? AND position_x = ? AND position_y = ?
                    """,
                    [entity_name, x, y],
                ).fetchone()[0]

        entity_rows = _count(RESOURCE_ENTITY_TABLE, position_x, position_y)
        if entity_rows:
            return (RESOURCE_ENTITY_TABLE, position_x, position_y, entity_rows)

        # Exact first (a caller may already hold tile coordinates), then the
        # centre-to-tile conversion. floor() is the exact inverse of the +0.5
        # the query layer applies, and is a no-op on a coordinate that is
        # already a tile index.
        for x, y in (
            (position_x, position_y),
            (float(math.floor(position_x)), float(math.floor(position_y))),
        ):
            tile_rows = _count(RESOURCE_TILE_TABLE, x, y)
            if tile_rows:
                return (RESOURCE_TILE_TABLE, x, y, tile_rows)

        return (RESOURCE_ENTITY_TABLE, position_x, position_y, 0)

    async def wait_for_resource_depletion(
        self,
        entity_name: str,
        position_x: float,
        position_y: float,
        timeout: float = 5.0,
        *,
        expected_destroy_tick: Optional[int] = None,
        expected_action_id: Optional[str] = None,
        baseline: Optional[Dict[str, Any]] = None,
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
        # MINE-BLOCK-1: prove depletion against the same table the baseline
        # measured. Ore lives in resource_tile, trees and rocks in
        # resource_entity; watching the wrong one can never observe the removal.
        resource_table = (baseline or {}).get("resource_table") or RESOURCE_ENTITY_TABLE
        if resource_table not in (RESOURCE_ENTITY_TABLE, RESOURCE_TILE_TABLE):
            raise ValueError(f"Unknown resource table: {resource_table!r}")
        # Watch the row the baseline actually measured. An ore tile is stored
        # at integer coordinates while the caller holds a tile centre, so
        # reusing the caller's numbers here would watch a row that never
        # existed and time out on a resource that really did deplete.
        row_x = (baseline or {}).get("resource_position_x")
        row_y = (baseline or {}).get("resource_position_y")
        if row_x is None or row_y is None:
            row_x, row_y = float(position_x), float(position_y)
        while True:
            if self._sync:
                self._sync.flush_pending()
            with self._db_lock:
                remaining = self._database.connection.execute(
                    f"""
                    SELECT count(*) FROM {resource_table}
                    WHERE name = ? AND position_x = ? AND position_y = ?
                    """,
                    [entity_name, float(row_x), float(row_y)],
                ).fetchone()[0]
            if remaining == 0:
                removal_fact = (
                    self._sync.get_applied_resource_removal(
                        entity_name, float(position_x), float(position_y)
                    )
                    if self._sync
                    else None
                )
                if removal_fact:
                    if expected_destroy_tick is None:
                        # Backward-compatible internal use without a captured
                        # causal baseline. Tier 4 always supplies the strict
                        # action-bound arguments below.
                        removed = removal_fact.get(
                            "duckdb_rows_removed",
                            removal_fact.get("remove_payload_rows_removed"),
                        )
                        if removed == 1:
                            return removal_fact
                    else:
                        baseline = baseline or {}
                        source_tick = removal_fact.get(
                            "snapshot_destroy_event_tick",
                            removal_fact.get("destroy_event_tick"),
                        )
                        sequence = removal_fact.get("destroy_event_sequence")
                        sequence_floor = baseline.get("entity_sequence_floor")
                        action_id = removal_fact.get("destroy_action_id")
                        action_matches = (
                            expected_action_id is None
                            or action_id == expected_action_id
                        )
                        sequence_is_newer = (
                            isinstance(sequence, int)
                            and isinstance(sequence_floor, int)
                            and sequence > sequence_floor
                        )
                        if (
                            baseline.get("resource_rows_at_start") == 1
                            and source_tick == expected_destroy_tick
                            and action_matches
                            and sequence_is_newer
                        ):
                            facts = dict(removal_fact)
                            facts["resource_present_at_action_start"] = True
                            facts["entity_sequence_floor"] = sequence_floor
                            # This is the net transition proven by the barrier.
                            # The exact reducer's own count remains available as
                            # remove_payload_rows_removed (and may be zero when
                            # a full-chunk rewrite arrived first).
                            facts["duckdb_rows_removed"] = 1
                            return facts
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
        ``entity_reference("offshore-pump").sites(near=...)`` around one of these tiles
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

    # -------------------------------------------------------------------------
    # Dump readers (Constitution §10/§11): status and power are read on demand
    # -------------------------------------------------------------------------

    def _script_output_root(self) -> Path:
        """The script-output root, whichever of the two conventions
        ``snapshot_dir`` follows (the root, or ``<root>/factoryverse/snapshots``)."""
        root = self._snapshot_dir
        if root.name == "snapshots" and root.parent.name == "factoryverse":
            return root.parent.parent
        if root.name == "factoryverse":
            return root.parent
        return root

    def _status_dump(self) -> StatusDumpReader:
        """The on-demand status dump reader (harness plumbing, not an affordance)."""
        if self._status_reader is None:
            self._status_reader = StatusDumpReader(
                self._script_output_root() / "factoryverse" / "status"
            )
        return self._status_reader

    def _power_dump(self) -> PowerDumpReader:
        """The on-demand power sample reader (harness plumbing, not an affordance)."""
        if self._power_reader is None:
            self._power_reader = PowerDumpReader(
                self._script_output_root() / "factoryverse" / "snapshots" / "power_networks.jsonl"
            )
        return self._power_reader

    def set_agent_id(self, agent_id: Optional[int]) -> None:
        """Tell the view which agent's force to read production for."""
        self._agent_id = int(agent_id) if agent_id is not None else None

    def _power_sample(self, as_of_tick: Optional[int]) -> Optional[PowerSample]:
        if as_of_tick is None:
            return self._power_dump().newest()
        return self._power_dump().at_or_before(int(as_of_tick))

    def _network_ids_by_entity(self) -> Dict[Tuple[str, float, float], Optional[int]]:
        """map_entity's as-of-write electric_network_id keyed by (name, x, y)."""
        rows = self.query(
            "SELECT entity_name, position_x, position_y, electric_network_id "
            "FROM map_entity WHERE electric_network_id IS NOT NULL"
        )
        return {
            (str(r["entity_name"]), float(r["position_x"]), float(r["position_y"])): r["electric_network_id"]
            for r in rows
        }

    @staticmethod
    def _status_of(block: Optional[StatusBlock], entity_name: str, x: float, y: float) -> Optional[str]:
        """The entity's status in ``block`` (exact key, then a ±0.6 tolerance)."""
        if block is None:
            return None
        exact = block.records.get((entity_name, float(x), float(y)))
        if exact is not None:
            return exact
        for (name, ex, ey), status in block.records.items():
            if name == entity_name and abs(ex - x) <= 0.6 and abs(ey - y) <= 0.6:
                return status
        return None

    def _upstream_starved(
        self,
        block: Optional[StatusBlock],
        network_id: Optional[int],
        nid_map: Dict[Tuple[str, float, float], Optional[int]],
    ) -> List[Dict[str, Any]]:
        """no_fuel entities on the same network (generator starvation)."""
        if network_id is None or block is None:
            return []
        out: List[Dict[str, Any]] = []
        for key, status in block.records.items():
            if status == "no_fuel" and nid_map.get(key) == network_id:
                out.append({"entity_name": key[0], "x": key[1], "y": key[2]})
                if len(out) >= 5:
                    break
        return out

    def status(self, max_positions: int = 5, statuses: Optional[List[str]] = None) -> StatusSummary:
        """The base-wide status summary — which problem, how many, roughly where.

        Reads the newest status dump block on disk (``source`` says which);
        groups every tracked entity by its status value and lists up to
        ``max_positions`` (name, x, y) per group with the remainder counted.
        This is the per-entity ``status`` read seen at scale: it is what a
        person gets by looking at their factory instead of at one machine.

        Args:
            max_positions: positions listed per status group (the rest is a count).
            statuses: restrict to these status names (e.g. ["no_power", "no_fuel"]).

        Returns:
            StatusSummary. ``tick`` is None and ``groups`` empty when no dump
            exists yet — different from "everything is working".

        Example:
            >>> summary = remote_view.status(statuses=["no_power", "no_fuel", "low_power"])
            >>> for name, group in summary.groups.items():
            ...     print(name, group.count, group.entities[:3])
            >>> print(summary.source, summary.age_ticks)
        """
        block = self._status_dump().current()
        if block is None:
            return StatusSummary(tick=None, source="status_dump:none", groups={}, total=0)
        wanted = set(statuses) if statuses else None
        groups: Dict[str, StatusGroup] = {}
        for status_name, keys in sorted(block.grouped().items()):
            if wanted is not None and status_name not in wanted:
                continue
            groups[status_name] = StatusGroup(
                status=status_name,
                count=len(keys),
                entities=list(keys[: max(0, int(max_positions))]),
                more=max(0, len(keys) - int(max_positions)),
            )
        now = self._current_game_tick()
        age = (int(now) - block.tick) if now is not None else None
        return StatusSummary(
            tick=block.tick,
            source=block.source,
            groups=groups,
            total=len(block.records),
            age_ticks=age,
        )

    def status_changed(self, since_tick: int) -> StatusChange:
        """Status transitions since ``since_tick`` — what became unhappy, what recovered.

        Diffs the newest dump block at or before ``since_tick`` against the
        newest block; ``source`` names both (``status_dump:<from>-><to>``).
        Grouped by ``before -> after`` through ``.grouped()``.

        Example:
            >>> change = remote_view.status_changed(since_tick=turn_start_tick)
            >>> for label, transitions in change.grouped().items():
            ...     print(label, len(transitions), transitions[0].entity)
        """
        return self._status_dump().changed(int(since_tick))

    def power(self, as_of_tick: Optional[int] = None) -> PowerNetworksReport:
        """Per-network power census from the newest power sample on disk.

        Reads ``power_networks.jsonl`` (the 300-tick sampler) and, for each live
        electric network, returns its anchor pole, pole / member counts,
        production / consumption / storage, a headroom ratio (production /
        consumption; None when consumption is 0), the per-prototype breakdowns,
        and the count of low_power / no_power entities on that network from
        the newest status dump. ``source`` and ``status_source`` say exactly
        which blocks were read; ``freshness_note`` says how they relate.

        The low_power/no_power counts join the status dump to map_entity on
        (name, position) to recover each entity's electric_network_id, which
        is AS OF the last entity write — on a network that just merged/split
        the counts can lag the wattages by one entity-write cycle.

        Args:
            as_of_tick: Read the newest sample at or before this tick instead.

        Returns:
            PowerNetworksReport. ``sample_tick`` is None (and ``networks`` empty)
            when no sample exists at all (or none at/before ``as_of_tick``).

        Example:
            >>> report = remote_view.power()
            >>> for net in report.networks:
            ...     print(net.anchor_pole_name, net.production_w, net.consumption_w)
            >>> print(report.source, report.freshness_note)
        """
        self._ensure_query_ready()
        sample = self._power_sample(as_of_tick)
        if sample is None:
            what = "no power sample on disk yet" if as_of_tick is None else f"no power sample at or before tick {int(as_of_tick)}"
            return PowerNetworksReport(
                networks=[],
                sample_tick=None,
                freshness_note=f"{what} — the sampler has not written, which is different from 'no networks'",
            )

        block = self._status_dump().current()
        nid_map = self._network_ids_by_entity() if block is not None else {}
        counts: Dict[Any, List[int]] = {}
        unattributed = 0
        if block is not None:
            for key, status_name in block.records.items():
                if status_name not in ("low_power", "no_power"):
                    continue
                nid = nid_map.get(key)
                if nid is None:
                    if status_name == "no_power":
                        unattributed += 1
                    continue
                bucket = counts.setdefault(nid, [0, 0])
                bucket[0 if status_name == "low_power" else 1] += 1

        def _anchor_xy(net: Dict[str, Any]) -> Tuple[float, float, Any]:
            pos = (net.get("anchor_pole") or {}).get("position") or {}
            return (float(pos.get("x", math.inf)), float(pos.get("y", math.inf)), net.get("network_id"))

        networks: List[PowerNetworkCensus] = []
        for net in sorted(sample.networks, key=_anchor_xy):
            anchor = net.get("anchor_pole") or {}
            anchor_pos = anchor.get("position") or None
            prod = float(net.get("production_w") or 0.0)
            cons = float(net.get("consumption_w") or 0.0)
            low, no = counts.get(net.get("network_id"), [0, 0])
            networks.append(
                PowerNetworkCensus(
                    network_id=net.get("network_id"),
                    anchor_pole_name=anchor.get("name"),
                    anchor_pole_position={"x": anchor_pos["x"], "y": anchor_pos["y"]} if anchor_pos else None,
                    pole_count=int(net.get("pole_count") or 0),
                    member_count=int(net.get("member_count") or 0),
                    production_w=prod,
                    consumption_w=cons,
                    storage_j=float(net.get("storage_j") or 0.0),
                    headroom_ratio=(prod / cons) if cons > 0 else None,
                    production_by_prototype=dict(net.get("production_w_by_prototype") or {}),
                    consumption_by_prototype=dict(net.get("consumption_w_by_prototype") or {}),
                    low_power_count=int(low),
                    no_power_count=int(no),
                    sample_tick=sample.tick,
                )
            )

        parts = [f"power sample at tick {sample.tick} ({sample.source})"]
        newest = self._power_dump().newest()
        if newest is not None and newest.tick != sample.tick:
            parts.append(f"newest sample is tick {newest.tick} (Δ{newest.tick - sample.tick} ticks)")
        if block is not None:
            parts.append(
                f"low_power/no_power counts from {block.source} (Δ{block.tick - sample.tick} vs sample) "
                f"using map_entity.electric_network_id which is as-of last entity write — "
                f"membership can lag on a just-merged/split network"
            )
        else:
            parts.append("no status dump on disk yet — low_power/no_power counts are 0")
        return PowerNetworksReport(
            networks=networks,
            sample_tick=sample.tick,
            freshness_note="; ".join(parts),
            source=sample.source,
            status_source=block.source if block is not None else "status_dump:none",
            unattributed_no_power=unattributed,
        )

    def get_power_networks(self, as_of_tick: Optional[int] = None) -> PowerNetworksReport:
        """Alias of :meth:`power` kept for existing callers; prefer ``power()``."""
        return self.power(as_of_tick=as_of_tick)

    def production(self, agent_id: Optional[int] = None) -> ProductionReport:
        """Force production (live) plus this agent's hand-crafted/mined counts.

        ``produced``/``consumed`` are read over RCON at call time
        (``source`` = ``live:<tick>``): the engine's cumulative item production
        statistics for the agent's force. ``hand_crafted``/``hand_mined`` come
        from the event-driven records in ``agent_manual_production_statistics``.
        ``automated()`` is the difference — the one quantity hand-crafting
        cannot inflate.

        Args:
            agent_id: whose force; defaults to the agent this view was built for.

        Returns:
            ProductionReport. ``source`` is ``"unavailable"`` (with empty
            counters) when there is no RCON connection or no agent id.

        Example:
            >>> p = remote_view.production()
            >>> print(p.source, p.automated().get("iron-plate", 0), p.hand_crafted)
        """
        aid = agent_id if agent_id is not None else self._agent_id
        produced: Dict[str, int] = {}
        consumed: Dict[str, int] = {}
        tick: Optional[int] = None
        source = "unavailable"
        if aid is not None and self._rcon_client is not None:
            cmd = (
                f"/silent-command local s = remote.call('agent_{int(aid)}', 'get_production_statistics') or {{}}; "
                f"rcon.print(helpers.table_to_json({{tick = game.tick, input = s.input or {{}}, output = s.output or {{}}}}))"
            )
            try:
                raw = self._rcon_client.send_command(cmd)
                data = json.loads(raw) if raw and raw.strip() else {}
                tick = int(data.get("tick")) if data.get("tick") is not None else None
                produced = {str(k): int(v) for k, v in (data.get("output") or {}).items()} if isinstance(data.get("output"), dict) else {}
                consumed = {str(k): int(v) for k, v in (data.get("input") or {}).items()} if isinstance(data.get("input"), dict) else {}
                source = f"live:{tick}" if tick is not None else "live"
            except Exception as e:  # engine unreachable — say so, never fake it
                logger.warning(f"production read failed: {e}")
                source = "unavailable"
        hand_crafted: Dict[str, int] = {}
        hand_mined: Dict[str, int] = {}
        if aid is not None:
            try:
                self._ensure_query_ready()
                rows = self.query(
                    f"SELECT crafted, mined FROM agent_manual_production_statistics "
                    f"WHERE agent_id = {int(aid)} ORDER BY tick DESC LIMIT 1"
                )
                if rows:
                    hand_crafted = self._parse_json_dict(rows[0]["crafted"])
                    hand_mined = self._parse_json_dict(rows[0]["mined"])
            except Exception as e:
                logger.debug(f"manual production read failed: {e}")
        return ProductionReport(
            tick=tick,
            source=source,
            produced=produced,
            consumed=consumed,
            hand_crafted={k: int(v) for k, v in hand_crafted.items()},
            hand_mined={k: int(v) for k, v in hand_mined.items()},
            agent_id=aid,
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

    def diagnose_power(
        self,
        entity_name: str,
        position: Any,
        as_of_tick: Optional[int] = None,
    ) -> PowerDiagnosis:
        """Diagnose why an entity is unpowered (or confirm it is fine).

        Encodes the manual power-diagnosis walk (status → pole coverage →
        network generation → undersupply → upstream starvation) as one call.
        Map-wide reads only (the status dump, map_entity, the power sample) —
        lives on RemoteView because that is exactly the data it needs; the
        diagnosis names its sources (``sample_tick``; the status dump is the
        newest block, see ``remote_view.status().source``).

        Walk:
          1. Locate the entity in map_entity (name + position). Absent →
             'entity_not_found'.
          2. Read its status from the newest status dump. No record → 'no_status_data'
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
        truth. The status-dump × map_entity join uses map_entity's as-of-write
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
        sample = self._power_sample(as_of_tick)
        sample_tick = sample.tick if sample is not None else None
        block = self._status_dump().current()
        nid_map = self._network_ids_by_entity()

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

        status = self._status_of(block, entity_name, x, y)

        net = sample.network(entity_nid) if sample is not None else None
        prod = float(net.get("production_w") or 0.0) if net else None
        cons = float(net.get("consumption_w") or 0.0) if net else None
        starved = self._upstream_starved(block, entity_nid, nid_map)

        def _net_fields() -> Dict[str, Any]:
            return {"network_id": entity_nid, "production_w": prod, "consumption_w": cons}

        # -- no status row -----------------------------------------------------
        if status is None:
            if entity_name in ELECTRIC_POLE_ENTITIES:
                return _mk(
                    "non_electric_or_no_issue",
                    f"'{entity_name}' is an electric pole, which reports no Factorio "
                    f"status (nil-status); poles are never in the status dump. Read the "
                    f"network's power flow with remote_view.power().",
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
            cov_net = sample.network(cov_nid) if sample is not None else None
            cov_prod = float(cov_net.get("production_w") or 0.0) if cov_net else 0.0
            cov_cons = float(cov_net.get("consumption_w") or 0.0) if cov_net else 0.0
            cov_starved = self._upstream_starved(block, cov_nid, nid_map)
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
            # EMPTY = nothing was charted, so there was nothing to snapshot;
            # quiescent like MAINTENANCE (fv_snapshot Map.lua is_quiescent_phase).
            if phase in ("MAINTENANCE", "EMPTY"):
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

                    if status.system_phase in ("MAINTENANCE", "EMPTY"):
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
