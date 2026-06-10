# Floor Certification

**The rule: nothing is "stable" because a report, a memory, a doc, or a code-reading says so. A claim is certified only by executing its check. A certification is a `(date, commit)` pair. Any commit touching a layer voids that layer's certifications.**

This document is the single ledger for the question "how do we know the floor is honest?" It exists so we can run the checks, record the result, and never re-litigate stability from prose again.

## Status legend

| Status | Meaning |
|--------|---------|
| ⬜ UNRUN | Check is defined and runnable, has not been executed since last relevant commit |
| 🔧 NO-HARNESS | Check is defined but the code to run it does not exist yet |
| 🔍 AUDIT | A test exists that *claims* to cover this, but the test itself hasn't been audited (tests are agent-written, quality inconsistent — a passing bad test certifies nothing) |
| ✅ date @ commit | Executed and passed |
| ❌ date @ commit | Executed and failed — link the tracker issue |

**Everything starts ⬜/🔧/🔍 — including things "live-verified" in past sessions. Past sessions are prose.**

## The harness-audit gate

**A green from an unaudited harness is rumor with a checkmark.** All tests in this repo are agent-written with inconsistent quality, so a ✅ only counts if the harness itself has passed a one-time audit (recorded in the Audit log below; re-audit when the harness changes). An audit asks four questions:

1. **Can it pass vacuously?** Empty registry / zero items / conditional assertions (`if X in y: assert ...`) / always-true assertions (`assert n >= 0`) all pass while testing nothing. Require non-emptiness guards.
2. **Does it test the real layer or a mock of it?** Mock-only tests certify call-shape coherence, never behavior. They can support L-claims about pure logic, nothing about the game.
3. **Is ground truth constructed independently?** A test that derives its expectation from the same code path it checks proves consistency, not correctness. Live checks must get truth from a different layer (raw RCON scan vs DB; hand-built rig vs reads).
4. **Do the assertions cover the claim in the ledger row?** A test can be honest and still certify less than the row says — narrow the row or widen the test.

Precedent for why this gate exists: the first audit (2026-06-10) found this repo's flagship guard — `test_all_examples_valid_attributes`, the doc-drift catcher recommended in CLAUDE.md — was validating **zero examples** in full-suite runs. `register_all_documentation()` relied on import side effects, which Python caches, so after any `reset_registry()` it silently re-registered nothing, and the test "passed" on an empty registry. Three tests in that suite were vacuous; one was a production bug.

Requirements column: `offline` = no Factorio needed. `live` = needs a running client (`uv run fv client launch --scenario lab-grid`). `scale` = needs a large generated factory.

---

## L0 — Replication & determinism (does the game run reproducibly?)

The substrate everything else assumes. If two fresh launches differ, no downstream check is meaningful.

| ID | Claim | How to check | Pass criterion | Req | Status |
|----|-------|--------------|----------------|-----|--------|
| L0.1 | All three mods load cleanly (embodied_agent, snapshot, placement_hints) | Launch client; grep `factorio-current.log` for `Error`/`fv_`; probe `remote.interfaces` over RCON | Zero mod errors; agent/snapshot/scenario interfaces registered | live | ✅ PASS 2026-06-10 — client/lab-grid tick 4726, commit cd19317; 0 log errors; 10 interfaces live; mods base 2.0.76 + fv_embodied_agent 0.1.3 + fv_snapshot 0.1.0 + fv_placement_hints 0.1.0 (`.fv-output/certification/2026-06-10/L0.1/`) |
| L0.2 | Fresh scenario is reproducible | Launch lab-grid twice from scratch; dump full entity census (name+position set) each time; diff | Identical census | live | 🔧 needs census dumper (see L1.1) |
| L0.3 | State survives save/load | Census → save → reload → census; diff | Identical census; all relational reads (L2) still resolve (no unit_number leakage) | live | 🔧 |

## L1 — Grid-state exactness (is the DB the truth?)

The whole bet on "database as vision" rests here. Ground truth is always a direct RCON scan of the surface; the DB must match it *exactly*, not approximately.

