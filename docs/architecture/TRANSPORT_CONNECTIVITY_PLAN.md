# Transport connectivity — belts, poles and pipes, and what the map model owes them

**Status: DESIGNED, not executed.** Every engine claim was produced against
`resources/factorio-api/2.0.76/`, this install's `data.raw`, or a live 2.0.76 instance on
2026-08-28. Every measurement was produced against a real base and is reproducible from the
probes named inline. Nothing here has been built. Principles live in `docs/CONSTITUTION.md`.

**This plan supersedes `BELT_AFFORDANCE_DEFERRED_PLAN.md`** (§12), and amends
`API_AFFORDANCE_REDESIGN_DEFERRED.md` §4.1 by name (§11).

---

## Summary

Three domains — belts, poles, pipes — were never designed, because their granular
primitives are not where the meaning lives and the aggregate had no lawful home. This plan
gives them one.

**The finding that shapes everything else:** in all three domains the engine already
computes what the agent needs, we do not use it, and what we built instead is wrong in a
way no check catches. Each domain ships an artifact certifying the wrongness — a green test
whose expected value is a fabrication, a `"greedy set cover algorithm"` docstring in the
agent's prompt, a comment claiming a method does not exist thirty lines from a file that
calls it.

So most of this plan is repair, and repair needs no new design. What needs design is three
decisions (§5–§7) and one contract (§2).

| | Now | After |
|---|---|---|
| Belt connectivity | computed by the engine, shipped, dropped into `raw_data`, read by nothing | derived on demand from event-backed geometry |
| Pole wiring | re-derived from Euclidean distance, wrong on 12 of 44 poles | live read; **not derivable, and the plan says why** |
| Pipe topology | flow direction fabricated from `dx > 0` | the engine's own `get_pipe_connections` and fluid segment |
| The aggregate | a table nobody could keep fresh | a **runtime construction** — no schema, fresh by construction |
| A pre-existing base | invisible; pipeline reports healthy | ingested at boot, or the boot fails closed |

---

## 1. What was measured, and against what

The design rests on a real base rather than on fixtures, and on a ground truth authored
independently of the code being tested — which is what §14 asks for and what almost no
check in this repo has.

**The fixture.** `iron_ore_saturated 2.0`, served by
`--start-server /factorio/saves/iron-saturated.zip` at tick 1,038,547: 284 transport-belts,
44 small-electric-poles, 24 electric-mining-drills, 22 inserters, 8 fast-inserters,
10 stone-furnaces, 2 steam-engines, 2 iron-chests, 1 boiler, 1 offshore-pump. Base extent
`x = [-9.5 .. 39.5]`, `y = [-4.5 .. 77.5]`.

It contains, in one world, every case the design has to survive: a corner, a **side-load
merging two commodities onto one belt**, dual-lane runs, a three-way pole fork, long
sparse pole spans, and a full pump → boiler → engine power chain. **It contains no pipes**,
so nothing here certifies the fluid half (§7, §10).

**The ground truth.** The owner described the base in prose with coordinates before the
pipeline was run against it. That description is the oracle; the pipeline's output is under
test.

### 1.1 Belts: geometry derivation is exact

From `(position, direction)` alone — two columns already in `map_entity`, both event-backed
— a four-component decomposition of 284 belts reproduced the description exactly:

| component | belts | heads (fed by nothing) | tail | merge |
|---|---|---|---|---|
| 1 | 142 | (19.5, 10.5), (24.5, 73.5) | (26.5, 58.5) | **(39.5, 58.5)** |
| 2 | 55 | (35.5, 53.5) | (-4.5, 55.5) | — |
| 3 | 55 | (35.5, 63.5) | (-4.5, 61.5) | — |
| 4 | 32 | (19.5, 17.5) | (-7.5, 21.5) | — |

Two independent corroborations. The engine's own `total_segment_length` for the belt at
(19.5, 17.5) reports **32.2 and 31.4** for its two lanes against a derived component of
**32** — agreement to within the curve asymmetry, which is itself the answer to whether
`total_segment_length` traverses a corner: it does, and the lanes differ. And the snapshot
payload for (-7.5, 21.5) carries `outputs: {}` with coal on both lanes — the line's end, at
the boiler.

