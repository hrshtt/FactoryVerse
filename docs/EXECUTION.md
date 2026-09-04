# Execution — where the refactor stands

One page, four questions: what we are doing, what we are up to right now, what has been done, what comes next. Updated on every commit that moves a phase. Dated entries only; no undated "currently".

This is not a finding ledger or an issue tracker — those were removed on purpose. A row here says a phase's *work* landed; whether it *works* is answered only by the check named on the row (Constitution §13). If a row has no check, it is a claim, and it says so.

The plans in `docs/architecture/` are the authority on *what*; this page is the authority on *where we are*.

---

## What we are doing

Replacing the agent's harness in the order the amended plans force, so that every later eval run is on a named world, under a defined turn, over a map model that holds only event-backed facts, through a namespace whose every verb is a human gesture. Branch: `prompt-audit-fixes`. The external harnesses (Codex, Hermes) are gone until this is done; `fv run` is the sole path.

Decisions that shape the order (2026-08-29): hand crafting and research stay in Python — the game splits into two **modes** (planning, gameplay) instead of growing top-level tools; the observer policy lives in `fv_embodied_agent` as a mod setting; polled tables leave the database and become source-declaring reads on `remote_view`; deletions of doomed verbs are prioritised so nothing is repaired on a surface about to be removed.

| Phase | Owns | Plan sections |
|---|---|---|
| 0 | The floor stops lying: checks that cannot pass vacuously, serializer without fabrications, dead code and dead columns gone | API §6, TRANSPORT §8/§9.9, NOTIFICATIONS gate 5 |
| 1 | Which world: scenario resolution, `--create` gone, settings load-bearing, observer policy, snapshot boot reconciliation | SCENARIO Stages 0–5, TRANSPORT §13 |
| 2 | The turn: one path, nonce conformance, full input in the record, tick ledger, `turn` stream with epoch/seq, `end_turn` + fast-forward, the report, two modes | TURN §3–§8, NOTIFICATIONS design |
| 3 | The surface: `await_item`, `Container.set_limit`, `entity_reference`, catalog reads on `crafting`/`research`, status/power/production readers on `remote_view`, then the namespace deletions one commit per surface and the polled tables cut | API §2, §4, §5; HUD §3, §5, §8 |
| 4 | Transport and ghosts: fixture check, `belt.contents`, `belt_to_ground_type`, `transport.line()`, poles, fluid, `place_line`, `ghost_builder` deleted | TRANSPORT §14, GHOST §4 |
| 5 | Names: tier rename, `execute_dsl → execute_python` | TIER_RENAME |

---

## What we are up to (2026-09-04)

**Phase 4 is blocked on a lying floor. Read this before doing anything else.**

### The blocker — the snapshot pipeline reports healthy over an empty disk

`tests/live/test_transport_fixture.py` boots the `iron-saturated` fixture, asks the
mod for its boot report, and then loads the host-side snapshot directory. In the
same run the mod reports **427 chunks charted, 427 snapshotted, ≥380 entities
tracked** while the loader reads **0 entities, 0 chunks**. The host directory holds
only `power_networks.jsonl` — no per-chunk `entities-init.jsonl` exists.

Requesting the boot pass explicitly (`remote.call("map","boot")`, added for this)
changes nothing, because `boot_reconcile_charted_chunks` only queues chunks whose
storage entry says they still need snapshotting. **"Snapshotted" is a claim about
mod storage, and it is being read as a claim about files on disk.** Those are
different facts, and on a resumed save they routinely disagree.

**The second-order damage is worse than the failing test.**
`tests/live/test_snapshot_boot_contract.py` took **68.7 s** when it certified this
layer on 2026-08-29 (registering 397 chunks, ingesting 404 entities) and now passes
in **3.37 s**, because the save's own bookkeeping satisfies every assertion without
a single file being written. It is green and it is testing nothing — §14 verbatim,
in the check that guards the floor everything else in Phase 4 stands on.

