"""Structured schema definitions for DuckDB tables.

This module defines the database schema using structured Python objects
that can be introspected for documentation generation. The schema definitions
are the single source of truth for both database creation and documentation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class ColumnDefinition:
    """Definition of a database column."""

    name: str
    """Column name."""
    type: str
    """SQL type (e.g., 'VARCHAR', 'DOUBLE', 'INTEGER')."""
    nullable: bool = True
    """Whether the column can be NULL."""
    description: str = ""
    """Human-readable description of the column."""
    default: Optional[str] = None
    """Default value (SQL expression)."""


@dataclass
class TableDefinition:
    """Definition of a database table."""

    name: str
    """Table name."""
    purpose: str
    """Human-readable description of the table's purpose."""
    columns: List[ColumnDefinition]
    """List of column definitions."""
    primary_key: List[str] = field(default_factory=list)
    """List of column names that form the primary key."""
    foreign_keys: List[Tuple[str, str, str]] = field(default_factory=list)
    """List of (column_name, foreign_table, foreign_column) tuples."""
    example_query: Optional[str] = None
    """Example SQL query for this table."""
    example_queries: Optional[List[str]] = None
    """Multiple example queries (if provided, overrides example_query)."""
    notes: Optional[str] = None
    """Additional notes about the table."""


# =============================================================================
# CORE TABLES
# =============================================================================

MAP_ENTITY = TableDefinition(
    name="map_entity",
    purpose="Core entity table containing all placed entities on the map",
    primary_key=["entity_name", "position_x", "position_y"],
    columns=[
        ColumnDefinition(
            name="entity_name",
            type="VARCHAR",
            nullable=False,
            description="Factorio internal name (e.g., 'burner-mining-drill')",
        ),
        ColumnDefinition(
            name="position_x",
            type="DOUBLE",
            nullable=False,
            description="X coordinate on the map",
        ),
        ColumnDefinition(
            name="position_y",
            type="DOUBLE",
            nullable=False,
            description="Y coordinate on the map",
        ),
        ColumnDefinition(
            name="chunk_x",
            type="INTEGER",
            nullable=False,
            description="Chunk X coordinate (for spatial queries)",
        ),
        ColumnDefinition(
            name="chunk_y",
            type="INTEGER",
            nullable=False,
            description="Chunk Y coordinate (for spatial queries)",
        ),
        ColumnDefinition(
            name="direction",
            type="VARCHAR",
            nullable=True,
            description="Entity direction (NORTH, EAST, SOUTH, WEST, etc.)",
        ),
        ColumnDefinition(
            name="bbox_min_x",
            type="DOUBLE",
            nullable=True,
            description="Bounding box minimum X",
        ),
        ColumnDefinition(
            name="bbox_min_y",
            type="DOUBLE",
            nullable=True,
            description="Bounding box minimum Y",
        ),
        ColumnDefinition(
            name="bbox_max_x",
            type="DOUBLE",
            nullable=True,
            description="Bounding box maximum X",
        ),
        ColumnDefinition(
            name="bbox_max_y",
            type="DOUBLE",
            nullable=True,
            description="Bounding box maximum Y",
        ),
        ColumnDefinition(
            name="electric_network_id",
            type="INTEGER",
            nullable=True,
            description="Electric network this entity belongs to",
        ),
        ColumnDefinition(
            name="agent_id",
            type="INTEGER",
            nullable=True,
            description="ID of agent that placed this entity (if any)",
        ),
        ColumnDefinition(
            name="player_id",
            type="INTEGER",
            nullable=True,
            description="ID of player that placed this entity (if any)",
        ),
        ColumnDefinition(
            name="label",
            type="VARCHAR",
            nullable=True,
            description="Optional user-defined label",
        ),
        ColumnDefinition(
            name="placed_tick",
            type="INTEGER",
            nullable=True,
            description="Game tick when entity was placed",
        ),
        ColumnDefinition(
            name="raw_data",
            type="VARCHAR",
            nullable=True,
            description="JSON blob with full entity data",
        ),
        ColumnDefinition(
            name="tile_x",
            type="INTEGER",
            nullable=True,
            description="Anchor tile X coordinate (integer grid position)",
        ),
        ColumnDefinition(
            name="tile_y",
            type="INTEGER",
            nullable=True,
            description="Anchor tile Y coordinate (integer grid position)",
        ),
    ],
    example_query="SELECT * FROM map_entity WHERE entity_name = 'burner-mining-drill'",
)

