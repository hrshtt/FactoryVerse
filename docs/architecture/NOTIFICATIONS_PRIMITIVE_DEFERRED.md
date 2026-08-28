# Notifications as a designed primitive — deferred

**Status: DEFERRED — designed, not executed.** The finding and the inherited scope below are unchanged. §*The design* was added after a full read of every send site in both emitting mods, the Python receive side, and the world lifecycle; it names running values and the gates that stand before any of it is believed. Nothing in it has been run.

> **Amendment 2026-08-29.** Audit corrections applied inline (marked *corrected*). Two consequences of decisions taken elsewhere: the `turn` stream's one reader is **the turn** — the orchestrator's report assembly (`TURN_CONTRACT_DEFERRED.md` §4) — since hand crafting and research stay in Python and no HUD tool consumes completions; and with the external transports removed, the actor session is no longer a competing drainer, which leaves the orchestrator and agent code as the two that remain to be reduced to one. The vocabulary file's correction is being applied in code by a sibling change: it must carry the **wire `event_type` strings**, not constructor or field names.

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

Bycatch: the wire carries more event types than anyone consumes. Several payload constructors in `udp_payloads.lua` are never called. *Corrected 2026-08-28:* `file_created` is **never emitted** — the six sites in `Map.lua` set an `event_type` field on `write_queue` items that the write loop (`Map.lua:1663-1700`) never reads — so no datagram and no warning exist; it is dead in a different way. Two more live instances of the same accretion: `snapshot_state` and `chunk_charted` are emitted with no subscriber, and Python subscribes to `ghost_operation` (`sync.py:119`) which nothing emits — ghosts ride `entity_operation` with `is_ghost = true`. Accretion signature, not design.

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

## The design

### What the audit found, in one paragraph each

**The agent mod.** One `helpers.send_udp` (`utils/udp.lua:47`) reached two ways: body actions push onto `agent.message_queue[category]` and are flushed every `on_tick` in `pairs()` order (`Agents.lua:299-357`); research and crafting notifications send *immediately inside the engine handler* (`Notifications.lua:17-34`). Both go to the same per-agent port. No sequence field exists in the mod. A craft completion therefore leaves twice on one port under two envelopes, the immediate one first. `place_entity` and all eight entity-ops emits send `status: null`. `Agent:destroy()` drops the queue unflushed. Research enqueue/dequeue emit nothing. `send_udp`'s return is never read; nothing bounds datagram size.

**The snapshot mod.** One `send_udp` (`snapshot.lua:669`), two counters: `storage.snapshot_sequence` (base 1, stamped into file lines) and `storage.udp_sequence` (base 0, stamped onto `file_io`/event datagrams that have no file counterpart). Entity datagrams stay in step with the file only by an explicit `payload.sequence = operation.sequence` at **eleven** sites — ten in `Entities.lua` and one in `Resource.lua:310` (*corrected 2026-08-28*). Neither counter is ever reset — `on_configuration_changed` wipes the files and keeps the counters. No remote call exposes either. Every send is coded after its write. A remote `set_udp_port` shadows the mod setting in `storage` with no way back.

**Python.** Binds one dispatcher per agent port and one on the snapshot port. Learns its sequence baseline by replaying files on disk, never by asking Lua. `_check_sequence` accepts any first value when its own counter is 0 (`sync.py:262-293`), so loss between attach and first datagram cannot be detected. Forgets an action on timeout and drops its late completion. Nothing sends UDP toward Factorio; the `--enable-lua-udp` argument is a flag value, not a port anyone binds.

**Lifecycle.** `storage` survives everything but `on_init`. Hot reload is `game.reload_script()` over RCON → `on_load` only, with no Python hook. There is no world identifier on either side; resume parity is a tick check and an entity digest, and the recorded `last_sequence` is not compared.

In one line: *write, then send, fire-and-forget, with a sequence bolted onto one stream by convention, and a receiver that reconstructs the counter from disk and trusts whatever arrives first.*

