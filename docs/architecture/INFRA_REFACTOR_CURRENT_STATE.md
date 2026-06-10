# Infrastructure Refactor: Current State Analysis

## Overview

This document compares the **planned refactor** (from `INFRA_REFACTOR_PLAN.md`) against the **current implementation state** of the FactoryVerse codebase.

**Important Context:**
- The stale files in `infra/llm/` are **temporary migration artifacts** kept during verification
- **No backward compatibility shims** - this is an anti-pattern for this codebase
- Once migration is verified (Phase 6 complete per `INFRA_REFACTOR_PROGRESS.md`), these files should be deleted
- The goal is a clean final state matching the plan exactly

---

## What Was Planned

### Module Structure (From Plan)

```
FactoryVerse/
├── cli.py                          # Unified CLI entry point
├── runtime.py                      # AgentRuntime (DOMAIN - unchanged)
│
├── infra/
│   ├── boilerplate/                # MOVED: Domain loading (scopes, context)
│   │   ├── __init__.py             # Scope, load(), BoilerplateContext
│   │   ├── rcon.py
│   │   ├── snapshot.py
│   │   ├── agent.py
│   │   ├── runtime.py
│   │   └── test_ground.py
│   │
│   ├── execution/                  # NEW: Unified execution layer
│   │   ├── __init__.py
│   │   ├── base.py                 # ExecutionEnvironment ABC
│   │   ├── jupyter.py              # JupyterExecutor
│   │   └── inprocess.py            # InProcessExecutor
│   │
│   ├── session/                    # NEW: Unified session management
│   │   ├── __init__.py
│   │   ├── session.py              # FactoryVerseSession (executor + context)
│   │   └── file_manager.py         # Directory/file management
│   │
│   ├── output/                     # EXTRACTED: Generic output utilities
│   │   ├── __init__.py
│   │   ├── console.py              # ConsoleOutput
│   │   └── error_parser.py         # FactorioErrorParser
│   │
│   └── docker/                     # UNCHANGED
│
├── llm/                            # RENAMED: LLM-specific orchestration layer
│   ├── __init__.py
│   ├── client/                     # LLM client abstraction
│   │   ├── __init__.py
│   │   ├── base.py                 # LLMClient ABC
│   │   ├── openai_compatible.py    # OpenAI-compatible client
│   │   └── factory.py              # Factory functions
│   │
│   ├── orchestrator.py             # FactorioAgentOrchestrator
│   ├── trajectory.py               # TrajectoryManager
│   ├── context/                    # Context management for LLMs
│   │   ├── __init__.py
│   │   ├── compressor.py           # OutputCompressor
│   │   ├── validator.py            # ToolValidator
│   │   └── initial_state.py       # InitialStateGenerator
│   │
│   └── prompts/                    # CONSOLIDATED: All prompt-related generation
│       ├── __init__.py
│       ├── system_prompt.py        # System prompt assembly
│       ├── api_reference.py        # API docs generation
│       ├── schema_reference.py     # Schema docs
│       ├── tech_recipes.py         # TechRecipePromptGenerator
│       └── categorical.py          # CategoricalReferenceGenerator
│
└── mcp_server/                     # UPDATED: Uses new session layer
    ├── __init__.py
    └── server.py
```

### Key Principles from Plan

1. **`infra/llm/` should be REMOVED** - everything moved to either `llm/` or `infra/output/`
2. **`boilerplate/` should be at `infra/boilerplate/`** - NOT under `infra/llm/`
3. **All imports should use new paths** - no references to `infra/llm/` except backward compat shims
4. **Scripts should be thin wrappers** - core logic in importable modules

---

## What Actually Exists

### Current Module Structure

