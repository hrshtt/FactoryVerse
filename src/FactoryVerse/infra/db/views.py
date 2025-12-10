"""
Logical views over the raw DuckDB tables, projecting JSON blobs into
typed nested structures (STRUCT/LIST/MAP) using DuckDB's JSON functions.

These are *schema-on-read* projections: the underlying physical tables
(`component_transport_belt`, `component_inserter`, etc.) keep JSON for
maximum robustness, and views expose strongly-typed shapes for queries.
"""

from __future__ import annotations

from typing import Iterable

import duckdb


VIEW_STATEMENTS: Iterable[str] = [
    # ------------------------------------------------------------------
    # Belts: typed view over component_transport_belt.belt_data (JSON)
    # ------------------------------------------------------------------
    """
    CREATE OR REPLACE VIEW belt_data_typed AS
    SELECT
        entity_key,
        entity_name,
        json_transform(
            belt_data,
            '{
                "item_lines": [
                  {
                    "index": "INTEGER",
                    "items": "MAP(VARCHAR, BIGINT)"
                  }
                ],
                "belt_neighbours": {
                  "inputs":  ["VARCHAR"],
                  "outputs": ["VARCHAR"]
                },
                "belt_to_ground_type": "VARCHAR",
                "underground_neighbour_key": "VARCHAR"
            }'
        ) AS belt
    FROM component_transport_belt
    """,
    # ------------------------------------------------------------------
    # Inserters: typed view over component_inserter.inserter_data (JSON)
    # ------------------------------------------------------------------
    """
    CREATE OR REPLACE VIEW inserter_data_typed AS
    SELECT
        entity_key,
        entity_name,
        electric_network_id,
        json_transform(
            inserter_data,
            '{
                "pickup_position": {
                    "x": "DOUBLE",
                    "y": "DOUBLE"
                },
                "drop_position": {
                    "x": "DOUBLE",
                    "y": "DOUBLE"
                },
                "pickup_target_key": "VARCHAR",
                "drop_target_key":   "VARCHAR"
            }'
        ) AS inserter
    FROM component_inserter
    """,
    # ------------------------------------------------------------------
    # Electric poles: typed view over connected_poles (JSON array)
    # ------------------------------------------------------------------
    """
    CREATE OR REPLACE VIEW electric_pole_typed AS
    SELECT
        entity_key,
        entity_name,
        electric_network_id,
        json_transform(
            connected_poles,
            '["VARCHAR"]'
        ) AS connected_poles,
        supply_area
    FROM component_electric_pole
    """,
    # ------------------------------------------------------------------
    # Power statistics: typed maps for input/output/storage
    # ------------------------------------------------------------------
    """
    CREATE OR REPLACE VIEW power_statistics_typed AS
    SELECT
        tick,
        json_transform(input,   '"MAP(VARCHAR, BIGINT)"') AS input,
        json_transform(output,  '"MAP(VARCHAR, BIGINT)"') AS output,
        json_transform(storage, '"MAP(VARCHAR, BIGINT)"') AS storage
    FROM power_statistics
    """,
]


def create_views(con: duckdb.DuckDBPyConnection) -> None:
    """
    Create or replace all logical views on top of the raw tables.

    Call this after `init_schema(con)` and any data load.
    """
    for stmt in VIEW_STATEMENTS:
        con.execute(stmt)


__all__ = ["create_views"]