| ID | Claim | How to check | Pass criterion | Req | Status |
|----|-------|--------------|----------------|-----|--------|
| L1.1 | **Census parity** — every placed entity in game ↔ exactly one `map_entity` row | Dump `find_entities_filtered` over RCON (name, type, position, direction); set-diff against `map_entity` | Empty diff both directions | live | 🔧 needs `fv dev census` |
| L1.2 | Removal syncs | Place N entities via TestGroundHelper, destroy them, flush, re-census | Rows gone; L1.1 still passes | live | 🔍 `tests/sync/test_udp_sync.py` claims coverage — audit it |
| L1.3 | Rotation/config-change syncs | Rotate + change recipe on live entities; check columns | Direction/recipe columns match game | live | 🔍 same suite |
| L1.4 | Sequence-gap triggers rebuild, rebuild restores parity | Induce a gap (drop UDP ops / fake sequence jump); confirm rebuild fires; run L1.1 | Rebuild detected in logs; census parity after | live | 🔧 |
| L1.5 | Derived AND component tables track mutations (`belt_line`, `resource_patch`, `electric_pole`; `inserter`, `transport_belt`, `mining_drill`, `assemblers`, …) | Mutate entities after initial load; query derived + component tables | Rows reflect post-load state | live | 🔧 — CONTRADICTION on component tables: scout code-reading said sync upserts write them; matrix AST extraction says incremental SQL touches only `map_entity`/`resource_entity`/`ghost`. Settled only by running this. |
| L1.8 | The two schema sources agree | Compare `schema_definitions.py` vs `db/schema.py` table-by-table; determine which the loader actually executes | No divergence, or one source declared canonical | offline | 🔧 — matrix generation mechanically found `assembler` vs `assemblers` naming divergence |
| L1.6 | Parity survives churn | Scripted 500-op loop (place/remove/rotate, mixed entity types), then L1.1 | Empty diff | live | 🔧 |
| L1.7 | `belt_line_segment` boundaries are correct at merges/splits | Build a splitter network; compare segment rows to hand-derived expectation | Segments split at merge/split points | live | 🔧 — code comment says "one segment per line for now"; expected ❌ |

> **Fine-grained cell inventory:** `docs/certification/COVERAGE_MATRIX.md` (generated by `scripts/certification/gen_matrix.py`) enumerates all 335 verifiable cells — 62 property fields, 63 API members, 68 sync cells, 13 JSONL kinds, 129 Lua emission keys. Ledger rows here are check-level; the matrix is where per-field coverage is tracked.

## L2 — Property correctness (do reads tell the truth, through every layer?)

Each check builds a known rig with TestGroundHelper, then asserts the SAME story from all three layers: raw RCON `inspect_entity`, the DuckDB row, and the Python typed object. Layer disagreement = failure even if each layer is individually plausible.

| ID | Claim | Rig | Pass criterion | Req | Status |
|----|-------|-----|----------------|-----|--------|
| L2.1 | **Golden rig**: inserter `pickup_target`/`drop_target`, belt `belt_inputs`/`belt_outputs` (directional), underground pairing | chest → inserter → furnace; 2+ belt line feeding an inserter; one underground pair | All targets resolve to name+position; flow direction correct; 3 layers agree | live | ⬜ — code committed at `e96ded3`; the 2026-06-07 live check was a session, not a test. **This becomes the golden pytest example all future tests copy.** |
| L2.2 | Fluid topology readable | offshore-pump → pipe → boiler → steam-engine | Fluid connections enumerable from Python; boiler/engine report connected | live | 🔧 — tracker PLACE-1/TYPE-1 territory; expected gaps |
| L2.3 | Power topology readable | 2 poles + powered machine | `electric_network` consistent across layers; machine reports powered | live | 🔧 |
| L2.4 | Volatile state readable (status, crafting progress, fuel, energy) | assembler with recipe + fed materials; burner with coal | ReachableView values change over ticks and match `inspect_entity` | live | 🔍 `tests/functional/test_complex_inspection.py` claims coverage — audit |
| L2.5 | Ghost reads | place ghosts; read via both views | Ghost table + reachable ghosts agree | live | 🔍 `tests/sync/test_ghost_snapshot.py` — audit |

## L3 — Prototype/runtime loading (is static data loaded correctly?)

| ID | Claim | How to check | Pass criterion | Req | Status |
|----|-------|--------------|----------------|-----|--------|
| L3.1 | Doc/code drift: every documented accessor exists with documented type | `pytest tests/unit/test_documentation_coverage.py -v` | All pass, `total_examples > 0` | offline | ✅ 2026-06-10 (harness audited & hardened same day — see Audit log) |
| L3.1b | Drift validator covers ALL accessors (examples using accessors unmapped in `validators.py` must fail loudly, not skip silently) | Inspect `StaticAttributeValidator` skip path; add a sentinel example with unmapped accessor | Unmapped accessor → loud failure or explicit skip-list | offline | 🔧 — suspected silent-skip scope limit, unverified |
| L3.2 | Data dump pipeline regenerates | `uv run fv data refresh`; diff entity set against `fv_filters.yaml` scope | Succeeds; filtered set as scoped | live | ⬜ |
| L3.3 | Prototype hydration matches dump | For sample entities: collision box, crafting speed, belt speed from Python objects vs `factorio-data-dump.json` | Values equal | offline | 🔧 |