**Probable cause, and a warning about the fixture.** Until the copy-before-boot fix
in `0cd396e`, a server booted from a named save autosaved back over it. The mtime on
`.fv-output/server_0/saves/iron-saturated.zip` moved during this session, so the
fixture very likely now carries the post-snapshot storage that makes the check
vacuous — the instrument was damaged by the defect it was being used to find. The
ground truth in `TRANSPORT_CONNECTIVITY_PLAN.md` §1.1 (four components, 142/55/55/32,
the merge at (39.5, 58.5)) was measured against the pristine save. **Re-creating or
re-verifying the fixture is part of this work**, not a preliminary to it.

**Shape of the fix** (not designed, not executed): the boot pass must verify its own
output rather than trust its bookkeeping — reconcile `snapshot_tick` /
`has_tracked_entities` against the files the mod can actually see, and treat a chunk
whose file is missing as needing a snapshot regardless of what storage says. This is
the same class as the defect Phase 1B fixed (`chunk_lookup` populated only by an
event that never fires on a pre-charted world) one level up: there, storage was empty
when the world was full; here, storage is full when the disk is empty.

### 2026-09-04 — the blocker measured on a real base, and what the day found

**A stronger fixture exists.** `starter-base-test` (the owner's client save, copied to
`.fv-output/server_0/saves/`, md5 `0725198e…`): 15 251 entities of 32 names in 166 chunks,
6 235 belt-family rows in 35 components (one of 3 741), 187 technologies, three electric
networks, oil. Baseline artifacts — save, engine census by name+position, world facts,
the verified snapshot directory, a facts sheet with the profile below — are in
`.fv-output/baselines/starter-base-test/` (untracked). It replaces iron-saturated as the
instrument for the floor work; iron-saturated stays as the transport oracle (§1.1).

**The blocker reproduced on the first boot, and it is one layer deeper than recorded.**
The save carries `fv_snapshot` storage from the client session. On the server the mod
ran **`on_load` only** (container log: no `on_init`, no `on_configuration_changed`), so
no boot pass ran at all — and `get_boot_report()` still answered `reason =
on_configuration_changed, tick = 43600`, with the client's chunk and entity counts.
**The boot report is a save-carried claim about a previous process**, and Python reads
it as a statement about this one. The epoch the certification design asks for (below)
has to stamp the report too, not only the files.

**Snapshotting itself is honest once asked.** Forcing every chunk through
`re_snapshot_chunks` wrote 1 048 chunks in 85 s; the loader's `map_entity` is set-equal
to an independent engine census (15 251 both ways, 0 either-only), and per name the
engine's `count_entities_filtered{name=…}`, the raw init lines and the table agree for
all 32 names. The writer does not lie; only the decision to write does.

**Profile (LuaProfiler from the scenario runtime; tick rate at speed 10):**
- Built entity through the mod's handlers: **1.9 ms** (engine alone 0.02 ms); destroyed
  1.5 ms. ~1.0 ms of it is the one `send_udp` per event (same cost at 100 B or 1 KB, any
  port), ~0.3–0.5 ms serialization + JSON, 0.08 ms the file append. A 200-belt drag is a
  0.4 s stall — this is the client freeze. Only `fv_snapshot` handles build events.
- The quiescent phase costs more than snapshotting: ~6.7 ms/tick idle vs ~3 ms/tick
  during the 1 048-chunk pass, because the status dump (13 937 records, `table_to_json`
  235 ms of a ~340 ms single-tick hitch every 60 ticks) is suspended while snapshotting.
- Boot walk over 2 743 chunks: 115 ms once. `SnapshotLoader.load_all` on this base:
  111–166 s. Belt derivation over it: 0.3 s.
Both per-event UDP and the one-tick status dump are floor work before an agent runs on
a base this size; neither was visible at 404 entities.

**Fixed the same day (chunk ownership).** Init files listed a multi-tile entity on a
chunk edge in both chunks' files (463 of 15 714 lines; every surplus a 2x2-or-larger
entity, none a 1x1) because the area query matches bounding-box overlap while the update
path assigns by `position`. `chunk_owns_entity` now applies the position rule to tracked
entities, ghosts and the tracked count. Worst-tick cost measured at +0.5 ms on a
596-entity chunk; net negative over a run. See the row below.

### Also in flight

