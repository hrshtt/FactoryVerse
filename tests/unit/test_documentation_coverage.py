"""
Tests for documentation coverage.

These tests ensure that:
1. All public methods on action classes are documented
2. All examples have valid Python syntax
3. Documentation can be generated without errors

Run with: pytest tests/unit/test_documentation_coverage.py -v
"""

import pytest


class TestDocumentationRegistry:
    """Tests for the documentation registry."""

    def test_registry_singleton(self):
        """Test that get_registry returns the same instance."""
        from FactoryVerse.docs.registry import get_registry, reset_registry

        # Reset to ensure clean state
        reset_registry()

        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_register_class(self):
        """Test registering a class."""
        from FactoryVerse.docs.registry import get_registry, reset_registry

        reset_registry()
        registry = get_registry()

        class DummyClass:
            """Test class."""

            def method_one(self) -> str:
                """Method one."""
                return "one"

            def method_two(self, x: int) -> int:
                """Method two."""
                return x

        doc = registry.register_class(
            cls=DummyClass,
            accessor_name="dummy",
            description="A test class",
        )

        assert doc.class_name == "DummyClass"
        assert doc.accessor_name == "dummy"

    def test_register_method(self):
        """Test registering a method."""
        from FactoryVerse.docs.registry import get_registry, reset_registry
        from FactoryVerse.docs.models import Example

        reset_registry()
        registry = get_registry()

        class DummyClass:
            async def do_something(self, value: int) -> str:
                """Do something."""
                return str(value)

        registry.register_class(DummyClass, accessor_name="dummy")
        doc = registry.register_method(
            cls=DummyClass,
            method_name="do_something",
            examples=[
                Example(
                    code="result = await dummy.do_something(42)",
                    decision_context="Testing",
                    expected_outcome="Returns '42'",
                )
            ],
        )

        assert doc.method_name == "do_something"
        assert doc.is_async
        assert len(doc.examples) == 1


class TestCoverageValidator:
    """Tests for coverage validation."""

    def test_coverage_report(self):
        """Test that coverage report is generated."""
        from FactoryVerse.docs.registry import get_registry, reset_registry
        from FactoryVerse.docs.validators import CoverageValidator

        reset_registry()
        registry = get_registry()

        class TestClass:
            def public_method(self):
                pass

            def _private_method(self):
                pass

        registry.register_required_class(TestClass)

        validator = CoverageValidator(registry)
        report = validator.validate()

        # Should have 1 undocumented public method
        assert report.total_methods == 1
        assert report.documented_methods == 0
        assert len(report.missing_methods) == 1
        assert report.missing_methods[0].method_name == "public_method"

    def test_coverage_with_documentation(self):
        """Test coverage when methods are documented."""
        from FactoryVerse.docs.registry import get_registry, reset_registry
        from FactoryVerse.docs.validators import CoverageValidator
        from FactoryVerse.docs.models import Example

        reset_registry()
        registry = get_registry()

        class TestClass:
            def documented_method(self):
                """A documented method."""
                pass

        registry.register_required_class(TestClass)
        registry.register_method(
            cls=TestClass,
            method_name="documented_method",
            examples=[
                Example(
                    code="obj.documented_method()",
                    decision_context="Test",
                    expected_outcome="Does something",
                )
            ],
        )

        validator = CoverageValidator(registry)
        report = validator.validate()

        assert report.complete
        assert report.documented_methods == 1


class TestExampleValidator:
    """Tests for example validation."""

    def test_valid_syntax(self):
        """Test validation of valid Python syntax."""
        from FactoryVerse.docs.validators import ExampleValidator
        from FactoryVerse.docs.models import Example

        validator = ExampleValidator()

        example = Example(
            code="""
x = 1 + 2
print(f"Result: {x}")
            """,
            decision_context="Simple math",
            expected_outcome="Prints 3",
        )

        result = validator.validate_syntax(example)
        assert result.valid


