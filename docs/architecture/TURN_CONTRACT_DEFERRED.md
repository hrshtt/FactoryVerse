# The Turn Contract — deferred plan

**Status: DEFERRED.** Grounded in code reads of all three harness paths, a trajectory audit across nine freeplay campaigns, and a code audit of the Factorio Learning Environment. Nothing here has been executed. Principles are distilled into `docs/CONSTITUTION.md` Part VI; this document holds the evidence and the mechanism.

This is the seventh plan, and it sits upstream of most of the other six. It exists because the project spent a year specifying *what the agent may touch* without ever specifying *what a turn is* — and the omission was invisible from inside every plan that assumed one.

## Summary

The causal loop between model and world — what the model sees before an inference, what it may do per inference, what comes back, and how far the world moves in between — was never a named object. It had no owner, no file, no check. Three harness paths therefore answered it three ways, each locally reasonable, none against a spec.

**The correction: the turn becomes a first-class contract, owned by the interaction tier, with one shape on every path.**

| | Now | After |
|---|---|---|
| Unit of action | One program per supervisor turn (Codex) · one per inference (Hermes) · up to ten chained (orchestrator) | One inference → one program → one result, on every path |
| Result delivery | A file the model is told to read (Codex) · in context (others) | In context, always |
| Clock during inference | Running, ×8 | Running in-turn at a human-shaped speed; fast-forwarded only by `end_turn` |
| World time per turn | Unbounded — whatever the model's tempo produced | Exactly T, normalized by `end_turn` |
| Attention per turn | Unbounded (Hermes, orchestrator) · one program (Codex) | N tool calls |
| Observation | Varies by path | The turn report: a diff over T, attributed |
| Horizon | Constant | Ramps with automation, as a declared reward |
| Tick attribution | Recoverable from stamps, never summarized | On every report: used / advanced / total |

**The second-order reason this matters is that nothing temporal can be measured until it lands.** The dead-poll, the fuel treadmill, the between-turn-event question in the HUD plan, the loss question in the notification plan, the phase split — every one of them is a question about the turn, and today the turn differs by which entry point you came through.

## 1. The finding

### 1.1 Three paths, three contracts

**Codex freeplay.** The supervisor owns the loop. Per turn it drains events into a file, invokes Codex once with an output schema whose only legal result is one JSON action carrying one Python program, executes that program, and writes the result to a file. Codex has no tool that reaches the runtime; its next inference is a prompt telling it to read the file. The model never receives its result as a result. It receives an instruction to go and look for it.

**Hermes.** A real tool loop with one tool, and a gate that blocks a second execution inside the same provider response: *reason from the first result and submit the next complete program in the following inference.* The result returns as a tool result. A live-state hook injects the world before every inference.

**The in-repo orchestrator.** Up to ten chained tool calls per turn; results go straight back into the message list; the turn ends on a `respond` or the cap.

Three answers to "what happens after my code runs". The Hermes gate is the closest to right and is the reference implementation for the one-program rule.

### 1.2 Why it was invisible

Not attention. Three mechanical reasons:

1. **The instrument ladder stops below the model.** The certification ledger certifies engine, mods, connections, database, namespace. Nothing certifies *the model was shown X after doing Y*. A row that cannot exist cannot be red.
2. **The trajectory record captures output, never input.** It records what the model did, not what it saw. On the Codex path what it saw is *whichever files it chose to read*, which is recorded nowhere. FLE records the full conversation per step; we do not. A model that ignored its result and a model that never received it are indistinguishable in our record — which is exactly the mirage-versus-blindness distinction the whole programme is about.
3. **Delegated harness work was reviewed by whether it ran.** A campaign that runs on file handoff looks identical from outside to one that delivers in context. The only thing that would have caught it is a contract to diff against, and there was none.

### 1.3 The treadmill was structural

The trajectory audit (nine campaigns, ~340 execution turns) found the "paycheck to paycheck" pattern real and half-explained by the clock:

- Codex reasoning gaps ran 2.7 game-minutes at median and 8–17 at the tail, because each turn re-reads files and the clock runs at ×8 meanwhile. Hermes gaps were under a minute, because results arrive in context.
- Measured refuel gaps were 3.5–5.3× the burn time of the dose that preceded them. The observe–act cycle was longer than the fuel horizon.
- But models also under-dosed against a stack that would have outlasted the worst gap, starved furnaces on ore fifteen times for every twice they starved drills on coal, and sat on over a thousand plates without placing a single belt or inserter across a hundred-plus turns.

