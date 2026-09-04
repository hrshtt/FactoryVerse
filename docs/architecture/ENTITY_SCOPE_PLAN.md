# Entity scope — one owner of what an entity is

**Status: DESIGNED 2026-09-02, not executed.** Every code claim was verified against the
tree on 2026-09-02 (branch `prompt-audit-fixes`), every closure number by running the
computation in §3.5 over `.fv-output/factorio-data-dump.json`. Nothing here has been
built. Principles live in `docs/CONSTITUTION.md`; this plan argues from §3, §8, §10,
§12, §14 and §15 and proposes no new clause.

**Scope, stated first so it cannot creep.** This plan owns the *system-level* answer to
"what is entity X to this environment": one artifact that says it, one policy that
decides it, and the checks that hold every stack to it — Lua capture, the serializers,
the map model, the Python typing layer, and the catalogs the agent is shown at session
start. It does **not** own the agent-facing interface of any entity: no new entity
class, no new verb, no change to what `inspect()` returns for a family. Robots are the
reason this plan exists and are explicitly not in it (§9). Circuit network is tagged
TBD in the policy and not considered further.

The measurement this plan starts from is `docs/SUPPORTED_ENTITIES.md` (2026-09-02).
That page is a snapshot; when the checks in §7 exist, the page is regenerated from
them or retired.

---

## Summary

Six different mechanisms decide what an entity is, across roughly twenty independent
lists, and no two are checked against each other. The audit found the consequences —
sixteen entities advertised and unusable, seven of them placeable so that `place()`
raises after the world has changed, a science pack killed by a glob written for chests,
cliffs invisible to every read — and it found them by hand, with scripts that are not
in the tree.

**The correction: scope is a property of the technology tree, computed once, and every
stack asserts the same hash.** Policy names the technologies the environment excludes
and why. Everything a permitted technology unlocks is in scope, transitively — recipes,
their items and fluids, the entities those items place. A short override table handles
the cases the tree cannot express, each with its reason. The result is a manifest that
assigns every prototype in the installation exactly one standing, and a check that
fails on any prototype it cannot classify.

| | Now | After |
|---|---|---|
| Who decides scope | `fv_filters.yaml` by item subgroup; `ENTITY_CLASS_MAP` by name; two Lua switches by type; force set in the snapshot | one policy file (technologies + overrides), one generated manifest, one hash |
| Item scope vs entity scope | derived from each other through subgroups | two outputs of one closure; `rail` is an item and not an entity |
| An entity without a class | `ValueError`, swallowed in every read, raised after mutation in `place()` | a generic entity carrying name, position and standing; `place()` resolves the class before the RCON call |
| Lua | filters by force; never reads a scope file; a dead JSON claims otherwise | captures everything on a tracked force plus terrain; loads the generated manifest once; reports its hash; tags reachable entries with standing |
| Serializers | three (snapshot shape, reachable summary, inspect) with three type switches | two: the shape serializer and `inspect`; the reachable listing carries only fields every entity has |
| Map model | captures everything, plain `VARCHAR`, four component tables routed by a switch that is a strict subset of the Lua switch | still captures everything (§10); routing generated from the manifest; a scope row records the hash; no read path drops a row silently |
| Catalog shown at session start | static, filter-driven, not research-aware; a second research-aware path beside it | one generator from the manifest, annotated with the force's live research state |
| Checks | none — `grep ENTITY_CLASS_MAP tests/` returns nothing | totality, goal reachability, class-binding parity, routing parity, cross-stack hash, no silent drop, catalog parity (§7) |

---

## 1. What exists today

Verified 2026-09-02. The six axes, and who owns each.

**Existence.** The engine dump, pruned by `infra/data_dump.py:48-82` at field level
(`BANNED_KEYS`), loaded once by `game/factory/prototype_data.py:37`. Both mods validate
names against `prototypes.entity[...]` — `fv_embodied_agent/utils/ParamSpec.lua:186-194`
on every mutating RCON method, `EntityInterface.lua:88`, `placement.lua:78`.

**Capture.** `fv_snapshot/utils/forces.lua:11-30` builds `{player} ∪ agent forces`.
`game_state/Map.lua:1249-1271` scans by that force set and drops `character` and
`entity-ghost`. `game_state/Resource.lua:130-193` is the only neutral-force path: type
`resource`, type `tree`, type `simple-entity` whose name contains `rock` or `stone`, and
four water tile names. No name list anywhere. `src/fv_snapshot/fv_filters.json` is read
by nothing; `README.md:19` says it is live.

