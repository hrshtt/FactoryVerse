"""FactoryVerse DSL package.

The DSL provides type definitions and entity implementations for the FactoryVerse
agent system. The new architecture uses FactoryVerse.factory.create_runtime()
as the entry point instead of context-based accessors.

Stable components:
- entity/ - Entity implementations and views (Reachable, RemoteView, Ghost)
- types - Core types (MapPosition, Direction, BoundingBox)
- prototypes - Prototype data management
- item/ - Item and ItemStack classes
"""

# Entity types and views
from .entity.views import Reachable, RemoteView, Ghost
from .entity.base_entity import BaseEntity
from .types import MapPosition, Direction, BoundingBox

__all__ = [
    # Core types
    "MapPosition",
    "Direction",
    "BoundingBox",
    # Entity base
    "BaseEntity",
    # Views
    "Reachable",
    "RemoteView",
    "Ghost",
]