**The merge at (39.5, 58.5) is the result that matters.** A side-load — two sources, two
commodities, one belt — was the case earlier analysis called genuinely ambiguous at the
entity level and the reason to withhold an aggregate. The derivation found it, at the exact
tile, and flagged it. Single-source versus multi-source falls out for free: the merged
component has two heads and one merge point; the other three have one head each.

### 1.2 Poles: geometry derivation over-connects, and must not be used

The same derivation over 44 poles at `maximum_wire_distance = 7.5`: **32 agree with the
engine's `connected_poles`, 12 disagree — every disagreement claiming more edges than
exist.** All five fork points named in the ground truth matched the engine exactly; the
disagreements are all in the dense furnace grid around (26–34, 54–62), where poles sit
within reach of each other but were never wired.

`maximum_wire_distance` is a bound on reach, not a statement of wiring. What is actually
wired depends on placement order and on `auto_connect_up_to_n_wires` (default 5) — it is a
fact about history, not about geometry. Network *membership* still agrees transitively (all
44 are one network, and over-connection cannot split a connected graph); individual *edges*
do not.

This is the same asymmetry a player feels: belt drags are cardinal and deterministic, pole
placement is free-form and its wiring is whatever happened.

---

## 2. The contract — three categories, not two

**A fact earns a place in the map model if and only if it changes only when an entity is
placed or removed.** That is the event the database has a contract with.

| | goes | because |
|---|---|---|
| **Structure** — footprints, direction, connection points, belt topology, pole supply area | **database** | a pure function of event-backed placement facts |
| **Simulation** — items on belts, fluid in pipes, entity status, power satisfaction | **live only** | changes every tick with no event; §10, §11 |
| **History** — pole wire edges, and anything else that is the residue of a past action | **live only** | not derivable from geometry, and **no engine event reports a change** |

The first two are the owner's formulation and they are right. **The third is new, and it is
the one that would have been got wrong**, because it looks like structure. A
`pole.wired_to()` derived from wire distance would have been confidently wrong on 12 of 44
poles in the fixture, and nothing in the answer would have said so — §15 exactly.

**Verified: of 219 engine events, zero mention wire or network.** No event fires for wire
connect or disconnect, for electric-network merge or split, or for fluid-segment merge or
split. The history category has no event by construction, so it can never be a table.

### 2.1 Derive; never store adjacency

Even for structure, the edge is **derived at read time and never stored**. The reason is
measured: `Entities.lua:_on_entity_built` re-serializes only `event.entity`, so building B
beside A changes A's `belt_neighbours` and A's `belt_shape` while A's row is never
rewritten. Observed in a real checkpoint — two adjacent poles in one network, one with
`pole_data = {}` and one listing the first.

Storing adjacency would require expanding the write set to the neighbourhood on every
placement. Deriving it requires nothing, is fresh by construction, and costs one recursive
CTE. **Store the geometry; compute the graph.**

### 2.2 One column unlocks it

`belt_to_ground_type` is promoted out of `raw_data` into `transport_belt`; `loader_type` is
added beside it (*corrected 2026-08-28:* `loader_type` is not serialized anywhere today — it
is a new field on the serializer, not a promotion). Two undergrounds both facing east — one
an entrance, one an exit — are today indistinguishable in the schema, and the belt
derivation cannot bridge a tunnel without them. Both are event-backed. That is the entire
schema change this plan requires; the wider retroactive audit of the map model is
`API_AFFORDANCE_REDESIGN_DEFERRED.md` §4.6, of which §2.1 and §8.2 here are the `raw_data`
half.

---

## 3. The construction

The aggregate is a **runtime object**, not a table and not a stored noun: an accessor that
composes derived structure with live reads and **declares, per method, which side it read
from** (§11).

This dissolves the objection that killed the aggregate in earlier analysis. A stored
component has an unstable key — adding one belt merges two components, removing one splits
them — and no engine id to anchor to. A computed component has no key to be unstable,
because it does not persist between calls.

