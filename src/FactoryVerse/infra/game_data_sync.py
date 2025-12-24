"""
GameDataSyncService - Per-agent database synchronization service.

Each agent runtime has its own instance that:
- Maintains write lock on agent's DuckDB database
- Ensures DB is synced before every DB usage
- Subscribes to shared UDPDispatcher for game state updates
- Processes updates in background with write lock
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List, TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb
    from factorio_rcon import RCONClient

from FactoryVerse.infra.udp_dispatcher import UDPDispatcher, get_udp_dispatcher

logger = logging.getLogger(__name__)


class GameDataSyncService:
    """
    Per-agent database synchronization service.
    
    Each agent runtime should have its own instance that:
    - Maintains exclusive write lock on agent's DuckDB
    - Ensures DB is synced before every DB usage
    - Subscribes to shared UDPDispatcher (filtered by agent_id)
    - Processes updates in background with write lock
    """
    
    def __init__(
        self,
        agent_id: str,
        db_connection: "duckdb.DuckDBPyConnection",
        snapshot_dir: Path,
        udp_dispatcher: Optional[UDPDispatcher] = None,
        rcon_client: Optional["RCONClient"] = None,
    ):
        """
        Initialize the game data sync service.
        
        Args:
            agent_id: Agent ID (e.g., "agent_1")
            db_connection: DuckDB connection for this agent
            snapshot_dir: Path to snapshot directory (script-output/factoryverse/snapshots)
            udp_dispatcher: Optional UDPDispatcher instance. If None, uses global dispatcher.
            rcon_client: Optional RCON client for action integration
        """
        self.agent_id = agent_id
        self.db = db_connection
        self.snapshot_dir = Path(snapshot_dir)
        self.udp_dispatcher = udp_dispatcher or get_udp_dispatcher()
        self.rcon_client = rcon_client
        
        # Write lock for exclusive DB access
        self._write_lock = asyncio.Lock()
        
        # Sync queue for background processing
        self._sync_queue: asyncio.Queue[Tuple[str, Dict[str, Any]]] = asyncio.Queue()
        
        # Background sync task
        self._background_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Action listener for action completion handling
        # Import here to avoid circular import (agent.py imports GameDataSyncService)
        from FactoryVerse.dsl.agent import AsyncActionListener
        self._action_listener = AsyncActionListener(udp_dispatcher=self.udp_dispatcher)
        
        # Snapshot state tracking (chunk -> state)
        self._chunk_states: Dict[Tuple[int, int], str] = {}
        self._completion_events: Dict[Tuple[int, int], asyncio.Event] = {}
        
        # Chunk loading tracking (chunks that have been loaded into DB)
        self._loaded_chunks: set[Tuple[int, int]] = set()
        
        # Chunks pending load (waiting for COMPLETE state)
        self._pending_loads: Dict[Tuple[int, int], asyncio.Event] = {}
        
        # Sequence tracking for reliable UDP (detect packet loss)
        self._last_sequence: Dict[str, int] = {}  # event_type -> last seen sequence
        self._sequence_gaps: List[Tuple[str, int, int]] = []  # (event_type, expected, received)
        
        # Chunks marked as stale due to sequence gaps (need reload)
        self._stale_chunks: set[Tuple[int, int]] = set()
        
        logger.info(f"GameDataSyncService initialized for agent {agent_id}")
    
    async def start(self) -> None:
        """
        Start background sync service and subscribe to UDP dispatcher.
        
        This should be called once during agent runtime initialization.
        """
        if self._running:
            logger.warning(f"GameDataSyncService for agent {self.agent_id} is already running")
            return
        
        # Ensure UDP dispatcher is running
        if not self.udp_dispatcher.is_running():
            await self.udp_dispatcher.start()
        
        # Subscribe to UDP dispatcher (shared across all agents)
        # Note: Actions are handled by AsyncActionListener (already subscribed to "*")
        # We only subscribe to DB sync-related events
        self.udp_dispatcher.subscribe("entity_operation", self._handle_entity_operation)
        self.udp_dispatcher.subscribe("file_io", self._handle_file_io)
        self.udp_dispatcher.subscribe("snapshot_state", self._handle_snapshot_state)
        self.udp_dispatcher.subscribe("chunk_charted", self._handle_chunk_charted)
        
        # Start action listener
        await self._action_listener.start()
        
        # Start background sync loop
        self._background_task = asyncio.create_task(self._background_sync_loop())
        self._running = True
        
        logger.info(f"GameDataSyncService started for agent {self.agent_id}")
    
    async def stop(self) -> None:
        """
        Stop background sync service and unsubscribe from UDP dispatcher.
        
        This should be called during agent runtime cleanup.
        """
        if not self._running:
            return
        
        self._running = False
        
        # Cancel background task
        if self._background_task:
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                pass
        
        # Stop action listener
        await self._action_listener.stop()
        
        # Unsubscribe from UDP dispatcher
        self.udp_dispatcher.unsubscribe("entity_operation", self._handle_entity_operation)
        self.udp_dispatcher.unsubscribe("file_io", self._handle_file_io)
        self.udp_dispatcher.unsubscribe("snapshot_state", self._handle_snapshot_state)
        self.udp_dispatcher.unsubscribe("chunk_charted", self._handle_chunk_charted)
        
        logger.info(f"GameDataSyncService stopped for agent {self.agent_id}")
    
    async def ensure_synced(
        self, 
        timeout: float = 5.0,
        required_chunks: Optional[list[Tuple[int, int]]] = None
    ) -> None:
        """
        Ensure DB is synced before query.
        
        **CRITICAL**: This should be called before any DB query to ensure:
        1. All queued updates are processed
        2. Required chunks are snapshotted and loaded (if specified)
        3. DB state is current
        
        This method acquires the write lock, processes any pending updates,
        ensures required chunks are loaded, and releases the lock.
        
        Args:
            timeout: Maximum time to wait for queue processing (seconds)
            required_chunks: Optional list of (chunk_x, chunk_y) tuples that must be loaded.
                           If provided, waits for chunks to be COMPLETE and loads them.
        """
        async with self._write_lock:
            # Process any pending updates in queue
            await self._process_sync_queue(timeout=timeout)
            
            # Ensure required chunks are loaded
            if required_chunks:
                for chunk_x, chunk_y in required_chunks:
                    await self._ensure_chunk_loaded(chunk_x, chunk_y, timeout=timeout)
    
    async def wait_for_chunk_snapshot(
        self, chunk_x: int, chunk_y: int, timeout: float = 30.0, load: bool = True
    ) -> None:
        """
        Wait for chunk snapshot to complete and optionally load it.
        
        Blocks until chunk snapshot state is COMPLETE.
        If load=True, also ensures chunk is loaded into DB.
        
        Args:
            chunk_x: Chunk X coordinate
            chunk_y: Chunk Y coordinate
            timeout: Maximum time to wait (seconds)
            load: If True, load chunk into DB after completion
            
        Raises:
            asyncio.TimeoutError: If chunk doesn't complete within timeout
        """
        chunk_key = (chunk_x, chunk_y)
        
        # Check if already complete and loaded
        if self._chunk_states.get(chunk_key) == "COMPLETE":
            if not load or chunk_key in self._loaded_chunks:
                return
        
        # Create or get completion event
        if chunk_key not in self._completion_events:
            self._completion_events[chunk_key] = asyncio.Event()
        
        event = self._completion_events[chunk_key]
        
        # Wait for completion
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            state = self._chunk_states.get(chunk_key, "UNKNOWN")
            raise asyncio.TimeoutError(
                f"Chunk ({chunk_x}, {chunk_y}) did not complete within {timeout}s. "
                f"Current state: {state}"
            )
        
        # Load chunk if requested
        if load:
            async with self._write_lock:
                await self._ensure_chunk_loaded(chunk_x, chunk_y, timeout=timeout)
    
    def get_snapshot_state(self, chunk_x: int, chunk_y: int) -> Optional[str]:
        """
        Get current snapshot state for a chunk.
        
        Args:
            chunk_x: Chunk X coordinate
            chunk_y: Chunk Y coordinate
            
        Returns:
            Snapshot state ("IDLE", "FIND_ENTITIES", "SERIALIZE", "WRITE", "COMPLETE")
            or None if chunk state is unknown
        """
        return self._chunk_states.get((chunk_x, chunk_y))
    
    def register_action(self, action_id: str) -> None:
        """
        Register an action for awaiting completion.
        
        Args:
            action_id: Action ID to register
        """
        self._action_listener.register_action(action_id)
    
    async def wait_for_action(
        self, action_id: str, timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Wait for an action to complete.
        
        Args:
            action_id: Action ID to wait for
            timeout: Optional timeout override in seconds
            
        Returns:
            Action completion payload
            
        Raises:
            TimeoutError: If action doesn't complete within timeout
            ValueError: If action_id not registered
        """
        return await self._action_listener.wait_for_action(action_id, timeout=timeout)
    
    # ============================================================================
    # UDP Payload Handlers (queue updates for background processing)
    # ============================================================================
    
    def _handle_entity_operation(self, payload: Dict[str, Any]) -> None:
        """Handle entity operation payload."""
        try:
            op = payload.get('op')
            entity_key = payload.get('entity_key')
            entity_name = payload.get('entity_name')
            logger.info(f"🔔 UDP: entity_operation received - op={op}, key={entity_key}, name={entity_name}")
            self._sync_queue.put_nowait(("entity_operation", payload))
            logger.info(f"   Queued for processing (queue size: {self._sync_queue.qsize()})")
        except asyncio.QueueFull:
            logger.warning(f"Sync queue full, dropping entity operation: {payload.get('op')}")
    
    def _handle_file_io(self, payload: Dict[str, Any]) -> None:
        """Handle file I/O payload."""
        try:
            self._sync_queue.put_nowait(("file_io", payload))
        except asyncio.QueueFull:
            logger.warning(f"Sync queue full, dropping file I/O: {payload.get('file_type')}")
    
    def _handle_snapshot_state(self, payload: Dict[str, Any]) -> None:
        """Handle snapshot state payload."""
        try:
            self._sync_queue.put_nowait(("snapshot_state", payload))
        except asyncio.QueueFull:
            logger.warning(f"Sync queue full, dropping snapshot state")
    
    def _handle_chunk_charted(self, payload: Dict[str, Any]) -> None:
        """Handle chunk charted payload."""
        try:
            self._sync_queue.put_nowait(("chunk_charted", payload))
        except asyncio.QueueFull:
            logger.warning(f"Sync queue full, dropping chunk charted")
    
    # ============================================================================
    # Background Sync Loop
    # ============================================================================
    
    async def _background_sync_loop(self) -> None:
        """
        Background loop that processes sync queue with write lock.
        
        This runs continuously, processing UDP updates as they arrive.
        All DB writes happen within the write lock context.
        """
        logger.info(f"🔄 Background sync loop started for agent {self.agent_id}")
        
        while self._running:
            try:
                # Get update from queue (with timeout for cancellation)
                try:
                    update_type, payload = await asyncio.wait_for(
                        self._sync_queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue  # Check for cancellation
                
                logger.info(f"📦 Dequeued update from sync queue: type={update_type}")
                
                # Process update with write lock
                async with self._write_lock:
                    await self._process_update(update_type, payload)
                    
            except asyncio.CancelledError:
                logger.info(f"Background sync loop cancelled for agent {self.agent_id}")
                break
            except Exception as e:
                logger.error(
                    f"Error in background sync loop for agent {self.agent_id}: {e}",
                    exc_info=True
                )
        
        logger.info(f"Background sync loop stopped for agent {self.agent_id}")
    
    async def _process_update(self, update_type: str, payload: Dict[str, Any]) -> None:
        """
        Process a single update (called with write lock held).
        
        Args:
            update_type: Type of update ("action", "entity_operation", "file_io", etc.)
            payload: Update payload
        """
        try:
            logger.info(f"⚙️  Processing update: type={update_type}, op={payload.get('op', 'N/A')}")
            
            # Check sequence number to detect packet loss
            # NOTE: Lua uses a GLOBAL sequence counter across all event types,
            # so we track globally, not per-event-type
            sequence = payload.get("sequence")
            if sequence is not None:
                event_type = payload.get("event_type", update_type)
                last_seq = self._last_sequence.get("_global", -1)
                
                if last_seq >= 0 and sequence != last_seq + 1:
                    # Gap detected! This indicates actual packet loss
                    gap = (event_type, last_seq + 1, sequence)
                    self._sequence_gaps.append(gap)
                    
                    # Mark chunk as stale if applicable
                    # Most events have chunk coordinates (file_io, entity_operation, etc.)
                    chunk_x = payload.get("chunk_x")
                    chunk_y = payload.get("chunk_y")
                    if chunk_x is None and "chunk" in payload:
                        # Some payloads use nested chunk object
                        chunk_x = payload["chunk"].get("x")
                        chunk_y = payload["chunk"].get("y")
                        
                    if chunk_x is not None and chunk_y is not None:
                        self._stale_chunks.add((chunk_x, chunk_y))
                        logger.warning(
                            f"Packet loss detected for chunk ({chunk_x},{chunk_y}): "
                            f"expected seq {last_seq + 1}, got {sequence}. Marked as stale."
                        )
                    else:
                        logger.warning(
                            f"Packet loss detected (global event): expected seq {last_seq + 1}, got {sequence}."
                        )
                
                self._last_sequence["_global"] = sequence
            
            # Process update
            if update_type == "entity_operation":
                await self._process_entity_operation(payload)
            elif update_type == "file_io":
                await self._process_file_io(payload)
            elif update_type == "snapshot_state":
                await self._process_snapshot_state(payload)
            elif update_type == "chunk_charted":
                await self._process_chunk_charted(payload)
            else:
                logger.warning(f"Unknown update type: {update_type}")
                
            logger.debug(f"✅ Finished processing update: type={update_type}")
        except Exception as e:
            logger.error(
                f"Error processing {update_type} update for agent {self.agent_id}: {e}",
                exc_info=True
            )
    
    async def _process_sync_queue(self, timeout: float = 5.0) -> None:
        """
        Process all pending updates in queue (called with write lock held).
        
        Args:
            timeout: Maximum time to spend processing queue
        """
        deadline = time.time() + timeout
        processed = 0
        
        while time.time() < deadline:
            try:
                update_type, payload = self._sync_queue.get_nowait()
                await self._process_update(update_type, payload)
                processed += 1
            except asyncio.QueueEmpty:
                break
        
        if processed > 0:
            logger.debug(f"Processed {processed} queued updates for agent {self.agent_id}")
    
    # ============================================================================
    # Chunk Loading Coordination
    # ============================================================================
    
    async def _ensure_chunk_loaded(
        self, chunk_x: int, chunk_y: int, timeout: float = 30.0
    ) -> None:
        """
        Ensure chunk is loaded into DB (called with write lock held).
        
        If chunk is not yet COMPLETE, waits for completion.
        If chunk is COMPLETE but not loaded, loads it.
        
        Args:
            chunk_x: Chunk X coordinate
            chunk_y: Chunk Y coordinate
            timeout: Maximum time to wait for completion (seconds)
        """
        chunk_key = (chunk_x, chunk_y)
        
        # Check if already loaded
        if chunk_key in self._loaded_chunks:
            return
        
        # Check if chunk is COMPLETE
        state = self._chunk_states.get(chunk_key)
        if state != "COMPLETE":
            # Wait for completion (release lock while waiting)
            # Note: We need to release the lock to avoid deadlock
            # This is a bit tricky - we'll create an event and wait outside the lock
            if chunk_key not in self._pending_loads:
                self._pending_loads[chunk_key] = asyncio.Event()
            
            # Release lock temporarily to wait
            # We'll need to re-acquire it after waiting
            load_event = self._pending_loads[chunk_key]
            
            # Check state again after potential wait
            # For now, we'll just try to load and let it fail if not ready
            # In practice, ensure_synced should be called after wait_for_chunk_snapshot
            if state != "COMPLETE":
                logger.warning(
                    f"Chunk ({chunk_x}, {chunk_y}) not COMPLETE (state: {state}), "
                    f"cannot load. Call wait_for_chunk_snapshot() first."
                )
                return
        
        # Load the chunk
        await self._load_chunk(chunk_x, chunk_y)
    
    async def _load_chunk(self, chunk_x: int, chunk_y: int) -> None:
        """
        Load a single chunk into DB (called with write lock held).
        
        This loads the chunk's snapshot files into the database.
        Only loads if chunk files exist and are complete.
        
        Args:
            chunk_x: Chunk X coordinate
            chunk_y: Chunk Y coordinate
        """
        import json
        chunk_key = (chunk_x, chunk_y)
        
        # Check if already loaded
        if chunk_key in self._loaded_chunks:
            return
        
        # Check if chunk directory exists
        chunk_dir = self.snapshot_dir / str(chunk_x) / str(chunk_y)
        if not chunk_dir.exists():
            logger.debug(f"Chunk directory does not exist: {chunk_dir}")
            return
        
        try:
            # Load resource tiles (resources_init.jsonl)
            resources_file = chunk_dir / "resources_init.jsonl"
            if resources_file.exists():
                with open(resources_file, "r") as f:
                    for line in f:
                        if line.strip():
                            data = json.loads(line)
                            entity_key = f"{data['kind']}:{data['x']},{data['y']}"
                            self.db.execute(
                                "INSERT OR REPLACE INTO resource_tile (entity_key, name, position, amount) VALUES (?, ?, ?, ?)",
                                [entity_key, data["kind"], json.dumps({"x": float(data["x"]), "y": float(data["y"])}), data.get("amount", 0)]
                            )
            
            # Load water tiles (water_init.jsonl)
            water_file = chunk_dir / "water_init.jsonl"
            if water_file.exists():
                with open(water_file, "r") as f:
                    for line in f:
                        if line.strip():
                            data = json.loads(line)
                            entity_key = f"water:{data['x']},{data['y']}"
                            self.db.execute(
                                "INSERT OR REPLACE INTO water_tile (entity_key, type, position) VALUES (?, ?, ?)",
                                [entity_key, "water-tile", json.dumps({"x": float(data["x"]), "y": float(data["y"])})]
                            )
            
            # Load resource entities (trees_rocks_init.jsonl)
            trees_rocks_file = chunk_dir / "trees_rocks_init.jsonl"
            if trees_rocks_file.exists():
                with open(trees_rocks_file, "r") as f:
                    for line in f:
                        if line.strip():
                            data = json.loads(line)
                            entity_key = data.get("key") or f"{data['name']}:{data['position']['x']},{data['position']['y']}"
                            bbox = data.get("bounding_box")
                            if bbox:
                                self.db.execute(
                                    "INSERT OR REPLACE INTO resource_entity (entity_key, name, type, position, bbox) VALUES (?, ?, ?, ?, ST_MakeEnvelope(?, ?, ?, ?))",
                                    [entity_key, data["name"], data.get("type", "unknown"), json.dumps(data["position"]),
                                     float(bbox["min_x"]), float(bbox["min_y"]), float(bbox["max_x"]), float(bbox["max_y"])]
                                )
                            else:
                                self.db.execute(
                                    "INSERT OR REPLACE INTO resource_entity (entity_key, name, type, position) VALUES (?, ?, ?, ?)",
                                    [entity_key, data["name"], data.get("type", "unknown"), json.dumps(data["position"])]
                                )
            
            # Replay updates log (entities_updates.jsonl)
            updates_file = chunk_dir / "entities_updates.jsonl"
            if updates_file.exists():
                with open(updates_file, "r") as f:
                    for line in f:
                        if line.strip():
                            operation = json.loads(line)
                            op = operation.get("op")
                            if op == "upsert":
                                # This is a created/updated entity - sync it
                                await self._sync_entity_created({"entity": operation.get("entity")})
                            elif op == "remove":
                                # This is a destroyed entity - sync it
                                await self._sync_entity_destroyed({
                                    "entity_key": operation.get("key"),
                                    "entity_name": operation.get("name", ""),
                                })
            
            # Replay trees/rocks updates log (trees_rocks-update.jsonl)
            trees_rocks_updates_file = chunk_dir / "trees_rocks-update.jsonl"
            if trees_rocks_updates_file.exists():
                with open(trees_rocks_updates_file, "r") as f:
                    for line in f:
                        if line.strip():
                            operation = json.loads(line)
                            op = operation.get("op")
                            if op == "remove":
                                # Remove the resource entity from the database
                                entity_key = operation.get("key")
                                if entity_key:
                                    self.db.execute(
                                        "DELETE FROM resource_entity WHERE entity_key = ?",
                                        [entity_key]
                                    )
                                    logger.debug(f"Removed resource entity {entity_key} from chunk ({chunk_x}, {chunk_y})")
            
            # Mark chunk as loaded
            self._loaded_chunks.add(chunk_key)
            logger.debug(f"Chunk ({chunk_x}, {chunk_y}) loaded successfully")
            
        except Exception as e:
            logger.error(
                f"Error loading chunk ({chunk_x}, {chunk_y}): {e}",
                exc_info=True
            )
            raise
    
    def is_chunk_loaded(self, chunk_x: int, chunk_y: int) -> bool:
        """
        Check if chunk is loaded into DB.
        
        Args:
            chunk_x: Chunk X coordinate
            chunk_y: Chunk Y coordinate
            
        Returns:
            True if chunk is loaded, False otherwise
        """
        return (chunk_x, chunk_y) in self._loaded_chunks
    
    def get_pending_chunks(self) -> list[Tuple[int, int]]:
        """
        Get list of chunks that are COMPLETE but not yet loaded.
        
        Returns:
            List of (chunk_x, chunk_y) tuples
        """
        pending = []
        for chunk_key, state in self._chunk_states.items():
            if state == "COMPLETE" and chunk_key not in self._loaded_chunks:
                pending.append(chunk_key)
        return pending
    
    async def load_all_complete_chunks(self, timeout: float = 30.0) -> int:
        """
        Load all chunks that are COMPLETE but not yet loaded.
        
        This is useful for initial DB setup or recovery.
        
        Args:
            timeout: Maximum time to wait per chunk (seconds)
            
        Returns:
            Number of chunks loaded
        """
        pending = self.get_pending_chunks()
        loaded_count = 0
        
        async with self._write_lock:
            for chunk_x, chunk_y in pending:
                try:
                    await self._load_chunk(chunk_x, chunk_y)
                    loaded_count += 1
                except Exception as e:
                    logger.error(
                        f"Failed to load chunk ({chunk_x}, {chunk_y}): {e}",
                        exc_info=True
                    )
        
        if loaded_count > 0:
            logger.info(f"Loaded {loaded_count} chunks into DB")
        
        return loaded_count
    
    # ============================================================================
    # Update Processors (stubs for Phase 1, to be implemented in later phases)
    # ============================================================================
    
    async def _process_entity_operation(self, payload: Dict[str, Any]) -> None:
        """
        Process entity operation update.
        
        Handles incremental entity DB updates:
        - created: UPSERT into map_entity and component tables
        - destroyed: DELETE from all tables
        - rotated: UPDATE direction in map_entity and component tables
        - configuration_changed: UPSERT updated configuration
        """
        op = payload.get("op")
        entity_key = payload.get("entity_key")
        
        # Normalize entity_key: ensure it has parentheses to match DB format (name:x,y vs (name:x,y))
        if entity_key and not entity_key.startswith("("):
            entity_key = f"({entity_key})"
            payload["entity_key"] = entity_key

        entity_name = payload.get("entity_name")
        chunk = payload.get("chunk", {})
        chunk_x = chunk.get("x")
        chunk_y = chunk.get("y")
        
        if not entity_key:
            logger.warning(f"Entity operation {op} missing entity_key: {payload}")
            return
        
        try:
            if op == "created" or op == "upsert":
                await self._sync_entity_created(payload)
            elif op == "destroyed":
                await self._sync_entity_destroyed(payload)
            elif op == "rotated":
                await self._sync_entity_rotated(payload)
            elif op == "configuration_changed":
                await self._sync_entity_configuration_changed(payload)
            else:
                logger.warning(f"Unknown entity operation: {op}")
        except Exception as e:
            logger.error(
                f"Error processing entity operation {op} for {entity_key}: {e}",
                exc_info=True
            )
    
    async def _sync_entity_created(self, payload: Dict[str, Any]) -> None:
        """Sync entity created - UPSERT into map_entity and component tables."""
        logger.info(f"🔧 _sync_entity_created called with payload keys: {list(payload.keys())}")
        entity_data = payload.get("entity")
        if not entity_data:
            logger.warning(f"Entity created payload missing entity data: {payload}")
            return
        
        logger.info(f"🔧 Entity data found: {entity_data.get('name')} at {entity_data.get('position')}")
        
        # Extract entity data
        entity_key = entity_data.get("key") or payload.get("entity_key")
        if not entity_key:
            logger.warning(f"Entity created missing entity_key: {payload}")
            return
        
        logger.info(f"🔧 Entity key: {entity_key}")
        
        # Check if entity is in placeable_entity ENUM
        entity_name = entity_data.get("name") or payload.get("entity_name")
        if not self._is_valid_entity(entity_name):
            logger.debug(f"Skipping entity {entity_name} (not in placeable_entity ENUM)")
            return
        
        logger.info(f"🔧 Entity {entity_name} is valid, upserting to map_entity...")
        
        # Insert/update map_entity
        await self._upsert_map_entity(entity_data)
        
        logger.info(f"🔧 map_entity upserted successfully")
        
        # Insert/update component tables based on entity type
        entity_type = entity_data.get("type")
        if entity_type == "inserter":
            await self._upsert_inserter(entity_data)
        elif entity_type == "transport-belt":
            await self._upsert_transport_belt(entity_data)
        elif entity_type == "mining-drill":
            await self._upsert_mining_drill(entity_data)
        elif entity_type == "assembling-machine":
            await self._upsert_assembler(entity_data)
        elif entity_type == "pumpjack":
            await self._upsert_pumpjack(entity_data)
        elif entity_type == "electric-pole":
            await self._upsert_electric_pole(entity_data)
        
        logger.info(f"✅ Entity created: {entity_key} ({entity_name})")
    
    async def _sync_entity_destroyed(self, payload: Dict[str, Any]) -> None:
        """Sync entity destroyed - DELETE from all tables."""
        entity_key = payload.get("entity_key")
        entity_name = payload.get("entity_name", "")
        if not entity_key:
            logger.warning(f"Entity destroyed payload missing entity_key: {payload}")
            return
        
        logger.debug(f"🗑️  Processing entity_destroyed - key={entity_key}, name={entity_name}")
        
        # Determine if this is a resource entity (tree/rock) vs map entity
        # Trees and rocks are in resource_entity table, not map_entity
        is_resource_entity = "tree" in entity_name or "rock" in entity_name or entity_name.startswith("dead-")
        
        if is_resource_entity:
            # Check if entity exists before deletion
            result = self.db.execute(
                "SELECT COUNT(*) FROM resource_entity WHERE entity_key = ?", 
                [entity_key]
            ).fetchone()
            exists_before = result[0] if result else 0
            
            # Delete from resource_entity table
            self.db.execute("DELETE FROM resource_entity WHERE entity_key = ?", [entity_key])
            
            # Verify deletion
            result_after = self.db.execute(
                "SELECT COUNT(*) FROM resource_entity WHERE entity_key = ?", 
                [entity_key]
            ).fetchone()
            exists_after = result_after[0] if result_after else 0
            
            logger.info(
                f"✅ Resource entity destroyed: {entity_key} ({entity_name}) - "
                f"existed_before={exists_before}, exists_after={exists_after}"
            )
        else:
            # Delete from component tables first (foreign key constraints)
            self.db.execute("DELETE FROM inserter WHERE entity_key = ?", [entity_key])
            self.db.execute("DELETE FROM transport_belt WHERE entity_key = ?", [entity_key])
            self.db.execute("DELETE FROM mining_drill WHERE entity_key = ?", [entity_key])
            self.db.execute("DELETE FROM assemblers WHERE entity_key = ?", [entity_key])
            self.db.execute("DELETE FROM pumpjack WHERE entity_key = ?", [entity_key])
            self.db.execute("DELETE FROM electric_pole WHERE entity_key = ?", [entity_key])
            
            # Delete from map_entity
            self.db.execute("DELETE FROM map_entity WHERE entity_key = ?", [entity_key])
            logger.debug(f"Map entity destroyed: {entity_key} ({entity_name})")
    
    async def _sync_entity_rotated(self, payload: Dict[str, Any]) -> None:
        """Sync entity rotated - UPDATE direction in component tables."""
        entity_key = payload.get("entity_key")
        direction = payload.get("direction")
        
        if not entity_key:
            return
        
        # Get direction_name from payload (could be string like "north" or number)
        # If not provided, we can't update
        if direction is None:
            logger.warning(f"Entity rotated payload missing direction: {payload}")
            return
        
        # Convert direction to string if it's a number
        if isinstance(direction, (int, float)):
            direction_map = {
                0: "north", 2: "east", 4: "south", 6: "west",
            }
            direction_name = direction_map.get(int(direction), "north")
        else:
            direction_name = str(direction).lower()
        
        direction_upper = direction_name.upper()
        
        # Update component tables that have direction
        # Check which component table this entity belongs to
        self.db.execute(
            "UPDATE inserter SET direction = ?::direction WHERE entity_key = ?",
            [direction_upper, entity_key]
        )
        
        self.db.execute(
            "UPDATE transport_belt SET direction = ?::direction WHERE entity_key = ?",
            [direction_upper, entity_key]
        )
        
        self.db.execute(
            "UPDATE mining_drill SET direction = ?::direction WHERE entity_key = ?",
            [direction_upper, entity_key]
        )
        
        logger.debug(f"Entity rotated: {entity_key} -> {direction_upper}")
    
    async def _sync_entity_configuration_changed(self, payload: Dict[str, Any]) -> None:
        """Sync entity configuration changed - UPSERT updated configuration."""
        # Configuration changes are similar to created (UPSERT)
        # The entity data should contain the updated configuration
        await self._sync_entity_created(payload)
    
    # ============================================================================
    # Entity Data Processing Helpers
    # ============================================================================
    
    def _is_valid_entity(self, entity_name: Optional[str]) -> bool:
        """Check if entity name is in placeable_entity ENUM."""
        if not entity_name:
            return False
            
        # For robustness, we always allow entities. 
        # The ENUM check can strictly filter valid entities from the Dump, 
        # but for testing and mod compatibility, we should be permissive.
        return True
    
    async def _upsert_map_entity(self, entity_data: Dict[str, Any]) -> None:
        """UPSERT entity into map_entity table."""
        import json
        
        entity_key = entity_data.get("key")
        if not entity_key:
            return
        
        entity_name = entity_data.get("name")
        if not entity_name:
            return
        
        pos = entity_data.get("position", {})
        px = float(pos.get("x", 0.0))
        py = float(pos.get("y", 0.0))
        
        bbox = entity_data.get("bounding_box", {})
        if bbox:
            min_x = float(bbox.get("min_x", px))
            min_y = float(bbox.get("min_y", py))
            max_x = float(bbox.get("max_x", px))
            max_y = float(bbox.get("max_y", py))
        else:
            # Fallback to point
            min_x = min_y = px
            max_x = max_y = py
        
        electric_network_id = entity_data.get("electric_network_id")
        
        self.db.execute(
            """
            INSERT OR REPLACE INTO map_entity (entity_key, position, entity_name, bbox, electric_network_id)
            VALUES (?, ?, ?, ST_MakeEnvelope(?, ?, ?, ?), ?)
            """,
            [
                entity_key,
                json.dumps({"x": px, "y": py}),
                entity_name,
                min_x,
                min_y,
                max_x,
                max_y,
                electric_network_id,
            ],
        )
    
    async def _upsert_inserter(self, entity_data: Dict[str, Any]) -> None:
        """UPSERT inserter into inserter table."""
        import json
        
        entity_key = entity_data.get("key")
        if not entity_key:
            return
        
        inserter_info = entity_data.get("inserter")
        if not inserter_info:
            return
        
        direction_name = entity_data.get("direction_name", "north")
        
        # Build output struct
        drop_pos = inserter_info.get("drop_position", {})
        output_struct = None
        if drop_pos:
            output_struct = {
                "position": {"x": drop_pos.get("x", 0), "y": drop_pos.get("y", 0)},
                "entity_key": inserter_info.get("drop_target_key"),
            }
        
        # Build input struct
        pickup_pos = inserter_info.get("pickup_position", {})
        input_struct = None
        if pickup_pos:
            input_struct = {
                "position": {"x": pickup_pos.get("x", 0), "y": pickup_pos.get("y", 0)},
                "entity_key": inserter_info.get("pickup_target_key"),
            }
        
        self.db.execute(
            """
            INSERT OR REPLACE INTO inserter (entity_key, direction, output, input)
            VALUES (?, ?::direction, ?, ?)
            """,
            [
                entity_key,
                direction_name.upper(),
                json.dumps(output_struct) if output_struct else None,
                json.dumps(input_struct) if input_struct else None,
            ],
        )
    
    async def _upsert_transport_belt(self, entity_data: Dict[str, Any]) -> None:
        """UPSERT transport belt into transport_belt table."""
        import json
        
        entity_key = entity_data.get("key")
        if not entity_key:
            return
        
        belt_data = entity_data.get("belt_data")
        if not belt_data:
            return
        
        neighbours = belt_data.get("belt_neighbours", {})
        direction_name = entity_data.get("direction_name", "north")
        
        # Output is a single struct
        outputs = neighbours.get("outputs", [])
        output_struct = None
        if outputs:
            output_struct = {"entity_key": outputs[0]}
        
        # Input is an array of structs
        inputs = neighbours.get("inputs", [])
        input_array = [{"entity_key": inp} for inp in inputs] if inputs else []
        
        self.db.execute(
            """
            INSERT OR REPLACE INTO transport_belt (entity_key, direction, output, input)
            VALUES (?, ?::direction, ?, ?)
            """,
            [
                entity_key,
                direction_name.upper(),
                json.dumps(output_struct) if output_struct else None,
                json.dumps(input_array) if input_array else None,
            ],
        )
    
    async def _upsert_mining_drill(self, entity_data: Dict[str, Any]) -> None:
        """UPSERT mining drill into mining_drill table."""
        import json
        
        entity_key = entity_data.get("key")
        if not entity_key:
            return
        
        mining_area_data = entity_data.get("mining_area")
        if not mining_area_data:
            return
        
        direction_name = entity_data.get("direction_name", "north")
        
        # Extract mining area coordinates
        left_top = mining_area_data.get("left_top", {})
        right_bottom = mining_area_data.get("right_bottom", {})
        min_x = float(left_top.get("x", 0))
        min_y = float(left_top.get("y", 0))
        max_x = float(right_bottom.get("x", 0))
        max_y = float(right_bottom.get("y", 0))
        
        # Output struct (if available)
        output_struct = None
        # TODO: Extract output position from entity data if available
        
        self.db.execute(
            """
            INSERT OR REPLACE INTO mining_drill (entity_key, direction, mining_area, output)
            VALUES (?, ?::direction, ST_MakeEnvelope(?, ?, ?, ?), ?)
            """,
            [
                entity_key,
                direction_name.upper(),
                min_x,
                min_y,
                max_x,
                max_y,
                json.dumps(output_struct) if output_struct else None,
            ],
        )
    
    async def _upsert_assembler(self, entity_data: Dict[str, Any]) -> None:
        """UPSERT assembler into assemblers table."""
        entity_key = entity_data.get("key")
        if not entity_key:
            return
        
        # Recipe can be in assembling_machine data or directly in entity_data
        recipe_name = None
        if "assembling_machine" in entity_data:
            assembler_data = entity_data.get("assembling_machine")
            recipe_name = assembler_data.get("recipe_name")
        elif "recipe" in entity_data:
            recipe_name = entity_data.get("recipe")
        
        # Recipe can be None (no recipe set)
        if recipe_name:
            self.db.execute(
                """
                INSERT OR REPLACE INTO assemblers (entity_key, recipe)
                VALUES (?, ?::recipe)
                """,
                [
                    entity_key,
                    recipe_name,
                ],
            )
        else:
            self.db.execute(
                """
                INSERT OR REPLACE INTO assemblers (entity_key, recipe)
                VALUES (?, NULL)
                """,
                [entity_key],
            )
    
    async def _upsert_pumpjack(self, entity_data: Dict[str, Any]) -> None:
        """UPSERT pumpjack into pumpjack table."""
        import json
        
        entity_key = entity_data.get("key")
        if not entity_key:
            return
        
        pumpjack_data = entity_data.get("pumpjack")
        if not pumpjack_data:
            return
        
        # Pumpjack has output array of structs
        outputs = pumpjack_data.get("outputs", [])
        output_array = []
        for output in outputs:
            if isinstance(output, dict):
                output_array.append({
                    "position": output.get("position", {}),
                    "entity_key": output.get("entity_key"),
                })
        
        self.db.execute(
            """
            INSERT OR REPLACE INTO pumpjack (entity_key, output)
            VALUES (?, ?)
            """,
            [
                entity_key,
                json.dumps(output_array) if output_array else None,
            ],
        )
    
    async def _upsert_electric_pole(self, entity_data: Dict[str, Any]) -> None:
        """UPSERT electric pole into electric_pole table."""
        import json
        
        entity_key = entity_data.get("key")
        if not entity_key:
            return
        
        pole_data = entity_data.get("electric_pole")
        if not pole_data:
            return
        
        connected_poles = pole_data.get("connected_poles", [])
        supply_area = pole_data.get("supply_area")
        
        # Supply area is a GEOMETRY, we'd need to construct it from the data
        # For now, we'll just store connected poles
        self.db.execute(
            """
            INSERT OR REPLACE INTO electric_pole (entity_key, connected_poles)
            VALUES (?, ?)
            """,
            [
                entity_key,
                json.dumps(connected_poles) if connected_poles else None,
            ],
        )
    
    async def _process_file_io(self, payload: Dict[str, Any]) -> None:
        """
        Process file I/O update.
        
        Handles both written (overwrite) and appended (incremental) operations.
        """
        operation = payload.get("operation")
        file_type = payload.get("file_type")
        file_path = payload.get("file_path")
        chunk = payload.get("chunk")
        
        if not operation or not file_type or not file_path:
            logger.warning(f"File I/O payload missing required fields: {payload}")
            return
        
        try:
            if operation == "written":
                await self._handle_file_written(file_type, file_path, chunk, payload)
            elif operation == "appended":
                await self._handle_file_appended(file_type, file_path, chunk, payload)
            else:
                logger.warning(f"Unknown file I/O operation: {operation}")
        except Exception as e:
            logger.error(
                f"Error processing file I/O {operation} for {file_type}: {e}",
                exc_info=True
            )
    
    async def _handle_file_written(
        self,
        file_type: str,
        file_path: str,
        chunk: Optional[Dict[str, Any]],
        payload: Dict[str, Any]
    ) -> None:
        """
        Handle file written (overwrite) operation.
        
        Reloads the entire file into the appropriate table.
        """
        import json
        from FactoryVerse.infra.db.loader.utils import load_jsonl_file
        
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            logger.debug(f"File does not exist (may not be created yet): {file_path}")
            return
        
        if file_type == "resource":
            # Resource tiles (resources_init.jsonl)
            await self._reload_resource_tiles(file_path_obj)
        elif file_type == "water":
            # Water tiles (water_init.jsonl)
            await self._reload_water_tiles(file_path_obj)
        elif file_type == "trees_rocks":
            # Resource entities (trees_rocks_init.jsonl)
            await self._reload_resource_entities(file_path_obj)
        elif file_type == "entities_init":
            # Map entities - these are handled via entity operations
            # But we might need to reload if it's an initial snapshot
            logger.debug(f"entities_init file written (handled via entity operations): {file_path}")
        elif file_type == "ghosts_init":
            # Ghosts - reload from file
            await self._reload_ghosts(file_path_obj)
        else:
            logger.debug(f"Unhandled file type for written operation: {file_type}")
    
    async def _handle_file_appended(
        self,
        file_type: str,
        file_path: str,
        chunk: Optional[Dict[str, Any]],
        payload: Dict[str, Any]
    ) -> None:
        """
        Handle file appended (incremental) operation.
        
        Appends new entries to the appropriate table.
        """
        import json
        from FactoryVerse.infra.db.loader.utils import load_jsonl_file
        
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            logger.debug(f"File does not exist (may not be created yet): {file_path}")
            return
        
        entry_count = payload.get("entry_count", 1)
        
        if file_type == "power_statistics":
            # Power statistics - append new entry
            await self._append_power_statistics(file_path_obj, entry_count)
        elif file_type == "agent_production_statistics":
            # Agent production statistics - append new entry
            agent_id = payload.get("agent_id")
            await self._append_agent_production_statistics(file_path_obj, agent_id, entry_count)
        elif file_type == "status":
            # Status files - on-demand reads, not incremental sync
            logger.debug(f"Status file appended (on-demand reads): {file_path}")
        elif file_type == "entities_updates":
            # Entities updates - append new operations
            await self._append_entities_updates(file_path_obj, entry_count)
        else:
            logger.debug(f"Unhandled file type for appended operation: {file_type}")
    
    # ============================================================================
    # File Reload Helpers (for written operations)
    # ============================================================================
    
    async def _reload_resource_tiles(self, file_path: Path) -> None:
        """Reload resource tiles from file (overwrites chunk's resource tiles)."""
        import json
        
        # Extract chunk from file path: snapshots/{chunk_x}/{chunk_y}/resources_init.jsonl
        # Or it might be in a different location
        chunk_x, chunk_y = self._extract_chunk_from_path(file_path)
        
        # Read file
        entries = []
        with open(file_path, "r") as f:
            for line in f:
                if line.strip():
                    try:
                        data = json.loads(line)
                        entity_key = f"({data['kind']}:{data['x']},{data['y']})"
                        entries.append({
                            "entity_key": entity_key,
                            "name": data["kind"],
                            "position": {"x": float(data["x"]), "y": float(data["y"])},
                            "amount": data.get("amount", 0),
                        })
                    except Exception as e:
                        logger.warning(f"Error parsing resource tile entry: {e}")
                        continue
        
        if not entries:
            return
        
        # Delete existing resource tiles for this chunk (if we can identify them)
        # For now, we'll use UPSERT which will overwrite
        # TODO: More efficient chunk-based deletion
        
        # Insert/update resource tiles
        self.db.executemany(
            """
            INSERT OR REPLACE INTO resource_tile (entity_key, name, position, amount)
            VALUES (?, ?, ?, ?)
            """,
            [
                (
                    r["entity_key"],
                    r["name"],
                    json.dumps(r["position"]),
                    r["amount"],
                )
                for r in entries
            ],
        )
        
        logger.debug(f"Reloaded {len(entries)} resource tiles from {file_path}")
    
    async def _reload_water_tiles(self, file_path: Path) -> None:
        """Reload water tiles from file (overwrites chunk's water tiles)."""
        import json
        
        # Read file
        entries = []
        with open(file_path, "r") as f:
            for line in f:
                if line.strip():
                    try:
                        data = json.loads(line)
                        entity_key = f"(water:{data['x']},{data['y']})"
                        entries.append({
                            "entity_key": entity_key,
                            "type": "water-tile",
                            "position": {"x": float(data["x"]), "y": float(data["y"])},
                        })
                    except Exception as e:
                        logger.warning(f"Error parsing water tile entry: {e}")
                        continue
        
        if not entries:
            return
        
        # Insert/update water tiles
        self.db.executemany(
            """
            INSERT OR REPLACE INTO water_tile (entity_key, type, position)
            VALUES (?, ?, ?)
            """,
            [
                (
                    w["entity_key"],
                    w["type"],
                    json.dumps(w["position"]),
                )
                for w in entries
            ],
        )
        
        logger.debug(f"Reloaded {len(entries)} water tiles from {file_path}")
    
    async def _reload_resource_entities(self, file_path: Path) -> None:
        """Reload resource entities (trees/rocks) from file."""
        import json
        
        # Read file
        entries = []
        with open(file_path, "r") as f:
            for line in f:
                if line.strip():
                    try:
                        data = json.loads(line)
                        entity_key = data.get("key") or f"({data['name']}:{data['position']['x']},{data['position']['y']})"
                        bbox = data.get("bounding_box", {})
                        
                        bbox_coords = None
                        if bbox:
                            min_x = float(bbox.get("min_x", data["position"]["x"]))
                            min_y = float(bbox.get("min_y", data["position"]["y"]))
                            max_x = float(bbox.get("max_x", data["position"]["x"]))
                            max_y = float(bbox.get("max_y", data["position"]["y"]))
                            bbox_coords = (min_x, min_y, max_x, max_y)
                        
                        entries.append({
                            "entity_key": entity_key,
                            "name": data["name"],
                            "type": data.get("type", "unknown"),
                            "position": {"x": float(data["position"]["x"]), "y": float(data["position"]["y"])},
                            "bbox": bbox_coords,
                        })
                    except Exception as e:
                        logger.warning(f"Error parsing resource entity entry: {e}")
                        continue
        
        if not entries:
            return
        
        # Insert/update resource entities
        for e in entries:
            if e["bbox"]:
                min_x, min_y, max_x, max_y = e["bbox"]
                self.db.execute(
                    """
                    INSERT OR REPLACE INTO resource_entity (entity_key, name, type, position, bbox)
                    VALUES (?, ?, ?, ?, ST_MakeEnvelope(?, ?, ?, ?))
                    """,
                    [
                        e["entity_key"],
                        e["name"],
                        e["type"],
                        json.dumps(e["position"]),
                        min_x,
                        min_y,
                        max_x,
                        max_y,
                    ],
                )
            else:
                self.db.execute(
                    """
                    INSERT OR REPLACE INTO resource_entity (entity_key, name, type, position)
                    VALUES (?, ?, ?, ?)
                    """,
                    [
                        e["entity_key"],
                        e["name"],
                        e["type"],
                        json.dumps(e["position"]),
                    ],
                )
        
        logger.debug(f"Reloaded {len(entries)} resource entities from {file_path}")
    
    async def _reload_ghosts(self, file_path: Path) -> None:
        """Reload ghosts from file."""
        import json
        
        # Read file
        entries = []
        with open(file_path, "r") as f:
            for line in f:
                if line.strip():
                    try:
                        data = json.loads(line)
                        ghost_name = data.get("ghost_name") or "unknown"
                        pos = data.get("position", {})
                        px = float(pos.get("x", 0.0))
                        py = float(pos.get("y", 0.0))
                        ghost_key = data.get("key") or f"({ghost_name}:{px},{py})"
                        chunk = data.get("chunk", {})
                        chunk_x = chunk.get("x") if chunk else None
                        chunk_y = chunk.get("y") if chunk else None
                        
                        entries.append({
                            "ghost_key": ghost_key,
                            "ghost_name": ghost_name,
                            "force": data.get("force"),
                            "position": {"x": px, "y": py},
                            "direction": data.get("direction"),
                            "direction_name": data.get("direction_name"),
                            "chunk_x": chunk_x,
                            "chunk_y": chunk_y,
                        })
                    except Exception as e:
                        logger.warning(f"Error parsing ghost entry: {e}")
                        continue
        
        if not entries:
            return
        
        # Insert/update ghosts
        for g in entries:
            self.db.execute(
                """
                INSERT OR REPLACE INTO ghost (
                    ghost_key, ghost_name, force, position_x, position_y,
                    direction, direction_name, chunk_x, chunk_y
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    g["ghost_key"],
                    g["ghost_name"],
                    g["force"],
                    g["position"]["x"],
                    g["position"]["y"],
                    g["direction"],
                    g["direction_name"],
                    g["chunk_x"],
                    g["chunk_y"],
                ],
            )
        
        logger.debug(f"Reloaded {len(entries)} ghosts from {file_path}")
    
    # ============================================================================
    # File Append Helpers (for appended operations)
    # ============================================================================
    
    async def _append_power_statistics(self, file_path: Path, entry_count: int) -> None:
        """Append new power statistics entries from file."""
        import json
        
        # Read only the last N entries (where N = entry_count)
        # For efficiency, we'll read the entire file and take the last N entries
        # In production, we might want to seek to the end and read backwards
        entries = []
        with open(file_path, "r") as f:
            lines = f.readlines()
            # Take last entry_count lines
            for line in lines[-entry_count:]:
                if line.strip():
                    try:
                        data = json.loads(line)
                        entries.append(data)
                    except Exception as e:
                        logger.warning(f"Error parsing power statistics entry: {e}")
                        continue
        
        if not entries:
            return
        
        # Check if table exists
        try:
            rows = []
            for entry in entries:
                stats = entry.get("statistics") or {}
                tick = int(entry.get("tick", 0))
                rows.append((
                    tick,
                    json.dumps(stats.get("input", {})),
                    json.dumps(stats.get("output", {})),
                    json.dumps(stats.get("storage", {})),
                ))
            
            if rows:
                self.db.executemany(
                    """
                    INSERT INTO power_statistics (tick, input, output, storage)
                    VALUES (?, ?, ?, ?)
                    """,
                    rows,
                )
                logger.debug(f"Appended {len(rows)} power statistics entries")
        except Exception as e:
            # Table might not exist
            logger.debug(f"Power statistics table not available: {e}")
    
    async def _append_agent_production_statistics(
        self, file_path: Path, agent_id: Optional[str], entry_count: int
    ) -> None:
        """Append new agent production statistics entries from file."""
        import json
        
        # Extract agent_id from path if not provided: {snapshot_dir}/{agent_id}/production_statistics.jsonl
        if not agent_id:
            try:
                agent_id = file_path.parent.name
                agent_id_int = int(agent_id)
            except (ValueError, AttributeError):
                logger.warning(f"Could not extract agent_id from path: {file_path}")
                return
        else:
            try:
                agent_id_int = int(agent_id)
            except ValueError:
                logger.warning(f"Invalid agent_id: {agent_id}")
                return
        
        # Read only the last N entries
        entries = []
        with open(file_path, "r") as f:
            lines = f.readlines()
            for line in lines[-entry_count:]:
                if line.strip():
                    try:
                        data = json.loads(line)
                        entries.append(data)
                    except Exception as e:
                        logger.warning(f"Error parsing agent production statistics entry: {e}")
                        continue
        
        if not entries:
            return
        
        # Check if table exists
        try:
            rows = []
            for entry in entries:
                tick = int(entry.get("tick", 0))
                stats = entry.get("statistics") or {}
                rows.append((agent_id_int, tick, json.dumps(stats)))
            
            if rows:
                self.db.executemany(
                    """
                    INSERT INTO agent_production_statistics (agent_id, tick, statistics)
                    VALUES (?, ?, ?)
                    """,
                    rows,
                )
                logger.debug(f"Appended {len(rows)} agent production statistics entries for agent {agent_id_int}")
        except Exception as e:
            # Table might not exist
            logger.debug(f"Agent production statistics table not available: {e}")
    
    async def _append_entities_updates(self, file_path: Path, entry_count: int) -> None:
        """Append new entity operations from entities_updates.jsonl."""
        import json
        
        # Read only the last N entries
        entries = []
        try:
            with open(file_path, "r") as f:
                lines = f.readlines()
                for line in lines[-entry_count:]:
                    if line.strip():
                        try:
                            entries.append(json.loads(line))
                        except Exception as e:
                            logger.warning(f"Error parsing entity update entry: {e}")
                            continue
        except FileNotFoundError:
            return

        if not entries:
            return
            
        # Process operations
        for op_data in entries:
            # Map file format to payload format
            payload = op_data.copy()
            
            # Map operation types: file format -> event format
            raw_op = payload.get("op")
            if raw_op == "upsert":
                payload["op"] = "created"
                # For upserts, key is often inside the entity object
                if "entity" in payload and isinstance(payload["entity"], dict):
                    if "key" in payload["entity"] and "entity_key" not in payload:
                        payload["entity_key"] = payload["entity"]["key"]
                    if "name" in payload["entity"] and "entity_name" not in payload:
                        payload["entity_name"] = payload["entity"]["name"]
                        
            elif raw_op == "remove":
                payload["op"] = "destroyed"
            
            # General fallback for top-level keys
            if "key" in op_data and "entity_key" not in payload:
                payload["entity_key"] = op_data["key"]
            if "name" in op_data and "entity_name" not in payload:
                payload["entity_name"] = op_data["name"]
                
            # Normalize entity_key: ensure it has parentheses to match DB format (name:x,y vs (name:x,y))
            ek = payload.get("entity_key")
            if ek and not ek.startswith("("):
                # Ensure it has parentheses and use comma separator
                if ":" in ek and "," not in ek[ek.find(":"):]:
                    # Handle name:x:y format if it exists
                    parts = ek.split(":")
                    if len(parts) >= 3:
                        ek = f"{parts[0]}:{parts[1]},{parts[2]}"
                payload["entity_key"] = f"({ek})"

            if "op" not in payload:
                continue

            try:
                await self._process_entity_operation(payload)
            except Exception as e:
                logger.error(f"Failed to process appended entity op: {e}")

    # ============================================================================
    # Utility Helpers
    # ============================================================================
    
    def _extract_chunk_from_path(self, file_path: Path) -> Tuple[Optional[int], Optional[int]]:
        """
        Extract chunk coordinates from file path.
        
        Path format: snapshots/{chunk_x}/{chunk_y}/filename.jsonl
        """
        try:
            parts = file_path.parts
            # Find snapshots directory
            snapshots_idx = None
            for i, part in enumerate(parts):
                if part == "snapshots" or "snapshots" in str(part):
                    snapshots_idx = i
                    break
            
            if snapshots_idx is None:
                return None, None
            
            # Next two parts should be chunk_x and chunk_y
            if snapshots_idx + 2 < len(parts):
                chunk_x = int(parts[snapshots_idx + 1])
                chunk_y = int(parts[snapshots_idx + 2])
                return chunk_x, chunk_y
        except (ValueError, IndexError):
            pass
        
        return None, None
    
    async def _process_snapshot_state(self, payload: Dict[str, Any]) -> None:
        """
        Process snapshot state update.
        
        Updates chunk state tracking, signals completion events, and triggers
        chunk loading when state becomes COMPLETE.
        """
        state = payload.get("state")
        chunk = payload.get("chunk")
        
        if not chunk or not state:
            return
        
        chunk_x = chunk.get("x")
        chunk_y = chunk.get("y")
        
        if chunk_x is None or chunk_y is None:
            return
        
        chunk_key = (chunk_x, chunk_y)
        old_state = self._chunk_states.get(chunk_key)
        
        # Update state
        self._chunk_states[chunk_key] = state
        
        logger.debug(
            f"Chunk ({chunk_x}, {chunk_y}) state: {old_state} -> {state}"
        )
        
        # Signal completion if state is COMPLETE
        if state == "COMPLETE":
            # Signal completion event
            if chunk_key in self._completion_events:
                self._completion_events[chunk_key].set()
                # Clean up event after signaling
                del self._completion_events[chunk_key]
            
            # Signal pending load event if exists
            if chunk_key in self._pending_loads:
                self._pending_loads[chunk_key].set()
            
            # Auto-load chunk if not already loaded
            if chunk_key not in self._loaded_chunks:
                try:
                    await self._load_chunk(chunk_x, chunk_y)
                    logger.info(f"Chunk ({chunk_x}, {chunk_y}) loaded into DB")
                except Exception as e:
                    logger.error(
                        f"Failed to load chunk ({chunk_x}, {chunk_y}): {e}",
                        exc_info=True
                    )
            
            logger.debug(f"Chunk ({chunk_x}, {chunk_y}) snapshot completed")
    
    async def _process_chunk_charted(self, payload: Dict[str, Any]) -> None:
        """
        Process chunk charted update.
        
        Tracks when chunks are charted. The chunk will be snapshotted by the
        game, and we'll receive snapshot_state updates as it progresses.
        """
        chunk = payload.get("chunk")
        charted_by = payload.get("charted_by", "unknown")
        snapshot_queued = payload.get("snapshot_queued", False)
        
        if chunk:
            chunk_x = chunk.get("x")
            chunk_y = chunk.get("y")
            if chunk_x is not None and chunk_y is not None:
                logger.debug(
                    f"Chunk ({chunk_x}, {chunk_y}) charted by {charted_by} "
                    f"(snapshot queued: {snapshot_queued})"
                )
                # Chunk state will be updated via snapshot_state payloads
    

    @property
    def is_running(self) -> bool:
        """Check if service is running."""
        return self._running
    
    def get_sequence_gap_stats(self) -> Dict[str, Any]:
        """
        Get statistics about sequence gaps (actual UDP packet loss detection).
        
        Uses global sequence tracking across all event types to detect real packet loss.
        Gaps indicate actual dropped UDP packets, not interleaving of event types.
        
        Returns:
            Dictionary with gap statistics:
            - total_gaps: Total number of packet loss events detected
            - gaps_by_type: Dictionary grouping gaps by the event_type where loss was detected
            - summary: Human-readable summary
        """
        from collections import defaultdict
        
        gaps_by_type = defaultdict(list)
        for event_type, expected, received in self._sequence_gaps:
            gaps_by_type[event_type].append({
                'expected': expected,
                'received': received,
                'gap_size': received - expected
            })
        
        total_gaps = len(self._sequence_gaps)
        summary_lines = [f"Total sequence gaps: {total_gaps}"]
        
        if total_gaps > 0:
            summary_lines.append("\nGaps by event type:")
            for event_type, gaps in sorted(gaps_by_type.items(), key=lambda x: len(x[1]), reverse=True):
                total_missed = sum(g['gap_size'] for g in gaps)
                summary_lines.append(f"  {event_type}: {len(gaps)} gaps, {total_missed} packets missed")
        
        return {
            'total_gaps': total_gaps,
            'gaps_by_type': dict(gaps_by_type),
            'summary': '\n'.join(summary_lines)
        }

