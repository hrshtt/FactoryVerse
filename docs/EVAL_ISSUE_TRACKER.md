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

#### [LIVE-1] Consolidated live-acceptance backlog for the next deploy battery
- **Severity:** high (gates several archived fixes' final certification)
- **Context:** several fixes are verified offline and deploy at the next server restart; each has exact probes defined. Run them in ONE battery, then archive the corresponding lines for good.
- **Probes:**
  1. **ERR-4** (crafting/inventory structured errors): the 6 probes in `.fv-output/certification/2026-06-11/ERR-1-craft-inv/` — unknown recipe / locked recipe ("NOT unlocked", not ingredients) / missing ingredients have-need / full-chest fail-before-mutate / invalid inventory-type lists six names / partial insert success with `count<requested_count`.
  2. **SNAP-4 residual** (spill-on-full): pickup with full agent inventory → structured error BEFORE mutation, entity still in world+DB, nothing on ground.
  3. **SNAP-5 / L2.2 DB layer** (loader tick-ordering): re-snapshot a chunk after entity changes → DB reflects init, stale older-tick upserts not replayed.
  4. **L2.2/L2.3 re-cert** (sensor fixes): re-run the 4-layer rig diff — boiler/generator fluidboxes populated with capacity+connections, poles report copper neighbours + supply area, machines report electric_network_id; verify `real_connections` vs `.connections` shape on wire connectors live.
  5. **OBS-2** (prompt caching): next eval run shows `cache_read_input_tokens > 0`.
  6. **PROMPT-3** (cell bounds): initial_state.md renders the Working Area section in a real session.
  7. **AFFORD-1**: `find_water()` + `is_buildable()` exercised live.
  8. **L0.3**: save → `fv server start --save` → census diff (affordances built, check unrun).
  9. **Drafted harnesses**: execute `check_L2_4.py`, `check_L2_5.py`, `check_L4_5.py` (open-questions in their headers).

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
- **Status note 2026-06-11:** the L2.2 sensor batch rebuilt fluid inspection (capacity/connections now flow); whether the Pipe Python type now exposes `.status`/`.direction` is UNVERIFIED — fold a probe into the L2.2 re-cert. Statuses still arrive as raw ints at the payload tier (L2.3 finding; symbolic names only in `__repr__`).
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
- [SNAP-4] Agent pickup removals invisible to snapshot (20 phantoms/500-op churn) — fixed 2026-06-11 (376729c), L1.6 re-certified green: `entity.mine{inventory, raise_destroyed=true}`; spill-on-full pre-check pending live probe (LIVE-1 #2).
- [SNAP-5] Updates-log replay resurrects silently-destroyed entities — fixed-offline 2026-06-11 (4cf7998): loader drops upserts older than chunk init tick (chunk_meta ordering); live re-cert in LIVE-1 #3.
- [API-1] "No entity pickup method" — reclassified doc gap, fixed 2026-06-10, pickup certified working (L4.3: removal + inventory credit). Was: `entity_ops.pickup_entity` existed but was unregistered in the doc registry → invisible to agents.
- [ERR-1] Placement errors were raw Lua tracebacks — fixed 2026-06-10, certified L4.2 (RAW 0/4): structured causes (collision lists, out-of-reach + walk-closer).
- [ERR-2] WalkingUnreachableError had no spatial context — fixed 2026-06-11 (d7fd560): message carries agent/target positions, distance, bearing, out-of-bounds hint; attrs on the exception.
- [ERR-3] placement_hints wrappers swallowed exceptions as [] — fixed 2026-06-11 (75379b5): ConnectionQueryError with "query failure ≠ no valid positions".
- [ERR-4] Crafting/inventory raw throws, locked-vs-missing indistinguishable, partial-insert-then-throw — fixed-offline 2026-06-11 (9b07b23): L4.2-contract errors (locked recipe names its tech, missing ingredients have/need, partial insert = honest success + rollback, six inventory-type names documented). Live probes in LIVE-1 #1.
- [PLACE-1] get_connection_positions returned [] for boiler→steam-engine — fixed 2026-06-10/11, certified L4.4 twice (open-ground pass, field failure, per-direction staging fix, east-case green).
- [PROMPT-1] factoriopedia promised but not in namespace — resolved by removal + guard: docs no longer promise it (L5.1 certified 0 phantom names 2026-06-11; negative control catches re-introduction). The module itself is parked on token_compression.
- [PROMPT-3] Cell bounds undocumented — fixed 2026-06-11 (7012629): initial_state "Your Working Area" section with hard bounds + don't-probe-beyond guidance. Live render check in LIVE-1 #6.
- [AFFORD-1] Placement-as-sonar (no terrain affordance) — fixed 2026-06-11 (f6fd8b7): `remote_view.find_water()` + `placement_hints.is_buildable()`, doc-registered. Live exercise in LIVE-1 #7.
- [OBS-2] Task Progress ×163 + 30k uncached prefix (~10M prompt tokens/17 turns) — fixed 2026-06-11 (675ac71): ProgressDeduper + anthropic cache_control, −49.7% on trajectory replay. Cache-hit observation in LIVE-1 #5.
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
