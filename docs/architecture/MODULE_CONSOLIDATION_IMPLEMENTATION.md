# Module Consolidation Implementation Plan

## Scope Summary

- **197 Python files** to relocate
- **315 import statements** to update
- **6 entry points** in pyproject.toml to update

---

## Phase 0: Safe Deletions (No Import Changes)

### Delete Dead Files

```bash
# Empty file, no imports
rm src/FactoryVerse/agent/infra/factory_context.py

# Unused debug script (standalone, no imports)
rm src/FactoryVerse/verify_dsl_runner.py
```

### Update `agent/infra/__init__.py`

Remove `factory_context` from docstring.

---

## Phase 1: File-by-File Mapping

### Legend
- `→` = Move file
- `(stays)` = No change
- `DELETE` = Remove

---

### 1.1 Top-Level Files

| Current | Destination | Import Change |
|---------|-------------|---------------|
| `cli.py` | `interfaces/cli/legacy.py` | `FactoryVerse.cli` → `FactoryVerse.interfaces.cli.legacy` |
| `cli_v2.py` | `interfaces/cli/main.py` | `FactoryVerse.cli_v2` → `FactoryVerse.interfaces.cli.main` |
| `config.py` | MERGE into `environment/config.py` | `FactoryVerse.config` → `FactoryVerse.environment.config` |
| `agent_runtime.py` | `environment/agent_runtime.py` | `FactoryVerse.agent_runtime` → `FactoryVerse.environment.agent_runtime` |
| `runtime.py` | `environment/runtime.py` | `FactoryVerse.runtime` → `FactoryVerse.environment.runtime` |
| `prototype_data.py` | `domain/factory/prototype_data.py` | `FactoryVerse.prototype_data` → `FactoryVerse.domain.factory.prototype_data` |
| `verify_dsl_runner.py` | DELETE (unused debug script) | - |
| `__init__.py` | (stays) | - |

---

### 1.2 `agent/` → `domain/agent/`

**48 imports affected**

| Current | Destination |
|---------|-------------|
| `agent/__init__.py` | `domain/agent/__init__.py` |
| `agent/models.py` | `domain/agent/models.py` |
| `agent/placement_hints.py` | `domain/agent/placement_hints.py` |
| `agent/remote_view.py` | `domain/agent/remote_view.py` |
| `agent/reachable_view.py` | `domain/agent/reachable_view.py` |
| `agent/event_stream.py` | `domain/agent/event_stream.py` |
| `agent/ghost_builder.py` | `domain/agent/ghost_builder.py` |
| `agent/core/` | `domain/agent/core/` (entire directory) |
| `agent/embodied_actions/` | `domain/agent/embodied_actions/` (entire directory) |
| `agent/infra/rcon_handler.py` | `domain/agent/infra/rcon_handler.py` |
| `agent/infra/async_listener.py` | `domain/agent/infra/async_listener.py` |
| `agent/infra/__init__.py` | `domain/agent/infra/__init__.py` |
| `agent/infra/factory_context.py` | DELETE |

**Import pattern:**
```
FactoryVerse.agent.X → FactoryVerse.domain.agent.X
```

---

### 1.3 `agent/infra/snapshot/` → Split into TWO locations

**Snapshot Domain Types** → `domain/snapshot/`

| Current | Destination |
|---------|-------------|
| `agent/infra/snapshot/types.py` | `domain/snapshot/types.py` |

**Snapshot RCON Adapter** → `domain/snapshot/`

| Current | Destination |
|---------|-------------|
| `infra/remote_adapters/map_snapshot.py` | `domain/snapshot/adapter.py` |

**DuckDB Implementation** → `domain/infra/duckdb/`