**Shape.** `fv_embodied_agent/utils/serialize.lua:17-42` dispatches on prototype type
into belts, pipes, poles, mining-drill, or a generic fallback that never drops. A second,
richer serializer, `agent_actions/reachability.lua:89-158`, builds the reachable listing
with its own hand-written type gates for recipe, fuel, contents and held item. A third,
`agent_actions/inspection.lua:1058-1165`, is the deep read behind `inspect()`; it is
shared by both views (`base_entity.py:405`) and already dispatches `beacon`, `radar`,
`reactor`, `storage-tank` and `lane-splitter` — Lua is ahead of Python on the audit's
T2a set.

**Projection.** `game/infra/duckdb/apply_ops.py:145-214` routes by type into four
component tables (`:42`); `pipes` and `poles` are serialized and never projected. No
name filter at ingestion (`:242-315`, `loader.py:57-195`, `sync.py:368-408`).
`map_entity.entity_name` is `VARCHAR` (`schema_definitions.py:62-66`);
`database.py:99-108` declines enums on purpose. Two op vocabularies — file
(`snapshot.lua:471-638`) and UDP (`udp_payloads.lua:32-37`) — reconciled in Python.

**Typing.** `game/factory/entity/create_entity.py:93-165`, 53 names to classes, three
of them prototypes 2.0 removed. `:206-212` raises for the rest. Handled by: silent skip
in `reachable_view.py:135-156`, debug log and `None` in `duckdb/query.py:323-334` and
`:442-453`, uncaught after the mutation in `place_entity.py:203-211` (the RCON call is
`:174-177`). `item/base.py:320-338` is a fallback branch that would raise `TypeError`
(missing `walking_action`) if it were ever reached. Capability is class declaration,
never prototype data (`base_entity.py:428-469`). No test references the map.

**Scope.** Root `fv_filters.yaml` — its header claims to govern "mod, DuckDB, DSL, and
LLM"; it governs `EntityPrototypes` / `ItemPrototypes` / `RecipePrototypes`
(`game/factory/prototypes.py`), `entity_reference` (`:337-344`, which therefore accepts
`beacon`), and one prompt generator. Entity scope resolves through the placing item's
subgroup (`utils/filters.py:164-178`). `filter_items` scans only the `item` prototype
type (`:285`) where the dump has seventeen item-like types. The file is also the
repo-root marker for `environment/config.py:30,45`. History: `FilterConfig` landed in
`1df2a5e` (2025-12-23), the YAML in `6d1514c`, the dead JSON in `cc9b1f2` one minute
before the loader; the last touch, `0bc3681` (2026-06-10), records an over-prune from
75 to 12 caught by an anti-vacuity guard. No unit test exercises it.

**The smaller lists.** `item/base.py:110-162` `PlaceableItemName` (62 names, type hint
only, includes four names with no class); `placement_hints.py:75-103` six name
frozensets, one reused by `remote_view.py:1332-1460`; type sets in
`entity/transform.py:209-518` and `entity_reference.py:34-37`; `EntityInterface.lua:152`
recipe allow-list with a `crafting_categories` fallback; `fv_placement_hints/utils/
entity_lookup.lua:353-398` name and type sets; `mining.lua:37-60`.

**Research.** Live in exactly two places: `crafting.list_recipes` reads
`force.recipes[*].enabled` in `crafting.lua:15-44`; `research.list_technologies` reads
`technology.enabled` in `researching.lua:35-76`. The session-start reference has two
halves born in one commit (`04b10d8`): `infra/llm/prompts/categorical.py` (filter-driven,
never research-aware) and `tech_recipes.py` (research-aware, never filter-driven), both
injected once by `initial_state.py:370-433`.

**Run assembly.** `EnvironmentConfig.for_run` (`environment/config.py:1061`) is the one
place a run is assembled. Mods are copied per run by
`infra/docker/factorio_server_manager.py:170-300` and `infra/factorio_client_setup.py:
380-490`. `vocabulary.lua` in `fv_embodied_agent` is a data-only Lua table checked from
both sides by `tests/unit/test_vocabulary_parity.py` — the precedent this plan reuses.

---

## 2. The decisions

Taken with the project owner on 2026-09-02 during the design discussion.

