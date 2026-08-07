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
| Verification Integrity (STATUS-1; VERIF-1 closed) | 0 | 1 | 0 | 0 | 1 |
| Pending live acceptance (gated finale only) | 0 | 1 | 0 | 0 | 1 |
| Information Surfaces (MIRAGE-1..4, REPR-1, META-1, PROV-1 narrowed, CONF-1, DISPATCH-1, RESERVE-1, ISLAND-1, REASON-1, POLE-PREVIEW-1; PROV-2 closed) | 0 | 6 | 6 | 1 | 13 |
| Walking/Pathfinding | 0 | 1 | 2 | 0 | 3 |
| API Gaps | 0 | 0 | 1 | 0 | 1 |
| Type System | 0 | 1 | 1 | 0 | 2 |
| Placement/Spatial | 0 | 1 | 0 | 0 | 1 |
| Prompt/Docs | 0 | 1 | 0 | 0 | 1 |
| Freeplay Policy / Long-Horizon Control (FREEPLAY-1..4) | 0 | 4 | 0 | 0 | 4 |
| Context / Retrieval (CTX-1) | 0 | 1 | 0 | 0 | 1 |
| Evaluation Metrics (SCORE-1) | 0 | 1 | 0 | 0 | 1 |
| Codex Adapter / Ownership (CODEX-GOAL-1) | 0 | 0 | 1 | 0 | 1 |
| Infra/Ops (MODLIST-1, MODSYNC-1) | 0 | 0 | 0 | 2 | 2 |
| **Total** | **0** | **18** | **11** | **3** | **32** |

*Update 2026-08-07 — `codex-terra-factory-debug-20260807-004` was operator-stopped after 115 completed turns. The run exposed a family of long-horizon freeplay issues: a direct-burner maintenance treadmill, construction-inventory hoarding, blank durable architecture across four compactions, 24 state-only action turns, repeated broad workspace reads, and an automation metric that credits actor-serviced production. Full audit: `docs/retros/2026-08-07-codex-terra-freeplay-004-context-and-policy-audit.md`. These are one-run findings and proposed measurement/fix directions, not yet generic strategy policy.*

*Last updated: 2026-07-12 (later session) — **POWER INTEGRATION BUILD** (full plan + per-finding dispositions in docs/retros/2026-07-12-power-surface-audit.md §6): per-network power stats + symbolic status pipeline shipped and certified (**ledger L1.16 + L1.17**, both executed; L1.17 red-first caught STATUS-WALK-FEEDER — status walk scoped to charted chunks that lab-grid SELECTIVE never marks). Fixed this session: **MIRAGE-2** (electric_network_id + force lifted, live-verified non-NULL through the eval stack), **REASON-1** (ConnectionPositionList.reason), **ARG-2** (+ new ARG-4 teleport positional, same dispatch file, both live-verified), STATUS-1 mostly (symbolic names in DB `entity_status` + reachability payloads + diagnose verdicts; residual: EntityInspection.model_dump_json still emits raw int), POLE-PREVIEW-1 partially (prototype-backed helpers — big-pole wire 30→32 hardcode drift — + `get_power_networks()` census + `diagnose_power()`; pre-placement preview cue still open), PROMPT-2b DONE (fuel-loop worked pattern + diagnose-upstream idiom + digest teaching, +6.9k chars measured). New same-session found+fixed: SYNC-PATH-1 (live file_io sync was a silent no-op — tier4 passes `factoryverse/snapshots` as snapshot_dir, `_resolve_file_io_path` duplicated the segment; 4 unit tests + E2E re-verified). NEW PENDING ADJUDICATION: L4.6-FLAKE (drop_target resolves ~3s vs harness's 1.0s sleep → 2/20 false FAILs, contradicts the 2026-06-11 18/18 row; harness untouched). Still open from the power audit: PWR-GEN-INVIS-1 (EEI invisible to reachable view Lua-side; steam-engine visibility untested), PWR-FORCE-1 residual (within-cell power physically shared between friendly agent forces — scenario-design fact). Earlier same day: GLOBAL-NET-1 (observability-mutates-physics, the terra-pro run's headline) fixed + certified ledger L1.14, AND DB-VISION-1 (eval-path vision frozen at boot — tier4 never wired RemoteView's sync; wrong snapshot port on top) fixed + certified ledger L1.15, both same session; archived with fallout notes. NEW: MODLIST-1 (docker auto-restart bypasses prepare_mods' DLC disable — the 23:49 self-restart booted with Space Age active and wiped the terra-pro forensic factory). Remaining terra-pro findings (ERR-5/ERR-6/ARG-3/ERR-1-residual, EVAL-PORT-1) stay PROPOSED in docs/runs/2026-07-11-engine-unit-terra-pro.md pending adjudication/fix. Prior: 2026-07-08 — ledger L1.11 first execution (GEN-DB-1, the generated anti-mirage battery): MIRAGE-1/2 mechanically reproduced (both proven loader-lift gaps — the data is in raw_data); NEW: MIRAGE-3 (dead tile-lookup surface incl. lying remote_view affordances), MIRAGE-4 (ghost builder-lift asymmetry), REPR-1 (direction ints vs documented names; emitted direction_name dropped), META-1 (chunk_snapshot_meta blind for empty chunks), PROV-1 (re-snapshot squashes provenance). Prior: VERIF-1 CLOSED as ledger L0.6 (2026-06-11, re-certified 2026-07-04).*

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

