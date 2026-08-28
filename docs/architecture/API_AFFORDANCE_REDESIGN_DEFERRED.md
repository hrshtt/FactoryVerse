# The API affordance redesign — deferred holistic plan

**Status: DEFERRED.** Grounded in code reads; nothing here has been executed. Principles live in `docs/CONSTITUTION.md`.

> **Amendment 2026-08-29.** Three changes, each marked in place: (1) §3 — no HUD tools; `crafting` and `research` stay in the namespace (§2.7), and the cognitive-burden boundary moves to the two play modes in `TURN_CONTRACT_DEFERRED.md` §6. (2) §4.1 — the alert argument is rewritten around `defines.alert_type`, per `TRANSPORT_CONNECTIVITY_PLAN.md` §11. (3) A new §4.6 applies Constitution §10/§11 retroactively to every table in the map model, because the model was built before `remote_view` existed as the declared home for volatile reads. Audit corrections from 2026-08-28 are applied inline.

This plan owns the agent-visible surface as a whole. The four sibling plans own their corners in mechanism detail, and each states its own case.

## Summary

The agent-visible Python namespace has fourteen accessors. Nine of them are verbs and views that no human gesture corresponds to — flat action modules whose arguments reconstruct objects the agent already holds, a planning module that answers questions about entities from a module rather than from the entity, and a live-power checker invented to compensate for a status pipeline built in the wrong shape.

**The correction: affordance decides ownership, not just existence.** The project already grounds *what exists* in human affordance. This applies the same rule to decide *whose method it is*.

| | Now | After |
|---|---|---|
| Python accessors | `walking` `crafting` `mining` `research` `inventory` `placement` `entity_ops` `reachable_view` `resources` (alias of `reachable_view`) `remote_view` `ghost_builder` `placement_hints` `verify` `events` | `walking` `inventory` `crafting` `research` `reachable_view` `remote_view` `entity_reference` *(2026-08-29; was without `crafting`/`research`)* |
| Tools | `execute_dsl`, `execute_duckdb` (+ `respond` in assisted mode) | `execute_python`, `execute_duckdb`, `end_turn` — no HUD tools (2026-08-29) |
| Where the deleted verbs go | — | onto entity and item objects, onto the new reference object, or deleted outright |

**The second-order reason this matters is eval validity.** An API carrying a greedy set-cover pole planner cannot answer the charge that the model was handed a factory-building kit, because no human performs set-cover. An API whose every verb is a gesture can.

**Which constitutional clauses do the work here:** §4 decides the namespace; §5 decides Python versus tool; §6 decides the reference object's membership; §7 and §8 decide what may be inferred and what must be reported; §10 and §11 decide where status lives; §2 is why `walking`, the map-as-database, and the base-wide status read exist in the shapes they do.

## 1. What is wrong today

### 1.1 The same act at two altitudes, both documented

`Item.place()` delegates to the flat `placement.place`; `BaseEntity.walk_to()` delegates to the flat `walking.walk_to_entity`. **Both flat forms are in the namespace and in the generated reference**, so the model is shown two routes for one act with no rule for choosing.

They are not equivalent, and the flat route is the lossy one:

- `Item.place()` returns a reachable entity. `placement.place()` defaults to a plain struct, so the documented flat call forces a follow-up inspection before the result is usable.
- `BaseEntity.walk_to()` promotes the view from remote to reachable on arrival. `walking.walk_to_entity()` takes a name and a position — there is no object to promote, so **the dual-view invariant silently does not hold on the flat path.** An agent that walks the documented flat way arrives holding nothing it can mutate.

The flat route's own documented justification — use it when working from raw query results — is already obsolete in code: the remote view's entity query returns hydrated objects, and only the raw SQL passthrough returns dictionaries.

### 1.2 Module-owned questions about objects

`placement_hints` answers *where can this connect*, *where can an inserter go*, *what does this pole cover* — from a module, taking the entity as an argument.

Its own docstring names the affordance it is modelling: it mirrors the visual feedback human players receive — tile highlights, rotation indicators, drag lines. **That feedback attaches to the cursor and to entities. Never to a module.**

### 1.3 Status built in the database's shape, then compensated for

Three status paths coexist with opposite shapes:

