# FactoryVerse Module Consolidation Design

## Summary

This document captures the design decisions for restructuring FactoryVerse's top-level module organization. The goal is a cleaner separation of concerns that makes the codebase easier to explain, navigate, and extend.

---

## Current State (Pre-Consolidation)

```
FactoryVerse/
├── cli.py, cli_v2.py, config.py, agent_runtime.py, runtime.py, prototype_data.py
├── agent/
├── factory/
├── environment/
├── infra/
├── llm/
├── mcp_server/
├── ui/
├── scenarios/
├── tasks/
├── testing/
├── docs/
└── utils/
```

**Problems:**
1. **Scattered entry points**: CLI at top-level, MCP in `mcp_server/`, UI in `ui/`
2. **Unclear infra boundaries**: `llm/` separate from `infra/`, but both are infrastructure
3. **Orphaned modules**: `testing/` duplicates pattern from `scenarios/`
4. **No clear story**: 12+ top-level modules with unclear relationships
5. **Adapter location**: Remote adapters in `infra/remote_adapters/` instead of with their domain modules

---

## Proposed Structure

```
FactoryVerse/
├── domain/                   # Factorio knowledge (WHAT)
│   ├── infra/                # Domain-level infrastructure
│   │   ├── duckdb/           # DuckDB connection, query utilities
│   │   ├── rcon/             # RCON helpers for domain operations
│   │   └── adapters/
│   │       └── base.py       # Base adapter class (shared)
│   │
│   ├── agent/                # Agent interfaces
│   │   ├── adapter.py        # Agent lifecycle adapter (fv_embodied_agent)
│   │   ├── admin.py          # Admin interface adapter
│   │   ├── embodied_actions/
│   │   └── ...
│   │
│   ├── factory/              # Factory objects (entities, items, recipes)
│   │
│   ├── snapshot/             # Game state snapshot
│   │   ├── adapter.py        # Map snapshot adapter (fv_snapshot)
│   │   └── ...
│   │
│   ├── scenarios/            # Scenario adapters
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── lab_grid.py
│   │   └── test_ground.py    # ← absorbed from testing/
│   │
│   └── tasks/                # In-game verification affordances
│
├── infra/                    # Platform infrastructure (HOW to run)
│   ├── docker/               # Server management
│   ├── execution/            # Code execution environments
│   ├── llm/                  # LLM clients ← absorbed from top-level llm/
│   ├── services/
│   └── session/
│
├── interfaces/               # Entry points (HOW to access)
│   ├── cli/                  # ← absorbed from cli.py, cli_v2.py
│   ├── mcp/                  # ← absorbed from mcp_server/
│   └── ui/                   # ← absorbed from ui/
│
├── environment/              # Orchestration (GLUE)
│   ├── tiers/                # Tier definitions & contracts
│   └── config.py             # Cross-cutting configuration
│
├── docs/                     # Documentation generation
└── utils/                    # Utilities
```

---

## Design Principles

### 1. Four Pillars

| Pillar | Purpose | Question it answers |
|--------|---------|---------------------|
| `domain/` | Factorio knowledge | "What does FactoryVerse know about?" |
| `infra/` | Platform infrastructure | "What external systems does FactoryVerse need?" |
| `interfaces/` | Entry points | "How do users access FactoryVerse?" |
| `environment/` | Orchestration | "How do all the pieces work together?" |

### 2. Two Kinds of Infrastructure

- **`infra/`** = Platform infrastructure for FactoryVerse to exist (Docker, LLM clients, execution)
- **`domain/infra/`** = Opinionated infrastructure for implementing domain logic (DuckDB, RCON helpers)

DuckDB is not necessary for FactoryVerse to run - it's an opinionated choice for implementing domain queries. Hence it lives in `domain/infra/`, not `infra/`.

### 3. Adapters Live With Their Domain

Each Lua mod/interface has a corresponding Python adapter. That adapter lives with its domain module, not in a generic bucket:

| Lua Interface | Domain Module | Adapter Location |
|---------------|---------------|------------------|
| `fv_embodied_agent` (agent) | `domain/agent/` | `domain/agent/adapter.py` |
| `fv_embodied_agent` (admin) | `domain/agent/` | `domain/agent/admin.py` |
| `fv_snapshot` | `domain/snapshot/` | `domain/snapshot/adapter.py` |
| `lab_grid` scenario | `domain/scenarios/` | `domain/scenarios/lab_grid.py` |
| `test_ground` scenario | `domain/scenarios/` | `domain/scenarios/test_ground.py` |

