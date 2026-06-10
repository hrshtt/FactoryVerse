#!/usr/bin/env python3
"""Detailed token analysis with example-level breakdown."""

import re
import tiktoken
from pathlib import Path
from collections import defaultdict


def count_tokens(text: str, encoding) -> int:
    return len(encoding.encode(text))


def analyze_code_examples(content: str, encoding) -> dict:
    """Find and analyze all code blocks."""
    # Match ```python ... ``` blocks
    python_blocks = re.findall(r"```python\n(.*?)```", content, re.DOTALL)
    # Match ```sql ... ``` blocks
    sql_blocks = re.findall(r"```sql\n(.*?)```", content, re.DOTALL)
    # Match generic ``` ... ``` blocks
    generic_blocks = re.findall(r"```\n(.*?)```", content, re.DOTALL)

    python_tokens = sum(count_tokens(b, encoding) for b in python_blocks)
    sql_tokens = sum(count_tokens(b, encoding) for b in sql_blocks)
    generic_tokens = sum(count_tokens(b, encoding) for b in generic_blocks)

    return {
        "python_blocks": len(python_blocks),
        "python_tokens": python_tokens,
        "sql_blocks": len(sql_blocks),
        "sql_tokens": sql_tokens,
        "generic_blocks": len(generic_blocks),
        "generic_tokens": generic_tokens,
        "total_code_tokens": python_tokens + sql_tokens + generic_tokens,
    }


def analyze_tables(content: str, encoding) -> dict:
    """Find and analyze markdown tables."""
    # Match markdown tables (lines starting with |)
    table_lines = [line for line in content.split("\n") if line.strip().startswith("|")]
    table_content = "\n".join(table_lines)
    table_tokens = count_tokens(table_content, encoding)

    return {
        "table_lines": len(table_lines),
        "table_tokens": table_tokens,
    }


def count_by_pattern(content: str, encoding) -> dict:
    """Break down tokens by content type."""
    results = {}

    # Headers
    headers = re.findall(r"^#{1,6}.+$", content, re.MULTILINE)
    results["headers"] = count_tokens("\n".join(headers), encoding)

    # Method signatures (```python ... ```)
    signatures = re.findall(r"```python\n((?:async\s+)?(?:def|class)[^\n]+)\n", content)
    results["method_signatures"] = count_tokens("\n".join(signatures), encoding)

    # Decision Points sections
    decision_points = re.findall(r"\*\*Decision Points:\*\*.*?(?=\*\*Examples|$)", content, re.DOTALL)
    results["decision_points"] = count_tokens("\n".join(decision_points), encoding)

    # Example annotations (→ Returns..., Preconditions:, etc.)
    annotations = re.findall(r"→ .*$|Preconditions:.*$|Alternatives:.*$", content, re.MULTILINE)
    results["example_annotations"] = count_tokens("\n".join(annotations), encoding)

    # Error Handling sections
    error_sections = re.findall(r"\*\*Error Handling:\*\*.*?(?=####|###|##|$)", content, re.DOTALL)
    results["error_handling"] = count_tokens("\n".join(error_sections), encoding)

    return results


