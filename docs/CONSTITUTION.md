# The FactoryVerse Constitution

The smallest set of decisions that determine what goes into the agent's hands and where it lives.

This is not a description of the system. It is a description of the choices that shape it. Read it before proposing anything: if a proposal cannot be argued from these clauses, either the proposal is wrong or a clause needs amending — say which.

**What may never appear here:** anything that can become false without someone editing it. No file paths, no line numbers, no test results, no counts, no "currently". Examples name mechanisms in Factorio, never mechanisms in our code. If you need to know whether something works, run its check — this document will never tell you.

It supersedes the principle lists embedded in the individual plan documents.

---

## Part I — What the agent may do

### 1. The human player interface is the reference

The agent may do what a person at the keyboard can do. It may not do what a person cannot.

This is the only boundary available that is not taste. Every other criterion reduces to a designer's intuition about what is too hard — and a designer's intuition about what is too hard is the thing under measurement.

The test is a question with a checkable answer: **what is the human doing while this runs?** If the answer is "nothing — this is happening for them," the capability is invented.

### 2. First exception — the medium

Replication is the guide, not the criterion. Where a human affordance is delivered through a channel an LLM does not have, and that channel is not what we are measuring, abstract to the level of the decision.

Two standing instances:

- **Walking.** A person holds a key and steers around a rock. That is a continuous motor loop containing no decisions — they already know where they are going. Walking to a destination keeps the decision (where, and when) and drops the loop. Whether a model can emit direction constants for forty turns without losing track of its own position is a property of the channel, not a capability.
- **The map as a database.** A person reads the map screen and takes in a spatial gestalt at a glance. Queries over the same facts preserve every decision that glance informs, and drop only the optic nerve.

**The guard.** This is the most abusable clause in the document — any convenience can be dressed as a medium constraint. Two questions gate it:

1. Does the collapsed sequence contain decisions, or is it pure execution?
2. Is the thing being removed something we were trying to measure?

Walking passes both. A verb that places forty entities passes neither: each placement is a decision about what goes where, whether the plan still holds now that you have arrived, and what to do when one fails. **Abstract a channel; never a deliberation.**

Turn cost is not evidence. That an action is tedious or expensive in turns is not a medium constraint — turns are a real currency the agent is meant to spend.

### 3. Second exception — progression

A capability may be genuinely human-available and still be wrong to grant now, because the game gates it on purpose.

Factorio's gates are a curriculum. Handing an agent a mid-game capability at turn one does not produce mid-game performance; it produces an agent below the curve holding an unearned tool.

The worked instance: placing a single ghost is available from the first minute and stays. *Executing* ghosts at scale is what construction bots are for, and bots sit behind research. Emulating that executor early was a bet on uplift that measurement did not support.

**In-game progression is a design input, not an obstacle to route around.** Where the game gates something, the gate carries information about sequencing, and the burden falls on whoever wants to open it early.

---

## Part II — Who owns what

### 4. Affordance ownership

A capability is owned by whatever the human holds, looks at, or reads while performing it.

- Hand or body → **the object**. A person places a belt by *holding a belt*, so the belt places itself. Not a module verb taking a name.
- Map view → **the map surface**.
- HUD → **a tool**.

Read from the negative side: a verb earns a top-level name only if it is not always parameterized by something the agent is already holding. Most flat action modules fail this. They are filing cabinets for verbs that already have an owner.

### 5. Three surfaces, one rule each

| Surface | The human gesture | Owns |
|---|---|---|
| **Python** | The avatar, and the windows you open by clicking or hovering something on the map | Everything about map entities — place, remove, rotate, configure, inspect, transfer — and every live read of their simulated state |
| **Database** | The map screen | The map model: what exists, where, and how it is configured |
| **Tools** | HUD windows opened by hotkey, and the chrome that is always on screen | Personal crafting, research, the catalogs those screens list, and the agent's own state |

**Python is the only channel to live simulation state on map entities.** The simulation runs on its own clock; anything reflecting what it has just done to an entity arrives through Python or not at all.

The cleaving question for a new capability is not what it does but **what you were touching when you did it.** Setting a recipe on an assembler means clicking that assembler — Python. Queueing a craft by hand means opening a screen that belongs to you, not to anything on the map — a tool. These are not the same act and must not share a name: personal crafting is *hand crafting*, and that word never appears on an entity.

**Facts may live on more than one surface; verbs may not.** Inventory is readable from the agent's own state and from Python, because it is both a HUD panel and the bridge to placement. Nothing crafts in two places.

### 6. A reference answers; it does not act

There is a real read surface in the game: a thing on your cursor. Hold a belt and the world tells you a great deal before you have built anything — legal tiles, rotation, supply overlays, connection highlights.

A method belongs to a not-yet-placed reference **if and only if** a person could answer it holding the item and having placed nothing. Footprint, buildability, coverage, connection points — yes. Contents, status, network membership — no: those require the thing to exist.

