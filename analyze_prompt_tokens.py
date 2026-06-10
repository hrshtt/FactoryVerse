#!/usr/bin/env python3
"""Analyze system prompt token usage by category using tiktoken."""

import re
import tiktoken
from pathlib import Path
from dataclasses import dataclass


@dataclass
class Section:
    name: str
    start_pattern: str
    end_pattern: str
    content: str = ""
    tokens: int = 0


def count_tokens(text: str, encoding) -> int:
    """Count tokens in text using tiktoken."""
    return len(encoding.encode(text))


def extract_sections(content: str) -> dict[str, str]:
    """Extract major sections from the system prompt."""
    sections = {}

    # Define section patterns (tag-based and header-based)
    tag_patterns = [
        ("identity", r"<identity>", r"</identity>"),
        ("game_knowledge", r"<game_knowledge>", r"</game_knowledge>"),
        ("strategic_mindset", r"<strategic_mindset>", r"</strategic_mindset>"),
        ("tools", r"<tools>", r"</tools>"),
        ("dsl_reference", r"<dsl_reference>", r"</dsl_reference>"),
        ("critical_requirements", r"<critical_requirements>", r"</critical_requirements>"),
        ("database_reference", r"<database_reference>", r"</database_reference>"),
        ("game_notifications", r"<game_notifications>", r"</game_notifications>"),
        ("response_style", r"<response_style>", r"</response_style>"),
        ("strategic_reminders", r"<strategic_reminders>", r"</strategic_reminders>"),
    ]

    for name, start, end in tag_patterns:
        pattern = f"{start}(.*?){end}"
        match = re.search(pattern, content, re.DOTALL)
        if match:
            sections[name] = match.group(0)  # Include tags

    # Extract task section (everything after </factorio_agent>)
    task_match = re.search(r"</factorio_agent>\s*(.+)$", content, re.DOTALL)
    if task_match:
        sections["task_definition"] = task_match.group(1)

    # Extract wrapper overhead
    wrapper = "<factorio_agent>\n\n</factorio_agent>"
    sections["wrapper_tags"] = wrapper

    return sections


def extract_dsl_subsections(dsl_content: str) -> dict[str, str]:
    """Break down the DSL reference into subsections."""
    subsections = {}

    # Runtime Environment section
    runtime_match = re.search(r"## Runtime Environment.*?(?=## Overview|---)", dsl_content, re.DOTALL)
    if runtime_match:
        subsections["runtime_environment"] = runtime_match.group(0)

    # Overview section (tables)
    overview_match = re.search(r"## Overview.*?(?=## Pre-Imported Types|## Quick Reference)", dsl_content, re.DOTALL)
    if overview_match:
        subsections["overview_tables"] = overview_match.group(0)

    # Pre-imported types
    types_match = re.search(r"## Pre-Imported Types.*?(?=## Quick Reference)", dsl_content, re.DOTALL)
    if types_match:
        subsections["pre_imported_types"] = types_match.group(0)

    # Quick Reference
    quick_ref_match = re.search(r"## Quick Reference.*?(?=## Action Classes)", dsl_content, re.DOTALL)
    if quick_ref_match:
        subsections["quick_reference"] = quick_ref_match.group(0)

    # Action Classes - break into individual classes
    action_classes = [
        ("action_MovementAction", r"### MovementAction.*?(?=### CraftingAction)"),
        ("action_CraftingAction", r"### CraftingAction.*?(?=### ResearchAction)"),
        ("action_ResearchAction", r"### ResearchAction.*?(?=### AgentInventory)"),
        ("action_AgentInventory", r"### AgentInventory.*?(?=## View Classes)"),
    ]

    for name, pattern in action_classes:
        match = re.search(pattern, dsl_content, re.DOTALL)
        if match:
            subsections[name] = match.group(0)

    # View Classes
    view_classes = [
        ("view_ReachableView", r"### ReachableView.*?(?=### RemoteView)"),
        ("view_RemoteView", r"### RemoteView.*?(?=## Placement|## View Classes\n\n\n)"),
    ]

    for name, pattern in view_classes:
        match = re.search(pattern, dsl_content, re.DOTALL)
        if match:
            subsections[name] = match.group(0)

    # Placement & Spatial Reasoning
    placement_match = re.search(r"## Placement & Spatial Reasoning.*?(?=## Entity Inspection Schema)", dsl_content, re.DOTALL)
    if placement_match:
        subsections["placement_spatial"] = placement_match.group(0)

    # Entity Inspection Schema
    inspection_match = re.search(r"## Entity Inspection Schema.*?(?=## Core Types)", dsl_content, re.DOTALL)
    if inspection_match:
        subsections["entity_inspection_schema"] = inspection_match.group(0)

    # Core Types
    core_types_match = re.search(r"## Core Types.*?(?=---\s*\*Generated)", dsl_content, re.DOTALL)
    if core_types_match:
        subsections["core_types"] = core_types_match.group(0)

    # Notes/footer
    footer_match = re.search(r"\*\*IMPORTANT NOTES\*\*:.*$", dsl_content, re.DOTALL)
    if footer_match:
        subsections["dsl_footer_notes"] = footer_match.group(0)

    return subsections


