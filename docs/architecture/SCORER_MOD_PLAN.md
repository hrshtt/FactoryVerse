# The scorer — a fourth mod that judges from the engine

**Status: DESIGNED, not executed.** Every code claim was verified against the tree on
2026-09-02, every engine claim against `resources/factorio-api/2.0.76/` or the installed
2.0.76 client. Nothing here has been built. Principles live in `docs/CONSTITUTION.md`;
this plan argues from §13–§15 and §19–§20 and proposes two clauses it cannot argue from
(§12).

**Scope, stated first so it cannot creep.** This plan owns one mod, `fv_scorer`, and the
Python that configures it and reads it. It owns the reward, a fixed diagnostic battery,
and three integrity checks. It does **not** own a goal-specification language, authored
predicates, human-gameplay scoring, or deterministic replay of agent runs. The first of
those is recorded in `GOAL_SPECIFICATIONS_DEFERRED_INDEFINITELY.md` and is not worked on
until explicitly said so. The others are named in §8 and §15 as out of scope.

---

## Summary

The score today is automated production, read from the force's flow statistics by a
Python verifier over a polled file. It is the right quantity and it is thin: freeplay
verification always succeeds, the campaign checkpoint records raw counts with no pricing
and no windows, and nothing explains *why* a run scored what it scored. The run
forensics say every run so far failed on whether the harness could say truthfully what
it had just done — and the score is read through that same harness.

**The correction: the meter is not the sensor.** The scorer is a separate mod that reads
the engine — forces, flow statistics, the character, events — and never our files or our
storage for anything that is a reward. That makes it a second witness on every world,
and the divergence between the two witnesses becomes a number the run record carries.

| | Now | After |
|---|---|---|
| Reward | raw automated item counts, Python-side, polled JSONL with a feed-stale guard | production score priced by the engine's own `production-score.lua`, per force, computed in-engine from flow windows |
| Freeplay | `verify_task` returns success unconditionally | the same reward, plus a diagnostic battery that explains it |
| Where the score is computed | Python, from a file the snapshot mod writes | `fv_scorer`, from the engine, written to its own file |
| Who sees what | one scalar, in `scores.jsonl` at checkpoints | three named outputs (§3): reward to the record and the horizon, diagnostics to the record only, integrity to the record only |
| Coupling | none (nothing exists) | `fv_scorer` depends on `base`; optionally on `fv_embodied_agent` for custom events and agent lookup; the agent mods never call it |
| Checkpoint score | a claim written next to the save | recomputable from the save (§8, gated on one check) |

---

## 1. What exists today

Verified 2026-09-02.

- **Tasks.** `game/tasks/base.py` — `TaskConfig` with `starting_inventory`,
  `all_technologies_researched`, and a `VerificationCriteria` of `target_item`, `quota`
  (items per 60 game-seconds, FLE-compatible), `sustained_seconds` (30) and
  `check_interval_seconds` (5). Twenty-four FLE-ported throughput tasks in
  `definitions/throughput_tasks.py`.
- **Verification.** `game/tasks/verification.py:35` `ThroughputVerifier` — rate from
  the delta of the force's `input_counts` over the delta of ticks, `checks_required`
  consecutive passes, reset on any dip; the VERIF-1 feed-stale invariant at `:65,:149`
  exists because a dead feed once served the same frame for sixty-three checks.
  `verify_task` at `:456` — `FREEPLAY` succeeds unconditionally.
- **Sources.** `game/tasks/sources.py` — three readers over
  `script-output/factoryverse/agent-snapshots/{id}/production-statistics.jsonl`, which
  `fv_snapshot/game_state/Agents.lua:130-211` polls every sixty ticks with a heartbeat
  write every five polls so the tick advances. `DuckDBSource` refuses to answer force
  production from the database (Constitution §10).
- **Attribution.** `fv_embodied_agent/Agent.lua:228` `create_or_get_force` — every agent
  is its own force, friendly to `player` and to every other agent force. `:654`
  `get_production_statistics` returns `input_counts` / `output_counts`; `input_counts`
  is production and hand-crafted products never appear in it (measured 2026-08-29,
  `0cd396e`).