1. **The technology tree defines scope.** Subgroup lists go. Policy is a set of
   excluded technologies, each tagged with a criterion, plus a short override table.
   This is Constitution §3 made mechanical: the game's gates carry the sequencing
   information, so the environment's scope is expressed in the game's own unit of
   progression.
2. **Lua is a capture-everything seam.** The snapshot captures every entity on a tracked
   force plus terrain, and reads no scope for capture. Python owns the entity boundary
   and every contract at it. Lua uses the manifest for two things only: tagging
   reachable entries with their standing, and asserting the hash at boot.
3. **One family table, two projections, no third serializer.** The shape serializer
   (what the map model stores: event-backed structure, §10) and `inspect` (the deep
   per-entity read of live state, shared by both views) keep separate outputs, because
   the snapshot serializes a hundred entities a tick at boot and must not carry
   volatile state, while `inspect` makes an order of magnitude more engine reads per
   entity. What they share is the dispatch: one table of prototype type → family,
   generated from the manifest's `components`, so a family cannot be handled by one and
   forgotten by the other. The reachable listing's own summary serializer is deleted;
   the listing carries only fields every entity has — name, type, position, direction,
   status, standing. Anything richer is `inspect`, and a consumer that wants less
   filters what `inspect` returns.
4. **Lamps, cars and the display panel are excluded.** Circuit network is TBD: never
   used, not needed to win, lowest priority; the policy tags it so and the tree carries
   the display panel out with it.
5. **Enemies are never introduced.** They keep the standing `hostile`, the boot gate
   keeps asserting zero of them, and nothing captures them. **Cliffs are worked on**:
   they become terrain, captured on the neutral path, so a placement refusal on a cliff
   is explained by a read.
6. **Static scope and live availability stay separate.** The manifest never encodes
   what the force has researched. What is researched is read live (§12) and used only
   to annotate.

Two earlier decisions from `docs/SUPPORTED_ENTITIES.md` are carried in: the target of a
freeplay run is a rocket launch carrying a satellite, and `rail` is an item with no
placement interface.

---

## 3. The manifest

### 3.1 Inputs

- **The dump.** `factorio-data-dump.json`, with its hash. Technology prototypes carry
  `effects` (`unlock-recipe`), `prerequisites` and `unit`; recipes carry `enabled`,
  `hidden`, `results`; every item-like prototype type carries `place_result`. Verified
  2026-09-02: 196 technology prototypes, 19 fluids, 17 item-like prototype types.
- **The policy.** One file, `fv_scope.yaml` at the repo root, replacing `fv_filters.yaml`
  (and taking over its role as the repo-root marker). Three tables, every row with a
  `reason` naming one of the criteria below or a dated decision:
  - `exclude_technologies` — seeds; every technology with an excluded prerequisite is
    excluded transitively.
  - `allow_technologies` — by name, overriding transitive exclusion. The one known case
    is `cliff-explosives`, whose prerequisites include `military-2`; whether to allow it
    is open (§12).
  - `overrides` — by prototype name: `standing: item-only` (`rail`), `standing: charted`
    for an entity the tree admits but policy refuses (`locomotive`, `cargo-wagon`,
    `fluid-wagon` under criterion 4; `cargo-landing-pad` under criterion 2),
    `standing: object` for an entity the tree cannot reach but the world provides
    (`crash-site-chest-1`, `crash-site-chest-2`: placed by the scenario, lootable).

The criteria are the owner's five from the audit, numbered as there: (1) enemies and
the military and wall family; (2) end-game deferred for bandwidth, lifted for the rocket
chain; (3) parameter stubs; (4) trains; (5) robots, deferred and now the next priority.
Plus (6) TBD for circuit network.

### 3.2 Standings

Every entity prototype in the installation gets exactly one:

| Standing | Meaning | Who may hold it |
|---|---|---|
| `object` | In scope. Its item is craftable, it can be placed, and a Python class exists. | placeable items in the closure, less overrides |
| `item-only` | Its item is in scope and craftable; the entity is never placed by the agent. | `rail`; any object-candidate whose class does not exist yet (§3.4) |
| `charted` | Captured to the map model when it exists, visible to raw SQL and to every listing as a generic entity, outside the typed API and the catalogs. | everything a tracked force can own that policy excludes |
| `terrain` | Neutral-force world objects the resource surface owns: resources, trees, rocks, cliffs, fish. | the neutral capture path |
| `hostile` | Enemy forces. Never captured; the boot gate asserts none exist. | units, spawners, worms |
| `agent` | The character. Excluded at every call site. | `character` |
| `inert` | Never a persistent thing the agent can meet: effects, projectiles, corpses, remnants, proxies, stubs, the ten parameter entities. | by prototype type, plus a named stub list |

