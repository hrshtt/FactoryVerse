"""Snapshot infrastructure module.

This module provides infrastructure components for snapshot data management:
- SnapshotDatabase: Database connection and schema
- SnapshotLoader: File loading and replay
- SyncService: UDP-based real-time sync
- QueryExecutor: SQL validation and entity construction

For the main entry point, use RemoteView from FactoryVerse.agent.remote_view.

Usage:
    from FactoryVerse.agent.remote_view import RemoteView
    from FactoryVerse.agent.infra.snapshot import SnapshotDatabase, SnapshotLoader

    # Use RemoteView for domain-level queries
    view = RemoteView(snapshot_dir, rcon_client=rcon)
    await view.load()
    await view.start()
"""

from .database import SnapshotDatabase
from .loader import SnapshotLoader
from .sync import SyncService
from .query import QueryExecutor
from .types import ChunkKey, LoadResult, SyncState, EntityOperation

__all__ = [
    # Infrastructure components (for advanced use)
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
