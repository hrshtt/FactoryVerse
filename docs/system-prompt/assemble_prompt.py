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
PROJECT_ROOT = SCRIPT_DIR.parent.parent

include_examples = "--with-examples" in sys.argv

# Read base prompt
base_prompt = (SCRIPT_DIR / "factoryverse-system-prompt-v3.md").read_text()

# Read documentation from project root
dsl_doc = (PROJECT_ROOT / "dsl_documentation.txt").read_text()
duckdb_doc = (PROJECT_ROOT / "duckdb_documentation.txt").read_text()

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

# Write assembled prompt
output_path = SCRIPT_DIR / f"factoryverse-system-prompt-v3-{output_suffix}.md"
output_path.write_text(assembled)

print(f"✅ Assembled prompt written to {output_path.relative_to(PROJECT_ROOT)}")
print(f"   Examples included: {include_examples}")
print(f"   Total size: {len(assembled):,} characters")
print(f"   Total lines: {len(assembled.splitlines()):,} lines")