```
FactoryVerse/
├── cli.py                          # ✅ Has prompts/agent commands
├── runtime.py                      # ✅ Unchanged
│
├── infra/
│   ├── boilerplate/                # ✅ EXISTS (moved from infra/llm/boilerplate)
│   │   ├── __init__.py             # ✅ Scope, load(), BoilerplateContext
│   │   ├── rcon.py                 # ✅
│   │   ├── snapshot.py             # ✅
│   │   ├── agent.py                # ✅
│   │   ├── runtime.py              # ✅
│   │   ├── test_ground.py          # ✅
│   │   └── mcp.py                  # ✅
│   │
│   ├── execution/                  # ✅ EXISTS
│   │   ├── __init__.py             # ✅
│   │   ├── base.py                 # ✅ ExecutionEnvironment ABC
│   │   ├── jupyter.py              # ✅ JupyterExecutor
│   │   └── inprocess.py            # ✅ InProcessExecutor
│   │
│   ├── session/                    # ✅ EXISTS
│   │   ├── __init__.py             # ✅
│   │   ├── session.py              # ✅ FactoryVerseSession
│   │   ├── file_manager.py         # ✅
│   │   ├── lifecycle.py            # ✅ (extra, not in plan)
│   │   └── trajectory.py           # ✅ (extra, not in plan)
│   │
│   ├── output/                     # ✅ EXISTS
│   │   ├── __init__.py             # ✅
│   │   ├── console.py              # ✅ ConsoleOutput
│   │   ├── error_parser.py         # ✅ FactorioErrorParser
│   │   └── web.py                  # ⚠️ (extra, not in plan)
│   │
│   └── llm/                        # ❌ STILL EXISTS (should be removed!)
│       ├── __init__.py             # ⚠️ Still exports PrimeIntellectClient
│       ├── agent_orchestrator.py   # ❌ OLD - should use llm/orchestrator.py
│       ├── client.py               # ❌ OLD - should use llm/client/
│       ├── trajectory_manager.py  # ❌ OLD - should use llm/trajectory.py
│       ├── tool_validator.py      # ❌ OLD - should use llm/context/validator.py
│       ├── output_compressor.py   # ❌ OLD - should use llm/context/compressor.py
│       ├── initial_state_generator.py  # ❌ OLD - should use llm/context/initial_state.py
│       ├── tech_recipe_prompt.py  # ❌ OLD - should use llm/prompts/tech_recipes.py
│       ├── categorical_references.py  # ❌ OLD - should use llm/prompts/categorical.py
│       ├── console_output.py      # ❌ OLD - should use infra/output/console.py
│       ├── factorio_error_parser.py    # ❌ OLD - should use infra/output/error_parser.py
│       ├── session_manager.py      # ❌ OLD - functionality moved to infra/session/
│       ├── boilerplate.py          # ❌ OLD - functionality moved to infra/boilerplate/
│       │
│       └── boilerplate/            # ⚠️ BACKWARD COMPAT SHIM (re-exports from infra/boilerplate)
│           ├── __init__.py         # ✅ Re-exports with deprecation warning
│           ├── agent.py            # ❌ Still exists (should be removed)
│           ├── mcp.py              # ❌ Still exists (should be removed)
│           ├── rcon.py             # ❌ Still exists (should be removed)
│           ├── runtime.py          # ❌ Still exists (should be removed)
│           ├── snapshot.py         # ❌ Still exists (should be removed)
│           ├── test_ground.py      # ❌ Still exists (should be removed)
│           └── README.md           # ❌ Still exists (should be removed)
│
├── llm/                            # ✅ EXISTS (new location)
│   ├── __init__.py                 # ✅
│   ├── client/                     # ✅ EXISTS
│   │   ├── __init__.py             # ✅
│   │   ├── base.py                 # ✅ LLMClient ABC
│   │   ├── openai_compatible.py   # ✅
│   │   └── factory.py              # ✅
│   │
│   ├── orchestrator.py             # ✅ EXISTS
│   ├── trajectory.py               # ✅ EXISTS
│   ├── context/                    # ✅ EXISTS
│   │   ├── __init__.py             # ✅
│   │   ├── compressor.py           # ✅
│   │   ├── validator.py            # ✅
│   │   └── initial_state.py        # ✅
│   │
│   └── prompts/                    # ✅ EXISTS
│       ├── __init__.py             # ✅
│       ├── system_prompt.py        # ✅
│       ├── api_reference.py        # ✅
│       ├── schema_reference.py     # ✅
│       ├── tech_recipes.py         # ✅
│       └── categorical.py          # ✅
│
└── mcp_server/                     # ✅ EXISTS
    ├── __init__.py                 # ✅
    └── server.py                   # ⚠️ Still imports from infra/llm/boilerplate
```

---

## Key Discrepancies

### 1. `infra/llm/` Still Exists ❌

**Problem:** The entire `infra/llm/` directory should have been removed after migration, but it still contains:

