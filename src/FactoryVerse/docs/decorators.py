"""
Documentation Decorators.

Decorators for co-locating documentation with method implementations.
These are an alternative to using the registry directly - they allow
documentation to live right next to the code it describes.

Example usage:

    @documented_class(
        accessor_name="walking",
        decision_context="Use for agent movement to positions or entities"
    )
    class MovementAction:

        @documented_method(
            examples=[
                Example(
                    code='await walking.walk_to(MapPosition(10, 20))',
                    decision_context="Walking to a known position",
                    expected_outcome="Agent moves to position"
                )
            ],
            error_cases=[
                ErrorCase(
                    exception="WalkingUnreachableError",
                    when="Path is blocked",
                    resolution="Clear obstacles or try different route"
                )
            ]
        )
        async def walk_to(self, goal: MapPosition) -> MapPosition:
            ...
"""

from typing import List, Optional, Callable, TypeVar, Type, Any
from functools import wraps

from FactoryVerse.docs.models import Example, ErrorCase


F = TypeVar("F", bound=Callable[..., Any])
T = TypeVar("T", bound=Type[Any])


# Metadata attribute names
_METHOD_DOC_ATTR = "_factoryverse_method_doc"
_CLASS_DOC_ATTR = "_factoryverse_class_doc"


def documented_method(
    examples: Optional[List[Example]] = None,
    error_cases: Optional[List[ErrorCase]] = None,
    decision_points: Optional[List[str]] = None,
    notes: Optional[List[str]] = None,
    description: Optional[str] = None,
) -> Callable[[F], F]:
    """Decorator to attach documentation metadata to a method.

    This decorator stores documentation metadata on the function itself,
    which can later be collected by the registry when the class is registered.

    Args:
        examples: Usage examples showing decision contexts
        error_cases: Documented error conditions
        decision_points: When to use this method vs alternatives
        notes: Additional notes or caveats
        description: Override docstring description

    Example:
        @documented_method(
            examples=[
                Example(
                    code='await walking.walk_to(MapPosition(10, 20))',
                    decision_context="Walking to a specific coordinate",
                    expected_outcome="Agent moves to (10, 20)"
                )
            ]
        )
        async def walk_to(self, goal: MapPosition) -> MapPosition:
            '''Walk to the specified position.'''
            ...
    """

    def decorator(func: F) -> F:
        # Store metadata on the function
        metadata = {
            "examples": examples or [],
            "error_cases": error_cases or [],
            "decision_points": decision_points or [],
            "notes": notes or [],
            "description": description,
        }
        setattr(func, _METHOD_DOC_ATTR, metadata)
        return func

    return decorator


def documented_class(
    accessor_name: str,
    decision_context: str = "",
    notes: Optional[List[str]] = None,
    related_classes: Optional[List[str]] = None,
    description: Optional[str] = None,
) -> Callable[[T], T]:
    """Decorator to attach documentation metadata to a class.

    This decorator stores documentation metadata on the class itself,
    which can later be collected by the registry.

    Args:
        accessor_name: How agents access this class (e.g., 'walking')
        decision_context: When to use this class vs alternatives
        notes: Additional notes
        related_classes: Related class names
        description: Override docstring description

    Example:
        @documented_class(
            accessor_name="walking",
            decision_context="Use for agent movement and navigation",
            related_classes=["ReachableView", "RemoteView"]
        )
        class MovementAction:
            '''Handles agent walking and pathfinding.'''
            ...
    """

    def decorator(cls: T) -> T:
        # Store metadata on the class
        metadata = {
            "accessor_name": accessor_name,
            "decision_context": decision_context,
            "notes": notes or [],
            "related_classes": related_classes or [],
            "description": description,
        }
        setattr(cls, _CLASS_DOC_ATTR, metadata)
        return cls

    return decorator


def get_method_doc_metadata(func: Callable) -> Optional[dict]:
    """Get documentation metadata attached to a method by decorator."""
    return getattr(func, _METHOD_DOC_ATTR, None)


def get_class_doc_metadata(cls: Type) -> Optional[dict]:
    """Get documentation metadata attached to a class by decorator."""
    return getattr(cls, _CLASS_DOC_ATTR, None)


def register_decorated_class(cls: Type) -> None:
    """Register a class and all its decorated methods with the global registry.

    This function scans a class for @documented_class and @documented_method
    decorators and registers them with the global documentation registry.

    Args:
        cls: The class to register
    """
    from FactoryVerse.docs.registry import get_registry

    registry = get_registry()

    # Get class-level metadata
    class_meta = get_class_doc_metadata(cls)
    if class_meta:
        registry.register_class(
            cls=cls,
            accessor_name=class_meta["accessor_name"],
            description=class_meta.get("description", ""),
            decision_context=class_meta.get("decision_context", ""),
            notes=class_meta.get("notes"),
            related_classes=class_meta.get("related_classes"),
        )

        # Mark as required for coverage
        registry.register_required_class(cls)

    # Scan for decorated methods
    for name in dir(cls):
        if name.startswith("_"):
            continue

        member = getattr(cls, name, None)
        if member is None:
            continue

        # Handle properties
        if isinstance(member, property):
            func = member.fget
        else:
            func = member

        method_meta = get_method_doc_metadata(func) if func else None
        if method_meta:
            registry.register_method(
                cls=cls,
                method_name=name,
                description=method_meta.get("description", ""),
                examples=method_meta.get("examples"),
                error_cases=method_meta.get("error_cases"),
                decision_points=method_meta.get("decision_points"),
                notes=method_meta.get("notes"),
            )


def auto_register(*classes: Type) -> None:
    """Register multiple decorated classes with the global registry.

    Example:
        auto_register(MovementAction, CraftingAction, ResearchAction)
    """
    for cls in classes:
        register_decorated_class(cls)
