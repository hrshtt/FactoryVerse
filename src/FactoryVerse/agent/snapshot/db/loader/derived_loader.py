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

from FactoryVerse.factory.prototypes import get_entity_prototypes


def derive_electric_poles(con: duckdb.DuckDBPyConnection) -> None:
    """
    Derive electric_pole table:
    - supply_area: from prototype supply_area_distance
    - connected_poles: spatial query for poles within maximum_wire_distance
    """
    # Get prototypes (uses PrototypeDataManager internally)
    prototypes = get_entity_prototypes()

    # Get all electric poles from map_entity
    poles = con.execute("""
        SELECT entity_name, position_x, position_y, position
        FROM map_entity
        WHERE entity_name IN (
            SELECT DISTINCT entity_name FROM map_entity
            WHERE entity_name LIKE '%electric-pole%' OR entity_name LIKE '%pole%'
        )
    """).fetchall()

    if not poles:
        return

    # Process each pole
    for row in poles:
        entity_name = row[0]
        px = float(row[1])
        py = float(row[2])
        position_data = row[3]  # This is already a dict (STRUCT from DuckDB)

        # Use position from composite key columns
        x = px
        y = py

        # Get supply area distance from prototype
        pole_proto = prototypes.get_prototype(entity_name)
        supply_area_distance = pole_proto.get("supply_area_distance")
        if supply_area_distance is None:
            # Default values if prototype not found
            supply_area_distance = 2.5  # Default for small-electric-pole

        # Calculate supply area coordinates
        min_x = x - supply_area_distance
        min_y = y - supply_area_distance
        max_x = x + supply_area_distance
        max_y = y + supply_area_distance

        # Find connected poles (within maximum_wire_distance)
        max_wire_distance = pole_proto.get("maximum_wire_distance")
        if max_wire_distance is None:
            max_wire_distance = 7.5  # Default for small-electric-pole

        # Query for connected poles using spatial distance
        # First get all other poles
        all_poles = con.execute(
            """
            SELECT entity_name, position_x, position_y
            FROM map_entity
            WHERE NOT (entity_name = ? AND position_x = ? AND position_y = ?)
            AND entity_name IN (
                SELECT DISTINCT entity_name FROM map_entity
                WHERE entity_name LIKE '%electric-pole%' OR entity_name LIKE '%pole%'
            )
        """,
            [entity_name, px, py],
        ).fetchall()

        # Filter by distance in Python (DuckDB spatial functions need proper geometry types)
        connected = []
        for other_row in all_poles:
            other_name = other_row[0]
            other_x = float(other_row[1])
            other_y = float(other_row[2])
            distance = ((x - other_x) ** 2 + (y - other_y) ** 2) ** 0.5
            if distance <= max_wire_distance:
                # Store as entity_key string for backward compatibility with connected_poles array
                # This is just a reference array, not a foreign key
                connected.append(f"({other_name}:{other_x},{other_y})")

        connected_poles = connected

        # Insert or update (use ST_MakeEnvelope to create GEOMETRY)
        con.execute(
            """
            INSERT OR REPLACE INTO electric_pole (entity_name, position_x, position_y, supply_area, connected_poles)
            VALUES (?, ?, ?, ST_MakeEnvelope(?, ?, ?, ?), ?)
            """,
            [entity_name, px, py, min_x, min_y, max_x, max_y, json.dumps(connected_poles)],
        )