| Current | Destination |
|---------|-------------|
| `agent/infra/snapshot/__init__.py` | `domain/infra/duckdb/__init__.py` |
| `agent/infra/snapshot/database.py` | `domain/infra/duckdb/database.py` |
| `agent/infra/snapshot/loader.py` | `domain/infra/duckdb/loader.py` |
| `agent/infra/snapshot/sync.py` | `domain/infra/duckdb/sync.py` |
| `agent/infra/snapshot/query.py` | `domain/infra/duckdb/query.py` |
| `agent/infra/snapshot/schema_definitions.py` | `domain/infra/duckdb/schema_definitions.py` |
| `agent/infra/snapshot/snapshot.py` | `domain/infra/duckdb/snapshot.py` |
| `agent/infra/snapshot/db/` | `domain/infra/duckdb/db/` (entire hierarchy) |

**Import patterns:**
```
FactoryVerse.agent.infra.snapshot.types → FactoryVerse.domain.snapshot.types
FactoryVerse.agent.infra.snapshot.X → FactoryVerse.domain.infra.duckdb.X
FactoryVerse.infra.remote_adapters.MapSnapshotInterface → FactoryVerse.domain.snapshot.MapSnapshotInterface
```

---

### 1.4 `factory/` → `domain/factory/`

**93 imports affected** (highest impact)

| Current | Destination |
|---------|-------------|
| `factory/` | `domain/factory/` (entire hierarchy preserved) |

Subdirectories:
- `factory/entity/` → `domain/factory/entity/`
- `factory/entity/capabilities/` → `domain/factory/entity/capabilities/`
- `factory/entity/implementations/` → `domain/factory/entity/implementations/`
- `factory/item/` → `domain/factory/item/`
- `factory/recipe/` → `domain/factory/recipe/`
- `factory/resource/` → `domain/factory/resource/`
- `factory/technology/` → `domain/factory/technology/`

**Import pattern:**
```
FactoryVerse.factory.X → FactoryVerse.domain.factory.X
```

---

### 1.5 `scenarios/` → `domain/scenarios/`

**5 imports affected**

| Current | Destination |
|---------|-------------|
| `scenarios/` | `domain/scenarios/` (entire directory) |
| `testing/test_ground.py` | `domain/scenarios/test_ground.py` |
| `testing/__init__.py` | DELETE (re-export from domain/scenarios) |

**Import patterns:**
```
FactoryVerse.scenarios.X → FactoryVerse.domain.scenarios.X
FactoryVerse.testing.TestGroundHelper → FactoryVerse.domain.scenarios.TestGroundHelper
```

---

### 1.6 `tasks/` → `domain/tasks/`

**4 imports affected**

| Current | Destination |
|---------|-------------|
| `tasks/` | `domain/tasks/` (entire hierarchy) |

**Import pattern:**
```
FactoryVerse.tasks.X → FactoryVerse.domain.tasks.X
```

---

### 1.7 `llm/` → `infra/llm/`

**26 imports affected**

| Current | Destination |
|---------|-------------|
| `llm/` | `infra/llm/` (entire hierarchy) |

Subdirectories:
- `llm/client/` → `infra/llm/client/`
- `llm/context/` → `infra/llm/context/`
- `llm/prompts/` → `infra/llm/prompts/`

**Import pattern:**
```
FactoryVerse.llm.X → FactoryVerse.infra.llm.X
```

---

### 1.8 `infra/remote_adapters/` → Split

| Current | Destination |
|---------|-------------|
| `infra/remote_adapters/base.py` | `domain/infra/adapters/base.py` |
| `infra/remote_adapters/agent.py` | `domain/agent/adapter.py` |
| `infra/remote_adapters/admin.py` | `domain/agent/admin.py` |
| `infra/remote_adapters/map_snapshot.py` | `domain/snapshot/adapter.py` |
| `infra/remote_adapters/__init__.py` | DELETE |