- **Phase 4B (not started)** — the Lua half: `belt.contents` live read, the remaining
  adjacency keys out of the serializer (`underground_neighbour`, `connected_poles`,
  inserter/miner `pickup_target`/`drop_target` — all still read by Python today),
  pole `wired_to()` / `can_wire_to()` as live reads, `place_line`.
- **Phase 2 still owes**: **the one-program gate** (TURN §2.2, gate 3 — "the first
  thing to build"; `orchestrator.py` still executes every tool call in an inference,
  and `test_turn_record.py`'s nonce check covers only the single-call case, so it is
  green over a case that cannot fail); the `action` stream's migration onto
  `stream.lua`; a hash-and-delta scheme for `inference_input` before N is raised
  above 128; the comprehension probes (TURN §8.6), which need a model.
- **Phase 1 owes one live check**: a human client joining a running world (spectator
  controller, no character, nothing altered) — skipped until `FV_LIVE_HUMAN_CLIENT=1`
  with a client connected.
- **Scorer plan written (2026-09-02)**: `docs/architecture/SCORER_MOD_PLAN.md` — a
  fourth mod, `fv_scorer`, reading the engine directly. Designed, not scheduled; it
  enters the order after Phase 4's floor is honest (its census check needs the
  fixture). The specification-language direction discussed alongside it is recorded in
  `GOAL_SPECIFICATIONS_DEFERRED_INDEFINITELY.md` and is not in scope.
- **Entity scope plan written (2026-09-02)**: `docs/architecture/ENTITY_SCOPE_PLAN.md`
  — scope as a property of the technology tree, one generated manifest, standings for
  every prototype, one hash asserted from Lua, the map model and Python. Designed, not
  scheduled. Its first two steps (the drop gets a voice; the manifest and its offline
  checks) need no instance and are not behind the Phase 4 blocker; its later steps
  touch the serializer Phase 4B touches and are sequenced with it. It is the
  precondition for robots.
- **Factoriopedia plan written (2026-09-03)**: `docs/architecture/FACTORIOPEDIA_PLAN.md`
  — the agent-facing half: an invariant system prompt carrying complete examples for
  the fourteen pre-science entities, a `factoriopedia` tool whose page depth is gated
  on the force's live research state, and the report naming what a finished research
  unlocked. Designed, not scheduled; its first step (registering every entity class
  with the documentation registry) closes audit defect 10 and needs only the scope
  manifest.
- **Plan review (2026-09-03)**: every plan read against the tree by one agent each,
  with a shared brief (thesis, motivation, agent-facing change, systems change, status,
  dependencies, scope verdict, risks). Verdicts: the nine effective plans are mostly
  spent; what is load-bearing for the first run and still open is the floor fix
  (item 1 below), the one-program gate, `belt.contents`, the forced-gap task, and
  ENTITY_SCOPE step A. SCORER, ENTITY_SCOPE B–F, FACTORIOPEDIA, TRANSPORT's pole
  drag and fluid half, `place_line`, and the tier rename are load-bearing for the
  research argument, not for the first run, and are sequenced after it.

  **Defects the review surfaced, not yet fixed, none behind the blocker** (the
  "honesty commit", item 2 below):
  1. `EXECUTE_DSL_DESCRIPTION` (`environment/tool_definitions.py:37-39`) still tells
     the model that `walking, mining, placement, entity_ops, placement_hints, events`
     are loaded; all six left the namespace in Phase 3C. No check catches it.
  2. `place()` constructs the typed object after the RCON call and outside any try
     (`place_entity.py:203-211`); `reachable_view.py:142` and `duckdb/query.py:332,451`
     swallow unknown entities. Five placeables the categorical reference advertises
     (`radar`, `beacon`, `stone-wall`, `gate`, `land-mine`) have no class, so placing
     one mutates the world, raises, and is invisible to every typed read afterwards.
     ENTITY_SCOPE step A, minus its manifest dependency.
  3. `crafting.enqueue` raises for missing ingredients where HUD §2.4 rule 3 and
     `research.dequeue` return a game-rule failure as data.
  4. `docs/system-prompt/factoryverse-system-prompt-v3-core.md` is a stale snapshot
     from `fda10e2` still advertising `ghost_builder`, `build_plan`, `GhostPlan`.
     Read by nothing; delete or regenerate.
  5. `footprint_tiles.is_ghost` (already listed below) — decide it in the same pass.
  6. `sync.py::_check_sequence` accepts any first sequence at attach; same defect class
     as the blocker (a locally reconstructed baseline trusted over Lua). Loss there is
     loud, so it is a one-line honesty fix, not a blocker.
  7. `execute_dsl → execute_python` moves into this commit: the tool description is
     being rewritten anyway, and the frozen-names note in `tool_definitions.py` must
     be amended in writing when it happens (the trajectory reader accepts both names).

  **Decisions pending, recorded so silence is not read as a decision:** SCORER
  proposes Constitution §22 and §23 and cannot be argued from the existing clauses —
  adopt or refuse by name before its step 2. FACTORIOPEDIA binds a ninth name against
  the eight-name assertion — amend or re-home before its step C. TRANSPORT §9.1
  (does rotating one underground end flip `belt_to_ground_type` on both with one
  event) is a ten-minute probe that can invalidate Phase 4A's one schema change.

  **Record corrections made 2026-09-03:** NOTIFICATIONS' status line (it said nothing
  had run); the API §6 and GHOST §7 baseline gates marked closed with loss (surfaces
  deleted before they ran); TRANSPORT §15 notes that surface and teaching shipped
  together so §9.8 measures the pair; the phantom `SCORER_DEFERRED.md` removed from
  AGENTS.md; the four plan docs and `SUPPORTED_ENTITIES.md` committed.
