"""Map View System - Non-blocking parallel observation interface for Factorio game state.

Provides Python agents with a spatial view of the map by reading snapshot files
and staying synchronized via UDP notifications.
"""

import asyncio
import json
import queue
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Literal
from datetime import datetime

import duckdb

from FactoryVerse.infra.factorio_client_setup import get_client_script_output_dir
from FactoryVerse.infra.docker.factorio_server_manager import FactorioServerManager
from FactoryVerse.infra.udp_dispatcher import UDPDispatcher, get_udp_dispatcher


def get_snapshot_dir(mode: Literal["client", "server"], 
                     instance_id: int = 0,
                     work_dir: Optional[Path] = None,
                     script_output_dir: Optional[Path] = None) -> Path:
    """
    Get snapshot directory path based on mode.
    
    Uses infrastructure modules to determine correct paths:
    - Client: Uses factorio_client_setup.get_client_script_output_dir()
    - Server: Uses FactorioServerManager.get_server_script_output_dir()
    
    Args:
        mode: "client" or "server"
        instance_id: Server instance ID (only used for server mode, default: 0)
        work_dir: Project work directory (only used for server mode, default: current directory)
        script_output_dir: Override script-output directory (optional)
    
    Returns:
        Path to snapshot directory (script-output/factoryverse/snapshots)
    """
    if script_output_dir is None:
        if mode == "client":
            script_output_dir = get_client_script_output_dir()
        elif mode == "server":
            if work_dir is None:
                work_dir = Path.cwd()
            server_mgr = FactorioServerManager(work_dir)
            script_output_dir = server_mgr.get_server_script_output_dir(instance_id)
        else:
            raise ValueError(f"Invalid mode: {mode}. Must be 'client' or 'server'")
    
    return script_output_dir / "factoryverse" / "snapshots"


class FileWatcher:
    """Monitors snapshot files and listens to UDP notifications for incremental updates."""
    
    def __init__(self, snapshot_dir: Path, udp_dispatcher: Optional[UDPDispatcher] = None):
        """
        Initialize the file watcher.
        
        Args:
            snapshot_dir: Path to snapshot directory (script-output/factoryverse/snapshots)
            udp_dispatcher: Optional UDPDispatcher instance. If None, uses global dispatcher.
        """
        self.snapshot_dir = Path(snapshot_dir)
        self.udp_dispatcher = udp_dispatcher
        self.running = False
        self.event_queue = queue.Queue()  # Thread-safe queue
    
    async def start(self):
        """Subscribe to UDP dispatcher for file events."""
        # Get dispatcher (use provided one or global)
        if self.udp_dispatcher is None:
            self.udp_dispatcher = get_udp_dispatcher()
        
        # Ensure dispatcher is running
        if not self.udp_dispatcher.is_running():
            await self.udp_dispatcher.start()
        
        # Subscribe to file events
        self.udp_dispatcher.subscribe("file_created", self._handle_udp_message)
        self.udp_dispatcher.subscribe("file_updated", self._handle_udp_message)
        self.udp_dispatcher.subscribe("file_deleted", self._handle_udp_message)
        
        self.running = True
        print(f"✅ FileWatcher subscribed to UDP dispatcher")
    
    def _handle_udp_message(self, payload: Dict[str, Any]):
        """Handle UDP message from dispatcher (called by dispatcher thread)."""
        event_type = payload.get('event_type')
        
        # Only process file events (safety check)
        if event_type in ('file_created', 'file_updated', 'file_deleted'):
            # Put event in thread-safe queue
            try:
                self.event_queue.put_nowait(payload)
            except queue.Full:
                print(f"⚠️  Event queue full, dropping event: {event_type}")
    
    def get_event(self, timeout: float = 0.1) -> Optional[Dict[str, Any]]:
        """Get next file event from queue (thread-safe)."""
        try:
            return self.event_queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    async def stop(self):
        """Unsubscribe from UDP dispatcher."""
        if self.udp_dispatcher and self.running:
            self.udp_dispatcher.unsubscribe("file_created", self._handle_udp_message)
            self.udp_dispatcher.unsubscribe("file_updated", self._handle_udp_message)
            self.udp_dispatcher.unsubscribe("file_deleted", self._handle_udp_message)
        
        self.running = False
        print("✅ FileWatcher stopped")