### The unit

One Lua file, `stream.lua`, with no side effects at load: no `storage`, no `script.*`, no `remote.*` at module level. Each owner mod requires it and hands it a slot in its own `storage`, so two mods get two implementations and two counters — the only shape per-mod `storage` allows. It owns **tracking only**: port, epoch, sequence, tick, event_type. `data` passes through untouched, and the per-type payload constructors stay beside the handlers that know their fields.

| Function | When the owner calls it | What it does |
|---|---|---|
| `open(slot, port_source, vocabulary, file)` | `on_init` and `on_load` | Binds a stream to its counter slot, its port (a setting name for mod-wide streams, a number for per-agent ones), the legal `event_type` set, and its file. Initialises `{epoch=0, seq=0}` if absent. |
| `emit(stream, event_type, data)` | anywhere in a handler | Rejects an `event_type` not in the vocabulary; appends to a this-tick buffer that never touches `storage`. Never sends. |
| `flush(stream)` | once per tick, from `on_tick` | Stamps epoch, sequence, tick on each buffered item in emit order; **one** `write_file` append per stream per tick; then one datagram per item. An item over the datagram ceiling goes out as envelope-only with `in_file=true`; the file has the record. |
| `new_epoch(stream)` | `on_init` and `on_configuration_changed` — the two places files are cleared; **never** `on_load` | Epoch +1, sequence 0, file truncated. Counter and file reset together. |
| `state(stream)` | exposed by the owner over remote | `{port, epoch, seq, tick}` — what Python asks for at attach and after any gap. |

Envelope on the wire: `{"epoch":1,"seq":4382,"tick":36480,"event_type":"crafting_finished","data":{…}}`. On per-agent streams the port already names the agent; `agent_id` moves into `data`.

Rules the unit enforces that today are conventions or absent: send-after-write; one flush order per port; one blocking write per port per tick; the file line and the datagram are the same envelope, stamped once; a sequence never exists without an epoch.

### Streams — one per reader

| Owner | Stream | Reader | Cadence | Slot |
|---|---|---|---|---|
| `fv_embodied_agent` | `action` | the action listener, per call, correlated by `action_id` | per tick | `storage.agents[id].streams.action` |
| `fv_embodied_agent` | `turn` | the event queue → the turn report | per turn | `storage.agents[id].streams.turn` |
| `fv_snapshot` | `entities` | the sync service, continuous, rebuilds on gap | per tick | `storage.streams.entities` |
| `fv_snapshot` | `files` | the sync service's file re-read path | seconds | `storage.streams.files` |

Splitting the agent port into `action` and `turn` is what removes the crafting inversion: two readers, two orders, each self-contained.

### Running values

Ports keep every base and stride `config.py` already has; two bases are added.

| Stream | Server N, agent i | Client | Port source |
|---|---|---|---|
| `action` | `34202 + N·10 + i` (unchanged) | `34202 + i` | `create_agent(action_port=…)` |
| `turn` | `34300 + N·10 + i` | `34300 + i` | `create_agent(turn_port=…)` |
| `entities` | `34400 + N` (unchanged) | `34500` | setting `fv-snapshot-entities-port` |
| `files` | `34600 + N` | `34700` | setting `fv-snapshot-files-port` |

The socat sidecar forwards the two new ranges. `fv-snapshot-udp-port` becomes `fv-snapshot-entities-port`; the `storage.snapshot_udp_port` override is deleted and the remote `set_port` writes the setting instead (gate 2).

Files, under `script-output/`: `factoryverse/agent-snapshots/<id>/action.jsonl`, `…/turn.jsonl`, `factoryverse/snapshots/entities.jsonl`, `factoryverse/snapshots/files.jsonl`. The `-init.jsonl` files are untouched — they are the load class. The one real migration is `entities`: today's update log is per chunk; one stream file carries the chunk inside `data` and the loader groups on it (gate 3).

