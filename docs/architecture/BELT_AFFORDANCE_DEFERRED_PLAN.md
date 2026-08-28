# Belt affordance — deferred refactor plan

**Status: DEFERRED.** Grounded in code reads; nothing here has been executed. Principles live in `docs/CONSTITUTION.md`.

**Superseded by `TRANSPORT_CONNECTIVITY_PLAN.md`** (its §12 says what is absorbed and what is carried forward); kept for its teaching section and its baseline gate. Not amended further.

**The motivating observation:** across eval runs, models do not use belts to connect resources. They do use power — which is taught, cued, and free of phantoms.

## Summary

Belts are the first affordance where three distinct gap categories intersect, which is plausibly why belts specifically go unused. The plan: add one bounded bulk verb, `place_line`; delete the phantom belt surface rather than implement it; and teach belts with a worked pattern and one invariant.

The three categories are recorded here because they have confirmed members beyond belts. The siblings are listed as known members, not as rediscoveries waiting to happen.

## 1. Three gaps, three categories

Direct belt placement already works and is **not** ghost-coupled. `place("transport-belt", pos, direction)` is inventory-backed, reach-checked against the agent's live position, engine-validated, and returns structured errors. What is missing sits above the primitive.

### Category 1 — Expectation gap: the mechanism works, the model was never taught

| Member | Evidence |
|---|---|
| **Belts** | The system prompt mentions belts only as aspiration — *"belts connect production"*. No worked belt pattern, while the power chain has one. No direction or flow semantics. No line verb taught |
| Pipes and underground transport | Zero guidance beyond fluid-connection cues; the underground-segment read is never mentioned |
| Ghost workflow | One bare bullet, with no when, why or how |

This is the inverse face of the mirage class. There, the model claims knowledge it lacks. Here, the harness withholds expectation for capability it has. The teaching surface is uneven in a way that correlates with observed use — power taught and used, belts untaught and unused. Correlation, not established causation; the baseline run tests it.

**This category is first-class, not a prompt chore, and it has a confirmed sibling outside belts.** The base-wide status read has exactly the same shape: an agent has to know the *shape* of the problems its base can have before checking for them is a sensible act. A capability nobody expects is a capability nobody uses, whatever surface it sits on.

### Category 2 — Phantom surface: advertised capability that is dead or lying

Worse than absent. The model burns turns discovering the lie, and then stops trusting the surface.

| Member | Evidence |
|---|---|
| **`ConnectionType.BELT_FLOW`** | An enum member with no implementation. It passes connection validation silently — there is no branch for it — and then the method that consumes it raises `NotImplementedError`. No Lua counterpart exists |
| `ConnectionType.INSERTER_REACH` | Accepted by the enum, rejected by the method that takes the enum, which redirects to a different call |
| Stale inserter names | The inserter list names variants absent from the 2.0 scoped prototype set, and the injected documentation recommends one of them for throughput. Shallow-verified — confirm against the live prototype set before fixing |

### Category 3 — Missing bounded bulk verb: sound primitives, no orchestrated middle

The only compositions on offer are hand-looping primitives per tile, or heavyweight ceremony. Mining's capped verb is currently the only one of the right shape: bounded so async completion uncertainty cannot compound, and returning actuals.

| Member | Evidence | Owner |
|---|---|---|
| **Belt lines** | The only paths are the line generator into a plan into the ghost builder — which walks to *every* tile, handles straight lines only, and carries ghost ceremony — or a per-tile hand loop | **This plan** |
| Pipe and wall lines | Identical path | Inherit `place_line` for free; contiguous geometry fits the contract exactly |
| Pole lines | Same path, but pole runs are **spaced** at wire-distance pitch, not contiguous — a contiguous contract does not cover them | **This plan**, via a `spacing` argument |
| Uncapped `craft(count)` | Count passes straight through and completion time compounds | **The HUD Partition**, where blocking `craft()` is deleted outright. This plan does not touch crafting |
| Single-only `pickup` | No bulk removal, so deconstructing a misplaced line is a hand loop | Out of scope; the mirror-image member |

## 2. Why a bulk verb is lawful at all

Constitution §7: **the API may infer exactly what the game infers for a human making the same gesture, and no more.**

A belt line is one continuous drag in the human interface. One gesture, and the game fills the tiles. `place_line` is that gesture.

What the rule rejects, and this plan does not build: a waypoint API taking start, corner and end. Each leg would be deterministic, but no human gesture routes a belt around a corner. Routing, turns and obstacle avoidance stay in the model, composed as separate calls it fully enumerated.

**A bulk verb is never justified by tedium.** Constitution §2 is explicit that turn cost is not evidence — turns are a currency the agent is meant to spend. `place_line` earns its place as a gesture the game itself supports, not as relief from repetition. That distinction is exactly what separates it from the ghost builder, which was argued for on the other grounds and is being deleted.