#### [VERIF-1] ✅ CLOSED 2026-06-11 (ledger L0.6) — Throughput meter's snapshot tick FROZE mid-run — production feedback stale for 7 turns
- **Severity:** CRITICAL for eval verdicts (a producing factory can read as a false FAIL; agent sees phantom "0 produced")
- **Observed in:** engine_unit_throughput attempt 3 / claude-sonnet-4.6 / 2026-06-11_15-14-28 (found by the trace retro, independently confirmed: `Snapshot tick: 404340` repeated 63× in the throughput meter T10→T16 while observe.py probes show the game advancing 360557→554661)
- **Evidence:** the in-run Task Progress notifications kept reporting the same snapshot tick + 0 rate for the entire back half of the run; the agent's production feedback channel was a frozen frame indistinguishable from "factory dead".
- **Impact:** double: (a) ThroughputVerifier may judge PASS/FAIL on stale state; (b) the agent loses its only closed-loop production signal — it can't tell a broken factory from a stale meter.
- **ROOT CAUSE (confirmed against the attempt-3 trajectory):** NOT the chunk snapshot pipeline. `Agents.lua` production poll dedups unchanged stats with no heartbeat — once the factory lost power (fuel starvation @ ~tick 404340), every poll deduped, `production-statistics.jsonl` froze, and `AgentSnapshotSource` served the dead frame's tick forever. The feed froze EXACTLY when production halted — the moment a truthful signal mattered most. Same mechanism explains the run's early 8-check stretch at tick 86520 (idle start). Worse: frozen tick ⇒ `delta_ticks=0` ⇒ silent 0-rate that RESET the consecutive-pass counter — the harness failure punished the agent.
- **FIX (4 layers, all certified L0.6):** (1) Lua heartbeat — dedup forces a full write every 5 skipped polls, ≤300 game-tick staleness, growth bound intact; (2) eval grader switched to `RCONSource` (live engine truth; its `map.get_game_tick` remote NEVER existed → silent tick=0, replaced with raw silent-command); (3) `ThroughputVerifier` runtime invariant — tick advances or the result is `feed_stale=True` with a loud reason; stale/no-data checks neither reset nor advance the consecutive counter; same-frame-within-grace holds instead of fabricating a 0-rate; (4) both meter renderers show a `⚠️ VERIFICATION FEED PROBLEM` block instead of a fake rate; `feed_stale` lands in trajectory verification_check events. Pinned by `tests/unit/test_verifier_feed_staleness.py` (6 tests incl. a regression pin for a falsy-zero walltime bug caught en route — PY-1 class strikes again).

#### [STATUS-1] Entity statuses reach the agent as raw integers — diagnosis latency is the cost
- **Severity:** high (twice load-bearing on 2026-06-11: attempt 3 lost ~3 turns chasing pole topology while `54` meant no_power and the root cause `53`/no_fuel sat one inspection upstream; the retro shows the agent reacted faster wherever the symbolic name leaked via `__repr__`)
- **Formalizes:** TYPE-1's remaining ask (symbolic status names at payload/dump tier; names exist only in `__repr__` today).
- **Fix direction:** map `defines.entity_status` ints → names in the snapshot payload + inspection results + DB column (or a lookup table the prompt documents); add the diagnose-upstream idiom to the prompt (PROMPT-2b) so no_power triggers a generator-side status walk.
- **MOSTLY FIXED 2026-07-12 (power build, certified L1.17):** symbolic lower_snake names now in (a) the `entity_status` DB table (60-tick full snapshots, heartbeat-on-empty, freshness marker), (b) reachability payloads (`status_name` alongside the int, mirroring direction_name), (c) `diagnose_power()` named verdicts, (d) the reachable-view status filter (accepts names, was a never-matches string-vs-int mirage). Prompt idiom shipped (PROMPT-2b) incl. the live-learned caveats: poles carry nil status, starved producers read `working`, logistics statuses mask low_power. **RESIDUAL:** `EntityInspection.model_dump_json` still emits the raw int (only `__repr__` decodes).

### Information Surfaces (attempt-3 base archaeology + legibility audit; docs/INFORMATION_SURFACES.md is the parent doc)

