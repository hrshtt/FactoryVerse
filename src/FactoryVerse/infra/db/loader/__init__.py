"""
Loaders for populating the DuckDB schema from snapshot files.
"""

from .base_loader import load_base_tables
from .component_loader import load_component_tables
from .derived_loader import load_derived_tables
from .main import load_all

__all__ = [
    "load_base_tables",
    "load_component_tables",
    "load_derived_tables",
    "load_all",
]

