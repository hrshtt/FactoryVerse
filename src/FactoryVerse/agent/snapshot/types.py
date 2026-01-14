"""Type definitions for snapshot module.

Shared types used across all snapshot-related modules.
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any


@dataclass(frozen=True)
class ChunkKey:
    """Immutable chunk identifier.

    Factorio chunks are 32x32 tile areas. Chunk coordinates are
    the position divided by 32, floored.
    """

    x: int
    y: int

    def __hash__(self) -> int:
        return hash((self.x, self.y))

    def to_tuple(self) -> Tuple[int, int]:
        """Convert to tuple for compatibility with existing code."""
        return (self.x, self.y)

    @classmethod
    def from_position(cls, x: float, y: float) -> "ChunkKey":
        """Create chunk key from world position."""
        import math

        return cls(x=math.floor(x / 32), y=math.floor(y / 32))

    def __str__(self) -> str:
        return f"Chunk({self.x}, {self.y})"


@dataclass
class LoadResult:
    """Result of loading snapshot files.

    Returned by loader.load_all() to provide stats about what was loaded.
    """

    entity_count: int = 0
    resource_count: int = 0
    ghost_count: int = 0
    water_count: int = 0
    last_sequence: int = 0
    chunks: List[ChunkKey] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"LoadResult(entities={self.entity_count}, "
            f"resources={self.resource_count}, ghosts={self.ghost_count}, "
            f"chunks={len(self.chunks)}, last_seq={self.last_sequence})"
        )


@dataclass
class SyncState:
    """Current synchronization state.

    Used by sync service to track state and communicate with facade.
    """

    last_sequence: int = 0
    is_running: bool = False
    needs_rebuild: bool = False
    pending_updates: int = 0

    @property
    def is_synced(self) -> bool:
        """True if sync is running and no pending updates."""
        return self.is_running and self.pending_updates == 0


@dataclass
class EntityOperation:
    """Parsed entity operation from update file or UDP.

    Represents a single upsert or remove operation.
    """

    op: str  # "upsert" or "remove"
    tick: int
    sequence: int
    chunk: ChunkKey
    entity_name: str
    position: Optional[Dict[str, float]] = None
    entity_data: Optional[Dict[str, Any]] = None  # Full entity for upsert

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EntityOperation":
        """Parse from dictionary (file line or UDP payload)."""
        chunk_data = data.get("chunk", {})
        chunk = ChunkKey(x=chunk_data.get("x", 0), y=chunk_data.get("y", 0))

        return cls(
            op=data.get("op", ""),
            tick=data.get("tick", 0),
            sequence=data.get("sequence", 0),
            chunk=chunk,
            entity_name=data.get("entity_name") or data.get("name", ""),
            position=data.get("position"),
            entity_data=data.get("entity"),
        )


__all__ = [
    "ChunkKey",
    "LoadResult",
    "SyncState",
    "EntityOperation",
]