`item-only` and `charted` are the same to the map model and differ in one place: the
item catalog lists an `item-only` name and not a `charted` one.

### 3.3 Outputs

One JSON manifest, generated by `fv scope generate`, committed, and hashed:

- `dump_hash`, `policy_hash`, `manifest_hash`, `generated_at`.
- `technologies`: allowed and excluded, each excluded one with its reason chain.
- `recipes`, `items`, `fluids`: the closure.
- `entities`: every prototype name → `{type, standing, reason, placed_by, component}`.
- `components`: prototype type → component (`belt`, `pipe`, `pole`, `inserter`, `drill`,
  `crafter`, `none`), the one routing table both the shape serializer and `apply_ops`
  are generated from or checked against.
- `class_bindings`: `object` name → Python class, resolved by prototype type with named
  exceptions (§3.4).

Plus one generated Lua module, `src/fv_embodied_agent/scope.lua`, data only, the same
shape `vocabulary.lua` has: `standing[name]`, `component[type]`, `manifest_hash`. It is
committed, and a unit check asserts the committed file equals a fresh generation — the
`fv docs generate` discipline applied to scope.

### 3.4 Class binding

`ENTITY_CLASS_MAP` stops being a source and becomes an assertion target. Python declares
a binding by prototype **type** (`assembling-machine → AssemblingMachine`,
`container → Container`, …) with named exceptions where one type splits by a prototype
fact (`furnace` splits on `energy_source.type`). The manifest resolves every `object`
name to a class through that table; the check fails if any does not resolve and if any
binding names a prototype outside `object` standing (the three dead inserter names go).

Mixins stay authored, because they encode behaviour. The check reads the prototype and
asserts the class composes what the prototype implies: a burner energy source implies
`BurnerMixin`, a fluidbox implies `FluidMixin`, `crafting_categories` implies
`CrafterMixin`, and so on — and nothing the prototype does not imply.

An `object`-candidate without a class is not an error in the manifest; it is
`item-only` with reason `no class`, until the class lands. On the closure below that is
`beacon`, `heat-exchanger`, `heat-pipe`, `nuclear-reactor` and `radar` (the audit's
decision already made `radar` ingredient-only). Writing those classes is entity
interface work and outside this plan; the manifest makes the gap honest instead of
hidden.

### 3.5 The closure, measured

Run 2026-09-02 over the dump with sixteen seed exclusions — the military branch
(`military`, `gun-turret`, `stone-wall`, `land-mine`, `artillery`, `tank`,
`flamethrower`, `laser-turret`, `rocketry`), trains beyond `railway`
(`automated-rail-transportation`, `rail-signals`), robots (`construction-robotics`,
`logistic-robotics`), `circuit-network`, `lamp`, `automobilism`:

| | Count |
|---|---|
| Technologies excluded, transitively | 96 |
| Recipes in scope | 138 |
| Items in scope | 111 |
| Fluids in scope | 7 |
| Entities placed by an item in scope | 55 |
| Name overrides needed on top | 5 |

`rocket-part`, `satellite`, `rail` and all five non-military science packs are in the
closure. Transitive exclusion carries out `gate` (via `stone-wall`), `logistic-system`,
`military-science-pack`, every equipment and damage technology, `spidertron`, and
`cliff-explosives`. The 55 entities are the audit's 50 typed names less the three
loaders and two crash-site chests (no recipe reaches them) plus `beacon`,
`heat-exchanger`, `heat-pipe`, `nuclear-reactor`, `radar`, `locomotive`, `cargo-wagon`,
`fluid-wagon`, `cargo-landing-pad` and `straight-rail`. After the five overrides the
`object`-candidate set is 50 again, with the five no-class names above as `item-only`.

One seed name in the probe did not match a technology prototype. That is a check, not
a footnote: every name in the policy must exist in the dump (§7, C1).

The dump holds 196 technology prototypes where the live engine reported 187 to the
audit's reachability run. The difference is to be explained before C2 is trusted.

### 3.6 Loaded once, asserted everywhere