**Import patterns:**
```
FactoryVerse.infra.remote_adapters.base → FactoryVerse.domain.infra.adapters.base
FactoryVerse.infra.remote_adapters.AgentInterface → FactoryVerse.domain.agent.AgentInterface
FactoryVerse.infra.remote_adapters.AdminInterface → FactoryVerse.domain.agent.AdminInterface
FactoryVerse.infra.remote_adapters.MapSnapshotInterface → FactoryVerse.domain.snapshot.MapSnapshotInterface
```

---

### 1.9 `infra/` (Stays, with LLM absorbed)

| Current | Destination |
|---------|-------------|
| `infra/docker/` | (stays) |
| `infra/execution/` | (stays) |
| `infra/output/` | (stays) |
| `infra/services/` | (stays) |
| `infra/session/` | (stays) |
| `infra/udp_dispatcher.py` | (stays) |
| `infra/instance_manager.py` | (stays) |
| `infra/rcon_helper.py` | (stays) |
| `infra/data_dump.py` | (stays) |
| `infra/factorio_client_setup.py` | (stays) |
| `infra/factorio_client_manager.py` | (stays) |
| `infra/__init__.py` | (stays) |

---

### 1.10 `ui/` → `interfaces/ui/`

**19 imports affected**

| Current | Destination |
|---------|-------------|
| `ui/` | `interfaces/ui/` (entire hierarchy) |

**Import pattern:**
```
FactoryVerse.ui.X → FactoryVerse.interfaces.ui.X
```

---

### 1.11 `mcp_server/` → `interfaces/mcp/`

**1 import affected**

| Current | Destination |
|---------|-------------|
| `mcp_server/` | `interfaces/mcp/` (entire directory) |

**Import pattern:**
```
FactoryVerse.mcp_server.X → FactoryVerse.interfaces.mcp.X
```

---

### 1.12 `docs/` → `utils/docs/`

**20 imports affected**

| Current | Destination |
|---------|-------------|
| `docs/` | `utils/docs/` (entire hierarchy) |

**Import pattern:**
```
FactoryVerse.docs.X → FactoryVerse.utils.docs.X
```

---

### 1.13 `environment/` (Stays, absorbs config)

| Current | Destination |
|---------|-------------|
| `environment/` | (stays) |
| `config.py` | MERGE into `environment/config.py` |

**Config Merge Strategy:**

Current state:
- `config.py` = `FactoryVerseConfig` (Pydantic settings from .env: RCON ports, paths, Docker)
- `environment/config.py` = Environment enums + configs that IMPORT `FactoryVerseConfig`

Merge approach:
1. Move contents of `config.py` into `environment/config.py` (at top of file)
2. Delete top-level `config.py`
3. Update all `from FactoryVerse.config import` → `from FactoryVerse.environment.config import`

This makes `environment/config.py` the single source of truth for all configuration.

---

### 1.14 `utils/` (Stays, absorbs docs)

| Current | Destination |
|---------|-------------|
| `utils/` | (stays) |
| `docs/` → | `utils/docs/` |

---

## Phase 2: Import Update Strategy

### Option A: sed-based (Fast, Risky)

