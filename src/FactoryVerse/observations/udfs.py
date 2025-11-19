"""User-Defined Functions (UDFs) for MapView DSL.

Provides spatial helpers and RCON-coupled functions for multi-scale queries.
"""

import json
from typing import Dict, Any, Optional, List
import duckdb

try:
    from duckdb.typing import VARCHAR, DOUBLE, BIGINT
except ImportError:
    # Fallback for older DuckDB versions
    VARCHAR = str
    DOUBLE = float
    BIGINT = int

# RCON helper will be injected at runtime
_rcon_helper = None


def register_udfs(db: duckdb.DuckDBPyConnection, rcon_helper=None):
    """
    Register all UDFs with DuckDB.
    
    Args:
        db: DuckDB connection
        rcon_helper: Optional RCON helper for real-time queries
    """
    global _rcon_helper
    _rcon_helper = rcon_helper
    
    # Spatial helper UDFs
    db.create_function('find_buildable_areas', _find_buildable_areas, 
                      [VARCHAR, DOUBLE, VARCHAR], VARCHAR)
    
    db.create_function('get_area_status', _get_area_status,
                      [VARCHAR, BIGINT], VARCHAR)
    
    db.create_function('trace_supply_chain', _trace_supply_chain,
                      [BIGINT, VARCHAR], VARCHAR)
    
    # RCON-coupled UDFs (if RCON helper available)
    if rcon_helper:
        db.create_function('get_entity_details', _get_entity_details,
                          [BIGINT], VARCHAR)
        db.create_function('get_live_inventory', _get_live_inventory,
                          [BIGINT, VARCHAR], VARCHAR)
        db.create_function('get_live_power_stats', _get_live_power_stats,
                          [BIGINT], VARCHAR)


def _find_buildable_areas(bbox_wkt: str, min_size: float, 
                         exclude_types: Optional[str] = None) -> str:
    """
    Find empty buildable areas in a bounding box.
    
    Args:
        bbox_wkt: Bounding box as WKT string
        min_size: Minimum area size in tiles
        exclude_types: JSON array of entity types to exclude
    
    Returns:
        JSON array of buildable areas with geometry
    """
    # This is a placeholder - actual implementation would query the DB
    # For now, return empty result
    return json.dumps([])


def _get_area_status(bbox_wkt: str, zoom_level: int) -> str:
    """
    Get aggregate status for an area (zoomed-out view).
    
    Args:
        bbox_wkt: Bounding box as WKT string
        zoom_level: Zoom level (1=chunk, 2=region, 3=map)
    
    Returns:
        JSON with aggregate status, warnings, issues
    """
    # Placeholder - would query materialized views
    return json.dumps({
        'warnings': [],
        'issues': [],
        'stats': {}
    })


def _trace_supply_chain(unit_number: int, direction: str) -> str:
    """
    Trace supply chain to find bottlenecks/issues.
    
    Args:
        unit_number: Entity unit number
        direction: 'upstream' or 'downstream'
    
    Returns:
        JSON array of entities in the chain with status
    """
    # Placeholder - would query supply_chain view
    return json.dumps([])


def _get_entity_details(unit_number: int) -> str:
    """
    Get live entity details via RCON (like GUI popup).
    
    Args:
        unit_number: Entity unit number
    
    Returns:
        JSON with full entity state
    """
    if not _rcon_helper:
        return json.dumps({'error': 'RCON helper not available'})
    
    try:
        # Make RCON call to inspect entity
        # This would call: rcon_helper.call('entities.inspect_entity', unit_number)
        # For now, return placeholder
        return json.dumps({'unit_number': unit_number, 'status': 'unknown'})
    except Exception as e:
        return json.dumps({'error': str(e)})


def _get_live_inventory(unit_number: int, inventory_type: Optional[str] = None) -> str:
    """
    Get live inventory via RCON.
    
    Args:
        unit_number: Entity unit number
        inventory_type: Optional inventory type filter
    
    Returns:
        JSON with inventory contents
    """
    if not _rcon_helper:
        return json.dumps({'error': 'RCON helper not available'})
    
    try:
        # Make RCON call to get inventory
        # This would call: rcon_helper.call('inventory.inspect_inventory', unit_number, inventory_type)
        return json.dumps({'unit_number': unit_number, 'inventory': {}})
    except Exception as e:
        return json.dumps({'error': str(e)})


def _get_live_power_stats(network_id: int) -> str:
    """
    Get live power stats via RCON.
    
    Args:
        network_id: Power network ID
    
    Returns:
        JSON with power statistics
    """
    if not _rcon_helper:
        return json.dumps({'error': 'RCON helper not available'})
    
    try:
        # Make RCON call to get power stats
        # This would call: rcon_helper.call('power.inspect_power', network_id)
        return json.dumps({'network_id': network_id, 'production': 0, 'consumption': 0})
    except Exception as e:
        return json.dumps({'error': str(e)})