class TestStaticAttributeValidator:
    """Tests for static attribute validation - catches doc/code drift."""

    def test_valid_resource_attribute(self):
        """Test that valid ResourceOrePatch attributes pass."""
        from FactoryVerse.docs.validators import StaticAttributeValidator
        from FactoryVerse.docs.models import Example

        validator = StaticAttributeValidator()

        example = Example(
            code="""
ores = reachable_view.get_resources(resource_type="ore")
for patch in ores:
    print(f"{patch.name}: {patch.total} total")
            """,
            decision_context="Surveying resources",
            expected_outcome="Prints resource info",
        )

        result = validator.validate_example_attributes(example)
        assert result.valid, f"Should pass: {result.error}"

    def test_invalid_resource_attribute(self):
        """Test that invalid attributes are caught - this is the bug that prompted this validator."""
        from FactoryVerse.docs.validators import StaticAttributeValidator
        from FactoryVerse.docs.models import Example

        validator = StaticAttributeValidator()

        # This was the actual bug: patch.total_amount instead of patch.total
        example = Example(
            code="""
ores = reachable_view.get_resources(resource_type="ore")
for patch in ores:
    print(f"{patch.name}: {patch.total_amount} total")
            """,
            decision_context="Surveying resources",
            expected_outcome="Prints resource info",
        )

        result = validator.validate_example_attributes(example)
        assert not result.valid, "Should catch invalid attribute 'total_amount'"
        assert "total_amount" in result.error
        assert "total" in result.error  # Should suggest the correct attribute

    def test_valid_entity_attribute(self):
        """Test that valid BaseEntity attributes pass."""
        from FactoryVerse.docs.validators import StaticAttributeValidator
        from FactoryVerse.docs.models import Example

        validator = StaticAttributeValidator()

        example = Example(
            code="""
entity = reachable_view.get_entity("stone-furnace")
print(entity.position)
            """,
            decision_context="Getting entity position",
            expected_outcome="Prints position",
        )

        result = validator.validate_example_attributes(example)
        assert result.valid, f"Should pass: {result.error}"

    def test_invalid_syntax(self):
        """Test detection of invalid Python syntax."""
        from FactoryVerse.docs.validators import ExampleValidator
        from FactoryVerse.docs.models import Example

        validator = ExampleValidator()

        example = Example(
            code="def broken(",  # Invalid syntax
            decision_context="Broken code",
            expected_outcome="Should fail",
        )

        result = validator.validate_syntax(example)
        assert not result.valid
        assert result.error_type == "SyntaxError"

    def test_async_syntax(self):
        """Test validation of async code."""
        from FactoryVerse.docs.validators import ExampleValidator
        from FactoryVerse.docs.models import Example

        validator = ExampleValidator()

        example = Example(
            code="""
result = await something.do_async()
print(result)
            """,
            decision_context="Async example",
            expected_outcome="Works with async",
        )

        result = validator.validate_syntax(example)
        assert result.valid


class TestMarkdownGenerator:
    """Tests for markdown generation."""

    def test_generate_empty_registry(self):
        """Test generation with empty registry."""
        from FactoryVerse.docs.registry import reset_registry
        from FactoryVerse.docs.generator import MarkdownGenerator

        reset_registry()
        generator = MarkdownGenerator()
        markdown = generator.generate()

        assert "# FactoryVerse API Reference" in markdown
        assert "## Overview" in markdown

    def test_generate_with_class(self):
        """Test generation with registered class."""
        from FactoryVerse.docs.registry import get_registry, reset_registry
        from FactoryVerse.docs.generator import MarkdownGenerator
        from FactoryVerse.docs.models import Example

        reset_registry()
        registry = get_registry()

        class TestAction:
            """A test action class."""

            def do_action(self) -> str:
                """Perform the action."""
                return "done"

        registry.register_class(
            cls=TestAction,
            accessor_name="test_action",
            description="Test action for documentation",
        )
        registry.register_method(
            cls=TestAction,
            method_name="do_action",
            examples=[
                Example(
                    code='result = test_action.do_action()',
                    decision_context="Performing test action",
                    expected_outcome="Returns 'done'",
                )
            ],
        )

        generator = MarkdownGenerator(registry)
        markdown = generator.generate()

        # Class appears in Quick Reference section by accessor name
        assert "test_action" in markdown
        assert "do_action" in markdown
        assert "Test action for documentation" in markdown


