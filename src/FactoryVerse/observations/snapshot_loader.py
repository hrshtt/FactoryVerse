"""Snapshot file loader for loading game state from disk into DuckDB."""

import json
import time
from pathlib import Path
from typing import Dict, Any, Optional

import duckdb


class SnapshotLoader:
    """Loads snapshot files into DuckDB tables."""
    
    def __init__(self, db: duckdb.DuckDBPyConnection, snapshot_dir: Path):
        """
        Initialize snapshot loader.
        
        Args:
            db: DuckDB connection
            snapshot_dir: Path to snapshot directory
        """
        self.db = db
        self.snapshot_dir = Path(snapshot_dir)
        
        # ID counters (DuckDB doesn't support auto-increment)
        self._resource_id_counter = 1
        self._water_id_counter = 1
        self._tree_id_counter = 1
    
    async def load_entity_file(self, file_path: Path, chunk_x: int, chunk_y: int, 
                              event: Dict[str, Any]):
        """Load an entity JSON file into DuckDB."""
        try:
            with open(file_path, 'r') as f:
                entity_data = json.load(f)
            
            unit_number = entity_data.get('unit_number')
            if not unit_number:
                return
            
            position = entity_data.get('position', {})
            position_x = position.get('x', 0)
            position_y = position.get('y', 0)
            
            # Determine if it's a belt or pipe (linestring) or regular entity (point)
            entity_type = entity_data.get('type', '')
            entity_name = entity_data.get('name', '')
            
            # Check if it's a belt
            if entity_type in ('transport-belt', 'underground-belt', 'splitter', 
                              'loader', 'loader-1x1', 'linked-belt'):
                await self._load_belt(entity_data, chunk_x, chunk_y, event, position_x, position_y)
            # Check if it's a pipe
            elif entity_type in ('pipe', 'pipe-to-ground'):
                await self._load_pipe(entity_data, chunk_x, chunk_y, event, position_x, position_y)
            # Regular point entity
            else:
                await self._load_point_entity(entity_data, chunk_x, chunk_y, event, 
                                             position_x, position_y)
        except Exception as e:
            print(f"⚠️  Error loading entity file {file_path}: {e}")
    
    async def _load_point_entity(self, entity_data: Dict, chunk_x: int, chunk_y: int,
                                event: Dict, position_x: float, position_y: float):
        """Load a point entity (assembler, inserter, etc.)."""
        unit_number = entity_data.get('unit_number')
        
        # Create POINT geometry
        self.db.execute("""
            INSERT INTO entities (
                unit_number, name, type, position, position_x, position_y,
                direction, recipe, power_network_id, chunk_x, chunk_y, tick, data
            ) VALUES (?, ?, ?, CAST(ST_MakePoint(?, ?) AS GEOMETRY), ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (unit_number) DO UPDATE SET
                name = EXCLUDED.name,
                type = EXCLUDED.type,
                position = EXCLUDED.position,
                position_x = EXCLUDED.position_x,
                position_y = EXCLUDED.position_y,
                direction = EXCLUDED.direction,
                recipe = EXCLUDED.recipe,
                power_network_id = EXCLUDED.power_network_id,
                chunk_x = EXCLUDED.chunk_x,
                chunk_y = EXCLUDED.chunk_y,
                tick = EXCLUDED.tick,
                data = EXCLUDED.data
        """, [
            unit_number,
            entity_data.get('name'),
            entity_data.get('type'),
            position_x,
            position_y,
            position_x,  # position_x
            position_y,  # position_y
            entity_data.get('direction'),
            entity_data.get('recipe'),
            entity_data.get('power_network_id'),
            chunk_x,
            chunk_y,
            event.get('tick'),
            json.dumps(entity_data)
        ])
    
    async def _load_belt(self, entity_data: Dict, chunk_x: int, chunk_y: int,
                        event: Dict, position_x: float, position_y: float):
        """Load a belt entity (linestring)."""
        unit_number = entity_data.get('unit_number')
        
        # For now, create a simple linestring from position
        # TODO: Extract actual belt path from entity_data if available
        # For belts, we might need to construct the line from connected segments
        line_wkt = f"LINESTRING({position_x} {position_y}, {position_x + 1} {position_y})"
        
        self.db.execute("""
            INSERT INTO belts (
                unit_number, name, type, line, direction,
                chunk_x, chunk_y, tick, upstream_units, downstream_units, data
            ) VALUES (?, ?, ?, ST_GeomFromText(?), ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (unit_number) DO UPDATE SET
                name = EXCLUDED.name,
                type = EXCLUDED.type,
                line = EXCLUDED.line,
                direction = EXCLUDED.direction,
                chunk_x = EXCLUDED.chunk_x,
                chunk_y = EXCLUDED.chunk_y,
                tick = EXCLUDED.tick,
                upstream_units = EXCLUDED.upstream_units,
                downstream_units = EXCLUDED.downstream_units,
                data = EXCLUDED.data
        """, [
            unit_number,
            entity_data.get('name'),
            entity_data.get('type'),
            line_wkt,
            entity_data.get('direction'),
            chunk_x,
            chunk_y,
            event.get('tick'),
            json.dumps(entity_data.get('upstream_units', [])),
            json.dumps(entity_data.get('downstream_units', [])),
            json.dumps(entity_data)
        ])
    
    async def _load_pipe(self, entity_data: Dict, chunk_x: int, chunk_y: int,
                        event: Dict, position_x: float, position_y: float):
        """Load a pipe entity (linestring)."""
        unit_number = entity_data.get('unit_number')
        
        # For now, create a simple linestring from position
        # TODO: Extract actual pipe path from entity_data if available
        line_wkt = f"LINESTRING({position_x} {position_y}, {position_x + 1} {position_y})"
        
        self.db.execute("""
            INSERT INTO pipes (
                unit_number, name, type, line,
                chunk_x, chunk_y, tick, connected_units, data
            ) VALUES (?, ?, ?, ST_GeomFromText(?), ?, ?, ?, ?, ?)
            ON CONFLICT (unit_number) DO UPDATE SET
                name = EXCLUDED.name,
                type = EXCLUDED.type,
                line = EXCLUDED.line,
                chunk_x = EXCLUDED.chunk_x,
                chunk_y = EXCLUDED.chunk_y,
                tick = EXCLUDED.tick,
                connected_units = EXCLUDED.connected_units,
                data = EXCLUDED.data
        """, [
            unit_number,
            entity_data.get('name'),
            entity_data.get('type'),
            line_wkt,
            chunk_x,
            chunk_y,
            event.get('tick'),
            json.dumps(entity_data.get('connected_units', [])),
            json.dumps(entity_data)
        ])
    
    async def load_resource_file(self, file_path: Path, chunk_x: int, chunk_y: int,
                                event: Dict[str, Any]):
        """Load a resources.jsonl file into DuckDB."""
        try:
            # Delete existing resources for this chunk
            self.db.execute("DELETE FROM resources WHERE chunk_x = ? AND chunk_y = ?", 
                          [chunk_x, chunk_y])
            
            # Load new resources
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    resource = json.loads(line)
                    resource_id = self._resource_id_counter
                    self._resource_id_counter += 1
                    
                    x = resource.get('x')
                    y = resource.get('y')
                    
                    self.db.execute("""
                        INSERT INTO resources (id, kind, position, x, y, amount, chunk_x, chunk_y, tick)
                        VALUES (?, ?, ST_MakePoint(?, ?), ?, ?, ?, ?, ?, ?)
                    """, [
                        resource_id,
                        resource.get('kind'),
                        x,
                        y,
                        x,  # x
                        y,  # y
                        resource.get('amount', 0),
                        chunk_x,
                        chunk_y,
                        event.get('tick')
                    ])
        except Exception as e:
            print(f"⚠️  Error loading resource file {file_path}: {e}")
    
    async def load_water_file(self, file_path: Path, chunk_x: int, chunk_y: int,
                             event: Dict[str, Any]):
        """Load a water.jsonl file into DuckDB."""
        try:
            # Delete existing water for this chunk
            self.db.execute("DELETE FROM water WHERE chunk_x = ? AND chunk_y = ?", 
                          [chunk_x, chunk_y])
            
            # Load new water tiles
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    water = json.loads(line)
                    water_id = self._water_id_counter
                    self._water_id_counter += 1
                    
                    x = water.get('x')
                    y = water.get('y')
                    
                    # Create a polygon for the water tile (1x1 tile)
                    tile_wkt = f"POLYGON(({x} {y}, {x+1} {y}, {x+1} {y+1}, {x} {y+1}, {x} {y}))"
                    
                    self.db.execute("""
                        INSERT INTO water (id, tile, x, y, chunk_x, chunk_y, tick)
                        VALUES (?, ST_GeomFromText(?), ?, ?, ?, ?, ?)
                    """, [
                        water_id,
                        tile_wkt,
                        x,  # x (center)
                        y,  # y (center)
                        chunk_x,
                        chunk_y,
                        event.get('tick')
                    ])
        except Exception as e:
            print(f"⚠️  Error loading water file {file_path}: {e}")
    
    async def load_trees_file(self, file_path: Path, chunk_x: int, chunk_y: int,
                             event: Dict[str, Any]):
        """Load a trees.jsonl file into DuckDB."""
        try:
            # Delete existing trees for this chunk
            self.db.execute("DELETE FROM trees WHERE chunk_x = ? AND chunk_y = ?", 
                          [chunk_x, chunk_y])
            
            # Load new trees
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    tree = json.loads(line)
                    tree_id = self._tree_id_counter
                    self._tree_id_counter += 1
                    
                    position = tree.get('position', {})
                    position_x = position.get('x', 0)
                    position_y = position.get('y', 0)
                    
                    bounding_box = tree.get('bounding_box', {})
                    min_x = bounding_box.get('min_x', position_x - 0.5)
                    min_y = bounding_box.get('min_y', position_y - 0.5)
                    max_x = bounding_box.get('max_x', position_x + 0.5)
                    max_y = bounding_box.get('max_y', position_y + 0.5)
                    
                    # Create POINT for position
                    position_wkt = f"POINT({position_x} {position_y})"
                    
                    # Create POLYGON for bounding box
                    bbox_wkt = (f"POLYGON(({min_x} {min_y}, {max_x} {min_y}, "
                              f"{max_x} {max_y}, {min_x} {max_y}, {min_x} {min_y}))")
                    
                    self.db.execute("""
                        INSERT INTO trees (id, name, position, position_x, position_y, bbox, chunk_x, chunk_y, tick)
                        VALUES (?, ?, ST_GeomFromText(?), ?, ?, ST_GeomFromText(?), ?, ?, ?)
                    """, [
                        tree_id,
                        tree.get('name'),
                        position_wkt,
                        position_x,  # position_x
                        position_y,  # position_y
                        bbox_wkt,
                        chunk_x,
                        chunk_y,
                        event.get('tick')
                    ])
        except Exception as e:
            print(f"⚠️  Error loading trees file {file_path}: {e}")
    
    async def load_initial_snapshot(self):
        """Load all existing snapshot files into DuckDB."""
        print("🔄 Loading initial snapshot...")
        start_time = time.time()
        
        chunk_dirs = []
        if self.snapshot_dir.exists():
            for chunk_x_dir in self.snapshot_dir.iterdir():
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
                        await self.load_entity_file(entity_file, chunk_x, chunk_y, {'tick': 0})
            
            # Load resources
            resources_file = chunk_dir / 'resources' / 'resources.jsonl'
            if resources_file.exists():
                await self.load_resource_file(resources_file, chunk_x, chunk_y, {'tick': 0})
            
            # Load water
            water_file = chunk_dir / 'resources' / 'water.jsonl'
            if water_file.exists():
                await self.load_water_file(water_file, chunk_x, chunk_y, {'tick': 0})
            
            # Load trees
            trees_file = chunk_dir / 'resources' / 'trees.jsonl'
            if trees_file.exists():
                await self.load_trees_file(trees_file, chunk_x, chunk_y, {'tick': 0})
            
            loaded += 1
            if loaded % 10 == 0:
                print(f"  Loaded {loaded}/{total_chunks} chunks...")
        
        elapsed = time.time() - start_time
        print(f"✅ Initial snapshot loaded: {loaded} chunks in {elapsed:.2f}s")

