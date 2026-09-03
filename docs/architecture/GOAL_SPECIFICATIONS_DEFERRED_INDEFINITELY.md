# Goals as temporal-logic specifications — deferred indefinitely

**Status: DEFERRED INDEFINITELY. Not in scope. Not to be worked on until explicitly said
so.** This is a record of a design discussion held on 2026-09-02, kept so the idea is not
rediscovered from scratch and so its absence from `SCORER_MOD_PLAN.md` is read as a
decision rather than an oversight. Nothing here has been built, nothing is scheduled,
and no plan depends on it. The scorer plan is complete without it.

---

## What was being reached for

Factorio's simulation is deterministic and every fact in it is readable from Lua at
every tick. So a goal does not have to be a number compared against a threshold. It can
be a **formula over facts about the world and about time**, evaluated by a monitor that
runs inside the clock:

- **Spatial atoms.** An inserter feeds furnace F. Drill D and furnace F are on one belt
  component. Assembler A lies inside a pole's supply area. The character is within reach
  of entity E.
- **State atoms.** Furnace F has status `working`. The force holds at least N plates.
  The iron-plate rate over the last minute is at least R.
- **Temporal operators.** Eventually. Always. Until. Within N ticks. Sustained for N
  ticks. Since the last mark (a turn boundary).
- **Actor scope.** Every atom is evaluated for a force, so "for agent i" is free.

Goals and sub-goals become compositions of these. One language would then express
tasks, diagnostics and integrity checks, and the same monitor would evaluate all three.

## Where it lives in the literature

Two mature bodies of work, named so the next reader does not reinvent them.

**Runtime verification.** Linear temporal logic (Pnueli, 1977). Signal temporal logic
(Maler and Nickovic, 2004), whose robustness semantics (Fainekos and Pappas, 2009;
Donzé and Maler, 2010) return *how far* a run is from satisfying a formula, not only
whether it does — a graded score. Past-time LTL has constant-state online monitors
(Havelund and Roşu, 2002), which is the fragment that fits a Lua tick handler.
Three-valued semantics (Bauer, Leucker and Schallhart, 2011) make future operators
honest: true, false, or not yet decidable. STREL (Bartocci et al., 2017) adds
reachability over a spatial graph, which is close to "reachable along the belt
network". Allen's interval algebra (1983) expresses "the furnace was starved *while* the
agent was elsewhere". The Event Calculus (Kowalski and Sergot, 1986) models exactly
Factorio's structure: engine events initiate and terminate fluents that hold over
intervals. Vacuity detection (Beer, Ben-David, Eisner and Rodeh, 2001) is Constitution
§14 formalised: a specification satisfied for a trivial reason.

**Reinforcement learning from specifications.** Reward machines (Icarte, Klassen,
Valenzano and McIlraith, 2018; JAIR 2022): finite automata over atomic propositions,
reward per transition, decomposition for free. LTL2Action (Vaezipoor et al., 2021),
SPECTRL (Jothimurugan, Alur and Bastani, 2019) and DiRL (2021) train against temporal
specifications directly. The broader current term is reinforcement learning with
verifiable rewards. Craftax and MineDojo score milestone ladders. Eureka, Text2Reward
and Google's language-to-rewards have models author reward code, verified by a
simulator.

## What Factorio would add

- **Exact monitors.** Determinism makes a verdict a fact about the run, not a sample.
- **Engine-computed spatial atoms.** Transport lines, electric network ids, fluid
  segment ids, inserter pickup and drop targets, supply areas: all engine reads, usable
  live every tick by an evaluator that stores nothing.
- **Actor scope through forces.**
- **A native progression ladder** in research, so milestones are game-priced.
- **The turn boundary** as a first-class time mark.

## Three levels of ambition, if it were ever taken up

1. **Tasks as specs.** Today's throughput verifier is one hard-coded formula:
   eventually, sustained thirty seconds, rate at least quota. In the language it is one
   line, and every other task becomes expressible. For freeplay this would be a
   **milestone lattice** beside the production score, not a replacement scalar: first
   automated plate, first belt-fed furnace, first assembler with inserters on both
   sides, first science pack made by machines, first research paid for by automated
   packs. Engine-verified, graded by robustness, comparable across runs.
2. **Diagnostics as specs.** Starvation while absent, refuel gap versus dose burn,
   unattended survival, the transition chain behind a stopped output. Same language,
   same monitor, never shown to the agent.
3. **The agent's plans as specs.** Planning mode emits sub-goals in the language; the
   scorer monitors them; the report says which advanced, which were violated, which are
   undecided. That would address the plan-written-once-never-revised failure
   (`TURN_CONTRACT_DEFERRED.md` §6) with a verifiable plan tracker and would produce a
   belief-versus-truth signal with the agent's own spec as the belief. It touches the
   agent surface and is therefore a Constitution question before it is a build.

## Why it is deferred

- **Scope.** It is a language, a monitor, an atom library, a fixture discipline and a
  teaching problem. The scorer needs none of it to deliver a reward, a diagnostic
  battery and integrity checks.
- **The spec is the reward.** Specification gaming is the classic failure of this
  family. Designer taste re-enters through the specs, which is the §1 problem in a new
  coat; the only defence is that shaping specs must be game-priced and declared under
  §19, and that discipline is not yet exercised on the simpler reward.
- **Vacuity.** "Always not starved" on a base with no furnaces passes. Every spec would
  need a holds-fixture and a fails-fixture before it is armed. The scorer plan applies
  that rule to a fixed battery first; a language multiplies the surface it applies to.
- **Expressivity versus cost.** Future operators need lookahead; an in-engine monitor
  should stay in past-time plus bounded-future and report three-valued verdicts. That is
  a real design, not a library import.

## The minimum shape, recorded for whenever

Specs as data, sent to the scorer at boot and hashed into the manifest. A small atom
library over engine reads and custom events. A past-time monitor with bounded metric
operators in Lua, one state cell per subformula per force. Robustness written beside
the boolean verdict. The vacuity gate: no spec armed without both fixtures.

## What would reopen this

An explicit decision, in writing, after the scorer plan's checks are green and after
the first eval run under the turn contract has produced a diagnostic battery that a
fixed list demonstrably cannot express. Until then this file is inert.

## Related

- `SCORER_MOD_PLAN.md` — the scope this was deliberately kept out of.
- `TURN_CONTRACT_DEFERRED.md` §6 — the planning mode that level 3 would attach to.
- `TRANSPORT_CONNECTIVITY_PLAN.md` §3 — the rule that conclusions do not reach the agent.
