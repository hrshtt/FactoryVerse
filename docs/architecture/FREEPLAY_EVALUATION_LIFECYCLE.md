# Freeplay Evaluation Lifecycle

**Status:** Launchable freeplay vertical slice; live-certified  
**Date:** 2026-08-06  
**Scope:** Single-agent freeplay campaigns on dedicated Factorio server instances  
**Deferred:** Lab-grid episodes, puzzle tasks, cooperative/competitive multi-agent runs

## Purpose

FactoryVerse freeplay evaluation measures how a coding agent builds and operates a
long-lived Factorio factory. A freeplay evaluation is not a short task episode and
cannot be represented by one model turn loop. It is a **campaign** that persists
Factorio state across multiple bounded runtime sessions.

The coding harness owns the agent's planning memory and reusable code. FactoryVerse
owns the game environment, the embodied Python interface, checkpoints, independent
state measurement, artifacts, and lifecycle truth.

The implementation must preserve the research action space:

- the agent writes Python in a persistent runtime;
- the Python runtime exposes embodied action interfaces and Factory Objects;
- DuckDB provides map-scale perception;
- reach, position, inventory, game time, and placement rules remain enforced;
- production agents cannot access raw RCON or administrative mutation interfaces.

MCP is not a prerequisite. If it returns, it may transport runtime execution but
does not own the campaign or evaluation lifecycle.

## Decisions

1. **One freeplay campaign owns one dedicated Factorio server instance.** No other
   evaluation agent shares that instance.
2. **Enemies are disabled.** Freeplay measures automation, planning, recovery, and
   progression rather than combat competence.
3. **The native Factorio save is canonical world state.** DuckDB is derived state
   and must be rebuilt and checked after loading a save.
4. **One runtime session has one active owner.** Sub-agents may advise the coding
   harness but cannot independently mutate the live runtime.
5. **The coding harness brings its own memory.** FactoryVerse records the visible
   transcript and workspace but does not implement the harness's planning memory.
6. **Runtime sessions are bounded even when campaigns are long-lived.** A campaign
   may last days; each attachment has explicit start, heartbeat, checkpoint, and
   termination records.
7. **The grader is independent of the actor runtime.** Actor-reported success is
   never a verdict.
8. **Production and debug capabilities are separate profiles.** Debug convenience
   never silently leaks into production evaluation.
9. **Single-agent is a vertical-slice limit, not a campaign identity rule.** The
   current supervisor admits one actor, but actor and runtime-session identities
   remain explicit so a future campaign can lease distinct bodies to distinct
   execution owners without sharing a namespace or mutation path.

## Evaluation Object Model

### Campaign

A `FreeplayCampaign` is the comparable evaluation unit. It binds:

- campaign ID;
- model and coding-harness identity;
- Factorio image, mods, scenario, seed, and dedicated instance;
- public interface/documentation versions;
- native checkpoint lineage;
- scoring time series;
- all runtime sessions and terminal status.

The campaign persists after individual harness or runtime processes exit.

### Runtime Session

A `RuntimeSession` is one bounded attachment of the coding harness to the campaign.
It owns:

- one explicit embodied actor identity;
- one exclusive runtime lease;
- one persistent Python namespace for the duration of the session;
- the submitted Python blocks and their outputs;
- session resource usage and heartbeats;
- a snapshot of the harness workspace at the session boundary.

Ending a session discards live Python object references. The harness may retain its
own files and memory, but must rediscover Factorio entities by stable references
(name/type plus position) after resuming.

### Checkpoint

A `FreeplayCheckpoint` records a campaign boundary:

- verified native Factorio save ZIP;
- game tick;
- checkpoint ID, parent checkpoint, and creation reason;
- save size and SHA-256 digest;
- DuckDB snapshot/export for evidence;
- database freshness and engine-parity result;
- scoring snapshot;
- actor workspace snapshot or diff;
- runtime and interface versions.

The Factorio save is the only canonical restore source. A saved DuckDB file is an
evidence artifact and cache, never a competing restore source.

### Result

A `FreeplayResult` is a terminal or intermediate campaign report. It contains a
validity classification, checkpoint lineage, time/resource usage, and scoring
curves. A campaign may be paused without receiving a terminal pass/fail verdict.

## Ownership and Trust Boundaries