- **Operational notes**: live suites share the compose project (`factorio_0`), so they
  run one at a time; `fv server start` returns before RCON accepts authentication —
  attach with a bounded retry (the pattern is in `tests/live/test_turn_contract.py`).

---

## What has been done

| Date | What | Commit | Check |
|---|---|---|---|
| 2026-08-28 | Ten code audits of the nine plans against the tree (namespace, turn loop, notifications, schema, scenario boot, transport repairs, crafting/research/mining, test battery, run forensics, ghosts) | — | The audits' claims were folded into the plans; each plan names its own checks |
| 2026-08-29 | Plans aligned with the tree and the decisions above; API §4.6 retroactive map-model audit added | `c53a0ee` | none — documentation |
| 2026-08-29 | Codex runner, Codex app-server, Hermes entry point removed; campaign infra kept | `12412be` | `uv run pytest tests/unit -q` green; `fv --help` renders |
| 2026-08-29 | Notifications gate 5: `vocabulary.lua` (wire vs target), parity checked from both sides | `e39e942` | `tests/unit/test_vocabulary_parity.py` — 13 green, 4 strict xfail naming the exact gaps |
| 2026-08-29 | Phase 0A — coverage asserts complete with live exemptions; converse namespace check; accessor table derived from registry; every SQL example executes against the real DDL; DDL↔doc parity; prose method tokens resolved; `entity_key` phantom gone; `fv docs generate` writes both docs | `d84b464` | `tests/unit/test_documentation_coverage.py`, `tests/unit/test_docs_honesty.py` |
| 2026-08-29 | Phase 0B — five geometry events registered; pipe `dx>0` fabrication replaced by a `ports` emit; `item_lines` and `belt_neighbours` dropped; dead cross-mod event pair fixed; `Error.lua` and nine dead senders deleted | `3972df1` | `tests/unit/test_snapshot_lua_contracts.py` (text contracts); `luac -p`. **Live (2026-08-29):** `tests/live/test_database_coherence.py` 13 passed and `test_entity_persistence_contracts.py` 2 passed on fresh Docker servers with the changed mods; a local client on `lab-grid` loads both mods with no errors and mints exactly one `EntityInterface` event pair (241/242) where it used to mint two. Still unexercised in-engine: `_on_entity_teleported` on ghosts, flipped-splitter state |
| 2026-08-29 | Phase 0C — `tile_x/tile_y` and `ghost.placed_by` written; broken Jupyter bootstrap and dead `factoriopedia.py` deleted; RESOURCE-FILTER-1 and CONTAINER-CONTENTS-1 fixed | `c030f36` | `tests/unit/test_phase0_dead_columns_and_lies.py` |

