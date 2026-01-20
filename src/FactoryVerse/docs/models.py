"""
Documentation data models.

These dataclasses represent documentation structure and are used by:
- Decorators to attach documentation to methods/classes
- Registry to collect and organize documentation
- Generator to produce markdown output
- Validators to check coverage and example correctness
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Type, Callable
from enum import Enum


class ValidationLevel(Enum):
    """How thoroughly to validate examples."""

    SYNTAX = "syntax"  # Check Python syntax only
    IMPORT = "import"  # Check imports resolve
    EXECUTION = "execution"  # Run in test environment


@dataclass
class Example:
    """An executable example with decision context.

    Examples are designed to help agents make decisions, not to prescribe
    specific approaches. Each example should clarify WHEN to use a method,
    not just HOW.
    """

    code: str
    """The Python code to execute."""

    decision_context: str
    """What decision this example helps with (e.g., 'Choosing between position-based and entity-based walking')."""

    preconditions: List[str] = field(default_factory=list)
    """Required state before execution (e.g., 'has iron-plate in inventory')."""

    expected_outcome: str = ""
    """What happens when executed successfully."""

    alternatives: List[str] = field(default_factory=list)
    """Other valid approaches for the same decision."""

    setup_code: str = ""
    """Code to run before the example (not shown in docs)."""

    teardown_code: str = ""
    """Code to run after the example (not shown in docs)."""

    validation_level: ValidationLevel = ValidationLevel.SYNTAX
    """How to validate this example."""


@dataclass
class ErrorCase:
    """Documents an error condition for a method."""

    exception: str
    """The exception class name."""

    when: str
    """When this error occurs."""

    resolution: str
    """How to handle or prevent this error."""

    example_trigger: Optional[str] = None
    """Optional code that would trigger this error."""


@dataclass
class MethodDocumentation:
    """Documentation for a single method.

    This is the core unit of documentation. Each public method should have
    one MethodDocumentation instance with examples and error cases.
    """

    method_name: str
    """Name of the method (e.g., 'walk_to')."""

    signature: str
    """Full method signature with parameters and types."""

    return_type: str
    """Return type annotation as string."""

    description: str
    """Method description, typically from docstring."""

    examples: List[Example] = field(default_factory=list)
    """Decision-driven examples showing when/how to use the method."""

    error_cases: List[ErrorCase] = field(default_factory=list)
    """Documented error conditions."""

    decision_points: List[str] = field(default_factory=list)
    """When to use this method vs alternatives."""

    notes: List[str] = field(default_factory=list)
    """Additional notes or caveats."""

    is_async: bool = False
    """Whether this is an async method."""

    is_property: bool = False
    """Whether this is a property."""

    def __post_init__(self):
        # Auto-detect async from signature
        if "async " in self.signature and not self.is_async:
            self.is_async = True


@dataclass
class ClassDocumentation:
    """Documentation for a class (typically an action class).

    Groups related methods and provides class-level context about
    when to use this class vs alternatives.
    """

    class_name: str
    """Name of the class (e.g., 'MovementAction')."""

    accessor_name: str
    """How agents access this class (e.g., 'walking')."""

    description: str
    """Class description and purpose."""

    methods: List[MethodDocumentation] = field(default_factory=list)
    """Documented methods on this class."""

    decision_context: str = ""
    """When to use this class vs alternatives."""

    properties: List[MethodDocumentation] = field(default_factory=list)
    """Documented properties on this class."""

    class_attributes: Dict[str, str] = field(default_factory=dict)
    """Important class-level attributes."""

    related_classes: List[str] = field(default_factory=list)
    """Other classes that work together with this one."""

    notes: List[str] = field(default_factory=list)
    """Additional notes or caveats."""


@dataclass
class TypeDocumentation:
    """Documentation for a type (dataclass, enum, etc.)."""

    type_name: str
    """Name of the type."""

    description: str
    """Type description."""

    fields: Dict[str, str] = field(default_factory=dict)
    """Field name to description mapping."""

    examples: List[Example] = field(default_factory=list)
    """Usage examples."""

    is_enum: bool = False
    """Whether this is an enum."""

    enum_values: Dict[str, str] = field(default_factory=dict)
    """For enums: value name to description."""


@dataclass
class UndocumentedMethod:
    """Represents a method that should be documented but isn't."""

    class_name: str
    method_name: str
    signature: str
    is_public: bool = True


@dataclass
class CoverageReport:
    """Report on documentation coverage."""

    total_methods: int
    """Total number of public methods found."""

    documented_methods: int
    """Number of methods with documentation."""

    missing_methods: List[UndocumentedMethod] = field(default_factory=list)
    """Methods without documentation."""

    methods_without_examples: List[str] = field(default_factory=list)
    """Documented methods that lack examples."""

    @property
    def coverage_percent(self) -> float:
        """Documentation coverage as percentage."""
        if self.total_methods == 0:
            return 100.0
        return (self.documented_methods / self.total_methods) * 100

    @property
    def complete(self) -> bool:
        """Whether documentation is complete."""
        return len(self.missing_methods) == 0

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [
            f"Documentation Coverage: {self.coverage_percent:.1f}%",
            f"  Documented: {self.documented_methods}/{self.total_methods} methods",
        ]
        if self.missing_methods:
            lines.append(f"  Missing: {len(self.missing_methods)} methods")
            for m in self.missing_methods:
                lines.append(f"    - {m.class_name}.{m.method_name}")
        if self.methods_without_examples:
            lines.append(f"  Without examples: {len(self.methods_without_examples)} methods")
            for method_key in self.methods_without_examples:
                lines.append(f"    - {method_key}")
        return "\n".join(lines)


@dataclass
class ExampleValidationResult:
    """Result of validating an example."""

    example: Example
    method_name: str
    class_name: str
    valid: bool
    error: Optional[str] = None
    error_type: Optional[str] = None


@dataclass
class ValidationReport:
    """Report on example validation."""

    total_examples: int
    valid_examples: int
    failed_validations: List[ExampleValidationResult] = field(default_factory=list)

    @property
    def all_valid(self) -> bool:
        return len(self.failed_validations) == 0

    def summary(self) -> str:
        lines = [
            f"Example Validation: {self.valid_examples}/{self.total_examples} passed",
        ]
        if self.failed_validations:
            lines.append("Failed examples:")
            for result in self.failed_validations:
                lines.append(f"  - {result.class_name}.{result.method_name}")
                lines.append(f"    Error: {result.error_type}: {result.error}")
        return "\n".join(lines)
