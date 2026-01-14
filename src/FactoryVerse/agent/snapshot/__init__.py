"""Snapshot module for map-wide entity queries.

This module provides RemoteView, a DuckDB-backed query interface
for accessing entities, ghosts, and resources across the entire map.

Usage:
    from FactoryVerse.agent.snapshot import RemoteView

    view = RemoteView(snapshot_dir, rcon_client=rcon)
    await view.load()  # Waits for bootstrap to complete by default
    await view.start()

    entities = view.get_entities("SELECT * FROM map_entity LIMIT 10")

Components:
    RemoteView: Main facade class (use this)
    SnapshotDatabase: Database connection and schema
    SnapshotLoader: File loading and replay
    SyncService: UDP-based real-time sync
    QueryExecutor: SQL validation and entity construction
"""

from .remote_view import RemoteView
from .database import SnapshotDatabase
from .loader import SnapshotLoader
from .sync import SyncService
from .query import QueryExecutor
from .types import ChunkKey, LoadResult, SyncState, EntityOperation

__all__ = [
    # Main entry point
    "RemoteView",
    # Components (for advanced use)
    "SnapshotDatabase",
    "SnapshotLoader",
    "SyncService",
    "QueryExecutor",
    # Types
    "ChunkKey",
    "LoadResult",
    "SyncState",
    "EntityOperation",
]
