# Ghost surface — deferred refactor plan

**Status: DEFERRED.** Grounded in a code-audit sweep of the ghost surface; nothing here has been executed. Principles live in `docs/CONSTITUTION.md`.

## Summary

The ghost system is two things wearing one name, and they deserve opposite fates.

- **The primitives** — ghost place, remove and rotate, the `ghost` table, the label chain — are game-native, and *more* grounded than the project has credited them. Factorio 2.0's remote view is literally a ghost-planning surface in the human interface: no body, no reach, no inventory. **Keep, and name them for what they are: the map-view write surface.**
- **The orchestration** — `GhostBuilderAction.build_plan` / `build_ghosts` and the plan-commit coupling — is a construction-robot emulator running on the avatar's legs, filling a hole cut when `fv_filters.yaml` excluded the bot and logistic-chest stack. **Delete.**

**Ghosts are primitives; there is no executor verb.** Removal costs the agent zero placement capability — everything `ghost_builder` can build goes through the same `place()` the model calls itself. It costs only turns, and paying those turns in model-authored composition is the bet already made.

## 1. Why the orchestration is being removed

**The reason is progression, not principle.**

An earlier draft argued that `ghost_builder` violated two frozen principles. The argument was available, but it was not the driver, and leading with it teaches the next reader to over-apply the affordance rule and delete things that do not deserve it.

**Individual ghost placement passed the human-affordance test honestly, and still does.** A human player places single ghosts freely, from anywhere, from the first minute. Nothing about the primitive is in question. It stays.

**What is being withdrawn is the scaling layer.** The game already supplies an executor for ghosts at scale: construction bots, gated behind Construction robotics. Building a hand-rolled emulator of that executor moved a mid-game capability to turn one.

The bet was that this would be an uplift. Measured against how models actually perform, it was not. The delta between expected and observed capability puts models much earlier on the curve — they are still learning to build a base at all — and an unearned mid-game tool did not move that.

Constitution §3: **in-game progression is a design input, not an obstacle to route around.** Where the game gates a capability, the gate carries information about sequencing, and the burden falls on whoever wants to open it early.

**The cost of removal is low, and that is part of the decision.** Withdrawing the emulator makes room for real bot integration later, which is a tractable build with current coding agents in a way it was not when the emulator was written. This is a development clarification, not a contradiction being resolved — though there *was* a contradiction underneath, a capability justified by appeal to capability. That justification was misguided independently of whether any principle forbade it.

**Historical honesty:** `ghost_builder` was scaffolding for a real observed failure — a fifth of eval runs stuck in "cannot place entity" loops. The actual cause was a geometry handoff bug, fixed elsewhere. The scaffolding is obsolete; what was wrong at the time was the expected uplift, not the response to the failure.

### 1.1 What ghosts still owe the agent

Ghosts remain a **tracked, queryable intent record** — what is pending, where, labelled how, since when, readable at map scale. That is the whole obligation.

**Nothing beyond that belongs in the Python execution layer.** No plan objects advertising commitment, no executor verb, no orchestration. Ghost place, remove and rotate stay as primitives; everything else about ghosts is a read.

This sits correctly under Constitution §10: ghost placement and removal raise engine events that the shared reducer already applies, so the `ghost` table is event-backed and lawfully part of the map model. It is also the one place ghosts differ from entities — **ghost status is not a thing.** There is no volatile per-ghost state to keep out of the database.

## 2. What is game-native and what is invented

| Layer | Verdict | Grounding |
|---|---|---|
| Ghost entity, place / remove / rotate — the `ghost=True` flag through `place_entity.py` into `placement.lua` | **Game-native.** Skips reach and inventory, validates as `manual_ghost` — semantics match Factorio 2.0 remote-view building exactly | The map-view **write** affordance. It fills the empty cell in the interface isomorphism: avatar is code, map-read is SQL, HUD is tools and events, **map-write is ghosts** |
| The `ghost` table and the shared reducer in `apply_ops.py`; the label chain — engine-side `tags.fv_label`, inherited when a real entity is built over a ghost in `placement.lua` | **Sound.** Event-backed, so lawfully in the map model | Second grounding: **ghosts are the game's native shared-intent ledger** — the map-state twin of the transcript. This is where attribution becomes the multi-agent surface, when that is designed |
| `placement_hints` generators — lines, pole coverage, underground segments | **Keep the lawful ones as reads.** Pure, non-mutating | Constitution §6 and §7 decide membership: a read may infer what the cursor preview would tell a human. Line previews and supply overlays pass. Greedy set-cover does not — the cursor shows coverage, never a solved cover |
| `GhostBuilderAction` walk-and-build orchestration | **Delete** (§1) | The bot gate is the grounding. Humans do not walk ghost-to-ghost hand-building at scale, because the game hands them an executor once they earn it |
| `GhostPlan` as a commit handle | **A half-reinvented blueprint** — absolute coordinates, single entity, non-reusable, non-parameterized. Slim it to a validated position list | The real compiled-skill artifact in Factorio is the blueprint (§5). A future shape, not this one |