```
transport.line(entity | position)     structure   derived from map_entity
transport.lines()                     structure   every component, with heads/tails/merges
transport.shares_line_with(a, b)      structure   derived; live cross-check available
belt.contents                         live        get_transport_line(i).get_contents()
belt.saturation                       live        items / (4 · length), per lane

power.network(pole)                   live        electric_network_statistics — engine puts it on the pole
power.networks()                      live        the same read, batched
pole.wired_to()                       live        real_connections — HISTORY, never derived
pole.covers()                         structure   supply box ∩ collision box, from geometry
pole.can_wire_to(other)               live        can_wires_reach — engine truth

fluid.segment(entity, box)            live        get_fluid_segment_id / _contents / _extent
entity.ports()                        structure   get_pipe_connections, with fungible groups
```

**Naming obeys §11**: the singular and the aggregate share a root, so a reader knows the
base-wide read is the per-entity fact at scale. This also repairs a violation already
shipped — singular `electric_network_id` / `powered` against aggregate `power_networks`,
roots that do not match.

**Deliberately absent.** No `throughput` — it has no engine source and would have to be
manufactured by diffing `DetailedItemOnLine.unique_id` across ticks, an instrument with no
human counterpart, since a person cannot perceive item identity. No `bottleneck` — that is
a diagnosis, and §2 forbids abstracting a deliberation. Named so nobody rediscovers them.

**The line this plan defends:** *the read may tell the agent what it would see; it may not
tell the agent what it would conclude.* Saturation is what a human reads off the animation
and we have no animation — a channel abstraction, lawful under §2. Attributed bottleneck is
the reasoning under measurement.

---

## 4. What the agent is not given a noun for

`transport.line()` returns a component with its heads, tails, merge points and per-lane
contents. **It is not a `BeltLine` object the agent holds.** The distinction is not
cosmetic: `LuaTransportLine` already means *one lane of one entity*, `place_line` already
means *a straight run being built*, and to a Factorio player "belt line" reads as a straight
leg — which a component through a splitter is not. Three meanings for one word, in a system
whose failures are overwhelmingly about the surface saying something untrue.

The component is a **read result**, named for what it is (`line`, `lines`), never a handle
that persists across turns.

---

## 5. Decision — belts

Ship `transport.line()` / `transport.lines()` / `shares_line_with()` as derived reads, plus
`belt.contents` and `belt.saturation` as live per-entity reads.

**`belt.contents` is a two-line repair, not a design.** `inspection.lua:657` has the live
read commented out under a comment claiming `LuaTransportLine` has no `get_contents()`
method. It does, and `serialize.lua:196` calls it successfully in a sibling file. `BeltState`
has no contents field of any kind, which today makes the belt aggregate the only one in the
system whose singular does not exist. That must land first: §11's naming rule cannot even be
applied until it does.

---

## 6. Decision — poles

**`pole.wired_to()` is a live read and is never derived.** §1.2 is the evidence and §2 is
the rule.

For placement, the human gesture is a drag, and §7 admits it: spacing is a prototype
constant and the nudge off a blocked tile is a collision response, so the collapsed sequence
contains no decisions. But it decomposes into two halves that belong on different surfaces,
which is what the free-form nature of pole placement forces:

- **`remote_view` answers where the poles would go** to connect A to B — a read, computable
  before anything is held, returning a validated position list.
- **The pole item places them** — `pole_item.place_line(positions)` or
  `(start, end)` — walking and placing until the end is reached, returning actuals per §8:
  what was placed, the first blocker with its reason, and the resume point.

**The honesty problem, stated plainly:** there is no drag-building API in 2.0.76.
`build_from_cursor` is `LuaPlayer`-only and a bare character has none; the only trace a drag
leaves in Lua is `on_pre_build.created_by_moving`, after the fact. So whatever is built is
**our arithmetic wearing the engine's name**, and a unit test over our own spacing formula
is the §14 vacuous green by construction. The only check that distinguishes replication from
resemblance is a **differential against a real human drag** on a live client (§9).

