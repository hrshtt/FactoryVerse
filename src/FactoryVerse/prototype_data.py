"""Single source of truth for prototype data in a Python runtime.

This module provides the PrototypeDataManager singleton that:
1. Loads factorio-data-dump.json ONCE from config
2. Applies filtering ONCE using FilterConfig
3. Caches all filtered results in memory
4. Shares the SAME filtered data objects to all consumers

This eliminates redundant file I/O and filtering, ensures consistency,
and fixes working-directory dependency issues.
"""

from typing import Optional, Dict, List, Any
import json
from pathlib import Path


class PrototypeDataManager:
    """Single source of truth for filtered prototype data.
    
    Loads raw data ONCE, applies filtering ONCE, caches results.
    All consumers get the SAME filtered data objects.
    
    This is a singleton - use get_prototype_manager() to access it.
    """
    
    def __init__(self):
        """Initialize with empty cache. Data loaded lazily on first access."""
        self._raw_data: Optional[Dict[str, Any]] = None
        self._filtered_entities: Optional[List[str]] = None
        self._filtered_recipes: Optional[List[str]] = None
        self._filtered_items: Optional[List[str]] = None
        self._resource_entities: Optional[List[str]] = None
        self._resource_tiles: Optional[List[str]] = None
        self._dump_file_path: Optional[Path] = None
    
    def _ensure_loaded(self) -> None:
        """Load and filter data if not already done.
        
        This is called automatically by all getter methods.
        Loads from config, applies filtering, caches everything.
        """
        if self._raw_data is not None:
            return  # Already loaded
        
        # Load from config (single source of truth for file path)
        from FactoryVerse.config import FactoryVerseConfig
        config = FactoryVerseConfig()
        dump_file = config.get_dump_file()  # Absolute path, validated
        
        self._dump_file_path = dump_file
        
        # Load raw data ONCE
        print(f"[PrototypeDataManager] Loading prototype data from {dump_file}")
        with open(dump_file, 'r') as f:
            self._raw_data = json.load(f)
        
        # Apply filtering ONCE
        from FactoryVerse.filtering.filters import get_filter_config
        filters = get_filter_config()
        
        print("[PrototypeDataManager] Applying filters...")
        self._filtered_entities = filters.filter_entities(self._raw_data)
        self._filtered_recipes = filters.filter_recipes(self._raw_data)
        self._filtered_items = filters.filter_items(self._raw_data)
        self._resource_entities = filters.get_resource_entities(self._raw_data)
        self._resource_tiles = filters.get_resource_tiles(self._raw_data)
        
        print(f"[PrototypeDataManager] Cached {len(self._filtered_entities)} entities, "
              f"{len(self._filtered_recipes)} recipes, {len(self._filtered_items)} items, "
              f"{len(self._resource_entities)} resource entities, {len(self._resource_tiles)} resource tiles")
    
    def get_raw_data(self) -> Dict[str, Any]:
        """Get raw prototype data (loaded once, cached).
        
        Returns:
            Dictionary containing all prototype data from factorio-data-dump.json
        """
        self._ensure_loaded()
        return self._raw_data
    
    def get_filtered_entities(self) -> List[str]:
        """Get filtered entity list (computed once, cached).
        
        Returns:
            Sorted list of entity names that pass the filter
        """
        self._ensure_loaded()
        return self._filtered_entities
    
    def get_filtered_recipes(self) -> List[str]:
        """Get filtered recipe list (computed once, cached).
        
        Returns:
            Sorted list of recipe names that pass the filter
        """
        self._ensure_loaded()
        return self._filtered_recipes
    
    def get_filtered_items(self) -> List[str]:
        """Get filtered item list (computed once, cached).
        
        Returns:
            Sorted list of item names that pass the filter
        """
        self._ensure_loaded()
        return self._filtered_items
    
    def get_resource_entities(self) -> List[str]:
        """Get resource entity list (trees, rocks) (computed once, cached).
        
        Returns:
            Sorted list of resource entity names
        """
        self._ensure_loaded()
        return self._resource_entities
    
    def get_resource_tiles(self) -> List[str]:
        """Get resource tile list (ore patches) (computed once, cached).
        
        Returns:
            Sorted list of resource tile names
        """
        self._ensure_loaded()
        return self._resource_tiles
    
    def get_dump_file_path(self) -> Optional[Path]:
        """Get the path to the dump file that was loaded.
        
        Returns:
            Path to factorio-data-dump.json, or None if not loaded yet
        """
        return self._dump_file_path
    
    def is_loaded(self) -> bool:
        """Check if data has been loaded.
        
        Returns:
            True if data is loaded and cached
        """
        return self._raw_data is not None


# Singleton instance
_prototype_manager: Optional[PrototypeDataManager] = None


def get_prototype_manager() -> PrototypeDataManager:
    """Get the global PrototypeDataManager singleton.
    
    This is the primary way to access prototype data in the codebase.
    The singleton is instantiated on first call and reused for subsequent calls.
    
    Returns:
        PrototypeDataManager instance (singleton)
        
    Example:
        >>> manager = get_prototype_manager()
        >>> entities = manager.get_filtered_entities()
        >>> recipes = manager.get_filtered_recipes()
    """
    global _prototype_manager
    if _prototype_manager is None:
        _prototype_manager = PrototypeDataManager()
    return _prototype_manager


def reset_prototype_manager() -> None:
    """Reset the singleton instance (useful for testing).
    
    After calling this, the next call to get_prototype_manager() will create
    a new instance and reload data from disk.
    
    Example:
        >>> reset_prototype_manager()
        >>> manager = get_prototype_manager()  # Fresh instance
    """
    global _prototype_manager
    _prototype_manager = None


__all__ = [
    'PrototypeDataManager',
    'get_prototype_manager',
    'reset_prototype_manager',
]