def derive_resource_patches(con: duckdb.DuckDBPyConnection) -> None:
    """
    Derive resource_patch table using DBSCAN clustering.
    Uses resource_searching_radius from electric-mining-drill prototype as eps parameter.
    Clustering is done GLOBALLY across all chunks for each resource type.
    """
    if not HAS_SKLEARN:
        print("WARNING: sklearn not available. Skipping resource patch derivation.")
        print("Install with: uv add scikit-learn numpy")
        return

    # Clear existing patches first
    con.execute("DELETE FROM resource_patch;")

    # Get search radius from prototype (uses PrototypeDataManager internally)
    prototypes = get_entity_prototypes()
    drill_proto = prototypes.get_prototype("electric-mining-drill")
    search_radius = drill_proto.get("resource_searching_radius")
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
        tiles = con.execute(
            """
            SELECT name, position_x, position_y, position, amount
            FROM resource_tile
            WHERE name = ?
            ORDER BY name, position_x, position_y
        """,
            [resource_name],
        ).fetchall()

        if not tiles:
            continue

        print(
            f"Clustering {len(tiles)} tiles of type '{resource_name}' globally (across all chunks)..."
        )

        # Extract positions for clustering
        positions = []
        tile_keys = []
        amounts = []
        for row in tiles:
            tile_name = row[0]
            px = float(row[1])
            py = float(row[2])
            amount = row[4] if len(row) > 4 else row[3]  # Handle different row structures

            positions.append([px, py])
            # Store as entity_key string for backward compatibility with tiles array
            # This is just a reference array, not a foreign key
            tile_keys.append(f"({tile_name}:{px},{py})")
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
        print(
            f"  -> Found {len(unique_clusters)} patches from {len(positions)} tiles (eps={search_radius})"
        )

        # Group tiles by cluster
        clusters: Dict[int, List[Tuple[str, float, float, int]]] = defaultdict(list)
        for idx, label in enumerate(clustering.labels_):
            if label >= 0:  # Ignore noise points (-1)
                clusters[label].append(
                    (tile_keys[idx], positions[idx][0], positions[idx][1], amounts[idx])
                )

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

            con.execute(
                """
                INSERT OR REPLACE INTO resource_patch (patch_id, resource_name, geom, tile_count, total_amount, centroid, tiles)
                VALUES (?, ?, ST_GeomFromText(?), ?, ?, ST_Point(?, ?), ?)
            """,
                [
                    patch_id,
                    resource_name,
                    geom_wkt,
                    len(cluster_tiles),
                    total_amount,
                    centroid_x,
                    centroid_y,
                    patch_tile_keys,
                ],
            )

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
        SELECT position_x, position_y, position
        FROM water_tile
        ORDER BY position_x, position_y
    """).fetchall()

    if not tiles:
        return

    print(f"Clustering {len(tiles)} water tiles globally (across all chunks)...")

    # Build tile map - use floor to get integer tile coordinates
    tile_map: Dict[Tuple[int, int], str] = {}
    position_map: Dict[
        Tuple[int, int], Tuple[float, float]
    ] = {}  # Store original positions for centroid

    for row in tiles:
        px = float(row[0])
        py = float(row[1])
        
        # Get tile coordinates - use floor to ensure we get the correct tile
        # Water tiles are typically at integer positions, but we floor to be safe
        tile_x = int(math.floor(px))
        tile_y = int(math.floor(py))

        tile_coord = (tile_x, tile_y)
        # Store as entity_key string for backward compatibility with tiles array
        # This is just a reference array, not a foreign key
        tile_key = f"(water:{px},{py})"
        tile_map[tile_coord] = tile_key
        position_map[tile_coord] = (float(px), float(py))

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
        (0, 1),
        (1, 0),
        (0, -1),
        (-1, 0),  # Cardinal
        (1, 1),
        (1, -1),
        (-1, 1),
        (-1, -1),  # Diagonal
    ]

    # Initialize all tiles in union-find
    for tile_pos in tile_map.keys():
        parent[tile_pos] = tile_pos

    # Union all connected tiles (8-connectivity)
    # This should connect ALL tiles globally, regardless of which chunk they came from
    connections_made = 0
    for x, y in tile_map.keys():
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

    print(
        f"  -> Made {connections_made} connections, found {len(patches)} water patches from {len(tile_map)} tiles"
    )

    # Debug: show patch sizes
    patch_sizes = sorted([len(tiles) for tiles in patches.values()], reverse=True)
    print(f"  -> Patch sizes: {patch_sizes[:10]}")  # Show top 10

    # Create patches
    patch_id = 1
    for root, tile_positions in patches.items():
        if len(tile_positions) < 1:
            continue

        # Calculate centroid using original positions
        centroid_x = sum(position_map[pos][0] for pos in tile_positions) / len(
            tile_positions
        )
        centroid_y = sum(position_map[pos][1] for pos in tile_positions) / len(
            tile_positions
        )

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

        con.execute(
            """
            INSERT OR REPLACE INTO water_patch (patch_id, geom, tile_count, centroid, tiles)
            VALUES (?, ST_GeomFromText(?), ?, ST_Point(?, ?), ?)
        """,
            [
                patch_id,
                geom_wkt,
                len(tile_positions),
                centroid_x,
                centroid_y,
                patch_tile_keys,
            ],
        )

        patch_id += 1


def derive_belt_network(con: duckdb.DuckDBPyConnection) -> None:
    """
    Derive belt_line and belt_line_segment tables from transport_belt connections.
    Uses graph traversal to find connected components and segments.
    """
    # Get all belts with their connections
    belts = con.execute("""
        SELECT 
            tb.entity_name,
            tb.position_x,
            tb.position_y,
            tb.direction,
            tb.output,
            tb.input
        FROM transport_belt tb
    """).fetchall()

    if not belts:
        return

    # Build graph using composite keys
    belt_graph: Dict[Tuple[str, float, float], List[Tuple[str, float, float]]] = defaultdict(list)
    belt_positions: Dict[Tuple[str, float, float], Tuple[float, float]] = {}
    belt_directions: Dict[Tuple[str, float, float], str] = {}

    for row in belts:
        entity_name = row[0]
        px = float(row[1])
        py = float(row[2])
        direction = row[3]
        output_json = row[4]
        input_json = row[5]

        composite_key = (entity_name, px, py)
        belt_positions[composite_key] = (px, py)
        belt_directions[composite_key] = direction

        # Add output connections
        if output_json:
            if isinstance(output_json, dict):
                output = output_json
            elif isinstance(output_json, str):
                output = json.loads(output_json)
            else:
                output = None

            if output:
                out_name = output.get("entity_name")
                out_x = output.get("position_x")
                out_y = output.get("position_y")
                if out_name and out_x is not None and out_y is not None:
                    out_key = (out_name, float(out_x), float(out_y))
                    belt_graph[composite_key].append(out_key)

        # Add input connections
        if input_json:
            if isinstance(input_json, (list, tuple)):
                inputs = input_json
            elif isinstance(input_json, str):
                inputs = json.loads(input_json)
            else:
                inputs = None

            if inputs:
                for inp in inputs:
                    if isinstance(inp, dict):
                        inp_name = inp.get("entity_name")
                        inp_x = inp.get("position_x")
                        inp_y = inp.get("position_y")
                        if inp_name and inp_x is not None and inp_y is not None:
                            inp_key = (inp_name, float(inp_x), float(inp_y))
                            belt_graph[inp_key].append(composite_key)

    # Find connected components (belt lines)
    visited: Set[Tuple[str, float, float]] = set()
    line_id = 1
    segment_id = 1

    def dfs(belt_key: Tuple[str, float, float], component: List[Tuple[str, float, float]]):
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
            line_wkt = (
                "LINESTRING(" + ", ".join([f"{x} {y}" for x, y in positions]) + ")"
            )

            # Create buffer polygon for geom
            geom_wkt = f"POLYGON(({min(x for x, _ in positions)} {min(y for _, y in positions)}, {max(x for x, _ in positions)} {min(y for _, y in positions)}, {max(x for x, _ in positions)} {max(y for _, y in positions)}, {min(x for x, _ in positions)} {max(y for _, y in positions)}, {min(x for x, _ in positions)} {min(y for _, y in positions)}))"

            # Convert composite keys to entity_key strings for belts array (backward compatibility)
            belt_key_strings = [f"({name}:{x},{y})" for name, x, y in belt_keys]
            
            con.execute(
                """
                INSERT OR REPLACE INTO belt_line (line_id, geom, line_segments, belts)
                VALUES (?, ST_GeomFromText(?), ST_GeomFromText(?), ?)
            """,
                [line_id, geom_wkt, line_wkt, json.dumps(belt_key_strings)],
            )

            # Create segments (simplified - one segment per line for now)
            # In reality, segments should be split at merges/splits
            start_key = belt_keys[0]  # (entity_name, x, y)
            end_key = belt_keys[-1]  # (entity_name, x, y)

            con.execute(
                """
                INSERT OR REPLACE INTO belt_line_segment (
                    segment_id, line_id, segment_order, geom, line, belts,
                    upstream_segments, downstream_segments, 
                    start_entity_name, start_entity_x, start_entity_y,
                    end_entity_name, end_entity_x, end_entity_y
                )
                VALUES (?, ?, ?, ST_GeomFromText(?), ST_GeomFromText(?), ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                [
                    segment_id,
                    line_id,
                    0,
                    geom_wkt,
                    line_wkt,
                    json.dumps(belt_key_strings),
                    json.dumps([]),
                    json.dumps([]),
                    start_key[0],  # entity_name
                    start_key[1],  # x
                    start_key[2],  # y
                    end_key[0],    # entity_name
                    end_key[1],    # x
                    end_key[2],    # y
                ],
            )

            line_id += 1
            segment_id += 1


def load_derived_tables(con: duckdb.DuckDBPyConnection, snapshot_dir: Path) -> None:
    """
    Load all derived tables from base tables.

    Args:
        con: DuckDB connection
        snapshot_dir: Path to snapshot directory (unused but kept for consistency)
    """
    # snapshot_dir is normalized by caller, but we don't use it here
    # (derived tables are computed from base tables in the database)
    print("Deriving electric poles...")
    derive_electric_poles(con)

    print("Deriving resource patches...")
    derive_resource_patches(con)

    print("Deriving water patches...")
    derive_water_patches(con)

    print("Deriving belt network...")
    derive_belt_network(con)

    print("Derived tables loaded successfully.")