GHOST = TableDefinition(
    name="ghost",
    purpose="Ghost entities - planned placements that haven't been built yet",
    primary_key=["ghost_name", "position_x", "position_y"],
    columns=[
        ColumnDefinition(
            name="ghost_name",
            type="VARCHAR",
            nullable=False,
            description="Entity name this ghost will become when built",
        ),
        ColumnDefinition(
            name="position_x",
            type="DOUBLE",
            nullable=False,
            description="X coordinate on the map",
        ),
        ColumnDefinition(
            name="position_y",
            type="DOUBLE",
            nullable=False,
            description="Y coordinate on the map",
        ),
        ColumnDefinition(
            name="chunk_x",
            type="INTEGER",
            nullable=False,
            description="Chunk X coordinate",
        ),
        ColumnDefinition(
            name="chunk_y",
            type="INTEGER",
            nullable=False,
            description="Chunk Y coordinate",
        ),
        ColumnDefinition(
            name="direction",
            type="VARCHAR",
            nullable=True,
            description="Entity direction",
        ),
        ColumnDefinition(
            name="placed_tick",
            type="INTEGER",
            nullable=True,
            description="Game tick when ghost was created",
        ),
        ColumnDefinition(
            name="placed_by",
            type="VARCHAR",
            nullable=True,
            description="Who placed this ghost (agent/player)",
        ),
        ColumnDefinition(
            name="label",
            type="VARCHAR",
            nullable=True,
            description="Optional label",
        ),
        ColumnDefinition(
            name="raw_data",
            type="VARCHAR",
            nullable=True,
            description="JSON blob with full ghost data",
        ),
    ],
    example_query="SELECT * FROM ghost WHERE ghost_name = 'assembling-machine-1'",
)

RESOURCE_TILE = TableDefinition(
    name="resource_tile",
    purpose="Ore deposits (iron-ore, copper-ore, coal, stone, uranium-ore)",
    primary_key=["name", "position_x", "position_y"],
    columns=[
        ColumnDefinition(
            name="name",
            type="VARCHAR",
            nullable=False,
            description="Resource type (e.g., 'iron-ore', 'coal')",
        ),
        ColumnDefinition(
            name="position_x",
            type="DOUBLE",
            nullable=False,
            description="X coordinate",
        ),
        ColumnDefinition(
            name="position_y",
            type="DOUBLE",
            nullable=False,
            description="Y coordinate",
        ),
        ColumnDefinition(
            name="chunk_x",
            type="INTEGER",
            nullable=False,
            description="Chunk X coordinate",
        ),
        ColumnDefinition(
            name="chunk_y",
            type="INTEGER",
            nullable=False,
            description="Chunk Y coordinate",
        ),
        ColumnDefinition(
            name="amount",
            type="INTEGER",
            nullable=True,
            description="Remaining ore amount in this tile",
        ),
    ],
    example_query="SELECT * FROM resource_tile WHERE name = 'iron-ore' AND amount > 1000",
)

