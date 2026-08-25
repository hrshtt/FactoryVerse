# Notifications as a designed primitive — deferred

**Status: DEFERRED — placeholder. No design exists yet, and none is proposed here.**

Notifications will be designed as a first-class primitive. Nothing about *how* is decided. This document records the decision, the evidence that motivated it, the scope the channel has already inherited from other plans, and the one open thread — so the work can be picked up cold.

## The finding

Four transport channels run between the mods and Python. Three carry a full infrastructure stack. Notifications carry a good presentation layer over a bare datagram.

| | RCON calls | Snapshot state → DuckDB | Action completion | **Notifications** |
|---|---|---|---|---|
| Schema declared once, shared by both sides | ✅ `ParamSpec.lua` | ✅ `udp_payloads.lua` constants | ✅ `ACTION_STATUS` | ❌ type strings hardcoded independently in Lua and in Python |
| An enumeration of valid members | ✅ | ✅ subscription table | ✅ status enum | ❌ no list of valid notification types exists anywhere |
| Durable landing zone | n/a | ✅ DuckDB + JSONL | ✅ correlated result | ❌ an unbounded in-memory queue, destructively drained |
| **Loss detection** | TCP | ✅ sequence gap triggers rebuild | ✅ await timeout | ❌ **none.** The payload carries no sequence; a dropped datagram is silently and permanently lost |
| Fan-out to multiple consumers | ✅ | ✅ dispatcher | ✅ | ❌ one queue, first-drainer-wins |
| Reaches the agent by a designed route | ✅ | ✅ | ✅ | ❌ the only agent-facing surface was an undocumented namespace accessor, now deleted (see below) |

What notifications *do* have — and why the gap is easy to miss — is a genuinely well-built typed layer on top: `GameEvent` and its subclasses with `drain()` / `wait_for()` / `subscribe()`, a named runtime module, delivery into model context through the orchestrator, and prose in the system prompt describing it. **The layer that is missing is underneath it, not above it.**

**How this channel reaches the agent is settled, and it is not through a namespace accessor.** The stream was also exposed to agent code as `events`; the API plan deletes that. Notifications arrive **between turns** — the model receives them the way a person notices the HUD change — and `EventStream` stays as infrastructure the orchestrator drains and injects. Whatever this primitive becomes, **it does not get an agent-facing subscription API**, because there is no gesture that corresponds to subscribing to a channel.

Three consequences visible in the current tree. Recorded as evidence, **not** as a problem statement to design against:

1. **Silent loss is undetectable and unrecoverable.** Every other channel can report that it dropped something. A lost research completion simply never happened.
2. **Competing consumers race.** `EventStream.drain()` is destructive over one shared queue. The orchestrator, the actor session, and agent code can each drain it; whoever drains first wins, and there is no retention to arbitrate.
3. **Coverage is a fraction of what the mods already observe.** `Notifications.lua` registers six research events and one crafting event. `fv_snapshot` already observes entities being built, destroyed, rotated and reconfigured — those become *state* in the database and never surface as agent-perceptible *events*. The file's own docstring says "Entity lifecycle events (future)."

Bycatch: the wire carries more event types than anyone consumes. Several payload constructors in `udp_payloads.lua` are never called, and `file_created` is emitted repeatedly from the snapshot mod with zero subscribers. Because the listener subscribes to everything, each arrival logs an unknown-type warning. Accretion signature, not design.

## The scope this channel has already inherited

Constraints the design must accommodate. **None of them is a design decision.**

**It carries completions.** Action completions, plus the crafting and research completions that the HUD Partition depends on. That is the whole payload class for now.

**Status does not ride it.** Entity status is a pull-based read — per-entity through Python, base-wide as the same read batched. It lands on disk and is read on demand. It rides nothing.

**No alert slot.** An earlier draft reserved one, on a conflation of alerts with entity status. They are separate engine mechanisms, and after `fv_filters.yaml` almost nothing in the alert vocabulary applies to this scope. Alert work is withdrawn until bots exist — at which point construction failures and destroyed entities make the surface meaningful, and this channel is where they would land. The note is kept for then; nothing is reserved now.

## Two dependents, and why the design matters

