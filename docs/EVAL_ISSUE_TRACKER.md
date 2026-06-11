# Eval Issue Tracker

A living document that captures issues observed during agent eval runs. Designed to stay compact: active issues are detailed, resolved issues get compressed into one-line entries in the archive.

## How to use this document

**Adding an issue:** Append to the relevant category under Active Issues. Use this template:

```
### [SHORT-ID] Title
- **Severity:** critical | high | medium | low
- **Observed in:** {task} / {model} / {run_id}
- **Evidence:** What the agent tried, what happened, what should have happened.
- **Impact:** How this blocked the agent (wasted N steps, caused failure, etc.)
- **Fix direction:** Brief note on what the fix looks like.
```

**Resolving an issue:** When fixed, move the entry to the Archive section as a single line:
```
- [SHORT-ID] Title — fixed in {commit/PR}. Was: {one-line summary of what was wrong}.
```

**Compression cycle:** After every 5-10 eval runs, review the Active Issues. If an issue hasn't appeared in the last 5 runs, move it to Archive with status `stale` or `not-reproduced`. Keep Active Issues under ~20 entries.

**Reading this document quickly:** The Dashboard at the top gives counts. Skim category headers for what's broken. Only read individual issues if you're about to fix something in that category. Certification status for fixes lives in `docs/FLOOR_CERTIFICATION.md` — a "FIXED" here without a ledger row is prose.

---

## Dashboard

| Category | Critical | High | Medium | Low | Total |
|----------|----------|------|--------|-----|-------|
| Verification Integrity | 1 | 1 | 0 | 0 | 2 |
| Pending live acceptance (gated finale only) | 0 | 1 | 0 | 0 | 1 |
| Walking/Pathfinding | 0 | 0 | 2 | 0 | 2 |
| API Gaps | 0 | 0 | 1 | 0 | 1 |
| Type System | 0 | 1 | 1 | 0 | 2 |
| Placement/Spatial | 0 | 1 | 0 | 0 | 1 |
| Prompt/Docs | 0 | 1 | 0 | 0 | 1 |
| **Total** | **1** | **5** | **4** | **0** | **10** |

