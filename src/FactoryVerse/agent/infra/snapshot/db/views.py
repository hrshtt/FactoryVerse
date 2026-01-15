"""
Logical views over the raw DuckDB tables, projecting JSON blobs into
typed nested structures (STRUCT/LIST/MAP) using DuckDB's JSON functions.

These are *schema-on-read* projections: the underlying physical tables
keep JSON for maximum robustness, and views expose strongly-typed shapes for queries.
"""

from __future__ import annotations

from typing import Iterable

import duckdb


VIEW_STATEMENTS: Iterable[str] = [
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
    
    Call this after schema creation and any data load.
    
    Args:
        con: DuckDB connection
    """
    for stmt in VIEW_STATEMENTS:
        try:
            con.execute(stmt)
        except Exception:
            # View may fail if table doesn't exist (e.g., analytics tables are optional)
            pass


__all__ = ["create_views"]
