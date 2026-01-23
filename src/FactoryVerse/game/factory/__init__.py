"""FactoryVerse DSL package.

The DSL provides type definitions and entity implementations for the FactoryVerse
agent system. The new architecture uses FactoryVerse.factory.create_runtime()
as the entry point instead of context-based accessors.

Stable components:
- entity/ - Entity implementations with view properties (REACHABLE, REMOTE)
- types - Core types (MapPosition, Direction, BoundingBox)
- prototypes - Prototype data management
- item/ - Item and ItemStack classes

Note: Ghosts are handled via the is_ghost property on entities. View is a property
of BaseEntity that controls access (REACHABLE for full access, REMOTE for read-only).
"""

# Entity types
from .entity.base_entity import BaseEntity, EntityView
from .types import MapPosition, Direction, BoundingBox

__all__ = [
    # Core types
    "MapPosition",
    "Direction",
    "BoundingBox",
    # Entity base
    "BaseEntity",
    "EntityView",
]