## 3. What removal actually costs

`ghost_builder` has **zero dependents in the primitive layer.** Nothing composes on `build_plan` or `build_ghosts`; `BaseEntity.build()` / `remove()` and `item.place_ghost()` call placement directly and survive; label inheritance lives in Lua, not Python.

*Scoped 2026-08-28, so the deletion is not misread as zero-touch:* outside the primitive layer it is wired in `environment/runtime.py`, `environment/tiers/tier4_runtime.py` (loader, property, namespace dict), `environment/sessions.py`, `environment/agent_runtime.py` (module preload), the docs registry and generator, the runtime prompt (*"prefer placement_hints + ghost_builder"* for multi-entity layouts, with worked `build_plan` examples), and three tests (`test_building_contracts`, `test_environment_tiers`, `tests/live/test_freeplay_harness_domains`). The 2026-08-25 baseline run made zero calls to it on a prompt that steered toward it. Also note the builder continues past failures in *both* modes — `strict` only gates an upfront inventory check (`ghost_builder.py:129-153`), not the per-item loop.

| Structure | Post-removal path | Loss |
|---|---|---|
| Single entities | Direct `place()` — never ghost-coupled | None |
| Lines — belt, pipe, wall | Hand loop now; `place_line` when the belt plan lands | The packaged path, which walked to *every* tile and continued past failures — the shape the belt plan condemns |
| Pole lines | Hand loop over the pole-line read now; `place_line(spacing=…)` later. Pole runs are spaced, not contiguous, so they ride the verb only through its `spacing` argument | Same as lines |
| Pole coverage, underground segments | The generators still return validated positions as reads; the model loops `place()`. Permanently — coverage is 2D set-cover, not a line, and gets no bulk verb | Only the loop. Roughly five lines of model-authored walk-and-place; `ghost_builder`'s own loop is the existence proof that the composition works |
| Large multi-entity layouts | The model composes chunk by chunk under the bulk-verb cap | The one genuine hole — and the one `ghost_builder` never soundly filled: its characteristic failure was orphaned ghost runs, which is abandoned intent, not scale. This hole's real owners are blueprints and bots (§4.1, §5), neither built here |

## 4. Target design

1. **Delete `GhostBuilderAction`** (`game/agent/ghost_builder.py`) and its runtime wiring and documentation.
2. **Slim `GhostPlan` to a validated position list.** The generators keep returning positions, validity, label and description; the object stops advertising itself as ready for commitment. Commit becomes the model looping `place()` — ghost or real — over positions it holds as data, so the mutation set is model-enumerated by construction.
3. **Name the map-write surface.** Ghost place, remove and rotate get documented as one contract: no reach, no inventory, laxer validation, and mutations are exactly the positions passed. No new code — this is framing (§6) that gives the primitives their explicit grounding.
4. **The intent-ledger read is a database query, not a status read.** Pending count, labels and age are map-model questions about event-backed rows, so they belong in SQL. An earlier draft routed this through a status filter; that was wrong about which surface owns it.
5. **Delete the broken bootstrap block** in `infra/session/session.py`, which imports a `GhostBuilder` class that does not exist — the module defines only `GhostInfo` and `GhostBuilderAction` — with the wrong constructor arity and a stale module path. Dead or broken either way.

### 4.1 The bots reality check

`fv_filters.yaml` excludes the logistic, storage, provider, requester, buffer and personal-equipment families. Roboport and construction-robot are **not** explicitly excluded — but construction bots source materials from exactly the chest layer that is, and personal roboports are out. So ghosts currently have **no game-native executor**, and `ghost_builder` existed to fill that hole.

Post-removal, the near-term executor is hand-building. Honest, and consistent with the bet.

