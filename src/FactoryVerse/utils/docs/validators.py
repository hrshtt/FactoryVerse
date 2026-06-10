"""
Documentation Validators.

Validates documentation coverage and example correctness at multiple levels:
1. Syntax validation - Check examples are valid Python
2. Import validation - Check imports resolve
3. Execution validation - Run examples in test environment

These validators are designed to run in CI to ensure documentation
stays in sync with implementation.
"""

import ast
import sys
import traceback
from typing import List, Type, Optional, Any, Dict
from dataclasses import dataclass

from FactoryVerse.utils.docs.models import (
    Example,
    CoverageReport,
    ValidationReport,
    ExampleValidationResult,
    ValidationLevel,
)
from FactoryVerse.utils.docs.registry import DocumentationRegistry, get_registry


class CoverageValidator:
    """Validates documentation coverage for required classes.

    This validator checks that all public methods on required classes
    are documented, and optionally that all documented methods have examples.
    """

    def __init__(self, registry: Optional[DocumentationRegistry] = None):
        self._registry = registry or get_registry()

    def validate(
        self,
        required_classes: Optional[List[Type]] = None,
        require_examples: bool = False,
    ) -> CoverageReport:
        """Validate coverage for required classes.

        Args:
            required_classes: Classes to validate. If None, uses classes
                            registered with register_required_class()
            require_examples: If True, also fail on methods without examples

        Returns:
            CoverageReport with coverage statistics
        """
        # Register any additional required classes
        if required_classes:
            for cls in required_classes:
                self._registry.register_required_class(cls)

        report = self._registry.verify_coverage()

        return report

    def assert_complete(
        self,
        required_classes: Optional[List[Type]] = None,
        require_examples: bool = False,
    ) -> None:
        """Assert that documentation is complete.

        Raises AssertionError if coverage is incomplete, suitable for
        use in CI/test environments.
        """
        report = self.validate(required_classes, require_examples)

        if not report.complete:
            raise AssertionError(
                f"Documentation incomplete:\n{report.summary()}"
            )

        if require_examples and report.methods_without_examples:
            raise AssertionError(
                f"Methods missing examples:\n" +
                "\n".join(f"  - {m}" for m in report.methods_without_examples)
            )