- **Campaign.** `evals/freeplay/checkpoint.py:30` `capture_score` — produced, consumed,
  hand-crafted, hand-mined, rockets, researched count, entity counts, database
  fingerprint, power; appended to `scores.jsonl`. `:116` `create` — paused save, DuckDB
  copy, fingerprint, score, all hashed.
- **Horizon.** `environment/config.py:938` `TurnConfig` — `horizon_ticks(researched,
  automated_rate_per_min)`, hashed into the record, never shown. The rate input is the
  unpriced sum of automated items per minute from `game/agent/turn_report.py`.
- **Record.** `infra/session/trajectory.py` — `VERIFICATION_CHECK`, `RUN_END`,
  `TURN_REPORT`; nothing carries a per-turn score.
- **Engine.** `core/lualib/production-score.lua` in the 2.0.76 client:
  `generate_price_list(param)` and `get_production_scores(price_list)`. Prices are seeded
  for raw resources, recursed through `prototypes.recipe` at call time (hidden recipes
  skipped, minimum-cost recipe per product, an energy term, a small ingredient-count
  exponent), so it prices exactly the set that survives `fv_filters.yaml`.
  `get_production_scores` sums net production per force. FLE's
  `fle/env/tools/admin/score/server.lua` is a lightly edited copy of the same function.
- **Engine, the body.** `LuaControl` on a character exposes `walking_state`,
  `mining_state`, `crafting_queue_size`, `crafting_queue_progress`, `crafting_queue`.
  `LuaFlowStatistics.get_flow_count(name, category, precision_index)` with
  `defines.flow_precision_index` from `five_seconds` to `one_thousand_hours`.
- **Engine, events.** `fv_embodied_agent/utils/custom_events.lua` defines nine events
  (`on_agent_created`, `on_agent_removed`, `on_chunk_charted`, `on_agent_entity_built`,
  `on_agent_entity_rotated`, `on_agent_entity_configuration_changed`,
  `on_agent_resource_mined`, `on_agent_crafting_completed`,
  `on_agent_mining_completed`), IDs served by value over the `custom_events` remote
  interface. Placement passes `raise_built = true` (`placement.lua:288`); pickup mines
  with `raise_destroyed = true` (`entity_ops.lua:847`); so the engine's
  `script_raised_built` / `script_raised_destroy` fire beside ours.

---

## 2. The decision — the meter is not the sensor

Constitution §15: silence is not evidence; where a floor might be lying, prove it is not
before building on it. The score is the one floor every result stands on, and today it
is read through the pipeline whose honesty is the thing under repair. Three times in
this refactor a check was green while the layer under it did nothing. A score with the
same failure mode is not a score; it is a rumor with a decimal point (§14).

So the scorer reads the engine for anything that is a reward: `LuaForce` statistics,
`LuaEntity` on the character, `LuaSurface` counts, engine events. It never reads a file
another mod wrote, never reads another mod's storage, and never asks Python what the
world looks like. Python tells it only *what to watch* (§7).

Two consequences are the point:

1. **A second witness.** The map model is the agent's observation. The scorer's census
   of the same force is the engine's. Their divergence is harness debt, measured per
   turn, and it is the first integrity number the record has ever carried (§6).
2. **The score is a fact about the world, not about the run.** A mod that reads only
   the engine can be added to a checkpoint save and asked again (§8).

The cost, accepted: the scorer cannot see intent, the agent's observation, or which
program caused what. Those live in the trajectory. Every cross-track quantity is a join
on the tick, not a mod feature.

---

## 3. Three outputs, named separately

Constitution §19 says the score and the horizon are computed separately and named
separately. This plan extends the rule to everything the scorer writes: a reward, a
diagnostic and an integrity number are three different objects, and conflating them is
how a diagnostic becomes a shaping signal by accident.

| Output | What it is | Source | Who sees it |
|---|---|---|---|
| **Reward** | one scalar the agent is shaped toward: automated production score | engine flow statistics × engine price list, per force | the record; the horizon (as today, an S2 condition decides whether the priced or unpriced rate feeds it); the agent only through §19's declared inputs |
| **Diagnostics** | the battery that explains the scalar (§5) | engine reads, custom events, the certified status dump, harness marks | the record only. **Never the agent.** |
| **Integrity** | whether the harness told the truth (§6) | scorer versus map model, engine event versus custom event, fingerprint before and after | the record only |