```text
Trusted Freeplay Supervisor
├── campaign manifest and state machine
├── dedicated-instance provisioning
├── checkpoint/save orchestration
├── independent scoring and artifact recording
├── budgets, heartbeat, and runtime lease
└── finalization and cleanup
          │
          │ grants one production runtime lease
          ▼
Coding Harness + Actor Runtime
├── persistent Python namespace (session scoped)
├── harness-owned files and memory
├── embodied Python interfaces / Factory Objects
└── DuckDB perception
          │
          │ no raw RCON or admin capability
          ▼
Dedicated Factorio Freeplay Instance
```

### Future-compatible embodied delegation

Physical sub-agent spawning is not part of the current implementation. The
current boundary nevertheless preserves the invariant it would require: every
physical body has one identifiable runtime session and one live execution owner.
A future child actor must receive a distinct body, namespace, lease, budgets, and
trajectory attribution; it must never share its parent's mutation path.

The eventual supervisor-owned lifecycle is conceptually:

```text
REQUESTED -> PROVISIONED -> ACTIVE -> HANDOFF -> COMPLETED -> REAPED
                                └-> REVOKED -> PARKED | DESPAWNED
```

If a child harness exits, crashes, times out, or loses its lease, the supervisor
must revoke execution and move its body to a defined safe state. Inventory and
partial construction remain honest game state; resource handoff must occur through
embodied game mechanics. MCP or another transport may request execution for an
already leased child, but does not own body creation or cleanup.

### Production actor capability profile

Allowed:

- `walking`, `mining`, `crafting`, `research`, `inventory`, and placement;
- reachable and remote views;
- entity operations that correspond to embodied GUI actions;
- placement hints, ghost planning/building, verification views, and events;
- DuckDB read queries;
- documented FactoryVerse types;
- private writable campaign workspace.

Forbidden:

- raw RCON clients or arbitrary Lua execution;
- scenario/admin adapters;
- direct inventory/entity spawning;
- task grader internals;
- supervisor state and artifact mutation;
- sibling campaign state;
- unrestricted access to Factorio control ports.

### Debug capability profile

Debug sessions may opt into RCON, scenario adapters, and administrative entity/item
mutation. Their artifacts must be marked `debug`, and their results are not valid
production evaluation evidence.

## Campaign Lifecycle

```text
DEFINED
  -> PROVISIONING
  -> PREFLIGHT
  -> READY
  -> LEASED
  -> RUNNING
  -> CHECKPOINTING (repeatable)
  -> QUIESCING
  -> PAUSED | GRADING
  -> ARCHIVED
  -> DESTROYED
```

Exceptional terminal classifications:

- `INVALID_ENVIRONMENT`
- `INVALID_OBSERVATION`
- `INVALID_HARNESS`
- `ACTOR_CRASH`
- `CANCELLED`

Valid evaluation outcomes include `PASS`, `FAIL_BUDGET`, and `FAIL_STALLED`.
Infrastructure-invalid runs must never be recorded as model failures.

### Create a new campaign

1. Resolve an immutable campaign manifest.
2. Provision one dedicated freeplay server with the selected seed and mods.
3. Confirm enemies are disabled and the expected interfaces are loaded.
4. Create the embodied agent and production capability profile.
5. Wait for snapshot bootstrap and build the initial DuckDB database.
6. Prove body/vision/time coherence.
7. Capture checkpoint `0000-baseline`.
8. Start the first runtime session and grant its lease.

### Resume a campaign

1. Select a verified checkpoint from the campaign index.
2. Start the dedicated server from its native save.
3. Wait for Factorio and mod interfaces to become ready.
4. Force/reconcile a fresh snapshot from the loaded game.
5. Rebuild DuckDB from the loaded world.
6. Compare engine truth against the rebuilt database and reject stale/future data.
7. Start a fresh runtime session with no stale Python object references.
8. Restore only harness-owned memory/workspace and grant a new lease.

### Checkpoint a running campaign

1. Revoke new actor executions and allow or cancel the current bounded execution.
2. Wait for embodied actions and snapshot writes to quiesce.
3. Record the current engine tick and independent score.
4. Call `game.server_save(checkpoint_name)`.
5. Verify that the host-visible ZIP is new, non-empty, and structurally valid.
6. Flush/rebuild the database and capture a DB evidence artifact.
7. Run engine/DB parity checks.
8. Capture the harness workspace and append the checkpoint index atomically.
9. Resume the lease for a periodic checkpoint, or keep it revoked when pausing.