| Path | Shape | Verdict |
|---|---|---|
| The snapshot mod's status walk, dumping tickstamped blocks to disk on a rolling window | tickstamped blocks of engine truth | **sound, keep** |
| The reducer that full-replaces a database table from the newest dump | polled volatile state in a database, discarding every block but one | **cut** |
| Per-entity status in the inspection and reachability payloads | live, one roundtrip each | correct |
| The batched live read behind the verify view | live, batched, one tick for many entities | correct |

**The migration to live reads already started and stalled.** One commit deleted the old status loader and added the batched verify view — but only for the power subset. The disk-to-database path and its whole feed remain live.

The rule that settles it: **nothing raises an event when a machine runs short of ingredients**, so status has no event backing and does not belong in the database (Constitution §10). Storing it produces rows that are plausibly wrong at read time, which is worse than absent — because a stale answer still renders as an answer.

### 1.4 Invented compositions

Greedy set-cover over a list of consumers. A pre-flight validation service. A walk-and-build orchestrator. **No human performs any of these gestures.**

### 1.5 A surface with no documentation at all

`events` has been in the namespace for months and appears in **zero** documentation entries. The completeness check we have runs one direction only — everything documented exists — so an *undocumented* accessor is invisible to it.

*Sharpened 2026-08-28.* `events` is absent from the generated reference and the system prompt but **is** advertised to the model in the `execute_dsl` tool description (`environment/tool_definitions.py:36`); `verify` and `ghost_builder` are the mirror case — documented in the reference, absent from that description; `resources` is in neither. And the reference's "Top-Level Accessors" table is a hardcoded string literal in `utils/docs/generator.py:75-92`, unchecked against the runtime, that names a class `Verification` which does not exist (the class is `VerifyView`). Three surfaces describe the namespace; none is derived from it.

This is a second failure mode, distinct from the hallucinated-capability one we already guard against: **dead capability** rather than imagined capability, and `events` is its live instance. It is deleted in §2.5, but the gap that hid it is the more important finding — it is why §6 adds a check in the other direction.

## 2. Python after the redesign

### 2.1 Absorbed onto objects

| Removed | Absorbs into | Exists today? |
|---|---|---|
| `walking.walk_to_entity` | `BaseEntity.walk_to()`, and the resource equivalent | ✅ |
| `placement.place` | `PlaceableItem.place()`, reached through `inventory.get_item()` | ✅ |
| `placement.remove_ghost` | `BaseEntity.remove()` — already ghost-only, already delegating | ✅ |
| `placement.set_state_barrier` | nothing. Internal test infrastructure that should never have been namespace-visible | delete |
| `entity_ops.inspect_entity` / `pickup_entity` / `rotate_entity` | `BaseEntity.inspect()` / `.pickup()`; the rotatable mixin | ✅ |
| `entity_ops.set_entity_recipe` / `set_entity_filter` | the crafter and inserter mixins | ✅ |
| `entity_ops.put_` / `take_inventory_item` | the burner mixin's fuel verbs, the crafter mixin's ingredient and product verbs, the container's store and take | ✅ |
| `entity_ops.set_inventory_limit` | `Container.set_limit()` | ❌ **build** |
| `verify.powered` | `entity.status` | route exists as `entity.inspect().status` (`entity/inspection.py:51`); there is no `.status` property on `BaseEntity` today — **build** the property over the batched read |
| `verify.connected` | comparing two entities' network ids | ✅ already redundant |
| `verify.supply_coverage` | the pole reference's supply area, plus per-entity status | ✅ substrate exists |
| `mining` | `resource.mine()` | ✅ — the HUD plan owns this |
| `ghost_builder` | direct `place()` composition | ✅ — the ghost plan owns this |
| `crafting`, `research` | tools (§3) | the HUD plan owns this |

**Verb vocabulary is frozen as it stands, with the reason attached.** Adding fuel, adding ingredients, and storing an item are **three distinct human gestures**, not naming drift. The first two are the special click, where the game reaches into your inventory and picks the right stack. The third is plain drag-and-drop. Vocabulary tracks gesture — the same reasoning that makes `mine` resource-exclusive.

**One thing must survive the verify view's deletion: its mechanism.** It uses a raw batched Lua call precisely because per-entity inspection costs one roundtrip each. Status is a live read; if status is also an entity property, reading N entities costs N roundtrips unless the batched read survives as infrastructure beneath the views. **Absorb the methods, keep the transport.** It is also the substrate the base-wide summary stands on (§4.3).

