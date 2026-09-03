# Supported entities

What the agent can do with each entity in the game, and what it cannot do with the rest.
Measured 2026-09-02 on branch `prompt-audit-fixes` against `factoriotools/factorio:2.0.76`,
base mod only.

This page is a measurement, not a design. It says where the tree stands; the plans in
`docs/architecture/` say where it is going, and `docs/EXECUTION.md` says how far along it
is. A row here is evidence only to the extent the "Certified by" column names something
that was run (Constitution §13).

Every entity is referenced by `entity_name` + position. `unit_number` appears nowhere.

---

## How this was measured

The denominator is the set of prototypes that derive from `EntityPrototype`, taken from the
inheritance tree in `https://lua-api.factorio.com/2.0.76/prototype-api.json` — 133 of the 278
prototype classes. Intersected with the installation's own dump, that is **567 entities** across
118 prototype types.

Two caveats about the dump, both real:

- `PrototypeDataManager` loads `.fv-output/factorio-data-dump.json`, which has **213** top-level
  prototype types where the raw `data-raw-dump.json` has **224**. Pruning drops whole types,
  not just fields; four of the eleven missing are entity-derived (`corpse`, `character-corpse`,
  `smoke-with-trigger`, `rocket-silo-rocket-shadow`). The counts here use the raw dump.
- The dump was taken with the DLC data directories present, so it contains prototypes the
  running world does not build from. Attribution against `wube/factorio-data` at tag `2.0.76`
  puts all 567 in `base` (566) or `core` (1) — including `lane-splitter`, `cargo-landing-pad`
  and the three valves, which are vanilla 2.0 additions rather than Space Age content, and the
  `dummy-elevated-*` rails, which are inert base stubs. **No entity in this table is
  unreachable because of a disabled mod.**

To regenerate: the scripts that produced the tables are `extract_universe.py`, `classify.py`
and `gen_doc.py`. They read the dump, import `ENTITY_CLASS_MAP` from the tree, and run the real
`FilterConfig` — nothing here is transcribed by hand.

---

## Three gates, and they do not agree

Support is not a ladder, because three independent mechanisms decide what an entity is, and no
two of them were reconciled against each other.

**Gate 1 — capture.** `fv_snapshot` decides what reaches the database. It reads no name list at
all. `utils/forces.lua:11-30` tracks the `player` force plus agent forces, never `neutral` and
never `enemy`. `game_state/Map.lua:1249-1278` scans that force set into `map_entity`, dropping
`character` and routing `entity-ghost` elsewhere. `game_state/Resource.lua:136-192` is the only
neutral-force path, and it admits exactly four things: `type=resource`, `type=tree`,
`type=simple-entity` whose name contains `rock` or `stone`, and water tiles. DuckDB ingestion
applies no name filter of its own (`apply_ops.py`), and `map_entity.entity_name` is plain
`VARCHAR` with no enum (`schema_definitions.py:62-66`).

**Gate 2 — typing.** `ENTITY_CLASS_MAP` (`create_entity.py:93-165`) decides what becomes an
object with accessors. There is no fallback: an unmapped name raises `ValueError`
(`create_entity.py:206-212`).

**Gate 3 — the documented set.** `fv_filters.yaml` decides what the prototype accessors and the
generated docs call "known" — 73 names. It governs `EntityPrototypes` and `is_valid_entity_id`.
It does **not** govern capture, and it does **not** govern typing.

**What Gate 3 actually delivers is not an entity list.** At runtime the agent is never handed an
enumeration of placeable entities. `get_filtered_entities()` has no caller in any prompt or
doc-generation path; its consumers are `prototypes.py` and `factorio_types.py` — the DuckDB and
`EntityPrototypes` machinery. What the agent receives is a categorical **item and recipe**
reference, built fresh each session by `CategoricalReferenceGenerator.generate_combined_reference()`
(`infra/llm/prompts/categorical.py`, called from `initial_state.py:420-429`) and injected as the
first *user* message, not in the system prompt. Entity names in the system prompt template and in
`api_reference.md` appear only as prose or code examples. So an entity becomes visible to the
agent by way of *its item*, which is why the item filter — not the entity filter — decides what
the agent knows it can build. Nothing on this path reads the static snapshots in `docs/for-llms/`;
Tier 5 regenerates them in-process, so those files can go stale without affecting a run.

The gates overlap and none contains another. An entity can sit in the database and be absent
from the API; it can be typed and absent from the filter; it can pass the filter and be
neither captured nor typed.

---

## The categories

| Tier | What it means | The mechanism that draws the line |
|---|---|---|
| **T4 — Derived** | A typed object that also participates in derived topology: `transport.line()` reads its connectivity live from the map model rather than from stored adjacency. | In `ENTITY_CLASS_MAP`, and its prototype type is routed into the `transport_belt` component table (`apply_ops.py:163-170`). |
| **T3 — Typed** | A real object. Accessors, capability mixins, live state reads, configuration verbs owned by the object (Constitution §4). This is what "supported" means without qualification. | Present in `ENTITY_CLASS_MAP`. |
| **T2a — Charted, untyped (gap)** | In the database and queryable by raw SQL, and the filter claims the system knows it — but no class exists, so it can never be held as an object. **This tier is a defect, not a decision.** | Passes `fv_filters.yaml`, absent from `ENTITY_CLASS_MAP`. |
| **T2b — Charted, excluded (by design)** | In the database and queryable by raw SQL. Deliberately outside the agent's scope: trains, circuits, logistics, military, robots. | Captured by Gate 1, excluded by `fv_filters.yaml`. |
| **T1 — Invisible** | A real entity that exists in the world and that no gate captures. It is not in the database, not in any view, and not in the API. Nothing the agent can read will mention it. | Enemy force, or neutral force outside the four `Resource.lua` rules. |
| **T0 — Not a world object** | Visual effects, ordnance in flight, remnants, engine proxies, and inert stubs. Never a persistent thing standing on the map. | Prototype type is an effect type, or the name is a known stub. |

T2a and T2b are the same mechanically. They are split because one is a decision the project made
and the other is a hole the project did not notice.

---

## Scope policy — why entities are excluded

The exclusions in `fv_filters.yaml` are deliberate, and they are the project owner's, recorded
here 2026-09-02 because they are design intent that no file in the tree states:

1. **Enemies are not part of the game we are building.** Biters are not integrated for agents,
   so military entities — and the wall/gate family that exists to answer them — fall out on top
   of that.