### End or pause a campaign

1. Revoke the runtime lease.
2. Quiesce/cancel pending actor work.
3. Capture a final checkpoint and score.
4. Close the runtime and all listeners it owns.
5. Write `result.json` and a terminal trajectory event.
6. Stop only infrastructure owned by this campaign.
7. Preserve the native save and artifacts for resume/audit.

## Database and Save Reconciliation

Freeplay resume is valid only when the database reflects the loaded save. The
minimum acceptance check is:

- current game tick is at or after all loaded snapshot ticks;
- all database rows belong to the current boot/save lineage;
- an independent engine census and database census agree for entity name,
  position, direction, and force;
- relational reads use stable name/type plus position references;
- snapshot and status feeds advance after resume;
- no pre-load Python object is reused.

The existing L0.3 certification proves native save/load state preservation for one
cycle. It does **not** certify database continuity across load or repeated campaign
resume cycles; the freeplay resume gate must cover those explicitly.

## Scoring

Freeplay is longitudinal, so scoring is a time series rather than one completion
bit. The initial score vector should be deliberately small and defensible:

- force production totals and rates by item;
- manual versus automated production;
- researched technologies;
- placed entity counts by functional category;
- active electric generation and consumption;
- number of automated recipe chains producing non-zero output;
- elapsed wall time, game ticks, actor executions, tokens, and cost.

Stalling cannot be inferred from one flat production metric. A stall candidate is a
window with no improvement across production, research, automation, and factory
capacity. Initial implementation records the curves; automatic stall verdicts may
be added after field data establishes honest thresholds.

## Clock Policy

For the first freeplay implementation, Factorio runs continuously. Every score and
checkpoint records both wall time and game tick. Model/harness latency is therefore
part of the evaluated system and must be reported.

Pausing Factorio during model reasoning is deferred. Dedicated instances make it
possible later without affecting other evaluations.

## Artifacts

Campaign layout:

```text
.fv-output/freeplay/<campaign_id>/
├── manifest.json
├── state.json
├── result.json
├── scores.jsonl
├── server-compose.yml
├── server-config/
├── server-output/
├── transcript/
│   └── runtime-protocol.jsonl
├── checkpoints/
│   ├── index.json
│   └── <checkpoint_id>/
│       ├── checkpoint.json
│       ├── factorio-save.zip
│       └── map.duckdb
├── sessions/
│   └── <session_id>/
│       ├── session.json
│       ├── preflight.json
│       ├── trajectory.jsonl
│       ├── agent_session.ipynb
│       └── runtime.duckdb
└── diagnostics/                 # created when launch/preflight fails
```

`manifest.json` must include:

- repository commit and dirty-tree fingerprint;
- Factorio image/version and mod hashes;
- scenario, peaceful/enemy settings, and map seed;
- model, provider, coding harness, and versions;
- interface, schema, prompt, and grader hashes;
- capability profile and clock policy;
- budgets and instance identity.

## Today's Launchable Vertical Slice

The following is the required end-of-day path. Anything else is deferred.

### Implementation status (2026-08-06)

The freeplay-first path is implemented as `fv freeplay-eval`. It is separate from
the legacy internal-model `fv freeplay` loop.

Implemented, offline-verified, and live-certified:

- immutable campaign manifests and durable lifecycle state;
- process-held exclusive runtime leases;
- campaign-local Compose, server config, save, snapshot, DB, session, score, and
  transcript paths;
- enemy-free map settings and a biter-specific preflight that counts only
  enemy-force units, unit spawners, and turrets across all surfaces;
- one production Tier 4 runtime with persistent Python state and no injected raw
  RCON or scenario/admin adapter;
- a transport-independent, single-actor execution session plus a stdin/stdout
  JSONL adapter with execution deadlines;
- native saves, SHA-256 checkpoint lineage, consistent DuckDB evidence copies,
  and independent production/progression score snapshots;
- automatic latest-checkpoint resume with native-save hash verification and a
  strict engine/DB entity fingerprint gate;
- a pre-admission freeplay snapshot barrier that re-snapshots every tracked
  chunk, waits for the writer to become idle, and refuses to admit an actor
  when starting resources are absent from DuckDB;
