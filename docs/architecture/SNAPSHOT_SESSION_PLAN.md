# Snapshot sessions — the mod remembers nothing across a save

*Designed 2026-09-04. Not scheduled. Supersedes the epoch-and-reconcile design recorded under
EXECUTION item 1 the same day, and the Tier 4 disk guard added in `0cd396e`.*

## 0. Why this exists

Twice in a week the snapshot floor was green over an empty disk. On 2026-09-02 the mod's
storage said 427 chunks were snapshotted while the host directory held nothing. On 2026-09-04,
on `starter-base-test`, the server boot ran `on_load` only — no boot pass — and
`get_boot_report()` answered with the *client session's* pass, carried in the save's
`script.dat`, read by Python as a statement about the running process.

Both are the same defect. `fv_snapshot` keeps, in storage, claims about files on a disk it
cannot read (Factorio gives mods `write_file` and `remove_path`, nothing else). Storage
survives a save; the disk it describes does not travel with it. Every repair so far — the
boot pass (Phase 1B), the remote `boot`, the Tier 4 guard, the epoch stamp designed this
morning — adds a way to *distrust* that memory. This plan removes the memory.

**One paragraph.** The mod is inert until a consumer opens a session. The consumer names the
session, and every file and datagram the mod produces carries that name, in the path and in
the envelope. The mod may remember what it wrote during the current session, because that
memory dies with the session. It may not remember anything across a save, so `fv_snapshot`
keeps no storage at all, and that is a checkable invariant on any save's `script.dat`. Which
chunks exist and which are charted are questions for the engine, answered live on request.
What has been snapshotted is a question for the consumer's ledger, and the mod never answers
it.

## 1. Argued from the Constitution

- **§10 (event-backing decides membership)** is untouched: Load and Update remain the two
  write classes, and the files carry the same records. What changes is *who decides a Load
  happened*: the consumer that requested it and received `chunk_written`, not a flag in Lua.
- **§11 (volatile facts are read live and say where they came from)**: "which chunks are
  charted" is exactly such a fact. `charted_chunks()` is a live engine read (~115 ms over
  2 743 chunks, measured), not a table the mod maintains. The status dump and power sample
  become session options, off by default, which is §11's "read live through Python, batched"
  instead of a file nobody asked for.
- **§13–§15 (a claim is certified by its check; a green from an unaudited check is a rumor;
  silence is not evidence)**: a report carried across a save is precisely the unaudited
  green. With no storage there is nothing to carry, and the invariant "`script.dat` holds no
  `fv_snapshot` storage" is checkable offline on any save. The certification collapses to one
  shape: open a session, request, compare the session directory to an engine census, and
  assert every file and datagram carries the session id.
- **§20 (nothing of the agent lingers past the turn)** has a sibling here: nothing of a
  consumer lingers past its session.

## 2. What Python calls today (grounded 2026-09-04)

| call | sites | fate |
|---|---|---|
| `get_snapshot_status` | `adapter.py:123`, `remote_view.py:2098`, `lab_grid.py:549`, `tier4_runtime.py:888,1127`, `tier3_python.py:565`, live tests | survives as `snapshot_status()` |
| `set_udp_port` / `get_udp_port` | `port_config.py:52,55`, `adapter.py:132`, `tier3_python.py:249–262` | session option `udp_port` |
| `get_chunk_lookup` | `lab_grid.py:617`, `tier4_runtime.py:855,889` | deleted — it read the bookkeeping; replaced by `charted_chunks()` + the host ledger |
| `get_boot_report`, `boot` | `tier4_runtime.py::_reconcile_snapshot_disk`, two live tests | deleted — the save-carried claim |
| `re_snapshot_chunks` | `tier4_runtime.py:875` (`_prepare_freeplay_snapshot`) | `snapshot_chunks()` — there is no "re" when nothing remembers the first time |
| `snapshot_area` | `adapter.py:126` | deleted — area→chunks is host arithmetic |
| `set_orchestration_mode` | `adapter.py:129` | deleted with its three modes; `auto_snapshot_charted` is the one option that remains |