- **Old implementations** that duplicate functionality in `llm/`:
  - `agent_orchestrator.py` (old) vs `llm/orchestrator.py` (new)
  - `trajectory_manager.py` (old) vs `llm/trajectory.py` (new)
  - `client.py` (old) vs `llm/client/` (new)
  - `tool_validator.py` (old) vs `llm/context/validator.py` (new)
  - `output_compressor.py` (old) vs `llm/context/compressor.py` (new)
  - `initial_state_generator.py` (old) vs `llm/context/initial_state.py` (new)
  - `tech_recipe_prompt.py` (old) vs `llm/prompts/tech_recipes.py` (new)
  - `categorical_references.py` (old) vs `llm/prompts/categorical.py` (new)

- **Old utilities** that should have been moved:
  - `console_output.py` → should be in `infra/output/console.py` ✅ (moved)
  - `factorio_error_parser.py` → should be in `infra/output/error_parser.py` ✅ (moved)
  - `session_manager.py` → functionality moved to `infra/session/` ✅ (moved)
  - `boilerplate.py` → functionality moved to `infra/boilerplate/` ✅ (moved)

- **Backward compat shim** (acceptable, but should be minimal):
  - `infra/llm/boilerplate/__init__.py` ✅ (re-exports with deprecation)
  - But the actual files still exist! ❌

### 2. Import Inconsistencies ❌

**Files still importing from old `infra/llm/` paths:**

1. **`infra/execution/jupyter.py`**:
   ```python
   from FactoryVerse.infra.llm.output_compressor import OutputCompressor
   from FactoryVerse.infra.llm.factorio_error_parser import FactorioErrorParser
   ```
   Should be:
   ```python
   from FactoryVerse.infra.output.console import OutputCompressor  # Wait, this is wrong
   from FactoryVerse.infra.output.error_parser import FactorioErrorParser
   ```
   Actually, `OutputCompressor` should be from `llm/context/compressor.py`!

2. **`mcp_server/server.py`**:
   ```python
   from FactoryVerse.infra.llm.boilerplate import Scope
   from FactoryVerse.infra.llm.boilerplate.mcp import mcp_create_session
   ```
   Should be:
   ```python
   from FactoryVerse.infra.boilerplate import Scope
   from FactoryVerse.infra.boilerplate.mcp import mcp_create_session
   ```

3. **`infra/session/session.py`**:
   ```python
   from FactoryVerse.infra.llm.boilerplate import Scope
   ```
   Should be:
   ```python
   from FactoryVerse.infra.boilerplate import Scope
   ```

4. **`agent_runtime.py`** (legacy file?):
   ```python
   from FactoryVerse.infra.llm.output_compressor import OutputCompressor
   from FactoryVerse.infra.llm.factorio_error_parser import FactorioErrorParser
   ```

5. **`infra/llm/initial_state_generator.py`** (old file):
   ```python
   from FactoryVerse.infra.llm.tech_recipe_prompt import ...
   from FactoryVerse.infra.llm.categorical_references import ...
   ```

6. **`infra/llm/agent_orchestrator.py`** (old file):
   ```python
   from FactoryVerse.infra.llm.client import PrimeIntellectClient
   from FactoryVerse.infra.llm.trajectory_manager import TrajectoryManager
   from FactoryVerse.infra.llm.tool_validator import ToolValidator
   from FactoryVerse.infra.llm.console_output import ConsoleOutput
   ```

### 3. Duplicate Implementations ❌

**Both old and new versions exist:**

- `infra/llm/agent_orchestrator.py` (old) vs `llm/orchestrator.py` (new)
- `infra/llm/trajectory_manager.py` (old) vs `llm/trajectory.py` (new)
- `infra/llm/client.py` (old) vs `llm/client/` (new)

**Which one is being used?**
- CLI uses `llm/orchestrator.py` ✅
- But old files still exist and could be accidentally imported ❌

### 4. Backward Compat Shim Should Be Removed ❌

**`infra/llm/boilerplate/__init__.py`** exists as a backward compat shim, BUT:
- **No backward compat shims** - this is an anti-pattern for this codebase
- The entire `infra/llm/boilerplate/` directory (including `__init__.py`) should be removed
- All imports should use `infra/boilerplate/` directly

---

## What's Working ✅

1. **New module structure exists:**
   - `infra/execution/` ✅
   - `infra/session/` ✅
   - `infra/boilerplate/` ✅
   - `infra/output/` ✅
   - `llm/` ✅
   - `llm/client/` ✅
   - `llm/prompts/` ✅
   - `llm/context/` ✅

2. **CLI commands implemented:**
   - `fv prompts generate` ✅
   - `fv prompts api` ✅
   - `fv prompts schema` ✅
   - `fv agent` ✅