| 2026-08-29 | Phase 1A — one scenario resolver (repo-only for container boots; `setup_client` fails closed); FactoryVerse `freeplay` scenario restored from `236cba9` as a thin world-shaper with contract v2; `--create` branch and cached initial save deleted, every scenario boots `--start-server-load-scenario`, compose `restart: "no"`; §4.3 no-enemy recipe in both JSON files and asserted by preflight; `Spectator.lua` revived behind mod setting `fv-observer-spectator` (default on); `lab-grid` god block removed; post-boot probe (`environment/boot_probe.py`) in preflight; scenario hash in the manifest and preflight fails on mismatch | `3c934ea` | `tests/unit/test_scenario_boot_contract.py` (18). **Live (2026-08-29):** `tests/live/test_scenario_boot_contract.py` 6 passed on `factoriotools/factorio:2.0.76` — FactoryVerse `freeplay` loaded (base interface absent), seed honoured, 0 enemies in the §7 area, second seed gives a different world. Human-join check pending |
| 2026-08-29 | Phase 1B — snapshot boot reconciliation: `Map.boot()` on `on_init`/`on_configuration_changed` walks `get_chunks()` ∩ `is_chunk_charted`; one chunk-registration path; one writer of `has_tracked_entities`; `EMPTY` phase distinct from `MAINTENANCE`; probe `remote.call("map","get_boot_report")`; dead status walk deleted; Python bootstrap wait accepts `EMPTY` | `559e8b6` | `tests/unit/test_snapshot_lua_contracts.py` (12). **Live (2026-08-29):** `tests/live/test_snapshot_boot_contract.py` passed on the `iron-saturated` fixture — 1360 generated, 427 charted, 10 with entities, 404 entities tracked, phase MAINTENANCE, 49 s |

| 2026-08-29 | Phase 2A — the trajectory holds the model's input per step (`system_prompt` once by hash, `inference_input` verbatim, `inference_output`, `notification` with its index, `context_compressed` with the removed messages, `turn_complete.ended_by`); `TrajectoryReader.reconstruct_inference_input`; tick trailer `[tick a→b, +n]` on every `execute_dsl`/`execute_duckdb` result and `game_tick_before/after` on `tool_result` | `9ea484a` | `tests/unit/test_turn_record.py` — nonce conformance (gate 1) and exact reconstruction of every inference's input from the file (gate 2) are green |
| 2026-08-29 | Phase 2B — `stream.lua` (side-effect-free unit: open/emit/flush/new_epoch/state, envelope `{epoch,seq,tick,event_type,data}`); the seven `turn` types leave only on the per-agent `turn` port (`34300 + 10·N + i`), one file append + one datagram per item per tick; `crafting_finished` no longer leaves twice; Python `TurnStreamListener` adopts `(epoch, seq)` from `stream_state` at attach, accepts only the next seq, fills gaps from `turn.jsonl` and marks them; `research_moved`/`research_reversed` typed | `28f5b2d` | `tests/unit/test_turn_stream.py`, vocabulary xfails 4→3. **Live (2026-08-29):** `tests/live/test_turn_stream.py` 4 passed on 2.0.76 — datagram ceiling measured at ~8 KiB (`MAX_DATAGRAM_BYTES = 8000`), inversion gone (gate 6), a dropped datagram is announced and filled from the file (gate 7), attach at seq N accepts N+1 and treats N+5 as a gap (gate 8) |
| 2026-08-29 | Phase 2C — `end_turn` tool; exact fast-forward via `tick_paused` + `ticks_to_run` at speed 64 (`Tier3Python.advance_world`); `TurnConfig` (N=128 attention calls, T∈[3600, 36000], tier buckets, rate term; hashed into the record, absent from the prompt); the turn report as the first input of the next turn (clock, horizon, plan, production automated/hand, map diff, status transitions from `status_dump.changed`, research, crafting, inventory, events with epoch:seq); one drain per turn after the advance; planning/gameplay modes with a filtered namespace, planning after every `research_finished`; prompt teaches turns and the "between turns" claim is now true | `9ea484a` | `tests/unit/test_turn_contract.py` (10): ledger reconciles, attention cap, planning refuses body verbs and advances 0, one drain per turn, report thresholds. **Live (2026-08-29):** `tests/live/test_turn_contract.py` 3 passed — 600 and 3600 ticks land exactly (~186 t/s), and the ledger reconciles to the horizon once the remainder is computed on the frozen tick and the paused boundary is the next turn's start (two earlier runs put 2–6 ticks on nobody's ledger; that is now a unit test) |

