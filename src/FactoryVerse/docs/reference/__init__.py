"""
Documentation Reference Modules.

This package contains co-located documentation for all public APIs:
- actions.py: All action classes (walking, crafting, mining, etc.)
- views.py: ReachableView and RemoteView
- placement.py: PlacementHints and related classes
- types.py: Core types (MapPosition, Direction, etc.)

Documentation is registered with the global registry when these
modules are imported. Import order matters for proper registration.
"""

from FactoryVerse.docs.registry import get_registry


def register_all_documentation() -> None:
    """Register all documentation with the global registry.

    This function should be called once at application startup
    to ensure all documentation is registered before validation
    or generation.
    """
    # Import all reference modules to trigger registration
    from FactoryVerse.docs.reference import actions
    from FactoryVerse.docs.reference import views
    from FactoryVerse.docs.reference import placement
    from FactoryVerse.docs.reference import types


__all__ = ["register_all_documentation"]