**Invariant:** the reference exposes a strict read-only subset of the real object's surface, under identical names. One vocabulary with a capability gate, never a second altitude. Without this it recreates the defect it was built to remove.

---

## Part III — How much the API may infer

### 7. The inference bound

The API may infer exactly what the game infers for a human making the same gesture, and no more.

- A person dragging a belt into a cliff gets an underground pair inserted for them. The game does that unasked, as part of the gesture. We may too.
- A person dragging a belt around a corner to a distant target gets nothing. They route it themselves, leg by leg. An API that accepts waypoints and routes is a designer solving the routing problem and calling it a primitive.

This replaces a stricter rule — *the model must be able to predict the mutation set from the arguments alone* — which was right about the router and wrong about the drag. The rejection stands; the false positive is dropped, at a price paid in §8.

### 8. What arguments cannot promise, returns must

Because §7 permits calls whose effect the model cannot compute in advance, every such call reports on return: **the exact set of things it changed, the first thing that stopped it and why, and where to resume.**

This is not ergonomics. It is the only thing standing between an inferring API and an agent with false beliefs about the world. It applies wherever the outcome is not knowable up front — inferred placements, bounded waits, and every failure that crosses a surface boundary. A call that fails without saying what it already did is worse than a call that does nothing.

### 9. Waits are bounded, and the world does not stop when one ends

Any call that waits — for a walk, for a craft, for a multi-leg placement — carries a bound, and at that bound it **returns with actuals**. It does not raise as though the underlying work had stopped. The work continues; the wait ended. Those are different facts, and conflating them manufactures a false belief on purpose.

A wait must also be **well-founded**: a call that waits for something nothing is producing refuses immediately rather than burning its bound. Establishing well-foundedness may read across a surface boundary. It may never write across one.

Bounds exist so two runtimes can close a loop. They are not gameplay rules. Running out of materials and hitting an obstacle are the game's business and need no expression in the API.

---

## Part IV — Where facts live

### 10. Event-backing decides database membership

A fact enters the database if and only if something raises an event when it changes. There are exactly two write classes:

- **Load.** Charting new ground surfaces initial state. Nothing changed; we are seeing it for the first time.
- **Update.** An agent acted, or the simulation raised an event. The change has a signature, and the signature is what gets recorded.

Everything else stays out. Entity status changes constantly and silently — nothing fires when a machine runs short of ingredients — so storing it produces rows that are plausibly wrong at read time. That is worse than absent, because a stale answer still renders as an answer.

This clause replaces an earlier one that asked how volatile a fact was. Volatility is a judgment; event-backing is a fact you can go and check. Prefer the checkable form.

### 11. Volatile facts are read live, and say where they came from

Per-entity volatile state is read at call time through Python and never cached into the map model. The same holds at scale: a base-wide status read is that same read, batched. It does not become a table because there are many of them.

The map surface therefore has two halves — stable structure, and live state — and any method that can draw from either **declares which one it used**. Without that declaration the live half silently becomes a second, worse database.

Naming carries the relationship. The singular and the aggregate share a root, so a reader knows the base-wide summary is the per-entity fact seen at scale. That is what it is, and it is what a person gets by looking at their factory instead of at one machine: not a list of entities, but which problem is happening and roughly where.

### 12. Preconditions are never cached across a boundary

Actions on one surface change what is legal on another. Crafting changes what can be placed. Research changes what recipes a machine will accept. Python reads those conditions live, every time, and reports honestly when they fail. *You are not holding this* is a first-class result, not an incidental error string.

---

## Part V — How anything here is known to be true

A different kind of law: these govern belief, not design.

### 13. A claim is certified by running its check

Not by a document, a memory, a code reading, or a previous session. Certification is a pair — what was run, and against what state of the world — and anything touching that layer voids it.

This document is not exempt. It records decisions. Decisions are not evidence.

### 14. A green from an unaudited check is a rumor with a checkmark

A check can pass while testing nothing: an empty registry, a conditional assertion, an expectation derived from the same code it is checking. Ask once, per check — can it pass vacuously; does it test the real layer or a stand-in; is its ground truth built independently; does it cover the claim it is cited for.

### 15. Silence is not evidence

Empty, green, and broken render identically to a reader. Where a floor might be lying, prove it is not before building an argument on top of it.

An agent reasoning correctly from dishonest sensors reaches confident wrong conclusions. That is worse than being blocked, and it is worse for the research than a missing capability.

---

## Part VI — When the world moves

*This part is younger than the rest and written in a more exploratory register. Parts I–V were distilled from a year of arguing about what the agent may touch. This part comes from noticing, late, that nothing in the document said what a turn is — and that every harness had answered the question differently, none of them against a rule. Treat these clauses as the first honest attempt, not the settled one, and amend them by name as the checks come in.*