Two corollaries:

- **Auto-routing along a belt flow is the maximal form of the waypoint mistake.** Delete the phantom; never implement it.
- **Reach is dynamic** — a window centered on the agent's *current* position, read at call time — so no static "these n tiles are placeable" promise is possible. The orchestrated verb makes that moot: the honest invariant is per-step, because we walk before we place, and the cap bounds the total.

## 3. `place_line`

```
belt_item.place_line(start, direction, count, spacing=1) -> LinePlaced
```

**It lives on the item, not on a placement module.** A person places a belt by holding a belt (Constitution §4), and a belt line is one continuous object rather than a bulk operation over tiles — which is also why fail-fast was always the right shape. Pipes are equivalent.

**Contract:**

- **The tile set is computable by the caller before the call**: `start + i·spacing·unit(direction)`. The model can, and is taught to, pre-check exactly that set. Because `spacing` is an argument, the mutation set stays computable from the call alone. The cap bounds `count`; note that *walk length* grows as `count·spacing`, so duration is bounded but not by tile count — recorded as a consideration.
- **Inventory is checked upfront**, before the first walk, so the model never learns mid-line that it is short.
- **Orchestration is stance-chunked**: walk once per reach window and place the whole window from one stance, rather than walking to every tile. The ghost builder's own loop is the existence proof that walk-and-place composition works today.
- **Fail-fast, no skipping.** Stop at the first blocked tile. A gapped belt line is dead, and continuing past failures is the wrong shape here.
- **It returns actuals** (Constitution §8, load-bearing rather than stylistic): the exact placed count and positions, the first blocker with its position and a structured reason — the Lua side already computes colliding entities, distance and terrain cause — and the agent's final position as the resume point. Every element of the delta is a subset of the pre-computed tile set, so expectation and reality reconcile tile for tile.
- **The bound is a contract bound, not a gameplay rule** (Constitution §9). Running out of belts and hitting an obstacle are the game's business and need no API expression. At the bound the call returns actuals; it never raises as though it had stopped with nothing to say.
- **Corners are model-composed**: two calls whose tile sets the model computed. The engine curving the meeting belts renders geometry the model fully specified; it is not inference.

### 3.1 Per-entity contracts

"Entity-generic" hid real differences. One mechanism, but each rider has its own geometry and direction semantics.

| Entity | Pitch | What `direction` means | Specifics |
|---|---|---|---|
| **transport-belt** | contiguous | Line axis **and** per-entity facing — items flow along the line | The core case. Corners are two legs; a gap kills the line, so fail-fast is load-bearing |
| **pipe** | contiguous | Line axis only — pipes are undirected | A gapped pipe line is equally dead. Underground crossing is a directional pipe-to-ground pair the model composes from the segment read, never auto-inserted |
| **wall** | contiguous | Nothing — direction is irrelevant | Pure free rider |
| **electric pole** | **spaced at wire-distance pitch** — contiguous never fits a real pole run | Line axis only | The model computes spacing from the prototype data, or lifts positions from the pole-line read. Poles are sparse — a long run is a dozen placements — so the bulk verb matters least here. `spacing` is kept because it is one argument, not a second verb |

Deliberately not covered: **pole coverage** is 2D set-cover, not a line, and gets no bulk verb — the optimiser itself is deleted by the API plan, because the cursor shows a human coverage, never a solved cover.

**Belt-drag auto-underground is noted and deferred as additive.** Under Constitution §7 it is lawful: a human dragging into a cliff gets the underground pair inserted for them, unasked, as part of the gesture. Two open facts before building it — it is unverified against our engine image, including what happens when the obstacle exceeds underground range; and it is *player-input-side* behaviour, so there is no underground logic anywhere in the placement Lua to inherit. We would be implementing it. The grounding claim is about the human's experience, not about free code. It blocks nothing.

**Where it sits relative to the HUD Partition:** `place_line` occupies the body for its whole duration, so it stays in code, blocking, exactly like mining. It is a shipped composition like the ghost builder was, but in the lawful form: bounded, caller-enumerable, fail-fast, actuals-returning. It rides walking's completion channel, which is sequence-checked — **no dependency on the notifications work.**

## 4. Deletions and repairs

Category 2 is fixed by removal, not implementation. Items 3, 5 and 6 are **blocking** for the API plan's entity reference object: broken reads must not be moved onto a new surface.

