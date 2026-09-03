# Factoriopedia — what the agent is told about the world, and when

**Status: DESIGNED 2026-09-03, not executed.** Every code claim was verified against the
tree on 2026-09-02/03 (branch `prompt-audit-fixes`); the starting-set numbers were
computed over `.fv-output/factorio-data-dump.json`. Nothing here has been built.
Principles live in `docs/CONSTITUTION.md`; this plan argues from §2, §3, §5, §12 and §21
and proposes no new clause.

**Scope, stated first so it cannot creep.** This plan owns the agent-facing half of the
entity subject: what the system prompt says about entities, a tool through which the
agent reads the rest, and one line in the turn report. It owns no entity class, no
verb, and no change to any entity's interface. Its substrate — standings, the unlocking
technology per item and recipe, the live research annotation — is
`ENTITY_SCOPE_PLAN.md`, which must land first. Robots remain deferred (that plan, §5).

---

## Summary

The agent is shown, once, at session start, every recipe the environment will ever
allow, whether or not the force has unlocked it; it is never told what a finished
research opened; and the API reference in its system prompt describes no entity at
all. A person at the keyboard has the opposite experience: the crafting menu shows
what is unlocked, the technology screen shows what each research will open, the
research-complete toast lists what just opened, and Factoriopedia answers any name on
demand.

**The correction: the prompt carries the invariant subset; Factoriopedia carries the
rest, gated on the force's live research state; the report says what a research
opened.** Invariant means true on the first turn and on the last: the namespace, the
views, the capability vocabulary, and complete API examples for the entities a run can
build before any science is spent. That set is a property of the technology tree, so
the prompt is identical across the turns of a run and across scenarios, which keeps
the record's one-hash assumption and the cache.

| | Now | After |
|---|---|---|
| Session-start reference | every recipe in scope, static, not research-aware; a second research-aware section beside it | the technology view: technologies in scope and the names they unlock; nothing locked is defined |
| Entity knowledge in the prompt | one sentence naming four verbs; no per-entity documentation | complete examples for the fourteen pre-science entities, generated from the registry |
| Everything else | not available anywhere the agent can read | `factoriopedia`, a tool: any name → its page, depth gated on live research state |
| After a research completes | the technology's name in the report | the technology's name and what it unlocked, one line per technology |
| Coverage | no entity class is registered with the documentation registry | every `object` class registered; the coverage validator fails on one that is not |

---

## 1. What exists today

Verified 2026-09-02/03.

- **The prompt.** `docs/system-prompt/factoryverse-system-prompt-v3-template.md` teaches
  the eight names and the affordance rule; entities appear in one sentence (`:295`)
  naming `add_fuel`, `set_recipe`, `set_limit`, `rotate`, `pickup`, `status`. Tier 5
  renders `docs/for-llms/api_reference.md` (57 KB) into it
  (`environment/config.py:921-931`, `for_run` at `:1129`): accessors, action classes,
  the two views, `EntityReference`, a generic *Entity Inspection Schema* with
  capability slots, core types. No entity class is documented.
- **The registry.** `utils/docs/registry.py` and `decorators.py` register classes,
  methods and types; `generator.py` renders; `validators.py` checks examples against
  real classes. No file under `game/factory/entity/` uses the decorators; the
  validator's class map holds `BaseEntity` only (`validators.py:612-697`). The coverage
  test has never seen an entity class — `docs/SUPPORTED_ENTITIES.md`, defect 10.