So the clock set the tempo and policy kept them on the treadmill. Both halves need addressing; this plan addresses the first, and gives the second a horizon it can see.

**Speed ×8 was a wall-clock optimization that leaked into game semantics.** Once inference no longer consumes unbounded game time, the wall-clock speed carries no meaning and can be whatever the box tolerates.

## 2. The shape of interaction

### 2.1 Programs are piecewise, not batch

The unstated assumption underneath the Codex path was that a turn is one large program. It is not how these models work. A coding agent reads a file, decides, reads another, edits, runs a test — twenty small calls per thought, each returning the state *now*. The world does not drift while it thinks, and the only things that move without it are background processes whose completions arrive between its turns.

The freeplay trajectories show a piecewise agent trapped in a batch regime: a 24-iteration inspect-and-sleep loop written *inside* one program is a model building the observe-twice loop the harness denied it. Batch programs with polling loops inside them are the signature of this mismatch.

**Looking must be free.** If a read costs world time, the model stops reading, batches, guesses, and its programs grow the polling loops. Every setting below is judged first on whether it keeps observation free.

### 2.2 The rule

**One inference → one program → one result, delivered in context, on every path.** A program may be one line. A harness that delivers by file is non-conformant; a harness that lets a second program run before the model has seen the first result is non-conformant.

## 3. The contract

### 3.1 The turn

A turn is a budget of **attention** over a horizon of **world time**.

- **Attention: N tool calls.** Working figure 128. Whether N is a constant or a manifest parameter like T is open (§9); this plan treats it as a manifest parameter with a default, because it is the second half of an APM cap and the first half is already tunable.
- **World time: T ticks.** Every turn is exactly T of world time, whatever the model's tempo. §5 makes T ramp.
- **The clock runs during the turn** at a human-shaped speed. Thinking and acting both spend it. A read is stale by a human's reaction time, which is the honest amount.
- **N over T is an APM cap.** At 128 calls per ten game-minutes, roughly thirteen actions per minute — a human number. This is the currency Constitution §2 says turns are meant to be.

### 3.2 Every call is self-contained

A walk completes inside the call that started it. A mine completes inside its call. When a call returns, the body is idle. Nothing the agent's body does lingers past a turn boundary.

World processes do linger, and are supposed to: machines run, research progresses, the hand-crafting queue drains. Those are the world's business (§7).

### 3.3 `end_turn`

A tool call. It ends the turn and fast-forwards the engine by `max(0, T − ticks used this turn)`, so the turn totals T. A slow thinker gets a short advance; a fast one gets a long one; each sees the same world-time horizon.

- **No debt.** If the model used more than T, the advance is zero and the turn was simply longer. The report says so. Debt is a second mechanism, and legibility wants one.
- **Fast-forward speed is an implementation detail.** Run it as fast as the engine allows.
- **The report (§4) is assembled at the end of the fast-forward** and is the first thing in the next turn.

**What the tool tells the agent.** Its description says that it ends the turn, that the world will advance to complete the turn's horizon, that the horizon grows with automation and research, and what the current horizon is. It does not state the coefficients. The inputs to the ramp are things we want the agent to do; the constants are an experimental condition, not a game rule. Whether even this much invites gaming is an empirical question the S2 conditions in §8 exist to answer — the audit's prior is that the gameable quantity is automated production, and a model that games it has automated.

### 3.4 There is no free wait

Waiting inside a turn — a bounded `await_item`, or any in-turn advance — spends the same clock that `end_turn` would. So *when* to wait cannot be gamed; only *what* to wait for, and that is a question about throughput (§7).

**Decision recorded: no in-turn `advance(ticks)` verb.** `end_turn` is the only way to ask for world time in bulk. The honest replacement for the fifty-odd `asyncio.sleep` calls in the trajectories is a bounded `await_item` (Constitution §9), which waits on a fact rather than on a duration. A model that wants the world to move without waiting on anything in particular ends its turn. Open for reversal if the probes in §8 show models need a duration-shaped wait.

### 3.5 What stays blocking, what stays async

Walking and mining occupy the body and block inside their call, as today. Crafting is enqueue-only with `await_item` as the join, per the HUD plan's surviving half. Research is queue-only; its completion arrives in the report. Nothing else in the API waits.

## 4. The turn report