Of nine names, five exist only to work around the bookkeeping being removed.

## 3. Storage inventory (what "no storage at all" covers)

| owner | key | today | after |
|---|---|---|---|
| `Map.lua` | `chunk_tracker`, `system_state`, `snapshot_state`, `orchestration_mode` | claims about files, phase machine, mode | gone; queue and written-set are session (module-level) state |
| `snapshot.lua` | `chunk_tracker` (27 uses), `snapshot_sequence`, `snapshot_udp_port`, `status_dump_files` | file bookkeeping, sequence, port, rolling buffer | gone; `seq` restarts at 1 per session; port is a session option; rolling buffer is host garbage |
| `udp_payloads.lua` | `udp_sequence` | datagram sequence | session `seq` |
| `Power.lua` | `system_state` | phase gating for the sampler | session option `power_interval_ticks` |
| `Agents.lua` | `last_production_stats` | previous sample for deltas | session state; a new session starts a new delta baseline, which the ledger owner knows |
| `Resource.lua` | `recent_tree_removals` | dedup window for tree-removal events | session state |
| `Research.lua` | none (reads `fv_embodied_agent` by remote) | — | — |

`fv_embodied_agent`'s turn stream (`utils/stream.lua`) keeps `(epoch, seq)` in a storage slot
its owner persists, so an `on_load` boot keeps the previous process's epoch. It should adopt
the session id as its epoch (step E). That is the one change this plan makes outside
`fv_snapshot`.

## 4. The API

```
open_session{id, options}        -> {id, tick, mod_version}
   options: auto_snapshot_charted (bool, default false)
            status_interval_ticks (0 = off), power_interval_ticks (0 = off)
            udp_port, budgets{entities_per_tick, tiles_per_tick, writes_per_tick, serializations_per_tick}
close_session()                  -> {id, chunks_written, ops_emitted}
session()                        -> {id | nil, tick_opened, queue, written: n}

charted_chunks()                 -> [{x, y}]      live from the engine
snapshot_chunks([{x, y}], priority) -> {queued}   writes snapshots/<id>/<x>/<y>/*-init.jsonl
snapshot_status()                -> {busy | idle, pending, budgets}
```

Streams, all stamped `{session, seq, tick, event_type, data}`, `seq` from 1 per session:

- `chunk_charted` stays, so a consumer that chose not to auto-snapshot decides per chunk.
- `chunk_written{x, y, files}` replaces `chunk_init_complete`.
- `snapshot_idle` replaces `system_phase_changed`; fires once when the queue drains.
- `entity_operation` keeps its shape; update files live under the session prefix.

**Deleted.** `boot`, `get_boot_report`, `get_chunk_lookup`, `trigger_initial_snapshot`,
`set_orchestration_mode` and its three modes, `snapshot_area`, `re_snapshot_area`,
`re_snapshot_chunks`, the map-area-state trio, `get_udp_port`, `set_udp_port`, the
`snapshot_state` datagram, `Map.boot` and `boot_reconcile_charted_chunks` (Phase 1B's
reconciliation was a repair of the memory; with no memory there is nothing to reconcile).

**Rules the API implies, stated so silence is not read as a decision.**

- One session at a time. `open_session` while one is open closes it first and says so in
  the return (`closed: {id, chunks_written}`); the consumer that lost it can see that it did.
- With no session open, every event handler returns before doing work. Build events cost
  the engine's 0.02 ms, not the mod's 1.9 ms. `chunk_charted` is not emitted; a consumer
  attaching later asks `charted_chunks()`.
- The session id is mandatory and host-minted. A mod cannot mint a unique id in `on_load`
  without touching game state, and a self-minted id is the bookkeeping problem in a smaller
  hat.
- `auto_snapshot_charted` ships. An agent walking a fresh world charts constantly, and an
  RCON round trip per chunk is latency the turn contract (§18) does not want. It is the one
  decision left in the mod, it is off by default, and the consumer that turned it on still
  receives `chunk_written` for every chunk it produces.