- **The first user message.** `infra/llm/context/initial_state.py:370-433` injects two
  sections once per session: `prompts/categorical.py` (every filtered fuel, recipe and
  item subgroup, no research state) and `prompts/tech_recipes.py` (technologies and
  enabled recipes from a live RCON read in a privileged namespace, `:477-548`, with a
  rendered warning that no query in the agent's namespace reproduces them).
- **Live catalogs.** `crafting.list_recipes` returns enabled recipes from the force
  (`crafting.lua:15-44`); `research.list_technologies` returns every enabled
  technology with `researched`, `available` and `unlocks` (`researching.lua:35-76`,
  `research.py:216-219`). Planning turns bind `research` and not `crafting`
  (`tiers/tier4_runtime.py:1400-1405`).
- **The report.** `game/agent/turn_report.py:259-268`: completed technology names,
  current research before and after, progress, queue length, researched count. No
  unlocks.
- **The record.** The system prompt is stored once by hash (`docs/EXECUTION.md`, Phase
  2A). A prompt that changed mid-run would break that assumption.
- **The execution path.** `execute_python` is an in-process `exec` over a namespace
  (`tier4_runtime.py:1597-1608`); the access profile is an affordance boundary, not a
  sandbox.
- **The tree.** Computed 2026-09-03: 22 recipes enabled before any research, placing
  six entities (`burner-inserter`, `burner-mining-drill`, `iron-chest`,
  `stone-furnace`, `transport-belt`, `wooden-chest`); two root technologies with no
  science cost (`electronics`, `steam-power`) unlock eight more (`inserter`, `lab`,
  `small-electric-pole`, `boiler`, `offshore-pump`, `pipe`, `pipe-to-ground`,
  `steam-engine`). The freeplay kit is one burner drill, one stone furnace and wood.

---

## 2. The decisions

Taken with the project owner, 2026-09-02/03.

1. **The system prompt is invariant within a run and across scenarios.** Nothing in it
   depends on force state. It is never rewritten after a research completion.
2. **Per-entity examples are in the prompt, and they are complete.** The agent must be
   able to expect the structure of every entity it will meet and query the API in that
   expectation. The set is the pre-science entities: those whose item is craftable from
   a start-enabled recipe or from a technology with no science cost. Fourteen today.
   Derived from the manifest per run, never hand-listed.
3. **Everything else is Factoriopedia, a tool.** The in-game mechanic is designed for a
   person; the agent's medium needs API references to complete the same act (§2), so
   the tool's pages carry the API surface as well as the game facts. Under §5 a HUD
   screen is a tool; reading it through Python would put a HUD thing on the hand.
4. **Depth is gated on the force's live research state** (§3, §12). Unlocked: the full
   page. Locked: the name, the technology that unlocks it and, by option, the recipe's
   ingredients — what the technology screen shows a person on hover. Outside scope
   (`charted`): that it exists in the world and is outside this environment. The gate
   is force state, so an all-researched task run reads everything with no scenario
   branch.
5. **The report says what a research opened.** For each technology that finished in
   the horizon: the recipes its unlock effects name, each with its product and the
   entity that product places. Prototype fact from the manifest; no live read. The
   in-game research-complete toast, and nothing more (§21).
6. **The session-start reference becomes the technology view.** The technologies in
   scope and the names each unlocks — no recipe bodies, no entity stats — plus the
   live annotation of which are researched at the stated tick. The two generators
   collapse into one over the manifest (ENTITY_SCOPE §4.4).

---

## 3. The prompt

Three parts, all rendered by Tier 5 from the registry and the manifest, none from a
hand-kept file:

- **Controls.** The namespace, the views, the idioms, the core types — what the API
  reference already carries.
- **Vocabulary.** The capability mixins, each with its verbs and reads, documented once.
  Every entity class composes from this set, so a page the agent reads later is
  recognisable: a reactor is burner plus fluid plus a few reads of its own.
- **The starting entities.** For each of the fourteen: its class, the capabilities it
  composes, and a complete, executed example of every verb it owns. `set_recipe` is
  the one capability absent from the set; it arrives with the first science
  technology, and its page is the first thing Factoriopedia will be asked for.

The set is computed, not listed: entities of standing `object` whose placing item is
reachable from start-enabled recipes plus technologies whose `unit` is absent (trigger
technologies). A scenario that changes the tree changes the set; a scenario that only
changes force state does not.

---

## 4. The tool

`factoriopedia(name, *, include_ingredients=True, include_api=True)` — one lookup, any
name the manifest knows.

| Kind | Unlocked | Locked | Charted |
|---|---|---|---|
| entity | prototype facts (footprint, energy, speed, slots), standing, its item, its class page: capabilities, every verb and read with an executed example | name, unlocking technology, ingredients of its item's recipe (option) | name, "present in the world, outside this environment" |
| item | facts, recipes producing it, what it places | name, unlocking technology, ingredients (option) | as above |
| recipe | ingredients, products, category, time, machines that run it | name, unlocking technology, ingredients (option) | not listed |
| technology | cost, prerequisites, what it unlocks, researched or not | always full: the technology screen shows every technology | not listed |
| fluid | facts, recipes producing and consuming it | as item | not listed |
| class | the class page, when any entity of the class is unlocked | name and the technologies that unlock its entities | — |

*Unlocked* is `force.recipes[*].enabled` for the recipe that produces the item, read at
call time and stated in the answer with its tick. The page is rendered from the same
registry that renders the prompt, so a verb documented in one place is documented in
both, and the honesty checks that run over the prompt run over the pages.

Not a catalog. `crafting.list_recipes` and `research.list_technologies` stay the lists
(API §2, HUD §3); Factoriopedia is the lookup. It is bound in both modes.

---

## 5. The report

One field on the research section: `unlocked`, a list of `{technology, recipes:
[{recipe, product, places}]}` for every `research_finished` in the horizon, rendered as
one line per technology. Source: the manifest. The planning turn that already follows
a research completion reads it as input (TURN §6).

---

## 6. Before believing any of this worked

| | Check | Layer | Cannot pass vacuously because |
|---|---|---|---|
| P1 | **Invariance.** The rendered system prompt is byte-identical when rendered under two different force states, and across the run's turns. | unit | two renders, two states, one comparison |
| P2 | **Starting set.** Derived from the manifest; equals the pre-science closure; exercises every mixin but `SetRecipeMixin`, asserted by name. | unit | the mixin list comes from the class tree, the set from the dump |
| P3 | **Coverage.** Every `object` class is registered; the coverage validator fails on an unregistered one; every example on every page and in the prompt executes. | unit | the validator's class map is built from the manifest's bindings, not from the registry |
| P4 | **Gating.** For a live force, a locked name's page holds no field beyond name, technology and ingredients; after the technology is researched by RCON, the full page returns. | live | the same name, before and after, on the same force |
| P5 | **Unlock line.** Equals the technology's prototype effects; appears in the report of the turn in which the completion fired. | unit, with the turn report's tests | effects come from the dump, the line from the report |
| P6 | **One generator.** The session-start reference's technologies and unlocks equal the manifest's; its researched flags equal the force at the stated tick. | live | membership from the manifest, state from the engine |

P1–P3 and P5 need no instance. P4 and P6 need a running instance and no fixture.

---

## 7. Order of work

1. **A — registry.** Register every `object` class and its methods; the validator's
   class map from the manifest bindings; every example executed. P3. Closes audit
   defect 10 and is useful before anything else here exists.
2. **B — the prompt.** Vocabulary section; starting-set section computed from the
   manifest; the four-verb sentence retired. P1, P2.
3. **C — the tool.** `factoriopedia` over the registry and the manifest, with the
   live gate. P4.
4. **D — the reference and the report.** One generator for the session-start
   technology view; the `unlocked` field. P5, P6. `categorical.py` and
   `tech_recipes.py` deleted.

A can start once ENTITY_SCOPE step B (the manifest) exists. Nothing here is behind
the Phase 4 blocker.

---

## 8. Where this lives

- `src/FactoryVerse/utils/docs/` — registration of entity classes; page rendering.
- `src/FactoryVerse/game/agent/factoriopedia.py` — the tool; bound in the runtime
  namespace for both modes.
- `src/FactoryVerse/infra/llm/prompts/reference.py` — the one session-start generator.
- `docs/system-prompt/*-template.md` — the vocabulary and starting-entity sections.
- `tests/unit/test_factoriopedia_*.py`, `tests/live/test_factoriopedia_contract.py`.

---

## 9. Related plans

- **ENTITY_SCOPE_PLAN** — substrate; §5 records this plan's direction.
- **TURN_CONTRACT §6** — the planning turn reads the unlock line; amend to name it.
- **API_AFFORDANCE_REDESIGN §2** — catalogs follow their screens; Factoriopedia is a
  screen those catalogs do not cover. Amend the tools table.
- **HUD_PARTITION §3** — same amendment.
- **Phase 3C's eight-name namespace assertion** (`tests/unit/test_docs_honesty.py`, both directions) — binding `factoriopedia` in the runtime namespace makes nine. The commit that binds it must amend the eight-name rule by name, or bind it outside the namespace; either way the plan must say which before step C starts. *(Noted 2026-09-03; unresolved.)*
- **TIER_RENAME** — Tier 5 renders three sections instead of one file.

---

## 10. Open

- **Class pages for locked families.** Decided: readable when any entity of the class
  is unlocked; before that, name and technologies only. Recorded here so it is not
  re-argued; the owner may reverse it by name.
- **Ingredients on locked pages.** An option, default on. Whether the default should be
  off for some scenario is a scenario question.
- **Whether Factoriopedia should also answer "what can I build with what I hold"** —
  that is `entity_reference` and the inventory, not this tool. Named so it is not
  added here.