The observation at the start of every turn. A diff over the previous turn's T, attributed.

| Section | Content | Source already in the tree |
|---|---|---|
| Clock | ticks used (execution, thinking), ticks advanced, turn total, absolute tick | per-call tick stamps already recorded on the actor protocol |
| Horizon | next T and the inputs that set it | §5 |
| Production | items produced and consumed, **split automated vs hand-crafted** | the snapshot mod's production statistics; hand-craft completions off the notification channel |
| Map | entities placed and removed by name and position; ghosts placed and built-over | the map-entity table before and after |
| Status | transitions since turn start, grouped by status value, with positions | two status dumps diffed — the "changed" read the reducer was throwing away |
| Research | progress, completions, unlocks | research state and the force-broadcast completion |
| Crafting | completions (hand-crafted, incl. auto-queued intermediates); remaining queue with derived character-time and its share of the next horizon; stall reason if any; predicted vs actual completion tick — see §7.1 | the crafting queue read; hand-craft completions off the notification channel |
| Inventory | delta by item | the agent snapshot |
| Events | every notification received during the turn, sequence-numbered | the notification channel |

Nothing here is new machinery. It is one assembly over things the mods already write, done once per turn instead of on demand. The same object is what the planning phase reads (§6).

**Context cost is the report's design problem, not retention.** A full dump names every entity; the report must be grouped and thresholded so a large base produces a small report. The status summary shape in the API plan applies: which problem, how many, roughly where, with drill-down available through the normal reads.

## 5. The horizon as a declared reward

T ramps with automation. Early, a long advance is fuel starvation with nothing to show; late, a short one cannot show a bus filling or a research finishing. What changes across a game is how long the base survives unattended, and the ramp models exactly that: *you may leave for as long as your factory can run without you.*

**Inputs.** Two, both already in the report, both hard to fake:

1. **Research tier** — coarse, discrete, game-native, paid for with real production. It aligns the horizon with the game's own phases, which is also where the planning phase triggers (§6).
2. **Automated production rate** over the previous turn — production minus hand-crafted. The one quantity hand-crafting cannot inflate.

**Never** raw machine counts (fifty unfed furnaces) or research counts (cheap techs).

**Shape.** Monotone in both inputs, clamped to [T_min, T_max], frozen per experiment, hashed in the manifest, never changed mid-campaign. The working sketch is a per-tier base scaled by a bounded function of automated rate; the numbers are S2 conditions.

**It is a reward, and it is declared.** Score is automated production. T is shaping toward it. They are computed separately and reported separately; the report states the next horizon and the inputs that set it. A visible shaping signal is a teacher; an invisible one is a confound. What the agent is *not* told is the constants (§3.3).

**Rejected: agent-chosen horizon.** Letting the agent pick its advance length up to a cap makes the ramp emergent and removes the hyperparameter — and removes comparability, since a model that never advances long buys more attention per world-minute. Held as an S2 variant (advance *up to* T_tier), not the default.

## 6. Phases are turn types

The planning phase from the freeplay work is not a second mechanism. It is a turn with execution disabled and no advance: the report as input, the map-scale reads and the research queue and the plan and sub-goal tools as the namespace, `end_turn` as the exit with zero fast-forward.

- **Trigger:** research finished — the game-native breakpoint, where a human's research screen opens and the game pauses — plus a bounded model-requested replan. The freeplay planning campaigns showed plans written once and never revised; a forced re-entry point is what was missing.
- **T steps at the same boundary**, so the phase change and the horizon change are one event.
- **Decision recorded:** the planning turn's tool set is `execute_duckdb`, the plan and sub-goal tools, the research queue tools, and `end_turn`. `execute_python` is absent, which is how reachable interaction and crafting are excluded without a namespace filter. Open for revision (§9).

## 7. Crafting during the advance

A model that queues two hundred belts before `end_turn` receives them next turn at no attention cost. This is faithful, and it is symmetric: machines also produce during the advance at no cost. The advance does not favor hand-crafting over automation.

The real asymmetry — hand-crafting needs no capital — is Factorio's, and Factorio prices it:

1. **Throughput.** One character crafts serially at speed one. Ten assemblers craft in parallel. This only bites when task scale exceeds one character's output, which early-game tasks never do. **That is a task-design fact**: if the horizon is short enough that hand-crafting suffices, hand-crafting is the right play.
2. **Hauling.** Ingredients must be collected stack by stack. Under the attention budget, hauling costs the one thing the turn rations. Inserters haul for free. This is an argument against any bulk-collect sugar.
3. **Inventory capacity** bounds the queue's inputs.