RESOURCE_ENTITY = TableDefinition(
    name="resource_entity",
    purpose="Natural resources like trees, rocks, and other minable objects",
    primary_key=["name", "position_x", "position_y"],
    columns=[
        ColumnDefinition(
            name="name",
            type="VARCHAR",
            nullable=False,
            description="Entity name (e.g., 'tree-01', 'rock-big')",
        ),
        ColumnDefinition(
            name="entity_type",
            type="VARCHAR",
            nullable=False,
            description="Type category (tree, simple-entity for rocks, etc.)",
        ),
        ColumnDefinition(
            name="position_x",
            type="DOUBLE",
            nullable=False,
            description="X coordinate",
        ),
        ColumnDefinition(
            name="position_y",
            type="DOUBLE",
            nullable=False,
            description="Y coordinate",
        ),
        ColumnDefinition(
            name="chunk_x",
            type="INTEGER",
            nullable=False,
            description="Chunk X coordinate",
        ),
        ColumnDefinition(
            name="chunk_y",
            type="INTEGER",
            nullable=False,
            description="Chunk Y coordinate",
        ),
        ColumnDefinition(
            name="raw_data",
            type="VARCHAR",
            nullable=True,
            description="JSON blob with full data",
        ),
    ],
    example_queries=[
        "SELECT * FROM resource_entity WHERE entity_type = 'tree'",
        "-- Query rocks (use 'rock' - automatically converted to 'simple-entity' in database)",
        "SELECT * FROM resource_entity WHERE entity_type = 'rock'",
        "-- Or use 'simple-entity' directly (database storage format)",
        "SELECT * FROM resource_entity WHERE entity_type = 'simple-entity'",
    ],
    notes=(
        "**Note on entity_type for rocks:** The database stores 'simple-entity' for rocks "
        "(Factorio's internal type), but you can use 'rock' in SQL queries via `get_resources()` - "
        "it will be automatically converted. Both work: `WHERE entity_type = 'rock'` or "
        "`WHERE entity_type = 'simple-entity'`."
    ),
)

WATER_TILE = TableDefinition(
    name="water_tile",
    purpose="Water tiles on the map",
    primary_key=["position_x", "position_y"],
    columns=[
        ColumnDefinition(
            name="position_x",
            type="DOUBLE",
            nullable=False,
            description="X coordinate",
        ),
        ColumnDefinition(
            name="position_y",
            type="DOUBLE",
            nullable=False,
            description="Y coordinate",
        ),
        ColumnDefinition(
            name="chunk_x",
            type="INTEGER",
            nullable=False,
            description="Chunk X coordinate",
        ),
        ColumnDefinition(
            name="chunk_y",
            type="INTEGER",
            nullable=False,
            description="Chunk Y coordinate",
        ),
    ],
    example_query="SELECT * FROM water_tile WHERE chunk_x = 0 AND chunk_y = 0",
)

CHUNK_SNAPSHOT_META = TableDefinition(
    name="chunk_snapshot_meta",
    purpose="Per-chunk snapshot freshness: the game tick at which each chunk's init files were last written",
    primary_key=["chunk_x", "chunk_y"],
    columns=[
        ColumnDefinition(
            name="chunk_x",
            type="INTEGER",
            nullable=False,
            description="Chunk X coordinate",
        ),
        ColumnDefinition(
            name="chunk_y",
            type="INTEGER",
            nullable=False,
            description="Chunk Y coordinate",
        ),
        ColumnDefinition(
            name="tick",
            type="BIGINT",
            nullable=False,
            description="Game tick when the chunk's init files were written",
        ),
    ],
    example_query="SELECT MIN(tick) AS oldest, MAX(tick) AS newest FROM chunk_snapshot_meta",
    notes=(
        "Written by fv_snapshot as a kind=chunk_meta first line in every init JSONL. "
        "A max(tick) far behind the current game tick means the map snapshot is stale — "
        "treat query results as old data, not as the absence of things."
    ),
)

