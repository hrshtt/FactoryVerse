# Retro: engine_unit_throughput finale attempt 3 — 2026-06-11_15-14-28 (killed T16/64)

**Run:** engine_unit_throughput · anthropic/claude-sonnet-4.6 via prime_intellect · lab-grid / server_0 / agent_1 · `game.speed=5` · 2026-06-11.
**Outcome:** 0 engine-units produced. Killed by the operator at turn 16 of a 64-turn budget (the run ended at an interactive `User >` prompt mid-recovery; the turn itself had hit its per-turn iteration cap — `/tmp/finale3_eval.log:7887` "Turn 16: Reached max iterations").
**Cost/tokens (VERIFIED from `trajectory.jsonl` `usage`):** 170 LLM iterations across turns 0–16; **12,352,760 prompt tokens**, of which **11,979,241 served from cache (97.0%)**; 61,576 completion tokens. `automation_produced` = 0 for every one of the 170 stats rows.

This was the first field run after two same-day fix batches (the cue/act-parity + fallback-deletion that killed attempt 2, certified L4.6 20/20; and the LIVE-1C cell-coherence + OBS-2 cache work). **It is the best engine_unit run on record and the first whose failure is a genuine in-game strategy gap rather than a harness lie.**

> **⚠️ RE-ANNOTATION 2026-07-12 (GLOBAL-NET-1, ledger L1.14): every electric-network observation in this retro is contaminated.** This run executed on a server whose fv_snapshot power-stats reader had CREATED a global electric network as a side effect (`Power.lua` nth_tick(300); fixed + certified L1.14 2026-07-12). On such a surface every electric entity is powered POLELESS through the global net (semantics executed-verified in L1.14's A/B). Specifically: (a) "engine network_id=1" at T0 and "furnace network=1" at T14 refer to the GLOBAL net, not a pole network — the machines were drawing from the engine through it, poles irrelevant; (b) the "network 1 vs network 9 fragmentation" subplot (timeline T14–15, finding L5) is not pole-topology fragmentation — network 9 was a pole island that never carried power, and no "engine→factory pole bridge" was ever load-bearing; (c) the §4 causal chain's final compounding step ("pole bridge vanished, splitting the network") is retracted — fuel starvation alone explains the death, which the rest of §4 already establishes. The agent-behavior findings (no_fuel root cause, 3-turn diagnosis latency, STATUS-1, PROMPT-2b) stand unchanged: the agent reasoned over the same contaminated surfaces the operator saw. ISLAND-1/POLE-PREVIEW-1 evidence from this run needs re-observation on a post-fix boot.

## House rule for this document
No "X works" claim without a trace pointer (`file:line` or turn number). Sources: `chat.md` (human-readable), `trajectory.jsonl` (mechanistic), `/tmp/finale3_probes.log` (independent 30s observe.py censuses), `/tmp/finale3_eval.log` (orchestrator stdout), `system_prompt.md`, `initial_state.md`. **VERIFIED** = read directly from a trace. **HYPOTHESIS** = inference not fully pinned by the traces.

---

## 1. Turn-by-turn timeline (compact)

`Snapshot tick` is the value the throughput meter reported to the agent. `chat.md` line refs unless noted.

| Turn | What the agent did | Outcome | Evidence |
|------|--------------------|---------|----------|
| 0 | Sited offshore-pump on shore (find_water + probe loop); cue'd pump→boiler (**2 cues**), placed boiler EAST; cue'd boiler→steam-engine (**1 cue**), placed engine; hand-fed coal; placed a pole | **Power chain assembled first-pass.** Boiler reached status 27 (working), water+steam both 200/200, engine network_id=1. The assembly that killed all 3 prior runs. | 796–800 (2 cues), 850–853 (1 engine cue), 1024–1031 (water+steam flowing), 1072 (network_id=1) |
| 0 | First `add_fuel(coal×50)` | Threw RuntimeError ("cannot accept ANY of it") **but** boiler later shows `coal:46` burning — partial insert that threw | 890, 973–976 |
| 1 | Walked to iron area, began placing electric drills | Built; `'NoneType'.inspect` + empty `TimeoutError` swallowed-and-retried | error scan T1 |
| 2 | Inspected power; **boiler already status 53 (no_fuel)**, fuel `{}`, burning None; steam fluidbox drained to 0 | Engine `power_output=0.0 max_output=0.0 energy=0.0` — engine had **never actually generated**. Re-fueled (partial-insert error again). | 1942–1946, 1983–1987, 2019 |
| 2–3 | Placed a **coal burner-drill at (80,64)** + wooden-chest at its ITEM_DROP | Coal extraction started (drill status 53 until fueled) — but it feeds a **chest 30 tiles from the boiler**, never the boiler | 2197–2201 (drill+chest), 781 (boiler at x=110) |
| 3–9 | Built out the factory: electric drills on iron, electric furnaces, assemblers, belts, poles | Steady growth; recurring `WalkingUnreachableError` (now context-rich, ERR-2), all recovered | probes 15:16→15:35; error scan |
| ~13 | Factory essentially complete: 7 electric-drills, 10 electric-furnaces, 8 assembling-machine-2 (recipes 4×engine-unit / 2×gear / 2×pipe), 59 belts, inserters, ~37 poles | Built and recipe-set, but **status 54 (no_power)** across the board | probes 15:33 (8 AM-2, 10 furnaces, 59 belts); eval log 5445–5448 (recipes engine-unit, status=54) |
| 14–15 | Noticed no_power; inspected furnace (status 54 / NO_POWER, energy=0, network=1); checked poles (network 9 — a *different* island from the engine's network 1) | Correctly identified a power problem; misattributed it to pole topology, walked back to the water to **add a second pump+boiler** | 8087 (NO_POWER), 8328–8335 (poles network 9), 8513/8684 (2nd pump+boiler placed) |
| 16 | Inspected the ORIGINAL rig: **boiler1 status 53 (no_fuel)**, steam fluidbox `name=None amount=0`; engine status 24; **"Poles nearby: []"** at the engine | **Correct diagnosis at last.** Re-fueled boiler1, tried to rebuild the engine→factory pole bridge | 8822 (boiler 53, steam=0), 8865 (no poles at engine) |
| 16 | Pole-bridge rebuild from x=113→x=60 | Blocked: poles can't sit on the coal/iron ore patch (x≈59–86); partial line only. **Operator killed here.** | 8969–8974, 9015–9018 |

Throughout: `Snapshot tick` the agent saw **froze at 404340 from T10 onward** (see §4, latent issue).

---

## 2. What the same-day fixes demonstrably bought

All VERIFIED in-trace. This is the half of the run that worked, and it is the part that has killed every prior attempt.

1. **The cue idiom was used verbatim and connected first-pass (PROMPT-2 + the new "Worked Pattern: The Power Chain" prompt section).** The new system-prompt section (`system_prompt.md:99–147`) walks pump→boiler→engine via `get_connection_positions`. The agent followed it almost line-for-line at T0: `get_connection_positions(pump, "boiler", FLUID_PIPE)` → 2 cues (`chat.md:783–800`), placed at `cues[0]`, then `get_connection_positions(boiler, "steam-engine", FLUID_PIPE)` → exactly 1 cue (`850–853`), placed at it. Result: water 200/200 and steam 200/200 flowing within the same turn (`1024–1031`). Attempt 2 died at T1 on a hand-placed fluid-dead boiler; the March and 2026-06-10 runs never got power live at all. **This is the single biggest delta in the run series.**
2. **First-pass connection, zero teardown.** Contrast 2026-06-10, which placed-and-tore-down boiler/engine rigs ~10 times against gaslighting `[]` cue returns. Here the cue returned real candidates immediately and the agent committed.
3. **Cache economics (OBS-2).** 97.0% of 12.35M prompt tokens served from cache (`usage.cached_prompt_tokens` summed across 170 rows). The March run was ~10M at 0% cache; the cache_control + ProgressDeduper work is observably live. First call cached=0 (cold), last call cached 78,061/78,832 (`trajectory.jsonl` first/last `usage`).
4. **Structured errors, recovered every time (ERR-2/ERR-4).** `WalkingUnreachableError` now carries position+distance+bearing+out-of-bounds hint (e.g. `chat.md:1877`) and the agent re-routed each time. The partial-insert path returns an honest success-with-rollback message naming the returned count (`/tmp/finale3_eval.log:1487` — "Partial insert: only 11 of 50 coal fit … remaining 39 returned"). No March-style blind retry loops anywhere in the 170 iterations.
5. **AFFORD-1 terrain affordances used well.** `find_water(near=…, radius=…)` and `is_buildable` used repeatedly instead of place-as-sonar (`chat.md:8390`, `8617–8639`). The 2nd offshore-pump at T15 was sited by probing `is_buildable` rather than hundreds of throwaway placements.

---

## 3. Root-cause analysis of the terminal failure

**The factory was built correctly and then ran dark for essentially the entire run because power was never a sustained, self-feeding loop.** The causal chain, read backwards from the symptom the agent kept seeing:

> machines status 54 (no_power) ← network 1 has 0 energy ← steam-engine power_output 0 ← boiler produces no steam (steam fluidbox `name=None, amount=0`) ← **boiler status 53 (no_fuel)** ← hand-fed coal exhausted, with **no coal→boiler automation** ← (compounded at the end by) the engine→factory pole bridge having vanished, splitting the network.

**VERIFIED mechanism — fuel starvation, not generation undersizing.** The drafted run-log row (`EVAL_ISSUE_TRACKER.md:164`) hypothesised "1 boiler/engine = 900kW vs ~2MW load." The traces do **not** support an overload reading: at every inspection where the engine was dark, the boiler was simultaneously `no_fuel` with an empty fuel inventory and the steam box at 0, and the engine reported `max_power_output=0.0` (`chat.md:1942–1946`, T2). An overloaded-but-fed generator throttles; it does not report `max_output=0` with an empty boiler upstream. The boiler cycled no_fuel at **T2 (1983), T4 (3137), and T16 (8822)** — each manual refuel bought a few minutes of game time (amplified to seconds of wall-clock by `game.speed=5`), then drained. **Power was therefore off for most of the run, which is sufficient on its own to explain `automation_produced=0`.** (A capacity ceiling may also exist once fuel is solved — that is a real but *secondary* HYPOTHESIS, untested because the boiler never stayed lit.)

**Why the agent didn't close the loop.** Two distinct wrong mental models, both VERIFIED:

- **Power as one-time setup, not a consumable loop.** The agent hand-fueled the boiler (T0, T2, T4, T16) and treated "boiler is burning" as done. It *did* attempt coal automation at T2–3 — placed a coal burner-drill and a collector chest (`chat.md:2197–2201`) — but built a coal→**chest** loop 30 tiles from the boiler, with nothing carrying coal the last leg into the boiler's fuel slot. It held a 2nd boiler + 2nd steam-engine + 2nd offshore-pump in inventory the whole run (`/tmp/finale3_eval.log:5714` shows `boiler:1, steam-engine:1` reserve mid-run) and only placed the spares at T15–16, unwired.
- **no_power never traced upstream until T16.** From T13 the entire factory read status 54. The agent re-derived "no_power" at the *furnace* repeatedly (T14 `8087`, T15 `8370`) and chased it laterally — pole networks (T15 `8328`), a second pump+boiler (T15) — for ~3 turns before, at T16, finally inspecting boiler1 and finding it `no_fuel` with no steam (`8822`) and the engine's bridge pole gone (`8865`). The diagnosis it reached at the kill was the correct one; it simply arrived 3 turns too late and then hit the un-buildable ore patch trying to rebuild the pole run.

**The status integers are load-bearing and illegible (the crux).** Every status the agent reasoned over arrived as a **raw integer**: boiler `27`/`53`, furnace/machine `54`, engine `24`/`1`. The agent had to carry a private int→meaning map in its head (53=no_fuel, 54=no_power, 27/1=working, 24=no-power-variant). It got `54`→no_power right but spent turns treating no_power as a *pole* problem rather than reading `54` as "look upstream at the generator." Where the symbolic name WAS surfaced (the `__repr__`, e.g. `status=NO_FUEL` at `chat.md:851`, `status=NO_POWER` at `8087`) the agent reacted faster. The legibility gap directly cost the 3-turn upstream-tracing delay. (Lines where raw ints appear and the agent reasoned over them: `1833` `54`, `1942` `24`, `1983` `53`, `8370` `54`, `8822` `53`, `8823` `24`.)

---

## 4. Other latent issues found in the traces (not previously flagged)

| # | Finding | Evidence | Class |
|---|---------|----------|-------|
| L1 | **Throughput `Snapshot tick` froze at 404340 from T10→T16** while the game kept advancing (probes show tick 360557→554661 over the same wall-clock window). For the last 7 turns the agent's *production feedback was stale* — even correct production would have been invisible. A frozen production-statistics feed reads identically to "0 produced." | `trajectory.jsonl` turn ticks all 404340 from T10; `/tmp/finale3_probes.log` 15:30 tick=360557 … 15:41 tick=554661 | a (harness) — likely the production-statistics snapshot path stalling; build the SNAP-1 "staleness LOUD" banner on this feed too |
| L2 | **Boiler fuel-slot cap is tiny and undocumented.** `put_inventory_item(coal×50)` returns "only 11 of 50 fit" (`eval log:1487`); a separate insert tops out at `coal:50` (`1489`). The agent had no signal that a boiler holds only seconds of fuel at `game.speed=5`, reinforcing the one-shot-fuel model. | `/tmp/finale3_eval.log:1487`, `1489` | b/e — a "fuel buffers are small; automate fuel" line belongs in the power-chain prompt |
| L3 | **Coal burner-drill placed with no fuel → status 53, silently idle.** The agent fueled it a step later, but a drill that mines coal yet itself needs coal is a bootstrap trap with no surfaced hint. | `chat.md:2197` (drill status 53), prompt note `system_prompt.md:144` (drop_target resolves only once fueled) | b — the prompt warns about drop_target-needs-fuel but not about the drill's own idle status |
| L4 | **`WalkingUnreachableError` is the dominant friction class, not connections.** ≥6 occurrences across T2/T8/T13/T14 (error scan). The agent burned tool calls re-routing around its own factory and the cell edge. Connections (the thing we fixed) were smooth; *movement inside a dense cell* is now the time sink. | error scan T2,T8,T13,T14; `chat.md:1877`, `8736` | a/e — pathfinding-in-clutter + possibly an approach-tile helper for dense builds |
| L5 | **Pole networks silently fragmented (network 1 vs network 9).** The factory poles formed network 9 (`8328–8335`); the engine was on network 1 (`1072`). The agent never received a "these are not the same electric network" signal and only inferred fragmentation indirectly. Aligns with the known ElectricPoleState stub. | `chat.md:8328–8335` vs `1072`; tracker L2.2/L2.3 | a/c |
| L6 | **Agent-code bugs that didn't bite:** `NameError: 'iron_f'` (T6), `'NoneType'.name` from `get_entity` returning None when out of reach then immediately using it (T15 `8551`, T16 `8736`). Recovered each time, but the `get_entity`-returns-None-when-out-of-reach-then-deref pattern recurred 3×. | error scan T6,T15,T16 | c/d — a get-then-walk-then-get idiom would help |

---

## 5. Prioritized fixes (effort estimates)

Derived from §3–§4 evidence, highest eval-impact-per-effort first.

1. **STATUS-1 — symbolic status names at the payload/dump tier (S, ~half day).** Today only `__repr__` carries names; raw inspection returns ints (§3 crux, L2.3). Surface `status_name` alongside the int everywhere `inspect()`/entity payloads flow. This is the single change most likely to have changed *this* run's outcome — the agent diagnosed faster every time the name was present. Already half-scoped in TYPE-1's residual ask (`tracker:88`).
2. **PROMPT-2b — power-as-consumable-loop + diagnose-upstream idiom (S, ~half day, prompt-only).** Two additions to the "Power Chain" section: (a) "Boilers burn fuel continuously and their fuel buffer is tiny — a hand-fed boiler dies in seconds. Automate coal→boiler with a burner-drill ITEM_DROP onto a belt/inserter into the boiler's fuel slot, exactly as you automate ore." (b) A diagnose-upstream rule: "no_power on a machine means trace the generator, not the poles: check the steam-engine's power_output, then the boiler's status and fuel, then the water — fix the *source* before re-wiring." Cite the 4× refuel + chest-30-tiles-away failure as the worked anti-pattern.
3. **L1 — make the production-statistics feed staleness LOUD (M, ~1 day).** A frozen `Snapshot tick` for 7 turns is indistinguishable from "0 produced" and silently invalidates the agent's only success signal. Extend the SNAP-1 staleness banner (already TODO per `tracker:129`) to the throughput meter: if `snapshot_tick` hasn't advanced in N turns, say so in the Task Progress block. Without this, *any* future run can be gaslit into believing it produced nothing.
4. **L2 — boiler/burner fuel-buffer hint in errors (S, ~hours).** The partial-insert message already names counts; add the fuel-seconds remaining, or at least a one-line "boilers hold ~Ns of fuel; automate" in the power-chain doc (folds into #2).
5. **L4 — dense-cell pathfinding / approach-tile helper (M).** Movement is now the dominant friction; an approach-tile resolver for "walk to the nearest standable tile near X" would cut the WalkingUnreachableError churn. Lower priority than power, but it's the next bottleneck once power is solved.
6. **L6 — get-then-deref guardrail (S, docs).** Document that `reachable_view.get_entity` returns None when the target is out of reach, and provide the walk-then-get idiom; three NoneType derefs traced to this.

---

## 6. Scorecard vs the three prior runs

VERIFIED figures cited; "—" = not recorded / not reached.

| Metric | 2026-03-28 | 2026-06-10 (T17) | 06-11 attempt 1/2 | **06-11 attempt 3 (this)** |
|--------|-----------|------------------|-------------------|----------------------------|
| Power live (sustained)? | No (died on power setup) | **No** (water_tile gaslit; SNAP-1) | a1 pivot T3; a2 fluid-dead boiler T1 | **Yes, first-pass at T0** (`chat.md:1024–1031`) — but not *sustained* (boiler kept draining) |
| Turns to power chain assembled | — (never) | never (cues returned `[]`) | never | **T0** |
| Full factory built? | No | No (0 pipes, 0 pumps) | No | **Yes by ~T13** (7 drills, 10 furnaces, 8 AM-2 recipe'd, 59 belts) |
| Hard errors | 19 swallowed (blind retries) | many, gaslighting | — | **~4 structured + recovered** (+ WalkingUnreachable churn); zero blind loops |
| Prompt tokens / cache | ~10M / **0%** | ~10.08M / — | — | **12.35M / 97% cached** |
| Engine-units produced | 0 | 0 | 0 | **0** |
| Killed | died (power) | T17 (solar pivot) | T3 / T1 | **T16 (operator)** |
| Failure class | model + harness | **harness lie** (run-killer SNAP-1) | harness (LUA-1 fallback) | **genuine strategy gap** (consumable-power loop) |

The trend line is the story: the failure mode has walked steadily *up the stack* — from harness lies (06-10) and a bad fallback cue (a2) to, finally, a clean in-game strategy error the model could in principle have solved with better guidance. The floor stopped lying; the remaining gap is teachable.

---

## 7. Epistemics notes

- **The drafted root-cause was an under-evidenced HYPOTHESIS.** The run-log row's "900kW vs 2MW undersized" framing did not survive the trace: the boiler was `no_fuel` with `max_output=0` at every dark inspection, which is fuel starvation, not capacity throttling. Capacity *may* also bind once fuel is fixed, but that's unproven and shouldn't be asserted. Logged here so the tracker row gets corrected, not copied.
- **A frozen feedback channel (L1) means "0 produced" is not fully trustworthy as a *production* claim for T10–T16** — it is trustworthy as an *outcome* (power was demonstrably dark, so nothing could have been produced), but the meter alone could not have distinguished the two. The independent observe.py probes (`/tmp/finale3_probes.log`) are what let us assert "dark" with confidence; this is exactly why the gated finale ran them.
- **The agent's final-turn reasoning was correct.** It is worth recording that this was not a model that failed to understand power — at T16 it correctly found the unfueled boiler, the dead steam box, and the missing pole. It ran out of turns (and hit an un-buildable ore patch) executing a correct recovery. The fix target is *time-to-correct-diagnosis* (STATUS-1, PROMPT-2b), not the model's reasoning ceiling.