class MapView:
    """Non-blocking map view for agent queries using DuckDB."""
    
    def __init__(self, 
                 mode: Literal["client", "server"] = "server",
                 instance_id: int = 0,
                 work_dir: Optional[Path] = None,
                 snapshot_dir: Optional[Path] = None,
                 udp_dispatcher: Optional[UDPDispatcher] = None):
        """
        Initialize map view with file watcher and DuckDB.
        
        Args:
            mode: "client" or "server" - determines script-output directory location
            instance_id: Server instance ID (only used for server mode, default: 0)
            work_dir: Project work directory (only used for server mode, default: current directory)
            snapshot_dir: Override snapshot directory path (optional, auto-detected if not provided)
            udp_dispatcher: Optional UDPDispatcher instance. If None, uses global dispatcher.
        """
        if snapshot_dir is None:
            snapshot_dir = get_snapshot_dir(mode, instance_id, work_dir)
        
        self.snapshot_dir = Path(snapshot_dir)
        self.mode = mode
        self.instance_id = instance_id
        self.file_watcher = FileWatcher(snapshot_dir, udp_dispatcher)
        
        # Create in-memory DuckDB database
        self.db = duckdb.connect(':memory:')
        self._create_schema()
        
        # ID counters for resources and water (DuckDB doesn't support auto-increment)
        self._resource_id_counter = 1
        self._water_id_counter = 1
        
        self.initial_load_complete = False
        self._update_task = None
        
    def _create_schema(self):
        """Create DuckDB tables for entities, resources, and water."""
        # Entities table
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                unit_number BIGINT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                position_x REAL NOT NULL,
                position_y REAL NOT NULL,
                direction INTEGER,
                direction_name TEXT,
                recipe TEXT,
                component_type TEXT,
                chunk_x INTEGER NOT NULL,
                chunk_y INTEGER NOT NULL,
                tick BIGINT,
                belt_data JSON,
                pipe_data JSON,
                inserter JSON,
                data JSON NOT NULL
            )
        """)
        
        # Resources table
        # Note: DuckDB doesn't support auto-increment, so we'll generate IDs manually
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS resources (
                id BIGINT PRIMARY KEY,
                chunk_x INTEGER NOT NULL,
                chunk_y INTEGER NOT NULL,
                kind TEXT NOT NULL,
                x INTEGER NOT NULL,
                y INTEGER NOT NULL,
                amount REAL NOT NULL,
                tick BIGINT
            )
        """)
        
        # Water table
        # Note: DuckDB doesn't support auto-increment, so we'll generate IDs manually
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS water (
                id BIGINT PRIMARY KEY,
                chunk_x INTEGER NOT NULL,
                chunk_y INTEGER NOT NULL,
                x INTEGER NOT NULL,
                y INTEGER NOT NULL,
                tick BIGINT
            )
        """)
        
        # Create indexes for spatial queries
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_entities_position ON entities(position_x, position_y)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_entities_chunk ON entities(chunk_x, chunk_y)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_resources_position ON resources(x, y)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_resources_chunk ON resources(chunk_x, chunk_y)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_water_position ON water(x, y)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_water_chunk ON water(chunk_x, chunk_y)")
    
    async def start(self):
        """Start the file watcher and begin processing events."""
        await self.file_watcher.start()
        self._update_task = asyncio.create_task(self._process_events_loop())
    
    async def _process_events_loop(self):
        """Process file events from UDP notifications."""
        while self.file_watcher.running:
            event = self.file_watcher.get_event(timeout=0.1)
            if event:
                await self._handle_file_event(event)
            await asyncio.sleep(0.01)  # Small delay to prevent busy waiting
    
    async def _handle_file_event(self, event: Dict[str, Any]):
        """Handle a file event (create/update/delete)."""
        event_type = event.get('event_type')
        file_type = event.get('file_type')
        chunk = event.get('chunk', {})
        chunk_x = chunk.get('x')
        chunk_y = chunk.get('y')
        file_path = event.get('file_path')
        
        if not chunk_x or chunk_y is None:
            return
        
        # Resolve file path
        if file_path:
            full_path = self.snapshot_dir / file_path
        else:
            # Reconstruct path from event data
            if file_type == 'entity':
                position = event.get('position', {})
                entity_name = event.get('entity_name', 'unknown')
                component_type = event.get('component_type', 'entities')
                pos_x = int(position.get('x', 0))
                pos_y = int(position.get('y', 0))
                filename = f"{pos_x}_{pos_y}_{entity_name}.json"
                full_path = self.snapshot_dir / str(chunk_x) / str(chunk_y) / component_type / filename
            elif file_type in ('resource', 'water'):
                filename = f"{file_type}s.jsonl"
                full_path = self.snapshot_dir / str(chunk_x) / str(chunk_y) / "resources" / filename
            else:
                return
        
        if event_type == 'file_deleted':
            await self._handle_file_delete(file_type, chunk_x, chunk_y, full_path, event)
        elif event_type in ('file_created', 'file_updated'):
            await self._handle_file_update(file_type, chunk_x, chunk_y, full_path, event)
    
    async def _handle_file_update(self, file_type: str, chunk_x: int, chunk_y: int, 
                                  file_path: Path, event: Dict[str, Any]):
        """Handle file create/update event."""
        if not file_path.exists():
            return
        
        if file_type == 'entity':
            await self._load_entity_file(file_path, chunk_x, chunk_y, event)
        elif file_type == 'resource':
            await self._load_resource_file(file_path, chunk_x, chunk_y, event)
        elif file_type == 'water':
            await self._load_water_file(file_path, chunk_x, chunk_y, event)
    
    async def _handle_file_delete(self, file_type: str, chunk_x: int, chunk_y: int,
                                  file_path: Path, event: Dict[str, Any]):
        """Handle file delete event."""
        if file_type == 'entity':
            # Try to get unit_number from event first
            unit_number = event.get('unit_number')
            
            # If not in event, try to read from file before it's deleted
            if not unit_number and file_path.exists():
                try:
                    with open(file_path, 'r') as f:
                        entity_data = json.load(f)
                        unit_number = entity_data.get('unit_number')
                except Exception:
                    pass
            
            # If we have unit_number, delete by it
            if unit_number:
                self.db.execute("DELETE FROM entities WHERE unit_number = ?", [unit_number])
            else:
                # Fallback: delete by position and name from file path
                # Format: {pos_x}_{pos_y}_{entity_name}.json
                try:
                    filename = file_path.stem
                    parts = filename.split('_')
                    if len(parts) >= 3:
                        pos_x = float(parts[0])
                        pos_y = float(parts[1])
                        self.db.execute(
                            "DELETE FROM entities WHERE chunk_x = ? AND chunk_y = ? AND position_x = ? AND position_y = ?",
                            [chunk_x, chunk_y, pos_x, pos_y]
                        )
                except Exception as e:
                    print(f"⚠️  Could not delete entity from {file_path}: {e}")
        elif file_type == 'resource':
            # Delete all resources in this chunk (resources.jsonl is chunk-level)
            self.db.execute("DELETE FROM resources WHERE chunk_x = ? AND chunk_y = ?", [chunk_x, chunk_y])
        elif file_type == 'water':
            # Delete all water in this chunk
            self.db.execute("DELETE FROM water WHERE chunk_x = ? AND chunk_y = ?", [chunk_x, chunk_y])
    
    async def _load_entity_file(self, file_path: Path, chunk_x: int, chunk_y: int, event: Dict[str, Any]):
        """Load an entity JSON file into DuckDB."""
        try:
            with open(file_path, 'r') as f:
                entity_data = json.load(f)
            
            # Extract fields
            unit_number = entity_data.get('unit_number')
            if not unit_number:
                return
            
            position = entity_data.get('position', {})
            position_x = position.get('x', 0)
            position_y = position.get('y', 0)
            
            # Upsert entity (replace if exists)
            self.db.execute("""
                INSERT INTO entities (
                    unit_number, name, type, position_x, position_y,
                    direction, direction_name, recipe, component_type,
                    chunk_x, chunk_y, tick, belt_data, pipe_data, inserter, data
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (unit_number) DO UPDATE SET
                    name = EXCLUDED.name,
                    type = EXCLUDED.type,
                    position_x = EXCLUDED.position_x,
                    position_y = EXCLUDED.position_y,
                    direction = EXCLUDED.direction,
                    direction_name = EXCLUDED.direction_name,
                    recipe = EXCLUDED.recipe,
                    component_type = EXCLUDED.component_type,
                    chunk_x = EXCLUDED.chunk_x,
                    chunk_y = EXCLUDED.chunk_y,
                    tick = EXCLUDED.tick,
                    belt_data = EXCLUDED.belt_data,
                    pipe_data = EXCLUDED.pipe_data,
                    inserter = EXCLUDED.inserter,
                    data = EXCLUDED.data
            """, [
                unit_number,
                entity_data.get('name'),
                entity_data.get('type'),
                position_x,
                position_y,
                entity_data.get('direction'),
                entity_data.get('direction_name'),
                entity_data.get('recipe'),
                event.get('component_type') or self._determine_component_type(entity_data.get('type'), entity_data.get('name')),
                chunk_x,
                chunk_y,
                event.get('tick'),
                json.dumps(entity_data.get('belt_data')) if entity_data.get('belt_data') else None,
                json.dumps(entity_data.get('pipe_data')) if entity_data.get('pipe_data') else None,
                json.dumps(entity_data.get('inserter')) if entity_data.get('inserter') else None,
                json.dumps(entity_data)
            ])
        except Exception as e:
            print(f"⚠️  Error loading entity file {file_path}: {e}")
    
    async def _load_resource_file(self, file_path: Path, chunk_x: int, chunk_y: int, event: Dict[str, Any]):
        """Load a resources.jsonl file into DuckDB."""
        try:
            # Delete existing resources for this chunk
            self.db.execute("DELETE FROM resources WHERE chunk_x = ? AND chunk_y = ?", [chunk_x, chunk_y])
            
            # Load new resources
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    resource = json.loads(line)
                    resource_id = self._resource_id_counter
                    self._resource_id_counter += 1
                    self.db.execute("""
                        INSERT INTO resources (id, chunk_x, chunk_y, kind, x, y, amount, tick)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, [
                        resource_id,
                        chunk_x,
                        chunk_y,
                        resource.get('kind'),
                        resource.get('x'),
                        resource.get('y'),
                        resource.get('amount', 0),
                        event.get('tick')
                    ])
        except Exception as e:
            print(f"⚠️  Error loading resource file {file_path}: {e}")
    
    async def _load_water_file(self, file_path: Path, chunk_x: int, chunk_y: int, event: Dict[str, Any]):
        """Load a water.jsonl file into DuckDB."""
        try:
            # Delete existing water for this chunk
            self.db.execute("DELETE FROM water WHERE chunk_x = ? AND chunk_y = ?", [chunk_x, chunk_y])
            
            # Load new water tiles
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    water = json.loads(line)
                    water_id = self._water_id_counter
                    self._water_id_counter += 1
                    self.db.execute("""
                        INSERT INTO water (id, chunk_x, chunk_y, x, y, tick)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, [
                        water_id,
                        chunk_x,
                        chunk_y,
                        water.get('x'),
                        water.get('y'),
                        event.get('tick')
                    ])
        except Exception as e:
            print(f"⚠️  Error loading water file {file_path}: {e}")
    
    def _determine_component_type(self, entity_type: str, entity_name: str) -> str:
        """Determine component type from entity type and name."""
        if entity_type in ('transport-belt', 'underground-belt', 'splitter', 'loader', 'loader-1x1', 'linked-belt'):
            return 'belts'
        elif entity_type in ('pipe', 'pipe-to-ground'):
            return 'pipes'
        elif entity_type in ('electric-pole', 'power-switch', 'substation'):
            return 'poles'
        else:
            return 'entities'
    
    async def load_initial_snapshot(self):
        """Load all existing snapshot files into DuckDB."""
        print("🔄 Loading initial snapshot...")
        start_time = time.time()
        
        chunk_dirs = []
        if self.snapshot_dir.exists():
            for chunk_x_dir in self.snapshot_dir.iterdir():
                # Handle both positive and negative chunk coordinates
                # Positive: "0", "1", "2" etc. (isdigit() returns True)
                # Negative: "-1", "-2", "-3" etc. (starts with '-' then digits)
                chunk_x_name = chunk_x_dir.name
                is_valid_chunk_x = (
                    chunk_x_dir.is_dir() and 
                    (chunk_x_name.isdigit() or (chunk_x_name.startswith('-') and chunk_x_name[1:].isdigit()))
                )
                if is_valid_chunk_x:
                    for chunk_y_dir in chunk_x_dir.iterdir():
                        chunk_y_name = chunk_y_dir.name
                        is_valid_chunk_y = (
                            chunk_y_dir.is_dir() and 
                            (chunk_y_name.isdigit() or (chunk_y_name.startswith('-') and chunk_y_name[1:].isdigit()))
                        )
                        if is_valid_chunk_y:
                            chunk_dirs.append((int(chunk_x_dir.name), int(chunk_y_dir.name), chunk_y_dir))
        
        total_chunks = len(chunk_dirs)
        loaded = 0
        
        for chunk_x, chunk_y, chunk_dir in chunk_dirs:
            # Load entities
            for component_type in ['entities', 'belts', 'pipes', 'poles']:
                component_dir = chunk_dir / component_type
                if component_dir.exists():
                    for entity_file in component_dir.glob('*.json'):
                        await self._load_entity_file(entity_file, chunk_x, chunk_y, {'tick': 0})
            
            # Load resources
            resources_file = chunk_dir / 'resources' / 'resources.jsonl'
            if resources_file.exists():
                await self._load_resource_file(resources_file, chunk_x, chunk_y, {'tick': 0})
            
            # Load water
            water_file = chunk_dir / 'resources' / 'water.jsonl'
            if water_file.exists():
                await self._load_water_file(water_file, chunk_x, chunk_y, {'tick': 0})
            
            loaded += 1
            if loaded % 10 == 0:
                print(f"  Loaded {loaded}/{total_chunks} chunks...")
        
        elapsed = time.time() - start_time
        print(f"✅ Initial snapshot loaded: {loaded} chunks in {elapsed:.2f}s")
        self.initial_load_complete = True
    
    async def wait_for_initial_load(self, timeout: Optional[float] = None):
        """Wait for initial snapshot load to complete."""
        start_time = time.time()
        while not self.initial_load_complete:
            if timeout and (time.time() - start_time) > timeout:
                raise TimeoutError("Initial load timeout")
            await asyncio.sleep(0.1)
    
    # Spatial queries
    def get_entities_in_area(self, min_x: float, min_y: float, max_x: float, max_y: float,
                             entity_type: Optional[str] = None,
                             component_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all entities in a bounding box."""
        query = """
            SELECT * FROM entities
            WHERE position_x >= ? AND position_x <= ?
            AND position_y >= ? AND position_y <= ?
        """
        params = [min_x, max_x, min_y, max_y]
        
        if entity_type:
            query += " AND type = ?"
            params.append(entity_type)
        
        if component_type:
            query += " AND component_type = ?"
            params.append(component_type)
        
        result = self.db.execute(query, params).fetchdf()
        return result.to_dict('records') if not result.empty else []
    
    def get_entities_near(self, x: float, y: float, radius: float,
                          entity_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get entities within radius of a point."""
        query = """
            SELECT * FROM entities
            WHERE SQRT(POWER(position_x - ?, 2) + POWER(position_y - ?, 2)) <= ?
        """
        params = [x, y, radius]
        
        if entity_type:
            query += " AND type = ?"
            params.append(entity_type)
        
        result = self.db.execute(query, params).fetchdf()
        return result.to_dict('records') if not result.empty else []
    
    def get_resources_in_area(self, min_x: float, min_y: float,
                              max_x: float, max_y: float,
                              resource_kind: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all resources in a bounding box."""
        query = """
            SELECT * FROM resources
            WHERE x >= ? AND x <= ?
            AND y >= ? AND y <= ?
        """
        params = [min_x, max_x, min_y, max_y]
        
        if resource_kind:
            query += " AND kind = ?"
            params.append(resource_kind)
        
        result = self.db.execute(query, params).fetchdf()
        return result.to_dict('records') if not result.empty else []
    
    # Entity queries
    def get_entity(self, unit_number: int) -> Optional[Dict[str, Any]]:
        """Get entity by unit_number."""
        result = self.db.execute("SELECT * FROM entities WHERE unit_number = ?", [unit_number]).fetchdf()
        if result.empty:
            return None
        return result.iloc[0].to_dict()
    
    def get_entities_by_name(self, name: str) -> List[Dict[str, Any]]:
        """Get all entities with a specific name."""
        result = self.db.execute("SELECT * FROM entities WHERE name = ?", [name]).fetchdf()
        return result.to_dict('records') if not result.empty else []
    
    def get_entities_by_type(self, entity_type: str) -> List[Dict[str, Any]]:
        """Get all entities of a specific type."""
        result = self.db.execute("SELECT * FROM entities WHERE type = ?", [entity_type]).fetchdf()
        return result.to_dict('records') if not result.empty else []
    
    # Resource queries
    def get_resource_at(self, x: float, y: float) -> Optional[Dict[str, Any]]:
        """Get resource at specific position."""
        result = self.db.execute("SELECT * FROM resources WHERE x = ? AND y = ?", [int(x), int(y)]).fetchdf()
        if result.empty:
            return None
        return result.iloc[0].to_dict()
    
    def get_resources_by_kind(self, kind: str) -> List[Dict[str, Any]]:
        """Get all resources of a specific kind."""
        result = self.db.execute("SELECT * FROM resources WHERE kind = ?", [kind]).fetchdf()
        return result.to_dict('records') if not result.empty else []
    
    # Advanced queries (SQL interface)
    def query(self, sql: str, params: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
        """Execute raw SQL query on the map view."""
        if params:
            result = self.db.execute(sql, params).fetchdf()
        else:
            result = self.db.execute(sql).fetchdf()
        return result.to_dict('records') if not result.empty else []
    
    # Chunk queries
    def get_chunk_entities(self, chunk_x: int, chunk_y: int) -> List[Dict[str, Any]]:
        """Get all entities in a chunk."""
        result = self.db.execute(
            "SELECT * FROM entities WHERE chunk_x = ? AND chunk_y = ?",
            [chunk_x, chunk_y]
        ).fetchdf()
        return result.to_dict('records') if not result.empty else []
    
    def get_chunk_resources(self, chunk_x: int, chunk_y: int) -> List[Dict[str, Any]]:
        """Get all resources in a chunk."""
        result = self.db.execute(
            "SELECT * FROM resources WHERE chunk_x = ? AND chunk_y = ?",
            [chunk_x, chunk_y]
        ).fetchdf()
        return result.to_dict('records') if not result.empty else []
    
    async def stop(self):
        """Stop the map view and file watcher."""
        if self._update_task:
            self._update_task.cancel()
        await self.file_watcher.stop()
        self.db.close()

