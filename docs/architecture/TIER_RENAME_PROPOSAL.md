# Rename the environment layers to bespoke names

**Status: DEFERRED.** A mechanical rename with no agent-visible surface. Orthogonal to the other five plans and to `docs/CONSTITUTION.md` — no clause bears on it. Recorded so its silence is not mistaken for an oversight.

## The proposal

`env.tier1` … `env.tier6` (and `Tier1Factorio` …, `tier1_factorio.py` …) should be renamed to describe what each layer owns. Keep the `Tier` IntEnum and its integer ordering as the dependency and initialization spine.

The ordering machinery is doing real work — prerequisites check downward, resets cascade upward, `initialize(up_to=…)` walks the sequence, and `IntEnum` makes lower-and-higher a comparison. **The numbers on call-site names are not.**

| Now | Owns | Proposed |
|-----|------|----------|
| `env.tier1` / `Tier1Factorio` | Factorio processes, docker, mods | `env.factorio` |
| `env.tier2` / `Tier2Settings` | scenario and save selection | `env.settings` |
| `env.tier3` / `Tier3Python` | RCON and UDP connections | `env.connections` |
| `env.tier4` / `Tier4Runtime` | agent modules, views, DuckDB | `env.runtime` |
| `env.tier5` / `Tier5Specification` | system prompt, task definition | `env.spec` |
| `env.tier6` / `Tier6Interaction` | interaction loop | `env.interaction` |

## Why

- **Usage is inverted against legibility.** `tier3` and `tier4` dominate call sites by a wide margin, and those are exactly the two whose numbers say nothing. `env.tier3.rcon_helper` and `env.tier4.remote_view` are the workhorses.
- **Every reader pays a decoder-table tax**, including every agent session — which is why AGENTS.md has to carry the tier table at all.
- **Numbers are insertion-brittle.** A mechanism-selection layer between runtime and specification is a live possibility; inserting it means renumbering everything or living with a lie.
- **"Tier" is overloaded in this repo.** The word named three other things before it named the architecture, and "belt tier" is Factorio's own vocabulary.
- **The semantic names already exist**, in the `Tier` enum itself (`FACTORIO_INFRA`, `SETTINGS`, `PYTHON_INFRA`, `RUNTIME`, `SPECIFICATION`, `INTERACTION` — `environment/tiers/base.py`). The numbering on accessors, classes and files duplicates them without adding information.

## Execution

1. A standalone, purely mechanical commit — never mixed with feature work.
2. Add deprecated property aliases (`env.tier3` → `env.connections`) so existing harnesses keep working for one cycle; remove them in a follow-up.
3. Rename classes and files (`tier3_python.py` → `connections.py`); update `TierError` messages to the semantic names.
4. Migrate docs and AGENTS.md. Historical records that used the numbers are not rewritten.
5. Run the offline test battery and confirm nothing behavioral changed.

## Open questions

- Is `env.spec` too terse against `env.specification`? Lean terse — it gets typed constantly.
- Does `env.factorio` collide with anything treating "factorio" as the process name?
- Whether to rename `TierBase` / `TierState` / `TierStatus` too. Lowest value; decide at execution time.

## Addendum — rename `execute_dsl` to `execute_python`

Same class of change: a name that describes what the thing is, not what it was called when it was written. Recorded here because it is a mechanical rename with the same execution discipline, not because it is tier-related.

**Why.** The tool the model is handed is named `execute_dsl`. The thing it executes is Python — a persistent namespace with top-level `await`, over the embodied action objects. There is no DSL. *Corrected 2026-08-28:* the description was repaired in `fda10e2` and now reads "Run Python in the agent's body." (`environment/tool_definitions.py:30`), and the tier-6 adapter docstring now says "Python, not Lua"; the earlier "Execute FactoryVerse DSL code" survives only in a docstring in `infra/session/session.py` that the model never sees. **The argument survives on the name alone:** the tool schema is prompt, the name is the first thing the model learns, and a model reading "DSL" reasonably expects a restricted language and under-uses Python. The system prompt still headlines the section "`execute_dsl` — Take Actions in the Game" and wraps the reference in a `<dsl_reference>` tag.

The tool schema is prompt. Its name is the first thing the model learns about the surface, and it is currently wrong.

**Scope.** The tool name and description in the interaction layer's tool table; the `RuntimeProtocol` method and its adapter implementation; every consumer in the orchestrator, trajectory writer, context validator/compressor, console, agent service and session; the two system-prompt mentions; the generated reference. Keep `execute_duckdb` — that name is accurate.

**Execution.** Ride the same mechanical commit as the tier rename, or a sibling one; deprecated alias for one cycle; fix the docstring in the same pass rather than leaving a correct name over a false description. Trajectory records carry the tool name, so the trajectory reader must accept both names for historical runs.

**Relationship to the turn contract.** `TURN_CONTRACT_DEFERRED.md` adds `end_turn` beside `execute_python` and `execute_duckdb`, and (2026-08-29) that is the whole tool table in both play modes. Landing the rename first means the turn contract's tool table is written once with correct names. The tool table's single definition is `environment/tool_definitions.py`, not the tier-6 file.