## L4 — Action contracts (do writes do what they claim, and fail honestly?)

| ID | Claim | How to check | Pass criterion | Req | Status |
|----|-------|--------------|----------------|-----|--------|
| L4.1 | Placement honesty: `can_place` ⇔ `place` outcome | Grid-sweep an area: for each cell, compare `can_place_entity(manual)` prediction vs actual place attempt | Zero disagreements | live | 🔧 — KNOT-2 / tracker API-2; suspected ❌ |
| L4.2 | Placement failures explain themselves | Force collisions/out-of-reach/bad-direction failures; inspect error objects | Structured reason, not raw Lua traceback | live | 🔧 — tracker ERR-1; suspected ❌ |
| L4.3 | Entity removal affordance exists | Call the removal API from agent namespace | Entity removed, inventory credited | live | 🔧 — tracker API-1: known missing, check defined so its fix has an acceptance test |
| L4.4 | Geometry handoff: positions the API returns are accepted by the API | Feed `drop_position`/connection-hint outputs back into `place()` | Accepted or explicitly marked non-placeable | live | 🔧 — KNOT-2; suspected ❌ |
| L4.5 | Async completion honest | walk/mine/craft: UDP completion arrives exactly once and state matches | Completion ⇔ real state change | live | 🔍 `tests/actions/*` claim coverage — audit |

## L5 — Model usability (can an LLM actually drive this?)

| ID | Claim | How to check | Pass criterion | Req | Status |
|----|-------|--------------|----------------|-----|--------|
| L5.1 | Namespace completeness: every name in the system prompt / api_reference exists in the DSL execution namespace | Script: parse `docs/for-llms/api_reference.md` + system prompt for callables; probe namespace | Zero NameError/AttributeError (the `factoriopedia` PROMPT-1 bug class) | offline-ish | 🔧 |
| L5.5 | Doc registry covers the full API surface (inverse of L5.1: everything that exists is documented) | `gen_matrix.py` Doc? column | 63/63 members registered | offline | ❌ 2026-06-10 — 42/63; MiningAction, PlacementAction, EntityOperationsAction entirely unregistered, so L3.1's coverage validation never sees them (vacuousness-by-omission) |
| L5.2 | Documented examples execute | Run `docs/all_examples.md` snippets against live client | Zero attribute/name errors | live | 🔧 |
| L5.3 | Contract micro-evals: place-and-remove, belt-feed-verify, fluid-connect | `uv run fv eval --task <contract_task>` with a competent model | Pass within small step budget | live | 🔧 — tasks don't exist yet; these become the per-primitive acceptance tier below throughput tasks |
| L5.4 | Throughput evals reproduce | `uv run fv eval --task iron_plate_throughput` | PASS (was green 2026-03-28, many commits ago — re-run) | live | ⬜ |

## L6 — Scale (the endgame constraint: massive factories, rocket launch)

The DB was chosen *because* end-game factories are too big for any other read model. That bet is unverified until these run.

| ID | Claim | How to check | Pass criterion | Req | Status |
|----|-------|--------------|----------------|-----|--------|
| L6.1 | Big-factory ingest correct | Generate/import a 10k+ entity factory (blueprint or scripted); full snapshot → DB load; run L1.1 census parity | Empty diff at 10k+ entities | scale | 🔧 needs factory generator |
| L6.2 | Sync keeps up under load | Churn ops while big factory is live; watch sequence gaps + game UPS | No rebuild storm; UPS ≥ ~55 | scale | 🔧 |
| L6.3 | Query latency at scale | Representative spatial queries (nearest patch, entities-in-radius, belt_line lookup) on the 10k+ DB | < 100 ms each | scale | 🔧 |
| L6.4 | Snapshot batching doesn't freeze the game | Full-map snapshot of big factory; measure tick stalls | No stall > a few ticks | scale | 🔧 |

---

## How checks get run (context-economical orchestration)

Checks are executed by **sub-agents**, not by the orchestrator (Claude main loop / Harshit). The orchestrator's context holds verdicts and decisions, never raw runtime output.