2. **End-game entities are deferred for bandwidth**, not rejected. Nobody had time to design and
   implement them.
3. **Parameter entities look like development overhang** — stubs rather than real entities,
   whose purpose is not understood.
4. **Trains are deferred completely**, as a very large integration that may never be enabled.
5. **Robots were deferred alongside trains, and are now a primary priority** to implement and
   integrate.

These justify a *placement* interface that omits those entities. They say nothing about whether
the same names are needed as **items**, and that distinction turns out to matter — see the next
section.

### Decisions of 2026-09-02

Taken by the project owner after the reachability run below, and binding on the filter:

- **Target state for a freeplay run is a rocket launch carrying a satellite** — the full
  base-game win. This lifts criterion 2's deferral for the rocket chain specifically, and puts
  `radar`, `solar-panel` and `accumulator` on the critical path as satellite ingredients.
- **`rail` becomes a craftable item with no placement interface.** Criterion 4 stands for
  placement: no rail entity class, no signals, no stops, no locomotives. The item exists solely
  so production science packs can be assembled. This is the first case where the item surface
  and the entity surface are deliberately different, and it is the reason they must stop being
  derived from one another.
- **`gate`, `stone-wall` and `land-mine` leave the scope entirely**, per criterion 1. They are
  removed from the documented set rather than given classes, which drops three of the sixteen
  advertised-but-unusable entities.
- **No code changes yet.** This page records the work; the tree is unchanged.

**Where the tree does not match the policy:**

- `land-mine` reaches the documented set through the `defensive-structure` subgroup, though
  criterion 1 excludes military and its recipe is filtered out. It is advertised and unusable.
- `gate` and `stone-wall` are likewise advertised (T2a) rather than excluded. Under criterion 1
  they should not appear at all.
- Criterion 3 is confirmed: `parameter-0` … `parameter-9` are `simple-entity` development stubs.
  They are correctly absent from everything the agent sees — but by accident, via a `rock|stone`
  name check in `Resource.lua`, after passing the `resource_entities` filter whose exclude list
  is empty.
- Modules are excluded from the agent's items by a bug, not by any of the five criteria.

---

## T4 — Derived (12) and T3 — Typed (38)

The 50 entities the agent can hold as objects. Capabilities are the mixins the class composes;
`—` means the class exposes only `BaseEntity`'s surface plus its own methods.

| Entity | Class | Capabilities | Derived topology |
|---|---|---|---|
| `express-loader` | `ExpressLoader` | belt, rotatable | yes |
| `express-splitter` | `ExpressSplitter` | belt, rotatable180 | yes |
| `express-transport-belt` | `ExpressTransportBelt` | belt, rotatable | yes |
| `express-underground-belt` | `ExpressUndergroundBelt` | belt, rotatable | yes |
| `fast-loader` | `FastLoader` | belt, rotatable | yes |
| `fast-splitter` | `FastSplitter` | belt, rotatable180 | yes |
| `fast-transport-belt` | `FastTransportBelt` | belt, rotatable | yes |
| `fast-underground-belt` | `FastUndergroundBelt` | belt, rotatable | yes |
| `loader` | `Loader` | belt, rotatable | yes |
| `splitter` | `Splitter` | belt, rotatable180 | yes |
| `transport-belt` | `TransportBelt` | belt, rotatable | yes |
| `underground-belt` | `UndergroundBelt` | belt, rotatable | yes |
| `accumulator` | `Accumulator` | — | — |
| `assembling-machine-1` | `AssemblingMachine` | crafter, electric, set_recipe | — |
| `assembling-machine-2` | `AssemblingMachine` | crafter, electric, set_recipe | — |
| `assembling-machine-3` | `AssemblingMachine` | crafter, electric, set_recipe | — |
| `big-electric-pole` | `BigElectricPole` | — | — |
| `boiler` | `Boiler` | burner, fluid, rotatable | — |
| `bulk-inserter` | `BulkInserter` | electric, inserter, rotatable | — |
| `burner-inserter` | `BurnerInserter` | burner, inserter, rotatable | — |
| `burner-mining-drill` | `BurnerMiningDrill` | burner, miner, rotatable | — |
| `centrifuge` | `Centrifuge` | crafter, electric, set_recipe | — |
| `chemical-plant` | `ChemicalPlant` | crafter, electric, fluid, set_recipe | — |
| `crash-site-chest-1` | `ShipWreck` | — | — |
| `crash-site-chest-2` | `ShipWreck` | — | — |
| `electric-furnace` | `ElectricFurnace` | crafter, electric | — |
| `electric-mining-drill` | `ElectricMiningDrill` | electric, miner, rotatable | — |
| `fast-inserter` | `FastInserter` | electric, inserter, rotatable | — |
| `inserter` | `Inserter` | electric, inserter, rotatable | — |
| `iron-chest` | `IronChest` | — | — |
| `lab` | `Lab` | electric | — |
| `long-handed-inserter` | `LongHandedInserter` | electric, inserter, rotatable | — |
| `medium-electric-pole` | `MediumElectricPole` | — | — |
| `offshore-pump` | `OffshorePump` | fluid, rotatable | — |
| `oil-refinery` | `OilRefinery` | crafter, electric, fluid, set_recipe | — |
| `pipe` | `Pipe` | fluid | — |
| `pipe-to-ground` | `PipeToGround` | fluid, rotatable | — |
| `pump` | `Pump` | electric, fluid, rotatable | — |
| `pumpjack` | `Pumpjack` | electric, fluid, miner, rotatable | — |
| `rocket-silo` | `RocketSilo` | crafter, electric, set_recipe | — |
| `small-electric-pole` | `SmallElectricPole` | — | — |
| `solar-panel` | `SolarPanel` | electric | — |
| `steam-engine` | `SteamEngine` | electric, fluid, rotatable | — |
| `steam-turbine` | `SteamTurbine` | electric, fluid, rotatable | — |
| `steel-chest` | `SteelChest` | — | — |
| `steel-furnace` | `SteelFurnace` | burner, crafter | — |
| `stone-furnace` | `StoneFurnace` | burner, crafter | — |
| `storage-tank` | `StorageTank` | fluid, rotatable | — |
| `substation` | `Substation` | — | — |
| `wooden-chest` | `WoodenChest` | — | — |