FOOTPRINT_TILES = TableDefinition(
    name="footprint_tiles",
    purpose="Maps tiles to entities that occupy them. Enables O(1) 'what entity is at tile X?' queries.",
    primary_key=["tile_x", "tile_y"],
    columns=[
        ColumnDefinition(
            name="tile_x",
            type="INTEGER",
            nullable=False,
            description="Tile X coordinate (integer grid position)",
        ),
        ColumnDefinition(
            name="tile_y",
            type="INTEGER",
            nullable=False,
            description="Tile Y coordinate (integer grid position)",
        ),
        ColumnDefinition(
            name="entity_name",
            type="VARCHAR",
            nullable=False,
            description="Name of entity occupying this tile",
        ),
        ColumnDefinition(
            name="entity_position_x",
            type="DOUBLE",
            nullable=False,
            description="Entity center X coordinate",
        ),
        ColumnDefinition(
            name="entity_position_y",
            type="DOUBLE",
            nullable=False,
            description="Entity center Y coordinate",
        ),
        ColumnDefinition(
            name="is_ghost",
            type="BOOLEAN",
            nullable=False,
            description="Whether this is a ghost entity",
            default="FALSE",
        ),
    ],
    example_queries=[
        "-- Check if tile is occupied",
        "SELECT * FROM footprint_tiles WHERE tile_x = 5 AND tile_y = 10",
        "-- Find all tiles in an area",
        "SELECT * FROM footprint_tiles WHERE tile_x BETWEEN 0 AND 10 AND tile_y BETWEEN 0 AND 10",
        "-- Get entity at specific tile",
        "SELECT entity_name, entity_position_x, entity_position_y FROM footprint_tiles WHERE tile_x = 5 AND tile_y = 5",
    ],
    notes=(
        "**Tile-based queries**: This table enables fast integer-based spatial queries. "
        "Each entity occupies one or more tiles based on its footprint (e.g., 3x3 assembler = 9 tiles). "
        "The primary key enforces that only one entity can occupy each tile."
    ),
)

# =============================================================================
# COMPONENT TABLES
# =============================================================================

INSERTER = TableDefinition(
    name="inserter",
    purpose="Inserter-specific data",
    primary_key=["entity_name", "position_x", "position_y"],
    foreign_keys=[
        ("entity_name", "map_entity", "entity_name"),
        ("position_x", "map_entity", "position_x"),
        ("position_y", "map_entity", "position_y"),
    ],
    columns=[
        ColumnDefinition(
            name="entity_name",
            type="VARCHAR",
            nullable=False,
            description="FK to map_entity",
        ),
        ColumnDefinition(
            name="position_x",
            type="DOUBLE",
            nullable=False,
            description="FK to map_entity",
        ),
        ColumnDefinition(
            name="position_y",
            type="DOUBLE",
            nullable=False,
            description="FK to map_entity",
        ),
        ColumnDefinition(
            name="direction",
            type="VARCHAR",
            nullable=False,
            description="Inserter direction",
        ),
        ColumnDefinition(
            name="pickup_position_x",
            type="DOUBLE",
            nullable=True,
            description="Pickup position X",
        ),
        ColumnDefinition(
            name="pickup_position_y",
            type="DOUBLE",
            nullable=True,
            description="Pickup position Y",
        ),
        ColumnDefinition(
            name="drop_position_x",
            type="DOUBLE",
            nullable=True,
            description="Drop position X",
        ),
        ColumnDefinition(
            name="drop_position_y",
            type="DOUBLE",
            nullable=True,
            description="Drop position Y",
        ),
    ],
)

TRANSPORT_BELT = TableDefinition(
    name="transport_belt",
    purpose="Transport belt data",
    primary_key=["entity_name", "position_x", "position_y"],
    foreign_keys=[
        ("entity_name", "map_entity", "entity_name"),
        ("position_x", "map_entity", "position_x"),
        ("position_y", "map_entity", "position_y"),
    ],
    columns=[
        ColumnDefinition(
            name="entity_name",
            type="VARCHAR",
            nullable=False,
            description="FK to map_entity",
        ),
        ColumnDefinition(
            name="position_x",
            type="DOUBLE",
            nullable=False,
            description="FK to map_entity",
        ),
        ColumnDefinition(
            name="position_y",
            type="DOUBLE",
            nullable=False,
            description="FK to map_entity",
        ),
        ColumnDefinition(
            name="direction",
            type="VARCHAR",
            nullable=False,
            description="Belt direction",
        ),
        ColumnDefinition(
            name="belt_speed",
            type="DOUBLE",
            nullable=True,
            description="Belt speed",
        ),
    ],
)