- intermediate `result.json` production and campaign-owned shutdown;
- a first-party Codex CLI controller using subprocess pipes, structured final
  actions, resumable Codex thread IDs, supervisor-owned checkpoint cadence, and
  a separate trusted control-artifact directory;
- repository provenance that hashes untracked file paths and contents, in
  addition to tracked binary diffs and `git status`.

The unit suite passes with 268 tests. On 2026-08-06, campaign `live-smoke-8`
completed the full Docker boot -> persistent Python -> embodied call + DuckDB
read -> checkpoint -> shutdown -> native-save resume -> fresh DB rebuild/parity
-> final checkpoint -> owned teardown cycle against Factorio 2.0.76.

The certification produced two hash-valid native saves and two independently
readable DuckDB files. Each DB contained 15 tables, 37 ingested starting chunks,
380 resource entities, 1,444 resource tiles, and 2,380 water tiles. Resume
matched checkpoint entity identity, preserved resource perception, reset the
Python namespace, and left no campaign containers running.

Campaign `codex-terra-runner-smoke-20260806` subsequently certified the direct
Codex path with `codex-cli 0.146.1` and `gpt-5.6-terra`: Codex emitted one
structured Python action over pipes, the actor runtime executed it successfully,
the response carried a verified source hash and explicit actor/session IDs, and
the supervisor captured baseline and final native checkpoints before removing
its containers. Its manifest includes the Codex action-schema/run-brief hashes
and hashes the contents of all 47 then-untracked repository files.

The full repository test command currently stops during collection on an
unrelated dirty-tree liveness-spec issue: the existing `map_entity.force` schema
change is not assigned to a generated liveness group. That pre-existing work is
outside this freeplay implementation and was not modified here.

### Operator commands

Create a campaign without starting Factorio:

```bash
fv freeplay-eval create \
  --campaign codex-freeplay-001 \
  --seed 44340 \
  --harness codex \
  --model gpt-5
```

Launch it (or resume the latest checkpoint when one exists):

```bash
fv freeplay-eval launch \
  --campaign codex-freeplay-001 \
  --harness codex \
  --model gpt-5
```

Launch reads one JSON object per stdin line. Machine-readable responses are
prefixed with `FV_EVAL_JSON ` so Factorio/Docker setup logs cannot corrupt
framing. The actor protocol exposes runtime observation and Python execution,
not granular gameplay verbs or campaign lifecycle authority:

```json
{"id":"1","op":"status"}
{"id":"2","op":"execute","source":"plan = {'phase': 'smelting'}\nprint(plan)"}
{"id":"3","op":"execute","source":"print(plan['phase'])","logical_path":"skills/smelting.py","timeout_seconds":30}
```

`code` remains a protocol-v1 compatibility alias for `source`. A caller may provide
`source_sha256` when it wants the runtime to reject mismatched content. Each response
and protocol record carries `actor_id` and `runtime_session_id`; executions also
carry the verified source hash and optional logical workspace path. The logical
path is provenance, not permission for the runtime to read an arbitrary host path.

`checkpoint`, `close`, `reset`, and body creation are rejected on this actor
channel. Closing stdin ends the transport, after which the trusted supervisor
checkpoints and finalizes the session. Operator interruption follows the same
supervisor-owned path. A future controller transport may expose explicit lifecycle
operations without adding them to the actor's capabilities.

Inspect durable state without attaching an actor:

```bash
fv freeplay-eval status --campaign codex-freeplay-001
```

Run Codex directly, with no MCP and no PTY relay:

```bash
fv freeplay-eval codex \
  --campaign codex-terra-freeplay-002 \
  --model gpt-5.6-terra \
  --max-turns 200 \
  --checkpoint-every 10
```

The Codex model name and runner budgets become immutable campaign-manifest
fields. On a later invocation, the command resumes the latest native Factorio
checkpoint and the stored Codex thread, provided the same runner arguments are
used and the repository fingerprint still matches the manifest. Source-tree
drift requires a new campaign. Codex owns `harness-workspace/`; canonical
responses, observations, thread state, schema, and JSONL event logs live in
`harness-control/`. The only model actions are `execute` and advisory
`report_complete`. Baseline, periodic, final, interruption, and error
checkpoints remain supervisor decisions.