### 16. The turn is the third exception — and it is the medium's

A person at the keyboard cannot bound how far the world moves while they think. We can, and we must, because the channel between a model and the world has a latency that the game was never balanced for: a decision that takes a person two seconds can take a model two minutes, and a world that keeps running through those two minutes is not the same game.

So the turn is an abstraction of the same kind as walking and the map (§2): it keeps the decisions — what to look at, what to do, when to let the world run — and drops the channel artefact, which is inference latency measured in game time. **The guard from §2 applies unchanged.** The collapsed thing must be pure execution — the passage of ticks nobody is deciding about — and never a deliberation.

What the exception does *not* license: freezing the world so that it only moves when the agent asks. A world that exists only inside the agent's calls teaches that the factory is a function the agent invokes, and that is the opposite of the fact this whole environment is meant to teach.

### 17. Every tick is accounted for

Game time advances for exactly three reasons: the agent's body did something that takes time, the agent thought while the world ran, or the agent ended its turn and the world completed its horizon. Each is counted, and the agent is told the count at the start of the next turn — how much it used, how much was advanced for it, and how far the world has come.

Time that passes for a reason no one can name is time that will be blamed on the wrong thing. The treadmill lived for a year in ticks nobody had attributed.

### 18. Looking is free; acting spends attention; waiting spends the world

Three currencies, deliberately kept apart.

A read costs nothing but the moment it takes, so the agent looks before it acts and looks again after — the habit every careful agent has and every batch interface destroys. An action costs a unit of attention, of which each turn holds a bounded number; that bound is the agent's hands, and it is a human-shaped number. A wait costs world time, and **there is no free wait**: waiting inside a turn spends the same clock that ending the turn would. The agent can therefore not game *when* it waits, only *what* it waits for — and what it waits for is a question about throughput, which the game already prices.

This clause sharpens §9 rather than replacing it: a bound still returns actuals, and the clock it burned is on the ledger.

### 19. The turn's horizon is a reward, and a declared one

How much world time a turn contains is not a constant. It grows as the base becomes able to run unattended, because that is what changes across a game: not the speed of the world but how long a person can afford to watch instead of do.

Whatever sets the horizon is therefore shaping the agent toward automation, and shaping that the agent cannot see is a confound dressed as a mechanic. So the horizon is stated before the turn and explained after it, in terms of the things that set it. Those things must be things the game itself prices — progression earned with real production, and production that came from machines rather than hands — never counts of things merely placed or merely unlocked. The constants that turn those inputs into a number are an experimental condition, held in the record of the run, and are not a game rule the agent is owed.

The score and the horizon are computed separately and named separately. Where they share a definition, comparisons across runs hold only under the same horizon, and that is said rather than assumed.

### 20. Nothing of the agent lingers past the turn

When a call returns, the body is idle: the walk finished, the mining stopped, the placement landed or failed. When a turn ends, nothing the agent's body began is still in flight.

The world's own processes are not the agent's, and they do not stop: machines run, research progresses, the personal crafting queue drains. That asymmetry is the lesson, not a leak — the agent is one actor in a world that has its own momentum — and any mechanism that pauses one world process at the turn boundary to make a scoring problem go away teaches the agent exactly which process is special. Scoring problems are solved in the score.

### 21. The report is the observation

What the agent sees at the start of a turn is what changed over the horizon it just let pass: what was produced and by what means, what appeared and what disappeared, what is now unhappy that was happy, what finished that it did not itself finish, and every event that fired, in order, with no gaps unannounced. Delivered in the agent's context, by the harness, before the agent is asked for anything.

This is the between-turn channel the rest of the document keeps referring to. It is the same object a planning phase reads, which is why a planning phase is a kind of turn and not a second mechanism. And it is the one thing a harness may not deliver by any route other than the agent's own input: a result the agent must go and fetch is a result the record cannot prove it saw.

---

## Part VII — Deliberately unaddressed

Named so that silence is not mistaken for coverage.

- **Multi-agent.** Agents as entities; inspection and transfer between friendly forces; ghosts as a shared record of intent. Real, coming, undecided. Under Part VI, turns become rounds — every agent submits, the world advances once — and the horizon becomes a shared quantity; both recorded, neither designed. When it is taken up: direct peer inventory access has no vanilla analog, while shared containers and dropped items do.
- **Alerts.** A separate engine mechanism from entity status, concerned mostly with hazards this scope does not yet contain. It becomes meaningful alongside bots, and alongside anything that can destroy what has been built.
- **Blueprints.** The game's own compiled-skill artifact, and the honest successor to anything that wants to package a layout. Gated by §3, like bots.

---

## Amendment

Clauses are superseded by name, in writing, with the reasoning that displaced them. Nothing here decays quietly. If a clause is wrong, replace it and say what changed.