And under this contract the "always await completion" gaming is gone by construction: waiting in-turn spends T (§3.4).

**Decisions:** do not touch the mechanic — a crafting queue that stops during the advance makes "the world runs without you" false for exactly one system, and the exception would be learned. Make hand-crafted versus automated legible in the report. Score automated production. Let T make hand-crafting lose where the game makes it lose. Put the derived queue time in every enqueue result so the model can see its queue outlast the turn.

### 7.1 The queue that outlasts the advance

The hand-crafting queue is the only process whose future is fully computable: serial, speed one, energy per recipe known, ingredients already taken. That makes it the one place in the report where we can state a prediction and then verify it.

**What the engine does.** Ingredients are consumed at enqueue, not at completion; cancelling refunds. The queue drains every tick the character exists — during walks, mining, and the advance — and nothing pauses it (§20). It stalls in exactly one case: output cannot be delivered because inventory is full. Queueing a recipe whose intermediates are missing auto-queues the intermediates ahead of it, so the queue the agent sees can be longer than what it asked for.

**Three moments, one vocabulary.**

*At enqueue*, the tool result carries per-item derived completion ticks (recipe energy over craft speed, summed serially), the total ticks remaining, and that total set against the horizon: whether the queue drains inside this turn, or spans into the next and by how much. Arithmetic, not extrapolation — the one prediction the HUD plan's rule permits.

*In the report*, a crafting block of four lines:

```
crafting   completed  inserter ×1, transport-belt ×50, iron-gear-wheel ×25 (auto)   char-time 2,850 ticks
           remaining  transport-belt ×150 — 4,500 ticks (≈45% of next horizon)   ingredients already consumed
           stalled    none      (or: inventory full since t+31,200 — 62 items undelivered)
           predicted  completion tick 36,480 → actual 36,480
```

The last line is deliberate. Every other section of the report shows only actuals. Here the report states what recipe data predicted and what happened, turn after turn — a cheap, built-in calibration lesson that recipe-derived numbers are trustworthy while extrapolated ones are not.

*In the score*, everything under `completed` is hand-crafted and lands on the production line as such. Remaining items count nowhere until they finish.

**The reading the agent is led to.** A queue that carries over is a throughput signal: *your hands are slower than your horizon.* The report puts "150 belts remaining, 45% of next horizon" beside what one assembler produced in the same window and prescribes nothing; the comparison is on the page. That is the moment an assembler pays off, said in arithmetic.

**Edges.** In a planning turn the horizon is zero and the queue does not move, which is correct. The queue is character-scoped: in the report it is *your queue*, never merged with force-wide production, which matters the moment there is a second agent.

## 8. Before believing any of this worked

In order, and the first two before any clock work:

1. **Nonce conformance.** A program prints a nonce; the next inference's *input* must contain it. Run on all three paths. This is the first ledger row above the model boundary, and it goes red on the Codex path today.
2. **Model input recorded per step** in the trajectory. Without it the legibility record has one track and no clock claim can be checked.
3. **One-program gate on every path**, checked: a second program inside one inference is refused.
4. **Tick ledger on every report** reconciles with the per-call stamps: used plus advanced equals the tick delta.
5. **Treadmill re-run** on the same seed under the new contract: refuel gap versus dose burn, servicing fraction over the run, first belt placed.
6. **Comprehension probes, no acting:** predict what happens to a queued craft at `end_turn`; predict whether a drill fueled with twelve coal survives a ten-minute horizon; predict what the report will show after placing an unfed furnace; predict the next horizon from a stated tier and rate.
7. **S2 conditions, not decisions:** running-clock-in-turn versus paused-between-calls; fixed T versus ramped; horizon coefficients told versus withheld; N as constant versus parameter.

Constitution §13: none of this is true until its check has been run.

## 9. Open

- **N: constant or manifest parameter.** Treated here as a parameter with a default of 128.
- **In-turn duration wait.** Dropped (§3.4). Revisit if probes show models need it.
- **Planning turn tool set.** As decided in §6; the plan and sub-goal tools themselves are the freeplay work's to specify.
- **What the `end_turn` description says** about the ramp. The cautious version is "the horizon grows with automation and research"; the S2 condition in §8 tests whether saying it changes play.
- **Multi-agent.** Turns become rounds: every agent submits, the world advances once. Recorded, not designed. FLE's default path does not interleave agents at all, which is worth knowing before its multi-agent results are cited.