Bots becoming the executor requires two deliberate decisions, not hope: a filter change admitting the bot and chest stack, and eval scenarios progressing past the current ceiling to construction robotics. Neither is decided here. Under Constitution §3, taking those two decisions in order *is* the honest path to ghosts-at-scale being game-native end to end — the gate is sequencing information, not an obstacle.

**Verified 2026-08-28:** roboport and construction-robot do **not** survive. `fv_filters.yaml` excludes the `logistic-network` subgroup (`:57` entities, `:200` recipes), entity filtering resolves through the placing item's subgroup (`utils/filters.py:164-178`), and in the live prototype dump `roboport`, `construction-robot`, `logistic-robot` and all five logistic chests carry `subgroup: "logistic-network"`. The exclusion is by subgroup, not by name.

## 5. Blueprints — the lawful successor

`GhostPlan` is a half-reinvented blueprint. The real thing is the game's own compiled-skill artifact — relative coordinates, multi-entity, storable, reusable, and in 2.0 parameterizable — which fits the skill-library thesis better than anything hand-built. The certified ghost primitives are the substrate blueprints stamp onto, so nothing sunk is wasted. **Recorded, not built.**

### 5.1 Game facts (researched, not verified against our engine image)

- **The unlock gate:** blueprint, deconstruction-planner, upgrade-planner and copy-paste shortcuts are hidden until the player researches **Construction robotics in any game**; the unlock then persists across all saves for that player. Wube's stated rationale is that new players should learn fundamentals before importing complete designs. The gate is UI pedagogy, not an engine restriction.
- **Mechanics:** blueprints store entities with *relative* positions, directions, modules, circuit connections and settings, with snap-to-grid. Stamping places **ghosts** — built by construction bots, or hand-built over. 2.0 parameterization makes a blueprint a template, with recipes and signals resolved at stamp time.
- **Strings** are base64-encoded compressed JSON: a text-native artifact an LLM can read, emit, diff and store. The game's compiled-skill format is literally JSON.
- **The Lua API has all four verbs on `LuaItemStack`, all synchronous:** author (`set_blueprint_entities`) or capture (`create_blueprint`); serialize and deserialize (`export_stack` / `import_stack`); stamp (`build_blueprint`). Stamping with `raise_built` set means the ghosts flow into the existing pipeline — ghost tracking, table mirror, label chain — so the blueprint layer *consumes* this plan's substrate.

### 5.2 The phase question resolves to tech-gated tool exposure

The instinct toward a separate blueprint mode with its own API and prompt resolves game-natively: **blueprint tools appear in the tool list when Construction robotics completes**, mirroring the shortcut bar exactly. No phase machinery, no prompt swap.

Early-game models carry zero blueprint weight in prompt or tools, which serves the motivating observation: models are perpetual new players, and Wube gates blueprints for the same reason about the same audience. **The game already has phases. They are called research.**

### 5.3 Surface placement and how a blueprint may be acquired

- **Tool-side, not Python.** The blueprint library is HUD chrome, and stamping from map view is a map-write. Neither is a body verb.
- **Self-authored** (the model emits blueprint-entity JSON, having enumerated every tile) and **self-captured** (`create_blueprint` over an area the model hand-built, so every future stamp replays a layout it built with its own calls) both pass Constitution §7 — the model's own enumeration is the gesture. **Imported** external strings fail it, being unenumerated mass mutation, and they defeat the learning loop, which is Wube's own reason for the gate. **No import surface, at least initially.**
- **The executor question becomes one decision.** The gate is Construction robotics itself, so when blueprints unlock, bots exist tech-side; the only blocker is the §4.1 filter exclusion. Bots, chests and blueprints enter scope together as one progression tier — or blueprints ship without them and stamped ghosts are hand-built over, which is fully supported play and graceful degradation.

### 5.4 Scope and build trigger

Contracts: author, capture, stamp, list — returning actuals (ghosts created, first blocker with reason) per Constitution §8. A home for the blueprint item stack. The tech-gated tool-exposure mechanism is the one new harness capability, since nothing currently adds tools mid-run; design it once and it generalizes to any progression-gated affordance. Parameterization is excluded from a first version.

**Build after an eval run first reaches the gate.** By current evidence models are nowhere near Construction robotics, so a blueprint surface built now sits unexercised. This also means the §4 removal costs nothing on the scale-someday axis: the successor is fully specified and strictly more grounded.