Epoch: fresh world → `(epoch=1, seq=0)` after `on_init`; each `on_configuration_changed` → +1; `on_load` never moves it. An `epoch=0` on the wire means an owner forgot `new_epoch` — checkable.

Vocabulary: one Lua file returning a flat table with no code in it, required by both mods and parsed by Python. Every name in it must be the string that goes on the wire as `event_type` — *corrected 2026-08-29:* the first draft of `vocabulary.lua` listed constructor names (`entity_created`) and `action` field values (`walk_to`) where the wire carries `entity_operation` with `op`, and `action` with `action_type`; and it named `resource_destroyed`, which is on no wire. The corrected file carries wire strings, and the two deliberate changes are stated as changes rather than as things that already exist: `ghost_*` replaces the `is_ghost` flag, and `status` becomes mandatory in `data` on the `action` stream. The dead names (`started`, `progress`, the five `action_*` constructors, `file_created`) are absent.

```
action:     walk_to mine_resource craft_enqueue craft_dequeue place_entity pickup_entity
            rotate_entity set_entity_recipe set_entity_filter set_inventory_limit
            get_inventory_item put_inventory_item        (data.status ∈ status)
turn:       research_queued research_started research_finished research_cancelled
            research_moved research_reversed crafting_finished
entities:   entity_created entity_destroyed entity_rotated entity_configuration_changed
            ghost_created ghost_destroyed ghost_rotated ghost_configuration_changed
            resource_destroyed chunk_init_complete snapshot_state system_phase_changed chunk_charted
files:      file_written file_appended                    (data.file_type ∈ file_types)
file_types: resource water trees_rocks power_statistics power_networks entity_status
            agent_production_statistics agent_crafting_statistics agent_mining_statistics
status:     queued completed cancelled failed
```

### The Python mirror

Smaller than what exists. Per port: hold `(epoch, seq)`. At attach, call `state()` over RCON and adopt it — the accept-anything-first rule goes away. Accept a datagram iff the epoch matches and the sequence is next. On a gap, read the stream file from `seq+1` — that is the "no gaps unannounced" of Constitution §21, now enforceable. On an epoch change, rebuild. A completion arriving for an action Python has already timed out is recorded at its sequence rather than dropped — the §9 evidence the craft-timeout incident lacked. The `turn` stream is drained by the turn only; the queue that today is drained by whoever gets there first becomes the turn report's Events section, per the Turn Contract.

### What this folds away

`Agents.lua process_agent_messages` and the per-category queue; `Notifications.lua`'s direct send and inline envelope; `udp.lua`'s sender and `create_action_payload`; `udp_payloads.lua`'s `add_sequence` and the five dead `action_*` constructors; `snapshot.lua`'s `get_next_sequence`, both counters, and the four dead `send_*` functions; the ten `payload.sequence = operation.sequence` sites; `storage.snapshot_udp_port`.

### Gates — before any of it is believed

Numbered so the ledger can name them. The first three are facts about the engine, not about this code, and stand before the first line of `stream.lua`.