**Certified by.** `tests/unit/test_transport.py` (11 tests) covers the belt derivation,
including a neighbour-invalidation case stored adjacency cannot pass. Live certification of
that derivation against the `iron-saturated` fixture is **blocked** by the snapshot-boot defect
recorded in `docs/EXECUTION.md`; the plan's four-component numbers are not current evidence.
`tests/unit/test_entity_reference.py` (26 tests) covers the read-only reference parity per
family. Live suites exercise `transport-belt`, `wooden-chest`, `small-electric-pole`,
`burner-mining-drill`, `electric-mining-drill`, `offshore-pump`, `inserter` and
`assembling-machine-1`. **Named in no test, unit or live:** `pipe`, `pipe-to-ground`,
`storage-tank`, `steam-turbine`, `solar-panel`, `accumulator`, `pumpjack`, `steel-furnace`,
`big-electric-pole`, `substation`, `rocket-silo`, `centrifuge`, `oil-refinery` and most inserter
tiers. Their presence in this table means a class exists, not that it works.

**Three entries in the map point at prototypes Factorio 2.0 does not have** —
`filter-inserter`, `stack-inserter`, `stack-filter-inserter`. 2.0 folded filtering into the base
`inserter` and renamed the stack tier to `bulk-inserter`. The classes are unreachable.

**Two entries are typed but outside the documented set** — `crash-site-chest-1` and
`crash-site-chest-2` (and `rocket-silo`, which is typed while its recipe category is excluded).
They work; the filter simply does not list them.

**Two entities participate in derived topology without a class** — `loader-1x1` and
`linked-belt` are routed into `transport_belt` by type, so they appear in `transport.line()`
results, but neither can be held as an object. The aggregate read and the per-entity read
disagree about what exists.

**Twenty-three of the 73 documented entities have no craftable placing item** — the agent is
told about them and can never obtain one. Three are T4: `loader`, `fast-loader` and
`express-loader` are fully typed, carry derived topology, and have no recipe in vanilla
Factorio at all. The rest are the 9 modules and `selection-tool` (not entities), `storage-tank`
(killed by the `storage-*` glob), and the T2a set.

**Four exported classes are never used as a map value** — `Container`, `Furnace`,
`ProcessingMachine` and `ElectricPole`. They are base classes whose leaf subclasses are mapped
instead, so they are reachable only through inheritance.

**Setting a recipe is gated in Lua, not by the class.** `EntityInterface.lua:152` allows
`assembling-machine`, `furnace` and `rocket-silo`, plus a fallback admitting anything whose
prototype has `crafting_categories`. This is the only true entity-type allow-list in the mod;
every other action — place, mine, rotate, inspect — is an entity-agnostic pass-through, and the
gating happens at the Python object layer through the capability mixins.

**Only belts have derived topology.** `transport.py` derives belt lines live at read time.
**Electric poles and pipes have none** — that is Phase 4B in `docs/EXECUTION.md`, and it has not
started. Pole and pipe connectivity is still whatever the serializer stores
(`pole_data.connected_poles`, fluidbox ports), which is exactly the stored adjacency the
transport plan exists to remove.

**Placement reasoning covers four entity families, not all of them.** `fv_placement_hints`
reasons about inserter pickup/drop positions (from live prototype fields), pipe and fluidbox
connection points, offshore-pump water sites, and mining-drill/pumpjack resource sites. Pole
wiring geometry exists and is self-documented as over-connecting 12 of 44 poles, so it is not
trusted. The mod contains **no** belt-direction or underground-pairing logic — that lives
entirely in `transport.py`. Every `can_place_entity` call in both mods correctly passes
`build_check_type = defines.build_check_type.manual` (or `manual_ghost`).

---

## T2a — Charted but untyped (16)

The filter says the system knows these. No class exists. They are in `map_entity` and answer
raw SQL, and that is all.

| Entity | Prototype type | Item craftable by the agent |
|---|---|---|
| `beacon` | `beacon` | **yes** |
| `burner-generator` | `burner-generator` | no |
| `gate` | `gate` | **yes** |
| `heat-exchanger` | `boiler` | **yes** |
| `heat-pipe` | `heat-pipe` | **yes** |
| `land-mine` | `land-mine` | item shown, no recipe |
| `lane-splitter` | `lane-splitter` | no |
| `loader-1x1` | `loader-1x1` | no placing item |
| `market` | `market` | no placing item |
| `nuclear-reactor` | `reactor` | **yes** |
| `one-way-valve` | `valve` | no |
| `overflow-valve` | `valve` | no |
| `proxy-container` | `proxy-container` | no |
| `radar` | `radar` | **yes** |
| `stone-wall` | `wall` | **yes** |
| `top-up-valve` | `valve` | no |

**Seven of these are fully reachable** — the agent can craft the item and place it: `beacon`,
`gate`, `heat-exchanger`, `heat-pipe`, `nuclear-reactor`, `radar`, `stone-wall`.

