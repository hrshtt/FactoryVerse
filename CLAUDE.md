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
- `fv_filters.yaml` scopes the prototype set (excludes military, trains, circuits, space). Counts are version-dependent — the current certified counts live in the L3.3 ledger row (docs/FLOOR_CERTIFICATION.md), and an engine-image bump VOIDS them until re-run
- Singleton ensures DuckDB schemas, Factory Objects, prompts all see same filtered data
- Regenerate (no `fv data refresh` command exists): one-shot dump from the current image, then prune. ⚠️ `--dump-data` force-loads ALL available mods (including DLC, ignoring mod-list) and persists re-enabled flags back to mod-list.json — remove the DLC data dirs in-container or the dump captures Space Age (live-verified 2026-06-11, L3.2):
  ```bash
  docker run --rm --platform linux/arm64 --entrypoint "" \
    -v "$HOME/Library/Application Support/factorio/mods":/opt/factorio/mods \
    -v /tmp/fv-dump-out:/opt/factorio/script-output \
    factoriotools/factorio:<version> /bin/sh -c \
    "rm -rf /opt/factorio/data/space-age /opt/factorio/data/quality /opt/factorio/data/elevated-rails && \
     /bin/box64 /opt/factorio/bin/x64/factorio --mod-directory /opt/factorio/mods --dump-data"
  cp /tmp/fv-dump-out/data-raw-dump.json .fv-output/server_0/
  uv run python -c "from FactoryVerse.infra.data_dump import refresh_data_dump; refresh_data_dump('server_0')"
  uv run python scripts/certification/check_L3_3.py   # re-earn L3.3 against the new dump
  ```

## Commands

```bash
# Install
uv pip install -e . && uv sync --group dev

# Test (offline; tests/actions + tests/sync have audited-unsound suites — see ledger Audit log)
uv run pytest tests/unit -q                           # the audited offline battery

# Validate (no Factorio needed)
pytest tests/unit/test_documentation_coverage.py -v   # type system validation
uv run python scripts/certification/check_L5_1.py     # namespace completeness
uv run fv docs generate                               # regenerate API docs

# Run
uv run fv client start --scenario lab-grid
uv run fv server start --num 1 --scenario lab-grid    # docker; --save <name> loads a save
uv run fv dev census --instance server_0              # ground-truth entity census
uv run fv agent                                       # interactive agent mode
```

## Type System Validation

The type system is the research artifact. Run validation before committing:

```bash
pytest tests/unit/test_documentation_coverage.py::TestDocumentationIntegration::test_all_examples_valid_attributes -v
```

This catches doc/code drift (e.g., `patch.total_amount` when property is `patch.total`).

When adding new accessors or classes, update `src/FactoryVerse/utils/docs/validators.py`:
- `ACCESSOR_RETURN_TYPES` - method → return type
- `_class_map` - type name → class for introspection
- `POLYMORPHIC_RETURN_TYPES` - context-dependent returns
- Unmapped accessor calls in documented examples now FAIL LOUDLY (L3.1b); either map them or add a rationale'd `UNMAPPED_ACCESSOR_SKIP_LIST` entry

## Key Directories

- `src/FactoryVerse/environment/` - Tiered orchestrator (start here)
- `src/FactoryVerse/game/agent/embodied_actions/` - Async action classes
- `src/FactoryVerse/game/agent/reachable_view.py` - Nearby entities (full access)
- `src/FactoryVerse/game/agent/remote_view.py` - Map-wide SQL queries (read-only)
- `src/fv_embodied_agent/` - Lua mod for agent control
- `src/fv_snapshot/` - Lua mod for game state serialization
- `scripts/certification/` - Check-runner harnesses (the ledger's executable half)
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
| Snapshot UDP | 34400 (mod default; socat forwards ONLY 34400 — do not repoint) | 34400 |
| Agent UDP | 34202–34211 (socat-forwarded range) | 34202+ |

See `docs/RUNTIME_PLAYBOOK.md` §1 for the live-verified connection facts; the playbook wins over this table on conflict.

## Known Issues

**Stability claims live in `docs/FLOOR_CERTIFICATION.md` (executed checks only — prose doesn't count). Do not trust this file, any doc, or memory for "X works" claims — look up the ledger row.** Issue tracking lives in `docs/EVAL_ISSUE_TRACKER.md`. **Live model-eval runs and the raw findings they surface live in `docs/runs/` (untracked; see its README)** — findings there are PROPOSED until adjudicated into the tracker; check it before running or analyzing an eval so known run-class issues aren't re-discovered. Still-open at last edit (2026-06-11): mining resource entities (trees/rocks) unverified; L2.4/L2.5/L4.5 harnesses drafted but not yet executed; L0.3 save/load and L3.2 dump-scope drift pending.