1. **Datagram ceiling.** Measure the largest `helpers.send_udp` payload that arrives intact on the dedicated-server image and on the client, through socat and direct. The oversize rule's threshold is that number, not a guess.
2. **Settings are script-writable at runtime.** `settings.global[name] = {value = …}` from a remote call on 2.0.76, read back on the next send. If not, per-mod ports go to `storage` with a documented unset, and the settings story shrinks.
3. **The loader survives one file per stream.** `SnapshotLoader.replay_updates` groups by `data.chunk` instead of by directory, and the `chunk_meta` stale guard still holds. A unit test with two chunks in one file.
4. **Two owners, two counters.** Both mods require `stream.lua`; each advances its own slot; a save/load round-trip preserves both independently; a `game.reload_script()` moves neither epoch. One check, three lifecycle facts.
5. **Vocabulary parity.** A unit test reads the vocabulary file and asserts the typed layer's dispatch table, the listener's terminal set, and the sync service's **subscription list** are exactly its sets. *2026-08-28:* a first version exists as three strict `xfail`s (turn types, listener statuses, sync file types) plus one structural test — the third leg tests the file-type filter, not the subscription list, and must be added; and "red" is encoded as a strict xfail latch, which is acceptable only while the file itself is honest (see the vocabulary correction above).
6. **The inversion is gone.** Enqueue a craft, walk; the `turn` stream shows `crafting_finished` at a sequence, the `action` stream shows `completed` at a sequence, and neither port carries the other's type.
7. **Loss is announced.** Drop one datagram (kill socat for a tick, or filter by sequence in the test dispatcher); the next turn report names the gap and the missing line is read from the file. This is the check the whole plan exists for.
8. **Attach is honest.** Start Python against a running world with `seq=N>0`; the first accepted datagram is `N+1`, and a datagram at `N+5` is a gap, not a baseline.

### Order of work

Vocabulary file and gate 5 first — they need none of the engine facts and turn this document's opening table from a claim into a check. (Started 2026-08-28; the file's header overclaimed and is being corrected — see the vocabulary paragraph above.) Then gates 1–3 as probes, not code. Then `stream.lua` behind the `turn` stream only, because that is the dependent the HUD partition and `await_item` are waiting on and the smallest blast radius. `action` next, which deletes the message queue. `entities` and `files` last, because the loader migration is theirs.

## The shared utility mod — from open thread to workstream

Recorded at the time of deferral as a hunch: *"the utility-oriented code blocks and library-style primitives should probably live in a separate utility mod that the other three mods share."* This section replaces that hunch with a census, the engine facts that constrain any sharing mechanism, and what those facts force. It does **not** decide the vehicle; it narrows the choice to two and says what would settle it.

### Why it sits on the notification path

The notification primitive needs exactly one of each: a payload envelope, a vocabulary, a sequence stamp, a sender, and a landing zone. Today every one of those exists **twice**, once per emitting mod, with the agent-facing copy being the thinner one:

| | `fv_embodied_agent` | `fv_snapshot` |
|---|---|---|
| Sender | `utils/udp.lua` — declared in its own header a *subset of snapshot.lua* | `utils/snapshot.lua` `send_udp_notification` |
| Payload factory | `udp.create_action_payload` | `utils/udp_payloads.lua` — whose five `action_*` constructors are **never called**; the agent mod builds its own |
| Sequence | none | **two** counters: `storage.udp_sequence` (payload module) and `storage.snapshot_sequence` (JSONL log), reconciled by "stamp only if absent" |
| Port resolution | per-agent `agent.udp_port`, fallback constant | mod setting `fv-snapshot-udp-port`, overridable by remote |
| Landing zone | in-memory Python queue | `script-output` JSONL + DuckDB |

Building the primitive inside either mod reproduces this split for a third channel. So the sharing question is not adjacent to the notification design — it is the first thing the design has to answer, and the primitive is the first shared thing, or the proof that a shared thing is unnecessary.

### Census — what is actually duplicated

