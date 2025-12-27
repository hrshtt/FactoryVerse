#!/usr/bin/env python3
"""Generate and update all LLM documentation.

This script:
1. Generates DSL documentation and saves to docs/for-llms/
2. Generates DuckDB schema documentation and saves to docs/for-llms/
3. Updates system prompts in docs/system-prompt/ with latest documentation

Usage:
    python scripts/generate_llm_docs.py
    python scripts/generate_llm_docs.py --with-examples  # Include code examples in prompts
"""

import sys
from pathlib import Path

# Determine project root
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DOCS_DIR = PROJECT_ROOT / "docs"
FOR_LLMS_DIR = DOCS_DIR / "for-llms"
SYSTEM_PROMPT_DIR = DOCS_DIR / "system-prompt"

# Ensure output directory exists
FOR_LLMS_DIR.mkdir(parents=True, exist_ok=True)

# Add src to path for imports
sys.path.insert(0, str(PROJECT_ROOT / "src"))

print("=" * 60)
print("Generating LLM Documentation")
print("=" * 60)

# ============================================
# 1. Generate DSL Documentation
# ============================================
print("\n[1/4] Generating DSL documentation...")

from FactoryVerse.dsl.document_dsl import generate_complete_interface_doc

dsl_doc = generate_complete_interface_doc(show_inherited=False)
dsl_output_path = FOR_LLMS_DIR / "dsl_documentation.txt"
dsl_output_path.write_text(dsl_doc)

print(f"   ✅ DSL documentation written to {dsl_output_path.relative_to(PROJECT_ROOT)}")
print(f"      Size: {len(dsl_doc):,} characters")
print(f"      Lines: {len(dsl_doc.splitlines()):,}")

# ============================================
# 2. Generate DuckDB Schema Documentation
# ============================================
print("\n[2/4] Generating DuckDB schema documentation...")

try:
    from FactoryVerse.infra.db.document_duckdb import generate_schema_doc
    import duckdb
    from pathlib import Path
    
    # Try to find database in common locations
    db_paths = [
        PROJECT_ROOT / "map.db",
        PROJECT_ROOT / "factoryverse.db",
    ]
    
    db_path = None
    for path in db_paths:
        if path.exists():
            db_path = path
            break
    
    if db_path:
        con = duckdb.connect(str(db_path), read_only=True)
        duckdb_doc = generate_schema_doc(con, include_enum_details=False)
        con.close()
        
        duckdb_output_path = FOR_LLMS_DIR / "duckdb_documentation.txt"
        duckdb_output_path.write_text(duckdb_doc)
        
        print(f"   ✅ DuckDB documentation written to {duckdb_output_path.relative_to(PROJECT_ROOT)}")
        print(f"      Database: {db_path.relative_to(PROJECT_ROOT)}")
        print(f"      Size: {len(duckdb_doc):,} characters")
        print(f"      Lines: {len(duckdb_doc.splitlines()):,}")
    else:
        raise FileNotFoundError("No database file found")
        
except Exception as e:
    print(f"   ⚠️  DuckDB documentation generation failed: {e}")
    print(f"      This is expected if database doesn't exist yet.")
    duckdb_doc = "# DuckDB Schema Documentation\n\n(Database not yet initialized)\n"
    duckdb_output_path = FOR_LLMS_DIR / "duckdb_documentation.txt"
    duckdb_output_path.write_text(duckdb_doc)
    print(f"   📝 Placeholder written to {duckdb_output_path.relative_to(PROJECT_ROOT)}")

# ============================================
# 3. Assemble System Prompts (Core Version)
# ============================================
print("\n[3/4] Assembling system prompt (core version)...")

base_prompt_path = SYSTEM_PROMPT_DIR / "factoryverse-system-prompt-v3.md"
if not base_prompt_path.exists():
    print(f"   ⚠️  Base prompt not found: {base_prompt_path.relative_to(PROJECT_ROOT)}")
    print(f"      Skipping system prompt assembly.")
else:
    base_prompt = base_prompt_path.read_text()
    
    # Replace placeholders
    assembled_core = base_prompt.replace("{DSL_DOCUMENTATION}", dsl_doc)
    assembled_core = assembled_core.replace("{DUCKDB_DOCUMENTATION}", duckdb_doc)
    assembled_core = assembled_core.replace("{CODE_EXAMPLES}", "")  # No examples in core
    
    # Write core version
    core_output_path = SYSTEM_PROMPT_DIR / "factoryverse-system-prompt-v3-core.md"
    core_output_path.write_text(assembled_core)
    
    print(f"   ✅ Core prompt written to {core_output_path.relative_to(PROJECT_ROOT)}")
    print(f"      Size: {len(assembled_core):,} characters")
    print(f"      Lines: {len(assembled_core.splitlines()):,}")

# ============================================
# 4. Assemble System Prompts (With Examples)
# ============================================
include_examples = "--with-examples" in sys.argv

if include_examples and base_prompt_path.exists():
    print("\n[4/4] Assembling system prompt (with examples)...")
    
    # Gather code examples
    examples_dir = PROJECT_ROOT / "examples"
    if examples_dir.exists():
        example_files = sorted(examples_dir.glob("*.py"))
        examples_content = []
        for example_file in example_files:
            if example_file.name != "__pycache__":
                content = example_file.read_text()
                examples_content.append(f"### {example_file.name}\n\n```python\n{content}\n```\n")
        code_examples = "\n".join(examples_content)
        # Wrap in XML tags
        code_examples = f"<code_examples>\n{code_examples}\n</code_examples>"
    else:
        code_examples = ""
    
    # Replace placeholders
    assembled_with_examples = base_prompt.replace("{DSL_DOCUMENTATION}", dsl_doc)
    assembled_with_examples = assembled_with_examples.replace("{DUCKDB_DOCUMENTATION}", duckdb_doc)
    assembled_with_examples = assembled_with_examples.replace("{CODE_EXAMPLES}", code_examples)
    
    # Write version with examples
    examples_output_path = SYSTEM_PROMPT_DIR / "factoryverse-system-prompt-v3-with-examples.md"
    examples_output_path.write_text(assembled_with_examples)
    
    print(f"   ✅ Prompt with examples written to {examples_output_path.relative_to(PROJECT_ROOT)}")
    print(f"      Size: {len(assembled_with_examples):,} characters")
    print(f"      Lines: {len(assembled_with_examples.splitlines()):,}")
else:
    print("\n[4/4] Skipping examples version (use --with-examples to include)")

# ============================================
# Summary
# ============================================
print("\n" + "=" * 60)
print("Documentation Generation Complete")
print("=" * 60)
print(f"\nGenerated files:")
print(f"  - {dsl_output_path.relative_to(PROJECT_ROOT)}")
print(f"  - {duckdb_output_path.relative_to(PROJECT_ROOT)}")
if base_prompt_path.exists():
    print(f"  - {core_output_path.relative_to(PROJECT_ROOT)}")
    if include_examples:
        print(f"  - {examples_output_path.relative_to(PROJECT_ROOT)}")
print()
