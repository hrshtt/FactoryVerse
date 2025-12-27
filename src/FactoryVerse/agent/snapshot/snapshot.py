from enum import Enum
import duckdb
import asyncio
import time
from pathlib import Path
from typing import Optional, Union
from factorio_rcon import RCONClient
from .db.loader import load_all        
from .db.schema import connect

class BootstrapStage(Enum):
    BOOTSTRAP = 1
    MAINTENANCE = 2

class SnapshotHandler:
    _rcon: RCONClient

    def __init__(self, rcon: RCONClient, snapshot_directory: Path):
        self._rcon = rcon
        self._snapshot_directory = snapshot_directory

        if self._snapshot_directory is None:
            raise ValueError(
                f"snapshot_dir required and could not be auto-detected: {e}"
            )

    async def _ensure_game_data_sync(self):
        """Ensure game data sync service is started."""
        if self._game_data_sync and not self._game_data_sync.is_running:
            await self._game_data_sync.start()
    
    async def _stop_game_data_sync(self):
        """Stop game data sync service."""
        if self._game_data_sync and self._game_data_sync.is_running:
            await self._game_data_sync.stop()
    
    async def load_snapshots(
        self,
        snapshot_dir: Optional[Path] = None,
        db_path: Optional[Union[str, Path]] = None,
        prototype_api_file: Optional[str] = None,
        *,
        include_base: bool = True,
        include_components: bool = True,
        include_derived: bool = True,
        include_ghosts: bool = True,
        include_analytics: bool = True,
        replay_updates: bool = True,
        wait_for_initial: bool = True,
        initial_timeout: float = 60.0,
    ) -> None:
        """Load snapshot data into the database (async version).
        
        High-level method that auto-creates connection, schema, and auto-detects
        snapshot directory. This is the primary way to set up the database.
        
        Also initializes and starts GameDataSyncService for real-time sync.
        If wait_for_initial=True, blocks until all charted chunks reach COMPLETE state.
        
        Args:
            snapshot_dir: Path to snapshot directory. If None, auto-detects from
                         Factorio client script-output directory.
            db_path: Optional path to DuckDB database file. If None, uses in-memory.
            prototype_api_file: Optional path to prototype-api.json file
            include_base: Load base tables (water, resources, entities)
            include_components: Load component tables (inserters, belts, etc.)
            include_derived: Load derived tables (patches, belt networks)
            include_ghosts: Load ghost tables
            include_analytics: Load analytics tables (power, agent stats)
            replay_updates: Replay operations logs (entities_updates.jsonl, etc.)
            wait_for_initial: If True, wait for all charted chunks to reach COMPLETE state
            initial_timeout: Maximum time to wait for initial snapshot completion (seconds)
        """
        # Load snapshots synchronously (files on disk)
        snapshot_dir = self._load_snapshots_sync(
            snapshot_dir=snapshot_dir,
            db_path=db_path,
            prototype_api_file=prototype_api_file,
            include_base=include_base,
            include_components=include_components,
            include_derived=include_derived,
            include_ghosts=include_ghosts,
            include_analytics=include_analytics,
            replay_updates=replay_updates,
        )
        
        # Start GameDataSyncService
        await self._ensure_game_data_sync()
        
        # Wait for bootstrap completion if requested
        # This waits for the system to transition from INITIAL_SNAPSHOTTING to MAINTENANCE
        # which respects the bootstrap waiting period for async charting
        if wait_for_initial:
            await self._wait_for_bootstrap_complete(timeout=initial_timeout)
            
            # CRITICAL: Reload all snapshot files from disk after bootstrap completes
            # This ensures we have ALL data that was snapshotted during bootstrap.
            # Without this reload, we'd have a mix of:
            # - Old data from initial load (before bootstrap)
            # - Some new data from UDP file_io events (if they arrived)
            # - Missing data from chunks that completed DURING bootstrap wait
            logger.info("🔄 Bootstrap complete. Reloading all snapshot files to ensure complete data...")
            print("\n" + "=" * 60)
            print("🔄 Reloading snapshot data after bootstrap...")
            print("=" * 60)
            
            load_all(
                self._duckdb_connection,
                snapshot_dir,
                prototype_api_file,
                include_base=include_base,
                include_components=include_components,
                include_derived=include_derived,
                include_ghosts=include_ghosts,
                include_analytics=include_analytics,
                replay_updates=replay_updates,
            )
            
            logger.info("✅ Post-bootstrap reload complete. DB now contains all snapshotted data.")
            print("✅ Post-bootstrap reload complete!")
    
    def _load_snapshots_sync(
        self,
        snapshot_dir: Optional[Path] = None,
        db_path: Optional[Union[str, Path]] = None,
        prototype_api_file: Optional[str] = None,
        include_base: bool = True,
        include_components: bool = True,
        include_derived: bool = True,
        include_ghosts: bool = True,
        include_analytics: bool = True,
        replay_updates: bool = True,
    ) -> Path:
        """Load snapshot data synchronously (doesn't wait for COMPLETE state).
        
        This is the internal synchronous version that:
        1. Creates DB connection
        2. Auto-detects snapshot directory
        3. Waits for snapshot files to exist on disk
        4. Loads files into DB
        5. Initializes GameDataSyncService (but doesn't start it)
        
        Returns:
            Path: The resolved snapshot_dir path
        """
        
        # Auto-create connection if not already loaded
        if self._duckdb_connection is None:
            if db_path is None:
                con = duckdb.connect(':memory:')
            else:
                con = connect(db_path)
            self._duckdb_connection = con
        
        # Auto-detect snapshot directory if not provided
        # Uses Factorio client script-output directory as default
        
        snapshot_dir = Path(self._snapshot_dir)
        
        # Wait for initial snapshot files if they don't exist
        # Check if any snapshot files exist
        snapshot_base = snapshot_dir / "factoryverse" / "snapshots"
        has_snapshots = False
        if snapshot_base.exists():
            # Check if any chunk directories exist
            chunk_dirs = [d for d in snapshot_base.iterdir() if d.is_dir()]
            for chunk_x_dir in chunk_dirs:
                if chunk_x_dir.is_dir():
                    chunk_y_dirs = [d for d in chunk_x_dir.iterdir() if d.is_dir()]
                    for chunk_y_dir in chunk_y_dirs:
                        # Check if any init files exist
                        if any(chunk_y_dir.glob("*_init.jsonl")):
                            has_snapshots = True
                            break
                    if has_snapshots:
                        break
        
        if not has_snapshots:
            # Try to trigger snapshot via RCON if available
            print("No snapshot files found. Triggering map snapshot via RCON...")
            result = self._rcon.send_command("take_map_snapshot")
            if result and "error" not in result.lower():
                print("✅ Map snapshot triggered successfully")
            else:
                print(f"⚠️  RCON command may have failed: {result}")
            
            # Wait for snapshot files to be created
            max_wait = 30  # 30 seconds timeout
            print(f"Waiting for snapshot files to be created (max {max_wait}s)...")
            for i in range(max_wait):
                if snapshot_base.exists():
                    chunk_dirs = [d for d in snapshot_base.iterdir() if d.is_dir()]
                    for chunk_x_dir in chunk_dirs:
                        if chunk_x_dir.is_dir():
                            chunk_y_dirs = [d for d in chunk_x_dir.iterdir() if d.is_dir()]
                            for chunk_y_dir in chunk_y_dirs:
                                if any(chunk_y_dir.glob("*_init.jsonl")):
                                    has_snapshots = True
                                    break
                            if has_snapshots:
                                break
                    if has_snapshots:
                        print(f"✅ Snapshot files found after {i+1} seconds")
                        break
                time.sleep(1)
            else:
                print(f"⚠️  Warning: No snapshot files found after {max_wait} seconds. Loading whatever exists...")
        
        # Load data (this will auto-create schema if needed)
        load_all(
            self._duckdb_connection,
            snapshot_dir,
            prototype_api_file,
            include_base=include_base,
            include_components=include_components,
            include_derived=include_derived,
            include_ghosts=include_ghosts,
            include_analytics=include_analytics,
            replay_updates=replay_updates,
        )
        
        # Initialize GameDataSyncService for real-time sync (but don't start it yet)
        if self._game_data_sync is None:
            udp_dispatcher = get_udp_dispatcher()
            self._game_data_sync = GameDataSyncService(
                agent_id=self._agent_id,
                db_connection=self._duckdb_connection,
                snapshot_dir=snapshot_dir,
                udp_dispatcher=udp_dispatcher,
                rcon_client=self._rcon,
            )
        
        return snapshot_dir
    
    
    async def _wait_for_bootstrap_complete(self, timeout: float = 120.0) -> None:
        """Wait for bootstrap phase to complete (INITIAL_SNAPSHOTTING → MAINTENANCE).
        
        Polls the snapshot system's phase status and waits for transition to MAINTENANCE.
        This is more reliable than waiting for individual chunks since it respects
        the bootstrap waiting period (300 ticks) that allows async charting to complete.
        
        Args:
            timeout: Maximum time to wait for bootstrap (seconds, default 120s = 2 minutes)
            
        Raises:
            asyncio.TimeoutError: If bootstrap doesn't complete within timeout
        """
        start_time = time.time()
        check_interval = 1.0  # Check every second
        
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
            
            # Query snapshot system status via RCON
            try:
                cmd = "/c rcon.print(helpers.table_to_json(remote.call('map', 'get_snapshot_status')))"
                result = self._rcon.send_command(cmd)
                
                # Handle None result (happens when command fails)
                if result is None or result.strip() == "":
                    logger.debug("Empty or None result from RCON, retrying...")
                    await asyncio.sleep(check_interval)
                    continue
                    
                status = json.loads(result)
                
                system_phase = status.get("system_phase")
                
                if system_phase == "MAINTENANCE":
                    # Bootstrap complete!
                    stats = status.get("bootstrap_wait", {})
                    completed = status.get("completed_chunks", 0)
                    logger.info(f"✅ Bootstrap complete! Transitioned to MAINTENANCE mode.")
                    logger.info(f"✅ {completed} chunks snapshotted during bootstrap.")
                    print(f"✅ Bootstrap complete! {completed} chunks snapshotted.")
                    return
                
                elif system_phase == "INITIAL_SNAPSHOTTING":
                    # Still bootstrapping
                    pending = status.get("pending_chunks", 0)
                    completed = status.get("completed_chunks", 0)
                    bootstrap_wait = status.get("bootstrap_wait", {})
                    current_tick = bootstrap_wait.get("current_tick", 0)
                    total_ticks = bootstrap_wait.get("total_ticks", 300)
                    waiting = bootstrap_wait.get("waiting", False)
                    
                    if waiting:
                        logger.debug(
                            f"Bootstrap waiting: {current_tick}/{total_ticks} ticks, "
                            f"{pending} pending chunks, {completed} completed"
                        )
                        if int(elapsed) % 5 == 0:  # Log every 5 seconds
                            print(
                                f"  ⏱️  Bootstrap waiting: {current_tick}/{total_ticks} ticks, "
                                f"{pending} pending, {completed} completed"
                            )
                    else:
                        logger.debug(
                            f"Processing chunks: {pending} pending, {completed} completed"
                        )
                        if int(elapsed) % 5 == 0:
                            print(f"  📦 Processing: {pending} pending, {completed} completed")
                
            except Exception as e:
                logger.warning(f"Error checking bootstrap status: {e}")
                # Continue waiting, don't fail on transient errors
            
            # Wait before next check
            await asyncio.sleep(check_interval)
    
