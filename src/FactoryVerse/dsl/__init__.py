"""FactoryVerse DSL package.

NOTE: This package is undergoing a major refactoring. Some imports may be broken.
The entity/ subpackage with views and implementations is stable.
"""

# Entity types and views
from .entity.views import Reachable, RemoteView, Ghost
from .entity.base_entity import BaseEntity
from .types import MapPosition, Direction, BoundingBox

# Import top-level affordances only if context module is available
try:
    from .context import configure, playing_factorio, get_current_factory
except ImportError:
    # Context module has broken deps - skip
    configure = None
    playing_factorio = None
    get_current_factory = None

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
    # Runtime (may be None if deps broken)
    "configure",
    "playing_factorio",
    "get_current_factory",
]