1. **Delete `ConnectionType.BELT_FLOW`.** Never implement it.
2. **Decide `INSERTER_REACH`'s fate** — delete it from the enum, since it has its own method, or dispatch it. One surface per capability; no enum members the accepting method rejects.
3. **Fix the inserter names** against the live prototype set, derived rather than hand-copied, and fix the throughput recommendation that names a nonexistent variant.
4. **Fix the stale direction docstring** in the placement Lua, whose mapping contradicts the runtime error a few lines below it. Not model-facing; drift hygiene.
5. **Fix the two diagonal defects.** `_calculate_line_positions` and `get_pole_line` each interpolate along an arbitrary vector and yield fractional, un-snapped positions — invalid geometry that validation merely marks invalid, with no usable signal. They are **separate code paths**, and only the coverage helper bothers to snap. Minimum fix for both: reject non-axis-aligned input loudly rather than producing garbage.
6. **Fix the underground distances.** `get_underground_segment` hardcodes maximum distances that drift from the live prototype data, and its silent fallback for unknown names is a phantom-adjacent lie — reject unknown names loudly. Pull the numbers from the prototype pipeline, exactly as the pole-line read already does for wire distance. ⚠️ Before changing any number, verify the semantics: the prototype field may count center-to-center rather than gap, so the current values could be an off-by-one-conservative encoding rather than plain drift.

## 5. Teaching

1. **One invariant, stated once:** bulk verbs mutate exactly the tiles you can compute from their arguments, and they tell you exactly what they changed when they stop early. That sentence covers mining and `place_line` together.
2. **A worked belt pattern**, parallel to the existing power-chain pattern: drill, connection-position cue onto a belt tile, pre-check the line, `place_line` legs, inserter bridge off the belt into the consumer. Include the resume idiom — on a blocker, clear or reroute, then call again from the returned resume point.
3. **Direction semantics, two sentences:** a belt faces the direction items flow; a corner is two perpendicular legs meeting, and the engine curves them. You specify geometry, never curves.

## 6. Before believing any of this worked

- **A baseline on the current surface.** Do models lay belt lines today when the task rewards it — unprompted, then prompted toward hand loops and the line generator? **If prompting alone fixes belt use, Category 1 dominates and the verb's expected effect shrinks. Reassess before building it.** Shared run with the ghost, HUD and API plans.
- **Comprehension probes, no acting.** Predict the tile set of a described call, including a spaced pole call — that is the probe that catches whether the arg-computability claim survives contact. Predict item flow direction for a described belt. Predict what a corner requires. Predict that a pipe takes no facing, and what a pipe-to-ground pair needs. Wrong predictions mean the teaching (§5) is load-bearing; right-but-unused means salience, which is not this plan's problem.
- **An executed check of the verb itself** — the fail-fast resume contract and the stance chunking — before any claim that `place_line` works. Constitution §13.

## 7. Explicitly out of scope

- Bulk removal, the mirror of this verb. Recorded as a Category-3 member only.
- Pipe, pole and wall teaching. The mechanism generalizes; their patterns are separate work.
- A pole-**coverage** bulk verb. Never.
- Underground insertion inside a line stays model-composed; the engine-native drag case is §3.1's deferred addition.
- Whether the line generator survives once `place_line` exists. Plausibly dead code afterward; decided then.

## 8. Where this lives

| What | Where |
|---|---|
| The placement primitive, generic and belt-capable | `src/fv_embodied_agent/agent_actions/placement.lua`; `game/agent/embodied_actions/place_entity.py` |
| Reach read dynamically at call time | `placement.lua` |
| Structured placement failures — collision, distance, terrain | `placement.lua` |
| The mining cap precedent | `game/agent/embodied_actions/mining.py` |
| Walk-and-place composition proof | `game/agent/ghost_builder.py` |
| Walking, async with structured failures | `game/agent/embodied_actions/walking.py` |
| The belt-flow phantom, the inserter list, and both diagonal defects | `game/agent/placement_hints.py` |
| Hardcoded underground distances and the silent fallback | `game/agent/placement_hints.py` |
| Prototype source for wire and underground distances | the prototype data pipeline, scoped by `fv_filters.yaml` |
| Prompt gaps | `docs/system-prompt/factoryverse-system-prompt-v3-template.md` |

## 9. Related plans

- `API_AFFORDANCE_REDESIGN_DEFERRED.md` — owns `place_line`'s home on the item, and deletes the pre-flight validator, so the pre-check idiom becomes the red-preview shape: read buildability, then place and be told why. §4's repairs are blocking for its reference object.
- `HUD_PARTITION_DEFERRED_REFACTOR.md` — no conflict. Crafting's Category-3 membership is resolved there by shape-change rather than capping. Its belt-crafting micro-eval overlaps this plan's baseline; one scenario can serve both if sequenced deliberately.
- `GHOST_SURFACE_DEFERRED.md` — `place_line` is the lawful replacement for the line-shaped uses of the ghost builder. Landing it first softens that deletion's turn cost.
- `NOTIFICATIONS_PRIMITIVE_DEFERRED.md` — no dependency.