Two rules follow and are load-bearing:

- **A reward is priced by the game.** No term in the reward is a weight a designer chose.
  Production score qualifies because the price list is the engine's. A reward for
  attention, or for using belts, or for revising a plan, is a designer's taste about good
  play, which §1 refuses as a boundary and this plan refuses as a reward.
- **A diagnostic is not a reward.** It is not shown, not summed into anything shown, and
  not an input to the horizon. If a diagnostic ever earns its way into shaping, it does
  so by amending §19 by name, not by a config flag.

---

## 4. The reward

**Production score, per force, in-engine.** `production-score.lua` is required from
`__core__` (its home is `core/lualib`), the price list is generated once at boot and
written to the scorer's output so the record carries it, and the score is
`get_production_scores(price_list)[force]` sampled on the scorer's cadence and at every
mark (§7).

**Automated only.** Force flow statistics exclude hand-crafted products (measured
2026-08-29), so the engine's number is already the automated number; nothing is
subtracted. Hand-crafted and hand-mined totals are recorded beside it from the custom
events, as diagnostics, never netted into the reward.

**Rates from engine windows.** A throughput task's "sustained thirty seconds at quota"
becomes `get_flow_count` at the five-second precision, six consecutive samples — the
same semantics as today's verifier, evaluated inside the clock it measures. The
feed-stale class of defect (VERIF-1) has no analogue in-engine and is retired with the
Python verifier once §9.3 passes.

**Comparability.** The price function is the one FLE's open-play metric is built on, so
a FactoryVerse production score and an FLE production score are the same quantity over
the same prototype set. That is a property to protect: parameters to
`generate_price_list` stay at their defaults unless a check shows the filtered
prototype set breaks a default.

**What is not a score term.** Rocket launches, researched count, entity counts and power
are facts the checkpoint already records; they stay facts. Whether freeplay has a win
condition is `SCENARIO_BOOT_CONTRACT_DEFERRED.md`'s open gate and is not decided here.

**The horizon.** Unchanged in mechanism. `TurnConfig.horizon_ticks` takes research tier
and an automated rate; whether that rate becomes the priced rate is an S2 condition
(`TURN_CONTRACT_DEFERRED.md` §8.7) and is recorded in the manifest either way. The
scorer supplies the number; the turn owns the ramp.

---

## 5. The diagnostic battery

Fixed, enumerated, and closed. Adding to it is a plan amendment, not a commit. Each row
names its source and its join key; each must pass §9.8's vacuity check before it is
written.

**World-side, computed by the scorer.**

| Diagnostic | Definition | Source | Join |
|---|---|---|---|
| Unattended fraction | production score gained between an `end_turn` mark and the next `turn_start` mark, over the score gained in the whole turn | flow statistics, marks | turn |
| Starvation ticks | ticks per machine in `no_fuel`, `no_ingredients`, `no_power`, `low_power`, `output_full`, `no_minable_resources`, summed per status and per force | the existing status dump (`fv_snapshot`), **certified once against `LuaEntity.status` and then consumed, not re-walked** (decision 2026-09-02) | tick, entity name + position |
| Starvation while absent | starvation ticks during which the character was farther than reach from the machine | status dump ∩ character position | tick, entity |
| Milestones | first tick at which each holds, per force: an entity of type transport-belt exists; a machine has an inserter with it as drop target; an electric mining drill exists; a science pack appears in automated production; a technology completes whose packs were all automated | `script_raised_built`, force build statistics, flow statistics, `on_research_finished` | tick |
| Hand share | hand-crafted and hand-mined counts beside automated, per item | `on_agent_crafting_completed`, `on_agent_mining_completed` | tick |
| Body time | ticks walking, ticks mining, ticks with a non-empty crafting queue, per turn | `walking_state`, `mining_state`, `crafting_queue_size` sampled on cadence | turn |

**Process-side, computed in Python from the trajectory.** Listed so the join is designed
once; none of these is the mod's business.