### 2.2 The entity reference object

A top-level accessor holding planning-time answers about entity types the agent does **not** hold and has **not** placed.

Membership is exactly Constitution §6: **a method belongs here if and only if a person could answer it holding the item on their cursor, with nothing placed.** The grounding is real — in Factorio the placement preview gives you legal tiles, rotation, supply-area overlays and connection highlights, all from having the thing in hand.

Initial members, lifted from `placement_hints`: connection positions for item-drop, fluid and wire; inserter placement between two entities; offshore pump sites; a pole's supply area at a candidate position and what it would cover; line and underground planning — **only after the belt plan's repairs.**

**The invariant, enforced structurally:** the reference exposes a strict read-only *subset* of the real object's surface, under **identical method names**. One vocabulary with a capability gate, never a second altitude. Placement still requires inventory. Without this it recreates the exact defect §1.1 describes.

**The boundary against Factoriopedia.** This object is for **runtime spatial inference**. Factoriopedia is *static* domain reference — limitations, recipes, prototype facts — and would need its own design. It is not invoked here and is not a substitute.

Writing that boundary down matters because the names will be confused, and because of a suggestive observation: models hallucinate a `factoriopedia.entity(...)` call unprompted. **The hallucinated shape is the natural shape.** The correction is to make it runtime, not static.

**Open, small:** for inserter positions, whose reference owns the method — the inserter's, or the source machine's. That it belongs on the reference object is settled; the specific owner is not.

### 2.3 `remote_view` — the map surface, explicitly a superset

Two distinct surfaces, documented as such:

- **The database tool** — raw SQL over the snapshot.
- **`remote_view`** — the Python spatial and live-read bridge. It owns spatial queries *and* reaches the runtime for volatile state.

It absorbs the terrain probes. Buildability is authoritative only through the engine's own placement check, and it is itself volatile — someone may have built there — so it is a live read living on a mostly-snapshot-backed object. It also owns the base-wide status summary (§4.3).

Both make Constitution §11 load-bearing rather than decorative: **every method here declares which side it read from**, live engine or snapshot, in its contract and in what the model is shown. Without that, the superset silently becomes a second, worse database — reproducing in a new location the exact failure §4 removes.

### 2.4 Deleted outright, not rehomed

| Deleted | Why |
|---|---|
| The greedy set-cover pole planner | Not a gesture. The human holds a pole, sees the supply overlay, and drags. **The overlay survives on the reference object; the optimiser does not.** The cursor shows coverage — never a solved cover |
| The batch, line and grid pre-flight validators | **The game has no validate button.** It has a red preview while you hold something, and it tells you why after you try. Try-and-be-told-why, not ask-then-do. Safe to delete because the structured failure path already exists: the placement Lua computes colliding entities, distance and terrain cause and returns them |
| The belt-flow connection type, and the inserter-reach enum membership | Phantom surface — the belt plan owns the removal |
| The `verify` module | Methods absorbed; transport retained as infrastructure |

### 2.5 `events` — deleted from the namespace, kept as infrastructure

**Deleted.** Not conditionally, and not pending the notification work.

Ask §4 what the human is holding, looking at, or reading while calling `drain()` or `subscribe()`. Nothing. Under §5, notifications arriving **between turns are the surface** — the model receives them, the way a person notices the HUD change. An in-Python subscription API is a transport channel dressed as an affordance, which is the category error this whole plan exists to remove.

**It also races with the thing the HUD plan depends on.** `drain()` is destructive over one shared queue, and the orchestrator, the actor session and agent code can all drain it. A model calling `events.drain()` inside its own code can eat the completion the orchestrator was about to inject between turns — and that injection is the partition's entire join story.

The one use that justified keeping it — a bounded in-code wait as the join channel of last resort — is now served by `await_item` (§2.6), which is better grounded: it asks a question about Python's own territory rather than exposing the event stream itself. The join reduces to the state-join, the queue read, and that wait.

**The stream survives underneath.** `EventStream` stays as infrastructure for the orchestrator to drain and inject; it loses its top-level name. Same shape as two other rulings here — `mining` stays in code without a top-level accessor, and the verify view's methods are absorbed while its batched transport survives beneath the views. **Absorb or delete the surface; keep the transport.**

