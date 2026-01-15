#!/usr/bin/env python3
"""Assemble the complete system prompt with documentation injected.

Usage:
    python assemble_prompt.py              # Core version (no examples)
    python assemble_prompt.py --with-examples  # Full version with examples
"""

import sys
from pathlib import Path

# Determine project root (two levels up from this script)
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent

include_examples = "--with-examples" in sys.argv

# Read base prompt template from docs/system-prompt/
base_prompt = (PROJECT_ROOT / "docs" / "system-prompt" / "factoryverse-system-prompt-v3-template.md").read_text()

# Read documentation from generated markdown files
dsl_doc = (PROJECT_ROOT / "docs" / "for-llms" / "api_reference.md").read_text()
duckdb_doc = (PROJECT_ROOT / "docs" / "for-llms" / "schema_reference.md").read_text()

# Handle examples
if include_examples:
    examples_dir = PROJECT_ROOT / "examples"
    example_files = sorted(examples_dir.glob("*.py"))
    examples_content = []
    for example_file in example_files:
        if example_file.name != "__pycache__":
            content = example_file.read_text()
            examples_content.append(f"### {example_file.name}\n\n```python\n{content}\n```\n")
    code_examples = "\n".join(examples_content)
    # Wrap in XML tags
    code_examples = f"<code_examples>\n{code_examples}\n</code_examples>"
    output_suffix = "with-examples"
else:
    # Empty string when not including examples
    code_examples = ""
    output_suffix = "core"

# Replace placeholders
assembled = base_prompt.replace("{DSL_DOCUMENTATION}", dsl_doc)
assembled = assembled.replace("{DUCKDB_DOCUMENTATION}", duckdb_doc)
assembled = assembled.replace("{CODE_EXAMPLES}", code_examples)

# Leave these for runtime injection:
# {UNLOCKED_RECIPES}
# {AVAILABLE_TECHNOLOGIES}
# {CURRENT_RESEARCH}

# Parse arguments for output path
output_path_arg = None
for arg in sys.argv[1:]:
    if arg == "--with-examples":
        include_examples = True
    elif not arg.startswith("--"):
        # Assume it's an output path
        output_path_arg = Path(arg)

# Write assembled prompt (to specified path or default location)
if output_path_arg:
    output_path = output_path_arg
else:
    output_suffix = "with-examples" if include_examples else "core"
    output_path = PROJECT_ROOT / "docs" / "system-prompt" / f"factoryverse-system-prompt-v3-{output_suffix}.md"

output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_text(assembled)

# Show relative path if within project, absolute path otherwise
try:
    rel_path = output_path.relative_to(PROJECT_ROOT)
    path_display = str(rel_path)
except ValueError:
    path_display = str(output_path)

print(f"✅ Assembled prompt written to {path_display}")
print(f"   Examples included: {include_examples}")
print(f"   Total size: {len(assembled):,} characters")
print(f"   Total lines: {len(assembled.splitlines()):,} lines")