def analyze_database_reference(db_content: str) -> dict[str, str]:
    """Break down database reference into subsections."""
    subsections = {}

    # Query constraints
    constraints_match = re.search(r"## Query Constraints.*?(?=## Return Types|---)", db_content, re.DOTALL)
    if constraints_match:
        subsections["query_constraints"] = constraints_match.group(0)

    # Return Types
    return_types_match = re.search(r"## Return Types.*?(?=## Table Reference|---)", db_content, re.DOTALL)
    if return_types_match:
        subsections["return_types"] = return_types_match.group(0)

    # Table Reference
    table_ref_match = re.search(r"## Table Reference.*?(?=## Common Query Patterns|---)", db_content, re.DOTALL)
    if table_ref_match:
        subsections["table_reference"] = table_ref_match.group(0)

    # Common Query Patterns
    patterns_match = re.search(r"## Common Query Patterns.*?(?=## Complete Workflow|---)", db_content, re.DOTALL)
    if patterns_match:
        subsections["query_patterns"] = patterns_match.group(0)

    # Complete Workflow Example
    workflow_match = re.search(r"## Complete Workflow Example.*?(?=\*\*Key Query Patterns\*\*)", db_content, re.DOTALL)
    if workflow_match:
        subsections["workflow_example"] = workflow_match.group(0)

    return subsections