- **Python** loads the manifest once per process, in the successor of
  `PrototypeDataManager`; `EntityPrototypes` and friends read from it. Nothing else
  reads the policy or recomputes the closure at runtime.
- **Lua** requires `scope.lua` at control stage. `remote.call("agent",
  "get_scope_hash")` returns what it loaded. The boot probe in preflight
  (`environment/boot_probe.py`) compares it to Python's and fails closed on mismatch,
  exactly as the scenario hash does.
- **The map model** carries a one-row `scope` record (`manifest_hash`, `dump_hash`,
  `loaded_tick`) so a database can say which scope it was built under.
- **The record** carries the manifest hash beside the system prompt hash, so a run's
  scope is a fact of the run.

---

## 4. The seams

### 4.1 Lua — capture, tagging, cliffs

Capture does not change: force set for owned entities, the neutral path for terrain.
The neutral path gains `cliff` (and `fish`, which is minable and already neutral) as
terrain, routed where trees and rocks go. `Resource.lua`'s `rock|stone` name check is
replaced by `standing[name] == "terrain"` from `scope.lua`, which is what it was
approximating.

The reachable listing (`get_reachable`) adds `standing` to every entry and loses its
type-dispatched fields (recipe, fuel, contents, held item). It keeps status, which every
entity has. Corpses stop needing a name check: they are `inert`.

The recipe allow-list in `EntityInterface.lua:152` is already a fast path over a
prototype fact (`crafting_categories`); it stays as a fact, not a list.

Nothing in Lua refuses on scope grounds. If an entity of `charted` standing is placed by
some other route — a scenario, a human, a test — it is captured and tagged, and Python
says what it is.

### 4.2 Python — the boundary

- **The drop gets a voice.** `create_entity` returns an `UnsupportedEntity` — name,
  position, type, standing, raw row — for any name whose standing is not `object`. It
  never raises for a known name. Every `except ValueError: pass` and `return None` in the
  read paths is deleted; if the manifest does not know a name at all, that is a
  `ValueError` that propagates, because it means the world and the manifest disagree
  and someone must look (§15).
- **`place()` resolves before it mutates.** `PlaceableItem.place()` resolves the class
  from the manifest before building the RCON command. An `item-only` or `charted`
  standing refuses there, naming the standing, with the world unchanged. After the RCON
  call nothing on the path can fail for a reason the manifest could have known (§8).
  The dead fallback in `item/base.py:320-338` is deleted.
- **`entity_reference(name)`** validates against `object ∪ item-only` and refuses
  `item-only` with the standing named, instead of admitting `beacon` today.
- **The smaller lists** are derived or deleted: `PlaceableItemName` becomes generated or
  goes; the `placement_hints.py` frozensets become prototype-type reads from the
  manifest; `transform.py` type sets read `components`; `entity_reference.py` frozensets
  read the same.

### 4.3 The map model

Capture-all stays, argued from §10: what enters the database is decided by events, not
by scope. `apply_ops` routing is generated from `components`, so the projection can no
longer be a strict subset of the serializer switch by accident. `get_entities` /
`get_ghosts` return `UnsupportedEntity` rows and never fewer rows than the SQL. Whether
`pipe` and `pole` gain component tables is Phase 4B's question (TRANSPORT §6–§7) and is
not decided here; this plan only guarantees the routing table is one table.

### 4.4 Catalogs and the session-start reference

`categorical.py` and `tech_recipes.py` collapse into one generator that reads the
manifest for membership and the force for state: every item, fluid and recipe in scope,
each annotated *unlocked* or *locked by <technology>* from a live read at generation
time, with the read's tick stated. Fluids get a catalog for the first time. The generator
runs at session start as today; when it runs is the Turn Contract's business.

`crafting.list_recipes` and `research.list_technologies` keep reading the force live and
additionally drop anything outside scope, so the two catalogs and the reference can no
longer disagree about membership.

### 4.5 What dies

`fv_filters.yaml`, `utils/filters.py`, `src/fv_snapshot/fv_filters.json` and its README
line, the three dead `ENTITY_CLASS_MAP` names, `serialize_entity_full`, the `rock|stone`
check, the `logistic-*` and `storage-*` globs and every other glob, `NON_ENTITY_CATEGORIES`.

---

## 5. What this plan does not decide

- **Classes for the five no-class names.** Each is an entity interface. This plan makes
  them `item-only` and honest; a later decision makes them `object`.