Three conditions or it is unlawful: straight runs only (a bend is §7's router); §8 returns;
and it never becomes a coverage solver. `get_pole_coverage_plan` — documented to the model
as `"greedy set cover algorithm"`, actually a centroid loop that returns a tuple with
`valid=True` hardcoded and can return zero positions while claiming valid — is deleted.

---

## 7. Decision — pipes

`fluid.segment()` mirrors `get_fluid_segment_id` / `get_fluid_segment_contents` /
`get_fluid_segment_extent_bounding_box`, which exist in 2.0.76 and have **zero occurrences
anywhere in `src/`**. It is the structural analogue of `electric_network_id` and strictly
better, because contents and extent come with it.

The payoff is one integer: **`place` returns the segment-id delta**, so *"did my pipe
actually connect, or is there a one-tile gap"* — the dominant real failure in this domain —
becomes an answer instead of an eyeball.

**Condition: it must be a mirror, not a derivation.** If the implementation walks pipe
adjacency in our own code rather than asking the engine, it has become the belt-line mistake
with better presentation. And it **replaces** the `dx > 0` flow fabrication rather than
sitting on top of it.

`entity.ports()` exposes what `get_pipe_connections` already returns per port — position,
`target_position`, `flow_direction`, fluidbox and connection index — with fungible groups
computed from same-box/same-flow/same-filter. The prototype work is done (§8.3): four
symmetry classes, an exact fungibility table, and the fact that a crafting machine's ports
merge under a one-fluid recipe, which makes fungibility a property of `(entity, recipe)` and
a cached `fluidbox_index` a latent lie.

**Unproven.** The fixture has no pipes. Everything in this section is grounded in the spec
and the prototype dump and in **no live measurement at all**. §9 lists what would settle it.

*Fixture found 2026-09-04.* `starter-base-test` (the baseline in
`.fv-output/baselines/starter-base-test/`, `md5 0725198e…`) carries what `iron-saturated`
lacks: 120 `pipe`, 284 `pipe-to-ground`, 7 `storage-tank`, 7 `offshore-pump`, 38 `boiler`,
76 `steam-engine`, 6 `pumpjack`, 5 `oil-refinery`, 11 `chemical-plant`, and the engine
reports **13 fluid segments** (`fluidbox.get_fluid_segment_id`) over them. The oracle for
this section's derivation is that engine read, taken live, the way §1.1's belt oracle was
the owner's description: derive the segments from geometry, compare to the 13 the engine
names, and the diagonal and fungibility cases in §7 either hold or they do not. Nothing in
§7 is proven until that comparison has run. `iron-saturated` stays the belt oracle (§1.1).

---

## 8. The repairs

Each verified directly. None needs a design decision; several are blocking for
`API_AFFORDANCE_REDESIGN_DEFERRED.md` step 3 ("repair before absorbing").

### 8.1 Checks that certify a fabrication

- **`tests/unit/test_loader_stale_updates.py:131`** — a passing test named *"stale
  pipe_neighbours must NOT win"* asserts `sorted(names) == ["boiler", "pipe"]` on
  `pipe_data.pipe_neighbours.inputs`. The boiler is under `inputs` because
  `_serialize_pipe_data` files **every** non-pipe neighbour as an input. The expected value
  *is* the defect. §14 verbatim.
- **`serialize.lua:258-273`** — the fabrication: `dx > 0 or dy > 0 → inputs, else outputs`.
  Both `pipe` and `pipe-to-ground` have `production_type = none` and every port
  `input-output`, so the distinction being computed does not exist in the domain. It uses
  `get_connections` rather than `get_pipe_connections`, discarding `flow_direction`,
  `position`, `target_position` and `connection_type` — every field that would have made the
  split real.

### 8.2 Volatile state in the map model

- **284 of 284 belts carry `belt_data.item_lines` in `map_entity.raw_data`** — measured on
  the fixture. Items on a belt are the most volatile fact in the game. It costs `1+N`
  blocking engine calls per belt per snapshot and is read by nothing. Delete the computation,
  not just the column.

### 8.3 Phantoms in surfaces the agent is told to use

- **`map_entity.tile_x` / `tile_y`** — declared in the DDL, documented to the agent in
  `schema_reference.md`, never written. Measured on the fixture: **0 of 398 populated**.
- **`FluidMixin.get_fluid()`** — `return None`, unconditionally, with a placeholder comment,
  under a docstring promising *"FluidBox if found."* On every fluid entity.
- **`"greedy set cover algorithm"`** ships to the model at `api_reference.md:2423` from
  `reference/placement.py:386`. §2.4 of the API plan says carrying a set-cover planner is
  what makes the eval indefensible; the code is not even one.
- **`tool_definitions.py` names 11 namespace objects; the namespace binds 14** —
  `ghost_builder`, `verify`, `resources` unmentioned, with no check in either direction.

### 8.4 Two sensors that disagree

The engine rule is *collision box intersects `pole.position ± supply_area_distance`* — a
square, box-vs-box. `verify_view.compute_supply_coverage` is correct;
`remote_view._find_covering_pole` uses a square against centre points;
`placement_hints` L1290 and L1414 use a **circle** against centre points. The inscribed
circle misses ~21.5% of the area — every corner. A 3×3 assembler at `dx = 4.5` from a medium
pole is powered by the engine and reported uncovered by `placement_hints`.

### 8.5 Engine truth available and unused

`can_wires_reach` · `is_connected_to_electric_network()` · `LuaWireConnector.network_id` /
`can_wire_reach` / `have_common_neighbour` · `get_fluid_segment_id` / `_contents` /
`_extent_bounding_box` · `LuaTransportLine.line_equals` / `total_segment_length` /
`input_lines` / `output_lines` · `loader_container` · `update_connections` ·
`on_object_destroyed`. All in 2.0.76; all zero occurrences in `src/`.

### 8.6 Others, verified

- `get_pole_coverage_plan` returns a tuple (so `plan.valid` raises `AttributeError`), sets
  `valid=True` unconditionally without ever calling `plan.validate()`, and can return
  `positions=[]` while claiming valid.
- `_transform_electric` — `if not energy_data: return None`. A machine at **zero energy**
  loses its `ElectricState` and its network id. The unpowered machine is the one that
  vanishes.
- **`force = "player"` hardcoded at six sites** in `fv_placement_hints/connections/init.lua`
  (143, 270, 356, 580, 701, 715). Agents run on `agent-{id}` forces.
- `entities_in_supply_area` counts every player-force entity in a square bbox — belts,
  chests, walls, other poles — with no electricity filter, under a docstring calling it
  "entities that would be powered".
- **`not_plugged_in_electric_network`** — the producer-side warning, "Used by generators and
  solar panels" — has zero occurrences in `src/`. A steam engine wired to nothing is
  diagnosed as fine. (`defines.entity_status` has 67 values; four are power-related; we read
  one.)
- **Underground spans**: prototype 5 / 7 / 9 (belts) and 10 (pipe-to-ground); code hardcodes
  4 / 6 / 8 / 10. Two different prototype fields, so **no single rule replaces the dict** —
  the semantics must be resolved per field. The unknown-name fallback is `10`, and there is
  no axis validation, so a diagonal call emits two ghosts that can never pair.
- **`pipe-to-ground`'s two ends face away from each other** — port 1 is the mouth at
  direction 0, port 2 is the tunnel at direction 8. `get_underground_segment` applies one
  `opposite_dir` rule to belts and pipes alike, which cannot be right for both.
- `FLUID_PIPE_ENTITIES` omits `heat-exchanger`, `assembling-machine-2`/`-3`,
  `electric-mining-drill` and all three valves, where
  `prototypes.entity[name].fluidbox_prototypes` is the derivation.
- **Missing event registrations**: `on_player_flipped_entity`, `script_raised_revive`,
  `on_robot_built_entity`, `on_entity_cloned`, `script_raised_teleported`. The interactive
  REPL puts a human at the keyboard who can flip a splitter, and the map model never learns.
  **A derived view over an incomplete event set is a floor that lies** — this is a
  prerequisite, not a follow-up.

---

## 9. Before believing any of this worked

**Live checks the design rests on, none answerable from the spec.**

1. **Underground pair rotation.** Does rotating one end flip `belt_to_ground_type` on both
   ends while only one entity gets an event? If yes, the one column §2.2 adds is the one
   that goes stale, and `_on_entity_rotated` must re-serialize `neighbours` too.
2. **Fluid segment nil cases.** Does a boiler, storage-tank, pump or chemical-plant box get
   a segment id or `nil`? The spec's third caveat is unenumerated and §7's reach depends on
   it. **Blocked on a fixture with pipes** — the current one has none.
3. **The pole drag differential.** Drag N start/end pairs including blocked tiles on a live
   client, dump the positions, run ours on the same pairs, require agreement within a stated
   tolerance. Without this, §6 is unfalsifiable.
4. **Do ghosts answer `can_wires_reach`?** Ten minutes, and it decides whether ghost-based
   pole planning is available.
5. **Underground span semantics.** Place at exactly the prototype maximum and at maximum+1,
   for both `pipe-to-ground` and `underground-belt`. Settles centre-to-centre versus gap per
   field and proves or kills the off-by-one.

**Regression checks the derivation owes.**

6. **The fixture is the certification instrument.** `iron_ore_saturated 2.0` with the
   ground-truth decomposition in §1.1 becomes a live test: four components, those heads and
   tails, that merge point. It cannot pass vacuously — an empty derivation fails it.
7. **The neighbour-invalidation check.** Place belt A, read its row; place B orthogonally so
   A curves; assert **A's derived component changed** without A being touched. This is the
   check that proves derivation beats storage, and it is the one a stored-adjacency
   implementation cannot pass.

**Prerequisites that are not design questions.**

8. **A belt baseline needs its own task.** `iron_plate_throughput` pre-seeds boiler ×2,
   offshore-pump ×2, steam-engine ×2, transport-belt ×500, medium-electric-pole ×500,
   coal ×500, burner drills and stone furnaces, with all technologies researched. Burner
   drills and stone furnaces are fuel-driven and a drill's item-drop feeds an adjacent
   furnace directly, so **16 plates/60s is reachable with zero electricity and zero belts.**
   A baseline run on this task produces a null that looks like "belts don't help". The
   baseline needs a forced ore→smelter gap.
9. **The documentation coverage check must go red first.** It reports 87.3% with 9
   undocumented methods and `complete = False`, and passes because the test asserts
   `total_methods > 0` and never reads `complete`. `CoverageValidator.assert_complete` has
   zero callers. Four plans edit the same prompt; none should be built on a check that
   passes vacuously.

Constitution §13: none of this is true until its check has been run.

---

## 10. Teaching

**Verified across every prompt any model actually received: 102 captured system prompts,
10 contain a worked pattern, all 10 are about power, and 0 have ever contained one for
belts.** Oracle usage tracks teaching, not availability: `find_offshore_pump_sites` 37 uses,
`get_placement_line` 36, `supply_coverage` 28, against `diagnose_power` 5,
`evaluate_pole_placement` 4, `get_underground_segment` 4.

And the experiment already ran on the neighbouring affordance. In
`docs/runs/2026-07-12-engine-unit-terra-pro-attempt5.md` every pole aggregate existed, the
model made **zero calls** to any of them and placed 26 poles blind — classified in the doc's
own words as *"the discoverability class (documented-but-never-reached)"*. A ~270-token
prompt change produced `verify.supply_coverage` ×6 including pre-placement checks, with the
loop *"exercised end-to-end without any of it being forced"*.

**The aggregate produced zero uplift; the teaching produced all of it.** So teaching is not
the last step of this plan, it is a parallel track that must land with the surface:

1. The three-category contract in one sentence the model can apply — structure is queryable,
   simulation is read live, and every method says which it used.
2. A worked belt pattern, parallel to the power chain: drill → item-drop cue onto a belt →
   pre-check the run → place → **verify the component** → inserter bridge into the consumer.
3. Direction semantics in two sentences, and the underground pair convention, which is the
   reverse of the intuitive one.
4. The distance cue. The 2026-08-25 run's §5 records an agent building extraction ~100 tiles
   from its consumers, failing to walk between them four times, and never considering
   connecting the two. **Nothing teaches an agent to notice it now has a distance problem**,
   and that sits above every surface-shape document including this one.

---

## 11. Amendments to other plans

**`API_AFFORDANCE_REDESIGN_DEFERRED.md` §4.1 — the alert argument is right and its stated
reason is the weaker of the two available.** That section discounts alerts because the alert
API hangs off `LuaPlayer` and our agents are bare characters. Verified: eleven alert methods,
all on `LuaPlayer`, none on `LuaForce`/`LuaSurface`/`LuaGameScript`. But that rests on a
filter file and a gating accident, so it reads as reversible.

It is not. **`defines.alert_type` has exactly 17 values and not one is power-related.** The
"not connected to power" warning was never an alert — it is entity status, rendered by
`render_no_power_icon` / `render_no_network_icon` on `LuaElectricEnergySourcePrototype`. A
player object would not have helped. Rewrite the clause around the enumeration, which cannot
rot.

**`SCENARIO_BOOT_CONTRACT_DEFERRED.md`** gains a sibling defect and should absorb it. That
plan shows no boot asserts *which scenario loaded*; the measurement here shows no boot
asserts *that the world was ingested*. See §13.

---

## 12. What this supersedes

`BELT_AFFORDANCE_DEFERRED_PLAN.md` is absorbed. Its three-category gap analysis was right
and is preserved in substance; what changed is scope and evidence:

- Its §4 repairs are a subset of §8 here, which spans all three domains.
- Its `place_line` is one gesture with three riders — belt (directed per tile), pipe
  (undirected entirely; the API should **refuse** a direction argument rather than accept
  and ignore it), pole (spaced, and split across two surfaces per §6).
- Its central contract was downstream of a semantic decision it did not contain: what a belt
  *is* to a reasoning agent. §1.1 and §3 answer that with measurement.
- Its §4 item 6 asked whether the hardcoded underground distances were drift or a
  deliberate gap-versus-centre encoding. Answered in §8.6: neither, uniformly.

**What survives standalone and is carried forward:** its teaching section (§10 here) and its
§6 baseline gate (§9.8 here), which is upstream of all three domains.

---

## 13. The snapshot boot contract

**The snapshot pipeline can only ingest a world it watched get built.** Loaded onto the
fixture — a save charted long before the mods existed — it captured **0 chunks, 0 entities**,
and reported `system_phase = MAINTENANCE`, which is the healthy value. Forcing
`snapshot_area` by hand ingested all 404 entities in ~4 seconds.

Two defects, one root cause:

1. **Chunk discovery is event-only.** `ChunkTracker.chunk_lookup` is populated exclusively
   by `on_chunk_charted` handlers, which never fire for an already-charted world.
   `trigger_initial_snapshot()` drains `deferred_chunks`, populated by the same handlers, so
   it is a no-op — returning `success = true`.
2. **`has_tracked_entities` is written only on the charted path** (`Map.lua:2037`, `:2089`).
   After a successful forced snapshot: 30 chunks tracked, 30 with `snapshot_tick` set,
   **0 flagged**, 10 actually containing entities, `get_charted_chunks()` → **0, forever**.

**Why it survived:** `control.lua:117-123` calls two functions with the same argument.
`track_all_charted_chunk_entity_status` iterates it and is dead; `dump_status_to_disk` →
`collect_all_statuses_for_dump` **ignores** it and is alive, because this exact defect class
was found in July 2026 and repaired at that one call site — the comment is still there
(`Entities.lua:169-176`). The patched path is the one that writes the files, so from outside
the system looks healthy.

**The fix shape, measured.** One pass over `surface.get_chunks()` filtered by
`force.is_chunk_charted` yields `charted=427, with_tracked_entities=10, with_resources=16,
with_water=3` — 427 charted chunks reduce to 10 needing an entity snapshot, so cost is
bounded by what is there, not by the 1360 generated. Three independent changes: a boot
reconciliation pass on `on_init` **and** `on_configuration_changed` (the case that matters,
since adding mods to a save fires exactly that); moving the `has_tracked_entities` write out
of the charted handlers to wherever a chunk entry is created; and making the phase machine
distinguish "nothing to do" from "nothing was asked".

**This is a prerequisite for the fixture**, and the fixture is the only way to certify
connectivity at scale. Full characterisation, with probes, in the companion note.

---

## 14. Order of work

Ordered so nothing is deleted before its replacement exists, and so the honesty repairs land
before the surfaces that would stand on them.

1. **The vacuous checks go red** (§9.9) and the missing events are registered (§8.6). Both
   are prerequisites for believing anything downstream.
2. **The fabrications are deleted** (§8.1, §8.2) and the phantoms removed (§8.3).
3. **The snapshot boot contract** (§13), which unblocks the fixture.
4. **The fixture becomes a check** (§9.6) — the four-component decomposition as a live test.
5. **`belt.contents`** (§5), the singular that §11 requires before any aggregate is nameable.
6. **`belt_to_ground_type` into the schema** (§2.2), then the derived component.
7. **The construction** (§3), one domain at a time — belts first because they are certified,
   poles second, fluid last because it is unproven (§7).
8. **The placement gestures** (§6), each behind its differential check.
9. **Teaching** (§10), landing with the surface rather than after it.
10. **Re-run the batteries and the fixture check; diff.**

---

## 15. Open

- *Attribution note, 2026-09-03:* Phase 4A shipped the derived read and the §10 teaching in one commit, so the §9.8 baseline can no longer separate surface uplift from prompt uplift. The unprompted/prompted comparison still runs; what it measures is the pair. Say so when reporting it.
- Whether the belt aggregate is needed **at all**. §9.8's baseline has not been run, and §10
  shows the neighbouring affordance answered "teaching, not surface".
- `get_max_transport_line_index()` per entity type. The spec pins the ten
  `defines.transport_line` names and 1-indexing but never the per-type maximum; splitter is
  8 or 10.
- What `entire_belt_hold` aggregates — the closest thing to a human referent for a belt
  aggregate, shipped with an empty description and gated behind `circuit-network`, which
  `fv_filters.yaml` excludes.
- `track_coverage_during_drag_building` — the only prototype hook named for the pole drag
  helper, shipped with an empty description. **Do not build on it without a check.**
- Whether 2.0's pipe UI shows a whole segment on hover. If it does, `fluid.segment` is a §5
  window; if not, it is a §2 medium exception and must be argued as one.
- Whether the boot pass snapshots resource and water chunks eagerly (16 and 3 on the
  fixture, cheap; unbounded on a wider-explored map) or lazily on first query.

---

## 16. Where this lives

| What | Where |
|---|---|
| Belt / pipe / pole serialization, and the `dx > 0` fabrication | `src/fv_embodied_agent/utils/serialize.lua` |
| The commented-out live belt contents read | `src/fv_embodied_agent/agent_actions/inspection.lua` |
| Chunk tracker, charted handlers, `has_tracked_entities` | `src/fv_snapshot/game_state/Map.lua` |
| The status walk and its L1.17 scope note | `src/fv_snapshot/game_state/Entities.lua` |
| Reducer, derived component tables, `raw_data` | `src/FactoryVerse/game/infra/duckdb/apply_ops.py` |
| Schema, and the dead `tile_x` / `tile_y` | `src/FactoryVerse/game/infra/duckdb/schema_definitions.py` |
| Pole coverage, three disagreeing implementations | `game/agent/placement_hints.py`; `game/agent/verify_view.py`; `game/agent/remote_view.py` |
| Fluid solver (correct) and the `(0,0)` fabrication | `src/fv_placement_hints/connections/init.lua`; `utils/entity_lookup.lua` |
| Hardcoded underground distances, `FLUID_PIPE_ENTITIES` | `game/agent/placement_hints.py` |
| The test whose expected value is a fabrication | `tests/unit/test_loader_stale_updates.py` |
| Vendored engine spec — the authority for every claim here | `resources/factorio-api/2.0.76/` |
| The fixture | `.fv-output/server_0/saves/iron-saturated.zip` |

## 17. Related plans

- **`API_AFFORDANCE_REDESIGN_DEFERRED.md`** — parent. §8's repairs are blocking for its
  step 3; its §2.2 `entity_reference` gains an exact spec from §7 (ports, fungible groups,
  symmetry classes); its §4.1 is amended by name in §11 (applied 2026-08-29); its new §4.6
  owns the table-level audit that §2.1/§8.2 here are the `raw_data` half of.
- **`GHOST_SURFACE_DEFERRED.md`** — its §2 keeps the `placement_hints` generators "as reads";
  those reads are what §3 replaces. Gate 4 in §9 decides whether ghosts can serve as the
  pole-planning cursor.
- **`SCENARIO_BOOT_CONTRACT_DEFERRED.md`** — §13 is a sibling defect in the same family and
  belongs in its Stage 0 probe.
- **`NOTIFICATIONS_PRIMITIVE_DEFERRED.md`** — its `new_epoch` fires on `on_init` and
  `on_configuration_changed`, the same two hooks §13's boot pass needs. One handler, two
  jobs.
- **`TURN_CONTRACT_DEFERRED.md`** — the turn report's Map section is a diff over the map
  model this plan defines; no conflict.
