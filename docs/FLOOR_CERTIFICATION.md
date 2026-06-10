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
| L1.2 | Removal syncs | `uv run python scripts/certification/check_L1_sync.py` | Rows gone; census parity exact after | live | ✅ 2026-06-10 — UDP destroy op applied <1s, row gone, parity 7=7 exact (script raise_destroy path; agent-mining removal still untested). Settles the old CLAUDE.md "removal broken" claim: FALSE. |
| L1.3 | Rotation/config-change syncs | same harness | Direction/recipe in DB match game | live | ✅ 2026-06-10 (server_0) — was ❌ same day: config-change payloads used a separate `udp_sequence` counter (guaranteed gap → drop+rebuild) and never reached update files (rebuild couldn't recover). Fixed in `Entities.lua` config handlers (both regular + agent variants): persist as upsert op to update log, stamp payload with the file-write sequence. Re-run: all 4 mutations sync; upsert op verified on disk in entities-updates.jsonl. |
| L1.4 | Sequence-gap triggers rebuild, rebuild restores parity | Induce a gap (drop UDP ops / fake sequence jump); confirm rebuild fires; run L1.1 | Rebuild detected in logs; census parity after | live | 🔧 |
| L1.5 | Component tables hold data (`inserter`, `transport_belt`, `mining_drill`, `assembler`) | same harness | Rows reflect game state | live | ❌ 2026-06-10 — settled empirically: **0 rows at every checkpoint**; neither Stack-A loader nor sync ever writes them — schema-only dead weight. Contradiction resolved: the AST extraction was right; the scout had read the unwired (now deleted) `db/` stack. Relational data lives in `map_entity.raw_data` JSON (round-trip verified by L2.1 layer-4). Open design question: populate them, turn into views over raw_data, or drop from schema. |
| L1.8 | The two schema sources agree | Compare `schema_definitions.py` vs `db/schema.py` table-by-table; determine which the loader actually executes | No divergence, or one source declared canonical | offline | ✅(resolved) 2026-06-10 — exhaustive code-trace: **Stack B (`db/schema.py` + `db/loader/`) is dead code**, zero runtime import paths; `schema_definitions.py` (Stack A) is canonical. Divergence moot pending Stack B's fate (see below). |
| L1.6 | Parity survives churn | Scripted 500-op loop (place/remove/rotate, mixed entity types), then L1.1 | Empty diff | live | 🔧 |
| L1.7 | `belt_line_segment` boundaries are correct at merges/splits | Build a splitter network; compare segment rows to hand-derived expectation | Segments split at merge/split points | live | 🔧 — code comment says "one segment per line for now"; expected ❌ |

> **Fine-grained cell inventory:** `docs/certification/COVERAGE_MATRIX.md` (generated by `scripts/certification/gen_matrix.py`) enumerates all 335 verifiable cells — 62 property fields, 63 API members, 68 sync cells, 13 JSONL kinds, 129 Lua emission keys. Ledger rows here are check-level; the matrix is where per-field coverage is tracked.

## L2 — Property correctness (do reads tell the truth, through every layer?)

Each check builds a known rig with TestGroundHelper, then asserts the SAME story from all three layers: raw RCON `inspect_entity`, the DuckDB row, and the Python typed object. Layer disagreement = failure even if each layer is individually plausible.

| ID | Claim | Rig | Pass criterion | Req | Status |
|----|-------|-----|----------------|-----|--------|
| L2.1 | **Golden rig**: inserter `pickup_target`/`drop_target`, belt `belt_inputs`/`belt_outputs` (directional), underground pairing | `uv run python scripts/certification/check_L2_1.py` (idempotent; needs test-ground client) | 13 fields agree across engine-Lua / `inspect_entity` / Python transform; name+position refs, zero unit_numbers | live | ✅ 2026-06-10 — first run ❌ @ eebf11b (underground pairing dropped by inspection.lua + BeltState); fixed (`underground_neighbour` through all 3 layers), re-run PASS 13/13. DB sub-layer → L1.9. |
| L1.9 | Standalone DB loader can create schema and ingest a snapshot dir | `load_all` / `create_schema` from a fresh process | Loads without error | offline-ish | ❌ 2026-06-10, severity DOWNGRADED — the BinderException is in dead Stack B; Tier4 uses Stack A (`SnapshotDatabase`+`SnapshotLoader`) and never hits it. Don't fix dead code; see Stack-B decision below. |

> **Stack-B decision (2026-06-10): DELETED.** Code-trace (and same-day empirical confirmation by the L1.sync runner: derived tables absent from a real Stack-A session DB) established the `db/` subtree had no runtime callers — except `status_loader`, which `query.py` lazy-imports; it was relocated to `game/infra/duckdb/status_loader.py`. Design rationale (Harshit, 2026-06-10): **belt aggregation is a label on primitives, not a derivation** — the system tags belts when placing lines (the `label` column already flows mod→sync→`map_entity`), agents read the tag as a low-level primitive, and connectivity graphs are Python functions composed on top of primitives (with `underground_neighbour` — certified in L2.1 — as the one edge case to mind). Clustering/DFS-in-the-DB is off-design, so the derivation algorithms were deleted with the stack; git history is the archive.
| L2.2 | Fluid topology readable | offshore-pump → pipe → boiler → steam-engine | Fluid connections enumerable from Python; boiler/engine report connected | live | 🔧 — tracker PLACE-1/TYPE-1 territory; expected gaps |
| L2.3 | Power topology readable | 2 poles + powered machine | `electric_network` consistent across layers; machine reports powered | live | 🔧 |
| L2.4 | Volatile state readable (status, crafting progress, fuel, energy) | assembler with recipe + fed materials; burner with coal | ReachableView values change over ticks and match `inspect_entity` | live | 🔧 — audit 2026-06-10: `test_complex_inspection.py` certifies only "inspect_entity capability structures + fuel>0"; never touches ReachableView or cross-tick change. Row needs its own check. |
| L2.5 | Ghost reads | place ghosts; read via both views | Ghost table + reachable ghosts agree | live | 🔧 — audit 2026-06-10: claimed harness `test_ghost_snapshot.py` is 11/11 ERROR at setup (undefined fixtures) — zero executable coverage ever existed. |

## L3 — Prototype/runtime loading (is static data loaded correctly?)

| ID | Claim | How to check | Pass criterion | Req | Status |
|----|-------|--------------|----------------|-----|--------|
| L3.1 | Doc/code drift: every documented accessor exists with documented type | `pytest tests/unit/test_documentation_coverage.py -v` | All pass, `total_examples > 0` | offline | ✅ 2026-06-10 (harness audited & hardened same day — see Audit log) |
| L3.1b | Drift validator covers ALL accessors (examples using accessors unmapped in `validators.py` must fail loudly, not skip silently) | Inspect `StaticAttributeValidator` skip path; add a sentinel example with unmapped accessor | Unmapped accessor → loud failure or explicit skip-list | offline | 🔧 — suspected silent-skip scope limit, unverified |
| L3.2 | Data dump pipeline regenerates | `uv run fv data refresh`; diff entity set against `fv_filters.yaml` scope | Succeeds; filtered set as scoped | live | ⬜ |
| L3.3 | Prototype hydration matches dump | `uv run python scripts/certification/check_L3_3.py` (17 entities × 16 property kinds + 10 recipes, all exposure paths: manager / EntityPrototypes / entity classes / Factoriopedia) | Values equal; scope loads cleanly; >100 comparisons (anti-vacuity) | offline | ✅ 2026-06-10 — first run ❌: hydration 458/458 exact but fv_filters entity scope leaked 2 hidden `item` prototypes (subgroup lives on item prototypes; pure items slipped through). Fixed in `filters.py` (shared `NON_ENTITY_CATEGORIES` + entity-existence intersection; my first fix over-pruned 75→12 entities and **the harness's own >100-comparisons guard caught the regression**). Re-run PASS: scope 73, 458/458. Residual: character reach distances have no typed accessor (manager raw only). |

## L4 — Action contracts (do writes do what they claim, and fail honestly?)

| ID | Claim | How to check | Pass criterion | Req | Status |
|----|-------|--------------|----------------|-----|--------|
| L4.1 | Placement honesty: `can_place` ⇔ `place` outcome | `uv run python scripts/certification/check_L4_placement.py --instance server_0` | Zero disagreements; ≥5 placeable + ≥5 blocked cells (anti-vacuity) | live | ✅ 2026-06-10 (server_0) @ 0bc3681 — 22-cell sweep, 0 disagreements (12 placeable / 10 blocked); fast-replace + fractional-snap semantics honest. **API-2 RECLASSIFIED**: pre-check exists and is agent-reachable (`placement_hints.validate_placement` + rich `get_placement_cue`); gap is the stub `reason:"placement_blocked"` (area.lua:50 TODO) + prompt visibility, not the affordance. Side-bugs: `create_agent` named-table nil-collapse (ParamSpec `normalize_varargs`); fast-replace drops displaced entity as item-on-ground. Ghost/directional sweep not yet covered. |
| L4.2 | Placement failures explain themselves | same harness (5 deliberate failures, verbatim agent-path payload capture) | Structured reason, not raw Lua traceback | live | ❌ 2026-06-10 (server_0) — ERR-1 confirmed: 4/4 failures return Lua tracebacks; collision errors state NO cause at all (`placement.lua:162` TODO). Irony on record: `get_placement_cue` already computes `colliding_entities` + `reason` — fix is wiring that into `place_entity`'s error payload. |
| L4.3 | Entity removal affordance exists | `remote.call('agent_N','pickup_entity', name, position)` (wrapped by `entity_ops.pickup_entity`) | Entity removed, inventory credited | live | ✅ 2026-06-10 (server_0) — works: entity removed from map, `extracted_items` reported, items credited to character main inventory (verified by raw engine read; accumulated correctly across 3 runs). API-1 reclassified: the affordance always existed, it was undocumented (see L5.5). Two side-findings: (1) `get_inventory_items` returns a LIST of `{name, quality, count}`, not the `{item: count}` dict previously documented; (2) suspected agent-character leak — 5 character entities on map after 3 create/destroy cycles → new check L4.6. |
| L4.6 | Agent lifecycle honest: no-arg `destroy_agents` destroys all; no silent no-ops | create 3 agents → no-arg destroy → census characters + registry | `destroyed=[...all ids]`, 0 characters, empty registry | live | ✅ 2026-06-10 (server_0) — was a silent no-op: nil fell through to empty list, returned `{destroyed:{}}` looking like success; the "character leak" was 6 live agents accumulated by probes whose cleanup never cleaned. Fixed in `Agents.lua` (nil joins the existing destroy-all-on-0 case). Acceptance: 3 creates → destroy → `[1,2,3]`, 0 chars. |
| L4.4 | Geometry handoff: positions the API returns are accepted by the API | same harness: drill `drop_position` round-trip + `get_fluid_connections` boiler→steam-engine with live controls | Accepted or explicitly marked non-placeable; connection candidates non-empty and placeable | live | ❌(half) 2026-06-10 (server_0) — drop_position half ✅: raw fractional coords accepted, engine snaps honestly, `get_item_drop_connections` works (KNOT-2 did not manifest). **PLACE-1 reproduced with controls**: boiler→steam-engine `{count:0}` while boiler→pipe gives 5 candidates — root cause `connections/init.lua:205-234`: solver tries the target's CENTER at the connection point ±1 tile, never offsets by the target's own fluidbox geometry, so every multi-tile target gets zero candidates. Fix the solver → re-run flips this row AND unblocks engine_unit. |
| L4.5 | Async completion honest | walk/mine/craft: UDP completion arrives exactly once and state matches | Completion ⇔ real state change | live | 🔧 — audit 2026-06-10: `tests/actions/*` has ZERO assertions about UDP completions; the purpose-built UDPCapture fixture is used by no test. Needs a real check-runner harness. |

## L5 — Model usability (can an LLM actually drive this?)

| ID | Claim | How to check | Pass criterion | Req | Status |
|----|-------|--------------|----------------|-----|--------|
| L5.1 | Namespace completeness: every name in the system prompt / api_reference exists in the DSL execution namespace | Script: parse `docs/for-llms/api_reference.md` + system prompt for callables; probe namespace | Zero NameError/AttributeError (the `factoriopedia` PROMPT-1 bug class) | offline-ish | 🔧 |
| L5.5 | Doc registry covers the full API surface (inverse of L5.1: everything that exists is documented) | `gen_matrix.py` Doc? column | All members registered or explicitly excluded with rationale | offline | ✅ 2026-06-10 — was 42/63; now 54 registered + 9 deliberately excluded (RemoteView lifecycle/internals, listed with inline rationale in `views.py` `remote_view_internal_methods`). Registration surfaced that **API-1 was a doc gap, not a missing affordance**: `entity_ops.pickup_entity` existed but was invisible to agents — see EVAL_ISSUE_TRACKER. Checked-in api_reference.md was also ~2,700 lines stale (system prompts generate live from the registry, so runtime impact was the missing classes, not the stale file). |
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
| 2026-06-10 | `tests/sync/test_udp_sync.py` + `test_snapshot_loader.py` | **AUDITED — unsound for L1.2/L1.3, stale-red** | Offline-only: real SyncService/loader + DuckDB but payloads/JSONL fabricated by test author — cannot see mod-side schema divergence (the dual-sequence-counter bug live L1.3 found is invisible by construction). Conditional config-change assert (udp_sync L350-352). Currently 11/21 FAIL: fixtures insert into dropped `map_entity.entity_key` column. Greens certify Python-side apply logic only; keep rows pointing at live check-runners. |
| 2026-06-10 | `tests/sync/test_ghost_snapshot.py` (L2.5 claimed harness) | **AUDITED — UNSOUND, cannot execute** | 11/11 ERROR at setup: fixtures `test_ground`/`admin` undefined in scope; `agent` fixture returns embodied-actions dict lacking the `.teleport`/`.interface_name` API the tests call. Even if revived: core verifications wrapped in `if updates_file.exists():` (L117, L202, L344), one test with no post-action assertion (L404), docker-only snapshot_dir hardcode (sync/conftest.py:160). L2.5 has zero executable coverage. |
| 2026-06-10 | `tests/functional/` (L2.4 claimed harness) | **AUDITED — PARTIAL, row over-claims** | Live + independent rig (admin RCON builds, inspect_entity reads) — sound structure. But test_complex_inspection never touches ReachableView, never re-reads across ticks, asserts no status/energy values (only fuel>0 at L172). Pole/connection tests are placement-geometry, not volatiles; pole-powering printed but never asserted. L2.4 row narrowed accordingly. |
| 2026-06-10 | `tests/actions/*` (L4.5 claimed harness) | **AUDITED — UNSOUND for L4.5: zero coverage** | No test asserts UDP completion arrives, arrives exactly once, or matches state; purpose-built UDPCapture fixture (sync/conftest.py:138) used by zero tests. Only files invoking walk/mine/craft completions are fixture-dead (14/14 ERROR: `dsl_context` undefined); inventory consistency assert self-skips on the bug it documents (L171); ghost-conversion tests verify via raw RCON Lua only (certify the engine, not this repo). **Exception: `test_placement_hints_runtime.py` is AUDITED-SOUND** for placement validation (independent RCON ghost-count truth) — mapped to placement rows, not L4.5. |

## Run log

| Date | Commit | Checks run | Result |
|------|--------|-----------|--------|
| 2026-06-10 | 9bc13d0 | L3.1 + offline unit battery, **pre-audit** | "58/58" — superseded: 3 of those passes were vacuous (see Audit log). Recorded as a cautionary entry. |
| 2026-06-10 | (this commit) | L3.1 + full offline unit battery, post-audit, hardened assertions | ✅ 58/58, non-vacuous; drift validator confirmed running on >0 real examples |
| 2026-06-10 | cd19317 | L0.1 via check-runner sub-agent (first use of RUNTIME_PLAYBOOK + verdict protocol) | ✅ PASS; runner also returned playbook errata (3 mods not 2 — fv_placement_hints exists; 7 undocumented remote interfaces; `script.active_mods` works from scenario runtime) — errata folded into playbook same day |
| 2026-06-10 | eebf11b | L2.1 via check-runner (harness: `check_L2_1.py`, audited in-run) | ❌ 11/13 — underground pairing lost in inspection.lua (read `entity.neighbours` only for pipes) and BeltState (no field); engine + snapshot JSONL both had it. Also: `force_resnapshot` no-op (MAINTENANCE phase), DB loader FK BinderException (→ L1.9) |
| 2026-06-10 | (fix commit) | L2.1 re-run after `underground_neighbour` fix (Lua + BeltState + transform), client restarted for mod reload | ✅ PASS 13/13 across engine/inspect/transform; red→green loop closed same day |
| 2026-06-10 | 904ad8d | L1 sync battery via check-runner (harness: `check_L1_sync.py`, audited in-run; real Tier4 classes, zero mocks) | L1.2 ✅ / L1.3 ❌ (dual sequence counters kill config-change sync; config ops also absent from update files) / L1.5 ❌ (component tables 0 rows always; derived tables don't exist in Stack A). Errata: mod's default snapshot UDP port is 34400, not the 34500 in the port table. |
| 2026-06-10 | (this commit) | L2.1 re-run after Stack-B deletion + layer-4 repoint to Stack A (harness edited → green re-earned) | ✅ PASS 13/13 across FOUR layers incl. DuckDB raw_data round-trip; component counts (0,0,0,0) logged as sentinel |
| 2026-06-10 | ab59324+ | **Server venue** (docker server_0, test-ground; harnesses gained `--instance`): L0.1-server smoke, L2.1, L1 sync battery | L2.1 ✅ 13/13 (snapshot files flow through compose volume); sync battery first run all-FAIL with `udp=NO` → diagnosed: socat sidecar only forwards 34202–34211 + 34400, harness's repoint-to-34571 blackholed; re-run listening on 34400: **identical to client** — place/remove/rotate ✅, config-change ❌ (same dual-counter mod bug, venue-independent), components 0 rows, derived absent. Venue parity certified. |
| 2026-06-10 | (this commit) | L1.3 fix → re-run on server_0 (mod re-synced via server restart) | ✅ all 4 mutations sync (place/remove/rotate/config); config upsert op verified on disk in entities-updates.jsonl with file-write sequence. Second red→green loop closed, first on the server venue. |
