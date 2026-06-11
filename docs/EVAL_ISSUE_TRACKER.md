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
| Pending live acceptance (fixes deployed/awaiting deploy) | 0 | 1 | 0 | 0 | 1 |
| API Gaps | 0 | 0 | 1 | 0 | 1 |
| Type System | 0 | 1 | 1 | 0 | 2 |
| Placement/Spatial | 0 | 1 | 0 | 0 | 1 |
| Prompt/Docs | 0 | 0 | 1 | 0 | 1 |
| Data Pipeline | 0 | 1 | 0 | 0 | 1 |
| **Total** | **0** | **4** | **3** | **0** | **7** |

*Last updated: 2026-06-11 — certification session (12 issues fixed and archived; see Archive + FLOOR_CERTIFICATION.md)*

---

## Active Issues

### Pending live acceptance

#### [LIVE-1] NEXT-SESSION WORKLIST (handoff 2026-06-11 — items 1+2+4 DONE same day, see below; 3 and 5 remain)
- **Severity:** high (gates the CELL-1 closure + the eval program)
- **State:** server_0 up fresh (lab-grid, game.speed=5 for faster Lua/snapshot throughput); all work committed through `108d475`.
- **Sequence:**
  1. ✅ DONE 2026-06-11: fresh restart exercised boot invalidation TWICE — snapshot volume cleared both times (CELL-2b live-confirmed).
  2. ✅ DONE 2026-06-11 @ 108d475: L0.4 GREEN ON BOTH PATHS (see ledger row). En route, the harness's own drafted drain criterion turned out to be a CELL-1-class lying wait (proceeded at pending=31 mid-bootstrap; 73 phantom failures on the true first clean run) — replaced with wait_fresh (IDLE + write_queue==0 + per-chunk lookup freshness, timeout RAISES). `--path orchestrator` implemented for real: EXTERNAL-mode Environment stack, orch._allocate_cell/_release_cell cycles, vision on the orchestrator's own session DB via unified execute_raw.
  3. **CELL-1/CELL-2 live acceptance** (the big one, NEXT): one eval-path session (`fv eval` or equivalent) asserting: initial_state.md shows the agent's OWN cell (its 484-tile patches at in-cell coords + Working Area section = PROMPT-3 render check); `wait_for_cell_snapshot` verifies-or-raises (no silent proceed); `remote_view.query` == `execute_duckdb` on the same SQL; zero phantom entities (CELL-2); `cache_read_input_tokens > 0` in the LLM usage (OBS-2). The T0 preflight ("CELL COHERENCE VIOLATION") should stay silent. NOTE: orchestrator-path L0.4 already covers the allocation/vision/one-DB half of this from below the eval layer — what remains uniquely here is tier5/6: initial_state ordering+render, LLM cache hits, and the full `fv eval` wiring.
  4. ✅ DONE 2026-06-11: `map.get_chunk_lookup` JSON shape live-verified (dict keyed "cx,cy" → {snapshot_tick, files_written, ...}) — now load-bearing in both the harness's wait_fresh and its CELL-2 sub-check. `pending_chunks` semantics pinned down as bycatch: drains to 0 ONLY on fresh boots; idles >0 forever once cell resets accumulate (it counts never-requested chunks map-wide).
  5. Then the **gated finale** (Harshit's spend approval): engine_unit field re-run WITH observe.py in-run ground-truth probes.
- **Known residuals (non-blocking):** NEW: Environment SERVER-mode init calls tier1.start_server unconditionally → would CLEAR a RUNNING boot's snapshot dirs + claim compose-down ownership (harnesses/tests attaching to live servers must use EXTERNAL; tier2 should probably check is-running before starting — design call). NEW: tier1 client SIGTERM-not-ours bug FIXED (ownership guard in start_client) but the symmetric start_server path still sets started_by_us after a compose up that may have been a no-op. Pre-existing: client-mode fresh starts don't clear snapshots (docker-only); execute_duckdb still accepts non-SELECT (same exposure as before, now on the shared DB); inserter typed ElectricState=None; `electric_network_id` DB column unlifted; raw-int statuses; L1.5 component tables (Harshit's parked design call); L1.7 belt segments (expected red); L6 scale battery (needs factory generator).

### Cell / Vision Coherence

#### [CELL-1] Agent cell assignment desynced from snapshot/remote_view scope — body and vision in DIFFERENT cells
- **Severity:** CRITICAL — nullifies every lab-grid eval until fixed (run-killer of the 2026-06-11 field run)
- **Observed in:** field run 2026-06-11 (post-certification): agent spawned on cell_0 at (50,119); engine ground truth has cell_0's iron at (5.5,59.5) right next to it; but the DB/initial_state served iron at (334.5,229.5), water at (433,238) — cell ~10's patches, 250+ tiles away behind force walls. Agent reasoned correctly on the data, walked into walls, burned the budget probing for an exit. 0 produced; model not at fault.
- **Corroboration:** the "chests at (382–388,227)" in the agent's DB are the PATH-1/ARG-1 probe's test chests (same boot, cell 10) — destroyed in probe cleanup but never re-snapshotted → the DB served a destroyed rig from stale init files (see CELL-2).
- **Hypothesis to trace:** the eval's allocation path (orchestrator `_allocate_agent_in_cell` vs `lab_grid.create_agent_in_cell`) diverges from the chart+re_snapshot scope — the agent's cell never got charted/snapshotted into the session DB, so the only content in the DB was other cells' stale files. NOTE: scenario fns are positional-only (playbook trap) — a named-table call into create_agent_in_cell would nil-collapse cell_index and silently change behavior.
- **ROOT CAUSE (traced 2026-06-11, .fv-output/certification/2026-06-11/CELL-1/):** allocation was CORRECT (cell_0, body+storage agree); it's an ordering bug + a lying wait: (1) `run_task` loads the DB and bakes initial_state.md BEFORE `_allocate_cell` (orchestrator.py:475 vs :478) — the agent's anchor observation is unconditionally pre-allocation; the only disk content was cell_10's stale probe files. (2) `wait_for_cell_snapshot` (lab_grid.py:616-634) exits on a GLOBAL pending==0 heuristic with a 2s "proceeding anyway" complete=True fallback — the post-allocation reload ran mid-write and missed cell_0's water file (216 tiles) by ~1s. (3) `load_all` (loader.py:55,86) globs every chunk dir, no scoping/tick guards; replay re-upserted cell_10's 4 destroyed chests. (4) BONUS: tier4 and RemoteView hold SEPARATE SnapshotDatabases — `reload_snapshot_data` refreshes only one → `remote_view.query` and `execute_duckdb` serve different truths.
- **Status: FIXED-OFFLINE 2026-06-11** (fix batch, `.fv-output/certification/2026-06-11/CELL-1-fixes/`): (1) run_task/run_freeplay allocate BETWEEN tier4 and tier5 — initial_state baked post-allocation (regenerate + tier6.reset fallback for pre-initialized entry paths); (2) `wait_for_cell_snapshot` is per-cell + honest: all 16 cell chunks' snapshot_tick >= pre-reset min_tick via `map.get_chunk_lookup` AND on-disk chunk_meta freshness; timeout RAISES (the 2s "proceeding anyway" fallback is gone); (3) execute_duckdb routed through new `RemoteView.execute_raw` (same connection/lock/flush as remote_view.query) + reload rebuilds RemoteView — one DB truth; (4) post-allocation preflight raises "CELL COHERENCE VIOLATION" on body-outside-bounds / no in-cell resources in DB / future-tick chunks. **LIVE acceptance owed (next session): eval-path session with own-cell initial_state, wait raising not lying, remote_view == execute_duckdb.**

#### [CELL-2] Snapshot dir is never cleaned across sessions/boots — stale cells' files load into every new session DB
- **Severity:** high (CELL-1 made it fatal; on its own it serves destroyed entities + other cells' contents as live data)
- **Evidence:** same field run — cell 10's init files (written by an earlier probe on the same boot, rig destroyed without a post-cleanup re-snapshot) loaded into the eval session's DB. Host volume `.fv-output/server_0/factoryverse/snapshots` also persists across container restarts, so FRESH scenario boots inherit prior boots' snapshots entirely.
- **Status: FIXED-OFFLINE 2026-06-11**: (a) fresh scenario server starts clear `<output>/factoryverse/snapshots` before container start (save loads keep theirs; logged); (b) loader skips init files/update records with tick > game.tick — loud log, None = old behavior, 5 unit tests pinned; (c) RUNTIME_PLAYBOOK §5: mutating runners MUST re_snapshot_area after cleanup. **LIVE acceptance owed: phantom-free DB in the next eval session.** Residual: client-mode (non-docker) fresh starts still inherit snapshots.

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

#### [PROMPT-2] Model doesn't know belt/inserter placement patterns
- **Severity:** medium
- **Observed in:** engine_unit_throughput / claude-sonnet-4.6 / 2026-03-28
- **Evidence:** Only 2 belt / 4 inserter references in 55 code blocks; planning comments never described belt/inserter layouts.
- **Fix direction:** review system-prompt examples for drill→furnace→assembler logistics patterns; add worked examples if absent. (Design/prompt work, not a bug.)

---

---

## Archive

*Resolved or stale issues, one line each. Certification evidence: `.fv-output/certification/<date>/<id>/` + FLOOR_CERTIFICATION.md rows.*

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