If `server_0` is already active, launch fails instead of attaching to an instance
whose dedicated ownership cannot be proven. A campaign that becomes `invalid`
is evidence of an invalid run and is not silently resumed.

Checkpointing briefly pauses game ticks so the native save, database copy, and
score describe one quiescent boundary. The supervisor restores the prior clock
state after capture and explicitly unpauses a loaded checkpoint before Tier 4
rebuilds its derived database. Actor thinking/execution otherwise follows the
continuous-simulation clock policy.

### P0: campaign and environment lifecycle

- Create a new campaign directory and immutable manifest.
- Start one dedicated `freeplay` server or resume it from a named native save.
- Attach one `agent_1` runtime in production mode.
- Preflight Factorio interfaces, body, snapshots, DuckDB freshness, and enemy state.
- Maintain a durable campaign `state.json` with explicit lifecycle status.

### P0: coding-harness runtime

- Give one external coding harness an exclusive runtime session.
- Bind that session to an explicit embodied actor identity.
- Execute multiple Python blocks in one persistent namespace.
- Expose FactoryVerse action/view objects and documentation.
- Do not inject raw RCON or scenario/admin adapters.
- Support status, execution timeout/interrupt, and clean lease revocation.
- Record submitted code, output, timing, and errors outside actor-controlled files.

The first transport is a local stdio/runtime protocol. MCP is explicitly not
required for launch; a future MCP adapter must wrap the same actor session and
must not reintroduce granular gameplay verbs or lifecycle authority.

### P0: checkpoints and resume

- Trigger and verify a native server save.
- Index checkpoint lineage with hashes and game ticks.
- Capture score and database evidence with each checkpoint.
- Resume from the latest checkpoint.
- Rebuild DuckDB after load and block actor attachment until parity/freshness pass.

### P0: finalization

- Revoke the runtime, capture a final checkpoint, and write `result.json`.
- Classify actor failure separately from invalid infrastructure.
- Stop only the campaign-owned server/runtime.
- Leave the campaign resumable from its final verified checkpoint.

### Launch acceptance

A freeplay run is launchable when an operator can:

1. create a campaign on a fresh dedicated server;
2. attach an external coding harness to a production Python runtime;
3. execute at least two dependent Python blocks proving namespace persistence;
4. perform one embodied action and one DuckDB query;
5. have the trusted controller checkpoint and terminate the run;
6. resume from that checkpoint into a fresh runtime;
7. prove engine/DB coherence after resume; and
8. inspect a complete manifest, transcript, score, checkpoint index, and result.

## Explicitly Deferred

- lab-grid cell checkpoints and resets;
- parallel evaluation scheduling;
- cooperative or competitive agents;
- physical sub-agent provisioning and embodied delegation;
- puzzle/fix-task graders;
- automatic freeplay stall thresholds;
- cross-host orchestration;
- generalized plugin or MCP gameplay surfaces;
- adversarial-strength Python sandboxing beyond the initial production capability
  profile and process boundary.

## Existing Components to Reuse

- `Environment` tier initialization and reverse shutdown;
- Tier 1 infrastructure ownership guards;
- server saves volume and `fv server start --save`;
- Tier 3 RCON/UDP connection setup (kept private from the actor);
- Tier 4 embodied actions, views, persistent namespace, and trajectory writer;
- snapshot/DuckDB bootstrap and live synchronization;
- production/manual statistics and feed-liveness verification;
- generated Python API and DuckDB schema documentation.

## Known Gaps in the Current Tree

- `fv freeplay` is an internal-LLM turn loop, not an external coding-harness run.
- Tier 4 code still executes in the runtime-host process. The production namespace
  omits raw RCON, but this is cooperative capability narrowing, not an
  adversarial Python sandbox;
- the Jupyter configuration currently logs a notebook but does not provide the
  active Tier 4 objects inside an isolated kernel;
- freeplay scoring fields exist on `FreeplayResult` but are not populated;
- trusted score snapshots currently occur at checkpoints rather than on a
  wall-clock sampling schedule;
- campaign-wide wall-time, execution-count, token, and cost budgets are not yet
  enforced by the supervisor; today, only per-execution deadlines are enforced;
- harness workspace snapshots are not yet captured by FactoryVerse;
- the runtime protocol captures submitted code and outputs, but the coding
  harness must still supply its complete model transcript and workspace evidence.