class ExampleValidator:
    """Validates that documentation examples are correct.

    Supports multiple validation levels:
    - SYNTAX: Parse as Python (fast, no imports needed)
    - IMPORT: Check imports resolve (medium, needs installed packages)
    - EXECUTION: Actually run in environment (slow, needs Factorio)
    """

    def __init__(self, registry: Optional[DocumentationRegistry] = None):
        self._registry = registry or get_registry()

    def validate_syntax(self, example: Example) -> ExampleValidationResult:
        """Validate that an example is syntactically valid Python.

        Args:
            example: The example to validate

        Returns:
            ExampleValidationResult with validation status
        """
        try:
            # Wrap in async function if it contains await
            code = example.code.strip()
            if "await " in code:
                code = f"async def _validate_():\n" + "\n".join(
                    "    " + line for line in code.split("\n")
                )

            ast.parse(code)
            return ExampleValidationResult(
                example=example,
                method_name="",
                class_name="",
                valid=True,
            )
        except SyntaxError as e:
            return ExampleValidationResult(
                example=example,
                method_name="",
                class_name="",
                valid=False,
                error=str(e),
                error_type="SyntaxError",
            )

    def validate_all_syntax(self) -> ValidationReport:
        """Validate syntax of all registered examples.

        Includes:
        - Examples from class/method documentation
        - Standalone examples (e.g., inspection schema examples)

        Returns:
            ValidationReport with validation results
        """
        total = 0
        valid = 0
        failed: List[ExampleValidationResult] = []

        # Class/method examples from registry
        for class_doc in self._registry.get_all_classes():
            for method_doc in class_doc.methods + class_doc.properties:
                for example in method_doc.examples:
                    total += 1
                    result = self.validate_syntax(example)
                    result.method_name = method_doc.method_name
                    result.class_name = class_doc.class_name

                    if result.valid:
                        valid += 1
                    else:
                        failed.append(result)

        # Standalone examples from inspection module
        standalone_examples = self._collect_standalone_examples()
        for source_name, example in standalone_examples:
            total += 1
            result = self.validate_syntax(example)
            result.method_name = source_name
            result.class_name = "EntityInspection"

            if result.valid:
                valid += 1
            else:
                failed.append(result)

        return ValidationReport(
            total_examples=total,
            valid_examples=valid,
            failed_validations=failed,
        )

    def _collect_standalone_examples(self) -> List[tuple]:
        """Collect examples from standalone sources (not attached to classes).

        Returns:
            List of (source_name, Example) tuples
        """
        examples = []

        # Inspection schema examples
        try:
            from FactoryVerse.utils.docs.reference.inspection import get_inspection_examples
            for i, example in enumerate(get_inspection_examples()):
                examples.append((f"inspection_example_{i+1}", example))
        except ImportError:
            pass

        return examples

    async def validate_execution(
        self,
        example: Example,
        runtime: Any,
        class_name: str = "",
        method_name: str = "",
    ) -> ExampleValidationResult:
        """Validate an example by executing it in a runtime environment.

        Args:
            example: The example to validate
            runtime: AgentRuntime instance with walking, crafting, etc.
            class_name: Class name for reporting
            method_name: Method name for reporting

        Returns:
            ExampleValidationResult with execution status
        """
        # Build execution namespace with runtime components
        namespace = self._build_namespace(runtime)

        # Run setup code if provided
        if example.setup_code:
            try:
                exec(compile(example.setup_code, "<setup>", "exec"), namespace)
            except Exception as e:
                return ExampleValidationResult(
                    example=example,
                    method_name=method_name,
                    class_name=class_name,
                    valid=False,
                    error=f"Setup failed: {e}",
                    error_type=type(e).__name__,
                )

        # Execute the example
        try:
            code = example.code.strip()
            # Handle async code
            if "await " in code:
                # Wrap in async function and execute
                wrapped = f"async def _run_example_():\n" + "\n".join(
                    "    " + line for line in code.split("\n")
                )
                exec(compile(wrapped, "<example>", "exec"), namespace)
                import asyncio
                await namespace["_run_example_"]()
            else:
                exec(compile(code, "<example>", "exec"), namespace)

            return ExampleValidationResult(
                example=example,
                method_name=method_name,
                class_name=class_name,
                valid=True,
            )

        except Exception as e:
            return ExampleValidationResult(
                example=example,
                method_name=method_name,
                class_name=class_name,
                valid=False,
                error=str(e),
                error_type=type(e).__name__,
            )

        finally:
            # Run teardown code if provided
            if example.teardown_code:
                try:
                    exec(compile(example.teardown_code, "<teardown>", "exec"), namespace)
                except Exception:
                    pass  # Ignore teardown errors

    def _build_namespace(self, runtime: Any) -> Dict[str, Any]:
        """Build execution namespace from runtime."""
        namespace = {
            # Core types
            "MapPosition": None,
            "TilePosition": None,
            "Direction": None,
            # Runtime components
            "walking": getattr(runtime, "walking", None),
            "crafting": getattr(runtime, "crafting", None),
            "research": getattr(runtime, "research", None),
            "inventory": getattr(runtime, "inventory", None),
            "mining": getattr(runtime, "mining", None),
            "placement": getattr(runtime, "placement", None),
            "entity_ops": getattr(runtime, "entity_ops", None),
            "reachable_view": getattr(runtime, "reachable_view", None),
            "remote_view": getattr(runtime, "remote_view", None),
            "ghost_builder": getattr(runtime, "ghost_builder", None),
            "placement_hints": getattr(runtime, "placement_hints", None),
        }

        # Import core types
        try:
            from FactoryVerse.types import MapPosition, TilePosition, Direction
            namespace["MapPosition"] = MapPosition
            namespace["TilePosition"] = TilePosition
            namespace["Direction"] = Direction
        except ImportError:
            pass

        return namespace

    async def validate_all_execution(
        self,
        runtime: Any,
        validation_level: ValidationLevel = ValidationLevel.EXECUTION,
    ) -> ValidationReport:
        """Validate all examples by execution.

        Args:
            runtime: AgentRuntime instance
            validation_level: Minimum level for validation

        Returns:
            ValidationReport with validation results
        """
        total = 0
        valid = 0
        failed: List[ExampleValidationResult] = []

        for class_doc in self._registry.get_all_classes():
            for method_doc in class_doc.methods + class_doc.properties:
                for example in method_doc.examples:
                    # Skip examples below the requested level
                    if example.validation_level.value < validation_level.value:
                        continue

                    total += 1
                    result = await self.validate_execution(
                        example=example,
                        runtime=runtime,
                        class_name=class_doc.class_name,
                        method_name=method_doc.method_name,
                    )

                    if result.valid:
                        valid += 1
                    else:
                        failed.append(result)

        return ValidationReport(
            total_examples=total,
            valid_examples=valid,
            failed_validations=failed,
        )

    def assert_all_syntax_valid(self) -> None:
        """Assert all examples have valid syntax.

        Raises AssertionError if any examples have syntax errors.
        """
        report = self.validate_all_syntax()
        if not report.all_valid:
            raise AssertionError(
                f"Example validation failed:\n{report.summary()}"
            )