**The HUD Partition depends on it.** That plan is what motivated opening this document: wanting crafting and research as discrete tools rather than blocking calls is what surfaced the need for this channel to be a designed primitive. The partition ships no `craft_await`, so its entire join story rests on completions arriving as between-turn events. Its first gate — *does the interaction layer actually inject notifications between turns?* — is a question about **this channel**, not about crafting.

**`inventory.await_item` depends on it more sharply.** The bounded wait that bridges Python to the crafting queue is only as honest as the completion signal underneath it.

`docs/CONSTITUTION.md` §9 forbids the failure mode outright: *a bound returns actuals and never raises as though the underlying work had stopped.* The current tree does exactly what §9 forbids — a craft timeout has no cancel path, so the craft completes in the world while Python reports failure. Belief divergence by construction.

Today §9 is aspirational on this channel, because a channel with no sequence number and no loss detection cannot enforce it: a dropped datagram means the wait ends, the craft finishes, and nothing ever reconciles the two. **Turning §9 from aspiration into enforcement is what this primitive is for.**

Whether the notification work must land before either dependent is **not decided here.**

## Open thread — a shared utility mod

Recorded at the time of deferral, **not yet validated or scoped**:

> The utility-oriented code blocks and library-style primitives should probably live in a separate utility mod that the other three mods share, rather than being re-implemented per mod. It may help us move faster.

Whether this is the right vehicle for the notification primitive is **open**. Three facts bear on it; none settles it.

- `src/fv_embodied_agent/utils/Error.lua` and `src/fv_snapshot/utils/Error.lua` are byte-identical.
- `utils.lua` exists in both mods, sharing most function names with a meaningful set of differing lines — a near-copy that has already drifted.
- `src/fv_embodied_agent/utils/udp.lua` says in its own header that it is a *"subset of snapshot.lua focused on UDP functionality"*, so `fv_embodied_agent` can use UDP without depending on the full snapshot module. The duplication was a deliberate dependency-avoidance choice. Undoing it means overturning a stated prior reason, not cleaning up an oversight.

Constraint to carry in: mods cannot `require()` across mod boundaries at runtime, and RCON executes in scenario context rather than mod context. Any sharing mechanism has to survive both.

## Unanswered — bring answers, not assumptions

Listed so the next session knows what was *not* decided. No candidate answers are recorded, on purpose.

- What a notification *is* at the contract level, and how its vocabulary is declared.
- Where notifications land, and whether they are retained.
- What loss means on this channel, and whether it must be detectable.
- Who may consume, and what happens with more than one consumer. Agent code is no longer a candidate; the orchestrator and the actor session both still are, and today they race.
- Which of the engine events the mods already observe belong on this channel.
- Whether the primitive lives in a shared utility mod, and whether that mod should exist at all.
- What it would take to believe the channel works.

## Where this lives

| What | Where |
|---|---|
| Lua emit side | `src/fv_embodied_agent/game_state/Notifications.lua` |
| Lua UDP transport | `src/fv_embodied_agent/utils/udp.lua`; `src/fv_snapshot/utils/udp_payloads.lua` |
| Python receive and queue | `src/FactoryVerse/game/agent/infra/async_listener.py` |
| Shared dispatcher | `src/FactoryVerse/infra/udp_dispatcher.py` |
| Typed presentation layer | `src/FactoryVerse/game/agent/event_stream.py` |
| Namespace wiring | `src/FactoryVerse/environment/tiers/tier4_runtime.py` |
| Contrast — a state channel with sequence and rebuild | `src/FactoryVerse/game/infra/duckdb/sync.py` |
| Delivery into model context | `src/FactoryVerse/infra/llm/orchestrator.py`; `src/FactoryVerse/evals/freeplay/actor_session.py` |
| Prompt prose describing notifications | `docs/system-prompt/factoryverse-system-prompt-v3-template.md` |

## Related plans

- `HUD_PARTITION_DEFERRED_REFACTOR.md` — the origin of this document, and its first dependent.
- `API_AFFORDANCE_REDESIGN_DEFERRED.md` — owns `inventory.await_item`, the second dependent, and deletes the `events` accessor outright.
