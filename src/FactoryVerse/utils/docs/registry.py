"""
Documentation Registry.

Central registry that collects and organizes documentation from:
- Decorated methods/classes
- Reference documentation modules
- Introspected type information

The registry enforces complete coverage and provides the foundation
for generating markdown documentation.
"""

from typing import Dict, List, Type, Callable, Optional, Any, Set
import inspect
import threading
from dataclasses import dataclass

from FactoryVerse.utils.docs.models import (
    ClassDocumentation,
    MethodDocumentation,
    TypeDocumentation,
    CoverageReport,
    UndocumentedMethod,
    Example,
    ErrorCase,
)


# Thread-safe singleton
_registry_lock = threading.Lock()
_registry_instance: Optional["DocumentationRegistry"] = None


def get_registry() -> "DocumentationRegistry":
    """Get the global documentation registry instance."""
    global _registry_instance
    if _registry_instance is None:
        with _registry_lock:
            if _registry_instance is None:
                _registry_instance = DocumentationRegistry()
    return _registry_instance


def reset_registry() -> None:
    """Reset the global registry (for testing)."""
    global _registry_instance
    with _registry_lock:
        _registry_instance = None


class DocumentationRegistry:
    """Central registry for all documentation.

    The registry serves as the single source of truth for documentation,
    collecting from multiple sources:
    1. @documented_method/@documented_class decorators
    2. Reference modules (docs/reference/*.py)
    3. Introspected type information

    It enforces coverage by tracking which classes/methods SHOULD be
    documented and comparing against what IS documented.
    """

    def __init__(self):
        # Registered documentation
        self._classes: Dict[str, ClassDocumentation] = {}
        self._methods: Dict[str, MethodDocumentation] = {}  # key: "ClassName.method_name"
        self._types: Dict[str, TypeDocumentation] = {}

        # Required classes for coverage (set via register_required_class)
        self._required_classes: Set[Type] = set()
        self._required_class_names: Set[str] = set()
        # Class objects by class name, kept so validators can introspect the
        # real class behind a documented accessor (prose checks, generated
        # tables) instead of trusting a name that may no longer exist.
        self._class_objects: Dict[str, Type] = {}

        # Method registry from actual classes (for coverage checking)
        self._actual_methods: Dict[str, Set[str]] = {}  # class_name -> set of method names

    def register_class(
        self,
        cls: Type,
        accessor_name: str,
        description: str = "",
        decision_context: str = "",
        notes: Optional[List[str]] = None,
        related_classes: Optional[List[str]] = None,
        exclude_methods: Optional[Set[str]] = None,
    ) -> ClassDocumentation:
        """Register a class for documentation.

        Args:
            cls: The actual class to document
            accessor_name: How agents access this (e.g., 'walking')
            description: Class description (falls back to docstring)
            decision_context: When to use this class
            notes: Additional notes
            related_classes: Related class names
            exclude_methods: Method names to exclude from coverage tracking
                           (e.g., internal lifecycle methods)

        Returns:
            ClassDocumentation instance (can be modified further)
        """
        class_name = cls.__name__
        description = description or (cls.__doc__ or "").strip()

        doc = ClassDocumentation(
            class_name=class_name,
            accessor_name=accessor_name,
            description=description,
            decision_context=decision_context,
            notes=notes or [],
            related_classes=related_classes or [],
        )
        self._classes[class_name] = doc
        self._class_objects[class_name] = cls

        # Discover public methods on this class (excluding internal ones)
        self._discover_methods(cls, exclude_methods)

        return doc

    def register_method(
        self,
        cls: Type,
        method_name: str,
        description: str = "",
        examples: Optional[List[Example]] = None,
        error_cases: Optional[List[ErrorCase]] = None,
        decision_points: Optional[List[str]] = None,
        notes: Optional[List[str]] = None,
    ) -> MethodDocumentation:
        """Register documentation for a method.

        Args:
            cls: The class containing the method
            method_name: Name of the method
            description: Method description (falls back to docstring)
            examples: Usage examples
            error_cases: Error conditions
            decision_points: When to use this method
            notes: Additional notes

        Returns:
            MethodDocumentation instance
        """
        class_name = cls.__name__
        key = f"{class_name}.{method_name}"

        # Get the actual method
        method = getattr(cls, method_name, None)
        if method is None:
            raise ValueError(f"Method {method_name} not found on {class_name}")

        # Introspect signature
        signature, return_type, is_async, is_property = self._introspect_method(
            method, method_name
        )

        # Get description from docstring if not provided
        if not description:
            if is_property:
                description = (method.fget.__doc__ or "").strip() if method.fget else ""
            else:
                description = (method.__doc__ or "").strip()

        doc = MethodDocumentation(
            method_name=method_name,
            signature=signature,
            return_type=return_type,
            description=description,
            examples=examples or [],
            error_cases=error_cases or [],
            decision_points=decision_points or [],
            notes=notes or [],
            is_async=is_async,
            is_property=is_property,
        )

        self._methods[key] = doc

        # Also add to the class documentation if it exists
        if class_name in self._classes:
            if is_property:
                self._classes[class_name].properties.append(doc)
            else:
                self._classes[class_name].methods.append(doc)

        return doc

    def register_type(
        self,
        type_cls: Type,
        description: str = "",
        fields: Optional[Dict[str, str]] = None,
        examples: Optional[List[Example]] = None,
    ) -> TypeDocumentation:
        """Register a type (dataclass, enum, etc.) for documentation.

        Args:
            type_cls: The type to document
            description: Type description
            fields: Field name to description mapping
            examples: Usage examples

        Returns:
            TypeDocumentation instance
        """
        from enum import Enum
        from dataclasses import fields as dc_fields, is_dataclass

        type_name = type_cls.__name__
        is_enum = issubclass(type_cls, Enum) if isinstance(type_cls, type) else False

        description = description or (type_cls.__doc__ or "").strip()

        doc = TypeDocumentation(
            type_name=type_name,
            description=description,
            fields=fields or {},
            examples=examples or [],
            is_enum=is_enum,
        )

        # Auto-extract enum values
        if is_enum:
            for member in type_cls:
                doc.enum_values[member.name] = str(member.value)

        # Auto-extract dataclass fields
        if is_dataclass(type_cls) and not fields:
            for f in dc_fields(type_cls):
                # Get field description from type annotation or default
                doc.fields[f.name] = f.type.__name__ if hasattr(f.type, "__name__") else str(f.type)

        self._types[type_name] = doc
        return doc

    def register_required_class(
        self,
        cls: Type,
        exclude_methods: Optional[Set[str]] = None,
    ) -> None:
        """Mark a class as required for documentation coverage.

        This is used to ensure all public APIs are documented.
        Coverage validation will fail if this class has undocumented methods.

        Args:
            cls: The class to require documentation for
            exclude_methods: Method names to exclude from coverage tracking
                           (e.g., lifecycle methods like 'start', 'stop')
        """
        self._required_classes.add(cls)
        self._required_class_names.add(cls.__name__)
        self._discover_methods(cls, exclude_methods)

    def _discover_methods(
        self,
        cls: Type,
        exclude_methods: Optional[Set[str]] = None,
    ) -> None:
        """Discover public methods on a class for coverage tracking.

        Args:
            cls: The class to discover methods from
            exclude_methods: Method names to exclude (e.g., lifecycle methods)
        """
        class_name = cls.__name__
        methods = set()
        exclude = exclude_methods or set()

        for name, member in inspect.getmembers(cls):
            # Skip private and dunder methods
            if name.startswith("_"):
                continue

            # Skip explicitly excluded methods
            if name in exclude:
                continue

            # Include methods and properties
            if inspect.isfunction(member) or inspect.ismethod(member):
                methods.add(name)
            elif isinstance(member, property):
                methods.add(name)
            elif callable(member) and not inspect.isclass(member):
                methods.add(name)

        self._actual_methods[class_name] = methods

    def _introspect_method(
        self, method: Any, method_name: str
    ) -> tuple[str, str, bool, bool]:
        """Introspect a method to get signature, return type, async status.

        Returns:
            (signature, return_type, is_async, is_property)
        """
        is_property = isinstance(method, property)
        is_async = False

        if is_property:
            # Get the fget function
            func = method.fget
            if func is None:
                return f"{method_name}: property", "Unknown", False, True
        else:
            func = method
            # Check if it's async
            is_async = inspect.iscoroutinefunction(func)

        try:
            sig = inspect.signature(func)
            # Format parameters (skip self)
            params = []
            for pname, param in sig.parameters.items():
                if pname == "self":
                    continue
                if param.annotation != inspect.Parameter.empty:
                    type_str = self._format_type(param.annotation)
                    if param.default != inspect.Parameter.empty:
                        params.append(f"{pname}: {type_str} = ...")
                    else:
                        params.append(f"{pname}: {type_str}")
                else:
                    if param.default != inspect.Parameter.empty:
                        params.append(f"{pname}=...")
                    else:
                        params.append(pname)

            param_str = ", ".join(params)

            # Get return type
            if sig.return_annotation != inspect.Signature.empty:
                return_type = self._format_type(sig.return_annotation)
            else:
                return_type = "None"

            if is_property:
                signature = f"{method_name}: {return_type}"
            elif is_async:
                signature = f"async {method_name}({param_str}) -> {return_type}"
            else:
                signature = f"{method_name}({param_str}) -> {return_type}"

            return signature, return_type, is_async, is_property

        except (ValueError, TypeError):
            # Fallback for methods that can't be introspected
            prefix = "async " if is_async else ""
            return f"{prefix}{method_name}(...)", "Unknown", is_async, is_property

    def _format_type(self, annotation: Any) -> str:
        """Format a type annotation as a readable string."""
        if annotation is None:
            return "None"

        # Handle string annotations
        if isinstance(annotation, str):
            return annotation

        # Handle ForwardRef
        if hasattr(annotation, "__forward_arg__"):
            return annotation.__forward_arg__

        # Handle NoneType
        if annotation is type(None):
            return "None"

        # Handle typing module types
        origin = getattr(annotation, "__origin__", None)
        if origin is not None:
            args = getattr(annotation, "__args__", ())
            origin_name = getattr(origin, "__name__", str(origin))

            # Clean up common type names
            if origin_name == "list":
                origin_name = "List"
            elif origin_name == "dict":
                origin_name = "Dict"
            elif origin_name == "tuple":
                origin_name = "Tuple"
            elif origin_name == "Union":
                # Check for Optional (Union[X, None])
                if len(args) == 2 and type(None) in args:
                    non_none = [a for a in args if a is not type(None)][0]
                    return f"Optional[{self._format_type(non_none)}]"

            if args:
                arg_strs = [self._format_type(a) for a in args]
                return f"{origin_name}[{', '.join(arg_strs)}]"
            return origin_name

        # Handle regular types
        if hasattr(annotation, "__name__"):
            return annotation.__name__

        return str(annotation)

    def get_class(self, class_name: str) -> Optional[ClassDocumentation]:
        """Get documentation for a class by name."""
        return self._classes.get(class_name)

    def get_method(self, class_name: str, method_name: str) -> Optional[MethodDocumentation]:
        """Get documentation for a method."""
        return self._methods.get(f"{class_name}.{method_name}")

    def get_type(self, type_name: str) -> Optional[TypeDocumentation]:
        """Get documentation for a type."""
        return self._types.get(type_name)

    def get_all_classes(self) -> List[ClassDocumentation]:
        """Get all registered class documentation."""
        return list(self._classes.values())

    def get_all_types(self) -> List[TypeDocumentation]:
        """Get all registered type documentation."""
        return list(self._types.values())

    def get_class_object(self, class_name: str) -> Optional[Type]:
        """The real class registered under `class_name`, if any."""
        return self._class_objects.get(class_name)

    def get_class_by_accessor(self, accessor_name: str) -> Optional[Type]:
        """The real class the agent reaches through `accessor_name`."""
        for doc in self._classes.values():
            if doc.accessor_name == accessor_name:
                return self._class_objects.get(doc.class_name)
        return None

    def discovered_methods(self, class_name: str) -> Set[str]:
        """Public methods discovered on a class (what coverage is measured against)."""
        return set(self._actual_methods.get(class_name, set()))

    def verify_coverage(self) -> CoverageReport:
        """Verify that all required classes have complete documentation.

        Returns:
            CoverageReport with coverage statistics and missing items
        """
        total_methods = 0
        documented_methods = 0
        missing_methods: List[UndocumentedMethod] = []
        methods_without_examples: List[str] = []

        for cls in self._required_classes:
            class_name = cls.__name__
            actual_methods = self._actual_methods.get(class_name, set())

            for method_name in actual_methods:
                total_methods += 1
                key = f"{class_name}.{method_name}"

                if key in self._methods:
                    documented_methods += 1
                    doc = self._methods[key]
                    if not doc.examples:
                        methods_without_examples.append(key)
                else:
                    # Get signature for the undocumented method
                    method = getattr(cls, method_name, None)
                    sig, _, _, _ = self._introspect_method(method, method_name) if method else ("", "", False, False)
                    missing_methods.append(
                        UndocumentedMethod(
                            class_name=class_name,
                            method_name=method_name,
                            signature=sig,
                        )
                    )

        return CoverageReport(
            total_methods=total_methods,
            documented_methods=documented_methods,
            missing_methods=missing_methods,
            methods_without_examples=methods_without_examples,
        )

    def clear(self) -> None:
        """Clear all registered documentation (for testing)."""
        self._classes.clear()
        self._methods.clear()
        self._types.clear()
        self._required_classes.clear()
        self._required_class_names.clear()
        self._actual_methods.clear()
        self._class_objects.clear()