## 6. Teaching

1. Remove the "place ghosts, then build them into real entities" workflow from the system prompt, and the reference steering that says to prefer the planner-plus-builder route for multi-entity layouts.
2. Replace it with the map-write framing, stated once: **ghosts are plans on the map** — placed from anywhere without reach or inventory, visible to everyone in the `ghost` table, and made real by walking there and placing the real entity over them, which replaces the matching ghost and inherits its label.
3. Keep the ghost-blocked-methods table and the `ghost` schema. Both are sound.
4. Rewrite the worked examples that call `build_plan` to the composed idiom.

## 7. Before believing any of this worked

- **A baseline on the current surface.** Does the model use the ghost workflow today, unprompted and then prompted? The orphaned-ghost pattern suggests engagement exists and produces litter. Measure before deleting, so the difference afterward is attributable. The belt, HUD and API plans all want this same run. *Closed with loss, 2026-09-03:* the executor was deleted in Phase 4A before this ran. The only pre-deletion evidence is the 2026-08-25 run's zero calls on a prompt that steered toward it. Do not reschedule.
- **Comprehension probes, no acting.** Predict ghost semantics: which methods are blocked on a ghost, that no inventory is consumed at ghost-place, that a plan is not a reservation, what `place()` over an existing ghost does. Wrong predictions mean the teaching gap dominates, and surfaces should be taught before they are restructured.
- **An executed check of the composed idiom** after removal — walk, place over ghost, label inheritance — plus coverage for `remove_ghost`, which has none today.

Constitution §13: none of this is true until its check has been run.

## 8. Explicitly out of scope

- Admitting bots and logistic chests into `fv_filters.yaml` — a separate decision, and the natural companion to blueprints.
- Building blueprints (§5). Shape recorded; the trigger is an eval run reaching the gate. The game facts in §5.1 are researched, not verified against our engine image.
- Multi-agent ghost semantics — ownership, contention, attribution. The substrate is preserved and nothing is designed. Two facts recorded: ghosts are force-visible shared state, and removing another agent's ghost is a griefing primitive.
- Whether the line generators survive once `place_line` exists. The belt plan owns that.

## 9. Where this lives

| What | Where |
|---|---|
| Orchestration class and its walk-and-build loop | `game/agent/ghost_builder.py` |
| Commit-boundary revalidation — a plan is a cached observation, not a reservation | `ghost_builder.py`, in the commit path |
| The single shared placement primitive and its ghost flag | `game/agent/embodied_actions/place_entity.py`; `src/fv_embodied_agent/agent_actions/placement.lua` |
| Ghost semantics — skip reach and inventory, `manual_ghost` validation | `placement.lua` |
| Label written engine-side, inherited when built over | `placement.lua` |
| Runtime wiring | `environment/runtime.py` |
| Broken bootstrap importing a nonexistent `GhostBuilder` | `infra/session/session.py` |
| Plan generators, pure reads | `game/agent/placement_hints.py` |
| `GhostPlan` | `game/agent/placement_hints.py` |
| Ghost table and reducer | `infra/duckdb/schema_definitions.py`; `infra/duckdb/apply_ops.py` |
| Filter exclusions for the bot and chest stack | `fv_filters.yaml` |
| Prompt ghost workflow and steering | `docs/system-prompt/factoryverse-system-prompt-v3-core.md` |

Blueprint research: the Factorio wiki on Blueprints and the Shortcut bar (for the Construction-robotics gate and cross-save persistence), FFF-392 (parameterization), FFF-380 (remote view), and the `LuaItemStack` API reference.

## 10. Related plans

- `BELT_AFFORDANCE_DEFERRED_PLAN.md` — `place_line` is the lawful replacement for the line-shaped uses of `build_plan`. Landing it first softens the turn cost of this deletion; neither blocks the other. Its repairs to the line and underground reads are what make §3's cost table rest on sound ground.
- `HUD_PARTITION_DEFERRED_REFACTOR.md` — resolves its open `ghost_builder` question into removal, and the map-write surface completes its interface isomorphism.
- `API_AFFORDANCE_REDESIGN_DEFERRED.md` — deletes the coverage optimiser and rehomes the surviving generators onto the entity reference object.
- `NOTIFICATIONS_PRIMITIVE_DEFERRED.md` — no dependency. Ghost operations are synchronous RCON plus snapshot sync.
