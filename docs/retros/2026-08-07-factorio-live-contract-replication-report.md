# Factorio live-contract replication report

Date: 2026-08-07

## Purpose

This report consolidates the reproductions derived from the Codex Terra
freeplay-004 audit. It separates Factorio mechanics, verified product defects,
timing-sensitive evidence, non-reproductions, and invalid test samples before
production fixes begin.

No production source was changed during this investigation. The new live tests
are opt-in and own disposable Docker servers. A later manual observation pass
used one persistent server and reset only test entities and actor state between
cases.

## Test surfaces

- `tests/live/test_reach_walking_contracts.py`
- `tests/live/test_resource_inventory_contracts.py`
- `tests/live/test_entity_persistence_contracts.py`
- `tests/live/test_database_coherence.py`
- `tests/unit/test_freeplay_issue_reproductions.py`
- `tests/reproductions/test_codex_terra_freeplay_004_trace.py`

The manual observation server used campaign
`regular-speed-24f5e377`, game port `52197`, RCON port `42500`, and a
connected Factorio client. The server was not restarted between cases. It is
back at `game.speed = 1` after the speed matrix.

## Executive findings

1. Factorio reach and the agent's reachable view use different geometry.
   Factorio correctly permits interaction with an entity boundary, while the
   reachable view can reject the same entity based on center distance.
2. Completed walking can remain reported as active because stale walking
   bookkeeping survives physical completion.
3. Tree mining is correct at ordinary speed, but completion/destruction becomes
   intermittent under the campaign's accelerated conditions. The evidence does
   not establish a simple deterministic speed threshold.
4. Live entity creation reliably reaches the general `map_entity` table but
   not the derived footprint or component tables.
5. A controlled working drill did not disappear. The original BUG-004 symptom
   remains unconfirmed, while the missing `mining_drill` row is confirmed.
6. Burner-mining-drill crafting correctly consumes a stone furnace. That
   retrospective observation was a recipe misunderstanding, not inventory loss.
7. Snapshot/status transport has independent sequencing and configuration
   defects: the snapshot mod boots on the wrong isolated port, and status
   notifications repeatedly reference files that are not visible to the loader.

## Results by contract

### Reach and walking state

#### Chest

- Final agent position: `(294.3515625, 0.5)`
- Chest position: `(304.5, 0.5)`
- Center distance: `10.1484375`
- Factorio `character.can_reach_entity(chest)`: `true`
- Exact chest present in `get_reachable`: `false`
- Immediate direct inspection: successful
- Reported walking state after arrival: `active=true`, `path_id=2`
- `stop()`: rejected with `Agent is not walking`

Factorio measures reach against the entity's physical boundary. The reachable
view appears to use a fixed center-radius query. The walk itself was valid; the
agent-facing postcondition was false.

#### Tree

- Center distance after entity-aware walking: `3.0234375`
- Factorio reach: `true`
- Exact tree present in reachable resource view: `false`

The resource view's `2.5` center-radius cutoff does not reproduce Factorio's
interaction geometry.

#### Timeout recovery

A deliberately timed-out walk was cancelled, and a second clean walk completed.
Timeout recovery is not currently implicated in the stale completed-walk state.

### Tree mining and speed matrix

The contract binds one exact `resource_entity` row to one live Factorio tree,
places the actor at an engine-validated mining position, mines once, and compares
returned products, inventory delta, engine existence, and the exact DB row.

| Speed | Synchronized result | Engine tree | Wood delta | DB row |
|---:|---|---|---:|---|
| 1 | Pass, repeated | Removed | +4 | Removed |
| 2 | Pass | Removed | +4 | Removed |
| 4 | Pass | Removed | +4 | Removed |
| 8 | Anomalous sample | Still present at full health | +4 | Removed |
| 8 | Instrumented repeat | Removed | +4 | Removed |

The anomalous speed-8 sample emitted a destroy notification and removed the DB
row, yet a full-health `tree-07` remained at the exact coordinate. A direct
post-test engine query found exactly one such tree. The instrumented repeat
recorded two nearby trees at distinct coordinates before mining, selected one,
and completed correctly.

An earlier dedicated speed-8 live run produced a stronger failure: mining
reported completion/depletion and four wood, while inventory did not change and
the engine tree and DB row remained. That failure was reproduced before the
manual observation server was created.

Conclusion: higher-speed execution exposes an intermittent causal-completion or
event-ordering defect, but this matrix does not prove that speed alone determines
the outcome. Tree identity, action notification ordering, DB deletion ordering,
and engine revalidation must be captured in the same tick-indexed trace.

#### Excluded samples

- The first attempted speed-2 sample is excluded because the external speed
  change was delayed and its effective mining speed was not proven.
- One driver attempt is excluded because a negative coordinate generated SQL
  containing `--`, which DuckDB parsed as a comment. Mining never started.

### Database coherence

The broad live suite previously produced eight passing checks and five expected
product failures. Those failures reduce to two classes.