The base adapter class lives in `domain/infra/adapters/base.py` as shared tooling.

### 4. Environment is Lean

Environment is the **orchestrator**, not a mega-module. It owns:
- Tier definitions and contracts
- Cross-cutting configuration
- The glue that makes domain + infra + interfaces work together

It does NOT own infra or interfaces - it coordinates them.

### 5. Hierarchical Coupling

Prefer importing from higher-level modules down, not reaching into sibling's internals:

```python
# Good: domain modules use domain/infra
from domain.infra.duckdb import QueryEngine
from domain.infra.adapters.base import BaseAdapter

# Bad: reaching into sibling's internals
from domain.agent.infra import something  # Don't do this
```

---

## Explaining FactoryVerse

> "FactoryVerse is a platform to let LLMs play Factorio.
>
> **Domain** embeds Factorio knowledge: agent interfaces for what agents can do, factory objects for what exists in the world, snapshots for game state, scenarios for specific setups, and tasks for verification.
>
> **Infra** handles external systems: Docker for servers, LLM clients for model interaction, execution environments for running code.
>
> **Interfaces** are entry points: CLI for command-line usage, MCP server for tool integration, UI for visual interaction.
>
> **Environment** is the glue: it defines contracts between modules and orchestrates the 6-tier stack so everything works together."

---

## Migration Plan

### Phase 1: Create Structure
1. Create `domain/`, `interfaces/` directories
2. Create `domain/infra/`, `domain/snapshot/` directories

### Phase 2: Move Domain Modules
1. Move `agent/` → `domain/agent/`
2. Move `factory/` → `domain/factory/`
3. Move `scenarios/` → `domain/scenarios/`
4. Move `tasks/` → `domain/tasks/`
5. Move `testing/test_ground.py` → `domain/scenarios/test_ground.py`
6. Delete empty `testing/`

### Phase 3: Move Infrastructure
1. Move `llm/` → `infra/llm/`
2. Extract `infra/remote_adapters/base.py` → `domain/infra/adapters/base.py`
3. Move `infra/remote_adapters/agent.py` → `domain/agent/adapter.py`
4. Move `infra/remote_adapters/admin.py` → `domain/agent/admin.py`
5. Move `infra/remote_adapters/map_snapshot.py` → `domain/snapshot/adapter.py`
6. Delete empty `infra/remote_adapters/`

### Phase 4: Move Interfaces
1. Move `cli.py`, `cli_v2.py` → `interfaces/cli/`
2. Move `mcp_server/` → `interfaces/mcp/`
3. Move `ui/` → `interfaces/ui/`

### Phase 5: Consolidate Top-Level Files
1. Move `config.py` → `environment/config.py`
2. Evaluate `agent_runtime.py`, `runtime.py`, `prototype_data.py` for proper homes

### Phase 6: Update Imports
1. Update all import statements across codebase
2. Update `pyproject.toml` entry points
3. Update tests

---

## Open Questions

1. **Where does `prototype_data.py` live?**
   - Option A: `domain/factory/` (it's about factory prototypes)
   - Option B: `domain/infra/` (it's data loading infrastructure)

2. **What about `agent_runtime.py` vs `runtime.py`?**
   - Need to understand the distinction and find proper homes

3. **Should `docs/` move under `domain/` or stay top-level?**
   - It generates documentation about domain objects
   - But it's also tooling, not domain knowledge itself

---

## Appendix: Evolution of Thinking

### Attempt 1: Environment Owns Everything
We considered making Environment own both `infra/` and `interfaces/`. This made Environment a mega-module ("the platform") but blurred single responsibility.

### Attempt 2: Environment + Domain (Two Pillars)
We then tried collapsing everything into two pillars: Environment (how) and Domain (what). Simpler to explain but Environment became too large.

### Final: Four Pillars
We settled on four pillars with clear responsibilities:
- Domain = knowledge
- Infra = external systems
- Interfaces = entry points
- Environment = orchestration

This keeps Environment lean as "just the glue" while giving each concern a clear home.