| 2026-08-29 | Phase 3A — `remote_view.status()`, `status_changed()`, `power()`, `production()` read the dump files / the engine and declare their source; power presentation re-pointed; `entity_status`, `power_samples`, `power_networks`, `agent_production_statistics` cut with reducers, boot loads and sync keys; `chunk_snapshot_meta.tick` advances live; `resource_tile.amount` documented as charting-time | `9b9daa9` | `tests/unit/test_dump_readers.py`, `test_state_tables_wired.py` (no polled table may exist), `test_power_ux.py`; DDL↔doc parity green. **Live (2026-08-29):** the re-scoped suites pass — DB coherence 13/13, entity persistence 2/2, freeplay harness 8/8 |
| 2026-08-29 | Phase 3B — `inventory.await_item` (bounded, well-founded, actuals), `Container.set_limit`, `entity.status` (live, sourced), `entity_reference(name)` (read-only subset under identical names; parity test per family), `research.list_technologies` / `crafting.list_recipes` (CATALOG-1 closed), caller-scoped `research.dequeue`, craft prediction at enqueue | `d266efd` | `tests/unit/test_entity_reference.py` (26) |
| 2026-08-29 | Phase 3C — deleted from the namespace: `walking.walk_to_entity`, `placement`, `entity_ops`, `mining`, `resources`, `verify`, `placement_hints`, `events`, blocking `crafting.craft()`; mechanisms kept behind the objects (`infra/live_batch.py`, pure placement-hint parsers); the namespace is exactly eight names and both direction checks assert it; `CraftingQueueStatus` is a dataclass (CRAFT-STATUS-1 closed); predictions flow into the report; prompt teaches the four idioms; docs regenerated | `51a07c0` | `tests/unit/test_docs_honesty.py` (namespace == the eight), `test_live_batch.py`, battery 485 passed |

