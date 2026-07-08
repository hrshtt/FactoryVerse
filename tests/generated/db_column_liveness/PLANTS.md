# Plants — db_column_liveness

Negative controls. Every entry below MUST be red (strict-xfail FAILING) on
every run. Any plant that passes means the family is broken (vacuous) or the
underlying surface was fixed without reconciling the spec + ledger — both stop
the line.

## Natural plants (known-dead documented surfaces, exploration 2026-07-08)

| Plant | Class | Tracker | Why it must be red |
|-------|-------|---------|--------------------|
| `map_entity.electric_network_id` | documented column, never lifted (loader.py INSERT list omits it) | MIRAGE-2 | engine has network ids; column is always NULL |
| `map_entity.tile_x` / `tile_y` | declared + live-queried (`get_entities_at_anchor_tile`), never lifted | NEW-2026-07-08 | always NULL |
| `inserter` / `transport_belt` / `mining_drill` / `assembler` tables | documented with worked JOIN examples; loader never inserts | MIRAGE-1 / ledger L1.5 ❌ | 0 rows while the rig contains all four entity kinds |
| `footprint_tiles` table | documented core table; 0 rows; queried live by remote_view (`is_tile_occupied` always False) | NEW-2026-07-08 | 0 rows while rig entities occupy tiles |
| `entity_key` JOIN key | schema_reference worked examples join on a column that exists on NO table | NEW-2026-07-08 | the documented JOIN must fail to execute |
| `map_entity.direction` / `ghost.direction` | MISREPRESENTED: docs promise names ("NORTH, EAST, ..."); VARCHAR holds raw defines.direction ints; mod-emitted `direction_name` dropped by loader (found by Phase B pilot run) | NEW-2026-07-08 | documented-semantics comparison must fail while int-derivability passes |
| `ghost.placed_by` | no write path emits this key at any level; alias-vs-drop is a pending design call. (`ghost.label`/`placed_tick` were plants of the same MIRAGE-4 class until FIXED 2026-07-08 — loader/sync made builder-aware; their tests are live now) | MIRAGE-4 (residual) | column NULL while raw_data.builder has agent_id |
| `chunk_snapshot_meta` empty-chunk rows | content-empty chunks never get an init file, hence never a meta row, even when `get_chunk_lookup` reports them freshly snapshotted (9/16 chunks in the terrain run) — per-chunk freshness undecidable from the DB for empty chunks | NEW-2026-07-08 | meta-row completeness assertion must fail |

## Synthetic plant

One test asserts a deliberately mutated expectation on a LIVE column
(`map_entity.entity_name` must equal a name the rig never placed), marked
strict-xfail with reason `SYNTHETIC PLANT`. If the machinery ever lets it
pass — empty comparisons, vacuous floors, wrong cell — the suite fails.

## Status

Filled in by Phase B/D runs: each plant's last observed state + run date.
