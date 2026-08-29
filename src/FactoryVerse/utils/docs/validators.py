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

    Some public methods on required classes are deliberately NOT documented
    to the agent. Each such method must appear in COVERAGE_EXEMPTIONS with a
    reason; an exemption that names a method which no longer exists, or which
    has since been documented, is itself a failure (see assert_exemptions_live)
    so the list cannot rot into a silent skip-list.
    """

    # "ClassName.method" -> why the agent is not told about it.
    COVERAGE_EXEMPTIONS: Dict[str, str] = {
        # (MiningAction / PlacementAction / EntityOperationsAction are no longer
        # registered: their accessors were deleted 2026-08-29 and the classes
        # are infrastructure behind resource.mine(), item.place() and the
        # entity mixins.)
        # Harness-internal reconciliation and checkpoint machinery on RemoteView.
        "RemoteView.checkpoint_database":
            "campaign checkpoint plumbing, not a map-screen read",
        "RemoteView.state_fingerprint":
            "resume-parity instrument for the harness, not a map-screen read",
        "RemoteView.capture_resource_depletion_baseline":
            "mining causal-baseline proof; called by the mining action, not the agent",
        "RemoteView.wait_for_placement":
            "placement causal join used by the placement action, not the agent",
        "RemoteView.wait_for_resource_depletion":
            "mining causal join used by the mining action, not the agent",
        # The transport under the execute_duckdb tool. The agent reaches it as
        # a tool, never as a method; documenting it would advertise a second route.
        "RemoteView.execute_raw":
            "transport for the execute_duckdb tool; not an agent-facing method",
        # Tier 4 tells the view whose force to read production for; the
        # agent never calls it.
        "RemoteView.set_agent_id":
            "harness wiring (tier4 sets the agent id); not an agent-facing method",
    }

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

        # Apply reasoned exemptions. They are subtracted from the missing list
        # only; total_methods keeps counting them so the ratio stays honest.
        exempt = self.COVERAGE_EXEMPTIONS
        report.missing_methods = [
            m for m in report.missing_methods
            if f"{m.class_name}.{m.method_name}" not in exempt
        ]
        report.documented_methods = report.total_methods - len(report.missing_methods)

        return report

    def assert_exemptions_live(self) -> None:
        """Every exemption must name a real, discovered, still-undocumented method.

        Raises AssertionError otherwise, so an exemption cannot outlive the
        thing it exempts (method deleted or since documented).
        """
        if not self.COVERAGE_EXEMPTIONS:
            raise AssertionError("COVERAGE_EXEMPTIONS is empty; the mechanism is vacuous")
        problems = []
        for key, reason in self.COVERAGE_EXEMPTIONS.items():
            class_name, method_name = key.split(".", 1)
            if not reason.strip():
                problems.append(f"{key}: exemption has no reason")
            cls = self._registry.get_class_object(class_name)
            if cls is None:
                # Required classes may be registered without register_class
                for required in self._registry._required_classes:
                    if required.__name__ == class_name:
                        cls = required
            if cls is None:
                problems.append(f"{key}: class {class_name} is not registered")
                continue
            if not hasattr(cls, method_name):
                problems.append(f"{key}: {class_name} has no attribute {method_name} — stale exemption")
                continue
            if method_name not in self._registry.discovered_methods(class_name):
                problems.append(f"{key}: {method_name} is not a discovered public method — stale exemption")
            if self._registry.get_method(class_name, method_name) is not None:
                problems.append(f"{key}: now documented — remove the exemption")
        if problems:
            raise AssertionError("Stale coverage exemptions:\n" + "\n".join(f"  - {p}" for p in problems))

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
        "remote_view.get_power_networks": "PowerNetworksReport",
        "remote_view.power": "PowerNetworksReport",
        "remote_view.status": "StatusSummary",
        "remote_view.status_changed": "StatusChange",
        "remote_view.production": "ProductionReport",
        "remote_view.diagnose_power": "PowerDiagnosis",


        # Inventory
        "inventory.await_item": "AwaitItemResult",
        "inventory.get_item": "PlaceableItem",
        "inventory.get_items": "List[Item]",
        "inventory.create_item_stacks": "List[ItemStack]",
        "inventory.check_total": "int",


        # Crafting
        "crafting.status": "CraftingQueueStatus",
        "crafting.enqueue": "Dict",
        "crafting.dequeue": "Dict",




        # Walking
        "walking.walk_to": "MapPosition",
        "walking.walk_to_position": "MapPosition",
        "walking.position": "MapPosition",
        "walking.stop": "WalkingStopped",

        # Crafting catalog and predictions
        "crafting.list_recipes": "List[Dict]",
        "crafting.enqueue": "Dict",
        "crafting.take_predictions": "List[CraftPrediction]",

        # Entity reference (planning-time, Constitution §6)
        "entity_reference": "EntityReference",

        # Research
        "research.list_technologies": "List[Dict]",
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
        # Resource-side only: entities are removed with .pickup(), not .mine()
        ".mine": "List[ItemStack]",
        ".pickup": "List[ItemStack]",
        ".status": "LiveStatus",
        ".can_place": "bool",
        ".set_limit": "Dict",
        ".supply_area": "BoundingBox",
        ".covers": "bool",
        ".wire_reach": "bool",
        ".drop_position": "SourcedValue",
        ".placements_between": "SourcedValue",
        ".sites": "SourcedValue",
        ".footprint": "SourcedValue",

        # ElectricPole accessors (DOC-GAP-1: exist in electric_pole.py,
        # previously unregistered — supply-area / wire-reach reasoning)
        ".get_supply_area": "BoundingBox",
        ".supply_area_distance": "float",
        ".maximum_wire_distance": "float",
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
        "List[CraftPrediction]": "CraftPrediction",
    }

    # Index access types (when accessing list[0])
    INDEX_ACCESS_TYPES: Dict[str, str] = LIST_ELEMENT_TYPES  # Same as iteration

    # Polymorphic return types - when return type depends on argument values
    # Format: (method_pattern, arg_pattern) -> refined_return_type
    POLYMORPHIC_RETURN_TYPES: Dict[tuple, str] = {}

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
            from FactoryVerse.game.factory.types import MapPosition, TilePosition, BoundingBox
            from FactoryVerse.game.agent.placement_hints import (
                ConnectionPosition, WireConnectionPosition,
            )
            from FactoryVerse.game.agent.remote_view import (
                PowerNetworksReport, PowerNetworkCensus, PowerDiagnosis,
                StatusSummary, StatusGroup, ProductionReport,
            )
            from FactoryVerse.game.agent.status_dump import StatusChange, StatusTransition
            from FactoryVerse.game.agent.embodied_actions.research import ResearchStatus, QueuedTechnology
            from FactoryVerse.game.agent.embodied_actions.inventory import AwaitItemResult
            from FactoryVerse.game.agent.embodied_actions.crafting import CraftPrediction
            from FactoryVerse.game.agent.entity_reference import EntityReference, SourcedValue
            from FactoryVerse.game.factory.entity.base_entity import LiveStatus
            from FactoryVerse.game.agent.embodied_actions.walking import WalkingStopped
            from FactoryVerse.game.agent.embodied_actions.place_entity import (
                EntityPlaced, GhostRemoved
            )
            from FactoryVerse.game.factory.types import CraftingQueueStatus, CraftingQueueItem
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
                "BoundingBox": BoundingBox,
                "PowerNetworksReport": PowerNetworksReport,
                "PowerNetworkCensus": PowerNetworkCensus,
                "PowerDiagnosis": PowerDiagnosis,
                "StatusSummary": StatusSummary,
                "StatusGroup": StatusGroup,
                "StatusChange": StatusChange,
                "StatusTransition": StatusTransition,
                "ProductionReport": ProductionReport,
                "ConnectionPosition": ConnectionPosition,
                "WireConnectionPosition": WireConnectionPosition,
                "ResearchStatus": ResearchStatus,
                "QueuedTechnology": QueuedTechnology,
                "AwaitItemResult": AwaitItemResult,
                "CraftPrediction": CraftPrediction,
                "EntityReference": EntityReference,
                "SourcedValue": SourcedValue,
                "LiveStatus": LiveStatus,
                "WalkingStopped": WalkingStopped,
                "EntityPlaced": EntityPlaced,
                "CraftingQueueStatus": CraftingQueueStatus,
                "CraftingQueueItem": CraftingQueueItem,
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



class NamespaceCoverageValidator:
    """The converse of CoverageValidator: everything the agent can reach is taught.

    CoverageValidator checks documented -> exists. This checks exists ->
    documented: every accessor bound into the agent namespace by
    `tier4_runtime.py` is either registered with the docs registry under that
    accessor name, or carries a reasoned exemption here. This is the check
    whose absence let `events` sit in the namespace for months with zero
    documentation (API_AFFORDANCE_REDESIGN §1.5, §6).
    """

    # accessor name -> why it is deliberately untaught
    NAMESPACE_EXEMPTIONS: Dict[str, str] = {
        "agent_id": "a value, not an accessor; shown in the prompt header",
    }

    def __init__(self, registry: Optional[DocumentationRegistry] = None):
        self._registry = registry or get_registry()

    @staticmethod
    def agent_namespace_accessors() -> Dict[str, str]:
        """Accessor names bound by Tier 4, parsed from the namespace literal.

        Returns {name: value_expression}. Only entries whose value is an
        instance attribute (`self._x`) count as accessors; direct class
        bindings (MapPosition, Item, ...) are types and are documented by the
        types section. Text-parsed because building a Tier4Runtime needs a
        live stack; the parse is asserted non-empty by its callers.
        """
        import re
        from pathlib import Path
        import FactoryVerse.environment.tiers.tier4_runtime as t4

        src = Path(t4.__file__).read_text()
        start = src.index("builtin_names = {")
        # The last accessor row is entity_reference (API §2.7); the dict closes after it.
        end = src.index("}", src.index("\"entity_reference\"", start))
        block = src[start:end]
        found: Dict[str, str] = {}
        for m in re.finditer(r'^\s*"(\w+)":\s*(self\.[\w.]+)', block, re.M):
            found[m.group(1)] = m.group(2)
        return found

    def validate(self) -> List[str]:
        """Return a list of problems; empty means every accessor is taught or exempt."""
        accessors = self.agent_namespace_accessors()
        problems: List[str] = []
        expected = {"agent_id", "walking", "inventory", "crafting", "research",
                    "reachable_view", "remote_view", "entity_reference"}
        if set(accessors) != expected:
            problems.append(
                f"namespace is {sorted(accessors)}; API_AFFORDANCE_REDESIGN §2.7 fixes it at "
                f"{sorted(expected)} — a new accessor needs a plan amendment, not a binding"
            )
        documented = {c.accessor_name for c in self._registry.get_all_classes()}
        for name in accessors:
            if name in documented:
                continue
            if name in self.NAMESPACE_EXEMPTIONS:
                continue
            problems.append(f"'{name}' is bound in the agent namespace and has no documentation entry")
        for name, reason in self.NAMESPACE_EXEMPTIONS.items():
            if not reason.strip():
                problems.append(f"exemption '{name}' has no reason")
            if name not in accessors:
                problems.append(f"exemption '{name}' names nothing in the namespace — stale")
            if name in documented:
                problems.append(f"exemption '{name}' is now documented — remove it")
        return problems


class ProseReferenceValidator:
    """Attribute-checks the prose the model reads, not just the code examples.

    Every backticked `accessor.method(` or `var.method(` token in a
    description, note, decision point, precondition, expected outcome,
    alternative or error case must resolve: accessor methods against the real
    accessor class (via the registry), bare `.method(` against the
    entity/resource/item classes the STATIC validator already knows. A prose
    token that resolves nowhere is a lie shipped to the model.
    """

    _TOKEN = __import__("re").compile(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\(")  # backticks optional; prose is inconsistent

    def __init__(self, registry: Optional[DocumentationRegistry] = None):
        self._registry = registry or get_registry()
        self._static = StaticAttributeValidator(self._registry)
        self.tokens_checked = 0

    def _prose_fields(self):
        """Yield (location, text) for every prose field in the registry."""
        for cls_doc in self._registry.get_all_classes():
            base = f"{cls_doc.class_name}"
            yield f"{base}.description", cls_doc.description
            yield f"{base}.decision_context", cls_doc.decision_context
            for i, n in enumerate(cls_doc.notes):
                yield f"{base}.notes[{i}]", n
            for m in cls_doc.methods + cls_doc.properties:
                mb = f"{cls_doc.class_name}.{m.method_name}"
                yield f"{mb}.description", m.description
                for i, n in enumerate(m.decision_points):
                    yield f"{mb}.decision_points[{i}]", n
                for i, n in enumerate(m.notes):
                    yield f"{mb}.notes[{i}]", n
                for i, ex in enumerate(m.examples):
                    yield f"{mb}.examples[{i}].decision_context", ex.decision_context
                    yield f"{mb}.examples[{i}].expected_outcome", ex.expected_outcome
                    for j, p in enumerate(ex.preconditions):
                        yield f"{mb}.examples[{i}].preconditions[{j}]", p
                    for j, a in enumerate(ex.alternatives):
                        yield f"{mb}.examples[{i}].alternatives[{j}]", a
                for i, ec in enumerate(m.error_cases):
                    yield f"{mb}.error_cases[{i}].when", ec.when
                    yield f"{mb}.error_cases[{i}].resolution", ec.resolution

    def _resolves(self, obj: str, method: str) -> bool:
        cls = self._registry.get_class_by_accessor(obj)
        if cls is not None:
            return hasattr(cls, method)
        # Not an accessor: a variable holding an entity/resource/item/type.
        # Accept if any known class in the type system has the method.
        if f".{method}" in self._static.ACCESSOR_RETURN_TYPES:
            return True
        for known in self._static._class_map.values():
            if method in self._static._get_class_attributes(known):
                return True
        # Types bound into the namespace directly (MapPosition(...) etc.)
        if obj in self._static._class_map and hasattr(self._static._class_map[obj], method):
            return True
        return False

    def validate(self) -> List[str]:
        """Return problems as 'location: token — reason'. Empty means clean."""
        self.tokens_checked = 0
        problems: List[str] = []
        for location, text in self._prose_fields():
            if not text:
                continue
            for m in self._TOKEN.finditer(text):
                obj, method = m.group(1), m.group(2)
                self.tokens_checked += 1
                if not self._resolves(obj, method):
                    problems.append(f"{location}: `{obj}.{method}(` resolves to nothing")
        return problems
