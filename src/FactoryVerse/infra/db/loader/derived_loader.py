"""
Load derived tables: electric_pole, resource_patch, water_patch, belt_line, belt_line_segment.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, Any, List, Set, Tuple, Optional
from collections import defaultdict

import duckdb

try:
    from sklearn.cluster import DBSCAN
    import numpy as np
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False
    DBSCAN = None
    np = None

from FactoryVerse.dsl.prototypes import get_entity_prototypes


def derive_electric_poles(con: duckdb.DuckDBPyConnection, dump_file: str = "factorio-data-dump.json") -> None:
    """
    Derive electric_pole table:
    - supply_area: from prototype supply_area_distance
    - connected_poles: spatial query for poles within maximum_wire_distance
    """
    # Get prototypes
    prototypes = get_entity_prototypes(dump_file)
    
    # Get all electric poles from map_entity
    poles = con.execute("""
        SELECT entity_key, entity_name, position
        FROM map_entity
        WHERE entity_name IN (
            SELECT DISTINCT entity_name FROM map_entity
            WHERE entity_name LIKE '%electric-pole%' OR entity_name LIKE '%pole%'
        )
    """).fetchall()
    
    if not poles:
        return
    
    # Build prototype lookup
    pole_prototypes: Dict[str, Any] = {}
    if hasattr(prototypes, 'electric_poles'):
        pole_prototypes = prototypes.electric_poles
    
    # Process each pole
    for row in poles:
        entity_key = row[0]
        entity_name = row[1]
        position_data = row[2]  # This is already a dict (STRUCT from DuckDB)
        
        # Handle both dict (STRUCT) and JSON string cases
        if isinstance(position_data, dict):
            position = position_data
        elif isinstance(position_data, str):
            position = json.loads(position_data)
        else:
            continue
        
        x = float(position.get("x", 0))
        y = float(position.get("y", 0))
        
        # Get supply area distance from prototype
        supply_area_distance = None
        if entity_name in pole_prototypes:
            supply_area_distance = pole_prototypes[entity_name].supply_area_distance
        
        if supply_area_distance is None:
            # Default values if prototype not found
            supply_area_distance = 2.5  # Default for small-electric-pole
        
        # Calculate supply area coordinates
        min_x = x - supply_area_distance
        min_y = y - supply_area_distance
        max_x = x + supply_area_distance
        max_y = y + supply_area_distance
        
        # Find connected poles (within maximum_wire_distance)
        max_wire_distance = None
        if entity_name in pole_prototypes:
            max_wire_distance = pole_prototypes[entity_name].maximum_wire_distance
        
        if max_wire_distance is None:
            max_wire_distance = 7.5  # Default for small-electric-pole
        
        # Query for connected poles using spatial distance
        # First get all other poles
        all_poles = con.execute("""
            SELECT entity_key, position
            FROM map_entity
            WHERE entity_key != ?
            AND entity_name IN (
                SELECT DISTINCT entity_name FROM map_entity
                WHERE entity_name LIKE '%electric-pole%' OR entity_name LIKE '%pole%'
            )
        """, [entity_key]).fetchall()
        
        # Filter by distance in Python (DuckDB spatial functions need proper geometry types)
        connected = []
        for other_row in all_poles:
            other_key = other_row[0]
            other_pos_data = other_row[1]  # Already a dict (STRUCT from DuckDB)
            
            # Handle both dict (STRUCT) and JSON string cases
            if isinstance(other_pos_data, dict):
                other_pos = other_pos_data
            elif isinstance(other_pos_data, str):
                other_pos = json.loads(other_pos_data)
            else:
                continue
            
            other_x, other_y = other_pos.get("x", 0), other_pos.get("y", 0)
            distance = ((x - other_x) ** 2 + (y - other_y) ** 2) ** 0.5
            if distance <= max_wire_distance:
                connected.append(other_key)
        
        connected_poles = connected
        
        # Insert or update (use ST_MakeEnvelope to create GEOMETRY)
        con.execute(
            """
            INSERT OR REPLACE INTO electric_pole (entity_key, supply_area, connected_poles)
            VALUES (?, ST_MakeEnvelope(?, ?, ?, ?), ?)
            """,
            [entity_key, min_x, min_y, max_x, max_y, json.dumps(connected_poles)],
        )


def derive_resource_patches(con: duckdb.DuckDBPyConnection, dump_file: str = "factorio-data-dump.json") -> None:
    """
    Derive resource_patch table using DBSCAN clustering.
    Uses _search_radius from ElectricMiningDrillPrototype as eps parameter.
    Clustering is done GLOBALLY across all chunks for each resource type.
    """
    if not HAS_SKLEARN:
        print("WARNING: sklearn not available. Skipping resource patch derivation.")
        print("Install with: uv add scikit-learn numpy")
        return
    
    # Clear existing patches first
    con.execute("DELETE FROM resource_patch;")
    
    # Get search radius from prototype
    prototypes = get_entity_prototypes(dump_file)
    search_radius = None
    if hasattr(prototypes, 'electric_mining_drill'):
        search_radius = prototypes.electric_mining_drill._search_radius
    
    if search_radius is None:
        search_radius = 2.5  # Default
    
    # Get all resource tiles grouped by resource type (GLOBALLY, across all chunks)
    resource_types = con.execute("""
        SELECT DISTINCT name FROM resource_tile
    """).fetchall()
    
    patch_id = 1
    for (resource_name,) in resource_types:
        # Get ALL tiles for this resource type GLOBALLY (across all chunks)
        # This query fetches ALL tiles from ALL chunks in one go - no chunk filtering
        tiles = con.execute("""
            SELECT entity_key, position, amount
            FROM resource_tile
            WHERE name = ?
            ORDER BY entity_key
        """, [resource_name]).fetchall()
        
        if not tiles:
            continue
        
        print(f"Clustering {len(tiles)} tiles of type '{resource_name}' globally (across all chunks)...")
        
        # Extract positions for clustering
        positions = []
        tile_keys = []
        amounts = []
        for row in tiles:
            tile_key = row[0]
            position_data = row[1]  # This is already a dict (STRUCT from DuckDB)
            amount = row[2]
            
            # Handle both dict (STRUCT) and JSON string cases
            if isinstance(position_data, dict):
                pos = position_data
            elif isinstance(position_data, str):
                pos = json.loads(position_data)
            else:
                continue
            
            positions.append([pos.get("x", 0), pos.get("y", 0)])
            tile_keys.append(tile_key)
            amounts.append(amount)
        
        if len(positions) < 2:
            continue
        
        # Run DBSCAN clustering on ALL positions at once (GLOBAL clustering)
        # This single DBSCAN call considers all tiles together, regardless of chunk
        positions_array = np.array(positions)
        clustering = DBSCAN(eps=search_radius, min_samples=1).fit(positions_array)
        
        # Count unique clusters (excluding noise points with label -1)
        unique_clusters = set(clustering.labels_)
        unique_clusters.discard(-1)  # Remove noise label
        print(f"  -> Found {len(unique_clusters)} patches from {len(positions)} tiles (eps={search_radius})")
        
        # Group tiles by cluster
        clusters: Dict[int, List[Tuple[str, float, float, int]]] = defaultdict(list)
        for idx, label in enumerate(clustering.labels_):
            if label >= 0:  # Ignore noise points (-1)
                clusters[label].append((tile_keys[idx], positions[idx][0], positions[idx][1], amounts[idx]))
        
        # Create patches for each cluster
        for cluster_id, cluster_tiles in clusters.items():
            # Create geometry from cluster points
            # Use ST_ConvexHull or ST_ConcaveHull in DuckDB
            tile_positions = [(x, y) for _, x, y, _ in cluster_tiles]
            total_amount = sum(amount for _, _, _, amount in cluster_tiles)
            
            # Calculate centroid
            centroid_x = sum(x for _, x, _, _ in cluster_tiles) / len(cluster_tiles)
            centroid_y = sum(y for _, _, y, _ in cluster_tiles) / len(cluster_tiles)
            
            # Create geometry from bounding box (can be improved with ST_ConvexHull)
            min_x = min(x for _, x, _, _ in cluster_tiles)
            max_x = max(x for _, x, _, _ in cluster_tiles)
            min_y = min(y for _, _, y, _ in cluster_tiles)
            max_y = max(y for _, _, y, _ in cluster_tiles)
            
            # Create polygon from bounding box (simplified)
            geom_wkt = f"POLYGON(({min_x} {min_y}, {max_x} {min_y}, {max_x} {max_y}, {min_x} {max_y}, {min_x} {min_y}))"
            
            # Extract tile keys for this patch
            patch_tile_keys = [tile_key for tile_key, _, _, _ in cluster_tiles]
            
            con.execute("""
                INSERT OR REPLACE INTO resource_patch (patch_id, resource_name, geom, tile_count, total_amount, centroid, tiles)
                VALUES (?, ?, ST_GeomFromText(?), ?, ?, ST_Point(?, ?), ?)
            """, [patch_id, resource_name, geom_wkt, len(cluster_tiles), total_amount, centroid_x, centroid_y, patch_tile_keys])
            
            patch_id += 1


def derive_water_patches(con: duckdb.DuckDBPyConnection) -> None:
    """
    Derive water_patch table using 8-connectivity (including diagonals).
    Uses Union-Find algorithm in Python, then creates spatial geometries.
    Clusters water tiles that have any other water tile in their 8 neighbors.
    This is done GLOBALLY across all chunks - all water tiles are considered together.
    """
    # Clear existing patches
    con.execute("DELETE FROM water_patch;")
    
    # Get ALL water tiles GLOBALLY (across all chunks)
    # This query should return tiles from ALL chunks, not filtered by chunk
    tiles = con.execute("""
        SELECT entity_key, position
        FROM water_tile
        ORDER BY entity_key
    """).fetchall()
    
    if not tiles:
        return
    
    print(f"Clustering {len(tiles)} water tiles globally (across all chunks)...")
    
    # Build tile map - use floor to get integer tile coordinates
    tile_map: Dict[Tuple[int, int], str] = {}
    position_map: Dict[Tuple[int, int], Tuple[float, float]] = {}  # Store original positions for centroid
    
    for row in tiles:
        tile_key = row[0]
        position_data = row[1]  # This is already a dict (STRUCT from DuckDB)
        
        # Handle both dict (STRUCT) and JSON string cases
        if isinstance(position_data, dict):
            pos = position_data
        elif isinstance(position_data, str):
            pos = json.loads(position_data)
        else:
            continue
        
        # Get tile coordinates - use floor to ensure we get the correct tile
        # Water tiles are typically at integer positions, but we floor to be safe
        x = pos.get("x", 0)
        y = pos.get("y", 0)
        tile_x = int(math.floor(x))
        tile_y = int(math.floor(y))
        
        tile_coord = (tile_x, tile_y)
        tile_map[tile_coord] = tile_key
        position_map[tile_coord] = (float(x), float(y))
    
    # Union-Find for 8-connectivity
    parent: Dict[Tuple[int, int], Tuple[int, int]] = {}
    
    def find(p: Tuple[int, int]) -> Tuple[int, int]:
        if p not in parent:
            parent[p] = p
        if parent[p] != p:
            parent[p] = find(parent[p])
        return parent[p]
    
    def union(p1: Tuple[int, int], p2: Tuple[int, int]):
        root1 = find(p1)
        root2 = find(p2)
        if root1 != root2:
            parent[root2] = root1
    
    # 8-connectivity neighbors (including diagonals)
    neighbors = [
        (0, 1), (1, 0), (0, -1), (-1, 0),  # Cardinal
        (1, 1), (1, -1), (-1, 1), (-1, -1)  # Diagonal
    ]
    
    # Initialize all tiles in union-find
    for tile_pos in tile_map.keys():
        parent[tile_pos] = tile_pos
    
    # Union all connected tiles (8-connectivity)
    # This should connect ALL tiles globally, regardless of which chunk they came from
    connections_made = 0
    for (x, y) in tile_map.keys():
        for dx, dy in neighbors:
            neighbor = (x + dx, y + dy)
            if neighbor in tile_map:
                # Check if they're already in the same set
                root1 = find((x, y))
                root2 = find(neighbor)
                if root1 != root2:
                    union((x, y), neighbor)
                    connections_made += 1
    
    # Group tiles by root
    patches: Dict[Tuple[int, int], List[Tuple[int, int]]] = defaultdict(list)
    for tile_pos in tile_map.keys():
        root = find(tile_pos)
        patches[root].append(tile_pos)
    
    print(f"  -> Made {connections_made} connections, found {len(patches)} water patches from {len(tile_map)} tiles")
    
    # Debug: show patch sizes
    patch_sizes = sorted([len(tiles) for tiles in patches.values()], reverse=True)
    print(f"  -> Patch sizes: {patch_sizes[:10]}")  # Show top 10
    
    # Create patches
    patch_id = 1
    for root, tile_positions in patches.items():
        if len(tile_positions) < 1:
            continue
        
        # Calculate centroid using original positions
        centroid_x = sum(position_map[pos][0] for pos in tile_positions) / len(tile_positions)
        centroid_y = sum(position_map[pos][1] for pos in tile_positions) / len(tile_positions)
        
        # Create geometry from tile positions
        # Use original positions for bounding box
        min_x = min(position_map[pos][0] for pos in tile_positions)
        max_x = max(position_map[pos][0] for pos in tile_positions)
        min_y = min(position_map[pos][1] for pos in tile_positions)
        max_y = max(position_map[pos][1] for pos in tile_positions)
        
        # Create polygon (simplified - could use ST_Union for better shape)
        geom_wkt = f"POLYGON(({min_x} {min_y}, {max_x} {min_y}, {max_x} {max_y}, {min_x} {max_y}, {min_x} {min_y}))"
        
        # Extract tile keys for this patch
        patch_tile_keys = [tile_map[pos] for pos in tile_positions]
        
        con.execute("""
            INSERT OR REPLACE INTO water_patch (patch_id, geom, tile_count, centroid, tiles)
            VALUES (?, ST_GeomFromText(?), ?, ST_Point(?, ?), ?)
        """, [patch_id, geom_wkt, len(tile_positions), centroid_x, centroid_y, patch_tile_keys])
        
        patch_id += 1


def derive_belt_network(con: duckdb.DuckDBPyConnection) -> None:
    """
    Derive belt_line and belt_line_segment tables from transport_belt connections.
    Uses graph traversal to find connected components and segments.
    """
    # Get all belts with their connections
    belts = con.execute("""
        SELECT 
            tb.entity_key,
            tb.direction,
            tb.output,
            tb.input,
            me.position
        FROM transport_belt tb
        JOIN map_entity me ON tb.entity_key = me.entity_key
    """).fetchall()
    
    if not belts:
        return
    
    # Build graph
    belt_graph: Dict[str, List[str]] = defaultdict(list)  # entity_key -> [connected_keys]
    belt_positions: Dict[str, Tuple[float, float]] = {}
    belt_directions: Dict[str, str] = {}
    
    for row in belts:
        entity_key = row[0]
        direction = row[1]
        output_json = row[2]
        input_json = row[3]
        position_data = row[4]  # This is already a dict (STRUCT from DuckDB)
        
        # Handle both dict (STRUCT) and JSON string cases
        if isinstance(position_data, dict):
            pos = position_data
        elif isinstance(position_data, str):
            pos = json.loads(position_data)
        else:
            continue
        
        belt_positions[entity_key] = (float(pos.get("x", 0)), float(pos.get("y", 0)))
        belt_directions[entity_key] = direction
        
        # Add output connections
        # Handle both dict (STRUCT) and JSON string cases
        if output_json:
            if isinstance(output_json, dict):
                output = output_json
            elif isinstance(output_json, str):
                output = json.loads(output_json)
            else:
                output = None
            
            if output:
                output_key = output.get("entity_key")
                if output_key:
                    belt_graph[entity_key].append(output_key)
        
        # Add input connections
        # Handle both list/array and JSON string cases
        if input_json:
            if isinstance(input_json, (list, tuple)):
                inputs = input_json
            elif isinstance(input_json, str):
                inputs = json.loads(input_json)
            else:
                inputs = None
            
            if inputs:
                for inp in inputs:
                    # Handle both dict and string cases
                    if isinstance(inp, dict):
                        input_key = inp.get("entity_key")
                    elif isinstance(inp, str):
                        # If it's a string, it might be the entity_key directly
                        input_key = inp
                    else:
                        continue
                    
                    if input_key:
                        belt_graph[input_key].append(entity_key)
    
    # Find connected components (belt lines)
    visited: Set[str] = set()
    line_id = 1
    segment_id = 1
    
    def dfs(belt_key: str, component: List[str]):
        if belt_key in visited:
            return
        visited.add(belt_key)
        component.append(belt_key)
        for neighbor in belt_graph.get(belt_key, []):
            if neighbor in belt_positions:  # Only follow transport belts
                dfs(neighbor, component)
    
    for belt_key in belt_positions.keys():
        if belt_key not in visited:
            component = []
            dfs(belt_key, component)
            
            if len(component) < 2:
                continue
            
            # Create belt line
            belt_keys = component
            positions = [belt_positions[key] for key in belt_keys]
            
            # Create LINESTRING from positions (simplified - should follow actual belt path)
            line_wkt = "LINESTRING(" + ", ".join([f"{x} {y}" for x, y in positions]) + ")"
            
            # Create buffer polygon for geom
            geom_wkt = f"POLYGON(({min(x for x, _ in positions)} {min(y for _, y in positions)}, {max(x for x, _ in positions)} {min(y for _, y in positions)}, {max(x for x, _ in positions)} {max(y for _, y in positions)}, {min(x for x, _ in positions)} {max(y for _, y in positions)}, {min(x for x, _ in positions)} {min(y for _, y in positions)}))"
            
            con.execute("""
                INSERT OR REPLACE INTO belt_line (line_id, geom, line_segments, belts)
                VALUES (?, ST_GeomFromText(?), ST_GeomFromText(?), ?)
            """, [line_id, geom_wkt, line_wkt, json.dumps(belt_keys)])
            
            # Create segments (simplified - one segment per line for now)
            # In reality, segments should be split at merges/splits
            start_entity = belt_keys[0]
            end_entity = belt_keys[-1]
            
            con.execute("""
                INSERT OR REPLACE INTO belt_line_segment (
                    segment_id, line_id, segment_order, geom, line, belts,
                    upstream_segments, downstream_segments, start_entity, end_entity
                )
                VALUES (?, ?, ?, ST_GeomFromText(?), ST_GeomFromText(?), ?, ?, ?, ?, ?)
            """, [
                segment_id,
                line_id,
                0,
                geom_wkt,
                line_wkt,
                json.dumps(belt_keys),
                json.dumps([]),
                json.dumps([]),
                start_entity,
                end_entity,
            ])
            
            line_id += 1
            segment_id += 1


def load_derived_tables(con: duckdb.DuckDBPyConnection, snapshot_dir: Path, dump_file: str = "factorio-data-dump.json") -> None:
    """
    Load all derived tables from base tables.
    
    Args:
        con: DuckDB connection
        snapshot_dir: Path to snapshot directory (unused but kept for consistency)
        dump_file: Path to Factorio prototype data dump JSON file
    """
    # snapshot_dir is normalized by caller, but we don't use it here
    # (derived tables are computed from base tables in the database)
    print("Deriving electric poles...")
    derive_electric_poles(con, dump_file)
    
    print("Deriving resource patches...")
    derive_resource_patches(con, dump_file)
    
    print("Deriving water patches...")
    derive_water_patches(con)
    
    print("Deriving belt network...")
    derive_belt_network(con)
    
    print("Derived tables loaded successfully.")