MINING_DRILL = TableDefinition(
    name="mining_drill",
    purpose="Mining drill data",
    primary_key=["entity_name", "position_x", "position_y"],
    foreign_keys=[
        ("entity_name", "map_entity", "entity_name"),
        ("position_x", "map_entity", "position_x"),
        ("position_y", "map_entity", "position_y"),
    ],
    columns=[
        ColumnDefinition(
            name="entity_name",
            type="VARCHAR",
            nullable=False,
            description="FK to map_entity",
        ),
        ColumnDefinition(
            name="position_x",
            type="DOUBLE",
            nullable=False,
            description="FK to map_entity",
        ),
        ColumnDefinition(
            name="position_y",
            type="DOUBLE",
            nullable=False,
            description="FK to map_entity",
        ),
        ColumnDefinition(
            name="direction",
            type="VARCHAR",
            nullable=False,
            description="Drill direction",
        ),
        ColumnDefinition(
            name="mining_target",
            type="VARCHAR",
            nullable=True,
            description="What resource this drill is mining",
        ),
    ],
)

ASSEMBLER = TableDefinition(
    name="assembler",
    purpose="Assembling machine data",
    primary_key=["entity_name", "position_x", "position_y"],
    foreign_keys=[
        ("entity_name", "map_entity", "entity_name"),
        ("position_x", "map_entity", "position_x"),
        ("position_y", "map_entity", "position_y"),
    ],
    columns=[
        ColumnDefinition(
            name="entity_name",
            type="VARCHAR",
            nullable=False,
            description="FK to map_entity",
        ),
        ColumnDefinition(
            name="position_x",
            type="DOUBLE",
            nullable=False,
            description="FK to map_entity",
        ),
        ColumnDefinition(
            name="position_y",
            type="DOUBLE",
            nullable=False,
            description="FK to map_entity",
        ),
        ColumnDefinition(
            name="recipe",
            type="VARCHAR",
            nullable=True,
            description="Currently set recipe",
        ),
        ColumnDefinition(
            name="crafting_speed",
            type="DOUBLE",
            nullable=True,
            description="Crafting speed multiplier",
        ),
    ],
)

# =============================================================================
# ANALYTICS TABLES
# =============================================================================

POWER_STATISTICS = TableDefinition(
    name="power_statistics",
    purpose="Global power grid statistics over time (input/output/storage per tick)",
    primary_key=["tick"],
    columns=[
        ColumnDefinition(
            name="tick",
            type="INTEGER",
            nullable=False,
            description="Game tick when statistics were recorded",
        ),
        ColumnDefinition(
            name="input",
            type="VARCHAR",
            nullable=False,
            description="JSON: Power input by source {entity_name: joules}",
        ),
        ColumnDefinition(
            name="output",
            type="VARCHAR",
            nullable=False,
            description="JSON: Power output by consumer {entity_name: joules}",
        ),
        ColumnDefinition(
            name="storage",
            type="VARCHAR",
            nullable=False,
            description="JSON: Power in storage {entity_name: joules}",
        ),
    ],
    example_query="SELECT tick, json(input) as power_input FROM power_statistics ORDER BY tick DESC LIMIT 10",
    notes="Statistics are deduplicated - only recorded when values change from previous tick.",
)

AGENT_PRODUCTION_STATISTICS = TableDefinition(
    name="agent_production_statistics",
    purpose="Per-agent force-level production statistics over time (includes automation)",
    primary_key=["agent_id", "tick"],
    columns=[
        ColumnDefinition(
            name="agent_id",
            type="INTEGER",
            nullable=False,
            description="Agent ID",
        ),
        ColumnDefinition(
            name="tick",
            type="INTEGER",
            nullable=False,
            description="Game tick when statistics were recorded",
        ),
        ColumnDefinition(
            name="statistics",
            type="VARCHAR",
            nullable=False,
            description="JSON: {input: {item: count}, output: {item: count}}",
        ),
    ],
    example_query="SELECT agent_id, tick, json(statistics) FROM agent_production_statistics WHERE agent_id = 1 ORDER BY tick DESC LIMIT 10",
    notes="Force-level stats include ALL production (automation + manual). Use with agent_manual_production_statistics to isolate automation.",
)

