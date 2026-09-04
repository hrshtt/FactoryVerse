# AGENTS.md

Guidance for coding agents working in this repository.

## What this is

FactoryVerse is a research platform for LLM agents playing Factorio: three Lua mods, a Python orchestration layer, and a DuckDB map model.

## Where the truth lives

- **`docs/CONSTITUTION.md`** — the decisions that shape what goes into the agent's hands and where it lives. Read it before proposing anything. A proposal that cannot be argued from its clauses is wrong, or a clause needs amending — say which.
- **`docs/architecture/*.md`** — the plans currently being worked toward (each is self-contained and states its own gates):
  - `API_AFFORDANCE_REDESIGN_DEFERRED.md` — parent plan: affordance decides ownership
  - `TURN_CONTRACT_DEFERRED.md` — what a turn is; upstream of most other plans
  - `HUD_PARTITION_DEFERRED_REFACTOR.md` — partially superseded 2026-08-29: craft/research stay in Python; join contract, mining rule and naming rule survive
  - `BELT_AFFORDANCE_DEFERRED_PLAN.md` — superseded by `TRANSPORT_CONNECTIVITY_PLAN.md`; kept for its teaching section
  - `TRANSPORT_CONNECTIVITY_PLAN.md` — belts, poles, pipes: derived structure, live simulation, no stored adjacency
  - `SNAPSHOT_SESSION_PLAN.md` — the snapshot mod keeps no storage; a consumer opens a named session and owns the ledger of what was written (designed 2026-09-04, not scheduled; supersedes the boot-report repairs)
  - `GHOST_SURFACE_DEFERRED.md` — ghosts as a map-view write surface
  - `NOTIFICATIONS_PRIMITIVE_DEFERRED.md` — notifications as a primitive (the `turn` stream half landed in Phase 2B; `action`/`entities`/`files` streams and the Lua census are unscheduled)
  - `SCENARIO_BOOT_CONTRACT_DEFERRED.md` — what a world boot is: scenario resolution, world settings, observer policy
  - `TIER_RENAME_PROPOSAL.md` — rename the environment tiers
  - `SCORER_MOD_PLAN.md` — a fourth mod that judges from the engine: reward, diagnostics, integrity (designed 2026-09-02, not scheduled)
  - `GOAL_SPECIFICATIONS_DEFERRED_INDEFINITELY.md` — goals as temporal-logic specs; a discussion record, deferred indefinitely and not in the scorer's scope
  - `ENTITY_SCOPE_PLAN.md` — one owner of what an entity is: scope derived from the technology tree, one manifest, one hash asserted from Lua, the map model and Python (designed 2026-09-02, not scheduled; precondition for robots)
  - `FACTORIOPEDIA_PLAN.md` — what the agent is told about the world and when: invariant prompt with the pre-science entities, a `factoriopedia` tool gated on live research, the unlock line in the report (designed 2026-09-03, not scheduled; depends on ENTITY_SCOPE)
- **`docs/EXECUTION.md`** — where the refactor stands: phases, what landed (with its commit and check), what is next. Update it on every commit that moves a phase.
- **The code and its checks.** Nothing else in this repo is an authority on whether something works. If you need to know, run the check. If there is no check, there is no claim.

There is deliberately no issue tracker, certification ledger, retro archive, or "known issues" list in the repo. External-harness transports (Codex, Hermes) were removed 2026-08-29 and are rebuilt only after the refactor; `fv run` is the sole interaction path. Past sessions' conclusions were removed on purpose; do not reconstruct them from memory.

## Layout

```
src/FactoryVerse/environment/   Orchestrator — composes the tiered stack; `EnvironmentConfig.for_run` is the one place a run is assembled
src/FactoryVerse/game/agent/    Agent-facing surface: embodied actions, reachable/remote views
src/FactoryVerse/game/factory/  Typed entity objects and prototype data
src/FactoryVerse/game/infra/    DuckDB map model, op log, loaders
src/FactoryVerse/infra/         RCON/UDP, Docker, LLM clients, sessions
src/FactoryVerse/evals/         Freeplay campaign supervisor: manifest, checkpoints, prejoin, stdio actor protocol (`fv campaign`)
src/FactoryVerse/dev/           Developer tooling (census)
src/fv_embodied_agent/          Lua mod: what a human at the keyboard can do
src/fv_snapshot/                Lua mod: game state → disk → DuckDB; entities/map/research interfaces
src/fv_placement_hints/         Lua mod: placement reasoning
src/factorio/                   Scenarios, mod-list, server config
tests/unit/                     Offline battery
tests/live/                     Contract tests against a running instance (skip offline)
```

## Commands

```bash
uv sync --group dev
uv run pytest tests/unit -q                       # offline
uv run pytest tests/live -q                       # needs a running instance
uv run fv client start --scenario lab-grid        # local client with mods
uv run fv server start --num 1 --scenario lab-grid
uv run fv run                                     # freeplay agent (auto-detects/launches an instance)
uv run fv run --task iron_plate_throughput        # verified task
uv run fv run --interactive                       # human-in-the-loop REPL
uv run fv docs generate                           # regenerate docs/for-llms/api_reference.md
uv run fv census                                  # ground-truth entity dump
uv run fv campaign --help                         # supervised campaigns (create/status/prejoin/launch)
```

`docs/system-prompt/*-template.md` is the runtime prompt input. `docs/for-llms/*` are generated snapshots of what the agent is shown (Tier 5 regenerates the same text in-process; `fv docs generate` rewrites only `api_reference.md`). They are agent inputs, not documentation for you.

## Factorio runtime constraints

- Mods load in stages (settings → data → control) and then freeze: no dynamic `require`, no new events, no prototype changes after load. Mod Lua changes need a full restart; scenarios hot-reload with `--watch`.
- RCON runs in the scenario runtime, not the mod runtime. Reach mod code only through `remote.call()`.
- An RCON call completes within one tick. Anything that spans ticks reports completion over UDP.
- Lua blocks the simulation. Heavy work is batched across ticks.
- `can_place_entity` must use `build_check_type = defines.build_check_type.manual`; the default bypasses placement rules.

## Entity referencing

Never use `unit_number` — it is ephemeral across save/load and recreation. Reference entities by `entity_name` + `position` (or `entity_type` + `position`) everywhere: Python ↔ Lua, mod ↔ mod, RCON, DuckDB.

## Prototype data

`fv_filters.yaml` scopes the prototype set. A running Factorio's `--dump-data` output is pruned by `FactoryVerse.infra.data_dump.refresh_data_dump` into the singleton `PrototypeDataManager` that every consumer (DuckDB schemas, entity objects, prompts) reads. `--dump-data` force-loads every mod in the mods directory; remove DLC data dirs in-container before dumping.

## Ports

| Service | Server N | Client |
|---|---|---|
| RCON | 27000+N | 27100 |
| Snapshot UDP | 34400 | 34400 |
| Agent UDP | 34202–34211 | 34202+ |

## Documentation validation

The typed agent surface is the research artifact. `tests/unit/test_documentation_coverage.py` fails on doc/code drift. When adding accessors or classes, update `src/FactoryVerse/utils/docs/validators.py` (`ACCESSOR_RETURN_TYPES`, `_class_map`, `POLYMORPHIC_RETURN_TYPES`).