def main():
    # Use cl100k_base encoding (GPT-4/Claude approximate)
    encoding = tiktoken.get_encoding("cl100k_base")

    # Read the system prompt
    prompt_path = Path(".fv-output/evals/advanced_circuit_throughput/2026-01-23_17-59-35/system_prompt.md")
    content = prompt_path.read_text()

    total_tokens = count_tokens(content, encoding)

    print("=" * 80)
    print("SYSTEM PROMPT TOKEN ANALYSIS")
    print("=" * 80)
    print(f"\n📊 Total tokens: {total_tokens:,}")
    print(f"📄 File size: {len(content):,} characters")
    print()

    # Extract major sections
    sections = extract_sections(content)

    # Calculate tokens per section
    section_tokens = {}
    for name, text in sections.items():
        section_tokens[name] = count_tokens(text, encoding)

    # Sort by token count
    sorted_sections = sorted(section_tokens.items(), key=lambda x: x[1], reverse=True)

    print("=" * 80)
    print("TOP-LEVEL SECTION ANALYSIS")
    print("=" * 80)
    print()
    print(f"{'Section':<30} {'Tokens':>10} {'% of Total':>12}")
    print("-" * 55)

    for name, tokens in sorted_sections:
        pct = (tokens / total_tokens) * 100
        bar = "█" * int(pct / 2)
        print(f"{name:<30} {tokens:>10,} {pct:>10.1f}%  {bar}")

    print()

    # Deep dive into DSL reference
    if "dsl_reference" in sections:
        print("=" * 80)
        print("DSL REFERENCE BREAKDOWN (largest section)")
        print("=" * 80)
        print()

        dsl_subsections = extract_dsl_subsections(sections["dsl_reference"])
        dsl_tokens = {}
        for name, text in dsl_subsections.items():
            dsl_tokens[name] = count_tokens(text, encoding)

        sorted_dsl = sorted(dsl_tokens.items(), key=lambda x: x[1], reverse=True)

        dsl_total = section_tokens.get("dsl_reference", 0)
        print(f"{'Subsection':<35} {'Tokens':>10} {'% of DSL':>12}")
        print("-" * 60)

        for name, tokens in sorted_dsl:
            pct = (tokens / dsl_total) * 100 if dsl_total > 0 else 0
            bar = "█" * int(pct / 3)
            print(f"{name:<35} {tokens:>10,} {pct:>10.1f}%  {bar}")

        accounted = sum(dsl_tokens.values())
        unaccounted = dsl_total - accounted
        print("-" * 60)
        print(f"{'Accounted':<35} {accounted:>10,}")
        print(f"{'Unaccounted/overlap':<35} {unaccounted:>10,}")

    print()

    # Deep dive into database reference
    if "database_reference" in sections:
        print("=" * 80)
        print("DATABASE REFERENCE BREAKDOWN")
        print("=" * 80)
        print()

        db_subsections = analyze_database_reference(sections["database_reference"])
        db_tokens = {}
        for name, text in db_subsections.items():
            db_tokens[name] = count_tokens(text, encoding)

        sorted_db = sorted(db_tokens.items(), key=lambda x: x[1], reverse=True)

        db_total = section_tokens.get("database_reference", 0)
        print(f"{'Subsection':<30} {'Tokens':>10} {'% of DB Ref':>12}")
        print("-" * 55)

        for name, tokens in sorted_db:
            pct = (tokens / db_total) * 100 if db_total > 0 else 0
            print(f"{name:<30} {tokens:>10,} {pct:>10.1f}%")

    print()

    # Categorize by purpose
    print("=" * 80)
    print("CATEGORICAL ANALYSIS (by purpose)")
    print("=" * 80)
    print()

    categories = {
        "🎯 Core Identity & Strategy": ["identity", "strategic_mindset", "strategic_reminders", "response_style"],
        "🎮 Game Knowledge": ["game_knowledge", "game_notifications"],
        "📚 API Documentation": ["dsl_reference", "tools"],
        "💾 Database Documentation": ["database_reference"],
        "⚙️ Requirements & Rules": ["critical_requirements"],
        "📋 Task Definition": ["task_definition"],
    }

    print(f"{'Category':<40} {'Tokens':>10} {'% of Total':>12}")
    print("-" * 65)

    category_totals = {}
    for cat_name, section_names in categories.items():
        cat_total = sum(section_tokens.get(s, 0) for s in section_names)
        category_totals[cat_name] = cat_total
        pct = (cat_total / total_tokens) * 100
        bar = "█" * int(pct / 2)
        print(f"{cat_name:<40} {cat_total:>10,} {pct:>10.1f}%  {bar}")

    print()

    # Compression recommendations
    print("=" * 80)
    print("COMPRESSION OPPORTUNITIES")
    print("=" * 80)
    print()

    recommendations = [
        ("dsl_reference", "Remove verbose examples, keep only signatures + 1 example each", 0.4),
        ("database_reference", "Condense table schemas, remove duplicate SQL examples", 0.3),
        ("placement_spatial", "Heavy examples - could reduce to core patterns", 0.5),
        ("view_RemoteView", "Redundant SQL examples - consolidate", 0.4),
        ("entity_inspection_schema", "Table-heavy - could use more compact format", 0.3),
    ]

    print("Highest-impact compression targets:")
    print()

    for section, strategy, reduction in recommendations:
        current = 0
        # Try to find in dsl_subsections or section_tokens
        if "dsl_reference" in sections:
            dsl_subs = extract_dsl_subsections(sections["dsl_reference"])
            if section in dsl_subs:
                current = count_tokens(dsl_subs[section], encoding)
        if current == 0 and section in section_tokens:
            current = section_tokens[section]

        if current > 0:
            savings = int(current * reduction)
            print(f"  • {section}")
            print(f"    Strategy: {strategy}")
            print(f"    Current: {current:,} tokens → Potential savings: ~{savings:,} tokens")
            print()

    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()

    api_docs = section_tokens.get("dsl_reference", 0) + section_tokens.get("database_reference", 0)
    api_pct = (api_docs / total_tokens) * 100

    print(f"API Documentation (DSL + DB): {api_docs:,} tokens ({api_pct:.1f}% of total)")
    print(f"This is the primary compression target.")
    print()
    print("Compression strategies:")
    print("  1. Replace verbose examples with single canonical examples")
    print("  2. Use compact table format for method signatures")
    print("  3. Move detailed examples to a separate on-demand reference")
    print("  4. Consider semantic compression (remove redundant explanations)")
    print("  5. Use code-only examples without prose descriptions")


if __name__ == "__main__":
    main()