### 2.6 `inventory` gains a bounded wait

`inventory.await_item(name, count=…)` bridges the boundary that opens when crafting leaves Python (§3).

It yields immediately if the items are already held, waits if the work is genuinely in flight, and at its bound **returns actuals** — how many exist, how much remains — rather than raising as though the craft had stopped (Constitution §9).

- **It cannot start anything.** It may read the crafting queue to establish that the wait is well-founded — refusing at once to wait for something nothing is producing — and may never write across that boundary.
- **There is no `await_entity`.** A furnace in your inventory is an item; it becomes an entity when placed. It returns the same type the non-blocking read returns, per §6's one-vocabulary invariant.
- **Its honesty is bounded by the completion channel underneath it.** Today that channel has no loss detection, so a dropped datagram means a wait can end while the craft completes in the world, with nothing to reconcile the two. That is the notification plan's problem to solve, and the reason it matters.

### 2.7 The resulting namespace

```
agent_id, walking, inventory, crafting, research, reachable_view, remote_view, entity_reference
```

Eight names *(2026-08-29; was six)*, and every one of them answers "which human gesture is this?" `crafting` and `research` are the two HUD queues — windows that belong to you and not to anything on the map — and they stay in Python by decision: the boundary that was to be drawn with tools is drawn instead with the planning/gameplay modes (§3). They pass §4's negative test: neither is ever parameterized by an object the agent already holds.

`walking` stays top-level because it is a **declared medium exception** (Constitution §2) — the motor loop is dropped, the destination decision kept. Not because its argument happens to be a position.

Debug-profile accessors are unchanged.

## 3. The tools

> **Superseded 2026-08-29.** No HUD tools will be built. The tool table is `execute_python`, `execute_duckdb`, `end_turn` (`TURN_CONTRACT_DEFERRED.md` §11), and it is the same in both play modes; the modes differ in what `execute_python`'s namespace binds. Constitution §5's reading "a window that belongs to you … is a tool" is narrowed: the HUD's *ownership* is expressed by the accessors `crafting` and `research` carrying no entity, never appearing on one, and reporting their completions in the turn report — not by a separate call channel. The `hand_crafting` naming rule and the catalog/per-machine split below survive as rules on those accessors. The rest of this section is kept as the record of what was decided against.

Constitution §5: **a window you open by clicking something on the map is Python; a window that belongs to you, and not to anything on the map, is a tool.**

| Tool | Human analog | Owns |
|---|---|---|
| `hand_crafting` | The personal crafting screen, hotkey-opened | The personal queue — add, clear, read progress. Time remaining is **derived from recipe energy and crafting speed**, never extrapolated from observed progress: an extrapolated estimate is a prediction, and predictions are the mirage class |
| research | The technology screen | Queue, clear, read current research |
| agent self-state | The always-on chrome | Position, health, inventory, current activity. No exact analog; a sensible helper. **Name it something other than `status`** — it collides with entity status and means something else |

**The catalogs follow their screens.** Listing technologies and listing recipes are tabs in those two windows, so they are reads on `research` and `crafting` (2026-08-29; the Lua remotes `get_technologies` and `get_recipes` already exist).

**What a specific machine can accept is not.** That question is parameterized by an entity the agent is holding, so §4 puts it on the entity. Same prototype data, two owners, split on *is this a question about an entity?*

**`hand_crafting` is a naming rule as well as a placement: the word never appears on an entity.** Setting a recipe on an assembler means clicking that assembler, and is a different act. One verb spanning the boundary teaches models to reach for the wrong surface.

The HUD plan owns the tool contracts in full.

### 3.1 What crossing the boundary costs

- **Preconditions are never cached** (Constitution §12). Crafting changes what can be placed; research changes what recipes a machine accepts. Python reads those live on every call. **"You are not holding this" becomes the primary cross-boundary failure message**, and its quality is load-bearing in a way it was not before.
- **The single-script bootstrap is gone.** A model can no longer write one script from raw ore to a working build; it must leave Python, craft, and return. That is the intended lesson — the world evolves outside your calls — but it is a real loss, recorded so nobody later "fixes" it by accident.

## 4. Entity status