| Diagnostic | Definition | Source |
|---|---|---|
| Servicing fraction | tool calls whose program only moved items into or out of entities, over all tool calls | `tool_code` events |
| Refuel gap versus dose burn | ticks between refuels of one burner entity, over the burn time of the dose given | custom events + prototype fuel values |
| Dead-poll turns | turns whose programs contain reads only | `tool_code` events |
| Reads before acts | reads in the same program preceding the first mutation | `tool_code` events |

`TURN_CONTRACT_DEFERRED.md` §8.5 already asks for the second and third as the treadmill
re-run's measures.

**Deliberately absent.** No bottleneck attribution, no "should have built X", no
LLM-judged anything. The scorer may compute conclusions the agent is not handed
(`TRANSPORT_CONNECTIVITY_PLAN.md` §3 binds the agent surface, not the evaluator), but a
conclusion needs a rule, and the rules for those are a specification language, which is
deferred (`GOAL_SPECIFICATIONS_DEFERRED_INDEFINITELY.md`).

---

## 6. Integrity

Three checks, each producing a number per turn in the record.

1. **Census parity.** Entity count by name for the force, `count_entities_filtered` in
   the scorer versus `map_entity` in the map model at the same tick. The existing
   `dev/census.py` is the third witness when the two disagree. A non-zero divergence is
   harness debt, and it is the number that would have caught the snapshot boot defect
   that blocks Phase 4 today.
