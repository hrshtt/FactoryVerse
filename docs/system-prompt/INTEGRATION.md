# System Prompt v3 Integration Guide

## What's Ready

✅ **System prompt template**: `docs/system-prompt/factoryverse-system-prompt-v3.md`
✅ **Assembly script**: `docs/system-prompt/assemble_prompt.py`  
✅ **Documentation generation**: `scripts/documentation_DSL.py` and `scripts/documentation_duckdb.py`
✅ **Example code files**: `examples/01-05_*.py`

## What's Needed for Agent Runs

### 1. System Prompt (Cacheable, Invariant)

**File**: `docs/system-prompt/factoryverse-system-prompt-v3-core.md` (assembled version)

**Contents**:
- Strategic guidance (bottleneck thinking, anti-patterns, progression)
- DSL documentation (auto-generated from `dsl_documentation.txt`)
- DuckDB schema (auto-generated from `duckdb_documentation.txt`)
- Code examples (optional, via `--with-examples`)

**Important**: This is **static** and should be cached between runs. No dynamic state here.

**Generation**:
```bash
cd docs/system-prompt
uv run python assemble_prompt.py  # Generates core version
```

### 2. First System Message (Dynamic, Per-Session)

**Purpose**: Provide current game state summary that changes between sessions

**Contents** (from `initial_state_generator.py` or equivalent):
- Current unlocked recipes
- Available technologies to research  
- Current research progress
- Agent position and inventory
- Database schema overview (table row counts)
- Example queries for current map

**Why separate**: Prevents cache misses. The system prompt stays invariant, only the first message changes.

**Format** (suggested):
```markdown
# Current Game State

## Agent Status
- Position: (x, y)
- Inventory: [list of items]

## Unlocked Recipes
[List of currently unlocked recipes with ingredients/products]

## Available Technologies
[Technologies that can be researched now]

## Current Research
[What's being researched, progress %]

## Map Overview
[Database table counts, key resource patch locations]
```

### 3. Integration Points to Update

#### A. Prompt Loading
**File to modify**: Likely `src/FactoryVerse/llm/initial_state_generator.py` or agent runner

**Current**: Loads `factoryverse-system-prompt-v2.md` as system prompt

**New**:
1. Load `docs/system-prompt/factoryverse-system-prompt-v3-core.md` as system prompt
2. Generate first system message with current state using existing `initial_state_generator` logic
3. Keep system prompt cacheable, put dynamic state in first message

#### B. Documentation Generation
**Files**: Already exist, no changes needed
- `scripts/documentation_DSL.py` → `dsl_documentation.txt`
- `scripts/documentation_duckdb.py` → `duckdb_documentation.txt`

**When to run**: Before assembling the prompt (can be part of setup/build)

#### C. Assembly Process
**Workflow**:
```bash
# 1. Generate documentation (if not already done)
uv run python scripts/documentation_DSL.py
uv run python scripts/documentation_duckdb.py

# 2. Assemble prompt
cd docs/system-prompt
uv run python assemble_prompt.py  # Creates v3-core.md

# 3. Use v3-core.md as system prompt in agent
# 4. Generate first message dynamically per-session
```

### 4. What's NOT Ready Yet

❌ **Verification loop section** - Drafted but not integrated (in `verification-loop-draft.md`)
❌ **Failure recovery patterns** - Needs more work based on actual agent performance
❌ **Long trajectory compression** - Future work (invariant summaries across compressions)

## Recommended Next Steps

1. **Update agent runner** to:
   - Use `v3-core.md` as system prompt
   - Generate first message with current state (reuse `initial_state_generator` logic)
   
2. **Test with simple task** to validate:
   - Prompt is understood
   - Strategic guidance is followed
   - Technical docs are accessible
   
3. **Iterate based on performance**:
   - Add verification patterns if needed
   - Refine examples based on common mistakes
   - Tune strategic guidance based on observed bottlenecks

## File Locations

```
docs/system-prompt/
├── factoryverse-system-prompt-v3.md          # Template (250 lines)
├── factoryverse-system-prompt-v3-core.md     # Assembled core (693 lines)
├── factoryverse-system-prompt-v3-with-examples.md  # With examples (1,355 lines)
├── assemble_prompt.py                        # Assembly script
└── README.md                                 # Documentation

examples/
├── 01_basic_query_and_walk.py
├── 02_mining_resources.py
├── 03_placing_entities.py
├── 04_automation_setup.py
└── 05_full_workflow.py

# Generated documentation (auto-created by scripts)
dsl_documentation.txt         # 307 lines
duckdb_documentation.txt      # 127 lines
```

## Questions for Refinement

1. Should we pre-generate and commit the assembled prompts, or assemble on-demand?
2. What's the format preference for the first system message?
3. Should code examples be included by default or only for training/debugging?
