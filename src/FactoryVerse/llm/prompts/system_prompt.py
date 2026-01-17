"""System prompt assembly for FactoryVerse agents.

This module generates the complete system prompt by:
1. Loading the base prompt template
2. Injecting API reference documentation
3. Injecting schema documentation
4. Optionally including code examples

The generated prompt is suitable for use with any LLM that supports
function calling / tool use.
"""

from pathlib import Path
from typing import Optional


def get_project_root() -> Path:
    """Find the FactoryVerse project root."""
    # Navigate up from this file to find project root
    current = Path(__file__).resolve()
    # llm/prompts/system_prompt.py -> llm/prompts -> llm -> FactoryVerse -> src -> project_root
    for _ in range(5):
        current = current.parent

    # Verify we found the right place
    if (current / "pyproject.toml").exists():
        return current

    # Fallback: find from cwd
    for candidate in [Path.cwd(), Path.cwd().parent]:
        if (candidate / "pyproject.toml").exists():
            return candidate

    raise RuntimeError("Could not find FactoryVerse project root")


def get_template_path() -> Path:
    """Get path to the base system prompt template."""
    root = get_project_root()
    return root / "docs" / "system-prompt" / "factoryverse-system-prompt-v3-template.md"


def get_examples_dir() -> Path:
    """Get path to code examples directory."""
    root = get_project_root()
    return root / "examples"


def generate_system_prompt(
    include_api_reference: bool = True,
    include_schema: bool = True,
    include_examples: bool = False,
    api_reference: Optional[str] = None,
    schema_reference: Optional[str] = None,
) -> str:
    """Generate complete system prompt for FactoryVerse agents.

    Assembles the system prompt by loading the template and injecting:
    - API reference documentation (DSL methods)
    - Schema reference (DuckDB tables)
    - Optional code examples

    Args:
        include_api_reference: Include API documentation
        include_schema: Include schema documentation
        include_examples: Include code examples from examples/ directory
        api_reference: Pre-generated API reference (if None, generates)
        schema_reference: Pre-generated schema reference (if None, generates)

    Returns:
        Complete system prompt string with placeholders for runtime data:
        - {UNLOCKED_RECIPES}: Runtime-injected unlocked recipes
        - {AVAILABLE_TECHNOLOGIES}: Runtime-injected tech tree
        - {CURRENT_RESEARCH}: Runtime-injected current research
    """
    # Load base template
    template_path = get_template_path()
    if not template_path.exists():
        raise FileNotFoundError(f"System prompt template not found: {template_path}")

    template = template_path.read_text()

    # Generate or use provided documentation
    if include_api_reference:
        if api_reference is None:
            from FactoryVerse.llm.prompts.api_reference import generate_api_reference

            api_reference = generate_api_reference()
    else:
        api_reference = "<!-- API Reference not included -->"

    if include_schema:
        if schema_reference is None:
            from FactoryVerse.llm.prompts.schema_reference import (
                generate_schema_reference,
            )

            schema_reference = generate_schema_reference()
    else:
        schema_reference = "<!-- Schema Reference not included -->"

    # Handle examples
    if include_examples:
        examples_dir = get_examples_dir()
        if examples_dir.exists():
            example_files = sorted(examples_dir.glob("*.py"))
            examples_content = []
            for example_file in example_files:
                if example_file.name != "__pycache__":
                    content = example_file.read_text()
                    examples_content.append(
                        f"### {example_file.name}\n\n```python\n{content}\n```\n"
                    )
            code_examples = "\n".join(examples_content)
            code_examples = f"<code_examples>\n{code_examples}\n</code_examples>"
        else:
            code_examples = ""
    else:
        code_examples = ""

    # Assemble the prompt
    assembled = template.replace("{DSL_DOCUMENTATION}", api_reference)
    assembled = assembled.replace("{DUCKDB_DOCUMENTATION}", schema_reference)
    assembled = assembled.replace("{CODE_EXAMPLES}", code_examples)

    # Leave runtime placeholders intact:
    # {UNLOCKED_RECIPES}
    # {AVAILABLE_TECHNOLOGIES}
    # {CURRENT_RESEARCH}

    return assembled


def write_system_prompt(
    output_path: Path, include_examples: bool = False, **kwargs
) -> None:
    """Generate and write system prompt to file.

    Args:
        output_path: Where to write the prompt
        include_examples: Whether to include code examples
        **kwargs: Additional args passed to generate_system_prompt()
    """
    prompt = generate_system_prompt(include_examples=include_examples, **kwargs)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(prompt)

    print(f"✅ System prompt written to {output_path}")
    print(f"   Examples included: {include_examples}")
    print(f"   Total size: {len(prompt):,} characters")
    print(f"   Total lines: {len(prompt.splitlines()):,} lines")


if __name__ == "__main__":
    import sys

    include_examples = "--with-examples" in sys.argv

    root = get_project_root()
    suffix = "with-examples" if include_examples else "core"
    output_path = (
        root / "docs" / "system-prompt" / f"factoryverse-system-prompt-v3-{suffix}.md"
    )

    write_system_prompt(output_path, include_examples=include_examples)
