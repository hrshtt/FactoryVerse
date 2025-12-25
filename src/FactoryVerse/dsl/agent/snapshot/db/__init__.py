"""DuckDB snapshot database module.

This module contains all DuckDB-specific implementation for snapshot storage and querying.
"""

from .schema import connect, create_schema
from .loader import load_all, load_all_to_file

__all__ = [
    "connect",
    "create_schema",
    "load_all",
    "load_all_to_file",
]
