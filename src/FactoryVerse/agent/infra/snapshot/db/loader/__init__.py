"""
Loaders for populating the DuckDB schema from snapshot files.
"""

from .base_loader import load_base_tables, load_ghosts
from .component_loader import load_component_tables
from .derived_loader import load_derived_tables
from .analytics_loader import load_analytics, load_power_statistics, load_agent_production_statistics
from .status_loader import (
    load_status_file,
    load_latest_status,
    get_latest_status_file,
    create_status_view,
    StatusSubscriber,
)
from .status_watcher import StatusWatcher, watch_status_files
from .main import load_all, load_all_to_file
from .utils import normalize_snapshot_dir

__all__ = [
    # Main entry points
    "load_all",
    "load_all_to_file",
    
    # Base loaders
    "load_base_tables",
    "load_ghosts",
    
    # Component loaders
    "load_component_tables",
    
    # Derived loaders
    "load_derived_tables",
    
    # Analytics loaders
    "load_analytics",
    "load_power_statistics",
    "load_agent_production_statistics",
    
    # Status loaders
    "load_status_file",
    "load_latest_status",
    "get_latest_status_file",
    "create_status_view",
    "StatusSubscriber",
    "StatusWatcher",
    "watch_status_files",
    
    # Utilities
    "normalize_snapshot_dir",
]
