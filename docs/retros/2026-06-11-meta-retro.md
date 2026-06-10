# Meta-retro: what the certification session taught us about the project itself

Companion to the concrete artifacts (ledger, tracker, run retro). This is about the *shape* of the problems, not their instances. Written 2026-06-11 after one full day: 31 commits, 12 ledger rows certified, 4 mod bugs fixed, 1 field test killed and dissected.

## 1. The impasse was epistemic, not architectural

The session opened with "I'm at an impasse about how to go about it." Every design decision that had been stuck for weeks resolved in *minutes* once reality was pinned by execution:

- The belt-aggregation knot (KNOT-3, stuck since the build-taxonomy investigation) → resolved as "labels on primitives" within one message — *after* we learned the derived tables never existed at runtime anyway.
- The Stack-B fate → trivially "delete" once traced — the agonizing was over code nobody ran.
- The component-tables question only became *askable* once L1.5 measured them at 0 rows.

**Lesson: verification debt masquerades as design difficulty.** When you can't tell what exists, every design question is entangled with an inventory question, and both feel hard. Pin reality first; design decisions are usually easy afterward. The right response to feeling stuck on design is often a certification sweep, not a design doc.

## 2. Every representation of the system was wrong the same way — including the owner, including me, including the checks

The session falsified, in order: the owner's recollection (removal sync "broken" — it worked; derived tables "set up" — they never ran), CLAUDE.md (two mods, wrong commands, wrong counts), the flagship test (validating zero examples), two scout reports (confidently describing the dead stack as live), error payloads (silence as success), my own memory files, and finally **a same-day certification** (L4.4 passed on open ground, failed in a confined cell hours later).

The pattern is not "docs rot." It's that *all* representations — memory, prose, tests, sub-agent analyses, even fresh certifications — drift from the system, and **green/empty/silent all render identically to "fine."** There is no class of representation exempt from this; there are only representations with and without re-execution paths. Hence the only durable rule: a claim's trustworthiness equals the cheapness of re-running its check. Certification is a *measurement at a point in condition-space*, not a property of code — which is why L4.4 needed to be earned twice and why venue/condition coverage now matters as much as check existence.

## 3. Duplication is what made prose unreliable

Nearly every confident-but-wrong account traced to a *duplicated* structure: two DB stacks, two schema sources, two sequence counters, two registration paths (decorator vs import side effect), two inventory-read shapes. Scouts and humans read ONE copy and correctly described it — of the wrong twin. Deleting the dead twin (−3,800 lines) was epistemics work disguised as hygiene: it didn't just remove code, it removed the generator of false beliefs. **When two implementations of one idea exist, every description of that idea is unfalsifiable prose until one dies.**

## 4. A dishonest floor doesn't block agents — it educates them wrongly

The field test's deepest finding: the agent was *competent*, and competence made the failure worse. It ran a clean experimental loop — query water (0 rows), probe placement (all fail), call the connection helper (silent []), run a 30s controlled test (no power) — and updated, perfectly rationally, toward "water does not exist in this world." The solar pivot was good science on poisoned data. For the research thesis (continual learning on grounded primitives), this is the sharpest possible warning: **skills compiled against a lying world-model are wrong skills, learned with high confidence.** Floor honesty is not a quality bar; it is the precondition for the learning loop to converge on anything true. And eval failure-attribution must now always distinguish "agent can't" from "agent was misinformed" — which requires parallel ground-truth instrumentation (observe.py-class probes) *during* runs, not just trajectory reading after.

## 5. Where setup friction actually lives: boundary contracts

Cataloging the session's two dozen traps (ports that differ from the table, no-arg = no-op, named-args nil-collapse, force_resnapshot no-op, empty RCON responses on /c errors, list-vs-dict inventory shapes, exact-position lookups): all but one sit at a **boundary crossing** — Python↔Lua, host↔container, mod↔scenario, doc↔runtime. Inside any single layer, the code is mostly fine. The playbook + smoke ritual is the institutional answer; the generalization is that every boundary needs an *executable* contract (a probe someone can run), because boundaries are precisely where prose lies most and where no single layer's tests look.

## 6. The instrument ladder, and why order matters

The session accidentally derived an ordering: offline checks → audited harnesses → live single-claim checks → field test → retro. Each rung makes the next rung's signal *interpretable*: the $9 field test produced 14 cleanly-attributable failure modes only because the floor under it was mostly certified — March's identical test produced a fog of 11 entangled issues. Field tests are the most information-dense instrument we own, but their information density is proportional to how much of the floor beneath them is already pinned. Spend on evals only after the cheaper rungs are green; otherwise you're buying noise.

## 7. The operator's distrust was the best signal in the session

Three escalating corrections from Harshit — "actually run things," "even the contradictions could be stale," "don't trust the tests either" — each arrived *before* the evidence that vindicated it, and each out-calibrated my defaults at that moment. The missing piece was never awareness of the rot; it was machinery to operationalize the distrust (ledger, audit gates, verdict protocol). Conversely, the owner's *positive* beliefs about the system were no more reliable than the docs. Net heuristic for this project: *trust the human's suspicion, verify the human's confidence.*

## What to do with this (beyond the tracker)

- Treat "I think X works" (from anyone, including past sessions, including certifications under other conditions) as a ledger lookup, not a fact.
- Before any design debate longer than ten minutes: ask which inventory question is hiding inside it, and run that check first.
- Kill duplicated structures on sight or mark one canonical in the ledger — they are falsehood generators.
- Any new boundary (scenario API, container, remote interface) ships with a smoke probe the day it ships.
- Field tests are precious: never run one over an uncertified floor layer you intend to learn about.