### 4.1 Why bulk status exists at all

**Because the map is animated.** A person looking at their base sees slowdowns, brownouts, starved machines and saturated belts at a glance and at scale, without inspecting anything.

We have no animation channel. **A batched status read is the proxy for that glance** — which makes it a **medium-exception argument** (Constitution §2), the same family as the map-as-database. It is not an infrastructure compromise or a wart on the design. It is the design, applied.

**Alerts are a different engine mechanism, and they are discounted.** They were conflated with entity status; they are not the same thing. *Amended 2026-08-29 per `TRANSPORT_CONNECTIVITY_PLAN.md` §11:* the closing fact is the enumeration, not the gating. `defines.alert_type` has exactly seventeen values and **not one is power-related**; "not connected to power" was never an alert — it is entity status, rendered by `render_no_power_icon` / `render_no_network_icon` on the electric energy-source prototype. That cannot rot with a filter file. The earlier reasons still hold as corroboration: every alert method hangs off `LuaPlayer` and our agents are bare characters; and after `fv_filters.yaml` removes military, trains, space and the bot stack, almost nothing in the alert vocabulary applies to this scope.

**No alert work until bots exist**, at which point construction failures and destroyed entities make the surface meaningful. What the agent actually needs — *this furnace has no fuel*, *this drill has no power*, *the output is backed up* — are not alerts at all. They are entity status values, which the game renders as icons on the machine in the world, and which are fully available to us.

### 4.2 What changes, and what does not

**Only the presentation layer changes.** The status walk, its dump to disk, its rolling retention and its notify all survive untouched.

| Layer | Fate |
|---|---|
| The status walk in the snapshot mod — force-filtered surface scan, symbolic status names, entities without status naturally excluded | **keep, unchanged** |
| The tickstamped dump to disk, meta-first, with a heartbeat when empty | **keep, unchanged** |
| The rolling retention that deletes the oldest dumps | **keep** — this is the blow-up guard, and it already exists |
| The file-appended notify | **keep** |
| The reducer that full-replaces a database table from the newest dump, its schema entry, its boot load and its sync marker | **cut** |
| A raw reader over the dump files, plus the summary (§4.3) | **build** |

**The code already documents this as the original design.** The status module says in its own comments that records are written to disk with no UDP needed, and that external systems read status files on demand. **The database reducer was the later addition; removing it restores the stated intent rather than inventing a new one.**

The framing: the agent should model problems **as if debugging a running system** — a stream of tickstamped issues — and cross-reference back into the spatial model, rather than discovering problems by scanning entities one at a time. The join key is already correct and stable, because map entities are keyed by name and position, which is the never-use-unit-number rule the whole project follows.

**This is a partial decertification, not a free deletion.** Whatever verified this pipeline verified both halves together — the dump side and the reducer side. Cutting the reducer invalidates the reducer half. **Re-scope and re-run against the dump layer alone**, and retire the reducer legs deliberately rather than leaving them silently orphaned.

### 4.3 The read surface — both scales in Python

| Read | Home | Human gesture |
|---|---|---|
| One entity's status | `entity.status` | Hovering or clicking the machine |
| The base-wide summary | `remote_view`, alongside the other map-scale reads | Looking at your factory |

Both are live reads of map entities, and Constitution §5 makes Python the only channel to those. **A batched status read does not become a table because there are many of them** (§11).

**Naming carries the bridge:** the singular and the aggregate share a root, so a reader knows the base-wide summary is the per-entity fact seen at scale. The aggregate returns **which problem is happening and roughly where** — grouped by status value, with drill-down to positions. Not a flat list of entities, which would be the same data and a worse instrument.

Two reads fall straight out of the dump layer with no new machinery:

- **Current** — aggregate the newest block by status name, so "what is wrong right now" is one small payload regardless of factory size.
- **Changed** — diff two blocks to get transitions. **This is the read the debugging frame actually wants, and the reducer made it impossible.**

**The discoverability debt.** An earlier draft made the summary a tool, arguing that an agent has to know *the shape of the problems its base can have* before checking for them is a sensible act. **That argument is right and survives; the conclusion does not.** It is a discoverability need, not a channel need, and it is now owed to teaching rather than paid for with tool-list real estate.

