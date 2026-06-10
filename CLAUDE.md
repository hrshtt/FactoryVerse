# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: FactoryVerse

AI agent research platform for Factorio. Two Lua mods + Python orchestration + DuckDB spatial queries.

## Core Mental Model

**Environment module (`src/FactoryVerse/environment/`) is THE canonical orchestrator.** CLI, MCP server, tests, UI are just entry points composing the same 6-tier stack:

```
Tier 6: Interaction      (Autonomous / Assisted / MCP)
Tier 5: Specification    (System prompt, task definition)
Tier 4: Runtime          (Agent modules, views, DuckDB)
Tier 3: Python Infra     (RCON + UDP connections)
Tier 2: Settings         (Scenario, save file)
Tier 1: Factorio Infra   (Client/Server + mods)
```

Use `Environment.for_testing()`, `Environment.for_agent()`, `Environment.for_mcp()`.

## The Three Mods

| Mod | Purpose |
|-----|---------|
| `fv_embodied_agent` | Replicates human player affordances - actions a human can perform via GUI (walk, place, craft, mine). 30+ remote interface methods. |
| `fv_snapshot` | Solves multi-agent read scaling - writes game state to disk without blocking each agent's read. DuckDB provides queryable equivalent of human's visual map access. Also registers `entities`/`map`/`research` interfaces. |
| `fv_placement_hints` | Placement reasoning, exposed via the `placement_hints` remote interface. (Confirmed loaded at runtime 2026-06-10.) |

See `docs/RUNTIME_PLAYBOOK.md` for RCON access mechanics and `docs/FLOOR_CERTIFICATION.md` for what is actually verified vs assumed.

**Key insight**: Human players have full map visibility + GUI actions. These mods replicate both for agents.

## Factorio Runtime Constraints

- **Frozen Runtime**: Factorio loads mods in stages (settings → data → control) then freezes. After loading:
  - Cannot `require()` modules dynamically
  - Cannot register new custom events
  - Cannot modify prototype data
  - All module-level state is immutable
- **Mods vs Scenarios**: Mods extend data tables, have isolated runtimes. Scenarios are script-only. RCON executes in scenario runtime (NOT mod runtime).
- **No `require` from RCON**: RCON runs in scenario context, not mod context. Must use `remote.call()` to access mod functions. All mod functionality exposed via remote interfaces.
- **Lua blocks simulation**: 60 ticks/second target. Heavy computation slows ALL mods/clients.
- **RCON completes in one tick**: Cannot span ticks → need UDP for async action completion.
- **Snapshot batching**: Distributes work (100 entities/tick) to avoid freezing.
- **Hot-reload**: Scenarios yes (via `--watch`), mods no (full restart required to pick up Lua changes).
- **Placement validation**: ALWAYS use `build_check_type = defines.build_check_type.manual` for `can_place_entity`. The default (script) bypasses placement rules and creates invalid states.

## Prototype Data Pipeline

```
fv_filters.yaml → factorio-data-dump.json → PrototypeDataManager (singleton) → all consumers
```

- Mods can modify existing prototypes → must extract from running Factorio
- `fv_filters.yaml` scopes to ~100-200 entities (excludes military, trains, circuits, space)
- Singleton ensures DuckDB schemas, Factory Objects, prompts all see same filtered data
- Regenerate: `uv run fv data refresh`

## Commands

```bash
# Install
uv pip install -e . && uv sync --group dev

# Test
pytest                                    # all tests
pytest tests/actions/test_crafting.py -v  # specific file

# Validate (no Factorio needed)
pytest tests/unit/test_documentation_coverage.py -v  # type system validation
uv run fv docs generate                              # regenerate API docs

# Run
uv run fv client start --scenario test-ground
uv run fv server start --num 1 --scenario test-ground --watch
uv run fv agent                                       # interactive agent mode
```

## Type System Validation

The type system is the research artifact. Run validation before committing:

```bash
pytest tests/unit/test_documentation_coverage.py::TestDocumentationIntegration::test_all_examples_valid_attributes -v
```

This catches doc/code drift (e.g., `patch.total_amount` when property is `patch.total`).

When adding new accessors or classes, update `src/FactoryVerse/docs/validators.py`:
- `ACCESSOR_RETURN_TYPES` - method → return type
- `_class_map` - type name → class for introspection
- `POLYMORPHIC_RETURN_TYPES` - context-dependent returns

## Key Directories

- `src/FactoryVerse/environment/` - Tiered orchestrator (start here)
- `src/FactoryVerse/agent/embodied_actions/` - Async action classes
- `src/FactoryVerse/agent/reachable_view.py` - Nearby entities (full access)
- `src/FactoryVerse/agent/remote_view.py` - Map-wide SQL queries (read-only)
- `src/fv_embodied_agent/` - Lua mod for agent control
- `src/fv_snapshot/` - Lua mod for game state serialization
- `tests/conftest.py` - Environment-based test fixtures

## Design Patterns

1. **Tiered Composition**: Environment orchestrates 6 tiers with explicit dependencies
2. **Dual-View System**: REACHABLE (nearby, mutate) vs REMOTE (map-wide, read-only)
3. **Async via UDP**: Walking/mining/crafting send UDP notifications on completion
4. **Database as Vision**: DuckDB spatial queries = agent equivalent of human's map screen
5. **Single Source of Truth**: PrototypeDataManager ensures all consumers see same filtered prototypes

## Entity Referencing

**NEVER use `unit_number` to reference entities.** Unit numbers are ephemeral and change based on save/load, entity recreation, and other factors.

Always reference entities by:
- **`entity_name` + `position`** - for specific entity lookup
- **`entity_type` + `position`** - for broader/categorical scans

This applies across all contexts: Python ↔ Lua, mod ↔ mod, RCON calls, DuckDB queries.

## Port Allocation

| Service | Server N | Client |
|---------|----------|--------|
| RCON | 27000+N | 27100 |
| Snapshot UDP | 34400+N | 34500 |
| Agent UDP | 34202+(N×10) | 34202+ |

## Known Issues

Stability claims live in `docs/FLOOR_CERTIFICATION.md` (executed checks only — prose doesn't count). Unsettled items pending their checks:

- Map DB on entity removal: code reads as handled (`sync.py`), this list previously said broken → settled by check L1.2 when run
- Mining resource entities (trees/rocks) needs verification
- Ghost placement not fully tested (check L2.5)