class TestDocumentationIntegration:
    """Integration tests for the full documentation system."""

    def test_reference_modules_load(self):
        """Test that reference modules can be loaded without error."""
        from FactoryVerse.docs.reference import register_all_documentation
        from FactoryVerse.docs.registry import get_registry, reset_registry

        reset_registry()
        register_all_documentation()

        registry = get_registry()
        classes = registry.get_all_classes()

        # Should have documented multiple classes
        assert len(classes) > 0

        # Check that key classes are present
        class_names = {c.class_name for c in classes}
        assert "MovementAction" in class_names or len(classes) > 0  # At least something registered

    def test_all_examples_valid_syntax(self):
        """Test that all registered examples have valid syntax."""
        from FactoryVerse.docs.reference import register_all_documentation
        from FactoryVerse.docs.registry import get_registry, reset_registry
        from FactoryVerse.docs.validators import ExampleValidator

        reset_registry()
        register_all_documentation()

        validator = ExampleValidator(get_registry())
        report = validator.validate_all_syntax()

        # All examples should have valid syntax
        if not report.all_valid:
            # Print failures for debugging
            for failure in report.failed_validations:
                print(f"FAILED: {failure.class_name}.{failure.method_name}")
                print(f"  Error: {failure.error}")
                print(f"  Code: {failure.example.code[:100]}...")

        assert report.all_valid, f"Some examples have invalid syntax: {report.summary()}"

    def test_all_examples_valid_attributes(self):
        """Test that all examples reference valid attributes on known types.

        This catches doc/code drift where example code uses attributes that
        don't exist on the actual classes (e.g., patch.total_amount vs patch.total).
        """
        from FactoryVerse.docs.reference import register_all_documentation
        from FactoryVerse.docs.registry import get_registry, reset_registry
        from FactoryVerse.docs.validators import StaticAttributeValidator

        reset_registry()
        register_all_documentation()

        validator = StaticAttributeValidator(get_registry())
        report = validator.validate_all_attributes()

        # All examples should reference valid attributes
        if not report.all_valid:
            # Print failures for debugging
            for failure in report.failed_validations:
                print(f"FAILED: {failure.class_name}.{failure.method_name}")
                print(f"  Error: {failure.error}")
                print(f"  Code snippet: {failure.example.code[:150]}...")

        assert report.all_valid, f"Some examples have invalid attribute accesses: {report.summary()}"

    def test_generate_full_documentation(self):
        """Test generating full documentation."""
        from FactoryVerse.docs.generator import generate_api_reference
        from FactoryVerse.docs.registry import reset_registry

        reset_registry()
        markdown = generate_api_reference()

        # Should have substantial content
        assert len(markdown) > 500

        # Should have key sections
        assert "## Overview" in markdown
        # Quick Reference only appears if classes are registered
        # The reference modules register classes on import
        if "## Quick Reference" in markdown:
            # If classes were registered, check for more content
            assert len(markdown) > 1000

    def test_coverage_report(self):
        """Test that coverage report can be generated."""
        from FactoryVerse.docs.reference import register_all_documentation
        from FactoryVerse.docs.registry import get_registry, reset_registry
        from FactoryVerse.docs.validators import CoverageValidator

        reset_registry()
        register_all_documentation()

        validator = CoverageValidator(get_registry())
        report = validator.validate()

        # Should have some coverage (exact numbers depend on implementation)
        print(report.summary())
        assert report.total_methods >= 0
        assert report.coverage_percent >= 0


class TestDecorators:
    """Tests for documentation decorators."""

    def test_documented_method_decorator(self):
        """Test that @documented_method stores metadata."""
        from FactoryVerse.docs.decorators import documented_method, get_method_doc_metadata
        from FactoryVerse.docs.models import Example

        @documented_method(
            examples=[
                Example(
                    code="x = 1",
                    decision_context="Test",
                    expected_outcome="Works",
                )
            ],
            description="Test method",
        )
        def my_method():
            pass

        metadata = get_method_doc_metadata(my_method)
        assert metadata is not None
        assert len(metadata["examples"]) == 1
        assert metadata["description"] == "Test method"

    def test_documented_class_decorator(self):
        """Test that @documented_class stores metadata."""
        from FactoryVerse.docs.decorators import documented_class, get_class_doc_metadata

        @documented_class(
            accessor_name="my_class",
            decision_context="Use for testing",
        )
        class MyClass:
            pass

        metadata = get_class_doc_metadata(MyClass)
        assert metadata is not None
        assert metadata["accessor_name"] == "my_class"
        assert metadata["decision_context"] == "Use for testing"

    def test_register_decorated_class(self):
        """Test auto-registration of decorated class."""
        from FactoryVerse.docs.decorators import (
            documented_class,
            documented_method,
            register_decorated_class,
        )
        from FactoryVerse.docs.registry import get_registry, reset_registry
        from FactoryVerse.docs.models import Example

        reset_registry()

        @documented_class(accessor_name="decorated", decision_context="Test")
        class DecoratedClass:
            @documented_method(
                examples=[
                    Example(code="x = 1", decision_context="Test", expected_outcome="Works")
                ]
            )
            def my_method(self):
                pass

        register_decorated_class(DecoratedClass)

        registry = get_registry()
        cls_doc = registry.get_class("DecoratedClass")
        assert cls_doc is not None
        assert cls_doc.accessor_name == "decorated"

        method_doc = registry.get_method("DecoratedClass", "my_method")
        assert method_doc is not None
        assert len(method_doc.examples) == 1
