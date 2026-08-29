"""
Documentation Reference Modules.

This package contains co-located documentation for all public APIs:
- actions.py: All action classes (walking, crafting, mining, etc.)
- views.py: ReachableView and RemoteView
- entity_reference.py: the planning-time reference (Constitution §6)
- types.py: Core types (MapPosition, Direction, etc.)

Documentation is registered with the global registry when these
modules are imported. Import order matters for proper registration.
"""

from FactoryVerse.utils.docs.registry import get_registry


def register_all_documentation() -> None:
    """Register all documentation with the global registry.

    Safe to call repeatedly (registration is keyed by class/method name,
    so re-registration overwrites idempotently). Must NOT rely on import
    side effects alone: Python caches imports, so after a reset_registry()
    a bare re-import would silently register nothing.
    """
    from FactoryVerse.utils.docs.reference import actions
    from FactoryVerse.utils.docs.reference import views
    from FactoryVerse.utils.docs.reference import types
    from FactoryVerse.utils.docs.reference import entity_reference

    actions._register_actions()
    views._register_views()
    types._register_types()
    entity_reference._register_entity_reference()


__all__ = ["register_all_documentation"]
