# Information Surfaces — the legibility audit

*Created 2026-06-11, prompted by the attempt-3 base walkthrough. Owner: the eval program.
Companion docs: `docs/retros/2026-06-11-engine-unit-attempt3-retro.md`,
`docs/retros/2026-06-11-attempt3-base-archaeology.md`, `docs/FLOOR_CERTIFICATION.md`.*

## 1. Why this document exists

The system has **two truth planes** and we have only ever instrumented one:

- **Plane 1 — state fidelity**: does what the system reports match the engine?
  This is what `FLOOR_CERTIFICATION.md` measures. After the 2026-06-11 sessions it
  is in reasonable shape (snapshot coherence, connection cues, honest waits).
- **Plane 2 — legibility**: can the model *reconstruct* plane-1 truth from what we
  surface — schemas, API shapes, prompt prose, error strings — and predict
  consequences from it? **Nothing measures this.** Until now we inferred it
  backwards from failed eval runs, one anecdote at a time.

The attempt-3 base is plane-2 failure made visible: not one wrong fact, but a model
acting on a blurry composite. The danger of skipping this audit: we classify
failures as "model error" against *what the harness conveys today*, silently
assuming conveyance ⇒ comprehension. Every fix then targets a symptom
("add a reservation API") when the disease may be incoherence ("the concept exists
in three surfaces under three vocabularies and the decision path sees none of
them").

**The discipline this doc imports**: no "the model knows X" claims without an
executed probe — the same rule the ledger imposed on "X works".

## 2. The surfaces (inventory, population-verified)

Model-facing surfaces, with verified status. ☠ marks **mirages** — surfaces that
are documented to the model but do not deliver.

| # | Surface | What it carries | Status |
|---|---------|----------------|--------|
| S1 | DuckDB schema **as documented** (prompt-injected schema reference) | tables, columns, worked SQL examples | ☠ partially LYING — documents `inserter`/`transport_belt`/`mining_drill`/`assembler` component tables incl. a worked JOIN example (`schema_reference.py:327-332`; in attempt-3's prompt at lines 3033, 3163) |
| S2 | DuckDB **as populated** | map_entity (+raw_data JSON), ghost, resource_tile/entity, water_tile, footprint_tiles, chunk_snapshot_meta | component tables **certified 0 rows always** (L1.5 ❌ 2026-06-10); `power_statistics` written mod-side (`Power.lua:127`) but loader never ingests (no loader reference) |
| S3 | `remote_view` API | query/get_entities/get_entity_at_tile/is_tile_occupied/find_water/get_ghosts/sync_state | live; tile-occupancy queries exist (O(1) via footprint_tiles) |
| S4 | `entity.inspect()` typed state | status (67-value enum), direction, burner/electric/crafter/miner/**inserter (pickup_position, drop_position, pickup_target, drop_target)**/fluid/belt (belt_inputs/outputs!)/container/pole (supply_area_distance, wire_distance, connected_poles)/generator | live (relational fields landed with PLACE-1 work) |
| S5 | `placement_hints` | validate_*/is_buildable/get_connection_positions/get_inserter_placement_positions/get_pole_line/**evaluate_pole_placement** (supply area, entities_powered, dry-run)/get_underground_segment | live; L4.6-certified connection-guaranteeing (cues) |
| S6 | Structured errors | placement collisions+reach, walking spatial context, crafting/inventory contracts, ConnectionQueryError ("query failure ≠ no positions") | live (ERR-1/2/3/4 certified); empty-cue `reason` exists at Lua tier but **dropped by the Python wrapper** (REASON-1) |
| S7 | System prompt prose | identity, bottleneck strategy, anti-patterns, worked power-chain pattern (new 40353fb), connection idioms, injected API/schema/tech reference | live; single-line guidance for several high-stakes semantics (see §4) |
| S8 | initial_state.md | position+inventory, Working Area bounds (fixed 1ca2af3), resource aggregates+top locations, placed entities, water, tech/recipes | live |
| S9 | Task Progress meter | current_rate vs target, consecutive checks, automation split, snapshot tick | live but **froze for 7 turns in attempt 3** (VERIF-1) with no staleness signal |
| S10 | Async events | research/crafting completion payloads | live |

## 3. Concept × Surface matrix

Cell values: **●** taught & true · **◐** present but unlinked to the decision path
or undiscoverable · **✗** absent · **☠** documented but false (mirage) · **?**
unverified.

| Concept | S1 doc'd schema | S2 live DB | S4 inspect | S5 placement | S6 errors | S7 prompt | S9 progress |
|---|---|---|---|---|---|---|---|
| Position / occupancy | ● | ● (footprint_tiles) | ● | ● (is_buildable, validate) | ● (collision lists) | ● | — |
| **Reservation** (inserter hand cells, drill drop cell) | ☠ (inserter table) | ✗ (table empty; in raw_data only) | ◐ (per-entity, post-hoc) | **✗ in validation/cue path** | ✗ (blocker not named) | ✗ | — |
| Direction semantics (16-dir ints; inserter dir = PICKUP side; cue.direction REQUIRED) | ◐ (VARCHAR names) | ◐ | ● enum | ● (cues carry it) | ✗ | ◐ single lines, new | — |
| Connection: fluid (port ≠ face) | ✗ | ◐ (raw_data fluidbox) | ● (fluid state + connections) | ● (L4.6 cues) | ◐ (reason dropped, REASON-1) | ● worked pattern (new) | — |
| Connection: item drop | ✗ | ◐ | ● (drop_target — resolves lazily!) | ● cues | ✗ | ◐ (lazy resolution noted, new) | — |
| Connection: wire/power reach | ✗ | ◐ (electric_network_id col) | ● pole state | ● (evaluate_pole_placement EXISTS) | ✗ | **✗ discoverability unverified** | — |
| Connection: belt flow | ✗ | ◐ | ● (belt_inputs/outputs) | ✗ (no belt-line connectivity check) | ✗ | ✗ | — |
| Status (what 53/54 mean) | ✗ | ◐ raw ints in raw_data | ● enum (67 values) | — | — | ✗ no decode table | ✗ |
| **Power as FLOW** (generation vs load, fuel as consumable) | ☠ (power_statistics) | ✗ (never loaded) | ◐ (per-entity energy fields) | ◐ (entities_powered count) | ✗ | ✗ (one-time setup framing until PROMPT-2b) | ✗ |
| Staleness / time | ● (chunk_snapshot_meta doc'd) | ● (queryable) | — | — | ✗ | ◐ (one find_water footnote) | **✗ meter froze silently (VERIF-1)** |
| Ghosts / orphans / islands | ● ghost table | ● | ● is_ghost | ◐ (ghost plans w/ labels) | ✗ | ✗ | ✗ (ISLAND-1) |
| Reach / build distance | ✗ | ✗ | — | ◐ | ● (distance + walk-closer) | ● | — |

## 4. Findings (named, with evidence)

**MIRAGE-1 (new, critical-adjacent).** The prompt's schema reference documents the
four component tables and ships a worked JOIN example against `inserter` —
tables certified **0 rows always** (ledger L1.5 ❌, settled 2026-06-10). Same
pattern risk for `power_statistics` (mod writes the jsonl; loader never reads it;
documented in schema). An agent following our documentation gets empty results
and learns false world-facts ("no inserters exist"). *The plane-1 ledger knew;
the plane-2 surface was never reconciled.* This is the strongest single piece of
evidence that the legibility plane needs its own instrument.

**SPLIT-1.** Status arrives as a 67-value typed enum via `inspect()` but as raw
ints via raw_data/DB/some print paths; attempt 3's agent saw `54` and spent ~3
turns misdiagnosing. Same concept, two vocabularies, no decode table anywhere in
prose (STATUS-1).

**RESERVE (recast).** Not a data hole — pickup/drop cells exist per-inserter in
`inspect()` (and in the *dead* DB table). The hole is **compositional**: the
placement/validation path neither consults nor names them; nothing aggregates
"cells reserved by hands/drops" into a queryable or collision-relevant surface
(RESERVE-1, archaeology obs #2 + cascades #1/#3/#4).

**DISCOVER-1.** `evaluate_pole_placement` (supply areas, entities_powered,
dry-run) — exactly what obs #10 wanted — already exists. Whether any prompt
surface advertises it is **unverified**; attempt 3 never called it. The L5.1
namespace check certifies no *phantom* names; nothing certifies *reachable*
names are findable when needed. Discoverability is a measurable, currently
unmeasured property.

**OVERLOAD-1.** "Connected" means four different mechanics (fluid ports, drop
cells, wire reach, belt flow) across surfaces that use one word. Belt-flow
connectivity has *no* placement-time surface at all (the attempt-3 disconnected
stubs went unnoticed by everything except Harshit's eyes).

**FLOW-1.** Power is surfaced as wiring topology (networks, poles) everywhere;
generation-vs-load and fuel-as-consumable appear nowhere the model can read
(power_statistics unloaded; no prompt framing until PROMPT-2b). The fuel
starvation was thus *invisible by construction* until machines went dark.

**Singleton-line risk.** Several high-stakes semantics live in exactly one
prompt line each (inserter direction = pickup side; cue.direction required;
drop_target lazy). One line against a strong contrary prior is a hypothesis, not
a conveyance — battery measures whether each line landed.

## 5. The instrument: comprehension battery

Model-in-the-loop probes that ask the model to **predict engine outcomes from
surfaced state, without acting**. Single completions; scored against engine
truth; diffable across prompt/surface versions. The discriminator:

- predicts wrong → the surface/doc is ambiguous or lying → surgery on the surface
- predicts right but acts wrong in evals → capability/attention → different
  intervention (or none)

Specimen: `attempt3-base-specimen` save (the actual misjudged structures,
preserved 2026-06-11; load via `fv server start --save attempt3-base-specimen`).

Probe protocol per item: system prompt = the production prompt (or the relevant
excerpt — variant B tests excerpt-only); user message = serialized surface data
exactly as the agent would see it + ONE question; structured answer; score
binary vs engine truth (captured per-probe via read-only RCON at battery build
time).

### Battery v0 probe list (~25, for review BEFORE any spend)

| ID | Concept (matrix row) | Probe (payload → question) | Truth source |
|----|---------------------|---------------------------|--------------|
| V1 | direction | inspect() of a real inserter (dir=WEST) → "which cell does it PICK from, which does it DROP to?" | engine pickup/drop_position |
| V2 | direction | same, dir=NORTH (0 — the falsy trap) | engine |
| V3 | direction | cue with direction=SOUTH → "what happens if you place without passing direction?" | L4.6 evidence |
| V4 | status | "a furnace reports status 54 — what does it mean, what do you check next?" | enum + causal chain |
| V5 | status | inspect() showing status enum NO_FUEL on boiler + machines at 54 → "root cause?" | attempt-3 ground truth |
| V6 | reservation | map_entity rows for furnace+inserter pair → "which cells are unsafe for a pole?" | engine hand cells |
| V7 | reservation | the EXACT attempt-3 pole-on-drop-cell placement, pre-placement data → "is (x,y) safe?" | archaeology obs #2 |
| V8 | fluid ports | boiler at (x,y) facing E → "where can a steam engine connect? how many options?" | L4.6 (exactly 1) |
| V9 | fluid ports | pump output occupied by boiler1 → "can a second boiler connect to this pump?" | engine (no) |
| V10 | fluid ports | empty cue list + (variant) the Lua reason string → "what do you conclude / do next?" | REASON-1 A/B test |
| V11 | item drop | drill inspect() unfueled, chest on drop cell, drop_target=nil → "is the connection broken?" | lazy-resolution truth |
| V12 | belt flow | belt_inputs/outputs of the attempt-3 disconnected stub → "does ore from belt A reach furnace F?" | engine neighbours |
| V13 | belt flow | two parallel belt rows from specimen → "same line or independent?" | engine |
| V14 | power flow | 1 boiler+engine + N machines (inspect data) → "is generation sufficient? what's consumed when it runs?" | physics |
| V15 | power flow | "your machines read no_power; list the queries/inspections to find root cause, in order" | discoverability of the causal chain |
| V16 | power flow | "boiler fuel: one-time or recurring? what build makes it permanent?" | PROMPT-2b target |
| V17 | wire | pole pair from specimen + a far machine → "is M powered? how do you check WITHOUT placing?" | evaluate_pole_placement discoverability |
| V18 | wire | nets 1 vs 9 from specimen → "one network or two? consequence?" | engine network ids |
| V19 | staleness | Task Progress with frozen tick (the real T10-16 text) → "is '0 produced' trustworthy? how verify?" | VERIF-1 |
| V20 | staleness | chunk_snapshot_meta query result vs game.tick → "is your map view current?" | doc'd discipline |
| V21 | ghosts | ghost-table rows for the 20 lost belts → "what are these? do they function?" | engine |
| V22 | mirage | "write SQL to list all inserters with their pickup/drop positions" → does it use the dead table? then: result is 0 rows → "conclusion?" | MIRAGE-1 (the prompt's own example) |
| V23 | occupancy | is_tile_occupied vs footprint: a 3x2 boiler's tiles → "which tiles does it block?" | engine bbox |
| V24 | reach | agent at (x,y), target 11 tiles away → "can you place? what first?" | build distance 10 |
| V25 | spacing | "you're laying furnaces along a belt with inserters; how much space do you leave between rows for future lines, and why?" | design-knowledge probe (capability baseline, not surface) |

Scoring: binary per probe + free-text capture for failure taxonomy. Run as a
matrix: (full prompt vs section-excerpt) × (Sonnet 4.6 baseline). Estimated cost
for v0 full pass: ~50 completions ≈ low single-digit dollars.

### What the battery does NOT measure
Capability under load (attention across 40k-token turns), multi-step planning,
or other models — it measures whether *each surface, read in isolation by our
production model, conveys what we think it conveys*. V25-style items establish
the capability baseline so surface failures aren't blamed on the model.

## 6. Standing rules going forward

1. **No "the model knows X" without a probe** — battery items are citable like
   ledger rows.
2. **Schema/prompt surfaces must reconcile with plane-1 status**: a ledger ❌ on
   a surface (L1.5) must propagate to every surface that documents it (the
   MIRAGE class). Add to harness-audit gates.
3. Prompt edits earn battery deltas, not vibes.
4. New surfaces declare their matrix row(s) and add probes with them.
