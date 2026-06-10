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

**Reading this document quickly:** The Dashboard at the top gives counts. Skim category headers for what's broken. Only read individual issues if you're about to fix something in that category.

---

## Dashboard

| Category | Critical | High | Medium | Low | Total |
|----------|----------|------|--------|-----|-------|
| API Gaps (missing functionality) | 1 | 1 | 0 | 0 | 2 |
| Error Quality (opaque/misleading) | 1 | 1 | 0 | 0 | 2 |
| Type System (incomplete types) | 0 | 1 | 1 | 0 | 2 |
| Placement/Spatial (hints, connections) | 1 | 1 | 0 | 0 | 2 |
| Prompt/Docs (model doesn't know about API) | 0 | 1 | 1 | 0 | 2 |
| Agent Loop (orchestrator/infra bugs) | 0 | 1 | 0 | 0 | 1 |
| **Total** | **3** | **6** | **2** | **0** | **11** |

*Last updated: 2026-03-28 — engine_unit_throughput + production_science_pack_throughput runs*

---

## Active Issues

### Snapshot / Observability (NEW category, from 2026-06-10 retro — docs/retros/2026-06-10-engine-unit-retro.md)

#### [SNAP-1] Session DB incoherent in lab-grid runs — FIXED 2026-06-11 (certified L1.10)
- **Severity:** critical — THE run-killer of 2026-06-10_23-35-34
- **Evidence:** agent queried water_tile >=8 times -> 0 rows (216 water tiles existed); map_entity [] despite placed entities; snapshot tick frozen at 660 for ~15 turns; resource_tile flapped full->empty->full. Agent rationally concluded "no water = steam impossible" and pivoted to solar.
- **Impact:** installed a false world-model; every downstream decision poisoned. Worse than a missing affordance.
- **Root cause (2026-06-11, NOT the loader):** (a) lab-grid `on_chunk_generated` wiped late-engine-generated chunks to bare dirt — cell_0 (handed to the first session by `find_empty_cell`) was genuinely barren; the DB truthfully reported a broken world. (b) `snapshot_area` silently skipped already-snapshotted chunks → init files + tick frozen after first pass. **Important retro errata: the "ground truth: 216 water tiles" in the retro was measured on a different boot/cell — during the field run the water genuinely did not exist.**
- **Fixes (certified L1.10 post-fix, cell_0):** SNAP-1a chunk-scoped deterministic restore in `on_chunk_generated`; SNAP-1b `re_snapshot_area` on agent creation + honest `chunks_skipped`/warning from `snapshot_area`; SNAP-1c per-file `chunk_meta` tick line → `chunk_snapshot_meta` DB table (staleness now disk-falsifiable and queryable — the "staleness LOUD in tool results" banner can now be built on it, still TODO under OBS).
- **Residual → SNAP-3.**

#### [SNAP-4] Agent pickup_entity removals invisible to snapshot pipeline — FIXED 2026-06-11 (L1.6 re-certified green)
- **Fix certified:** `entity.mine{inventory, raise_destroyed=true}` — minimal repro green (remove op in updates file, no phantom row, items credited), full 500-op churn re-run exact parity. Residual found by the full-inventory probe: engine SPILLS products instead of failing the mine (silent success, item on ground) → `can_insert` pre-check added before mutating (live probe pending next deploy).

#### [SNAP-5] Append-only updates log can resurrect raised-then-silently-destroyed entities on fresh load
- **Severity:** low-medium (edge: entity placed WITH raised events, then destroyed WITHOUT events, then a fresh-load replay applies the stale upsert). Found by SNAP-3 acceptance probe. SNAP-3's meta-only init rewrite does not cover the updates log (never truncated). Fix direction: on re_snapshot of a chunk, also emit a tombstone/truncation marker for that chunk into the updates stream, or have the loader prefer init-file state over older-than-init upserts (init chunk_meta tick now exists to order them).

#### [SNAP-4-original] (history)
- **Severity:** critical for any run where the agent relocates/cleans up entities (i.e. all of them — the field run used pickup dozens of times). Found by the L1.6 churn battery: `entity_ops.lua` uses `character.mine_entity()`, which on a non-player character raises NO event; fv_snapshot's removal handlers cover only player/robot-mined, died, script_raised_destroy → every agent pickup leaves a permanent phantom `map_entity` row, and rebuild can't recover because the update files never contain the remove. 20 phantoms per 500-op churn. Minimal repro: agent place+pickup one chest → world 0 entities, files have 2 upserts and no remove.
- **Fix direction:** make the removal event-visible — e.g. `entity.mine{inventory=..., raise_destroyed=true}` instead of `character.mine_entity()` (script_raised_destroy already syncs correctly per the same battery), or raise a custom picked-up event fv_snapshot subscribes to.

#### [SNAP-3] Stale init files survive raise-less script destroys — FIXED 2026-06-11 (certified)
- **Severity:** medium. Found by L1.10 post-fix probe: the serializer skips empty categories (Map.lua write-queue guards), so re-snapshotting a chunk whose entities were all removed WITHOUT raised events (script `destroy()` — e.g. cleanup/reset paths) leaves the old entities-init.jsonl on disk → phantom entities in a fresh load. Event-raised removals reconcile correctly. SNAP-1c makes it detectable (orphan's chunk_meta tick lags its siblings).
- **Fix certified:** ChunkTracker `files_written` (grow-only) + meta-only rewrite for previously-written-now-empty categories. Acceptance: 2 raise-less-placed chests → init 3 lines; raw destroy both → re-snapshot → init META-ONLY, tick advanced, fresh load 0 phantoms. Residual → SNAP-5 (updates-log replay).

#### [SNAP-2] initial_state.md generated before snapshot ready (race) — DECOMPOSED + FIXED 2026-06-11 (live-accepted)
- **Live acceptance (SNAP-2-live, @8ea7a5c):** all three create_agent calling conventions deliver inventory/force/udp_port to the correct slots on the deployed mod (named-table, sparse-named, leading-nil positional). Evidence: `.fv-output/certification/2026-06-11/SNAP-2-live/`.
- **Severity:** high. Evidence: showed empty inventory + empty resource queries at session start; real inventory only visible via in-run query at T1.
- **Finding (2026-06-11):** there is no race. Tier4's `_wait_for_snapshot_bootstrap` raises `TimeoutError` loudly rather than proceeding (tier4_runtime.py:868). The two symptoms have separate causes: (a) empty resource queries = SNAP-1 (barren cell_0 + frozen snapshot pipeline); (b) **empty inventory = ParamSpec nil-collapse**: `create_agent_in_cell` calls `create_agent(nil, false, force, starting_inventory)` positionally, and `normalize_varargs` used `{...}`+`table.insert`+plain `unpack`, all of which drop/shift args at nil holes — the inventory never reached the mod. Fixed via `table.pack`/explicit-index/`unpack(t,1,n)` in ParamSpec.lua + Agents.lua (offline-verified both calling conventions; live cert pending next mod deploy).

#### [ERR-3] Silent exception swallowing in placement_hints Python wrapper — FIXED 2026-06-11
- **Severity:** high. `_get_fluid_pipe_positions` except->return [] made a solver bug indistinguishable from "no candidates" for 3 calls. Same family as vacuous tests: silence reads as data. Remove blanket except; propagate cause.
- **Fix:** all 4 connection-solver wrappers (`item_drop`/`fluid_pipe`/`electric_wire`/`inserter_placement`) now raise `ConnectionQueryError` (carries query, source, target, cause; message explicitly tells the agent "query failure ≠ no valid positions"). Unimplemented connection types raise `NotImplementedError` pointing at the right method instead of returning []. Successful-but-empty stays `[]`. Offline-verified; live exercise rides with the L2.2 battery.

#### [PROMPT-3] Cell bounds undocumented — FIXED 2026-06-11 (live render check pending)
- **Severity:** medium. Agent probed x=-5, y=-100, (200,70); WalkingUnreachableError gave no boundary context (couples with ERR-2).
- **Fix:** initial_state.md now has a "Your Working Area (IMPORTANT: hard bounds)" section: derives the agent's cell from position + `scenario.config`, prints the buildable bounds, and states explicitly that outside tiles are out-of-map/unwalkable/unbuildable — "do not spend actions probing beyond them". No-op for non-cell scenarios. ERR-2's enriched WalkingUnreachableError covers the in-run half. Verified with a fake-runtime exec; live render rides the next session.

#### [AFFORD-1] No terrain affordance -> placement-as-sonar — FIXED 2026-06-11 (Python side; live exercise pending)
- **Severity:** medium. Agent used place/pickup of poles as a tile scanner (hundreds of RCON calls, ~70 pole debris via position-snap lookup misses). Provide find_water()/is_buildable(area).
- **Fix:** `remote_view.find_water(near, radius, limit)` — water tiles from the certified water_tile table, distance-sorted, with a doc'd staleness check (chunk_snapshot_meta) before concluding "no water". `placement_hints.is_buildable(left_top, right_bottom)` — batch non-mutating engine validation (manual build-check) over the area, returns all_buildable/counts/blocked_positions, max 1600 tiles/call. Both registered in the doc registry (the API-1 lesson) + validators mapping; L5.1 + drift suite green. Live exercise rides the L2.2 battery.

#### [OBS-2] Token waste: Task Progress block repeated verbatim x163; 30k static prefix per call — FIXED 2026-06-11 (live cache-hit check pending)
- **Severity:** medium (cost). ~10.08M prompt tokens in 17 turns. Dedupe progress block (emit on change), prompt-cache the static prefix.
- **Measured (trajectory replay):** 163 emissions / only 35 distinct contents / 128 verbatim repeats; ~27.8k-token byte-stable prefix re-sent on all 163 calls ≈ 45% of all prompt tokens.
- **Fix:** `ProgressDeduper` (full block on change + refresh every 10 repeats, one-line pointer otherwise; honesty invariant: changed content never collapsed; console/chat.md stay faithful) wired into orchestrator. Anthropic `cache_control` on the system prefix in `OpenAICompatibleClient`, gated to anthropic/* models via the Prime Intellect factory, logged retry-without fallback if the gateway rejects. Replay vs measured run: −5.4% dedupe, −40.3% caching, **−49.7% combined**. 15 new unit tests on real blocks from the run. Live check pending: `cache_read_input_tokens > 0` on the next eval run. Evidence: `.fv-output/certification/2026-06-11/OBS-2/`.

---

### API Gaps

#### [API-1] No entity pickup/removal method — RECLASSIFIED: documentation gap (fixed 2026-06-10)
- **Severity:** critical → resolved pending live cert
- **Observed in:** engine_unit_throughput / claude-sonnet-4.6 / 2026-03-28
- **Evidence:** Agent tried `entity_ops.pick_up()`, `entity_ops.remove()`, `steam_engine.remove()` — all raised `AttributeError`. Agent needed to undo a misplaced steam engine and pipes to rebuild, had no way to do so.
- **Root cause (found via FLOOR_CERTIFICATION L5.5, 2026-06-10):** the affordance EXISTED the whole time — `entity_ops.pickup_entity(entity_name, position)` → `EntityPickedUp` (`entity_operations.py:407`), bound in the agent namespace. But `EntityOperationsAction` was never registered in the doc registry, so the method was absent from the generated api_reference and the agent's system prompt. The agent guessed plausible names because the real one was invisible.
- **Fix applied:** EntityOperationsAction (all 7 members), MiningAction, PlacementAction registered with examples; system prompts now carry them (generated live from the registry).
- **Remaining:** live certification that `pickup_entity` actually works (place → pickup → inventory credited), and a re-run of engine_unit_throughput to confirm agents recover from misplacements.

#### [API-2] No way to check why placement failed before attempting it — RECLASSIFIED: affordance exists, reason is a stub (L4.1, 2026-06-10)
- **Severity:** high → medium (polish + visibility)
- **Observed in:** engine_unit_throughput / claude-sonnet-4.6 / 2026-03-28
- **Evidence:** Agent called `.place()` 16 times, many failed with opaque errors. No pre-check like `can_place_at(entity_name, position, direction)` that returns a reason.
- **Root cause (L4.1 certification):** the pre-check EXISTS and is agent-reachable — `placement_hints` is in the DSL namespace; `validate_placement` works but returns stub `reason:"placement_blocked"` (area.lua:50 TODO), while `get_placement_cue` already returns `colliding_entities` + `reason:"collision"` + footprint. The gap is the stub reason string and prompt visibility, not a missing affordance. Placement honesty itself certified: 22-cell sweep, prediction ⇔ outcome 0 disagreements.
- **Fix direction:** replace the area.lua stub reason with `get_placement_cue`-grade detail; ensure docs/prompt surface `validate_placement`/`get_placement_cue` (same doc-gap class as API-1).

---

### Error Quality

#### [ERR-1] Placement errors are raw Lua stack traces — FIXED 2026-06-10 (certified L4.2)
- **Severity:** critical
- **Observed in:** engine_unit_throughput / claude-sonnet-4.6 / 2026-03-28
- **Evidence:** Failed placements return: `RuntimeError: RCON command failed: Error when running interface function agent_1.place_entity: __fv_embodied_agent__/agent_actions/placement.lua:162: Agent: Cannot place entity at position 110, 68 stack traceback: [C]: in function 'error' ...`
- **Impact:** Agent sees a wall of Lua internals. The actual reason (collision? wrong terrain? too far?) is not stated. Agent can't diagnose and retries blindly. Spent 6+ attempts placing at invalid positions.
- **Fix direction:** Catch placement failures in Lua and return structured error: `"Cannot place boiler at (110,68): tile occupied by pipe at (110,68)"` or `"Cannot place offshore-pump at (110,70): requires water tile"`. Strip stack traces from agent-facing output.
- **Floor-certified (L4.2, 2026-06-10):** confirmed 4/4 — collision errors state NO cause (placement.lua:162 TODO). The structured reason already exists in `get_placement_cue` (`colliding_entities`, `reason`); the fix is wiring it into `place_entity`'s error payload. Acceptance test: `check_L4_placement.py` L4.2 section.

#### [ERR-4] Crafting + inventory paths raw-throw / indistinguishable causes — FIXED-OFFLINE 2026-06-11 (live check pending; deploys at next scheduled restart)
- **Source:** retro failure modes #6 and #7 (docs/retros/2026-06-10-engine-unit-retro.md): `crafting.craft` raised raw Lua errors and locked-recipe vs missing-ingredients were indistinguishable (agent burned turns retrying a trigger-tech-locked recipe); `put_inventory_item` could partial-insert-then-throw and the valid inventory-type names were undocumented.
- **Fix (ERR-1/L4.2 contract — agent-reachable failures return `{success=false, error=<cause>}`, guidance packed into the error string):**
  - `crafting.lua craft_enqueue` now distinguishes: (a) unknown recipe (suggests `get_recipes()`), (b) locked recipe — names the unlocking technology via a failure-path-only scan of `force.technologies`, or says "locked — research required" for trigger techs, and states "this is not an ingredient problem"; (c) missing ingredients enumerated as `name (have N, need M)`; (d) invalid count / queue-full (`begin_crafting`→0) with `craft_dequeue()` guidance; plus non-hand-craftable category → machine guidance, and partial-queue honesty (`count_queued < count_requested` + message).
  - `entity_ops.lua put_inventory_item`: invalid inventory-type names rejected BEFORE any lookup with the full valid list (`"auto"/"fuel"/"input"/"chest"/"output"/"modules"` + raw defines number); zero-capacity (`can_insert` false) fails BEFORE mutating; partial insert returns SUCCESS with `count`/`inserted`/`requested_count` + message (remainder rolled back to agent inventory) instead of throwing after mutating; insufficient items report have/need; out-of-reach gets positions + "walk closer"; entity-not-found and no-such-inventory (lists inventories the entity has) are structured. `get_inventory_item` unknown-name error now lists valid names too.
  - Python: `crafting.py`/`entity_operations.py` verified free of except→default swallowing (ERR-3 standard); docstrings + doc-registry error_cases (`utils/docs/reference/actions.py`) + RemoteInterface paramspec docs now state the failure modes and the inventory-type names. Untouched per certification boundaries: `placement.lua` (L4.2), `pickup_entity` (SNAP-4).
- **Verification (offline):** `luac -p` clean on all 3 touched Lua files; 31/31 stub-harness branch probes pass; `tests/unit` 75 passed; L5.1 PASS. Evidence: `.fv-output/certification/2026-06-11/ERR-1-craft-inv/`.
- **Live acceptance probes (for the next battery, after mod deploy):** (1) `craft_enqueue('no-such-recipe',1)` → RuntimeError "Unknown recipe"; (2) `craft_enqueue(<locked recipe, e.g. pipe pre-trigger>,1)` → "NOT unlocked … research"; (3) `craft_enqueue('iron-gear-wheel',1)` with empty inventory → "missing ingredients … iron-plate (have 0, need 2)"; (4) `put_inventory_item` into a full chest → fails BEFORE mutation with "cannot accept ANY", agent count unchanged; (5) `put_inventory_item(..., inventory_type='cargo')` → error listing the six valid names; (6) put 10 coal into a chest with 4 slots of room-equivalent → success, `count<requested_count`, message present, agent inventory holds remainder.
- **Fix:** the error now carries `agent_position`/`target_position` attrs and the message appends "[you are at (x,y); target (x,y) is N tiles to the south-east. If this is far beyond your working area, the target may be outside your reachable map bounds...]". Agent position is read best-effort at raise time (never masks the original error). Couples with PROMPT-3 (cell bounds in prompt) for the full treatment. Original entry below.
- **Severity:** high
- **Observed in:** engine_unit_throughput / claude-sonnet-4.6 / 2026-03-28
- **Evidence:** Agent got `WalkingUnreachableError: Walking failed` three times in a row. No information about what's blocking the path or where the agent is relative to the target.
- **Impact:** Agent was physically trapped by its own pipe/entity placements but couldn't diagnose this. Spent 3 steps blindly trying to walk before attempting to remove nearby entities.
- **Fix direction:** Include current position, target position, and ideally the blocking entity/tile: `"Walking failed: no path from (107.8, 69.0) to (105, 65) — path blocked near (107, 68)"`.

---

### Type System

#### [TYPE-1] Pipe entity missing .status and .direction attributes
- **Severity:** high
- **Observed in:** engine_unit_throughput / claude-sonnet-4.6 / 2026-03-28
- **Evidence:** Agent placed pipes, then tried to inspect them with `pipe.status` and `pipe.direction` — both raised `AttributeError`. Agent was trying to verify placement worked.
- **Impact:** Agent can't verify pipe placement succeeded or understand pipe orientation. Falls back to guessing.
- **Fix direction:** Add `.status` and `.direction` (or `.orientation`) to the Pipe type in the factory object system. Most entity types already have these.

#### [TYPE-2] ResourceOrePatch missing .amount attribute
- **Severity:** medium
- **Observed in:** engine_unit_throughput / claude-sonnet-4.6 / 2026-03-28
- **Evidence:** Agent tried `ore_patch.amount` — raised `AttributeError: 'ResourceOrePatch' object has no attribute 'amount'`.
- **Impact:** Minor — agent worked around it. But the prompt/docs apparently reference `.amount` on ore patches, creating a doc/code mismatch.
- **Fix direction:** Check if property is `.total` or `.amount` and align docs with implementation.

---

### Placement / Spatial

#### [PLACE-1] placement_hints returns empty for steam engine connections — FIXED 2026-06-10 (certified L4.4: candidate placed, fluidbox_connections=1)
- **Severity:** critical
- **Observed in:** engine_unit_throughput / claude-sonnet-4.6 / 2026-03-28
- **Evidence:** `placement_hints.get_connection_positions(boiler, "steam-engine", ConnectionType.FLUID_PIPE)` returned `[]`. Agent needed to know where to place a steam engine relative to a boiler and got no help.
- **Impact:** This is the single biggest cause of failure in this run. Without valid connection hints, the agent spent 20+ steps trial-and-error placing and re-placing the steam engine. The entire power setup (pump→boiler→steam engine) which should be a 3-step operation became a 30-step ordeal that consumed the full eval budget.
- **Fix direction:** Ensure `get_connection_positions` works for all fluid-connected entity pairs: pump↔pipe, pipe↔boiler, boiler↔steam-engine. These are the most common connections in early-game Factorio.
- **Root cause found (L4.4, 2026-06-10, with controls):** boiler→pipe returns 5 candidates, boiler→steam-engine returns 0 — the solver (`fv_placement_hints` connections/init.lua:205-234) tries the TARGET's center at the connection point ±1 tile and never offsets by the target's own fluidbox geometry, so any multi-tile target structurally gets zero candidates. Fix the solver's target-side offset; acceptance: `check_L4_placement.py` L4.4b flips + non-empty candidates must place successfully. Half-good news: drill `drop_position` round-trips into `place()` honestly (engine snap), and `get_item_drop_connections` works.

#### [PLACE-2] Agent gets physically trapped by placed entities
- **Severity:** high
- **Observed in:** engine_unit_throughput / claude-sonnet-4.6 / 2026-03-28
- **Evidence:** After placing pipes and a boiler, the agent's walking path was blocked in all directions. `WalkingUnreachableError` on 3 consecutive attempts to different positions.
- **Impact:** Agent became permanently stuck. Even if it could fix the layout, it couldn't reach anything to do so.
- **Fix direction:** Two possible approaches: (1) Allow agent to walk through/over its own placed entities (Factorio players can walk over pipes/belts). (2) Provide a `teleport_to_entity()` for reaching nearby owned entities. (3) At minimum, make pickup work from current position for adjacent entities so the agent can free itself.

---

### Prompt / Docs

#### [PROMPT-1] factoriopedia not available in execution namespace
- **Severity:** high
- **Observed in:** engine_unit_throughput / claude-sonnet-4.6 / 2026-03-28
- **Evidence:** Agent tried `factoriopedia("engine-unit")` and `factoriopedia("boiler", attach_placement_hints=True)` — both raised `NameError: name 'factoriopedia' is not defined`. Tried 4 times across the run.
- **Impact:** Agent couldn't look up recipe details, entity dimensions, or connection info mid-run. Had to guess entity sizes and fluid connection points.
- **Fix direction:** Either inject `factoriopedia` into the DSL execution namespace, or remove it from the system prompt/docs so the model doesn't try to call it. Current state is the worst of both worlds — model knows the name but can't use it.

#### [PROMPT-2] Model doesn't know belt/inserter placement patterns
- **Severity:** medium
- **Observed in:** engine_unit_throughput / claude-sonnet-4.6 / 2026-03-28
- **Evidence:** Only 2 belt references and 4 inserter references out of 55 code blocks. Agent never got past power setup to attempt logistics, but even in its planning comments it didn't describe belt/inserter layouts.
- **Impact:** Hard to fully assess since the agent failed earlier. But suggests the prompt doesn't give enough examples of how to connect entities with belts+inserters for item transport. The iron_plate run succeeded because burner drills drop directly into adjacent furnaces — no logistics needed.
- **Fix direction:** Review whether the system prompt includes examples of belt/inserter patterns for connecting drill→furnace→assembler chains. If not, add them.

---

### Agent Loop

#### [LOOP-1] Assistant messages with tool_calls missing content field
- **Severity:** high
- **Observed in:** production_science_pack_throughput / claude-sonnet-4.6 / 2026-03-28
- **Evidence:** 422 API error: `{'detail': [{'type': 'missing', 'loc': ['body', 'messages', 25, 'content'], 'msg': 'Field required'}]}`. The assistant message had `tool_calls` but no `content` field.
- **Impact:** Crashed the entire eval run 8 calls in. Total loss.
- **Fix direction:** Fixed — `ChatMessage.to_dict()` now sends `content: ""` when tool_calls present but content is None. **(FIXED 2026-03-28)**

---

## Archive

*Resolved or stale issues, one line each.*

- [LOOP-1] Assistant messages missing content field — fixed 2026-03-28. Was: `to_dict()` omitted `content` when None, causing 422 on APIs that require it.

---

## Run Log

Summary of eval runs and which issues were observed, for tracking recurrence.

| Date | Task | Model | Result | Issues Hit | Cost |
|------|------|-------|--------|------------|------|
| 2026-03-28 | iron_plate_throughput | anthropic/claude-sonnet-4.6 | PASS (54.5/60s) | None | $1.41 |
| 2026-03-28 | production_science_pack_throughput | anthropic/claude-sonnet-4.6 | FAIL (0 produced) | LOOP-1 | $0.67 |
| 2026-03-28 | engine_unit_throughput | anthropic/claude-sonnet-4.6 | FAIL (0 produced) | API-1, API-2, ERR-1, ERR-2, TYPE-1, TYPE-2, PLACE-1, PLACE-2, PROMPT-1, PROMPT-2 | ~$2-3 |