- **Robots.** The policy carries `construction-robotics` and `logistic-robotics` under
  criterion 5. Enabling robots later is deleting those two lines, writing the classes
  for `roboport`, the robots and the logistic chests, and deciding under §4 what surface
  each belongs to. That is its own plan; this plan is its precondition.
- **What the agent is told, and when.** Today the report names a finished technology
  and not what it unlocked (`turn_report.py:259-268`), and the session-start reference
  lists every recipe in scope whether or not the force has unlocked it. The owner's
  position (2026-09-02): both are incorrect behaviour. The report must say what a
  research completion unlocked, and definitions the agent is not yet privy to should
  not be shown for free — access to that reference should be a tool call, gated on the
  force's live research state. That is the agent-facing half of this subject and it is
  `FACTORIOPEDIA_PLAN.md`; this plan supplies its substrate (standings, unlocking
  technology per item and recipe, the live annotation) and builds none of its surface.
- **`fv_placement_hints` hardcodes `force = "player"`** at fifteen call sites, so its
  answers are for the player force, not the agent's. Real, orthogonal, noted for the
  transport plan.
- **Circuit network.** TBD. The policy line stays until the owner says otherwise.

---

## 6. Teaching

The agent's prompt learns two sentences. An entity it meets that it cannot hold as an
object is still reported, with a standing that says why. The reference it is shown at
session start is the environment's scope, and *locked by* names the technology that
opens each locked line. Nothing else changes in what the agent is told; the interface of
every supported entity is unchanged by this plan.

---

## 7. Before believing any of this worked

Each check names what it runs against and how it cannot pass vacuously (§14).

| | Check | Layer | Cannot pass vacuously because |
|---|---|---|---|
| C1 | **Totality.** Every entity prototype in the dump has exactly one standing; every name in the policy exists in the dump; the committed manifest and `scope.lua` equal a fresh generation. | unit | the dump and the policy are built independently; an empty dump fails the count floor from the audit |
| C2 | **Goal reachability.** From the starting recipes and the allowed technologies, `rocket-part` and `satellite` are reachable, and the excluded set is exactly the criterion branches. | unit | the fixpoint is the previous session's, now in the tree; the goal names are constants the closure does not see |
| C3 | **Class binding.** `object` names ⇔ bindings; mixins ⇔ prototype facts; no binding outside `object`. | unit | both sides are independent: prototype JSON and Python class declarations |
| C4 | **Routing parity.** The shape serializer's switch, `apply_ops`, and `components` agree, read from source text as `test_snapshot_lua_contracts.py` does. | unit | a missing branch on either side is a difference |
| C5 | **Cross-stack hash.** A booted instance's `get_scope_hash` equals Python's; preflight fails on mismatch; the `scope` row matches. | live | it reads the mod, not a file the test wrote |
| C6 | **No silent drop.** With a `charted` entity created in the world by script, the reachable listing, `get_entities` and raw SQL all report it, as `UnsupportedEntity` where typed; `place()` on an `item-only` item refuses with the world unchanged; `place()` on an `object` item returns the object. | live | an entity is created and counted on three surfaces; the refusal is asserted against a before/after entity count |
| C7 | **Catalog parity.** The session-start reference's item, fluid and recipe sets equal the manifest's; every *unlocked* annotation equals `force.recipes[*].enabled` at the stated tick. | live | membership from the manifest, state from the engine |
| C8 | **Cliffs.** A cliff within reach appears as terrain; `can_place` on its tiles refuses and the refusal names the cliff. | live | the world has to contain a cliff, so the check builds one |

C1–C4 need no instance. C5–C8 need a running instance and none needs the
`iron-saturated` fixture, so this plan is not behind the Phase 4 blocker.

---

## 8. Order of work

1. **A — the drop gets a voice.** `UnsupportedEntity`; delete the swallows; `place()`
   resolves before it mutates; the dead fallback goes. Check: a unit test that constructs
   every audit T2a name and gets an object back, and a `place()` test that asserts the
   RCON command is never built for a refused name. Independent of everything below and
   fixes the §8 violation today.
2. **B — the manifest.** Policy file, closure, standings, `fv scope generate`, the
   committed manifest and `scope.lua`, the Python loader. C1, C2.
3. **C — the bindings.** Type-keyed class table, mixin assertions, the smaller lists
   derived, `fv_filters.yaml` and `filters.py` deleted, repo-root marker moved. C3, C4.
