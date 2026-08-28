# The HUD Partition — deferred refactor plan

**Status: PARTIALLY SUPERSEDED (2026-08-29).** Grounded in code sweeps; nothing here has been executed. Principles live in `docs/CONSTITUTION.md` — this plan's original cleavage rule is constitutionalised there as §5, and its candidate principle (*a blocking form is sugar over an agent-visible lifecycle; wrappers may hide mechanism, never policy*) is frozen as §9 in a stronger form.

> **Amendment 2026-08-29.** The tool half of this plan is withdrawn. Hand crafting and research **stay in the Python runtime** as accessors. The cognitive-burden motivation that produced the tools is met instead by splitting play into two **modes** — *planning* and *gameplay* — each a turn type owned by `TURN_CONTRACT_DEFERRED.md` §6. The reasoning: introducing top-level tools was an attempt to draw a boundary around a Python API that kept growing; a mode boundary draws it more strictly, keeps every action in one API with one grammar, and categorises the experiment cleanly. What survives here, section by section: the naming rule (§2.1, §2.2), the three-response-kinds and tick-stamp rules (§2.4, now rules for Python results), the join contract and `await_item` (§3), what does not move (§4), the mining rule (§5), the multi-agent facts (§10). What is withdrawn: the tool table (§2), the self-state tool (§2.3), the tool-registration and namespace-deletion steps (§8). Sections below carry their own amendment notes where the change bites.

## Summary

~~Remove **crafting** and **research** from the agent-visible Python namespace. They become discrete tools whose completions arrive as between-turn events.~~ **Withdrawn 2026-08-29** — they stay in Python (see the amendment above). What this summary still asserts: Python is the embodiment surface, completions arrive in the turn report, and the blocking `craft()` is deleted in favour of enqueue-plus-`await_item`.

| Human interface | Agent surface |
|---|---|
| The avatar in the world, and the windows you open by clicking things in it | `execute_dsl` — code-as-action over body verbs and entity interaction |
| The map screen | `execute_duckdb` for stable structure; `remote_view` for live map-scale reads |
| The HUD — the crafting queue, the research bar, your own state | ~~discrete tools~~ → `crafting` and `research` accessors in Python (2026-08-29), plus the turn report |

**The cleaving question is not "does the body do it" but *what were you touching when you did it*.** A window you open by clicking something on the map is Python. A window that belongs to you, and not to anything on the map, is a tool. Crafting and research are exactly Factorio's two HUD queues — the processes the game renders as chrome because they run without the avatar.

The interaction *shape* then teaches what prose cannot: the model starts a craft, acts elsewhere, and a completion lands mid-transcript that this turn did not cause.

## 1. Why

1. **Crafting is the cheapest verb to lift.** All validation is already Lua-side and synchronous — recipe exists, force-locked, hand-craftable, craftable count with per-ingredient have-and-need, partial-queue honesty. The *engine* owns the queue; Lua detects completion. Python's `craft()` adds only await plumbing and a timeout belief. **Lifting is a deletion, not a migration.**
2. **Research is the twin proof the altitude is livable.** The same logical shape — enqueue into an engine-owned queue, completion arrives as an event — already runs with no blocking wrapper at all.
3. **The drift objection is answered by partition, not duplication.** An earlier MCP server was killed for *duplicating* the API. Here the namespace objects are deleted. Each verb has exactly one surface.
4. **Theory of mind.** The blocking form teaches a temporal mirage — *the world blocks on me* — which is false: belts move, and the timed-out craft completes anyway. Events landing uncaused-by-this-turn instantiate world-independence in the message stream.
5. **Fidelity.** Humans walk while hand-crafting. The Lua state machines already support it — walking, mining and crafting are independent per agent — and the blocking wrapper serializes what the game keeps parallel. The partition restores a human affordance.
6. **The moat, expressed.** Completion-on-UDP is the substrate differentiator; the blocking wrappers hide it. The partition puts it at the agent-visible surface, and interleaving becomes scoreable straight from tool-call records.
7. **Multi-agent insurance.** An agent that cannot represent "my own craft is pending" cannot represent "that drill appeared because another agent placed it."

## 2. The tools