```bash
# Run from src/FactoryVerse and tests directories

# factory → domain.factory (93 occurrences)
find . -name "*.py" -exec sed -i '' 's/from FactoryVerse\.factory\./from FactoryVerse.domain.factory./g' {} \;
find . -name "*.py" -exec sed -i '' 's/import FactoryVerse\.factory\./import FactoryVerse.domain.factory./g' {} \;

# agent → domain.agent (48 occurrences)
find . -name "*.py" -exec sed -i '' 's/from FactoryVerse\.agent\./from FactoryVerse.domain.agent./g' {} \;

# llm → infra.llm (26 occurrences)
find . -name "*.py" -exec sed -i '' 's/from FactoryVerse\.llm\./from FactoryVerse.infra.llm./g' {} \;

# config → environment.config (21 occurrences)
find . -name "*.py" -exec sed -i '' 's/from FactoryVerse\.config /from FactoryVerse.environment.config /g' {} \;
find . -name "*.py" -exec sed -i '' 's/from FactoryVerse\.config$/from FactoryVerse.environment.config/g' {} \;

# docs → utils.docs (20 occurrences)
find . -name "*.py" -exec sed -i '' 's/from FactoryVerse\.docs\./from FactoryVerse.utils.docs./g' {} \;

# ui → interfaces.ui (19 occurrences)
find . -name "*.py" -exec sed -i '' 's/from FactoryVerse\.ui\./from FactoryVerse.interfaces.ui./g' {} \;

# scenarios → domain.scenarios (5 occurrences)
find . -name "*.py" -exec sed -i '' 's/from FactoryVerse\.scenarios\./from FactoryVerse.domain.scenarios./g' {} \;

# tasks → domain.tasks (4 occurrences)
find . -name "*.py" -exec sed -i '' 's/from FactoryVerse\.tasks\./from FactoryVerse.domain.tasks./g' {} \;

# testing → domain.scenarios (3 occurrences)
find . -name "*.py" -exec sed -i '' 's/from FactoryVerse\.testing /from FactoryVerse.domain.scenarios /g' {} \;

# mcp_server → interfaces.mcp (1 occurrence)
find . -name "*.py" -exec sed -i '' 's/from FactoryVerse\.mcp_server/from FactoryVerse.interfaces.mcp/g' {} \;

# remote_adapters splits (complex - needs multiple patterns)
find . -name "*.py" -exec sed -i '' 's/from FactoryVerse\.infra\.remote_adapters import MapSnapshotInterface/from FactoryVerse.domain.snapshot import MapSnapshotInterface/g' {} \;
find . -name "*.py" -exec sed -i '' 's/from FactoryVerse\.infra\.remote_adapters import AgentInterface/from FactoryVerse.domain.agent import AgentInterface/g' {} \;
find . -name "*.py" -exec sed -i '' 's/from FactoryVerse\.infra\.remote_adapters import AdminInterface/from FactoryVerse.domain.agent import AdminInterface/g' {} \;

# snapshot split
find . -name "*.py" -exec sed -i '' 's/from FactoryVerse\.agent\.infra\.snapshot\.types/from FactoryVerse.domain.snapshot.types/g' {} \;
find . -name "*.py" -exec sed -i '' 's/from FactoryVerse\.agent\.infra\.snapshot\./from FactoryVerse.domain.infra.duckdb./g' {} \;
```

**Pros**: Fast, scriptable
**Cons**: May miss edge cases, no validation

---

### Option B: Python Script with AST (Safe, Slower)

Create a migration script that:
1. Parses each file with `ast`
2. Identifies import statements
3. Applies mapping rules
4. Validates syntax after change
5. Reports any ambiguous cases

**Pros**: Safe, handles edge cases, validates
**Cons**: More complex to write

---

### Option C: Hybrid (Recommended)

1. **sed for bulk changes** (simple patterns)
2. **Manual review** for complex cases (remote_adapters splits, snapshot splits)
3. **Validation pass** with `python -m py_compile` or pytest import check

---

## Phase 3: Entry Point Updates

### pyproject.toml Changes

```toml
[project.scripts]
# Full name (primary) - v2 Environment-based CLI
factoryverse = "FactoryVerse.interfaces.cli.main:main"
# Short alias for convenience
fv = "FactoryVerse.interfaces.cli.main:main"
# Legacy CLI (v1) - for backwards compatibility
fv-legacy = "FactoryVerse.interfaces.cli.legacy:main"
# MCP server - development
factoryverse-mcp = "FactoryVerse.interfaces.mcp:main"
# MCP server - gameplay
factoryverse-play = "FactoryVerse.interfaces.mcp.gameplay_server:main"
# UI entry point
fv-ui = "FactoryVerse.interfaces.ui.app:run_app"
```

---

## Phase 4: Execution Order