| 2026-08-29 | Live suites re-scoped to the eight-name surface: status/power/production through the readers, placement through `item.place()` and `entity_reference().can_place`, crafting through `enqueue` + `await_item`, research completion read off the turn stream file, ghost conversion as the composed idiom; two contracts driving the deleted executor removed | `52170d0` | The suites themselves — and they earned their keep by finding the four defects below |
| 2026-08-29 | Four defects the live runs found: force production read inverted (`input_counts` is production — measured); the power sampler dead in the new `EMPTY` phase; the boot gate counting a non-combat character as an enemy; a server booting from a named save autosaving over it. Plus a fail-closed guard when mod storage and the host snapshot disk disagree | `0cd396e` | `tests/live/test_database_coherence.py` 13/13 and `test_freeplay_harness_domains.py` 8/8 after the fixes; the production semantics were settled by a probe, recorded in the commit |
| 2026-08-29 | Phase 4A — `belt_to_ground_type` and `loader_type` promoted into `transport_belt`; `transport.line()` / `lines()` / `shares_line_with()` derived at read time, never stored; `belt.line()` as the per-entity mirror; `ghost_builder` withdrawn on progression grounds; belts and ghosts taught in the prompt | `5f97896` (deletion misfiled in `0cd396e`) | `tests/unit/test_transport.py` (11), including the neighbour-invalidation case stored adjacency cannot pass. **Live: BLOCKED** — see the blocker above |
| 2026-09-04 | Chunk ownership: init files, ghost files and the tracked count keep only entities whose `position` falls in the chunk (the update path's rule), instead of everything whose bounding box overlaps it | — | `tests/unit/test_snapshot_lua_contracts.py::test_chunk_snapshot_keeps_only_entities_the_chunk_owns`. **Live (2026-09-04):** on `starter-base-test`, 15 251 init lines = 15 251 unique keys = the engine census (was 15 714 lines); boot report `entities.tracked` 15 251 (was 15 715) |

Battery after Phase 4A: 494 passed, 1 skipped, 3 xfailed (strict).

Still in the serializer because Python reads them (go with Phase 4): `belt_data.underground_neighbour`, `pole_data.connected_poles`, inserter/miner `pickup_target`/`drop_target`. Known dead code left in place: `infra/services/agent_service.py` (no importer). `footprint_tiles.is_ghost` kept — `remote_view` branches on it to route lookups to the `ghost` table, but ghosts write no footprint tiles, so that branch is dead by data. Undecided; it belongs with the ghost work.

---

## What we will do

In order. Each item starts when the one before it has no "pending" or "BLOCKED" in
its check column.

1. **Unblock the floor.** The mod cannot read the disk (Factorio gives mods
   `write_file` and `remove_path` only), so the reconciliation is host-driven and the
   mod must accept being told to distrust its bookkeeping. Design (2026-09-04): each
   boot pass mints an epoch, kept in storage, **stamped into the boot report** and into
   every init file's `chunk_meta` line; the loader rejects files from another epoch;
   the Tier 4 reconcile becomes a pure decision over report-vs-disk (epoch, per-chunk
   presence) that both `fv run` and the live test call. Certification is agreement
   between witnesses that cannot collude — an engine census by name+position, the
   disk read through the loader, the report as the claim under test — across three
   boots: pristine save over an empty directory; the same save *carrying storage* over
   an empty directory (the case that passed in three seconds; measured 2026-09-04 as
   `on_load` only, no pass, report from the previous process); partial loss. Raw init
   lines must equal unique keys. The fixture is `starter-base-test` (hash pinned, a
   precondition on its `script.dat`, hash asserted unchanged after the run);
   `iron-saturated` stays for `test_transport_fixture.py`'s four named components.
2. **The honesty commit.** The seven defects listed under *Plan review (2026-09-03)*
   above, plus the two dead-by-data artifacts. One commit, no design questions, no
   instance needed. It goes before Phase 4B because every item is in the first run's
   path and none touches the serializer.
3. **Phase 4B — the Lua half of transport.** `belt.contents` as a live read (the
   commented-out `get_contents()` with the comment claiming the method does not
   exist, thirty lines from a file that calls it); the remaining adjacency keys out
   of the serializer once their Python readers move to the derived reads; pole
   `wired_to()` / `can_wire_to()` as live reads, never derived (§1.2 — geometry
   over-connects on 12 of 44 poles); `place_line` on the item, behind the drag
   differential §9.3 asks for; fluid last, because it is unproven and the fixture
   has no pipes. *Sequencing note (2026-09-03):* `belt.contents` and the forced-gap
   task are all the first run needs from this phase; poles, fluid and `place_line`
   serve the research argument and can follow the run unless it shows tile-loop
   placement is what fails.
4. **Phase 5 — names.** The tier rename, as one mechanical commit with deprecated
   aliases for a cycle. (`execute_dsl → execute_python` moved into item 2, since the
   tool description is rewritten there and the run should not be taken under a name
   that argues against the surface.) The tier rename buys the first run nothing and
   can follow it.
5. **Close what earlier phases owe**: the `action` stream onto `stream.lua`; the
   human-join live check; a hash-and-delta scheme for `inference_input` before N
   rises above 128.
6. **Then the first eval run under the new contract** — the comprehension probes each
   plan lists (they need a model, and they are cheap), then the belt baseline on a
   task with a forced ore→smelter gap (TRANSPORT §9.8), unprompted then prompted.
   External harness transports are rebuilt only after that run.

**A standing caution for whoever picks this up.** Three times in this work a check
was green while the thing it named was not happening: the documentation coverage
report, the status walk that ignored its own argument, and now the snapshot boot
contract. Each was found by asking what the check would do if the layer under it did
nothing at all. Ask that question of any green you are about to build on.