class StaticAttributeValidator:
    """Validates that example code references valid attributes on known types.

    This is a COMPLETE type checker for FactoryVerse documentation examples.
    The type system is the research artifact - incomplete coverage is a bug.

    Works by:
    1. Parsing example code as AST
    2. Tracking variable types through assignments using exhaustive accessor mappings
    3. Checking ALL attribute accesses against actual class definitions
    4. Failing on any unverified access (gaps in type coverage = bugs to fix)

    No Factorio runtime needed - runs purely on Python introspection.
    """

    # ==========================================================================
    # EXHAUSTIVE TYPE MAPPINGS
    # ==========================================================================
    # Every accessor and its return type. If something is missing, ADD IT.
    # Incomplete coverage means the type system has a gap.

    # Method call -> return type name
    ACCESSOR_RETURN_TYPES: Dict[str, str] = {
        # ReachableView
        "reachable_view.get_entity": "BaseEntity",
        "reachable_view.get_entities": "List[BaseEntity]",
        "reachable_view.get_resource": "BaseResource",
        "reachable_view.get_resources": "List[ResourceOrePatch]",
        "reachable_view.get_ghosts": "List[BaseEntity]",

        # RemoteView
        "remote_view.get_entity": "BaseEntity",
        "remote_view.get_entities": "List[BaseEntity]",
        "remote_view.get_resources": "List[BaseResource]",
        "remote_view.get_ghosts": "List[BaseEntity]",
        "remote_view.query": "List[Dict]",
        "remote_view.find_water": "List[Dict]",
        "remote_view.count_entities": "int",
        "remote_view.count_ghosts": "int",

        # Inventory
        "inventory.get_item": "PlaceableItem",
        "inventory.get_items": "List[Item]",
        "inventory.create_item_stacks": "List[ItemStack]",
        "inventory.check_total": "int",

        # PlacementHints
        # NOTE: get_connection_positions has polymorphic return type based on connection_type
        # Default to ConnectionPosition, but refined by POLYMORPHIC_RETURN_TYPES below
        "placement_hints.get_connection_positions": "List[ConnectionPosition]",
        "placement_hints.is_buildable": "Dict",
        "placement_hints.get_placement_line": "GhostPlan",
        "placement_hints.get_underground_segment": "GhostPlan",
        "placement_hints.get_pole_line": "GhostPlan",
        "placement_hints.get_pole_coverage_position": "Optional[MapPosition]",
        "placement_hints.get_pole_coverage_plan": "Tuple[GhostPlan, List]",
        "placement_hints.get_inserter_placement_positions": "List[Tuple[MapPosition, Direction]]",
        "placement_hints.evaluate_pole_placement": "PolePlacementResult",

        # Crafting
        "crafting.craft": "List[ItemStack]",
        "crafting.status": "Dict",
        "crafting.enqueue": "Dict",
        "crafting.dequeue": "Dict",

        # Mining
        "mining.mine": "List[ItemStack]",
        "mining.cancel": "MiningCancelled",

        # Placement
        # NOTE: place has polymorphic return type based on return_entity flag
        # Default to EntityPlaced, refined by POLYMORPHIC_RETURN_TYPES below
        "placement.place": "EntityPlaced",
        "placement.remove_ghost": "GhostRemoved",

        # EntityOperations
        "entity_ops.inspect_entity": "Dict",
        "entity_ops.pickup_entity": "EntityPickedUp",
        "entity_ops.set_entity_recipe": "EntityRecipeSet",
        "entity_ops.set_entity_filter": "EntityFilterSet",
        "entity_ops.set_inventory_limit": "InventoryLimitSet",
        "entity_ops.take_inventory_item": "InventoryItemTaken",
        "entity_ops.put_inventory_item": "InventoryItemPut",

        # Walking
        "walking.walk_to": "MapPosition",
        "walking.walk_to_position": "MapPosition",
        "walking.walk_to_entity": "MapPosition",
        "walking.position": "MapPosition",
        "walking.stop": "WalkingStopped",

        # Research
        "research.status": "ResearchStatus",
        "research.queue": "List[QueuedTechnology]",
        "research.enqueue": "Dict",
        "research.dequeue": "Dict",
        "research.get_queue": "Dict",

        # RemoteView tile queries
        "remote_view.is_tile_occupied": "bool",
        "remote_view.get_entity_at_tile": "BaseEntity",
        "remote_view.get_entities_in_tile_area": "List[BaseEntity]",
        "remote_view.get_entities_at_anchor_tile": "List[BaseEntity]",

        # GhostBuilder
        "ghost_builder.build_plan": "Dict",
        "ghost_builder.build_ghosts": "Dict",
        "ghost_builder.build_ghost": "bool",

        # Entity methods
        ".inspect": "EntityInspection",
        ".add_fuel": "None",
        ".add_ingredients": "None",
        ".set_recipe": "None",
        ".rotate": "None",
        ".place": "BaseEntity",
        ".place_ghost": "BaseEntity",
        ".build": "BaseEntity",
        ".remove": "None",
        ".walk_to": "MapPosition",
        ".mine": "List[ItemStack]",
    }

    # List element types (when iterating over a list)
    LIST_ELEMENT_TYPES: Dict[str, str] = {
        "List[BaseEntity]": "BaseEntity",
        "List[BaseResource]": "BaseResource",
        "List[ResourceOrePatch]": "ResourceOrePatch",
        "List[ItemStack]": "ItemStack",
        "List[Item]": "Item",
        "List[ConnectionPosition]": "ConnectionPosition",
        "List[WireConnectionPosition]": "WireConnectionPosition",
        "List[QueuedTechnology]": "QueuedTechnology",
        "List[Dict]": "Dict",
        "List[Tuple[MapPosition, Direction]]": "Tuple[MapPosition, Direction]",
    }

    # Index access types (when accessing list[0])
    INDEX_ACCESS_TYPES: Dict[str, str] = LIST_ELEMENT_TYPES  # Same as iteration

    # Polymorphic return types - when return type depends on argument values
    # Format: (method_pattern, arg_pattern) -> refined_return_type
    POLYMORPHIC_RETURN_TYPES: Dict[tuple, str] = {
        # get_connection_positions returns WireConnectionPosition for ELECTRIC_WIRE
        ("placement_hints.get_connection_positions", "ConnectionType.ELECTRIC_WIRE"): "List[WireConnectionPosition]",
        ("placement_hints.get_connection_positions", "ELECTRIC_WIRE"): "List[WireConnectionPosition]",
        # place returns a full BaseEntity when return_entity=True
        ("placement.place", "return_entity=True"): "BaseEntity",
    }

    # ==========================================================================
    # EXPLICIT SKIP-LIST FOR UNMAPPED ACCESSOR CALLS (L3.1b)
    # ==========================================================================
    # Any example calling `<accessor>.<method>(...)` on a known accessor
    # namespace MUST have that call mapped in ACCESSOR_RETURN_TYPES, OR appear
    # here with a rationale. Anything else FAILS validation loudly — silent
    # skipping of unmapped accessors is the bug this list exists to prevent.
    UNMAPPED_ACCESSOR_SKIP_LIST: Dict[str, str] = {}

    def __init__(self, registry: Optional[DocumentationRegistry] = None):
        self._registry = registry or get_registry()
        self._class_map = self._build_class_map()
        # Non-vacuity instrumentation (L3.1b): number of accessor method calls
        # actually checked against ACCESSOR_RETURN_TYPES during the last
        # validate_all_attributes() run. Tests assert this is > 0 so the
        # unmapped-accessor check can never pass by not running.
        self.accessor_calls_checked: int = 0

    @classmethod
    def _accessor_namespaces(cls) -> set:
        """Known accessor namespaces (e.g. 'reachable_view', 'inventory').

        Derived from ACCESSOR_RETURN_TYPES so a new accessor namespace is
        covered the moment its first method is mapped.
        """
        return {
            key.split(".", 1)[0]
            for key in cls.ACCESSOR_RETURN_TYPES
            if "." in key and not key.startswith(".")
        }

    def _build_class_map(self) -> Dict[str, Type]:
        """Build mapping of type names to actual Python classes for introspection."""
        class_map = {}

        try:
            from FactoryVerse.game.factory.resource.base import ResourceOrePatch, BaseResource
            from FactoryVerse.game.factory.entity.base_entity import BaseEntity
            from FactoryVerse.game.factory.item.base import Item, PlaceableItem, ItemStack
            from FactoryVerse.game.factory.entity.inspection import EntityInspection
            from FactoryVerse.game.factory.types import MapPosition, TilePosition
            from FactoryVerse.game.agent.placement_hints import (
                ConnectionPosition, WireConnectionPosition, GhostPlan, PolePlacementResult
            )
            from FactoryVerse.game.agent.embodied_actions.research import ResearchStatus, QueuedTechnology
            from FactoryVerse.game.agent.embodied_actions.mining import MiningCancelled
            from FactoryVerse.game.agent.embodied_actions.walking import WalkingStopped
            from FactoryVerse.game.agent.embodied_actions.place_entity import (
                EntityPlaced, GhostRemoved
            )
            from FactoryVerse.game.agent.embodied_actions.entity_operations import (
                EntityRecipeSet, EntityFilterSet, InventoryLimitSet,
                InventoryItemTaken, InventoryItemPut, EntityPickedUp,
            )

            class_map.update({
                "ResourceOrePatch": ResourceOrePatch,
                "BaseResource": BaseResource,
                "BaseEntity": BaseEntity,
                "Item": Item,
                "PlaceableItem": PlaceableItem,
                "ItemStack": ItemStack,
                "EntityInspection": EntityInspection,
                "MapPosition": MapPosition,
                "TilePosition": TilePosition,
                "ConnectionPosition": ConnectionPosition,
                "WireConnectionPosition": WireConnectionPosition,
                "GhostPlan": GhostPlan,
                "PolePlacementResult": PolePlacementResult,
                "ResearchStatus": ResearchStatus,
                "QueuedTechnology": QueuedTechnology,
                "MiningCancelled": MiningCancelled,
                "WalkingStopped": WalkingStopped,
                "EntityPlaced": EntityPlaced,
                "GhostRemoved": GhostRemoved,
                "EntityRecipeSet": EntityRecipeSet,
                "EntityFilterSet": EntityFilterSet,
                "InventoryLimitSet": InventoryLimitSet,
                "InventoryItemTaken": InventoryItemTaken,
                "InventoryItemPut": InventoryItemPut,
                "EntityPickedUp": EntityPickedUp,
            })
        except ImportError as e:
            # If imports fail, that's a bug in the type system setup.
            # Failing loudly here is mandatory: an empty class map would make
            # every attribute check silently pass (L3.1b hardening).
            raise ImportError(
                f"StaticAttributeValidator could not import type-system classes; "
                f"validation would be vacuous: {e}"
            ) from e

        return class_map

    def _get_class_attributes(self, cls: Type) -> set:
        """Get all public attributes (properties, methods, and instance attrs) of a class."""
        attrs = set()

        # Get class-level attributes (methods, properties)
        for name in dir(cls):
            if not name.startswith('_'):
                attrs.add(name)

        # Get instance attributes from __init__ annotations
        try:
            import typing
            hints = typing.get_type_hints(cls.__init__)
            for name in hints:
                if not name.startswith('_') and name != 'return':
                    attrs.add(name)
        except Exception:
            pass

        # Also check __init__ source for self.X assignments (catches non-annotated attrs)
        try:
            import inspect
            source = inspect.getsource(cls.__init__)
            # Simple pattern matching for self.X = ...
            import re
            for match in re.finditer(r'self\.(\w+)\s*=', source):
                attr_name = match.group(1)
                if not attr_name.startswith('_'):
                    attrs.add(attr_name)
        except Exception:
            pass

        # For dataclasses, get fields
        try:
            from dataclasses import fields, is_dataclass
            if is_dataclass(cls):
                for field in fields(cls):
                    attrs.add(field.name)
        except Exception:
            pass

        return attrs

    def _trace_variable_types(self, code: str) -> Dict[str, str]:
        """Trace variable types through the code using AST analysis.

        Returns a mapping of variable names to their inferred type names.
        """
        import re

        var_types: Dict[str, str] = {}

        # Parse assignments: VAR = accessor.method(...)
        for accessor_pattern, return_type in self.ACCESSOR_RETURN_TYPES.items():
            if "." in accessor_pattern and not accessor_pattern.startswith("."):
                # Full accessor pattern like "reachable_view.get_entity"
                pattern = rf"(\w+)\s*=\s*{re.escape(accessor_pattern)}\s*\(([^)]*)\)"
                for match in re.finditer(pattern, code, re.DOTALL):
                    var_name = match.group(1)
                    args_str = match.group(2)

                    # Check for polymorphic return type refinement
                    refined_type = return_type
                    for (method, arg_pattern), poly_type in self.POLYMORPHIC_RETURN_TYPES.items():
                        if method == accessor_pattern and arg_pattern in args_str:
                            refined_type = poly_type
                            break

                    var_types[var_name] = refined_type

        # Trace for-loop iterations: for VAR in COLLECTION:
        for_pattern = r"for\s+(\w+)\s+in\s+(\w+)\s*:"
        for match in re.finditer(for_pattern, code):
            loop_var = match.group(1)
            collection_var = match.group(2)

            # If we know the collection type, get the element type
            if collection_var in var_types:
                collection_type = var_types[collection_var]
                if collection_type in self.LIST_ELEMENT_TYPES:
                    var_types[loop_var] = self.LIST_ELEMENT_TYPES[collection_type]

        # Trace index access: VAR = COLLECTION[0] or VAR = COLLECTION[i]
        index_pattern = r"(\w+)\s*=\s*(\w+)\s*\[\s*\d+\s*\]"
        for match in re.finditer(index_pattern, code):
            result_var = match.group(1)
            collection_var = match.group(2)

            if collection_var in var_types:
                collection_type = var_types[collection_var]
                if collection_type in self.INDEX_ACCESS_TYPES:
                    var_types[result_var] = self.INDEX_ACCESS_TYPES[collection_type]

        # Trace method calls on known types: VAR = known_var.method(...)
        for var_name, var_type in list(var_types.items()):
            for method_pattern, return_type in self.ACCESSOR_RETURN_TYPES.items():
                if method_pattern.startswith("."):
                    # Method pattern like ".inspect"
                    method_name = method_pattern[1:]
                    pattern = rf"(\w+)\s*=\s*{re.escape(var_name)}\.{re.escape(method_name)}\s*\("
                    for match in re.finditer(pattern, code):
                        result_var = match.group(1)
                        var_types[result_var] = return_type

        return var_types

    def _infer_variable_type(self, code: str, var_name: str) -> Optional[str]:
        """Infer the type of a specific variable from code.

        Uses comprehensive type tracing through the code.
        """
        var_types = self._trace_variable_types(code)
        return var_types.get(var_name)

    def validate_example_attributes(self, example: Example) -> ExampleValidationResult:
        """Validate that attribute accesses in example code are valid.

        Args:
            example: The example to validate

        Returns:
            ExampleValidationResult with validation status
        """
        code = example.code.strip()

        # Wrap async code for parsing
        if "await " in code:
            code = f"async def _validate_():\n" + "\n".join(
                "    " + line for line in code.split("\n")
            )

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return ExampleValidationResult(
                example=example,
                method_name="",
                class_name="",
                valid=False,
                error=str(e),
                error_type="SyntaxError",
            )

        errors = []

        # ----------------------------------------------------------------
        # L3.1b: unmapped-accessor check (loud failure, no silent skips)
        # ----------------------------------------------------------------
        # Every method call on a known accessor namespace must be mapped in
        # ACCESSOR_RETURN_TYPES or listed in UNMAPPED_ACCESSOR_SKIP_LIST.
        # Without this, a call like `x = reachable_view.made_up_method()`
        # leaves `x` untyped and every attribute access on it passes silently.
        namespaces = self._accessor_namespaces()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in namespaces
            ):
                full_accessor = f"{node.func.value.id}.{node.func.attr}"
                self.accessor_calls_checked += 1
                if (
                    full_accessor not in self.ACCESSOR_RETURN_TYPES
                    and full_accessor not in self.UNMAPPED_ACCESSOR_SKIP_LIST
                ):
                    errors.append(
                        f"'{full_accessor}(...)' - accessor not mapped in "
                        f"ACCESSOR_RETURN_TYPES and not in UNMAPPED_ACCESSOR_SKIP_LIST. "
                        f"Add the mapping (preferred) or skip-list it with a rationale."
                    )

        # Find all attribute accesses
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                # Get the variable name (e.g., 'patch' from patch.total_amount)
                if isinstance(node.value, ast.Name):
                    var_name = node.value.id
                    attr_name = node.attr

                    # Try to infer the type
                    inferred_type = self._infer_variable_type(example.code, var_name)

                    if inferred_type and inferred_type in self._class_map:
                        cls = self._class_map[inferred_type]
                        valid_attrs = self._get_class_attributes(cls)

                        if attr_name not in valid_attrs:
                            # Find similar attributes for suggestion
                            similar = [a for a in valid_attrs if attr_name.lower() in a.lower() or a.lower() in attr_name.lower()]
                            suggestion = f" Did you mean: {', '.join(similar)}?" if similar else ""
                            errors.append(
                                f"'{var_name}.{attr_name}' - attribute '{attr_name}' does not exist on {inferred_type}.{suggestion}"
                            )

        if errors:
            return ExampleValidationResult(
                example=example,
                method_name="",
                class_name="",
                valid=False,
                error="; ".join(errors),
                error_type="AttributeError",
            )

        return ExampleValidationResult(
            example=example,
            method_name="",
            class_name="",
            valid=True,
        )

    def validate_all_attributes(self) -> ValidationReport:
        """Validate attributes in all registered examples.

        Returns:
            ValidationReport with validation results
        """
        total = 0
        valid = 0
        failed: List[ExampleValidationResult] = []
        self.accessor_calls_checked = 0  # reset non-vacuity counter for this run

        for class_doc in self._registry.get_all_classes():
            for method_doc in class_doc.methods + class_doc.properties:
                for example in method_doc.examples:
                    total += 1
                    result = self.validate_example_attributes(example)
                    result.method_name = method_doc.method_name
                    result.class_name = class_doc.class_name

                    if result.valid:
                        valid += 1
                    else:
                        failed.append(result)

        return ValidationReport(
            total_examples=total,
            valid_examples=valid,
            failed_validations=failed,
        )

    def assert_all_attributes_valid(self) -> None:
        """Assert all examples reference valid attributes.

        Raises AssertionError if any examples have invalid attribute accesses.
        """
        report = self.validate_all_attributes()
        if not report.all_valid:
            raise AssertionError(
                f"Static attribute validation failed:\n{report.summary()}"
            )