4. **D — the seams.** Lua loads `scope.lua`, tags, reports the hash; preflight asserts;
   the `scope` row; cliffs on the neutral path; `serialize_entity_full` retired. C5,
   C6, C8.
5. **E — the catalogs.** One generator; fluids; live annotation; the two catalog reads
   scoped. C7.
6. **F — the audit becomes a check.** `docs/SUPPORTED_ENTITIES.md` is regenerated from
   the manifest and the live probes, or retired in favour of C1–C8. The scripts leave
   the scratchpad.

A and B can start now. C through E touch surfaces Phase 4B also touches; sequence them
with it in `docs/EXECUTION.md` rather than here.

---

## 9. Where this lives

- `fv_scope.yaml` — the policy, repo root.
- `src/FactoryVerse/game/factory/scope/` — `closure.py`, `manifest.py`, `standings.py`,
  the loader; `fv scope generate` in the CLI.
- `src/FactoryVerse/game/factory/scope/manifest.json` — committed output.
- `src/fv_embodied_agent/scope.lua` — committed generated data module.
- `tests/unit/test_scope_*.py` for C1–C4; `tests/live/test_scope_contract.py` for C5–C8.

---

## 10. Related plans

- **API_AFFORDANCE_REDESIGN** — its prototype-scoping table names `fv_filters.yaml` as
  owner; amend to name the manifest.
- **GHOST_SURFACE §4.1** — its bots reality check reads the subgroup exclusion; the
  same fact is now two policy lines.
- **TRANSPORT_CONNECTIVITY** — `components` is the routing table §6–§7 decide the
  shape of; Phase 4B's serializer work and this plan's C4 are one change.
- **SCORER_MOD_PLAN §1** — says `production-score.lua` "prices exactly the set that
  survives `fv_filters.yaml`"; after this plan it prices the engine's recipes and the
  manifest says which of those the agent can reach. Amend the sentence.
- **TURN_CONTRACT** — receives the unlock-report amendment (§5).
- **SCENARIO_BOOT_CONTRACT** — the hash assertion joins its preflight.

---

## 11. Amendments to the Constitution

None proposed. §3 gives the tree as the unit of scope; §8 gives the `place()` ordering;
§10 keeps capture-all; §12 keeps research live; §14 and §15 give totality and the
refusal to drop.

---

## 12. Open

- **`cliff-explosives`.** Capturing cliffs makes them visible; removing them needs an
  item whose technology sits behind `military-2`. Allow the technology by name, or
  accept that cliffs are permanent obstacles in this environment. The owner's call.
- **The 196 vs 187 technology count** (§3.5). Hidden or disabled prototypes, or the
  engine filtering something the dump keeps. Explain before C2 is cited.
- **Where cliffs are stored.** `resource_entity` is the neutral table today and its
  name says otherwise. Rename or add; decide in B.
- **Whether `charted` entities appear in the categorical reference at all.** Today's
  answer is no; the alternative is a one-line "present in the world, outside scope"
  section so the agent is not surprised by a wreck. Cheap either way on a fresh start.
  *Sharpened 2026-09-04 by the `starter-base-test` baseline* (15 251 entities, 32
  names): 1 217 of them — `stone-wall` 1 188, `small-lamp` 17, `roboport` 12 — have no
  class today, so every typed read drops them silently (the §1 row "an entity without
  a class") while SQL and the engine both see them. On an inherited base that is 8 %
  of everything standing in front of the agent, and the "present, outside scope"
  section stops being optional: the reference must name what the agent cannot name.
  Walls become `charted` under criterion 1, lamps under decision 4, roboports wait on
  the manifest. Step A (the drop gets a voice) is where this lands.
- **What `inspect` returns for the energy family** — `solar-panel`, `accumulator`,
  `lab`. On `starter-base-test` they are 4 194 entities, 27 % of the base, and their
  classes expose nothing beyond the base surface (position, footprint, live status).
  The base-wide power read exists on `remote_view` (API §4.6); the per-entity singular
  §11 asks for does not. A human gets an accumulator's charge, a panel's output and a
  lab's science packs by hovering, so under decision 3 these are `inspect` fields:
  `energy`, `charge` (accumulator, as a fraction of capacity), `output` (panel, current),
  `science_packs` (lab, by name and count). Recommended, not decided; decide in B
  when the family table is generated, so the energy family is not handled by one
  projection and forgotten by the other.