*Last updated: 2026-06-11 (second session, post attempt-3 retro) — CELL-1/CELL-2 archived; L4.6 certified incl. field amendment; NEW from retro: VERIF-1 (frozen verification feed, CRITICAL) + STATUS-1 (raw-int statuses, formalizes TYPE-1's residual); PROMPT-2 part-done (power-chain idiom landed, followed verbatim in field), PROMPT-2b remains*

---

## Active Issues

### Pending live acceptance

#### [LIVE-1] NEXT-SESSION WORKLIST (handoff 2026-06-11 — items 1+2+4 DONE same day, see below; 3 and 5 remain)
- **Severity:** high (gates the CELL-1 closure + the eval program)
- **State:** server_0 up fresh (lab-grid, game.speed=5 for faster Lua/snapshot throughput); all work committed through `108d475`.
- **Sequence:**
  1. ✅ DONE 2026-06-11: fresh restart exercised boot invalidation TWICE — snapshot volume cleared both times (CELL-2b live-confirmed).
  2. ✅ DONE 2026-06-11 @ 108d475: L0.4 GREEN ON BOTH PATHS (see ledger row). En route, the harness's own drafted drain criterion turned out to be a CELL-1-class lying wait (proceeded at pending=31 mid-bootstrap; 73 phantom failures on the true first clean run) — replaced with wait_fresh (IDLE + write_queue==0 + per-chunk lookup freshness, timeout RAISES). `--path orchestrator` implemented for real: EXTERNAL-mode Environment stack, orch._allocate_cell/_release_cell cycles, vision on the orchestrator's own session DB via unified execute_raw.
  3. ✅ DONE 2026-06-11 @ 1ca2af3 (LIVE-1C): acceptance eval session PASSED — own-cell initial_state (484-tile iron in-cell), execute_duckdb own-cell truth, zero phantoms, honest wait, silent preflight, 70 plates automation, 934k/19-call tokens. CAUGHT 3 BUGS, all fixed same day: (a) PROMPT-3 Working Area silently absent — tier5 adapter namespace lacked `scenario` (every eval since 7012629); render now validated via the real adapter path; (b) OBS-2 cache hits unobservable — usage extraction dropped gateway cache fields; fixed + live probe cached=3008/3021 on call 2; (c) the eval COMPOSE-DOWNED server_0 on exit + cleared the running boot's snapshots on entry (server twin of the client SIGTERM bug) — attach guard added. Deferred to the finale's artifacts: in-eval Working Area render + cached_prompt_tokens observation (both validated at component level).
  4. ✅ DONE 2026-06-11: `map.get_chunk_lookup` JSON shape live-verified (dict keyed "cx,cy" → {snapshot_tick, files_written, ...}) — now load-bearing in both the harness's wait_fresh and its CELL-2 sub-check. `pending_chunks` semantics pinned down as bycatch: drains to 0 ONLY on fresh boots; idles >0 forever once cell resets accumulate (it counts never-requested chunks map-wide).
  5. Then the **gated finale** (Harshit's spend approval): engine_unit field re-run WITH observe.py in-run ground-truth probes.
- **Known residuals (non-blocking):** NEW: Environment SERVER-mode init calls tier1.start_server unconditionally → would CLEAR a RUNNING boot's snapshot dirs + claim compose-down ownership (harnesses/tests attaching to live servers must use EXTERNAL; tier2 should probably check is-running before starting — design call). NEW: tier1 client SIGTERM-not-ours bug FIXED (ownership guard in start_client) but the symmetric start_server path still sets started_by_us after a compose up that may have been a no-op. Pre-existing: client-mode fresh starts don't clear snapshots (docker-only); execute_duckdb still accepts non-SELECT (same exposure as before, now on the shared DB); inserter typed ElectricState=None; `electric_network_id` DB column unlifted; raw-int statuses; L1.5 component tables (Harshit's parked design call); L1.7 belt segments (expected red); L6 scale battery (needs factory generator).

### Verification Integrity

#### [VERIF-1] Throughput meter's snapshot tick FROZE mid-run — production feedback stale for 7 turns
- **Severity:** CRITICAL for eval verdicts (a producing factory can read as a false FAIL; agent sees phantom "0 produced")
- **Observed in:** engine_unit_throughput attempt 3 / claude-sonnet-4.6 / 2026-06-11_15-14-28 (found by the trace retro, independently confirmed: `Snapshot tick: 404340` repeated 63× in the throughput meter T10→T16 while observe.py probes show the game advancing 360557→554661)
- **Evidence:** the in-run Task Progress notifications kept reporting the same snapshot tick + 0 rate for the entire back half of the run; the agent's production feedback channel was a frozen frame indistinguishable from "factory dead".
- **Impact:** double: (a) ThroughputVerifier may judge PASS/FAIL on stale state; (b) the agent loses its only closed-loop production signal — it can't tell a broken factory from a stale meter.
- **Fix direction:** find why the verifier's snapshot stopped advancing (chunk re-snapshot cadence for the cell? verifier reading a cached DB connection that stopped reloading?); make staleness LOUD in the meter (builds on the SNAP-1 staleness-banner TODO — `chunk_snapshot_meta` exists for exactly this); add an L-row check: meter tick must track game tick within a bound during a live run.

#### [STATUS-1] Entity statuses reach the agent as raw integers — diagnosis latency is the cost
- **Severity:** high (twice load-bearing on 2026-06-11: attempt 3 lost ~3 turns chasing pole topology while `54` meant no_power and the root cause `53`/no_fuel sat one inspection upstream; the retro shows the agent reacted faster wherever the symbolic name leaked via `__repr__`)
- **Formalizes:** TYPE-1's remaining ask (symbolic status names at payload/dump tier; names exist only in `__repr__` today).
- **Fix direction:** map `defines.entity_status` ints → names in the snapshot payload + inspection results + DB column (or a lookup table the prompt documents); add the diagnose-upstream idiom to the prompt (PROMPT-2b) so no_power triggers a generator-side status walk.

### Information Surfaces (attempt-3 base archaeology + legibility audit; docs/INFORMATION_SURFACES.md is the parent doc)

#### [MIRAGE-1] System prompt documents DEAD database surfaces with worked examples
- **Severity:** high (documentation actively teaches false world-facts)
- **Evidence:** prompt schema reference documents the `inserter`/`transport_belt`/`mining_drill`/`assembler` component tables incl. a worked JOIN example (`schema_reference.py:327-332`; in attempt-3's actual prompt at lines 3033/3163) — tables certified **0 rows always** since 2026-06-10 (ledger L1.5 ❌). `power_statistics` likely same class (mod writes jsonl, loader never ingests, schema documented). An agent following our docs gets empty results and learns "no inserters exist".
- **Fix direction:** Harshit's L1.5 design call (populate vs views-over-raw_data vs drop) now has a forcing function — whichever way, the schema reference must reconcile; add a standing audit gate: ledger ❌ on a surface propagates to every surface documenting it.

#### [RESERVE-1] Inserter drop/pickup cells are invisible at placement time
- **Severity:** high — the single most damaging layout mechanic in attempt 3: poles placed onto cells an inserter's hand needs (Harshit's obs #2, class A), triggering place→pickup→replace rework loops whose residue is the smelting-row gaps and disconnected belt stubs (obs #1/#3/#4, class D).
- **Fix direction:** placement validation/cues must treat occupied drop/pickup cells as soft-blocked and NAME the reserving inserter in errors; expose reserved cells as a queryable surface.

#### [ISLAND-1] Nothing tells the agent about its own orphans (ghosts, disconnected islands)
- **Severity:** medium-high — 20 ghost belts and an entire abandoned left factory (obs #7/#8) kept producing/lingering with zero signal; Task Progress shows throughput only.
- **Fix direction:** Task Progress inventory line: pending ghosts count, producing-but-uncollected machines, disconnected belt segments.

#### [REASON-1] Empty cue lists drop their reason at the Python wrapper
- **Severity:** medium — the Lua tier now returns a structured `reason` on zero cues (L4.6 fix) but `get_connection_positions` returns a bare list; attempt 3's agent got `[]` for its second power rig and improvised the dead boiler-next-to-pump placement (obs #9, class C aggravated by missing why).
- **Fix direction:** surface `reason`/`blocked_candidates` through the wrapper (rich return or exception message).

#### [POLE-PREVIEW-1] No pre-placement pole supply/reach preview
- **Severity:** low-medium — poles mostly worked (obs #10, class B), but supply-area reasoning was blind guessing; also reconcile the generator-boundary network split (nets 1 vs 9, silent).
- **Fix direction:** expose supply-area coverage + wire-reach preview in pole cues; pole-network census in remote_view.

### Walking / Pathfinding

#### [ARG-2] walk_to options.entity_ref dead via remote interface
- **Severity:** medium. RemoteInterface.lua:371 dispatches 3 args; walking.lua reads entity_ref as 4th positional — entity-aware walking is unreachable from RCON/agents. Found by check_L4_5.
- **Fix direction:** align the dispatch arity; add an L4.5 case for entity-aware walk.

#### [OBS-3] status='failed' UDP datagrams drop result/failure_type
- **Severity:** medium. `create_action_payload` (udp.lua:99-119) omits `result` for status='failed' — failure_type/goal/message are lost on the wire; Python only sees "failed". The status itself is honest (exactly-once certified), but the agent loses the WHY at the async boundary (ERR-2-adjacent).
- **Fix direction:** include the failure payload in failed datagrams; extend check_L4_5's void-walk case to assert failure_type arrives.

---

### API Gaps

#### [API-2] Placement pre-check reason is a stub — RECLASSIFIED 2026-06-10: affordance exists (L4.1)
- **Severity:** medium (polish + visibility)
- **Observed in:** engine_unit_throughput / claude-sonnet-4.6 / 2026-03-28
- **Root cause (L4.1 certification):** the pre-check EXISTS and is agent-reachable — `placement_hints.validate_placement` works but returns stub `reason:"placement_blocked"` (area.lua:50 TODO), while `get_placement_cue` already returns `colliding_entities` + `reason:"collision"` + footprint. Placement honesty itself certified: 22-cell sweep, 0 disagreements.
- **Fix direction:** replace the area.lua stub reason with `get_placement_cue`-grade detail; ensure docs/prompt surface `validate_placement`/`get_placement_cue`.

---

### Type System

#### [TYPE-1] Pipe entity missing .status and .direction attributes
- **Severity:** high
- **Observed in:** engine_unit_throughput / claude-sonnet-4.6 / 2026-03-28
- **Evidence:** Agent placed pipes, then tried `pipe.status` and `pipe.direction` — both raised `AttributeError` while verifying placement.
- **Status note 2026-06-11 (LIVE-1A):** `.status`/`.direction` now present at payload AND typed tiers (live-verified) — the original AttributeError class is gone. Remaining ask: symbolic status names at the payload/dump tier (raw ints today; names only in `__repr__`).
- **Fix direction:** add/verify `.status` (symbolic) and `.direction` on Pipe; align with the L2.3 status-labels finding.

#### [TYPE-2] ResourceOrePatch missing .amount attribute
- **Severity:** medium
- **Observed in:** engine_unit_throughput / claude-sonnet-4.6 / 2026-03-28
- **Evidence:** `ore_patch.amount` raised AttributeError; docs referenced `.amount`, property is `.total` — doc/code drift class (the L3.1 validator now catches accessor-call drift, but property-style accesses are its documented residual gap, see L3.1b row).
- **Fix direction:** align docs with implementation or add the alias; extend the validator to property accesses (L3.1b residual).

---

### Placement / Spatial

#### [PLACE-2] Agent gets physically trapped by placed entities
- **Severity:** high → partially mitigated
- **Observed in:** engine_unit_throughput / claude-sonnet-4.6 / 2026-03-28
- **Evidence:** After placing pipes and a boiler, walking was blocked in all directions; 3 consecutive WalkingUnreachableErrors.
- **Mitigations since:** pickup_entity certified working (self-rescue by removing adjacent entities); ERR-2 errors now carry position/distance context. Not yet addressed: walk-over-own-pipes or teleport_to_entity.
- **Fix direction:** consider walkability rules for own low entities or a constrained teleport affordance; needs design input (agent-affordance realism question).

---

### Prompt / Docs

#### [PROMPT-2] Model doesn't know belt/inserter placement patterns — WIDENED 2026-06-11: connection-cue discoverability
- **Severity:** medium → high (now the main residual blocker for engine_unit)
- **Observed in:** engine_unit_throughput / claude-sonnet-4.6 / 2026-03-28; re-observed 2026-06-11 finale attempt
- **Evidence:** Only 2 belt / 4 inserter references in 55 code blocks; planning comments never described belt/inserter layouts. 2026-06-11 finale: agent used the new AFFORD-1 affordances well (find_water, 8× is_buildable) but called `get_connection_positions` ZERO times — hand-placed a steam engine flush against a boiler WATER port (adjacent, fluid-dead) then tore the rig down. The cue layer itself is now certified connection-guaranteeing (L4.6, 18/18) — the gap is purely that nothing teaches the model to reach for it.
- **Fix direction:** ~~system-prompt worked example for the power-chain idiom~~ DONE @ 40353fb — and attempt 3 followed it verbatim, power chain first-pass at T0. REMAINING (PROMPT-2b, from the attempt-3 retro): (a) power-as-consumable-loop — the worked pattern must end with coal automation INTO the boiler (drill→inserter→boiler), not a one-time add_fuel; (b) diagnose-upstream idiom — no_power means walk the generator chain's own statuses (engine→boiler→fuel) before touching pole topology; (c) note the boiler's tiny fuel buffer (~11 coal/insert observed). Belt/inserter logistics worked-pattern still open. |

---

---

## Archive

*Resolved or stale issues, one line each. Certification evidence: `.fv-output/certification/<date>/<id>/` + FLOOR_CERTIFICATION.md rows.*

- [CELL-1] Agent body and DB vision in DIFFERENT cells (run-killer of the 2026-06-11 field run) — fixed da0cb2f, live-accepted 2026-06-11 (L0.4 both paths @ 108d475 + LIVE-1C eval session @ 1ca2af3). Was NOT allocation: initial_state baked pre-allocation, a 2s "proceeding anyway" lying wait, an unscoped loader replaying destroyed entities, and tier4/RemoteView holding two separate DuckDBs. Full forensics: `.fv-output/certification/2026-06-11/CELL-1/` + git history of this entry.
- [CELL-2] Snapshot dir never cleaned across boots (stale cells' files in every session DB) — fixed da0cb2f + 1ca2af3 (attach guard), live-accepted 2026-06-11: boot clearing exercised twice, phantom-free eval session, future-tick loader guards pinned by unit tests. Residual: client-mode (non-docker) fresh starts still inherit snapshots.

- [SNAP-1] Session DB incoherent in lab-grid (water_tile 0, map_entity [], tick frozen) — fixed 2026-06-11 (8ea7a5c), certified L1.10. Was: scenario `on_chunk_generated` wiped cell_0 barren (DB truthfully reported a broken world — retro's "216 tiles existed" was measured on a different boot) + `snapshot_area` silently skipped snapshotted chunks. Fixes: chunk-scoped restore, re_snapshot on agent creation + honest skip counts, per-file chunk_meta ticks → `chunk_snapshot_meta` table. Staleness-LOUD banner in tool results still TODO (build on chunk_snapshot_meta).
- [SNAP-2] "initial_state race" — decomposed 2026-06-11 (8ea7a5c), live-accepted: no race existed; empty resources = SNAP-1, empty inventory = ParamSpec nil-collapse (`{...}`/table.insert/unpack drop args at nil holes). All 3 create_agent conventions deliver inventory/force/port correctly (SNAP-2-live).
- [SNAP-3] Stale init files survive raise-less destroys — fixed 2026-06-11 (376729c), certified: meta-only rewrite for previously-written-now-empty categories (ChunkTracker files_written). Residual became SNAP-5.
- [SNAP-4] Agent pickup removals invisible to snapshot (20 phantoms/500-op churn) — fixed 2026-06-11 (376729c), L1.6 re-certified green: `entity.mine{inventory, raise_destroyed=true}`; spill-on-full pre-check live-certified 2026-06-11 (LIVE-1A).
- [SNAP-5] Updates-log replay resurrects silently-destroyed entities — fixed-offline 2026-06-11 (4cf7998): loader drops upserts older than chunk init tick (chunk_meta ordering); live re-certified 2026-06-11 (LIVE-1A: 9/9 stale records dropped, init wins, 0 replayed).
- [API-1] "No entity pickup method" — reclassified doc gap, fixed 2026-06-10, pickup certified working (L4.3: removal + inventory credit). Was: `entity_ops.pickup_entity` existed but was unregistered in the doc registry → invisible to agents.
- [ERR-1] Placement errors were raw Lua tracebacks — fixed 2026-06-10, certified L4.2 (RAW 0/4): structured causes (collision lists, out-of-reach + walk-closer).
- [ERR-2] WalkingUnreachableError had no spatial context — fixed 2026-06-11 (d7fd560): message carries agent/target positions, distance, bearing, out-of-bounds hint; attrs on the exception.
- [ERR-3] placement_hints wrappers swallowed exceptions as [] — fixed 2026-06-11 (75379b5): ConnectionQueryError with "query failure ≠ no valid positions".
- [ERR-4] Crafting/inventory raw throws, locked-vs-missing indistinguishable, partial-insert-then-throw — fixed-offline 2026-06-11 (9b07b23): L4.2-contract errors (locked recipe names its tech, missing ingredients have/need, partial insert = honest success + rollback, six inventory-type names documented). Live-accepted 2026-06-11 (LIVE-1A, 18/18). Note: lab-grid enables all recipes per cell force — the locked-recipe path requires an explicit disable to fire there.
- [PLACE-1] get_connection_positions returned [] for boiler→steam-engine — fixed 2026-06-10/11, certified L4.4 twice (open-ground pass, field failure, per-direction staging fix, east-case green).
- [PROMPT-1] factoriopedia promised but not in namespace — resolved by removal + guard: docs no longer promise it (L5.1 certified 0 phantom names 2026-06-11; negative control catches re-introduction). The module itself is parked on token_compression.
- [PROMPT-3] Cell bounds undocumented — fixed 2026-06-11 (7012629): initial_state "Your Working Area" section with hard bounds + don't-probe-beyond guidance. Live render check in LIVE-1 #6.
- [AFFORD-1] Placement-as-sonar (no terrain affordance) — fixed 2026-06-11 (f6fd8b7): `remote_view.find_water()` + `placement_hints.is_buildable()`, doc-registered. Live-exercised 2026-06-11 (LIVE-1A: find_water SQL + validate_positions green vs engine truth); full RemoteView object path rides the next eval.
- [OBS-2] Task Progress ×163 + 30k uncached prefix (~10M prompt tokens/17 turns) — fixed 2026-06-11 (675ac71): ProgressDeduper + anthropic cache_control, −49.7% on trajectory replay. Cache-hit observation in LIVE-1 #5.
- [PATH-1] lab-grid pathfinder dead (chunk_generated_status never set) — fixed in 339f792, live-accepted 2026-06-11 (two walk_to round-trips with UDP completions, no workaround). Was: ALL walk_to failed map-wide in ~1 tick; the control.lua "Key technique" comment promised a call that never existed.
- [ARG-1] Per-agent action interfaces corrupted sparse named-table calls — fixed in 339f792 (ParamSpec table.pack treatment on the per-agent twin), live-accepted 2026-06-11 (named-table place_entity without direction places real chest + ghost; positional unaffected). Was: omitted optional args shifted later named args into their slots.
- [LOOP-1] Assistant messages missing content field — fixed 2026-03-28. Was: `to_dict()` omitted `content` when None, causing 422 on APIs that require it.
- [DATA-1] 2.0.76 dump shifted prototype scope (89/106/99 vs certified 73/113/85) — resolved 2026-06-11, L3.2/L3.3 green. Was: `--dump-data` force-loads DLC ignoring mod-list (and persists re-enabled flags back!); 100% of scope drift attributed to Space Age recategorization, 0 to engine/filters. Runtime was never contaminated (prepare_mods disables DLC at every server start; verified via script.active_mods). Re-dump with DLC dirs removed in-container → 73/113/85 restored, 458/458 hydration exact on 2.0.76. Dead `DLC_SPACE_AGE` env removed from compose generator.

---

## Run Log

Summary of eval runs and which issues were observed, for tracking recurrence.

| Date | Task | Model | Result | Issues Hit | Cost |
|------|------|-------|--------|------------|------|
| 2026-03-28 | iron_plate_throughput | anthropic/claude-sonnet-4.6 | PASS (54.5/60s) | None | $1.41 |
| 2026-03-28 | production_science_pack_throughput | anthropic/claude-sonnet-4.6 | FAIL (0 produced) | LOOP-1 | $0.67 |
| 2026-03-28 | engine_unit_throughput | anthropic/claude-sonnet-4.6 | FAIL (0 produced) | API-1, API-2, ERR-1, ERR-2, TYPE-1, TYPE-2, PLACE-1, PLACE-2, PROMPT-1, PROMPT-2 | ~$2-3 |
| 2026-06-10 | engine_unit_throughput | anthropic/claude-sonnet-4.6 | KILLED T17/64 (0 produced) | SNAP-1 (run-killer), SNAP-2, PLACE-1 (field regression), ERR-2, ERR-3, ERR-4, PROMPT-3, AFFORD-1, OBS-2, TYPE batch | ~$8-10 (10.08M prompt tokens) |
| 2026-06-11 | (lab-grid run, post-certification) | — | FAIL (0 produced) | CELL-1 (run-killer: body/vision cell desync), CELL-2 (stale snapshot contamination) — agent reasoned correctly on wrong-cell data | — |
| 2026-06-11 | iron_plate_throughput (LIVE-1C acceptance) | anthropic/claude-sonnet-4.6 | PASS (70 automation) | None blocking — caught PROMPT-3 render gap, OBS-2 observability gap, server-ownership teardown (all fixed same day) | ~$1.4 |
| 2026-06-11 | engine_unit_throughput (finale attempt 2) | anthropic/claude-sonnet-4.6 | KILLED T1 | Agent USED the cue API verbatim (PROMPT-2 fix works) but LUA-1 fallback served a direction-less garbage cue when its own body blocked both boiler mates → fluid-dead boiler. Fallback killed + cue/act parity + BODY-BLOCKED battery case same day (L4.6 amendment) | ~$0.5 |
| 2026-06-11 | engine_unit_throughput (finale attempt 3) | anthropic/claude-sonnet-4.6 | KILLED T16 (0 produced, Harshit's call) | BEST RUN YET — first failure that's a genuine strategy gap, not a harness lie. Power chain connected FIRST-PASS via cues at T0 (the assembly that killed 3 prior runs); factory RAN (1,893 ore, 1,604 plates by engine stats) then died of FUEL STARVATION: boiler cycled no_fuel (53) hand-fed 4×, coal→chest loop built 30 tiles from the boiler, never coal→boiler; no_power traced upstream only at T16 (correct diagnosis, out of turns). NOT generation undersizing — retro corrected that early hypothesis. → STATUS-1, PROMPT-2b, VERIF-1 (frozen verification feed found by retro). 12.35M prompt / 97% cached (OBS-2 live; March was 10M at 0%). Full retro: docs/retros/2026-06-11-engine-unit-attempt3-retro.md | ~$1.5-2 |
