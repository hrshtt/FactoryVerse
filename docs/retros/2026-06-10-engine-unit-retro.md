# Retro: engine_unit_throughput run 2026-06-10_23-35-34 (killed T17/64)

**Outcome:** 0 produced. Killed by operator at turn 17 of 64 when the agent pivoted to crafting solar panels. ~10.08M prompt tokens / 63k completion (~$8–10 effective), 169 tool calls, ~34 min game time. Final world: 1 boiler, 2 steam-engines, 2 assembling-machine-2 (recipe set), 69 poles, 1 stone-furnace — **zero pipes, zero offshore-pumps; power never went live.**

**Headline: the agent was right and the harness gaslit it.** It queried `water_tile` ≥8 times (always 0 rows; ground truth: 216 water tiles in cell_0), called the certified `get_connection_positions(boiler→steam-engine, FLUID_PIPE)` 3 times (silent `[]` every time), built correct boiler+engine layouts ~10 times, fueled them, and ran a clean 30-second controlled experiment. Every sensor said "water doesn't exist, power can't work." The solar pivot was the *rational endpoint of a false belief the harness installed* — not model failure. The single most expensive lesson: **a dishonest floor doesn't just block the agent, it actively teaches the agent false world-models.**

## Root causes (ranked by run damage)

1. **`water_tile` empty in the session DB** (SNAP-1) — the run-killer. Also: `map_entity` always `[]` despite placed entities, snapshot tick frozen at 660 for ~15 turns, `resource_tile` flapping full→empty→full. The DB-as-vision channel was incoherent all run.
2. **`get_fluid_connections` returned 0 in the field hours after certification** — REPRODUCED post-kill and root-caused: the probe used ONE staging position (found for default orientation) for all four rotations; the agent's boiler faced EAST, the rotated steam-engine footprint collided at staging near the cell edge, `create_entity` silently nil'd, east offsets never probed → 0 candidates → legacy fallback → 0. Certification passed only because open test-ground let all rotations fit. **Fixed same night** (per-direction staging with retries); east-facing boiler case verified count=1 + full L4 regression green. Compounding: Python `_get_fluid_pipe_positions` has `except → return []`, so failure was indistinguishable from "no candidates."
3. **Inspection sensors wrong**: `fluidboxes=[]` always; adjacent poles report `connected_poles=[]`, `electric_network_id=None`, `supply_area_entities=0`; statuses as raw ints (24/53/54). The agent's experiments ran against gaslighting instrumentation. (Matches ledger: ElectricPoleState is a KNOWN-STUB; status labels partial.)
4. **initial_state.md was wrong at session start** (empty inventory, empty resource queries — snapshot race): the agent began with a false world-model before turn 1.

## Full failure-mode inventory

(see the in-run analysis for verbatim quotes; classification: a=harness bug, b=docs/prompt gap, c=type-usability, d=agent error, e=task/scenario design)

| # | Failure | Class | Disposition |
|---|---------|-------|-------------|
| 1 | water_tile/map_entity/snapshot-tick incoherence | a | **SNAP-1 (new, critical)** |
| 2 | fluid-connection solver orientation bug | a | FIXED (this commit); L4.4 acceptance extended |
| 3 | `except→[]` silent swallow in `_get_fluid_pipe_positions` | a | tracker ERR-3 (new) |
| 4 | initial_state snapshot race | a/e | tracker SNAP-2 (new) |
| 5 | fluidbox/pole-network/status inspection wrong | a/c | feeds L2.2/L2.3 checks (now priority) |
| 6 | `put_inventory_item` partial-insert-then-raw-throw; inventory-type names undocumented | a/b | ERR-1-style treatment queue |
| 7 | `crafting.craft` raw; locked-recipe vs missing-ingredients indistinguishable | a/b | ERR-1-style treatment queue |
| 8 | WalkingUnreachableError ×8+, no context (ERR-2); `walking.lua already walking` cascade; empty TimeoutError | a | ERR-2 (existing, evidence updated) |
| 9 | Cell bounds undocumented → edge-probing at x=−5, y=−100, (200,70) | b/e | PROMPT-3 (new) |
| 10 | `'Direction' object is not callable` — agent shadowed `dir` builtin in persistent namespace; killed introspection 2 turns | d (c hazard) | note: persistent-namespace shadowing hazard |
| 11 | `await` on non-awaitable EntityRecipeSet; ResourceOrePatch `.amount` path-dependent; pickup exact-position miss | c | TYPE batch |
| 12 | place-as-sonar: no terrain affordance → hundreds of probe placements, ~70 pole debris from position-snap lookup misses | b | AFFORD-1 (new): `find_water()` / `is_buildable(area)` |
| 13 | Trigger-tech surprise (pipe recipe locked until 50 plates) | e | task design note |
| 14 | Task Progress block repeated verbatim ×163 (~20–25k tokens); 30k static prefix resent per call | a (cost) | OBS-2 (new): dedupe + prompt caching |

## What the new floor demonstrably fixed (visible in-run)

- Structured placement errors acted on every time ("out of reach … Walk closer first" → walked closer; collision lists → re-sited). No March-style blind retry loops.
- `pickup_entity` recovery loop used dozens of times, zero item loss — relocation/iteration behavior March's agent died without.
- boiler→pipe candidates correct (3 ports); trigger-research events surfaced cleanly.

## Top fixes by eval-impact-per-effort

1. SNAP-1: water_tile (+ map_entity/tick) snapshot correctness in lab-grid sessions — run-killer.
2. Snapshot staleness must be LOUD in tool results (frozen tick = warning banner, not silent `[]`).
3. ~~Solver orientation bug~~ FIXED + `except→[]` unsilencing (ERR-3).
4. Inspection ground truth: fluidboxes, pole network fields, status labels (L2.2/L2.3 checks).
5. ERR-1 treatment for crafting/inventory/pickup paths.
6. Cell bounds in prompt + ERR-2 spatial context.
7. Task Progress dedupe + prompt-prefix caching (~30–40% token cut).
8. Terrain affordance (`find_water`, `is_buildable`).

## Certification-discipline lessons

- **Certification venue must match field venue**: L4.4 passed on open test-ground and missed an orientation/confinement-dependent bug that lab-grid exposed in hours. Acceptance now includes the east-facing case; future live checks should run constrained-space variants.
- **The L1 sync battery certified the UDP path on test-ground but never certified tile snapshotting or a full lab-grid session pipeline** — SNAP-1 lived in the gap. The census harness (L1.1) + an L0/L1 lab-grid variant would have caught it.
- Silent exception swallowing (`except→[]`) turns every downstream bug into "no results" — same family as the vacuous-test findings.
