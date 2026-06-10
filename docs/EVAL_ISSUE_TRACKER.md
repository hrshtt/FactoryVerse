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

#### [ERR-2] WalkingUnreachableError gives no spatial context
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
