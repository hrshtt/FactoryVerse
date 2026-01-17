"""API reference documentation generation for FactoryVerse.

This module generates comprehensive API documentation by introspecting
the FactoryVerse Python codebase. The generated documentation covers:

- Top-level accessors (walking, inventory, reachable_view, etc.)
- Entity types and capabilities (mixins)
- Response types (dataclasses)
- Exception types
- Core data types (MapPosition, Direction, etc.)

The generated documentation is suitable for inclusion in LLM system prompts
to enable agents to understand and use the FactoryVerse DSL.

Note: This module delegates to the existing generate_docs.py script logic.
Future work will migrate the full introspection logic into this module.
"""

from pathlib import Path
from typing import Optional
import sys


def get_project_root() -> Path:
    """Find the FactoryVerse project root."""
    current = Path(__file__).resolve()
    for _ in range(5):
        current = current.parent

    if (current / "pyproject.toml").exists():
        return current

    for candidate in [Path.cwd(), Path.cwd().parent]:
        if (candidate / "pyproject.toml").exists():
            return candidate

    raise RuntimeError("Could not find FactoryVerse project root")


def generate_api_reference() -> str:
    """Generate API reference documentation via introspection.

    Introspects the FactoryVerse Python codebase to generate comprehensive
    documentation of all public APIs available to agents.

    Returns:
        Complete API reference as markdown string
    """
    # Import the generate_document function from the existing script
    root = get_project_root()
    scripts_dir = root / "scripts"

    # Temporarily add scripts to path
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    try:
        # Import the generation logic from the existing script
        from generate_docs import generate_document

        return generate_document()
    finally:
        # Clean up path
        if str(scripts_dir) in sys.path:
            sys.path.remove(str(scripts_dir))


def write_api_reference(output_path: Optional[Path] = None) -> Path:
    """Generate and write API reference to file.

    Args:
        output_path: Where to write (default: docs/for-llms/api_reference.md)

    Returns:
        Path to the written file
    """
    if output_path is None:
        root = get_project_root()
        output_path = root / "docs" / "for-llms" / "api_reference.md"

    content = generate_api_reference()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content)

    print(f"✅ API reference written to {output_path}")
    print(f"   Total size: {len(content):,} characters")

    return output_path


if __name__ == "__main__":
    import sys

    output_path = None
    if len(sys.argv) > 1:
        output_path = Path(sys.argv[1])

    write_api_reference(output_path)