AGENT_MANUAL_PRODUCTION_STATISTICS = TableDefinition(
    name="agent_manual_production_statistics",
    purpose="Per-agent manual production statistics (hand-crafted and hand-mined items only)",
    primary_key=["agent_id", "tick"],
    columns=[
        ColumnDefinition(
            name="agent_id",
            type="INTEGER",
            nullable=False,
            description="Agent ID",
        ),
        ColumnDefinition(
            name="tick",
            type="INTEGER",
            nullable=False,
            description="Game tick when statistics were recorded",
        ),
        ColumnDefinition(
            name="crafted",
            type="VARCHAR",
            nullable=False,
            description="JSON: Items hand-crafted by agent {item_name: count}",
        ),
        ColumnDefinition(
            name="mined",
            type="VARCHAR",
            nullable=False,
            description="JSON: Items hand-mined by agent {item_name: count}",
        ),
    ],
    example_queries=[
        "-- Get latest manual production for agent 1",
        "SELECT tick, json(crafted), json(mined) FROM agent_manual_production_statistics WHERE agent_id = 1 ORDER BY tick DESC LIMIT 1",
        "-- Calculate automation-produced items (pseudocode):",
        "-- automation[item] = force_output[item] - manual_crafted[item] - manual_mined[item]",
    ],
    notes=(
        "Tracks ONLY items produced by the agent character directly (crafting queue, mining). "
        "Does NOT include items produced by machines/automation. "
        "Use with agent_production_statistics to calculate automation output: "
        "automation = force_output - manual_crafted - manual_mined"
    ),
)

# =============================================================================
# SCHEMA COLLECTIONS
# =============================================================================

# Core tables (main entity/resource tables)
CORE_TABLES: List[TableDefinition] = [
    MAP_ENTITY,
    GHOST,
    RESOURCE_TILE,
    RESOURCE_ENTITY,
    WATER_TILE,
    CHUNK_SNAPSHOT_META,
    FOOTPRINT_TILES,
]

# Component tables (joined via foreign keys)
COMPONENT_TABLES: List[TableDefinition] = [
    INSERTER,
    TRANSPORT_BELT,
    MINING_DRILL,
    ASSEMBLER,
]

# Analytics tables (time-series data)
ANALYTICS_TABLES: List[TableDefinition] = [
    POWER_STATISTICS,
    AGENT_PRODUCTION_STATISTICS,
    AGENT_MANUAL_PRODUCTION_STATISTICS,
]

# All tables
ALL_TABLES: List[TableDefinition] = CORE_TABLES + COMPONENT_TABLES + ANALYTICS_TABLES

# Table lookup by name
TABLE_BY_NAME: dict[str, TableDefinition] = {table.name: table for table in ALL_TABLES}


__all__ = [
    "ColumnDefinition",
    "TableDefinition",
    # Core tables
    "MAP_ENTITY",
    "GHOST",
    "RESOURCE_TILE",
    "RESOURCE_ENTITY",
    "WATER_TILE",
    "FOOTPRINT_TILES",
    # Component tables
    "INSERTER",
    "TRANSPORT_BELT",
    "MINING_DRILL",
    "ASSEMBLER",
    # Analytics tables
    "POWER_STATISTICS",
    "AGENT_PRODUCTION_STATISTICS",
    "AGENT_MANUAL_PRODUCTION_STATISTICS",
    # Collections
    "CORE_TABLES",
    "COMPONENT_TABLES",
    "ANALYTICS_TABLES",
    "ALL_TABLES",
    "TABLE_BY_NAME",
]
