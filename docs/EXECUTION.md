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

## What we are up to (2026-08-29)

- **Phase 3 in progress** — the surface. 3A builds the source-declaring readers on `remote_view` (`status`, `status_changed`, `power`, `production`), re-points the power presentation, then cuts `entity_status`, `power_samples`, `power_networks`, `agent_production_statistics`. 3B builds `inventory.await_item`, `Container.set_limit`, `entity.status`, `entity_reference`, the catalog reads on `research`/`crafting`, caller-scoped research cancel, and the craft prediction at enqueue. 3C (after 3B) deletes: blocking `craft()`, the `placement`, `entity_ops`, `verify`, `events`, `mining` accessors, the `placement_hints` module, `resources`.
- **Phase 2 still owes**: the `action` stream's migration onto `stream.lua`; a hash-and-delta scheme for `inference_input` before N is raised; the comprehension probes (TURN §8.6), which need a model.
- **Operational note**: two live suites that "own" ports still share the compose project (`factorio_0`), so they must run one at a time; and `fv server start` returns before the server accepts RCON auth (a readiness race seen twice today) — attach with a retry.
- **Phase 1 owes one live check**: a human client joining a running world (spectator controller, no character, nothing altered) — `tests/live/test_scenario_boot_contract.py`, skipped until `FV_LIVE_HUMAN_CLIENT=1` with a client connected.

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

Battery after Phase 2: 457 passed, 1 skipped, 3 xfailed (strict).

Still in the serializer because Python reads them (go with Phase 4): `belt_data.underground_neighbour`, `pole_data.connected_poles`, inserter/miner `pickup_target`/`drop_target`. Known dead code left in place: `infra/services/agent_service.py` (no importer). `footprint_tiles.is_ghost` kept — `remote_view` reads it, but ghosts write no footprint tiles (Phase 3 decides).

---

## What we will do

In order. Each phase starts when the previous one's check column has no "pending".

1. **Finish Phase 1** and certify it live: scenario-matches-manifest, fresh boot differs by seed, zero enemies in the §7 fixed area, joining human has no character and alters nothing, fixture ingests ≥ 400 entities at boot.
2. **Phase 2 — the turn.** First the two gates that precede any clock work: a nonce printed by a program must appear in the next inference's input; the trajectory records the full model input, every notification, and every context compression. Then tick stamps on `execute_dsl`, `stream.lua` behind the `turn` stream, drain only at the turn boundary, `end_turn` with fast-forward, the report, the planning/gameplay mode split. Open question recorded in TURN §6: the planning-mode namespace is an assumption until it is exercised.
3. **Phase 3 — the surface.** Build before deleting: dump readers on `remote_view` (status current/changed, power, production), re-point the power presentation, then cut `entity_status`, `power_samples`, `power_networks`, `agent_production_statistics`. `await_item`, `Container.set_limit`, `entity_reference`, catalog reads. Then delete: blocking `craft()`, the `placement`, `entity_ops`, `verify`, `events`, `mining` accessors, `placement_hints._call()`'s error-key raise, `resources` alias. Regenerate the reference after each.
4. **Phase 4 — transport and ghosts**, each behind the fixture check.
5. **Phase 5 — names.**
6. **Then** the first eval run under the new contract, with the comprehension probes the plans list, and the belt baseline on a task with a forced ore→smelter gap (TRANSPORT §9.8). External harness transports are rebuilt only after that run.