#### Snapshot port boot configuration

- Allocated snapshot port: `52400` in the manual campaign
- Mod-reported boot port: `34400`
- The test repaired the disposable server in-place to continue downstream
  contracts.

#### Derived live tables

The manual client observation produced these exact counts:

| Entity | `map_entity` | `footprint_tiles` | Component table |
|---|---:|---:|---:|
| Inserter | 1 | 0 | `inserter=0` |
| Transport belt | 1 | 0 | `transport_belt=0` |
| Assembling machine 1 | 1 | 0 | `assembler=0` |
| Burner mining drill | 1 | not separately sampled | `mining_drill=0` |

The entities were visibly present in Factorio. This is not entity creation
failure and not total database blindness. The generic upsert succeeds; derived
materialization is missing.

The broad suite also verified working paths for:

- general placement and removal;
- ghost creation, rotation, and removal;
- direct resource removal;
- bootstrap resource/water/spatial data;
- production statistics; and
- power/status feeds when their files are successfully ingested.

### Working-entity persistence

A DB-seeded stone patch was used to create a fueled burner drill feeding a
wooden chest. The actor remained idle and did not move.

Regular-speed manual result after 609 ticks:

- drill still exists: yes;
- drill status: `working`;
- chest still exists: yes;
- chest stone delta: `+2`;
- drill `map_entity` rows: `1`;
- chest `map_entity` rows: `1`;
- `entity_status` rows: `1`;
- `mining_drill` rows: `0`.

BUG-004, spontaneous disappearance of a working drill, did not reproduce. The
positive persistence contract should remain. The component-table failure must
remain a separate expected failure.

### Crafting inventory causality

The active Factorio recipe, rather than a hard-coded test recipe, supplied the
ingredient and product expectations for one burner mining drill.

- All engine-declared ingredients were consumed exactly.
- The stone furnace was consumed to zero.
- One burner mining drill was produced.
- The public inventory view matched direct Factorio inventory.

This closes the reported disappearing-furnace observation as expected recipe
behavior.

### Status-file visibility

During ordinary-speed and accelerated manual cases, the sync service repeatedly
logged messages of this form:

`entity_status file not found for live sync: .../status/status-<tick>.jsonl`

The notifications arrived every 60 game ticks across long ranges. This is not
yet classified as file creation failure, path mismatch, notification-before-
flush, or premature cleanup. It is independently actionable because the loader
is being asked to consume a causal artifact that is absent at read time.

### Client/server mod synchronization

The first client connection was rejected because the client and server had
different `fv_placement_hints/connections/init.lua` contents. Every other file
matched. Copying the exact campaign-private server file into the client mod and
restarting Factorio resolved the connection.

The campaign supervisor snapshots current repository mods for the server, but
it does not refresh an already-running client's installed mod bundle. A launch
or prejoin compatibility step should compare full mod manifests before asking a
human observer to connect.

## Evidence classification

### Confirmed deterministic defects

- engine-reachable chest/tree omitted from the reachable view;
- completed walk reported active while stop reports not walking;
- live `map_entity` creation without footprint/component rows;
- isolated snapshot mod boots on its default rather than allocated port;
- client/server mod bundle can drift without prejoin detection.

### Confirmed intermittent defect family

- mining completion/destruction/product/DB outcomes can lose causal agreement;
- status notifications can arrive without a readable status file.

### Passing contracts

- timeout followed by a clean second walk;
- ordinary-speed tree mining;
- recipe-led crafting and inventory deltas;
- exact drill/chest engine persistence and continued unattended production;
- general `map_entity`, ghost, resource-removal, statistics, and power/status
  paths described above.

### Not reproduced

- spontaneous disappearance of a controlled working drill.

## Recommended fix order

1. **Causal action completion and identity**
   - Include exact entity identity, engine existence, inventory delta, destroy
     event, and DB deletion in one tick-indexed mining trace.
   - A successful/depleted result must not be returned until those facts agree,
     or it must return a structured reconciliation failure.
2. **Snapshot and status artifact delivery**
   - Apply allocated ports before actor/runtime startup.
   - Make file publication atomic and retry notification/file visibility races.
   - Treat a referenced-but-absent file as a first-class sync error with bounded
     recovery, not log spam.
3. **Derived-table live materialization**
   - Build footprint and component rows from every live map-entity upsert.
   - Delete/rotate/update those rows transactionally with the base row.
4. **Reachability geometry and walking state**
   - Use Factorio's reach predicate or equivalent bounding-box geometry for
     postconditions.
   - Clear `path_id` and all walking bookkeeping on every completion path.
5. **Prejoin mod manifest verification**
   - Compare client and campaign-private server mod manifests before connection,
     or provide an explicit sync-and-restart step.

## Boundary before fixes

Do not encode strategy rules from the Terra run into these fixes. The verified
problems are mechanics, causal completion, synchronization, database
materialization, and context truthfulness. Fix those contracts first, rerun the
live suites, then begin a new clean model campaign.