## 10. The Factorio Learning Environment, for the record

Audited against the checkout. FLE pauses the engine during inference, runs one concatenated program per text completion, delivers results in context, and records the full conversation per step — all of which this plan adopts. But in the only shipped mode its actions teleport and instant-complete, crediting a synthetic tick counter that the engine never runs; the world only exists inside an explicit sleep, which real-sleeps the Python process for a duration scaled by game speed. Alerts exist but are wired only to an MCP path the trajectory runner never uses, so nothing the model did not cause is ever announced; research completion is visible only by re-polling. Its throughput tasks loop a sixty-second sleep until production stops rising.

FLE is the opposite pole from our continuous ×8: perfect attribution, zero world-independence. This plan sits between them on purpose: **ticks that are run, not credited, and that run whether or not the model asked.** What is ours if built: real-tick embodiment, an event channel, and interleaved multi-agent on a shared clock.

## 11. Tier 6, renamed by what it owns

Tier 6 is not "interaction mode". It owns the Turn Contract: observation assembly with provenance, the one-program gate, execution under the clock policy, result delivery, the event drain, the tick ledger, and the report. Codex, Hermes and the orchestrator are transports beneath it. Each conforms or is marked non-conformant in the ledger.

The tier rename plan should not call this layer `interaction`. `turns` is the candidate.

The tools it registers, after the rename addendum: `execute_python`, `execute_duckdb`, `end_turn`, the HUD plan's research and self-state tools, and in the planning turn the plan and sub-goal tools.

## 12. Where this lives

| What | Where |
|---|---|
| Codex loop: one program per supervisor turn, file-delivered result | `evals/freeplay/codex_runner.py` — the run loop, the action schema, the follow-up prompt |
| Hermes gate: one program per inference | the hermes adapter plugin's `CausalExecutionGate` (campaign artifact; source in the hermes-agent checkout) |
| Orchestrator: ten chained calls per turn | `infra/llm/orchestrator.py` `run_turn` |
| Actor protocol and per-call tick stamps | `evals/freeplay/actor_session.py` |
| Hard-coded game speed and the paused-clock validity check | `evals/freeplay/supervisor.py` |
| Pausing and unpausing the engine | `evals/freeplay/checkpoint.py` |
| The tool table | `environment/tiers/tier6_interaction.py` |
| Production statistics, status dumps, entity events | `src/fv_snapshot/` |
| Notification channel | `src/fv_embodied_agent/game_state/Notifications.lua`; `game/agent/event_stream.py` |
| Trajectory record (output only) | `infra/llm/trajectory.py`; the freeplay `sessions/*/trajectory.jsonl` |
| Run forensics that surfaced the treadmill | `docs/runs/`, `docs/EVAL_ISSUE_TRACKER.md` FREEPLAY-1/2/4 |
| The earlier one-shot planning phase | `docs/architecture/FREEPLAY_PLANNING_PHASE.md` |
| FLE comparison | `../factorio-learning-environment` — gym env `step`, `instance.py` game control, the fast-mode Lua under `env/tools/agent/` |

## 13. Related plans

- **`NOTIFICATIONS_PRIMITIVE_DEFERRED.md`** — the event drain becomes delivery at the turn boundary, inside the report. Half its unanswered list is answered here: where they land (the report), who consumes (the turn), what loss means (a sequence gap in the report's event section).
- **`HUD_PARTITION_DEFERRED_REFACTOR.md`** — its join story was a turn-contract question. Crafting stays in Python as enqueue-plus-`await_item`; research becomes queue tools plus the report; its first gate ("does the layer inject between turns?") is §8's nonce check.
- **`API_AFFORDANCE_REDESIGN_DEFERRED.md`** — status leaving the database is the report's status section; `await_item` is the only in-turn wait; namespace deletions proceed independently.
- **`BELT_AFFORDANCE_DEFERRED_PLAN.md`**, **`GHOST_SURFACE_DEFERRED.md`** — independent. `place_line` stays a self-contained call under §3.2.
- **`TIER_RENAME_PROPOSAL.md`** — Tier 6's name waits for this; `execute_dsl → execute_python` lands first so the tool table is written once.
- **`FREEPLAY_PLANNING_PHASE.md`** — absorbed as a turn type (§6).