- **Every check-runner reads `docs/RUNTIME_PLAYBOOK.md` first** and starts with its §0 smoke ritual. Runner prompts reference checks by ledger ID; the ledger row is the spec.
- **Evidence to disk, verdicts to context**: full dumps/diffs/scripts land in `.fv-output/certification/<date>/<check-id>/`; the runner's final message is the fixed verdict block from playbook §6 (≤ ~15 lines). The orchestrator opens artifacts only on FAIL or suspicion.
- **Concurrency**: offline checks fan out freely. Live mutating checks are serialized per instance, or parallelized across lab-grid cells (force-isolated). Read-only probes run anytime.
- **Escalation ladder**: runner runs the check → orchestrator reads verdict, updates this ledger → orchestrator gets directly involved only when a verdict is FAIL with unclear attribution, two runners disagree, or a harness fails its audit. Fixes then go through the normal layer-tracing work, and the check re-runs to flip the row.
- **Audit gate applies to runners too**: the first execution of any new harness must include the four audit-question answers in its verdict (AUDIT field).

## Execution order

1. **Offline now**: L3.1 (already runnable).
2. **Build the census dumper** (`fv dev census`): unlocks L0.2, L0.3, L1.1, L1.4, L1.6, L6.1 — the highest-leverage single harness in the suite.
3. **Golden rig test** (L2.1) as the canonical pytest example; audit-or-replace the 🔍 suites against it.
4. **Live battery** on a launched client: L0.x, L1.x, L2.x in one session.
5. **L4 honesty checks** — these are expected to surface the tracker's top issues (PLACE-1, API-1, ERR-1) as ❌ rows; fixing an issue flips its row green and that's the definition of done.
6. **Scale battery** (L6) once L1 is green at small scale.

## Known-claim cross-reference (prose to be replaced by checks)

These statements exist in docs/memory and are *contradictory or unverified* — the listed check settles each. Until then, treat all of them as rumors:

- "Map DB not auto-updating on entity removal" (CLAUDE.md) vs "sync.py handles removal" (code-reading) → **L1.2**
- "Derived tables stale after load" (code-reading) → **L1.5**
- "Belt relational reads work" (session 2026-06-07) → **L2.1**
- "iron_plate_throughput passes" (run 2026-03-28) → **L5.4**
- "DuckDB scales to end-game factories" (design assumption, never run) → **L6.x**

## Audit log (harness quality, one-time per harness)

| Date | Harness | Verdict | Findings |
|------|---------|---------|----------|
| 2026-06-10 | `tests/unit/test_documentation_coverage.py` | **AUDITED — was unsound, now hardened** | 3 vacuous tests: attribute validation ran on 0 examples (import-side-effect registration + cached imports = silent no-op after `reset_registry()`; fixed in `reference/__init__.py` by calling `_register_*()` explicitly); tautological `or len(classes) > 0`; conditional Quick-Reference assertion; always-true `>= 0` assertions. All fixed; non-emptiness guards added. Residual: L3.1b silent-skip question still open. |
| 2026-06-10 | `tests/unit/test_environment_tiers.py` | **PARTIAL** — mock-only; certifies tier-wiring logic, nothing about the game. One stale mock fixed (`initial_inventory` param drift). Acceptable for logic-level claims only. | |
| 2026-06-10 | `tests/unit/test_task_verification.py` | **PARTIAL** — exercises verifier math on synthetic stats; does NOT certify the JSONL pipeline feeding it (that's a live check). | |
| 2026-06-10 | L0.1 runner procedure (RCON interface probe + log grep, two corroborating channels) | **AUDITED — sound** | Vacuous-grep risk guarded by 47 positive fv_ matches in same file; live engine, no mocks; log-on-disk vs runtime interfaces are independent channels. Scope limit: certifies loading, not method behavior. |
| — | `tests/sync/`, `tests/functional/`, `tests/actions/` (all 🔍 rows above) | UNAUDITED | |

## Run log

| Date | Commit | Checks run | Result |
|------|--------|-----------|--------|
| 2026-06-10 | 9bc13d0 | L3.1 + offline unit battery, **pre-audit** | "58/58" — superseded: 3 of those passes were vacuous (see Audit log). Recorded as a cautionary entry. |
| 2026-06-10 | (this commit) | L3.1 + full offline unit battery, post-audit, hardened assertions | ✅ 58/58, non-vacuous; drift validator confirmed running on >0 real examples |
| 2026-06-10 | cd19317 | L0.1 via check-runner sub-agent (first use of RUNTIME_PLAYBOOK + verdict protocol) | ✅ PASS; runner also returned playbook errata (3 mods not 2 — fv_placement_hints exists; 7 undocumented remote interfaces; `script.active_mods` works from scenario runtime) — errata folded into playbook same day |