| Unit | Copies | State | Note |
|---|---|---|---|
| `utils/Error.lua` | embodied, snapshot | byte-identical | The file has **no `return` statement**; `require("utils.Error")` yields `true`. Its three requirers in snapshot alias the result as `GameStateError` and never call it. Present in two mods, required in one, called by none (*corrected 2026-08-28*; `fv_placement_hints` has no copy) — delete, don't share. |
| `utils/utils.lua` | embodied, snapshot | near-copy, 24 shared function names | Differs in two places only: a spectator toggle, and how `validate_recipe`/`validate_technology` resolve an agent's force — embodied reads its own `storage.agent_forces`; snapshot hops through `remote.call("agent","list_agents")`. That difference is the whole reason the copy exists (see engine fact 2). |
| UDP send path | `udp.lua` vs `snapshot.lua` | subset by stated intent | Both wrap `helpers.send_udp`; neither validates size; neither stamps a sequence at the send site. |
| Action payload constructors | `udp.lua` (live) vs `udp_payloads.lua` (dead) | drifted | Two definitions of the same wire type, one unused. |
| Event aggregator in `control.lua` | embodied (~60 lines), snapshot (~110 lines) | copy with one extra bucket | Same `get_events()` → aggregate → register-once dispatcher; snapshot's adds a `custom_events` bucket. |
| Lifecycle boilerplate | all three `control.lua` | copy | `on_init` / `on_load` / `on_configuration_changed`, each re-registering remote interfaces and events, each carrying the same "storage is read-only in on_load" comment. |
| `utils/serialize.lua` | embodied only | **already shared** | `fv_snapshot/game_state/Entities.lua` does `require("__fv_embodied_agent__/utils/serialize")`. This is the existence proof that cross-mod code sharing works in this tree, on this engine version. |
| `utils/custom_events.lua` | embodied only | shared by **value** | Event IDs generated at load in embodied, copied into `storage.custom_events`, served over the `custom_events` remote interface; snapshot subscribes to the served numbers. |
| `game_state/EntityInterface.lua` | embodied only | shared by **require — wrongly** | See the defect below. |
| Geometry / position helpers | `utils.lua` (both), `fv_placement_hints/utils/geometry.lua` | overlapping, not identical | `min_position`, `extract_position`, `to_chunk_coordinates` vs `distance`, `snap_to_tile_center`, `bbox_*`. Three vocabularies for one domain. |
| Force resolution | `snapshot/utils/forces.lua`, `embodied Agents.list_agent_forces` | two entry points, one fact | |
| `ParamSpec.lua` | embodied only | not duplicated | Listed because the plan's table cites it as the RCON schema mechanism; it is a per-call validator, not a shared vocabulary. |

`fv_placement_hints` declares no dependency on either other mod and shares nothing with them.

### A defect the census surfaced — and why it is the argument

`EntityInterface.lua` calls `script.generate_event_name()` twice at module load. `fv_snapshot` requires that file across the mod boundary, so the file executes a second time in snapshot's Lua state and generates two **more** IDs. The client log shows it plainly: embodied gets `241`/`242`, snapshot's copy gets `243`/`244`. Embodied raises on 241/242; snapshot subscribes on 243/244. Those two subscriptions have never fired.

The database is not missing rotations because of it — `entity_ops.lua` also raises the *remote-shared* `on_agent_entity_rotated` / `on_agent_entity_configuration_changed`, and snapshot subscribes to those by served value — but the dead pair is a clean demonstration of the one rule that governs this whole workstream:

> **Cross-mod `require` shares an implementation, never an instance.** Anything a shared module does at load time, and anything it keeps in `storage`, happens separately in every mod that requires it.

A shared sequence counter written naively into a shared module is this bug again, with loss detection as the casualty instead of a rotation.

### Engine facts that constrain the vehicle (Factorio 2.0.76, verified)

1. **Cross-mod require exists and is load-time only.** `require("__mod-name__.file")` — the docs give the dot form; the tree's slash form also resolves. *"require() can not be used in the console, in event listeners or during a remote.call()."* Whatever is shared is required at the top of `control.lua`, or not at all. The plan's earlier line — *mods cannot `require()` across mod boundaries at runtime* — was true only in the "not inside handlers" sense and is corrected here.
2. **Each mod has its own Lua state and its own `storage`.** The requirer's globals, the requirer's `storage`, the requirer's `script` object. This is why `utils.lua` forked: the same function needs `storage.agent_forces` in one mod and a `remote.call` in the other. A library can carry the *code*; it cannot carry the *fact*.
3. **`remote.call` is the only runtime cross-mod hop.** Arguments are copied, metatables dropped, functions refused, LuaObject references kept. It costs a copy per call and runs synchronously inside the caller's tick.
4. **Custom event IDs are engine-global integers.** Generated at load by whichever mod calls `generate_event_name`, they can be raised by any mod that knows the number. Sharing the number (as `custom_events.lua` does via storage + remote) is correct; sharing the *generator* (as the `EntityInterface` require does) is the defect above.
5. **`storage` is not writable in `on_load`.** A durable counter is initialised in `on_init` / `on_configuration_changed` and advanced in handlers.
6. **Mods freeze after load.** A fourth mod is a full restart to pick up, like any mod change, and `--dump-data` force-loads it.