3. **New implementations are being used:**
   - `llm/orchestrator.py` is used by CLI ✅
   - `llm/client/` abstraction is used ✅

---

## Summary of Issues

### Critical Issues ❌

1. **`infra/llm/` directory should be removed** - contains duplicate/old implementations
2. **Multiple files still import from `infra/llm/`** - should use new paths
3. **Old implementation files still exist** - risk of accidental imports

### Medium Issues ⚠️

1. **Some files have extra modules** not in plan (e.g., `infra/session/lifecycle.py`, `infra/output/web.py`) - acceptable if intentional

### Low Issues ✅

1. **Extra modules** - not harmful, just not in original plan

---

## Cleanup Plan

**Status:** Phase 6 migration is complete per `INFRA_REFACTOR_PROGRESS.md`. The stale files in `infra/llm/` are temporary migration artifacts that should now be removed.

### Step 1: Fix Imports (Before Deletion)

Update all files importing from old paths to use new paths:

1. **`infra/execution/jupyter.py`**:
   ```python
   # OLD:
   from FactoryVerse.infra.llm.output_compressor import OutputCompressor
   from FactoryVerse.infra.llm.factorio_error_parser import FactorioErrorParser
   
   # NEW:
   from FactoryVerse.llm.context.compressor import OutputCompressor
   from FactoryVerse.infra.output.error_parser import FactorioErrorParser
   ```

2. **`mcp_server/server.py`**:
   ```python
   # OLD:
   from FactoryVerse.infra.llm.boilerplate import Scope
   from FactoryVerse.infra.llm.boilerplate.mcp import mcp_create_session
   
   # NEW:
   from FactoryVerse.infra.boilerplate import Scope
   from FactoryVerse.infra.boilerplate.mcp import mcp_create_session
   ```

3. **`infra/session/session.py`**:
   ```python
   # OLD:
   from FactoryVerse.infra.llm.boilerplate import Scope
   
   # NEW:
   from FactoryVerse.infra.boilerplate import Scope
   ```

4. **`agent_runtime.py`** (if still needed):
   ```python
   # OLD:
   from FactoryVerse.infra.llm.output_compressor import OutputCompressor
   from FactoryVerse.infra.llm.factorio_error_parser import FactorioErrorParser
   
   # NEW:
   from FactoryVerse.llm.context.compressor import OutputCompressor
   from FactoryVerse.infra.output.error_parser import FactorioErrorParser
   ```

### Step 2: Delete Stale Files

Once imports are fixed, delete all stale files:

**Delete entire `infra/llm/` directory:**
- `infra/llm/__init__.py`
- `infra/llm/agent_orchestrator.py`
- `infra/llm/trajectory_manager.py`
- `infra/llm/client.py`
- `infra/llm/tool_validator.py`
- `infra/llm/output_compressor.py`
- `infra/llm/initial_state_generator.py`
- `infra/llm/tech_recipe_prompt.py`
- `infra/llm/categorical_references.py`
- `infra/llm/console_output.py` (already moved to `infra/output/`)
- `infra/llm/factorio_error_parser.py` (already moved to `infra/output/`)
- `infra/llm/session_manager.py` (functionality moved to `infra/session/`)
- `infra/llm/boilerplate.py` (functionality moved to `infra/boilerplate/`)
- **Entire `infra/llm/boilerplate/` directory** (including `__init__.py` - no backward compat shims)

### Step 3: Verification

1. **Search for remaining imports:**
   ```bash
   grep -r "from FactoryVerse.infra.llm" src/
   grep -r "import.*infra.llm" src/
   ```

2. **Run tests** to ensure nothing breaks

3. **Update documentation** to reflect final clean structure

---

## Final State Goal

After cleanup, the structure should match the plan exactly:

```
FactoryVerse/
├── infra/
│   ├── boilerplate/     # ✅ Domain loading
│   ├── execution/       # ✅ Execution environments
│   ├── session/         # ✅ Session management
│   ├── output/          # ✅ Generic output utilities
│   └── (no llm/ dir)    # ✅ Removed entirely
│
└── llm/                 # ✅ LLM-specific layer
    ├── client/          # ✅ LLM client abstraction
    ├── orchestrator.py  # ✅ Agent orchestration
    ├── trajectory.py    # ✅ Trajectory management
    ├── context/         # ✅ Context management
    └── prompts/         # ✅ Prompt generation
```

**No backward compatibility shims. No duplicate implementations. Clean imports.**