It is the same failure the belt plan calls Category 1: **a capability nobody expects is a capability nobody uses.** If discoverability proves unmeetable through teaching, the response is to amend Constitution §5 by name — not to quietly re-promote the read to a tool.

### 4.4 History already exists, and the reducer was throwing it away

The dump layer writes a full snapshot on a fixed cadence and retains a rolling window of files. The reducer then full-replaces one table from the **newest** file, so every other block is discarded at the boundary. **The transitions the debugging frame needs were being computed away by the very step this plan removes.**

So the current-state-versus-history fork does not need deciding: **history is what exists, it is already bounded, and reading it raw is strictly more information than the table it fed.** The current-state view is a trivial derivation — the newest block — not a separate design.

Bounding on disk is solved. What is *not* solved is bounding the **context** cost: a full dump names every tracked entity, which no model should read raw. That is the summary's job, and it is a presentation problem, not a retention problem.

### 4.5 Status rides nothing

Status lands on disk and is read on demand. The only wire traffic is the file-appended notify, which rides the state channel — one of the three that are fully built.

**So this section has no dependency on the notification primitive**, and can land before, after or independently of it. With alerts discounted there is nothing left here that is notification-shaped, which is why the notification plan reserves no alert slot.

### 4.6 Retroactive membership audit of the map model *(added 2026-08-29)*

The map model was built before `remote_view` existed as the declared home for volatile, source-declaring reads, so Constitution §10 was never applied to it as a whole. This section applies it to every table, from the schema inventory taken on 2026-08-28 (`game/infra/duckdb/schema_definitions.py`; seventeen base tables, no views, one DDL site in `database.py:157`).