### What the facts force, before any vehicle is chosen

- **Sequence spaces are per emitting mod, by construction.** Because `storage` is per mod, a single global notification sequence would need a single owner mod that every other mod stamps through by `remote.call` on every send. That is possible but buys nothing: Python detects loss per stream anyway, and the snapshot channel already runs two spaces. The honest shape is one counter per (mod, stream), declared as such on the wire. Recorded as a forced fact, not a preference.
- **The vocabulary is data, not code.** A list of notification types that Lua stamps and Python parses must live in one file that both sides read. A shared Lua module solves the Lua half only; the Python half is a test that reads the same file. Nothing in the census does this today for any channel — the "schema declared once" column in this plan's opening table is a claim about Lua-side constants, not about a Lua↔Python contract.
- **The library must be side-effect-free at load.** No `generate_event_name`, no `storage` touches, no `remote.add_interface` at module level. Anything stateful takes the owning mod's `storage` table as an argument.
- **The stated prior reason survives.** `udp.lua`'s header says the copy exists so the agent mod need not depend on the snapshot mod. A shared core that both depend on — and neither on the other — honours that reason rather than overturning it. The plan's earlier framing (undoing a deliberate choice) was too strong.

### Two vehicles, and what separates them

**A. A fourth mod, `fv_core`** — a pure library: `info.json`, no `control.lua` handlers of its own, a dependency of all three, required as `__fv_core__.…`. Cleanest ownership; the same restart cost as any mod change; touches four Python sites (`factoryverse_server_mod_list`, `_copy_mod` sequence, the client setup list, the `config.py` mod-dir properties) and the DLC-pruned `--dump-data` path.

**B. `fv_embodied_agent` as the de facto core** — it is already the mod `fv_snapshot` depends on and already the source of the one working cross-mod require. Zero infra change; but the agent mod then owns library code it does not use, and `fv_placement_hints` would acquire a dependency on the agent mod to share geometry.

What separates them is not taste: it is whether the notification primitive needs **its own handlers** (an `on_init` to seed counters, an `on_configuration_changed` to migrate them). If it does, it is a mod, not a library, and A is the only honest home. If the primitive is a library whose state lives in each caller's `storage`, B is sufficient and A is overhead. That question is answered by the sequence-space fact above — **per-mod state, therefore library** — which leans B for the *primitive* while leaving A open for the *deduplication*. Not decided here.

### What it would take to believe

1. `require("__fv_core__.x")` (or the B-form) resolves on both the client launch and the dedicated-server image, in `control.lua` of each mod — a log line per mod, on both.
2. Two mods require the same module and each advance a counter in their own `storage`; a save/load round-trip preserves both, independently. Proves fact 2 and the per-mod sequence shape in one check.
3. The `EntityInterface` require in snapshot is replaced by the served-value route (or the raise sites are), and the client log shows exactly one `Generated custom event` pair per ID. This is the first row of the ledger for this workstream because it is red today.
4. A unit test reads the shared vocabulary file and asserts Python's typed layer and Lua's constants are the same set. No such test exists for any channel; this plan's opening table would fail it for the two channels it marks ✅.
5. `Error.lua` deleted from both mods, no behaviour change — a vacuity check on the census itself.

## Answered here, and still open