> **Withdrawn 2026-08-29.** No tool in this table will be built. The table is kept because its *contracts* — best-effort in-order batches, derived-not-extrapolated time remaining, selector-keyed clear, prerequisite-expanded research add, hand-craftable-versus-machine-only in the catalog — are the contracts the Python `crafting` and `research` accessors must now honour. Read each row as a method contract, not a tool. The two catalogs become **reads** on those accessors (`research.list_technologies()`, `crafting.list_recipes()`); the Lua remotes `get_technologies` (`agent_actions/researching.lua:35`) and `get_recipes` (`agent_actions/crafting.lua:15`) already exist and are today reached only by the one-shot initial-state prompt builder. That read, not a tool, is what closes the 2026-08-25 run's CATALOG-1 finding, where discovery ran through a mutating `enqueue`/`dequeue` loop and cancelled three real research jobs.

Queue-centric naming, because the engine owns the queues and the tools manipulate them. "Start" would imply the tool does the crafting.

| Tool | Contract |
|---|---|
| `hand_crafting_queue_add(items[])` | A batch of recipe-and-count. **Best-effort, in order:** each item's preflight runs against true post-previous-item inventory, because batch items compete for the same ingredients and atomic-all-or-nothing would need a simulate-and-rollback the engine does not offer. Returns per-item results plus the post-op queue, reporting what the engine actually consumed and queued — hand-crafting recursively crafts intermediates, so recipe-card arithmetic is not the contract. Time remaining is **derived from recipe energy and crafting speed**, never extrapolated from observed progress: an extrapolated estimate is a prediction, and predictions are the mirage class |
| `hand_crafting_queue_clear(selector)` | Exactly one of handle, recipe-and-count, or all. No bare "one" — ambiguous. States that cancellation refunds ingredients |
| `research_queue_add(techs[])` | Force-scoped, shared state. The engine auto-inserts prerequisites and order matters, so per-item acknowledgements are the wrong shape: the response is *what your request added, including prerequisites you did not name*, plus the full post-op queue |
| `research_queue_clear(selector)` | One tech, or all. Cancellation is non-destructive — per-tech progress is preserved |
| `list_recipes(filters)` | Name match, enabled versus locked-with-unlock-path, and **hand-craftable versus machine-only**, so models avoid the smelting game-rule failure instead of discovering it. Craftable-right-now is a returned annotation, not a filter; that keeps the catalog a catalog |
| `list_technologies(filters)` | Available (prerequisites met) versus researched versus locked; science-pack costs; what each unlocks |
| ~~agent self-state~~ | **Withdrawn 2026-08-29.** Position, health, inventory and current activity are already readable through the existing Python surface; no tool is added. The naming warning survives: nothing on the agent's own state may be called `status` |

### 2.1 Crafting names two acts — separate them

- **Personal crafting → `hand_crafting`** — the *name* of the act. Its own screen, hotkey-opened, and it hands you nothing directly: it holds ingredients in a buffer and delivers finished items to inventory. ~~The interactivity is indirect, which is exactly why it leaves Python.~~ *(2026-08-29: it does not leave Python; the indirectness is expressed by enqueue-plus-`await_item` rather than by a tool boundary.)*
- **Setting a recipe on an assembler → Python**, on the entity. You clicked that machine.

**`hand_crafting` is a naming rule as much as a placement: the word never appears on an entity.** This is the same trap already fixed once by making `mine` resource-exclusive (§5.2) — one verb spanning the boundary teaches models to reach for the wrong surface.

### 2.2 Catalogs follow their screens; per-machine applicability does not

Listing technologies and listing recipes are tabs in those two screens, so they belong with the queue they sit beside — reads on `research` and `crafting` (2026-08-29; previously "so they are tools").

**What a specific machine can accept is not.** That question is parameterized by an entity the agent is holding, so Constitution §4 puts it on the entity. Same underlying prototype data, two owners, split on *is this a question about an entity?*

### 2.3 `get_status` was three things — split them

| Thing | Home |
|---|---|
| One entity's status | **Python**, on the entity — the hover-and-click analog |
| The base-wide status summary | **Python**, on `remote_view` — the same live read batched, grouped by status value with drill-down, sharing a root with the per-entity name so the relationship is legible |
| The agent's own state | ~~A tool.~~ **Existing Python reads** (2026-08-29). This is what the earlier `get_status` was actually reaching for |