| Table | §10 class | Fate |
|---|---|---|
| `map_entity` | Update | stays. Two dead columns: `tile_x`/`tile_y` are declared, documented to the agent, and have no writer in any language (`apply_ops.py:250-253` omits them; the serializer's `anchor_tile` is dropped into `raw_data`) — write them or delete them |
| `ghost` | Update | stays. `placed_by` has no write path (`apply_ops.py:385`) |
| `footprint_tiles` | Update (derived) | stays. `is_ghost` is only ever written `FALSE` (`apply_ops.py:111`) |
| `inserter`, `transport_belt`, `mining_drill`, `assembler` | Update (derived) | stay. Routing is hand-listed twice, in Python (`apply_ops.py:119-179`) and Lua (`serialize.lua:17-42`), from neither the prototype pipeline nor `fv_filters.yaml`; `furnace` and `rocket-silo` get no `assembler` row though their recipe is serialized. Derive the routing once. `transport_belt` gains `belt_to_ground_type` (`TRANSPORT_CONNECTIVITY_PLAN.md` §2.2) |
| `resource_entity` | Update | stays |
| `agent_manual_production_statistics` | Update (aggregated from event-driven craft/mine records) | stays |
| `resource_tile` | Load only | stays, **but** `amount` has no update path and goes stale on the first mine. Either the resource-depletion event feeds it, or the schema notes say it is a charting-time value |
| `water_tile` | Load only | stays (immutable in practice) |
| `chunk_snapshot_meta` | Load only | stays, **but** `tick` never moves during a session (`sync._handle_chunk_init` is a no-op) while the schema notes tell the agent to trust it as a freshness marker. Fix or re-document |
| `entity_status` | **polled, volatile** | **leaves the database** (§4.2). Becomes the dump-file reader on `remote_view`, source-declared |
| `power_samples`, `power_networks` | **polled, volatile** | **leave the database.** Same mechanism: the 300-tick sampler still writes `power_networks.jsonl`; `remote_view` reads it and says so. Engine-owned network ids keep their anchor-pole identity as today |
| `agent_production_statistics` | **polled, volatile** | **leaves the database.** The force production read is one RCON call (`Agent.lua:618`); the turn report's Production row reads it live at the turn boundary and the per-agent JSONL remains the record |
| `sync_state` | infrastructure | stays; loses the `entity_status_last_tick` key |

**`raw_data` is the second half of the audit.** It carries the whole serializer payload, and inside it: `belt_data.item_lines` (items on belts — the most volatile fact in the game, on every belt row), and stored adjacency — `belt_neighbours`, `underground_neighbour`, `pipe_neighbours`, `pole_data.connected_poles`, inserter `pickup_target`/`drop_target` — which is stale by construction because a placement re-serializes only the placed entity. All of these are deleted from the serializer, not merely ignored (`TRANSPORT_CONNECTIVITY_PLAN.md` §2.1, §8.2). Adjacency is derived at read time from geometry; simulation state is read live.

**Doc drift that gates this work** (each is a §14/§15 defect: the agent is told things about the schema that are not true):

- The two component-table join examples shipped to the model use a column `entity_key` that exists in no table (`infra/llm/prompts/schema_reference.py:415,423` → `docs/for-llms/schema_reference.md`, → the system prompt).
- `docs/for-llms/schema_reference.md` is regenerated by no CLI command (`fv docs generate` writes only the API reference) and on disk documents foreign keys deleted on 2026-08-07; the system prompt embeds a fresher copy. Three surfaces, two schemas.
- No check compares the DDL with the documented schema, and no check compares documented columns with written columns. `tests/unit/test_state_tables_wired.py` checks only that each table group is created.

**Forced order.** Build the dump reader and the summary on `remote_view` first; re-point the power presentation (`remote_view.py:74-114` reads `entity_status` to render `power_networks`) at the reader; then cut the four tables, their schema entries, boot loads and sync keys together; then the turn report's Status and Production rows consume the reader (`TURN_CONTRACT_DEFERRED.md` §4). Nothing is cut before its replacement declares its source.

## 5. Refactor steps

Ordered so nothing is deleted before its replacement exists.

1. **The gates** (§6), before any deletion.
2. **Build the two missing pieces:** the container's inventory limit; the entity reference object with §2.2's membership and identical method names.
3. **Repair before absorbing.** The belt plan's read repairs — the two diagonal defects, the drifting underground distances, the stale inserter names — are **blocking**. Do not move broken reads onto a new object.
4. **Change the status presentation.** Smaller than it looks, because the dump layer is untouched: build the raw reader and the summary on `remote_view`; *then* cut the reducer, its table and schema entry, its boot load and its sync marker. Re-scope and re-verify against the dump layer alone. Make `entity.status` the sole per-entity route, which means fixing the residual place where inspection still serializes a raw status integer instead of the symbolic name.
5. **Keep the batched live read** as view infrastructure, then delete the verify module.
6. ~~**Split the tools** with the HUD plan~~ **Harden the two HUD accessors** (2026-08-29): `crafting` and `research` take the HUD plan's §2 contracts as method contracts; the catalog reads land on them; per-machine applicability lands on the entity; `await_item` lands with them; the blocking `craft()` is deleted. Then apply §4.6 to the map model in its forced order.
7. **Delete the namespace entries**, one commit per surface, each with its documentation: the flat walk, then placement, then entity operations, then the hints module, then verify, then `events`. `events` is the cheapest of them — it has no documentation to remove and no agent-facing consumer to migrate; only the accessor line goes, and `EventStream` stays wired for the orchestrator. Regenerate the reference after each.
8. **Teach.** Four plans edit the same prompt template; whichever lands later rebases. The minimum here: affordance ownership stated once as a rule the model can apply; the hydrated-versus-raw query idiom (§1.1); the reference-versus-real-object distinction; and the status idiom with its base-wide summary (§4.3, the discoverability debt).
9. **Re-run the batteries and diff.**

## 6. Before believing any of this worked

- **A baseline on the current surface.** Which of the fourteen accessors do models actually use, unprompted and then prompted? **A surface nobody uses cannot show a post-deletion regression, and one that is used needs an attributable difference.** The belt, HUD and ghost plans all want this same run.
- **Comprehension probes**, no acting: predict what `entity.walk_to()` returns and what view the entity is in afterwards; predict whether a reference-object method can place anything; predict where a status read comes from and how stale it can be; predict what `await_item` returns when its bound expires with the craft still running. **Wrong predictions mean the teaching gap dominates, and surfaces should be taught before they are restructured.**
- **Status-walk cost at scale.** The alert question is closed on engine documentation (§4.1) and the shape question is closed against what already exists (§4.4). What remains empirical is narrower: **what does a full force-filtered surface scan cost per tick at eval-scale factory size**, and do the cadence or the retention window need to move under that load? Secondary: confirm in our own image that no player object ever exists on an agent force.
- **One executed check per absorption.** Each deleted accessor gets a check that the object-level route works end to end. Cheap — they are mostly existing methods.
- **A completeness check in the other direction.** We verify that everything documented exists. Add the converse: **every accessor in the namespace is either taught or carries a reasoned exemption.** This is the gap that let `events` sit invisible for months.

Constitution §13: none of this is true until its check has been run.

## 7. Where this lives

| What | Where |
|---|---|
| The agent-visible namespace — ground truth for the surface | `environment/tiers/tier4_runtime.py` (`execute_code`, the dict at `:1416-1486`) |
| The tool table — the only definition; tier 6 registers it | `environment/tool_definitions.py` |
| The hardcoded accessor table in the generated reference | `utils/docs/generator.py` |
| A dead Factoriopedia class carrying a `system_prompt` property, zero importers | `game/factory/factoriopedia.py` |
| Schema DDL, the reducer, and the hand-written schema prose with the `entity_key` phantom | `game/infra/duckdb/schema_definitions.py`; `game/infra/duckdb/apply_ops.py`; `infra/llm/prompts/schema_reference.py` |
| Both flat forms and their object counterparts | `game/factory/item/base.py`; `game/factory/entity/base_entity.py` |
| View promotion on arrival, only on the object path | `game/factory/entity/base_entity.py` |
| Hydrated versus raw query results | `game/agent/remote_view.py` |
| Item surface — place, ghost-place, footprint, prototype, dimensions | `game/factory/item/base.py`; `game/agent/inventory.py` |
| Entity surface and its ghost-only guards | `game/factory/entity/base_entity.py` |
| Capability mixins — burner, crafter, inserter, rotatable, electric, fluid, belt, miner | `game/factory/entity/capabilities/` |
| Container operations, missing the inventory limit | `game/factory/entity/implementations/container.py` |
| Pole substrate — supply area, supply distance, wire distance | `game/factory/entity/implementations/electric_pole.py` |
| Electric state fields, carrying no status | `game/factory/entity/capabilities/electric.py` |
| The planning module and its own affordance claim | `game/agent/placement_hints.py` |
| Structured placement failures — the red preview | `src/fv_embodied_agent/agent_actions/placement.lua` |
| The batched live read, and why it batches | `game/agent/verify_view.py` |
| The status walk, dump and retention | `src/fv_snapshot/game_state/Entities.lua`; `src/fv_snapshot/utils/snapshot.lua` |
| The reducer being cut, and its table | `infra/duckdb/analytics_ops.py`; `infra/duckdb/schema_definitions.py` |
| Map entity primary key — the status join key | `infra/duckdb/schema_definitions.py` |
| Engine events already observed and converted to state | `src/fv_snapshot/game_state/Entities.lua` |
| Agents created as bare characters, with no player object | `src/fv_embodied_agent/Agent.lua` |
| Prototype scoping | `fv_filters.yaml` |

Engine research on alerts (§4.1) was read against the versioned Lua API documentation for our own engine version, not `/latest` — which answers the question differently and would be wrong for us.

## 8. Related plans

Each states its own current position; none needs amending from here.

- **`BELT_AFFORDANCE_DEFERRED_PLAN.md`** — owns `place_line`, the phantom deletions and the per-entity contracts. **Its repairs are blocking for §2.2.**
- **`HUD_PARTITION_DEFERRED_REFACTOR.md`** — partially superseded 2026-08-29 alongside §3 here; still owns the `hand_crafting` naming rule, the join contract, and the namespace-shape argument that `mining` and `entity_ops` fail.
- **`TURN_CONTRACT_DEFERRED.md`** — owns the two play modes that replace the tools, and the report that consumes §4.6's reader.
- **`TRANSPORT_CONNECTIVITY_PLAN.md`** — amends §4.1 by name; its §8 repairs block step 3; its §2.1/§8.2 are the `raw_data` half of §4.6.
- **`GHOST_SURFACE_DEFERRED.md`** — owns the ghost primitives, the builder's removal on progression grounds, and blueprints as the successor.
- **`NOTIFICATIONS_PRIMITIVE_DEFERRED.md`** — owns the completion channel. `await_item` is a dependent; status is not.
- **`TIER_RENAME_PROPOSAL.md`** — orthogonal; it renames internal layers, not the agent-visible surface.
