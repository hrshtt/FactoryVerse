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

from FactoryVerse.docs.models import (
    Example,
    CoverageReport,
    ValidationReport,
    ExampleValidationResult,
    ValidationLevel,
)
from FactoryVerse.docs.registry import DocumentationRegistry, get_registry


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
            from FactoryVerse.docs.reference.inspection import get_inspection_examples
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