2. **Event parity.** Every `on_agent_entity_built` (our claim) matched to a
   `script_raised_built` (the engine's claim) in the same tick for the same force, with
   position compared exactly. A mismatch in position is the snapped-placement mirage
   (SNAP-MIRAGE-1, 2026-08-25) caught in-engine; a claim with no engine event is a lie.
3. **Read-only.** The scorer's own pass must not change the world. The state fingerprint
   (`remote_view.state_fingerprint`) before and after a full scorer sample must be
   identical, checked in the live suite. The precedent is GLOBAL-NET-1, where an
   observability path mutated physics.

---

## 7. Coupling — what the mod depends on, and what depends on it

**Engine facts that constrain it** (from `NOTIFICATIONS_PRIMITIVE_DEFERRED.md`, verified):
each mod has its own Lua state and `storage`; `remote.call` is the only runtime hop and
copies its arguments; custom event IDs are engine-global integers shared by value;
`require` across mods shares implementation, never instance; mods freeze after load.

**Dependencies.** `fv_scorer/info.json` declares `base >= 2.0` and an *optional*
dependency `? fv_embodied_agent`. With the agent mod present the scorer reads the custom
event IDs into its own storage on `on_init` / `on_configuration_changed`, re-registers
from storage on `on_load` (the snapshot mod's pattern), and calls the agent mod for the
agent list and positions. Without it the scorer still scores forces; it loses hand-share,
body time and event parity. **The agent mods never call the scorer.** A thing under
measurement does not know its meter, and the scorer must be removable without touching
them.

**Configuration flows from Python, over the scorer's own remote interface.** Python is
already the one place a run is assembled (`EnvironmentConfig.for_run`).

```
remote.call("scorer", "track_force", force_name, label)   -- which forces, labelled
remote.call("scorer", "set_cadence", ticks)               -- sample interval (default 300)
remote.call("scorer", "mark", kind, payload)              -- opaque: turn_start, end_turn, checkpoint, …
remote.call("scorer", "price_list")                       -- the list in force, for the record
remote.call("scorer", "sample")                           -- one immediate sample, returned
```

Marks are opaque labels the scorer stamps with the tick and writes; the scorer does not
know what a turn is. That keeps it agnostic to the turn contract while letting every
turn-scoped diagnostic in §5 be computed from the marks.

**Outputs.** Files only, under `script-output/factoryverse/scorer/<force>/`: `samples.jsonl`
(tick, score, flow windows, body time, integrity counters), `events.jsonl` (marks,
milestones, event-parity records), `price_list.json` once. No UDP in this version: Python
reads the files at every mark it set, so nothing waits on a datagram, and the notifications
plan's vehicle question (`stream.lua`, fourth-mod-or-library) is not reopened here. Python
writes a `turn_score` event to the trajectory with what it read, so the record shows what
the harness saw.

**The agent mod gains one read.** A remote call returning `{agent_id, force, position}`
for every live agent, so the scorer can find the character without knowing how the
agent mod names things. Small, and the only change to an existing mod this plan asks for.

**Explicitly out of scope, by decision 2026-09-02:** scoring human gameplay. The mod
would work on it, and that is not a reason to pursue it.

---

## 8. Checkpoints and replay

**What the scorer buys on a checkpoint.** The checkpoint today stores a score beside a
save. With the scorer, the score is a function of the save: add `fv_scorer` to the mod
list, load the save, sample. That turns `CheckpointRecord.score` from a claim into a
certification pair (§13) — *if* flow history survives a save, which is §9.1 and is not
assumed. If it does not, a reloaded checkpoint can recompute the census and the research
state but not the production history, and the score in the checkpoint stays a claim.

**What it does not buy.** Deterministic replay of an agent run. A dedicated server records
no `replay.dat`; agents act over RCON; and under the turn contract the in-turn clock runs
on wall time, so a program's RCON calls land on ticks that will not reproduce. Replay would
need a tick stamp per RCON call (the record has one per program) and a driver that pauses
and steps. That is a decision for the work `TURN_CONTRACT_DEFERRED.md` still owes, and this
plan neither requires it nor designs it. The replay-file method in the data-collector
repository is a human-input instrument and is out of scope with human gameplay.

---

## 9. Before believing any of this worked

In order. Each is a check, not a reading.

1. **Flow history persists in a save.** Load the pristine `iron_ore_saturated 2.0` save,
   read `get_flow_count("iron-plate", "input", ten_hours)` before a tick runs. Non-zero
   means checkpoints are recomputable; zero means §8's first paragraph is false and says so.
2. **The price list is total over the filtered set.** Every item and fluid in the pruned
   prototype set has a non-nil price; the shared items price identically to FLE's copy.
3. **Two sensors agree.** On the fixture, the scorer's per-force score over a window
   equals the Python verifier's from the polled file over the same window. Only then is
   the Python verifier retired, and the retirement is its own commit.
4. **Read-only.** Fingerprint before and after a full sample, identical, in the live suite.
5. **Census parity on the fixture** — scorer, map model and `dev/census.py` agree on 284
   belts and the rest of `TRANSPORT_CONNECTIVITY_PLAN.md` §1.
6. **Event parity.** Place one entity through the agent mod; both events observed, same
   tick, same position. Place at a position the engine snaps; the parity record shows the
   delta.
7. **Cost.** UPS on the fixture with and without the scorer at the default cadence, and
   at cadence 60. A number, in the record.
8. **Vacuity, per diagnostic.** Each row of §5 is run on a world where it must be zero
   and one where it must not be. A diagnostic without both fixtures is not written.
9. **The in-engine sustained check reproduces a recorded verdict.** Replay the
   `VERIFICATION_CHECK` events of an existing run against the scorer's windows; pass/fail
   agrees.

Constitution §13: none of this is true until its check has been run.

---

## 10. Order of work

Ordered so the reward lands before anything that explains it, and so no Python is
deleted before its in-engine replacement has agreed with it.

1. **The two engine checks** (§9.1, §9.2). They decide what §8 may claim.
2. **The mod skeleton:** `info.json`, storage, `track_force`, `set_cadence`, `mark`,
   `sample`, the files. Reward only. Read-only check (§9.4) and cost (§9.7).
3. **Two sensors** (§9.3), then retire the Python verifier and the polled production file
   as a verification source. `sources.py` keeps the hand-crafted readers.
4. **Integrity:** census parity, then event parity (§9.5, §9.6). Wire `turn_score` into
   the trajectory and the campaign's `scores.jsonl`.
5. **Diagnostics,** one row per commit, each with its vacuity pair (§9.8). Status rows
   last, after the status dump is certified against the engine once.
6. **The checkpoint recompute** (§8), if §9.1 allowed it.

Nothing here is placed in `docs/EXECUTION.md`'s phase order yet. It starts when the
floor under Phase 4 stops lying, because §9.5 needs that fixture to mean something.

---

## 11. Teaching

None. The scorer is invisible to the agent. The horizon's declared inputs are already
in the report under §19; no score line, milestone list or diagnostic reaches the prompt
until an S2 condition (`TURN_CONTRACT_DEFERRED.md` §8.7) decides that showing the score
is a treatment worth measuring.

---

## 12. Proposed Constitution clauses

Two things this plan needs that no clause supplies. Proposed wording, to be adopted or
refused by name.

**§22 — The meter is not the sensor.** *Whatever computes a score reads the engine
directly and shares no code, storage or files with what the agent reads. The divergence
between the two is recorded. A score read through the agent's observation surface
inherits every defect of that surface and certifies nothing.*

**§23 — A diagnostic is not a reward.** *A reward is priced by the game and declared to
the agent in terms of its inputs. A diagnostic explains a reward and reaches only the
record. Nothing moves from the second class to the first except by amending §19 by
name.*

---

## 13. Where this lives

| What | Where |
|---|---|
| The engine price function | `core/lualib/production-score.lua` (2.0.76 client; not vendored — vendor it or require `__core__`) |
| FLE's copy, for comparability | `../factorio-learning-environment/fle/env/tools/admin/score/server.lua` |
| Task schema, verifier, sources | `game/tasks/base.py`, `verification.py`, `sources.py` |
| Campaign score and checkpoint | `evals/freeplay/checkpoint.py`, `campaign.py`, `models.py` |
| Horizon constants | `environment/config.py` `TurnConfig` |
| The turn report's production rows | `game/agent/turn_report.py` |
| Run record | `infra/session/trajectory.py` |
| Per-agent force and production read | `src/fv_embodied_agent/Agent.lua` |
| Custom events | `src/fv_embodied_agent/utils/custom_events.lua` |
| Placement raising the engine event | `src/fv_embodied_agent/agent_actions/placement.lua`; `entity_ops.lua` |
| The production poll this plan retires as a verification source | `src/fv_snapshot/game_state/Agents.lua` |
| The status dump the diagnostics consume | `src/fv_snapshot/game_state/Entities.lua` |
| Mod lists a fourth mod touches | `infra/docker/factorio_server_manager.py`; `infra/factorio_client_setup.py`; `environment/config.py` |
| The third census witness | `dev/census.py` |
| The pristine fixture for §9.1 | `~/Library/Application Support/factorio/saves/iron_ore_saturated 2.0.zip` (the `.fv-output` copy is contaminated with mod storage) |

## 14. Related plans

- **`TURN_CONTRACT_DEFERRED.md`** — owns the horizon and the S2 conditions; §8.5's
  treadmill measures are §5 here; replay is its owed work, not this plan's.
- **`API_AFFORDANCE_REDESIGN_DEFERRED.md`** — §4.6 moved the polled production table out
  of the database; this plan moves the verification read out of the file and into the
  engine, the same rule one step further.
- **`NOTIFICATIONS_PRIMITIVE_DEFERRED.md`** — supplies the engine facts in §7; its
  fourth-mod question is not reopened, because this mod writes files only.
- **`TRANSPORT_CONNECTIVITY_PLAN.md`** — its fixture is the census ground truth in §9.5;
  its §3 rule on conclusions binds the agent surface, not the scorer.
- **`SCENARIO_BOOT_CONTRACT_DEFERRED.md`** — a fourth mod rides its mod-list and
  manifest-hash machinery; the freeplay win condition stays its open gate.
- **`GOAL_SPECIFICATIONS_DEFERRED_INDEFINITELY.md`** — what this plan deliberately does
  not contain.

## 15. Open

- Whether the horizon's rate input becomes the priced rate (S2).
- Whether `production-score.lua` is vendored into the repo or required from `__core__`
  at runtime; vendoring pins it, requiring tracks the engine.
- Multi-agent on a shared force: attribution then rests on custom events alone, and
  "harmony" measures are Constitution Part VII's business. Separate forces need nothing.
- Whether `scores.jsonl` in the campaign keeps its current shape or becomes a view over
  the scorer's files.
- Deterministic replay of agent runs (§8): a decision for the turn contract's owed work.