def main():
    encoding = tiktoken.get_encoding("cl100k_base")

    prompt_path = Path(".fv-output/evals/advanced_circuit_throughput/2026-01-23_17-59-35/system_prompt.md")
    content = prompt_path.read_text()

    total = count_tokens(content, encoding)

    print("=" * 80)
    print("DETAILED TOKEN ANALYSIS BY CONTENT TYPE")
    print("=" * 80)
    print(f"\n📊 Total: {total:,} tokens")
    print()

    # Extract DSL reference
    dsl_match = re.search(r"<dsl_reference>(.*?)</dsl_reference>", content, re.DOTALL)
    dsl_content = dsl_match.group(1) if dsl_match else ""

    # Code examples
    print("=" * 80)
    print("CODE EXAMPLES BREAKDOWN")
    print("=" * 80)
    print()

    code_stats = analyze_code_examples(content, encoding)
    code_total = code_stats["total_code_tokens"]
    code_pct = (code_total / total) * 100

    print(f"Python code blocks:  {code_stats['python_blocks']:>4} blocks → {code_stats['python_tokens']:>6,} tokens")
    print(f"SQL code blocks:     {code_stats['sql_blocks']:>4} blocks → {code_stats['sql_tokens']:>6,} tokens")
    print(f"Other code blocks:   {code_stats['generic_blocks']:>4} blocks → {code_stats['generic_tokens']:>6,} tokens")
    print("-" * 60)
    print(f"TOTAL CODE:                      → {code_total:>6,} tokens ({code_pct:.1f}%)")

    print()

    # Tables
    print("=" * 80)
    print("MARKDOWN TABLES BREAKDOWN")
    print("=" * 80)
    print()

    table_stats = analyze_tables(content, encoding)
    table_pct = (table_stats["table_tokens"] / total) * 100
    print(f"Table lines:  {table_stats['table_lines']:>4} lines")
    print(f"Table tokens: {table_stats['table_tokens']:>6,} tokens ({table_pct:.1f}%)")

    print()

    # Pattern breakdown
    print("=" * 80)
    print("STRUCTURAL BREAKDOWN (DSL Reference only)")
    print("=" * 80)
    print()

    pattern_stats = count_by_pattern(dsl_content, encoding)
    dsl_total = count_tokens(dsl_content, encoding)

    for name, tokens in sorted(pattern_stats.items(), key=lambda x: x[1], reverse=True):
        pct = (tokens / dsl_total) * 100
        print(f"{name:<25} {tokens:>6,} tokens ({pct:.1f}%)")

    print()

    # Most verbose examples
    print("=" * 80)
    print("LARGEST CODE EXAMPLES (Top 10)")
    print("=" * 80)
    print()

    python_blocks = re.findall(r"```python\n(.*?)```", content, re.DOTALL)
    block_tokens = [(count_tokens(b, encoding), b[:80].replace("\n", " ")) for b in python_blocks]
    block_tokens.sort(reverse=True)

    for tokens, preview in block_tokens[:10]:
        print(f"  {tokens:>4} tokens: {preview}...")

    print()

    # Prose vs Code
    print("=" * 80)
    print("PROSE vs CODE vs STRUCTURE")
    print("=" * 80)
    print()

    # Remove code blocks
    content_no_code = re.sub(r"```.*?```", "", content, flags=re.DOTALL)
    # Remove tables
    content_no_code_tables = "\n".join(
        line for line in content_no_code.split("\n")
        if not line.strip().startswith("|")
    )

    prose_tokens = count_tokens(content_no_code_tables, encoding)
    structure_tokens = table_stats["table_tokens"]

    print(f"Code examples:  {code_total:>6,} tokens ({code_pct:.1f}%)")
    print(f"Tables:         {structure_tokens:>6,} tokens ({table_pct:.1f}%)")
    print(f"Prose/headers:  {prose_tokens:>6,} tokens ({(prose_tokens/total)*100:.1f}%)")

    print()

    # Compression math
    print("=" * 80)
    print("COMPRESSION MATH")
    print("=" * 80)
    print()

    current_dsl = count_tokens(dsl_content, encoding)
    current_db = count_tokens(re.search(r"<database_reference>(.*?)</database_reference>", content, re.DOTALL).group(1), encoding)

    print("Current state:")
    print(f"  DSL Reference:      {current_dsl:>6,} tokens")
    print(f"  Database Reference: {current_db:>6,} tokens")
    print(f"  Other:              {total - current_dsl - current_db:>6,} tokens")
    print()

    print("If we reduce examples by 50% (keep 1 per method):")
    example_reduction = int(code_total * 0.4)  # 40% of code tokens
    new_total = total - example_reduction
    print(f"  Savings:            {example_reduction:>6,} tokens")
    print(f"  New total:          {new_total:>6,} tokens")
    print()

    print("If we also compact tables (30% reduction):")
    table_reduction = int(structure_tokens * 0.3)
    new_total_2 = new_total - table_reduction
    print(f"  Additional savings: {table_reduction:>6,} tokens")
    print(f"  New total:          {new_total_2:>6,} tokens")
    print()

    print("If we remove redundant Decision Points/Annotations (50% reduction):")
    dp_reduction = int((pattern_stats.get("decision_points", 0) + pattern_stats.get("example_annotations", 0)) * 0.5)
    new_total_3 = new_total_2 - dp_reduction
    print(f"  Additional savings: {dp_reduction:>6,} tokens")
    print(f"  New total:          {new_total_3:>6,} tokens")
    print()

    print(f"Total potential reduction: {total - new_total_3:,} tokens ({((total - new_total_3)/total)*100:.1f}%)")
    print(f"Compressed prompt would be: ~{new_total_3:,} tokens")


if __name__ == "__main__":
    main()