**What happens when it does.** `PlaceableItem.place()` sends the placement, waits on the state
barrier, inspects the result, and then calls `create_reachable_entity`
(`place_entity.py:203-211`) — with no exception handling. For an unmapped name that constructor
raises `ValueError: Unknown entity type: <name>. This entity has not been migrated to the new
architecture yet.` **The entity is already built.** The call raises after changing the world and
tells the agent nothing about what it changed — Constitution §8, exactly ("a call that fails
without saying what it already did is worse than a call that does nothing").

Read from code, not executed: certifying it needs a live instance, and there is no check for it
today.

**And once built, it is invisible.** Every other route to the object swallows the same
exception rather than raising it:

- `reachable_view.py:144-146` — `except ValueError: pass`, commented *"Entity type not yet
  migrated - skip it for now"*
- `duckdb/query.py:332-334` and `:451-453` — `except ValueError: logger.debug(...); return None`

So an agent standing in front of a nuclear reactor it built one turn ago gets an entity list
that does not contain it. Empty and broken render identically (§15). The row is in
`map_entity`, so `remote_view.query()` will still find it — the database half of the map surface
sees what the object half cannot.

---

## T2b — Charted, excluded by design (97)

In the database, answerable by raw SQL through `remote_view.query()`, absent from the typed API
and from the generated docs. This is the scope decision `fv_filters.yaml` encodes: trains,
rails, circuits, logistics, robots, military, and the editor/debug entities.

- **`ammo-turret`** (1) — `gun-turret`
- **`arithmetic-combinator`** (1) — `arithmetic-combinator`
- **`artillery-turret`** (1) — `artillery-turret`
- **`artillery-wagon`** (1) — `artillery-wagon`
- **`car`** (2) — `car`, `tank`
- **`cargo-landing-pad`** (1) — `cargo-landing-pad`
- **`cargo-wagon`** (1) — `cargo-wagon`
- **`constant-combinator`** (1) — `constant-combinator`
- **`construction-robot`** (1) — `construction-robot`
- **`container`** (12) — `blue-chest`, `bottomless-chest`, `crash-site-spaceship`, `crash-site-spaceship-wreck-big-1`, `crash-site-spaceship-wreck-big-2`, `crash-site-spaceship-wreck-medium-1`, `crash-site-spaceship-wreck-medium-2`, `crash-site-spaceship-wreck-medium-3`, `factorio-logo-11tiles`, `factorio-logo-16tiles`, `factorio-logo-22tiles`, `red-chest`
- **`curved-rail-a`** (1) — `curved-rail-a`
- **`curved-rail-b`** (1) — `curved-rail-b`
- **`decider-combinator`** (1) — `decider-combinator`
- **`display-panel`** (1) — `display-panel`
- **`electric-energy-interface`** (2) — `electric-energy-interface`, `hidden-electric-energy-interface`
- **`electric-turret`** (1) — `laser-turret`
- **`entity-ghost`** (5) — `entity-ghost`, `entity-unknown`, `tile-proxy`, `tree-dying-proxy`, `tree-proxy`
- **`fluid-turret`** (1) — `flamethrower-turret`
- **`fluid-wagon`** (1) — `fluid-wagon`
- **`half-diagonal-rail`** (1) — `half-diagonal-rail`
- **`heat-interface`** (1) — `heat-interface`
- **`infinity-cargo-wagon`** (1) — `infinity-cargo-wagon`
- **`infinity-container`** (1) — `infinity-chest`
- **`infinity-pipe`** (1) — `infinity-pipe`
- **`lamp`** (1) — `small-lamp`
- **`linked-belt`** (1) — `linked-belt`
- **`linked-container`** (1) — `linked-chest`
- **`locomotive`** (1) — `locomotive`
- **`logistic-container`** (5) — `active-provider-chest`, `buffer-chest`, `passive-provider-chest`, `requester-chest`, `storage-chest`
- **`logistic-robot`** (1) — `logistic-robot`
- **`power-switch`** (1) — `power-switch`
- **`programmable-speaker`** (1) — `programmable-speaker`
- **`rail-chain-signal`** (1) — `rail-chain-signal`
- **`rail-signal`** (1) — `rail-signal`
- **`resource`** (6) — `coal`, `copper-ore`, `crude-oil`, `iron-ore`, `stone`, `uranium-ore`
- **`roboport`** (1) — `roboport`
- **`selector-combinator`** (1) — `selector-combinator`
- **`simple-entity`** (3) — `big-rock`, `big-sand-rock`, `huge-rock`
- **`simple-entity-with-force`** (1) — `simple-entity-with-force`
- **`simple-entity-with-owner`** (7) — `crash-site-spaceship-wreck-small-1`, `crash-site-spaceship-wreck-small-2`, `crash-site-spaceship-wreck-small-3`, `crash-site-spaceship-wreck-small-4`, `crash-site-spaceship-wreck-small-5`, `crash-site-spaceship-wreck-small-6`, `simple-entity-with-owner`
- **`spider-vehicle`** (1) — `spidertron`
- **`straight-rail`** (1) — `straight-rail`
- **`train-stop`** (1) — `train-stop`
- **`tree`** (20) — `dead-dry-hairy-tree`, `dead-grey-trunk`, `dead-tree-desert`, `dry-hairy-tree`, `dry-tree`, `tree-01`, `tree-02`, `tree-02-red`, `tree-03`, `tree-04`, `tree-05`, `tree-06`, `tree-06-brown`, `tree-07`, `tree-08`, `tree-08-brown`, `tree-08-red`, `tree-09`, `tree-09-brown`, `tree-09-red`
Note that `tree` (20), `resource` (6) and the three rock `simple-entity` names arrive by the
`Resource.lua` path into the resource tables rather than into `map_entity`, and are reachable
through `reachable_view.get_resources()` / `remote_view.get_resources()`. They are listed here
because they are charted but untyped in the `ENTITY_CLASS_MAP` sense.

---

## T1 — Invisible (28)

Real entities that exist in the world and that **no gate captures**. Not in the database, not in
any view, not in the API. Nothing the agent can read will mention them.

- **`character`** (1) — `character`
- **`cliff`** (1) — `cliff`
- **`fish`** (1) — `fish`
- **`simple-entity`** (10) — `parameter-0`, `parameter-1`, `parameter-2`, `parameter-3`, `parameter-4`, `parameter-5`, `parameter-6`, `parameter-7`, `parameter-8`, `parameter-9`
- **`spider-unit`** (1) — `dummy-spider-unit`
- **`turret`** (4) — `behemoth-worm-turret`, `big-worm-turret`, `medium-worm-turret`, `small-worm-turret`
- **`unit`** (8) — `behemoth-biter`, `behemoth-spitter`, `big-biter`, `big-spitter`, `medium-biter`, `medium-spitter`, `small-biter`, `small-spitter`
- **`unit-spawner`** (2) — `biter-spawner`, `spitter-spawner`
Three of these matter:

- **`cliff`** blocks placement and cannot be mined without cliff explosives. It is neutral
  force, so the `map_entity` scan skips it; it is not a tree, not a resource, and its name
  contains neither `rock` nor `stone`, so `Resource.lua` skips it too. The agent can therefore
  be refused a placement by an obstacle that appears in none of its reads. `can_place_entity`
  correctly uses `build_check_type.manual` (verified at every call site in both mods), so the
  refusal is honest — but nothing explains it.
- **The enemy forces** — 8 units, 2 spawners, 4 worm turrets — are captured by nothing. This is
  survivable only because the scenario boot gate asserts zero enemies in the play area. If that
  gate ever loosens, the agent is blind to them.
- **`parameter-0` … `parameter-9`** pass the `resource_entities` filter (its exclude list is
  empty) and are then dropped by the `rock|stone` name check in `Resource.lua`. A filter rule
  that matches nothing, saved by an unrelated guard one layer down.

`character` is excluded deliberately and at every call site; the agent's own body is not a map
entity.

---

## T0 — Not a world object (376)

Explosions, projectiles, streams, stickers, beams, fire, corpses, remnants, engine proxies, and
the inert `dummy-*` / `legacy-*` stubs. These are entity prototypes by inheritance but never a
persistent thing standing on the map, and no surface should ever show them. Listed for
completeness.

- **`arrow`** (2) — `fake-selection-box-2x2`, `orange-arrow-with-circle`
- **`artillery-flare`** (1) — `artillery-flare`
- **`artillery-projectile`** (1) — `artillery-projectile`
- **`beam`** (3) — `electric-beam`, `electric-beam-no-sound`, `laser-beam`
- **`cargo-pod`** (1) — `cargo-pod`
- **`character-corpse`** (1) — `character-corpse`
- **`combat-robot`** (3) — `defender`, `destroyer`, `distractor`
- **`corpse`** (129) — `1x2-remnants`, `accumulator-remnants`, `active-provider-chest-remnants`, `arithmetic-combinator-remnants`, `artillery-turret-remnants`, `artillery-wagon-remnants`, `assembling-machine-1-remnants`, `assembling-machine-2-remnants`, `assembling-machine-3-remnants`, `beacon-remnants`, `behemoth-biter-corpse`, `behemoth-spitter-corpse`, `behemoth-worm-corpse`, `behemoth-worm-corpse-burrowed`, `big-biter-corpse`, `big-electric-pole-remnants`, `big-remnants`, `big-scorchmark`, `big-scorchmark-tintable`, `big-spitter-corpse`, `big-worm-corpse`, `big-worm-corpse-burrowed`, `biter-spawner-corpse`, `boiler-remnants`, `buffer-chest-remnants`, `bulk-inserter-remnants`, `burner-inserter-remnants`, `burner-mining-drill-remnants`, `car-remnants`, `cargo-landing-pad-remnants`, `cargo-pod-container-remnants`, `cargo-wagon-remnants`, `centrifuge-remnants`, `chemical-plant-remnants`, `constant-combinator-remnants`, `construction-robot-remnants`, `decider-combinator-remnants`, `defender-remnants`, `destroyer-remnants`, `display-panel-remnants`, `distractor-remnants`, `electric-furnace-remnants`, `electric-mining-drill-remnants`, `express-splitter-remnants`, `express-transport-belt-remnants`, `express-underground-belt-remnants`, `fast-inserter-remnants`, `fast-splitter-remnants`, `fast-transport-belt-remnants`, `fast-underground-belt-remnants`, `flamethrower-turret-remnants`, `fluid-wagon-remnants`, `gate-remnants`, `gun-turret-remnants`, `heat-exchanger-remnants`, `heat-pipe-remnants`, `huge-scorchmark`, `huge-scorchmark-tintable`, `inserter-remnants`, `iron-chest-remnants`, `lab-remnants`, `lamp-remnants`, `land-mine-remnants`, `laser-turret-remnants`, `locomotive-remnants`, `logistic-robot-remnants`, `long-handed-inserter-remnants`, `medium-biter-corpse`, `medium-electric-pole-remnants`, `medium-remnants`, `medium-scorchmark`, `medium-scorchmark-tintable`, `medium-small-remnants`, `medium-spitter-corpse`, `medium-worm-corpse`, `medium-worm-corpse-burrowed`, `nuclear-reactor-remnants`, `offshore-pump-remnants`, `oil-refinery-remnants`, `passive-provider-chest-remnants`, `pipe-remnants`, `pipe-to-ground-remnants`, `power-switch-remnants`, `programmable-speaker-remnants`, `pump-remnants`, `pumpjack-remnants`, `radar-remnants`, `rail-chain-signal-remnants`, `rail-ending-remnants`, `rail-signal-remnants`, `requester-chest-remnants`, `roboport-remnants`, `rocket-silo-remnants`, `selector-combinator-remnants`, `small-biter-corpse`, `small-electric-pole-remnants`, `small-remnants`, `small-scorchmark`, `small-scorchmark-tintable`, `small-spitter-corpse`, `small-worm-corpse`, `small-worm-corpse-burrowed`, `solar-panel-remnants`, `spidertron-remnants`, `spitter-spawner-corpse`, `splitter-remnants`, `steam-engine-remnants`, `steam-turbine-remnants`, `steel-chest-remnants`, `steel-furnace-remnants`, `stone-furnace-remnants`, `storage-chest-remnants`, `storage-tank-remnants`, `substation-remnants`, `tank-remnants`, `train-stop-remnants`, `transport-belt-remnants`, `tree-01-stump`, `tree-02-stump`, `tree-03-stump`, `tree-04-stump`, `tree-05-stump`, `tree-06-stump`, `tree-07-stump`, `tree-08-stump`, `tree-09-stump`, `underground-belt-remnants`, `wall-remnants`, `wooden-chest-remnants`
- **`deconstructible-tile-proxy`** (1) — `deconstructible-tile-proxy`
- **`elevated-curved-rail-a`** (1) — `dummy-elevated-curved-rail-a`
- **`elevated-curved-rail-b`** (1) — `dummy-elevated-curved-rail-b`
- **`elevated-half-diagonal-rail`** (1) — `dummy-elevated-half-diagonal-rail`
- **`elevated-straight-rail`** (1) — `dummy-elevated-straight-rail`
- **`explosion`** (140) — `accumulator-explosion`, `active-provider-chest-explosion`, `arithmetic-combinator-explosion`, `artillery-cannon-muzzle-flash`, `artillery-turret-explosion`, `artillery-wagon-explosion`, `assembling-machine-1-explosion`, `assembling-machine-2-explosion`, `assembling-machine-3-explosion`, `atomic-fire-smoke`, `atomic-nuke-shockwave`, `beacon-explosion`, `behemoth-biter-die`, `behemoth-spitter-die`, `behemoth-worm-die`, `big-artillery-explosion`, `big-biter-die`, `big-electric-pole-explosion`, `big-explosion`, `big-spitter-die`, `big-worm-die`, `biter-spawner-die`, `blood-explosion-big`, `blood-explosion-huge`, `blood-explosion-small`, `boiler-explosion`, `buffer-chest-explosion`, `bulk-inserter-explosion`, `burner-inserter-explosion`, `burner-mining-drill-explosion`, `car-explosion`, `cargo-pod-container-explosion`, `cargo-wagon-explosion`, `centrifuge-explosion`, `chemical-plant-explosion`, `cluster-nuke-explosion`, `constant-combinator-explosion`, `construction-robot-explosion`, `decider-combinator-explosion`, `defender-robot-explosion`, `destroyer-robot-explosion`, `display-panel-explosion`, `distractor-robot-explosion`, `electric-furnace-explosion`, `electric-mining-drill-explosion`, `enemy-damaged-explosion`, `explosion`, `explosion-gunshot`, `explosion-gunshot-small`, `explosion-hit`, `express-splitter-explosion`, `express-transport-belt-explosion`, `express-transport-belt-explosion-base`, `express-underground-belt-explosion`, `express-underground-belt-explosion-base`, `fast-inserter-explosion`, `fast-splitter-explosion`, `fast-transport-belt-explosion`, `fast-transport-belt-explosion-base`, `fast-underground-belt-explosion`, `fast-underground-belt-explosion-base`, `flamethrower-turret-explosion`, `fluid-wagon-explosion`, `flying-robot-damaged-explosion`, `gate-explosion`, `grenade-explosion`, `ground-explosion`, `gun-turret-explosion`, `heat-exchanger-explosion`, `heat-pipe-explosion`, `inserter-explosion`, `iron-chest-explosion`, `lab-explosion`, `lamp-explosion`, `land-mine-explosion`, `laser-bubble`, `laser-turret-explosion`, `locomotive-explosion`, `logistic-robot-explosion`, `long-handed-inserter-explosion`, `massive-explosion`, `medium-biter-die`, `medium-electric-pole-explosion`, `medium-explosion`, `medium-spitter-die`, `medium-worm-die`, `nuclear-reactor-explosion`, `nuke-effects-nauvis`, `nuke-explosion`, `offshore-pump-explosion`, `oil-refinery-explosion`, `passive-provider-chest-explosion`, `pipe-explosion`, `pipe-explosion-base`, `pipe-to-ground-explosion`, `pipe-to-ground-explosion-base`, `power-switch-explosion`, `programmable-speaker-explosion`, `pump-explosion`, `pumpjack-explosion`, `radar-explosion`, `rail-chain-signal-explosion`, `rail-explosion`, `rail-signal-explosion`, `requester-chest-explosion`, `roboport-explosion`, `rock-damaged-explosion`, `rocket-silo-explosion`, `selector-combinator-explosion`, `slowdown-capsule-explosion`, `small-biter-die`, `small-electric-pole-explosion`, `small-spitter-die`, `small-worm-die`, `solar-panel-explosion`, `spark-explosion`, `spark-explosion-higher`, `spidertron-explosion`, `spitter-spawner-die`, `splitter-explosion`, `steam-engine-explosion`, `steam-turbine-explosion`, `steel-chest-explosion`, `steel-furnace-explosion`, `stone-furnace-explosion`, `storage-chest-explosion`, `storage-tank-explosion`, `substation-explosion`, `tank-explosion`, `train-stop-explosion`, `transport-belt-explosion`, `transport-belt-explosion-base`, `underground-belt-explosion`, `underground-belt-explosion-base`, `uranium-cannon-explosion`, `uranium-cannon-shell-explosion`, `wall-damaged-explosion`, `wall-explosion`, `water-splash`, `wooden-chest-explosion`
- **`fire`** (11) — `acid-splash-fire-spitter-behemoth`, `acid-splash-fire-spitter-big`, `acid-splash-fire-spitter-medium`, `acid-splash-fire-spitter-small`, `acid-splash-fire-worm-behemoth`, `acid-splash-fire-worm-big`, `acid-splash-fire-worm-medium`, `acid-splash-fire-worm-small`, `crash-site-fire-flame`, `fire-flame`, `fire-flame-on-tree`
- **`highlight-box`** (1) — `highlight-box`
- **`item-entity`** (1) — `item-on-ground`
- **`item-request-proxy`** (1) — `item-request-proxy`
- **`legacy-curved-rail`** (1) — `legacy-curved-rail`
- **`legacy-straight-rail`** (1) — `legacy-straight-rail`
- **`particle-source`** (4) — `blood-fountain`, `blood-fountain-big`, `blood-fountain-hit-spray`, `nuclear-smouldering-smoke-source`
- **`projectile`** (25) — `atomic-bomb-ground-zero-projectile`, `atomic-bomb-wave`, `atomic-bomb-wave-spawns-cluster-nuke-explosion`, `atomic-bomb-wave-spawns-fire-smoke-explosion`, `atomic-bomb-wave-spawns-nuclear-smoke`, `atomic-bomb-wave-spawns-nuke-shockwave-explosion`, `atomic-rocket`, `blue-laser`, `cannon-projectile`, `cliff-explosives`, `cluster-grenade`, `defender-capsule`, `destroyer-capsule`, `distractor-capsule`, `explosive-cannon-projectile`, `explosive-rocket`, `explosive-uranium-cannon-projectile`, `grenade`, `laser`, `piercing-shotgun-pellet`, `poison-capsule`, `rocket`, `shotgun-pellet`, `slowdown-capsule`, `uranium-cannon-projectile`
- **`rail-ramp`** (1) — `dummy-rail-ramp`
- **`rail-remnants`** (6) — `curved-rail-a-remnants`, `curved-rail-b-remnants`, `half-diagonal-rail-remnants`, `legacy-curved-rail-remnants`, `legacy-straight-rail-remnants`, `straight-rail-remnants`
- **`rail-support`** (1) — `dummy-rail-support`
- **`rocket-silo-rocket`** (1) — `rocket-silo-rocket`
- **`rocket-silo-rocket-shadow`** (2) — `cargo-pod-shadow`, `rocket-silo-rocket-shadow`
- **`smoke-with-trigger`** (4) — `crash-site-explosion-smoke`, `crash-site-fire-smoke`, `poison-cloud`, `poison-cloud-visual-dummy`
- **`speech-bubble`** (1) — `compi-speech-bubble`
- **`spider-leg`** (8) — `spidertron-leg-1`, `spidertron-leg-2`, `spidertron-leg-3`, `spidertron-leg-4`, `spidertron-leg-5`, `spidertron-leg-6`, `spidertron-leg-7`, `spidertron-leg-8`
- **`sticker`** (8) — `acid-sticker-behemoth`, `acid-sticker-big`, `acid-sticker-medium`, `acid-sticker-small`, `electric-mini-stun`, `fire-sticker`, `slowdown-sticker`, `stun-sticker`
- **`stream`** (11) — `acid-stream-spitter-behemoth`, `acid-stream-spitter-big`, `acid-stream-spitter-medium`, `acid-stream-spitter-small`, `acid-stream-worm-behemoth`, `acid-stream-worm-big`, `acid-stream-worm-medium`, `acid-stream-worm-small`, `flamethrower-fire-stream`, `handheld-flamethrower-fire-stream`, `tank-flamethrower-fire-stream`
- **`temporary-container`** (1) — `cargo-pod-container`
- **`tile-ghost`** (1) — `tile-ghost`
---

## Entities as ingredients — the road to a rocket

Measured 2026-09-02 against a live `freeplay` server on `factoriotools/factorio:2.0.76`, base
mod only, by dumping `prototypes.recipe` / `prototypes.technology` / `prototypes.item` /
`prototypes.entity` over RCON and running two forward-reachability fixpoints over the engine's
own graph: one unrestricted, one restricted to what `fv_filters.yaml` and `ENTITY_CLASS_MAP`
expose. The engine reported **567 entities**, matching this page's denominator exactly, and
**251 items** where `data.raw['item']` holds 173.

An entity name can be needed as an **item** without ever being placed. The scope policy above
governs placement; it does not govern ingredients, and the two have never been reconciled.

### Eight entity-items are consumed as ingredients on the way to a rocket

| Item | Places | Agent can craft it | Placement support | Consumed by |
|---|---|---|---|---|
| `transport-belt` | `transport-belt` | yes | T4 derived | logistic science pack |
| `inserter` | `inserter` | yes | T3 typed | logistic science pack |
| `electric-furnace` | `electric-furnace` | yes | T3 typed | production science pack |
| `pipe` | `pipe` | yes | T3 typed | engine unit, rocket silo |
| `solar-panel` | `solar-panel` | yes | T3 typed | satellite |
| `accumulator` | `accumulator` | yes | T3 typed | satellite |
| `radar` | `radar` | yes | **T2a — advertised, no class** | satellite |
| `rail` | `straight-rail` | **no** | **excluded (trains)** | production science pack, 30× |

### The run does not stall at the rocket. It stalls at the second research tier.

Under the current filters the agent can research **19** of the 187 technologies the engine
allows, and obtain **42** of 199 items. `rocket-part`, `rocket-silo` and `satellite` are all
unreachable — but so is almost everything else, because of a single rule.

`logistic-science-pack` is matched by the `"logistic-*"` exclude glob in `fv_filters.yaml`,
which was written to remove logistic-network entities. Its recipe is therefore not exposed, the
pack cannot be crafted, and **every technology requiring red + green science is blocked**. The
frontier — technologies whose prerequisites are met and which fail only for want of that pack —
is `automation-2`, `logistics-2`, `engine`, `solar-energy`, `advanced-material-processing` and
`electric-energy-distribution-1`. That is the whole early game.

### What blocks the rocket once that is fixed

The rocket's requirement closure is 44 technologies, 51 items and 61 recipes, needing five
science packs. The remaining blockers, each attributed to the rule that causes it:

| Blocked | Rule | Consequence |
|---|---|---|
| `rail` (item) | prototype type is `rail-planner`, so `filter_items()` never sees it; **and** subgroup `train-transport` is excluded | no production science pack — 30 rails per pack |
| `productivity-module` | prototype type is `module`, so `filter_items()` never sees it | no production science pack |
| all five science packs | prototype type is `tool`, so `filter_items()` never sees them | craftable but never shown to the agent |
| `low-density-structure` | exclude glob | no rocket part, no utility science pack |
| `rocket-fuel`, `rocket-part`, `satellite` | exclude globs; `rocket-building` category excluded | no launch |
| `rocket-silo` (item) | subgroup `space-related` excluded | the silo is typed (T3) but its item is not obtainable |
| `concrete`, `stone-brick` | subgroup `terrain` not in `include_subgroups` | no rocket silo — 1000× concrete |
| six fluids | `get_filtered_items()` cannot list fluids at all; there is no fluid catalog | `petroleum-gas`, `sulfuric-acid`, `lubricant`, `light-oil`, `heavy-oil`, `steam` are unnameable except through recipes |

`rocket-building` is the only crafting category in the closure with no placeable machine, which
is consistent — the silo item is excluded, so nothing can build one.

**Robots are not on the critical path.** Utility science needs `flying-robot-frame`, which is an
ordinary item, already exposed, and craftable. `roboport`, `construction-robot` and
`logistic-robot` are needed for a rocket only if the agent wants bot logistics. Making robots a
priority is additive; it unblocks nothing that is currently blocked.

The barrel recipes that appear in the closure are artifacts of taking every producing recipe for
each fluid, not requirements — a barrel route is always optional.

### The minimal change set for the decided target

Computed, not estimated: the reachability fixpoint was re-run with each candidate change applied
and the goals re-tested. With the changes below, `rocket-part` and `satellite` both become
reachable and **130 of 187 technologies** open up — the remaining 57 being exactly the military,
train and robot branches that criteria 1, 4 and 5 exclude.

**Six recipes to expose.** `logistic-science-pack`, `low-density-structure`, `rail`,
`rocket-fuel`, `rocket-part`, `satellite`. The first is a bug fix (the `logistic-*` glob); the
other five are criterion 2's deferral being lifted for the rocket chain.

**One entity to expose: `rocket-silo`.** It already has a class and works. `fv_filters.yaml`
simply never listed it, and `rocket-building` is the only crafting category in the closure whose
sole machine is the silo — so without it in the entity scope, `rocket-part` cannot be built even
if every recipe is exposed. This was the non-obvious blocker.

**Eleven items to make nameable.** `rail`, `productivity-module`, `concrete`, `stone-brick`,
`rocket-silo`, `satellite`, and all five science packs. These are already *craftable* once their
recipes are exposed — reachability does not depend on the item filter — but the agent is never
shown them and so cannot reference them by name. Four distinct causes, all in `filter_items()`
and its config: prototype types `tool`, `module` and `rail-planner` are never read; subgroup
`terrain` is not included; subgroups `train-transport` and `space-related` are excluded and need
explicit `include` entries for `rail`, `rocket-silo` and `satellite`.

**One entity to resolve: `radar`.** It is on the satellite's critical path as an ingredient, it
is advertised to the agent, and it has no class — so placing one raises after the world has
changed. Either give it a class or make it ingredient-only like `rail`. Ingredient-only is
sufficient for the target; nothing requires a radar to be placed.

**The structural lesson.** Three of these are the same mistake: the item surface is being
derived from entity-shaped rules. `rail` is now deliberately an item and not an entity;
`rocket-silo` is deliberately an entity whose item was missing; modules and science packs are
items that were never entities at all. The item filter and the entity filter answer different
questions and should stop sharing subgroup lists.

---

## Completeness

Every entity prototype in the installation appears in exactly one tier above.

| Tier | Count |
|---|---|
| T4 — Derived | 12 |
| T3 — Typed | 38 |
| T2a — Charted, untyped (gap) | 16 |
| T2b — Charted, excluded by design | 97 |
| T1 — Invisible | 28 |
| T0 — Not a world object | 376 |
| **Total** | **567** |

The four entity-derived prototype types the pruned dump drops (`corpse`, `character-corpse`,
`smoke-with-trigger`, `rocket-silo-rocket-shadow`) are all T0 and are included in that 376 from
the raw dump. Fifteen entity types the 2.0.76 API defines are absent from this installation
entirely — Space Age exclusives such as `asteroid`, `fusion-reactor`, `thruster`, `plant` and
`space-platform-hub` — and are therefore outside the denominator, not unsupported.

---

## Defects this audit found

Each is a hole in the tree, not a design decision. None has a check today.

1. **Untyped entities are silently dropped from every view.** `create_entity.py:206-212` raises;
   `reachable_view.py:144-146` and `duckdb/query.py:332-334,451-453` swallow. 16 entities the
   filter advertises, 7 of them craftable and placeable, vanish after being built. §15.
2. **`place()` raises after changing the world.** `place_entity.py:203-211` constructs the typed
   object outside any `try`, so placing an untyped entity succeeds in the game and throws in
   Python, reporting neither the placement nor its position. §8.
3. **Three `ENTITY_CLASS_MAP` entries name prototypes 2.0 removed** — `filter-inserter`,
   `stack-inserter`, `stack-filter-inserter`.
4. **Modules are classified as entities.** `filters.py:19` — `NON_ENTITY_CATEGORIES` contains
   `"module-category"` but not `"module"`, so the 9 module prototypes and `selection-tool` reach
   `get_filtered_entities()`. The comment directly above that set records this exact bug class
   being found and fixed for `item`; it recurred one line away.
5. **`filter_items()` scans only the `item` prototype type** (`filters.py:285`), so items living
   under `tool` / `module` / `capsule` are dropped despite matching an explicit include rule.
   All seven science packs are missing from what the agent is shown.
6. **Two exclude globs are overbroad, and one of them ends the run.** `"storage-*"` and
   `"logistic-*"` in `fv_filters.yaml` were written for logistic-network entities. `"storage-*"`
   also drops the `storage-tank` recipe. `"logistic-*"` also drops the **`logistic-science-pack`
   recipe**, which blocks every technology requiring red + green science — 19 of 187
   technologies remain reachable. This is the single most damaging line in the file.
7. **`src/fv_snapshot/fv_filters.json` is dead code.** No Lua file reads it, no script writes
   it, one commit ever (`cc9b1f2`), and its entity list is already stale. `src/fv_snapshot/README.md`
   still describes it as live.
8. **`src/factorio/mods/mod-list.json` contradicts the boot.** It enables `space-age`, `quality`
   and `elevated-rails`; `docker-compose.yml` mounts the host mods directory instead, where all
   three are disabled. The checked-in file is not what runs.
9. **`land-mine` reaches the agent's documented set** through the `defensive-structure`
   subgroup, though `military` and `combat` are excluded and its recipe is filtered out.
10. **The documentation-coverage validator checks no entity class.**
    `tests/unit/test_documentation_coverage.py` passes 24 tests over the eight-name namespace and
    six registered non-entity classes. `_class_map` holds exactly one entity entry, generic
    `BaseEntity`, and mixin methods are matched by name pattern rather than against the class
    that composes them — so an example calling `set_recipe` on a class without `SetRecipeMixin`
    would pass. Nothing has ever checked the 50 entity classes for drift.

Found by the rocket-reachability run, which the entity audit alone would not have surfaced:

11. **`filter_items()` misses four whole prototype types that matter.** Science packs are `tool`,
    modules are `module`, and `rail` is `rail-planner`. None is `item`, so none is ever shown to
    the agent, regardless of subgroup rules. `production-science-pack` needs `rail` and
    `productivity-module`; both are invisible for this reason alone.
12. **`concrete` and `stone-brick` are unreachable** because subgroup `terrain` is not in
    `include_subgroups`. The rocket silo needs 1000 concrete. No scope criterion covers this.
13. **There is no fluid surface at all.** `PrototypeDataManager` has no `get_filtered_fluids()`,
    and `fluid` appears in `filters.py` only inside `NON_ENTITY_CATEGORIES`. Six fluids are on
    the rocket's critical path and can be named only by reading a recipe.
14. **`rocket-silo` is typed but its item is excluded** (`space-related`), so the one entity most
    associated with the goal can be held as an object and never built.

---

## What would close the gap

In the order the defects compound, not in the order they were found.

1. **Give the drop a voice.** Whatever the eventual typing story, a name with no class must not
   disappear. Either return a generic entity carrying name, position and raw row, or raise where
   the caller can see it — but `except ValueError: pass` in a read path is the floor lying, and
   the standing caution in `docs/EXECUTION.md` is about exactly this failure mode.
2. **Fix `place()` first regardless**, because it is the one that mutates. Constructing the
   return value must not be able to fail after the world has changed.
3. **Decide T2a deliberately.** Sixteen entities are advertised and unusable. Each is either
   worth a class (`nuclear-reactor`, `heat-exchanger`, `heat-pipe` and `beacon` are real
   mid-game production; `gate` and `stone-wall` are trivial) or worth removing from the filter.
   Leaving them advertised is the only option that is wrong.
4. **Reconcile the three gates, or state that they differ on purpose.** A single test asserting
   `ENTITY_CLASS_MAP` ⊆ dump, and that the filtered set and the class map agree except for a
   named exemption list, would have caught defects 3, 4 and the whole of T2a — and cannot pass
   vacuously, since both sides are built independently.
5. **Cliffs.** Either capture them or accept that placement can fail for reasons no read
   explains, and say so in the prompt.