### Step 1: Create Directory Structure
```bash
mkdir -p src/FactoryVerse/domain/{agent,factory,snapshot,scenarios,tasks,infra/{adapters,duckdb}}
mkdir -p src/FactoryVerse/interfaces/{cli,mcp,ui}
```

### Step 2: Move Files (git mv for history)
```bash
# domain/factory (largest, do first)
git mv src/FactoryVerse/factory src/FactoryVerse/domain/factory

# domain/agent
git mv src/FactoryVerse/agent src/FactoryVerse/domain/agent

# domain/scenarios
git mv src/FactoryVerse/scenarios src/FactoryVerse/domain/scenarios
git mv src/FactoryVerse/testing/test_ground.py src/FactoryVerse/domain/scenarios/

# domain/tasks
git mv src/FactoryVerse/tasks src/FactoryVerse/domain/tasks

# infra/llm
git mv src/FactoryVerse/llm src/FactoryVerse/infra/llm

# interfaces/ui
git mv src/FactoryVerse/ui src/FactoryVerse/interfaces/ui

# interfaces/mcp
git mv src/FactoryVerse/mcp_server src/FactoryVerse/interfaces/mcp

# interfaces/cli
mkdir -p src/FactoryVerse/interfaces/cli
git mv src/FactoryVerse/cli.py src/FactoryVerse/interfaces/cli/legacy.py
git mv src/FactoryVerse/cli_v2.py src/FactoryVerse/interfaces/cli/main.py

# utils/docs
git mv src/FactoryVerse/docs src/FactoryVerse/utils/docs
```

### Step 3: Handle Splits (Manual)
- Split `agent/infra/snapshot/` → `domain/snapshot/` + `domain/infra/duckdb/`
- Split `infra/remote_adapters/` → `domain/agent/`, `domain/snapshot/`, `domain/infra/adapters/`

### Step 4: Update Imports (sed)
Run sed commands from Phase 2.

### Step 5: Update Entry Points
Edit `pyproject.toml`.

### Step 6: Create `__init__.py` Files
Ensure all new directories have proper `__init__.py` with exports.

### Step 7: Validate
```bash
# Syntax check all files
python -m compileall src/FactoryVerse

# Run tests
pytest tests/ -x --tb=short

# Check entry points work
fv --help
factoryverse-mcp --help
```

---

## Phase 5: Backward Compatibility (Optional)

Create re-export stubs in old locations for gradual migration:

```python
# src/FactoryVerse/factory/__init__.py (stub)
"""Deprecated: Use FactoryVerse.domain.factory instead."""
import warnings
warnings.warn(
    "FactoryVerse.factory is deprecated. Use FactoryVerse.domain.factory",
    DeprecationWarning,
    stacklevel=2
)
from FactoryVerse.domain.factory import *
```

**Recommendation**: Skip this. Do a clean break with one PR. Tests will catch any missed imports.

---

## Risk Assessment

| Module | Imports | Risk | Notes |
|--------|---------|------|-------|
| factory | 93 | HIGH | Most imports, but simple pattern |
| infra | 59 | MEDIUM | Some stay, some move |
| agent | 48 | MEDIUM | Snapshot split adds complexity |
| llm | 26 | LOW | Simple move |
| config | 21 | MEDIUM | Merge with existing environment/config.py |
| docs | 20 | LOW | Simple move |
| ui | 19 | LOW | Simple move |
| remote_adapters | ~10 | HIGH | Complex split into 3 locations |
| snapshot | ~10 | HIGH | Complex split into 2 locations |

---

## Validation Checklist

- [ ] All 197 Python files accounted for
- [ ] All 315 imports updated
- [ ] All 6 entry points updated
- [ ] `python -m compileall src/FactoryVerse` passes
- [ ] `pytest tests/` passes
- [ ] `fv --help` works
- [ ] `factoryverse-mcp --help` works
- [ ] `fv-ui` works
- [ ] No circular import errors
