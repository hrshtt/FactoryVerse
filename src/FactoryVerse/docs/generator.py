"""
Markdown Generator.

Generates API reference documentation from the documentation registry.
Produces well-formatted markdown suitable for LLM consumption.

Usage:
    python -m FactoryVerse.docs.generator

Or programmatically:
    from FactoryVerse.docs.generator import generate_api_reference
    markdown = generate_api_reference()
"""

from typing import Optional, List
from pathlib import Path
import textwrap
from datetime import datetime

from FactoryVerse.docs.registry import get_registry, DocumentationRegistry
from FactoryVerse.docs.models import (
    ClassDocumentation,
    MethodDocumentation,
    TypeDocumentation,
    Example,
)


class MarkdownGenerator:
    """Generates markdown documentation from the registry."""

    def __init__(self, registry: Optional[DocumentationRegistry] = None):
        self._registry = registry or get_registry()
        self._indent = "    "

    def generate(self) -> str:
        """Generate complete API reference markdown."""
        sections = [
            self._generate_header(),
            self._generate_overview(),
            self._generate_preimported_types_section(),
            self._generate_accessors_section(),
            self._generate_action_classes_section(),
            self._generate_view_classes_section(),
            self._generate_placement_classes_section(),
            self._generate_inspection_section(),
            self._generate_types_section(),
            self._generate_footer(),
        ]
        return "\n\n".join(filter(None, sections))

    def _generate_header(self) -> str:
        """Generate document header."""
        return textwrap.dedent("""
        # FactoryVerse API Reference

        This document provides the complete API reference for FactoryVerse agents.
        All methods, types, and examples are validated against the actual implementation.

        ---
        """).strip()

    def _generate_overview(self) -> str:
        """Generate overview section."""
        return textwrap.dedent("""
        ## Overview

        FactoryVerse provides a dual-view system for interacting with the game:

        | View | Accessor | Description |
        |------|----------|-------------|
        | **REACHABLE** | `reachable_view` | Nearby entities with full mutation access |
        | **REMOTE** | `remote_view` | Map-wide SQL queries (read-only, walk_to only) |

        ### Top-Level Accessors

        These are available in the agent runtime:

        | Accessor | Class | Purpose |
        |----------|-------|---------|
        | `walking` | MovementAction | Walk to positions/entities |
        | `crafting` | CraftingAction | Hand-craft recipes |
        | `research` | ResearchAction | Queue and track research |
        | `inventory` | AgentInventory | Query and shape inventory |
        | `reachable_view` | ReachableView | Query nearby entities |
        | `remote_view` | RemoteView | Map-wide SQL queries |
        | `ghost_builder` | GhostBuilderAction | Commit placement plans |
        | `placement_hints` | PlacementHints | Spatial reasoning for placement |
        """).strip()

    def _generate_preimported_types_section(self) -> str:
        """Generate section for pre-imported types (programmatic)."""
        try:
            from FactoryVerse.docs.reference.inspection import generate_preimported_types_markdown
            return generate_preimported_types_markdown()
        except Exception as e:
            return f"<!-- Failed to generate pre-imported types: {e} -->"

    def _generate_inspection_section(self) -> str:
        """Generate EntityInspection schema section (programmatic)."""
        try:
            from FactoryVerse.docs.reference.inspection import generate_inspection_markdown
            return generate_inspection_markdown()
        except Exception as e:
            return f"<!-- Failed to generate inspection schema: {e} -->"

    def _generate_accessors_section(self) -> str:
        """Generate quick reference for accessors."""
        classes = self._registry.get_all_classes()
        if not classes:
            return ""

        lines = ["## Quick Reference", ""]

        for cls_doc in classes:
            lines.append(f"### `{cls_doc.accessor_name}`")
            lines.append("")
            if cls_doc.description:
                lines.append(cls_doc.description)
                lines.append("")

            # List methods
            methods = cls_doc.methods + cls_doc.properties
            if methods:
                lines.append("**Methods:**")
                for method in methods:
                    sig = method.signature.split("->")[0].strip()
                    lines.append(f"- `{sig}`")
                lines.append("")

        return "\n".join(lines)

    def _generate_action_classes_section(self) -> str:
        """Generate detailed documentation for action classes."""
        classes = self._registry.get_all_classes()
        action_classes = [
            c for c in classes
            if c.accessor_name in ("walking", "crafting", "research", "inventory")
        ]

        if not action_classes:
            return ""

        lines = ["## Action Classes", ""]

        for cls_doc in action_classes:
            lines.extend(self._generate_class_section(cls_doc))
            lines.append("")

        return "\n".join(lines)

    def _generate_view_classes_section(self) -> str:
        """Generate detailed documentation for view classes."""
        classes = self._registry.get_all_classes()
        view_classes = [
            c for c in classes
            if c.accessor_name in ("reachable_view", "remote_view")
        ]

        if not view_classes:
            return ""

        lines = ["## View Classes", ""]

        for cls_doc in view_classes:
            lines.extend(self._generate_class_section(cls_doc))
            lines.append("")

        return "\n".join(lines)

    def _generate_placement_classes_section(self) -> str:
        """Generate detailed documentation for placement/spatial reasoning classes."""
        classes = self._registry.get_all_classes()
        placement_classes = [
            c for c in classes
            if c.accessor_name in ("placement_hints", "ghost_builder")
        ]

        if not placement_classes:
            return ""

        lines = ["## Placement & Spatial Reasoning", ""]

        # Add detailed documentation for each class (from registry)
        for cls_doc in placement_classes:
            lines.extend(self._generate_class_section(cls_doc))
            lines.append("")

        return "\n".join(lines)

    def _generate_class_section(self, cls_doc: ClassDocumentation) -> List[str]:
        """Generate section for a single class."""
        lines = []

        # Class header
        lines.append(f"### {cls_doc.class_name}")
        lines.append("")
        lines.append(f"**Accessor:** `{cls_doc.accessor_name}`")
        lines.append("")

        if cls_doc.description:
            lines.append(cls_doc.description)
            lines.append("")

        if cls_doc.decision_context:
            lines.append(f"**When to use:** {cls_doc.decision_context}")
            lines.append("")

        if cls_doc.notes:
            lines.append("**Notes:**")
            for note in cls_doc.notes:
                lines.append(f"- {note}")
            lines.append("")

        # Methods
        methods = cls_doc.methods + cls_doc.properties
        for method in methods:
            lines.extend(self._generate_method_section(method, cls_doc.accessor_name))
            lines.append("")

        return lines

    def _generate_method_section(
        self, method: MethodDocumentation, accessor_name: str
    ) -> List[str]:
        """Generate section for a single method."""
        lines = []

        # Method header
        lines.append(f"#### `{accessor_name}.{method.method_name}`")
        lines.append("")

        # Signature
        lines.append(f"```python")
        lines.append(f"{method.signature}")
        lines.append("```")
        lines.append("")

        # Description
        if method.description:
            lines.append(method.description)
            lines.append("")

        # Decision points
        if method.decision_points:
            lines.append("**Decision Points:**")
            for point in method.decision_points:
                lines.append(f"- {point}")
            lines.append("")

        # Examples
        if method.examples:
            lines.append("**Examples:**")
            lines.append("")
            for example in method.examples:
                lines.extend(self._generate_example(example))
            lines.append("")

        # Error cases
        if method.error_cases:
            lines.append("**Error Handling:**")
            lines.append("")
            for error in method.error_cases:
                lines.append(f"- **`{error.exception}`**: {error.when}")
                if error.resolution:
                    lines.append(f"  - Resolution: {error.resolution}")
            lines.append("")

        return lines

    def _generate_example(self, example: Example) -> List[str]:
        """Generate formatted example."""
        lines = []

        # Context
        if example.decision_context:
            lines.append(f"*{example.decision_context}:*")
            lines.append("")

        # Preconditions
        if example.preconditions:
            lines.append(f"Preconditions: {', '.join(example.preconditions)}")
            lines.append("")

        # Code
        lines.append("```python")
        lines.append(example.code.strip())
        lines.append("```")

        # Outcome
        if example.expected_outcome:
            lines.append("")
            lines.append(f"→ {example.expected_outcome}")

        # Alternatives
        if example.alternatives:
            lines.append("")
            lines.append(f"Alternatives: {', '.join(example.alternatives)}")

        lines.append("")
        return lines

    def _generate_types_section(self) -> str:
        """Generate documentation for types."""
        types = self._registry.get_all_types()
        if not types:
            return ""

        lines = ["## Core Types", ""]

        for type_doc in types:
            lines.extend(self._generate_type_section(type_doc))
            lines.append("")

        return "\n".join(lines)

    def _generate_type_section(self, type_doc: TypeDocumentation) -> List[str]:
        """Generate section for a single type."""
        lines = []

        lines.append(f"### {type_doc.type_name}")
        lines.append("")

        if type_doc.description:
            lines.append(type_doc.description)
            lines.append("")

        # Enum values
        if type_doc.is_enum and type_doc.enum_values:
            lines.append("**Values:**")
            for name, value in type_doc.enum_values.items():
                lines.append(f"- `{name}` = {value}")
            lines.append("")

        # Fields (for dataclasses)
        if type_doc.fields and not type_doc.is_enum:
            lines.append("**Fields:**")
            for name, desc in type_doc.fields.items():
                lines.append(f"- `{name}`: {desc}")
            lines.append("")

        # Examples
        if type_doc.examples:
            lines.append("**Examples:**")
            lines.append("")
            for example in type_doc.examples:
                lines.extend(self._generate_example(example))

        return lines

    def _generate_footer(self) -> str:
        """Generate document footer."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return textwrap.dedent(f"""
        ---

        *Generated from registry on {timestamp}*
        """).strip()


def generate_api_reference(registry: Optional[DocumentationRegistry] = None) -> str:
    """Generate API reference markdown from registry.

    Args:
        registry: Optional registry to use. If None, uses global registry.

    Returns:
        Complete API reference as markdown string.
    """
    # Ensure documentation is registered
    from FactoryVerse.docs.reference import register_all_documentation
    register_all_documentation()

    generator = MarkdownGenerator(registry)
    return generator.generate()


def write_api_reference(
    output_path: Optional[Path] = None,
    registry: Optional[DocumentationRegistry] = None,
) -> Path:
    """Generate and write API reference to file.

    Args:
        output_path: Path to write to. Defaults to docs/for-llms/api_reference.md
        registry: Optional registry to use.

    Returns:
        Path to written file.
    """
    if output_path is None:
        # Default path relative to project root
        import FactoryVerse
        project_root = Path(FactoryVerse.__file__).parent.parent.parent
        output_path = project_root / "docs" / "for-llms" / "api_reference.md"

    markdown = generate_api_reference(registry)

    # Ensure directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_text(markdown)
    return output_path


def main():
    """CLI entry point for documentation generation."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate FactoryVerse API reference documentation"
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        help="Output path (default: docs/for-llms/api_reference.md)",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate coverage before generating",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        dest="print_output",
        help="Print to stdout instead of writing file",
    )

    args = parser.parse_args()

    # Register documentation
    from FactoryVerse.docs.reference import register_all_documentation
    register_all_documentation()

    # Validate if requested
    if args.validate:
        from FactoryVerse.docs.validators import CoverageValidator
        validator = CoverageValidator()
        report = validator.validate()
        print(report.summary())
        print()

    # Generate
    if args.print_output:
        markdown = generate_api_reference()
        print(markdown)
    else:
        output_path = write_api_reference(args.output)
        print(f"Generated: {output_path}")


if __name__ == "__main__":
    main()