Answered by the design above, each traceable to an audit fact: what a notification *is* (an envelope on a stream, tracking owned by the unit, payload by the emitter); how its vocabulary is declared (one data file, both sides); where it lands (a per-stream file, then the turn report); what loss means (a sequence gap within an epoch, filled from the file); who consumes (one reader per port; the turn drains `turn`); which engine events belong (only those already on the wire, split by reader); what it takes to believe it (gates 1–8).

Still open:

- **The vehicle.** Library in the agent mod, or a fourth mod — narrowed in the next section, not decided. The unit is written so the move is mechanical either way.
- **Force fan-out.** Research events go to every agent on the force as separate datagrams on separate `turn` ports. That is correct for readers; whether the *file* should be per force rather than per agent is a multi-agent question and waits for it.
- **Whether `files` should exist at all.** Its datagrams are hints to re-read a file that is itself the record. If the sync service polled those files on its own cadence, the stream would be unnecessary. Kept because it is what exists today; cheap to delete once gates 1–8 are green.

## Where this lives

| What | Where |
|---|---|
| Lua emit side | `src/fv_embodied_agent/game_state/Notifications.lua` (immediate send, `:17-34`); `src/fv_embodied_agent/game_state/Agents.lua` (per-tick flush, `:299-357`) |
| Snapshot counters | `src/fv_snapshot/utils/snapshot.lua` `:82-91`; `src/fv_snapshot/utils/udp_payloads.lua` `:374-387`; the ten override sites in `game_state/Entities.lua` |
| Python baseline from disk, accept-first rule | `src/FactoryVerse/game/agent/remote_view.py` `:256, :298-303`; `src/FactoryVerse/game/infra/duckdb/sync.py` `_check_sequence` |
| Port map | `src/FactoryVerse/environment/config.py` `get_agent_port`, `get_snapshot_port`; `infra/docker/factorio_server_manager.py` `_build_udp_forwarder_config` |
| Lua UDP transport | `src/fv_embodied_agent/utils/udp.lua`; `src/fv_snapshot/utils/udp_payloads.lua` |
| Python receive and queue | `src/FactoryVerse/game/agent/infra/async_listener.py` |
| Shared dispatcher | `src/FactoryVerse/infra/udp_dispatcher.py` |
| Typed presentation layer | `src/FactoryVerse/game/agent/event_stream.py` |
| Namespace wiring | `src/FactoryVerse/environment/tiers/tier4_runtime.py` |
| Contrast — a state channel with sequence and rebuild | `src/FactoryVerse/game/infra/duckdb/sync.py` |
| The one working cross-mod require | `src/fv_snapshot/game_state/Entities.lua` (`serialize`) |
| The dead cross-mod require (duplicate event IDs) | same file, the `EntityInterface` require; IDs generated in `src/fv_embodied_agent/game_state/EntityInterface.lua` |
| Event IDs shared by value | `src/fv_embodied_agent/utils/custom_events.lua`; the `custom_events` remote interface |
| Duplicated aggregator and lifecycle boilerplate | each mod's `control.lua` |
| Python sites a fourth mod would touch | `infra/docker/factorio_server_manager.py` (`factoryverse_server_mod_list`, `_copy_mod`); `infra/factorio_client_setup.py`; `environment/config.py` mod-dir properties |
| Delivery into model context (between inferences today, `:505`; the actor session was removed 2026-08-29) | `src/FactoryVerse/infra/llm/orchestrator.py` |
| The dead `ghost_operation` subscription | `src/FactoryVerse/game/infra/duckdb/sync.py` |
| Prompt prose describing notifications | `docs/system-prompt/factoryverse-system-prompt-v3-template.md` |

## Related plans

- `HUD_PARTITION_DEFERRED_REFACTOR.md` — the origin of this document, and its first dependent.
- `API_AFFORDANCE_REDESIGN_DEFERRED.md` — owns `inventory.await_item`, the second dependent, and deletes the `events` accessor outright.
- `TURN_CONTRACT_DEFERRED.md` — the `turn` stream's only reader; its report's Events section is where a gap is announced.