#### [MIRAGE-2] `electric_network_id` DB column documented but always NULL
- **Severity:** high (measured legibility failure: battery probe V18 — model read all-null ids and correctly concluded "0 networks, nothing powered" about a powered factory)
- **Evidence:** scripts/battery/results/v0_claude-sonnet-4.6.json V18; the long-known "electric_network_id column unlifted" residual, upgraded from cosmetic to lying-surface by measurement. **Mechanically reproduced 2026-07-08 (ledger L1.11):** engine net ids non-nil AND the correct value present inside `raw_data` while the column is NULL — the mod emits it; only `loader.py:_insert_entity`'s INSERT list omits it (one-line lift).
- **Fix direction:** lift it from raw_data in the loader, or drop the column + schema docs (MIRAGE-1's reconciliation rule applies).
- **FIXED 2026-07-12 (power build):** `electric_network_id` + `force` added to `apply_ops.upsert_entity`'s INSERT; live-verified non-NULL through the real eval stack (net id 29, force 'player' on a fresh rig, zero reloads). Schema notes now state as-of-write semantics: engine net ids renumber on merge/split (PWR-NETID-1, certified L1.16 phase E) — fresh membership lives in the `power_networks` table; anchor pole (name+position) is the durable network reference.

#### [MIRAGE-1] System prompt documents DEAD database surfaces with worked examples
- **Severity:** high (documentation actively teaches false world-facts)
- **Evidence:** prompt schema reference documents the `inserter`/`transport_belt`/`mining_drill`/`assembler` component tables incl. a worked JOIN example (`schema_reference.py:327-332`; in attempt-3's actual prompt at lines 3033/3163) — tables certified **0 rows always** since 2026-06-10 (ledger L1.5 ❌). `power_statistics` likely same class (mod writes jsonl, loader never ingests, schema documented). An agent following our docs gets empty results and learns "no inserters exist".
- **Fix direction:** Harshit's L1.5 design call (populate vs views-over-raw_data vs drop) now has a forcing function — whichever way, the schema reference must reconcile; add a standing audit gate: ledger ❌ on a surface propagates to every surface documenting it.
- **Amendment 2026-07-08 (ledger L1.11):** mechanically reproduced (all 4 tables 0 rows with their entity kinds confirmed placed), AND the worked JOIN examples are doubly dead: they join on `entity_key`, a column that exists on NO table — the documented SQL raises a DuckDB binder error verbatim. The schema-reference reconciliation must fix the join key too.

#### [MIRAGE-3] Tile-lookup surface is dead: `footprint_tiles` 0 rows + `tile_x`/`tile_y` never lifted — and remote_view queries them live
- **Severity:** high (lying affordances in production: `remote_view.is_tile_occupied` always returns False, `get_entity_at_tile` always None, `get_entities_at_anchor_tile` always empty)
- **Observed in:** ledger L1.11 first execution 2026-07-08 (found by enumeration, confirmed by generated tests)
- **Evidence:** `footprint_tiles` documented as a core table with example queries, CREATE'd, never INSERTed (0 rows while rig entities occupy tiles); `map_entity.tile_x/tile_y` declared and queried (`remote_view.py:672`), absent from the loader INSERT list. Companion tests prove the data exists: every row's `raw_data` carries a correct `footprint_tiles` array and `anchor_tile` — loader-lift gap, same class as MIRAGE-2.
- **Fix direction:** lift both in the loader (data already in the payload), or drop table+columns and the remote_view methods that query them; reconcile schema docs either way.

#### [MIRAGE-4] Ghost provenance columns dead — PARTIALLY FIXED 2026-07-08; `placed_by` residual (design call)
- **Severity:** medium → low-medium residual (`placed_by` only)
- **Observed in:** ledger L1.11 ghost group 2026-07-08
- **Evidence:** agent-placed ghost carries real `agent_id`/`label`/`placed_tick` under `raw_data["builder"]` while the columns were NULL — a one-line asymmetry vs the builder-aware `_insert_entity`.
- **FIXED 2026-07-08 (label + placed_tick):** `loader._insert_ghost` + `sync._apply_ghost_upsert` made builder-aware; live-verified end-to-end (labeled ghost → DB label+tick; family re-run 31 passed/15 xfailed/0 xpassed, flipped tests now live). Shipped alongside as the label-chain work: `build_plan`/`build_ghosts` forward labels at commit; ghosts carry labels engine-side as `tags.fv_label`; build-over-ghost inherits the ghost's label when no explicit label is passed (explicit wins) — smoke: unlabeled build-over produced map_entity row with the plan label + agent provenance.
- **Residual:** `placed_by` — no write path emits that key at any level; Harshit's call: alias `builder.agent_id`/`player_id` into it, or drop from schema+docs. Strict-xfail keeps it registered.

#### [REPR-1] `direction` columns hold raw ints while docs promise names — the emitted `direction_name` is dropped
- **Severity:** high (same diagnosis-latency class as STATUS-1: schema doc says "Entity direction (NORTH, EAST, SOUTH, WEST, etc.)", the model reads `'12'`)
- **Observed in:** ledger L1.11 pilot row 2026-07-08 (map_entity + ghost; the drift L2.5 papered over with harness-side coercion)
- **Evidence:** mod emits BOTH `direction: 12` and `direction_name: "west"` in every entity payload; `_insert_entity`/`_insert_ghost` lift the int into the VARCHAR column. Values are engine-true (derivable), representation contradicts the docs.
- **Fix direction:** lift `direction_name` instead (one line per insert helper), or rewrite the column docs to state the defines.direction int encoding; pairs naturally with STATUS-1's symbolic-names work.

#### [META-1] `chunk_snapshot_meta` is blind for content-empty chunks — freshness undecidable from the DB
- **Severity:** medium (the SNAP-1c "queryable snapshot freshness" surface can't distinguish "empty and fresh" from "never snapshotted")
- **Observed in:** ledger L1.11 terrain group 2026-07-08: 9 of cell 13's 16 chunks had zero meta rows while `map.get_chunk_lookup` reported fresh snapshot_ticks for all 16.
- **Evidence:** init files (which carry the `kind=chunk_meta` line the loader reads) are only written for chunks with ≥1 content category; verified the 9 chunks are genuinely empty. `wait_fresh`-style rituals are unaffected (they read the RCON lookup), but any DB-side freshness consumer inherits the blind spot.
- **Fix direction:** emit a meta-only init line for content-empty snapshotted chunks, or document the table as "content chunks only" and keep freshness authority on `get_chunk_lookup`.

#### [PROV-1] Full re-gather resets the provenance epoch — NARROWED 2026-07-11 (design adjudicated; event-path leg fixed as PROV-2)
- **Severity:** medium (labels now survive every event-path operation — config changes, rotations, partial updates — via the provenance fold rule; the ONLY remaining squash is a full re-gather of a chunk: boot init, `re_snapshot_area`, future radar charting)
- **Adjudicated design (Harshit, 2026-07-11):** the HARD claim ("DB re-derivable from the world, including intent") is deliberately NOT supported — the plumbing (mod-side provenance map) isn't justified at current usage. The SOFT claim stands instead: provenance completeness is conditional on the boot epoch, and the condition must be TRACKED, not hidden. Labels are write-once (set at creation via builder block, changed only by an explicit relabel op, destroyed with the entity).
- **Remaining work:** (1) per-chunk provenance-epoch marker (chunk_snapshot_meta already carries per-chunk tick; provenance trustworthy for events after the chunk's last full-gather tick); (2) surface the flag to the agent (query banner / prompt language — an unsurfaced conditional label column is the next mirage; pairs with the SNAP-1 staleness-LOUD residual); (3) relabel action (Lua, trivial contract: explicit builder-carrying op; mutates label ONLY — agent_id/placed_tick are immutable creation facts).
- **Evidence:** GEN-DB-1/map_entity_builder 2026-07-08 (re-gather squash); the fold rule + fixed event path certified by L1.13 + L1.12 N6 2026-07-11. Fold rule documented as record contract in fv_snapshot/README.md.

#### [CONF-1] Splitter contract state has no write path and is never serialized (inserter slice CLOSED 2026-07-11)
- **Severity:** medium
- **Observed in:** 2026-07-09 entity-surface audit; inserter slice live-verified + FIXED via FILT-1 (ledger L1.12)
- **Evidence:** no `set_splitter_filter/priority` in Lua or Python; `splitter_filter`/`splitter_input_priority`/`splitter_output_priority` (real 2.0 LuaEntity attrs) never serialized — DB cannot distinguish a configured splitter from an unconfigured one. Inserter filters now serialize as `raw_data.inserter.{use_filters, filter_mode, filters:[{index,name}]}`.
- **Fix direction:** splitters were under-designed (Harshit adjudication 2026-07-09): design the splitter config interaction end-to-end on the same spine (EntityInterface method + config event + serialize + accessor_liveness cases). Column-vs-raw_data lift for ALL filter contracts is one design call, made together with L1.5.

#### [DISPATCH-1] Typed layer silently drops unmapped entity categories; ENTITY_CLASS_MAP carries phantom entries
- **Severity:** medium
- **Observed in:** 2026-07-09 entity-surface audit; phantom entry live-confirmed 2026-07-11 (L1.12 filters group: `create_entity{name='filter-inserter'}` → "Unknown entity name" — 2.0 merged filter variants into base `inserter`, the map still teaches a dead `FilterInserter` class)
- **Evidence:** `ENTITY_CLASS_MAP` (create_entity.py:93) lacks nuclear-reactor/heat-pipe/wall/gate/beacon/radar/lane-splitter and both views swallow the dispatch ValueError (reachable_view.py:92-94, query.py:339-341) — those categories are invisible, not raw. Adjudicated 2026-07-09: reactor/heat-pipe/beacon deferred (late game), wall/gate won't-do (no enemies), radar = design item, lane-splitter = add.
- **Fix direction:** make the swallow loud (log + generic-entity fallback) so deferred ≠ invisible; add lane-splitter; purge phantom 2.0-stale entries (filter-inserter and audit siblings).

#### [RESERVE-1] Inserter drop/pickup cells are invisible at placement time
- **Severity:** high — the single most damaging layout mechanic in attempt 3: poles placed onto cells an inserter's hand needs (Harshit's obs #2, class A), triggering place→pickup→replace rework loops whose residue is the smelting-row gaps and disconnected belt stubs (obs #1/#3/#4, class D).
- **Fix direction:** placement validation/cues must treat occupied drop/pickup cells as soft-blocked and NAME the reserving inserter in errors; expose reserved cells as a queryable surface.

#### [ISLAND-1] Nothing tells the agent about its own orphans (ghosts, disconnected islands)
- **Severity:** medium-high — 20 ghost belts and an entire abandoned left factory (obs #7/#8) kept producing/lingering with zero signal; Task Progress shows throughput only.
- **Fix direction:** Task Progress inventory line: pending ghosts count, producing-but-uncollected machines, disconnected belt segments.

#### [REASON-1] Empty cue lists drop their reason at the Python wrapper
- **Severity:** medium — the Lua tier now returns a structured `reason` on zero cues (L4.6 fix) but `get_connection_positions` returns a bare list; attempt 3's agent got `[]` for its second power rig and improvised the dead boiler-next-to-pump placement (obs #9, class C aggravated by missing why).
- **Fix direction:** surface `reason`/`blocked_candidates` through the wrapper (rich return or exception message).
- **FIXED 2026-07-12 (power build):** all three `_get_*_positions` wrappers return `ConnectionPositionList` (list-compatible) carrying `.reason`/`.max_wire_distance`/`.search_metadata`; empty results repr the reason. Fluid's Lua reason passes through; electric/item get a synthesized one. Documented in generated docs.

#### [POLE-PREVIEW-1] No pre-placement pole supply/reach preview
- **Severity:** low-medium — poles mostly worked (obs #10, class B), but supply-area reasoning was blind guessing; also reconcile the generator-boundary network split (nets 1 vs 9, silent).
- **Fix direction:** expose supply-area coverage + wire-reach preview in pole cues; pole-network census in remote_view.
- **PARTIAL 2026-07-12 (power build):** pole-network census SHIPPED (`remote_view.get_power_networks()` — per network: anchor pole, production/consumption W, headroom, low_power/no_power counts; live demo green) + `evaluate_pole_placement`/`get_pole_line`/coverage helpers now prototype-backed (were hardcoded dicts; big-pole wire understated 30 vs 32) + ElectricPole accessors registered in docs (DOC-GAP-1). REMAINING: a pre-placement supply/reach preview *cue* (Lua placement-hints tier) is still unbuilt.

### Walking / Pathfinding

#### [ARG-2] walk_to options.entity_ref dead via remote interface
- **Severity:** medium. RemoteInterface.lua:371 dispatches 3 args; walking.lua reads entity_ref as 4th positional — entity-aware walking is unreachable from RCON/agents. Found by check_L4_5.
- **Fix direction:** align the dispatch arity; add an L4.5 case for entity-aware walk.
- **FIXED 2026-07-12 (power build):** walk_to's dispatcher func accepts + forwards entity_ref as 4th positional (named `options.entity_ref` fallback kept); live-verified — pathing goal adjusted to an approach candidate 10 tiles off the pole's literal position. Same file fixed ARG-4 (teleport positional form: single-table dispatch heuristic treated `{x,y}` as named args); blast-radius checked on 6 other remote methods, no regressions.

#### [OBS-3] status='failed' UDP datagrams drop result/failure_type
- **Severity:** medium. `create_action_payload` (udp.lua:99-119) omits `result` for status='failed' — failure_type/goal/message are lost on the wire; Python only sees "failed". The status itself is honest (exactly-once certified), but the agent loses the WHY at the async boundary (ERR-2-adjacent).
- **Fix direction:** include the failure payload in failed datagrams; extend check_L4_5's void-walk case to assert failure_type arrives.

#### [REACH-1] A completed remote/entity-aware walk does not reliably establish interaction range
- **Severity:** high
- **Observed in:** open-ended freeplay / gpt-5.6-terra / codex-terra-factory-debug-20260807-004
- **Evidence:** Run-local BUG-003 records `remote_entity.walk_to()` and `walking.walk_to_entity()` returning or failing while the intended entity remained outside the 10-tile interaction surface. It recurred around turns 6, 7, 9, 85, and 86; at turn 85 a completed `lab.walk_to()` left only a pole locally interactable.
- **Impact:** A coherent batch can partially mutate one site, then abort when its next assumed-local operation is still out of range. The harness-owned snapshot accurately reveals the post-walk failure only after execution ends.
- **Fix direction:** Define and certify the postcondition: a successful entity-targeted walk must end with that entity in the interactable view, or return a structured failure. If long walking remains asynchronous, expose that as an honest in-progress result and require reacquisition before interaction.

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

### Freeplay Policy / Long-Horizon Control

#### [FREEPLAY-1] Proven direct-burner cells create an actor-service treadmill
- **Severity:** high
- **Observed in:** open-ended freeplay / gpt-5.6-terra / codex-terra-factory-debug-20260807-004
- **Evidence:** The stopped factory had 19 burner mining drills and 14 furnaces. Of 115 submitted programs, 75 put items into entity inventories and 49 took items out. One Python program could service many nearby cells, and game speed 8 allowed their buffers to refill during inference. The final inventory still held 2,353 iron plates and 3,083 copper plates.
- **Impact:** Locally reliable servicing kept increasing raw output but consumed the actor's long-horizon attention. The factory did not become a replenishing flow that continued operating after the actor walked away.
- **Fix direction:** Measure generic actor-mediated maintenance debt and actor-absence production. Test whether exposing that semantic changes behavior; do not encode a resource-specific build order from this one run.

#### [FREEPLAY-2] Construction optionality becomes inventory hoarding
- **Severity:** high
- **Observed in:** open-ended freeplay / gpt-5.6-terra / codex-terra-factory-debug-20260807-004
- **Evidence:** At stop time the actor held 72 transport belts, 2 electric mining drills, 2 long-handed inserters, and 1 burner inserter, with zero of those entity classes deployed. The two electric miners had existed since turn 28; belts were crafted on turn 62. No belt or electric-miner placement program was ever submitted.
- **Impact:** Resource scaling and component crafting did not convert into installed logistics or electric capacity. Inventory accumulation falsely preserved “future options” while maintenance obligations continued to grow.
- **Fix direction:** Distinguish installed closed-loop capacity from uncommitted construction inventory in evaluation and durable planning. Validate any transition/spending cue with paired runs before promoting it to generic prompt policy.

#### [FREEPLAY-3] Durable factory architecture stays blank across compactions
- **Severity:** high
- **Observed in:** open-ended freeplay / gpt-5.6-terra / codex-terra-factory-debug-20260807-004
- **Evidence:** `FACTORY_PLAN.md` remained the untouched template throughout 115 turns and four Codex compactions (around turns 13, 73, 88, and 110). In contrast, `PROGRESS.md` changed 64 times and accumulated 134,363 characters of file-change diffs.
- **Impact:** Immediate maintenance history was repeatedly preserved and reread, but no compact durable artifact carried the current factory stage, maintenance debt, transition trigger, or next complete autonomous route through compaction.
- **Fix direction:** Give the model a small, bounded architecture record and a clear update contract at material stage changes. Keep it strategy-neutral: state the chosen route and completion conditions, not a harness-prescribed route.

#### [FREEPLAY-4] State-only programs consume the embodied action budget
- **Severity:** high
- **Observed in:** open-ended freeplay / gpt-5.6-terra / codex-terra-factory-debug-20260807-004
- **Evidence:** 24 of 115 submitted programs were exact status/state-only actions (turns 44–51, 54–57, 59–61, 63–69, and 71–72). They repeatedly inspected the same direct cells while the trusted previous observation and current interactable snapshot were already available on disk.
- **Impact:** Nearly one fifth of the planned 200-turn budget was spent without a game mutation, reinforcing the maintenance loop and delaying architectural work.
- **Fix direction:** Make the cost of a state-only action explicit and detect identical/no-new-evidence inspection loops. Preserve legitimate diagnosis; do not make the observer steer strategy or mutate the run.

### Context / Retrieval

#### [CTX-1] Repeated broad workspace reads bloat and distort long-horizon context
- **Severity:** high
- **Observed in:** open-ended freeplay / gpt-5.6-terra / codex-terra-factory-debug-20260807-004
- **Evidence:** Codex reported 44.47M cumulative tokens (97.0% of input cached), but resident context repeatedly grew to 203–218k and compacted four times. The 138 completed shell commands returned 2,035,955 output characters; 98 commands mentioned the current interactable snapshot, 96 the last observation, 64 `PROGRESS.md`, 46 campaign/reference docs, and 37 `BUGS.md` (overlapping counts). The largest single command output was 59,076 characters.
- **Impact:** The harness-owned snapshot was correctly overwritten, but the model's repeated full reads inserted historical renderings and the growing journal into the thread until compaction. Compaction summaries grew from 20.4k to 47.6k tokens.
- **Fix direction:** Keep atomic snapshot replacement. Add focused readers/projections and teach narrow intent-based queries; bound model-owned journals and preserve only compact architectural state. Add telemetry that separates resident context from cumulative cached reprocessing.

### Evaluation Metrics

#### [SCORE-1] `automation_produced_items` credits actor-serviced production
- **Severity:** high
- **Observed in:** open-ended freeplay / gpt-5.6-terra / codex-terra-factory-debug-20260807-004
- **Evidence:** The final score reported 18,711 `automation_produced_items`, although the dominant mine/furnace system required repeated actor fueling and draining. The sole assembler was hand-fed 104 iron plates, produced exactly 52 gears, and had no replenishing input/output path.
- **Impact:** The metric cannot distinguish machine production from meaningful automation and can reward the exact maintenance-heavy policy the freeplay evaluation intends to outgrow.
- **Fix direction:** Report machine output separately from concurrent, buffered, replenishing flow. Add an actor-absence or maintenance-debt dimension before using this number as a policy signal or model verdict.

### Codex Adapter / Ownership

#### [CODEX-GOAL-1] Codex Goal automatic continuation conflicts with FactoryVerse turn ownership
- **Severity:** medium
- **Observed in:** Codex app-server integration / gpt-5.6-terra / pre-run-004 launch debugging
- **Evidence:** Goal support was added in `62ff0f1`, but Codex began/continued turns outside the supervisor's expected request sequence. `2eee4e1` now launches app-server with `--disable goals`, records `turn_owner=factoryverse-supervisor`, and supplies the immutable objective once in the first `turn/start` input. Run 004's app-server log contains `developerInstructions` and 116 explicit `turn/start` requests, but no `thread/goal/set` call.
- **Impact:** The desired instruction/task separation exists, but task metadata cannot currently use Goal without surrendering the harness's single causal turn owner.
- **Fix direction:** Keep Goals disabled until Codex offers a non-continuing goal-metadata mode or the adapter can prove strict supervisor ownership. Treat this as an ownership/API design issue, not a reason to move stable FactoryVerse instructions back into the user prompt.

### Prompt / Docs

#### [PROMPT-2] Model doesn't know belt/inserter placement patterns — WIDENED 2026-06-11: connection-cue discoverability
- **Severity:** medium → high (now the main residual blocker for engine_unit)
- **Observed in:** engine_unit_throughput / claude-sonnet-4.6 / 2026-03-28; re-observed 2026-06-11 finale attempt
- **Evidence:** Only 2 belt / 4 inserter references in 55 code blocks; planning comments never described belt/inserter layouts. 2026-06-11 finale: agent used the new AFFORD-1 affordances well (find_water, 8× is_buildable) but called `get_connection_positions` ZERO times — hand-placed a steam engine flush against a boiler WATER port (adjacent, fluid-dead) then tore the rig down. The cue layer itself is now certified connection-guaranteeing (L4.6, 18/18) — the gap is purely that nothing teaches the model to reach for it.
- **Fix direction:** ~~system-prompt worked example for the power-chain idiom~~ DONE @ 40353fb — and attempt 3 followed it verbatim, power chain first-pass at T0. ~~REMAINING (PROMPT-2b, from the attempt-3 retro)~~ **PROMPT-2b DONE 2026-07-12 (power build):** (a) worked pattern now closes the fuel loop (coal drill → burner-inserter → boiler via ITEM_DROP cue, ~11-coal buffer note); (b) diagnose-upstream idiom shipped — and it's now ONE call, `remote_view.diagnose_power(name, position)`, with named verdicts; (c) digest-line teaching (per-turn `power: N nets | kW/kW gen/load` line in Task Progress; rising load toward generation = expand signal). Rendered-prompt cost measured: +6.9k chars (~1.7k tokens). Belt/inserter logistics worked-pattern still open.
- **Recurrence 2026-08-07:** gpt-5.6-terra crafted 72 belts on turn 62 and held two electric miners from turn 28, but deployed none. Its first logistics placement attempt was a chest plus burner-inserter query on turn 114; every returned inserter position was blocked. This widens the issue beyond API discoverability: FREEPLAY-1..3 show policy, maintenance-cost, and plan-persistence contributors. No fixed belt layout should be prescribed until those factors are separated experimentally.

---

---

### Infra / Ops

#### [MODLIST-1] Docker auto-restart bypasses prepare_mods — post-dump boots run with Space Age ACTIVE
- **Severity:** low (window is narrow, but the failure is silent and voids run/certification validity when it fires)
- **Observed in:** server_0, boot of 2026-07-11 23:49:58 IST (container self-restart, `restart: unless-stopped`, RestartCount=1) — probed 2026-07-12: `script.active_mods` showed space-age/quality/elevated-rails 2.0.76 active on a lab-grid boot.
- **Evidence:** `--dump-data` rewrites mod-list.json without the DLC entries (documented DATA-1 hazard; rewrite mtime 2026-07-11 13:17). `prepare_mods` re-disables DLC at every `fv server start` — but a docker AUTO-restart re-reads mod-list.json directly, and Factorio enables mods with no mod-list entry by default. DATA-1's "runtime was never contaminated" holds only for fv-CLI-initiated boots.
- **Impact:** This time: none material — the terra-pro run (23:19) ran on the earlier clean boot; the DLC-active boot lasted 23:49→00:16 with no eval. But any eval or live cert on such a boot runs different prototypes than the certified dump scope (L3.3), silently. Same restart also destroyed the terra-pro forensic factory (scenario boots are always fresh) — cell-22 forensics were already complete, but "container self-restart wipes the world" is part of this hazard class.
- **Fix direction:** Make the dump procedure restore mod-list.json as its last step (wrap in CLAUDE.md's dump recipe + `refresh_data_dump`); optionally a boot-time guard — scenario or observe.py asserting `script.active_mods` has exactly the expected 4 mods, loud otherwise. Investigate why the container exited (exit code 0, ~19 min after last RCON activity) if it recurs.

#### [MODSYNC-1] Client/server placement-hint build selection is manual and mismatch-prone
- **Severity:** low (expected operator workflow, but blocks live inspection)
- **Observed in:** codex-terra-factory-debug-20260807-004 client joins / `mod-fv_placement_hints`
- **Evidence:** The client twice rejected the join because its `mod-fv_placement_hints` script differed from the server. The operator intentionally keeps two variants for concurrent agents and requested server-to-client resynchronization each time.
- **Impact:** Live inspection is unavailable until the correct variant is copied, and an unverified copy can silently select the wrong agent's build.
- **Fix direction:** Add an explicit operator command that lists candidate server/client hashes and copies one named server's mod to the client after confirmation. Do not globally auto-sync because the two-version workflow is intentional.

## Archive

*Resolved or stale issues, one line each. Certification evidence: `.fv-output/certification/<date>/<id>/` + FLOOR_CERTIFICATION.md rows.*

- [CELL-1] Agent body and DB vision in DIFFERENT cells (run-killer of the 2026-06-11 field run) — fixed da0cb2f, live-accepted 2026-06-11 (L0.4 both paths @ 108d475 + LIVE-1C eval session @ 1ca2af3). Was NOT allocation: initial_state baked pre-allocation, a 2s "proceeding anyway" lying wait, an unscoped loader replaying destroyed entities, and tier4/RemoteView holding two separate DuckDBs. Full forensics: `.fv-output/certification/2026-06-11/CELL-1/` + git history of this entry.
- [CELL-2] Snapshot dir never cleaned across boots (stale cells' files in every session DB) — fixed da0cb2f + 1ca2af3 (attach guard), live-accepted 2026-06-11: boot clearing exercised twice, phantom-free eval session, future-tick loader guards pinned by unit tests. Residual: client-mode (non-docker) fresh starts still inherit snapshots.

- [SNAP-1] Session DB incoherent in lab-grid (water_tile 0, map_entity [], tick frozen) — fixed 2026-06-11 (8ea7a5c), certified L1.10. Was: scenario `on_chunk_generated` wiped cell_0 barren (DB truthfully reported a broken world — retro's "216 tiles existed" was measured on a different boot) + `snapshot_area` silently skipped snapshotted chunks. Fixes: chunk-scoped restore, re_snapshot on agent creation + honest skip counts, per-file chunk_meta ticks → `chunk_snapshot_meta` table. Staleness-LOUD banner in tool results still TODO (build on chunk_snapshot_meta).
- [SNAP-2] "initial_state race" — decomposed 2026-06-11 (8ea7a5c), live-accepted: no race existed; empty resources = SNAP-1, empty inventory = ParamSpec nil-collapse (`{...}`/table.insert/unpack drop args at nil holes). All 3 create_agent conventions deliver inventory/force/port correctly (SNAP-2-live).
- [SNAP-3] Stale init files survive raise-less destroys — fixed 2026-06-11 (376729c), certified: meta-only rewrite for previously-written-now-empty categories (ChunkTracker files_written). Residual became SNAP-5.
- [SNAP-4] Agent pickup removals invisible to snapshot (20 phantoms/500-op churn) — fixed 2026-06-11 (376729c), L1.6 re-certified green: `entity.mine{inventory, raise_destroyed=true}`; spill-on-full pre-check live-certified 2026-06-11 (LIVE-1A).
- [SNAP-5] Updates-log replay resurrects silently-destroyed entities — fixed-offline 2026-06-11 (4cf7998): loader drops upserts older than chunk init tick (chunk_meta ordering); live re-certified 2026-06-11 (LIVE-1A: 9/9 stale records dropped, init wins, 0 replayed).
- [PROV-2] Config-change upserts squashed label/provenance — found by L1.12 baseline 2026-07-11 (label live-confirmed `'recipe-spine-label'` → None after set_recipe), fixed SAME DAY by the shared reducer (`apply_ops.py`): both writers (loader + sync) route through one apply function with the provenance fold rule — builder-less ops preserve row provenance, present builder is authoritative. Path agreement certified L1.13 (red-first: caught the placed_tick dual-writer drift); correctness certified L1.12 N6 (label survives set_recipe). Was: the config-changed handler re-serializes without builder_info → upsert carried `builder={}` → INSERT OR REPLACE nulled provenance. Residual epoch leg lives in PROV-1 (narrowed, design adjudicated).
- [ROT-1] `rotate()`/`rotate_180()` were client-side lies — found by 2026-07-09 audit, mechanically reproduced + fixed 2026-07-11 (ledger L1.12, exact promised-value equality on engine + DB legs). Was: Lua `rotate_entity` fully implemented with zero Python callers; mixins mutated local state only — and deeper, typed entities never RECEIVED `direction` (BaseEntity `**kwargs` swallowed the constructor arg; pre-fix `rotate()` died on AttributeError). Fix: `EntityOperationsAction.rotate_entity` wrapper + mixin `__init__` claims direction + local state synced from ENGINE-reported direction.
- [FILT-1] Inserter `set_filter` errored end-to-end — found by 2026-07-09 audit, mechanically reproduced + fixed 2026-07-11 (ledger L1.12). Was: DSL passed `inventory_type="inserter_filter"`, Lua INVENTORY_TYPE_MAP had no such key (error before any mutation) — and 2.0 inserter filters are entity-level, not inventory-level anyway. Fix: entity-level route in EntityInterface:set_filter (`use_filters` + `entity.set_filter{name=...}`) + filter contract serialized (`raw_data.inserter.{use_filters, filter_mode, filters[]}`) per the contracts-in-DB boundary rule. Splitter leg remains open as CONF-1.
- [TEST-0] Zero-coverage write primitives — CLOSED for set_inventory_limit, take_inventory_item, take_fuel, take_products 2026-07-11 (first-ever executions, all green, ledger L1.12). Remaining uncovered: remove_ghost (deferred to the intent-provenance family).
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
- [LOAD-1] Offline loader dropped ALL ghost-remove ops (silent no-op: mod emits `ghost_name`, `_apply_ghost_operation` remove/rotated read only `name`; UDP sync path unaffected, which is why L2.5's live check never saw it) — found by the 2026-07-08 label-chain smoke (ghost row survived build-over), fixed same day: key fallback + loud warning on missing name.
- [DB-VISION-1] **Eval-path vision was a boot-time photograph** — found live 2026-07-11 (terra-pro run: execute_duckdb `[]` from map_entity for the agent's own standing factory ALL RUN while water/resource init data answered fine), fixed + certified **ledger L1.15** 2026-07-12. Was TWO layers: tier4 `_load_remote_view` passed `udp_dispatcher=None` — RemoteView treats None as sync-disabled (load() sets `_sync=None`, start() returns early); the "global dispatcher fallback" its comment promised never existed — AND the only dispatcher that did exist bound the client snapshot port 34500 while server_N ops arrive on 34400 (the only socat-forwarded snapshot port; the run's console log shows 34202+34500, never 34400). Fix: tier4 pins the global dispatcher to `get_snapshot_port(instance)` BEFORE RemoteView's bootstrap wait can create it on the wrong default, passes it explicitly, loud fallback if the singleton is already foreign-pinned. Post-fix: marker placement visible in map_entity in 0.0s with zero reload calls. Bycatch worth remembering: LIVE-1C's acceptance green never certified live entity sync — that eval only consumed init-file data (resources), so the sync gap sailed through it; and L1.13's SyncService certification says nothing about tier4 WIRING the service (component-certified ≠ composed-certified).
- [GLOBAL-NET-1] **Observability mutated physics**: fv_snapshot's power-stats reader (`Power.lua` nth_tick(300)) called `surface.create_global_electric_network()` whenever stats were missing — every snapshot-enabled boot got a global electric network within ~300 ticks, which powers ALL electric entities poleless (Fulgora mechanic). Found live 2026-07-11 (terra-pro run: agent's 18 poles formed 4 dead islands while everything ran off the invisible global net). Fixed 2026-07-12 (guard: never create, empty stats when absent), certified **ledger L1.14** incl. the executed poleless-powering semantics A/B (no_power → create → working/shared-net-id → destroy → no_power; holds across snapshot windows both directions). Fallout: attempt-3 network forensics + every pole-affordance behavior observed on snapshot-enabled servers before 2026-07-12 are contaminated (retro annotated); ISLAND-1/POLE-PREVIEW-1 evidence predating the fix needs re-observation on a clean boot; global power stats now honestly empty on normal surfaces — per-network stats is an open design item. NET-LEGIBILITY-1 (contradictory net-id surfaces at stop-time) folds into this + STATUS-1.
- [DATA-1] 2.0.76 dump shifted prototype scope (89/106/99 vs certified 73/113/85) — resolved 2026-06-11, L3.2/L3.3 green. Was: `--dump-data` force-loads DLC ignoring mod-list (and persists re-enabled flags back!); 100% of scope drift attributed to Space Age recategorization, 0 to engine/filters. Runtime was never contaminated (prepare_mods disables DLC at every server start; verified via script.active_mods). Re-dump with DLC dirs removed in-container → 73/113/85 restored, 458/458 hydration exact on 2.0.76. Dead `DLC_SPACE_AGE` env removed from compose generator.
- [CODEX-TURN-1] Codex Goal continuation and weak turn correlation made the first supervised launch appear idle — fixed by `3bfc76f` (strict `turn/started`/completion identity, fail-closed) + `2eee4e1` (Goals disabled; FactoryVerse is sole turn owner). Run 004 then completed 115 explicit supervised turns. Goal metadata without continuation remains open as CODEX-GOAL-1.

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
| 2026-07-11 | engine_unit_throughput | openai/gpt-5.6-terra-pro (Prime Intellect) | STOPPED T1/iter15 (0 produced, operator call) | **GLOBAL-NET-1** (run headline: all power ran on the reader-created global net; FIXED+L1.14 2026-07-12) + PROPOSED in docs/runs/: DB-VISION-1, ERR-6, ARG-3, ERR-5, ERR-1-residual, EVAL-PORT-1; expressed: PROMPT-2b (2nd model family fails fuel loop), REASON-1, POLE-PREVIEW-1/ISLAND-1, STATUS-1. Frontier verdict: clears affordance layer 4.6× cheaper than Sonnet, same strategy ceiling. Full forensics: docs/runs/2026-07-11-engine-unit-terra-pro.md | ~2.67M prompt (71% cached) / 39k completion |
| 2026-08-07 | open-ended freeplay | openai/gpt-5.6-terra | STOPPED T115/200 (operator satisfied; final checkpoint tick 1,678,482) | FREEPLAY-1..4, CTX-1, SCORE-1, PROMPT-2 recurrence; run-local walking/snapshot/tree/placement defects recorded in `BUGS.md`. Strong resource scaling, but zero deployed belts/inserters/electric miners. Full audit: docs/retros/2026-08-07-codex-terra-freeplay-004-context-and-policy-audit.md | 44.47M cumulative total / 97.0% input cached / 279k output |
