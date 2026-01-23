"""Snapshot domain module.

Contains contracts and adapters for the fv_snapshot Lua mod:
- adapter.py: MapSnapshotInterface for RCON communication
- types.py: Domain types (ChunkKey, LoadResult, etc.)
"""

from .adapter import MapSnapshotInterface, SnapshotStatus, SnapshotAreaResult, ChunkInfo
from .types import ChunkKey, LoadResult, SyncState, EntityOperation

__all__ = [
    # Adapter
    "MapSnapshotInterface",
    "SnapshotStatus",
    "SnapshotAreaResult",
    "ChunkInfo",
    # Types
    "ChunkKey",
    "LoadResult",
    "SyncState",
    "EntityOperation",
]