~~The self-state tool has no exact human analog.~~ Self-state stays where it is read today; inventory appearing both on `inventory` and in an entity's inspection is lawful: facts may live on more than one surface, verbs may not.

**Orientation, not gating.** Reading self-state and then acting next turn is check-then-act across a turn boundary. The taught idiom for downstream gating stays the in-code state-join (§3), inside the block that acts. A model using self-state as a polling loop has rebuilt the dead-poll failure — so the baseline run scores its call frequency.

### 2.4 Contract rules across all of them

*(2026-08-29: these are now rules for the Python results of `crafting` and `research`, and for every entry in the turn report. Rule 3's third kind — harness/transport error, world state unknown — is the only one that may surface as a tool error on `execute_python`.)*

1. **Stamp everything with the tick** — every tool response, every notification. Time remaining means nothing without a clock to subtract from, and a visible clock advancing across messages the model did not cause is the cheapest teacher of world-independence.
2. **Queue mutations return the queue.** Per-item results *plus* authoritative post-op state. This mirrors the HUD — after you click, you see the queue — and it kills the ambiguity around batches, auto-inserted prerequisites and partial failure in one move.
3. **Three response kinds, not two.** *Success:* the world changed. *Game-rule failure:* the world refused for in-fiction reasons, returned as data with a machine-readable reason and have-versus-need — **the model's beliefs are still valid**. *Error:* the harness or transport failed and **world state is unknown** — the only case where the model should re-orient before acting, and the only one that should surface as a tool error to external clients.
4. **Catalog scoping is validated, not leaked.** `fv_filters.yaml` scopes our catalog but the engine still holds military, train and space technologies. Queue tools validate against the scoped set, and an out-of-scope request returns a game-rule failure that *names the scoping* rather than saying "not found".

**Rejected: a screenshot tool.** It contradicts database-as-vision by adding a second, pixel-based spatial channel; it confounds the legibility record, because pixels are not diffable against ground truth, so any run where the model *might* have looked has a polluted story; and mechanically it is a multi-hop pipeline — renders only on a connected graphical client, async write, file pickup — not "return an image". Screenshots stay a spectator and debug affordance.

**Why the expanded set strengthens the argument.** The tool schema *is* prompt. With two tools, the game's expectations lived buried inside one mega-tool's reference. With this set the affordance list is the curriculum: a model that has never seen Factorio reads "queue crafting, queue research, clear, self-state" and infers personal production queues plus shared research.

## 3. The join contract — verbs partition, facts don't

The failure mode: a model that queues a craft and then *waits* — polling or idling — is strictly worse than a blocking `craft()`. **The design stands or falls on the join story.**

Only *initiation* moves to the tool side. Observation is omnipresent, through four independent channels; any one suffices, and none depends on an event reaching context.

1. **State-join, the primary idiom.** Products land in inventory, and `inventory` stays in the namespace. Blocks that need products open by checking for them. Ground truth, idempotent, survives compaction and missed events.
2. **Ledger-join.** The queue tools' post-op state: is it still queued, how much remains.
3. **Event-join.** The between-turn notification.
4. **The bounded wait** (§3.1).

**Ordering.** The blocking form ordered actions by *time*, which is the mirage — a long craft silently breaks a time-ordered plan. The partition orders by *state*: crafts depend on ingredients in inventory, and downstream acts depend on products in inventory. **Inventory is the ledger that orders everything**, which is how the game itself sequences and how humans play.

**Worked example** — fifty belts against a walk to an iron patch:

| Shape | Transcript | Outcome |
|---|---|---|
| Today, blocking | one block: await the craft with the body idle, then walk, then place | fully serialized; the alternative shape is invisible to the model |
| The fear | queue, read status, read status, … | dead turns. Real, and what the baseline measures |
| The reconcile idiom | queue the craft, get back a handle and an estimate that says it runs in the background · next turn, walk and place furnaces while the craft drains on the same game clock · *between turns, the completion lands* · next turn opens with the state-join, and falls back to other prep if short | faster **by construction** — and this scenario *is* the behavioral micro-eval |

**The downside is asymmetric:** a worst-case model that always polls degrades to roughly the status quo plus wasted turns. It cannot deadlock, because queue reads and inventory reads always exist. The upside is real concurrency.

### 3.1 The bounded wait, and why it is not `craft_await`

**There is deliberately no `craft_await`.** What exists instead sits on the other side of the fence: **`inventory.await_item(name, count=…)`** — Python asking a question about Python's own territory, *has this arrived yet*, never reaching over to start or cancel a craft.

It yields immediately if the items are already held, waits if work is genuinely in flight, and at its bound **returns actuals** rather than raising as though the craft had stopped (Constitution §9). It refuses at once to wait for something nothing is producing; establishing that well-foundedness may read the crafting queue, and may never write to it. **There is no `await_entity`** — items are crafted, entities are placed, and that split is load-bearing everywhere else.

**Does this undo the partition?** It restores the possibility of a same-turn bootstrap: queue, await, place. That is acceptable, because a person who queues five plates *does* stand there for two seconds and then place them. What was wrong was an *unbounded* wait. With a bound, long crafts fall out of the turn on their own and arrive as between-turn events — **the partition is then enforced by the world rather than by the API, which is the stronger place for it to live.**

The partition holds regardless because of theory of mind: the interface's shape tells the model that crafting happens outside its Python execution. That expectation is the deliverable; the await is an ergonomic within it.

### 3.2 Cross-boundary preconditions, and one recorded cost

Actions on one surface change what is legal on another. Crafting changes what can be placed; research changes what recipes a machine accepts. **Python reads those live on every call and never caches them** (Constitution §12), which makes *"you are not holding this"* the primary cross-boundary failure message and its quality load-bearing.

**Recorded cost:** a model can no longer write one script from raw ore to a working build. It must leave Python, craft, and return. That is the intended lesson — the world evolves outside your calls — but it is a real loss, noted so nobody later "fixes" it by accident.

## 4. What does not move

- **Mining and placement.** Their Python bodies are the honesty instrument — cross-channel reconciliation between the command, the completion and the database. They stay below the tool boundary; their *outcome facts* surface as data.
- **Mining stays blocking, and blocking is honest there.** Mining occupies the body — the human cannot do anything else either, whereas crafting continues while walking. The asymmetry that was a fidelity bug for crafting is fidelity for mining.
- **Setting a machine's recipe stays in Python.** A spatial act on a reachable entity. The machine's own process is world-state, observed through the map model and live reads.
- **Entity status stays in Python at both scales** (§2.3). It is live simulation state on map entities, and Constitution §5 makes Python the only channel to those.
- **No MCP resurrection.** The interaction layer's tool table is the mechanism.

## 5. `mining` is not a top-level accessor

### 5.1 The correction

§4 answers *does mining become a tool* — no. This answers a different question: *is `mining` a **name** in the agent-visible namespace?* Staying in code is not the same as being a top-level accessor. **No.** Mining's only agent-visible entry is `resource.mine()`.

Mining is always parameterized by a resource the agent has already located and walked into reach of. A top-level `mining.mine(name, position)` reconstructs, by name and position, an object the reachable view just handed back. **A verb whose arguments re-look-up an object you already hold is an altitude error, not an affordance.**

The module already says so and is simply not obeyed: `embodied_actions/__init__.py` states that mining is not a top-level action, that resources have a `.mine()` method, and that the mining action is internal infrastructure — and its `__all__` omits it. The export barrier holds; the namespace barrier does not.

### 5.2 The rule, and the vocabulary that follows

This is Constitution §4 read from the negative side: **a verb earns a top-level name only if it is not always parameterized by an object the agent already holds.**

| Member | Standing |
|---|---|
| `walking`, `inventory`, `reachable_view`, `remote_view` | **Pass.** Their arguments are positions, queries, or nothing. `walking` additionally stands as a declared medium exception (Constitution §2) |
| `placement` | **Fail.** An earlier draft passed it on empty-position-plus-fungible-item reasoning; §4 reverses that from the positive side — a person places a belt by *holding a belt* |
| `mining` | **Fail** — this section |
| `entity_ops` | **Fail.** Its verbs are name-and-position-keyed exactly like `mining.mine`, and the object-level mirrors are already complete across the capability mixins |
| `ghost_builder` | **Fail**, and removed on independent grounds by the ghost plan |
| `placement_hints`, `verify` | **Fail.** Both answer questions about objects from a module |

**Vocabulary: `mine` is resource-exclusive.** Factorio uses one verb for both cases — its player API mines ore tiles and placed machines alike. **Our surface splits it**, and the split is already built at the object layer: resources have `.mine()`, placed entities have `.pickup()`.

**No entity-side name, docstring, return type or prompt line may use "mine" for picking up a placed entity, even though the engine does.** The engine's conflation is not inherited.

**One live defect this rule caught** *(fixed in `fda10e2`, 2026-08-25; the reference now reads "Prefer `entity.pickup()`")*: a decision-point note in the generated reference instructed the model to *"prefer `entity.mine()` when you already hold the entity object."* **No `mine` exists on any entity or mixin** — the method is `pickup()`. The reason it survived validation is still live and is the more important finding: the example validator walks code examples only, and every prose field (`decision_points`, `notes`, `preconditions`, `expected_outcome`, all of `ErrorCase`) still ships to the model unchecked.

## 6. Before believing any of this worked

- **Does the interaction layer actually inject notifications between turns?** The prompt *documents* that it does. *Answered 2026-08-25/28:* notifications **do** reach the model (15 Game Events blocks in the deepseek run) — but between inferences inside a turn, not between turns (`orchestrator.py:505`), and nothing records that they were delivered (`TrajectoryWriter.notification()` has no caller). The Turn Contract owns the correction.
- **Lifecycle comprehension probes**, no acting: what is pending right now? if you enqueue fifty gears and then walk, do they finish? what is the world-state after a craft "timeout"? what does `await_item` return when its bound expires with the craft still running? Wrong predictions justify surface surgery; right-but-unused means salience, which is not this plan's problem.
- **A baseline behavioral micro-eval on the current surface:** the fifty-belts scenario, time-boxed so interleaving wins by construction. Do models discover enqueue-then-walk today, unprompted and then prompted? **If they already interleave when prompted, the expected effect shrinks — reassess before building.** It also scores self-state call frequency (§2.3).

Constitution §13: none of this is true until its check has been run.

## 7. Dependency — the notification primitive

**This plan is what motivated opening `NOTIFICATIONS_PRIMITIVE_DEFERRED.md`**, and it now has two claims on that channel.

The partition ships no `craft_await`, so its join story rests on completions arriving in the turn report (2026-08-29: the report is the only between-turn channel; today the orchestrator drains notifications between *inferences* inside a turn, `infra/llm/orchestrator.py:505`, which the Turn Contract corrects). `inventory.await_item` rests on the same signal: **a wait can be no more honest than the completion it is waiting for.**

The failure mode is already in the tree, in §9's inventory: a craft timeout has no cancel path, so the craft completes in the world while Python reports failure. Constitution §9 forbids exactly that. But a channel with no sequence number and no loss detection cannot enforce it — a dropped datagram means the wait ends, the craft finishes, and nothing reconciles the two.

**Building the notification primitive is what turns Constitution §9 from aspiration into enforcement.** Whether it must land first is not decided here.

## 8. Refactor steps

1. **The gates** (§6).
2. **One Lua touch:** handle-keyed cancellation for the crafting queue, which is recipe-name-keyed today. Crafting *completion* needs no Lua work — it already emits on the same channel research uses. A mod change means a full restart to pick up.
3. ~~**The tool layer**~~ **The accessor contracts (2026-08-29):** make `crafting` and `research` honour the §2 contracts as methods — handle-keyed dequeue, derived time remaining in every enqueue result, prerequisite-expanded research add with the post-op queue returned, a caller-scoped research cancel (today `cancel_current_research` in `researching.lua:153` cancels whatever is active, regardless of who queued it), and the two catalog reads. No new game logic; handlers call the existing Lua verbs.
4. ~~**Namespace deletion**~~ **Delete the blocking form only:** delete `craft()` and its timeout path (`crafting.py:180` awaits with no `try/except`, no server-side cancel, and re-raises a bare `asyncio.TimeoutError` while the craft completes in the world — the CRAFT-TIMEOUT-1 incident of 2026-08-25). `crafting` and `research` stay in the namespace; regenerate the reference.
5. **The mining-name pass:** deletions and renames only. The mining action itself is untouched and stays injected infrastructure, which is already how the reachable view receives it. Drop the accessor from the namespace and from the documentation; resolve the alias that points "resources" at the mining action in one place and at the reachable view in another; purge the entity-side "mine" vocabulary (§5.2). Afterward: the generated reference has no top-level `mining.` accessor, `resource.mine()` and `entity.pickup()` still resolve, and no entity-side string contains "mine".
6. **Teaching:** the cleaving question in one sentence, and the reconcile idiom — state-join first, `await_item` as the bounded form. ~~Seed the unlocked-recipes and current-research placeholders that already exist in the prompt template~~ — *corrected 2026-08-29: `{UNLOCKED_RECIPES}`, `{AVAILABLE_TECHNOLOGIES}` and `{CURRENT_RESEARCH}` exist only as comments in `infra/llm/prompts/system_prompt.py:71-74`; the template contains none of them and nothing fills them.* The catalog reads and the turn report's research section replace what those placeholders were meant to do.
7. **Re-run the probes and the micro-eval; diff.**

## 9. Risks, and the policy hiding in the current tree

| Risk | Standing |
|---|---|
| Dead-poll regression — models wait instead of interleaving | Bounded by §3's asymmetry; the baseline measures it before commitment; mitigations are the runs-in-the-background nudge, the taught idiom, and events pushing |
| Two interaction grammars in one agent | Teachable — the cleaving question is one sentence and game-native |
| Turn-budget pressure on tool-calling clients | Crafting decisions are rare relative to spatial operations |
| Compiled skills cannot inline crafting steps | Coherent with the bet: procurement is turn-level planning, not frozen skill code |
| Surface drift | Prevented structurally — one surface per verb, enforced by deletion |

**The hidden-policy inventory** that motivated the candidate principle now frozen as Constitution §9. Each is a wrapper hiding *policy*, not mechanism:

- Walking timeout silently stops the walk and then raises.
- **Craft timeout has no cancel path — the craft completes in the world while Python reports failure.** Belief divergence by construction. *Observed live on 2026-08-25 (CRAFT-TIMEOUT-1); still present at `crafting.py:180`.*
- Progress packets extend the deadline for walking only.
- The ghost builder's non-strict mode continues past failures.
- A list-valued inventory transfer is N sequential calls behind one apparently atomic call.
- Causal barriers are wired only in the tiered runtime; the base runtime runs mining and placement bare. **Same verb, different epistemic guarantees depending on which entry point you came through.**

## 10. Multi-agent facts recorded now

Crafting is **character-scoped** and private; research is **force-scoped** and common. Therefore: research notifications must fan out to all agents, while the current channel is single-consumer and first-drainer-wins; research responses eventually need actor attribution; and clearing the whole research queue is a shared-state destructive operation, which is a griefing primitive between agents. Three facts, no design.

## 11. Where this lives

| What | Where |
|---|---|
| Crafting verbs, preflight and completion | `src/fv_embodied_agent/agent_actions/` (crafting) and its notification emit |
| Research verbs and the force-broadcast completion | `src/fv_embodied_agent/` research interface; `game_state/Notifications.lua` |
| Blocking `craft()` and its timeout path | `game/agent/embodied_actions/crafting.py` |
| The mining action and its docstring declaring itself internal | `game/agent/embodied_actions/__init__.py`; `game/agent/embodied_actions/mining.py` |
| Resource `.mine()` and entity `.pickup()` | `game/factory/resource/base.py`; `game/factory/entity/base_entity.py` |
| The agent-visible namespace | `environment/tiers/tier4_runtime.py` |
| The tool table | `environment/tiers/tier6_interaction.py` |
| Reachable view receiving the injected mining action | `game/agent/reachable_view.py` |
| Prompt placeholders for recipes and research | `docs/system-prompt/factoryverse-system-prompt-v3-template.md` |

## 12. Related plans

- `API_AFFORDANCE_REDESIGN_DEFERRED.md` — the parent. §5 here is the namespace-shape half of the same decision. Its §3 is amended alongside this plan's §2.
- `TURN_CONTRACT_DEFERRED.md` — §6 owns the two modes that replace the tools withdrawn here.
- `GHOST_SURFACE_DEFERRED.md` — `ghost_builder` fails §5.2 as well as being removed there on progression grounds.
- `BELT_AFFORDANCE_DEFERRED_PLAN.md` — `place_line` lands on the item, per §5.2's reversal, and stays below this boundary as body-occupying work.
- `NOTIFICATIONS_PRIMITIVE_DEFERRED.md` — §7. Two dependents now.
