# System Prompt Token Analysis Report

**File:** `.fv-output/evals/advanced_circuit_throughput/2026-01-23_17-59-35/system_prompt.md`
**Total Tokens:** 21,499
**Analyzer:** tiktoken (cl100k_base encoding)

---

## Executive Summary

**90% of your system prompt is API documentation.** The DSL reference and database reference together consume 19,287 tokens (89.8%). The core strategy, identity, and game knowledge that actually guide agent behavior are only ~2,000 tokens (10%).

### Token Distribution by Category

| Category | Tokens | % | Visual |
|----------|--------|---|--------|
| 📚 API Documentation (DSL) | 15,044 | 70.0% | ████████████████████████████████████ |
| 💾 Database Documentation | 4,257 | 19.8% | ██████████ |
| 🎯 Core Identity & Strategy | 894 | 4.2% | ██ |
| 🎮 Game Knowledge | 618 | 2.9% | █ |
| 📋 Task Definition | 326 | 1.5% | |
| ⚙️ Critical Requirements | 86 | 0.4% | |

---

## Detailed Breakdown

### DSL Reference (15,044 tokens - 70%)

| Subsection | Tokens | % of DSL |
|------------|--------|----------|
| `placement_spatial` | 4,077 | 27.1% |
| `view_RemoteView` | 1,756 | 11.7% |
| `entity_inspection_schema` | 1,651 | 11.0% |
| `core_types` | 1,488 | 9.9% |
| `view_ReachableView` | 1,426 | 9.5% |
| `quick_reference` | 970 | 6.4% |
| `action_AgentInventory` | 739 | 4.9% |
| `action_CraftingAction` | 688 | 4.6% |
| `action_MovementAction` | 592 | 3.9% |
| Others | 1,657 | 11.0% |

### Content Type Analysis

| Type | Tokens | % of Total |
|------|--------|------------|
| **Code Examples** | 18,546 | **86.3%** |
| Markdown Tables | 3,019 | 14.0% |
| Prose/Headers | 9,931 | 46.2% |

**Key insight:** 130 Python code blocks + 138 other code blocks = 268 code examples consuming 86% of tokens.

### Largest Code Examples

| Tokens | Description |
|--------|-------------|
| 274 | ELECTRIC_WIRE connection example |
| 233 | Complete workflow example |
| 179 | Entity inspection example |
| 174 | BaseEntity class definition |
| 163 | ITEM_DROP placement example |

---

## Compression Opportunities

### High-Impact Targets

1. **DSL Reference Examples** (potential: -6,000 tokens)
   - Current: 3-5 examples per method
   - Target: 1 canonical example per method
   - Strategy: Keep the most instructive example, remove redundant variants

2. **Placement/Spatial Section** (potential: -2,000 tokens)
   - 4,077 tokens for placement hints
   - Many verbose examples showing similar patterns
   - Strategy: Consolidate to core patterns only

3. **Database Reference** (potential: -1,500 tokens)
   - Duplicate SQL patterns
   - Verbose table definitions
   - Strategy: Compact schema format, single example per pattern

4. **Entity Inspection Schema** (potential: -800 tokens)
   - 1,651 tokens of capability slot tables
   - Strategy: More compact table format

### Recommended Compression Math

| Action | Savings | New Total |
|--------|---------|-----------|
| Start | - | 21,499 |
| Reduce examples 50% | -7,418 | 14,081 |
| Compact tables 30% | -905 | 13,176 |
| Remove redundant annotations | -888 | 12,288 |
| **Total** | **-9,211** | **~12,000** |

---

## Structural Recommendations

### 1. Tiered Documentation
```
Tier 1 (Always in prompt): Signatures + 1 example each (~8,000 tokens)
Tier 2 (On-demand): Extended examples, edge cases
Tier 3 (Reference): Full API docs (current state)
```

### 2. Compact Method Format
**Current (verbose):**
```markdown
#### `walking.walk_to`

\`\`\`python
async walk_to(goal: MapPosition, strict_goal: bool = ..., ...) -> MapPosition
\`\`\`

Walk to a target position. Returns when agent arrives or fails.

**Decision Points:**
- Use walk_to(position) for known coordinates
- Use entity.walk_to() for navigating to entities

**Examples:**
*Walking to a known coordinate:*
\`\`\`python
# Walk to a known coordinate
position = MapPosition(x=10.5, y=20.5)
final_pos = await walking.walk_to(position)
\`\`\`
→ Agent walks to position and returns final MapPosition
```

**Compressed (efficient):**
```markdown
`walking.walk_to(goal: MapPosition, strict_goal=False) -> MapPosition`
Walk to position. Use `entity.walk_to()` for entity-aware pathfinding.
\`\`\`python
await walking.walk_to(MapPosition(x=10, y=20))
\`\`\`
```

### 3. Remove Redundant Elements
- **Decision Points** → Only keep when choice is non-obvious
- **Example annotations** (→ Returns...) → Code should be self-explanatory
- **Preconditions** → Merge into example comment if needed
- **Error Handling sections** → Keep only critical ones

### 4. Database Schema Compression
**Current:**
```markdown
| Column | Type | Description |
|--------|------|-------------|
| `entity_name` | `VARCHAR` | Factorio internal name (e.g., 'burner-mining-drill') |
| `position_x` | `DOUBLE` | X coordinate on the map |
...
```

**Compressed:**
```markdown
`map_entity(entity_name, position_x/y, chunk_x/y, direction, bbox_*, electric_network_id, tile_x/y, raw_data)`
```

---

## Implementation Priority

1. **Immediate (Quick wins):**
   - Remove duplicate examples (keep 1 per method)
   - Remove example annotations (→ Returns...)
   - Compact table schemas to one-line format

2. **Medium-term:**
   - Implement tiered documentation loading
   - Create "slim" vs "full" prompt variants
   - Semantic compression of Decision Points

3. **Long-term:**
   - Dynamic documentation injection based on task
   - Tool-call based documentation retrieval
   - Fine-tuned model that requires less documentation

---

## Files Generated

- `analyze_prompt_tokens.py` - Section-level analysis
- `analyze_prompt_detailed.py` - Code example analysis
- `TOKEN_ANALYSIS_REPORT.md` - This report