- Module-level memory within a session is allowed: the queue, the written-set, sequences,
  the tree-removal dedup window, the previous production sample. All of it is rebuilt empty
  on `on_load`, which is the point.

## 5. What the host does

The host keeps a ledger keyed by session: for each chunk, when it was requested and when
`chunk_written` arrived. Attach is four steps — open a session, ask for charted chunks,
request them all, wait for `snapshot_idle`. The loader reads `snapshots/<id>/` and nothing
else. Older session directories are the host's garbage, which turns the ad hoc directory
clearing on scenario boot (`clear_all_server_snapshot_dirs`, and the "saves keep their
snapshots" branch that was the false assumption) into a rule: delete what is not the live
session's. A host that restarts while the server keeps running opens a new session and pays
the 85 s again (measured on 15 251 entities). That is the honest price; the consumer may skip
it only when it still holds the files for a session it knows is live, because it named it.

`copy-before-boot` (`0cd396e`) stays: it protects the *save*, which is a different fact from
the snapshot directory.

## 6. Steps and gates

Each step is one commit. A step's gate is its check; a step with no check is a claim.

- **A. The invariant first.** `tests/unit/test_snapshot_lua_contracts.py`: no `storage.` in
  `fv_snapshot` except a documented allow-list that shrinks to empty by step D; and an
  offline check that opens a save zip and asserts `script.dat` carries no `mod-fv_snapshot`
  storage block (run it on `starter-base-test`: it fails today, which is the point).
- **B. Sessions and the streams.** `open_session` / `close_session` / `session()`; the
  envelope; `seq` per session; handlers inert without a session; session-prefixed paths.
  Gate: a live check that opens a session on `starter-base-test`, builds 200 belts through
  `raise_built`, and asserts every datagram and every update line carries the id and a
  contiguous `seq`; then closes the session, builds 200 more, and asserts nothing was
  written and the LuaProfiler cost per build is the engine's.
- **C. `charted_chunks` and `snapshot_chunks`.** The find/serialize/write pipeline kept as
  is (its budgets are the batching mechanism, and its output is honest — set-equal to the
  engine census on 15 251 entities), addressed by session. `chunk_written` and
  `snapshot_idle`. Gate: the certification — open, request all charted, wait for idle, load
  `snapshots/<id>/`, assert set equality with an independent engine census by name+position
  (`count_entities_filtered{name=…}` per name), raw lines equal unique keys, every file
  under the session prefix.
- **D. Storage removed, names deleted.** The inventory in §3 to zero; the calls in §2
  re-pointed or deleted; `_reconcile_snapshot_disk` and `_prepare_freeplay_snapshot`
  replaced by the host ledger; `port_config` ports become the session option. Gate: step
  A's invariant passes on a save produced *after* a session ran on it; the unit battery;
  the re-scoped live suites.
- **E. The turn stream adopts the session id.** `stream.lua`'s epoch becomes the session id,
  supplied by `fv_embodied_agent` from the same `open_session` (one id for both mods, or a
  paired call — decide at the step). Gate: `tests/live/test_turn_stream.py` gates 6–8 with
  the epoch replaced.
- **F. Options that were floors.** `status_interval_ticks` and `power_interval_ticks` off
  by default; the status dump, when on, spread across ticks rather than one ~340 ms tick
  (13 937 records measured). Per-event UDP batched per tick behind the sequenced envelope
  (one datagram ≈ 1 ms measured, any size). These are separable and can follow the first
  run.

## 7. What this closes and what it does not

Closes: both layers of the boot-report blocker (EXECUTION, 2026-09-02 and 2026-09-04); the
epoch design; the Tier 4 guard; the client freeze attributable to this mod. Does not close:
the per-event UDP cost when a session *is* open (step F); the loader's 111–166 s on a
15k-entity base (a Python matter, out of scope here); `test_transport_fixture.py`'s four
components, which certify on top of step C.
