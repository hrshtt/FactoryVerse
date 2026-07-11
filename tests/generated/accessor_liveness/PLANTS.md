# Plants — accessor_liveness family

Negative controls. Every entry MUST come out red (strict xfail); an XPASS
fails the suite and forces spec+ledger reconciliation. A family whose plants
pass is broken.

## Natural plants (live in the tree, confirmed in-source 2026-07-09)

| # | Case | Why it must fail | Tracker |
|---|------|------------------|---------|
| (none currently — natural plants N1-N6 all flipped by fixes; the family's red-on-plant guarantee rests on the two synthetic plants below until the next finding) | | | |

## Flipped plants (fixed surfaces; kept for the audit trail, no longer red)

| # | Case | Flip | 
|---|------|------|
| N1-N3 | rotate / rotate_180 engine + DB legs | ROT-1 fixed 2026-07-11: mixins wired to remote `rotate_entity` (+ deeper fix: typed entities never received `direction` — BaseEntity `**kwargs` swallowed it; mixin `__init__` now claims it). Baseline xfails went strict-XPASS, spec+file reconciled to LIVE with exact promised-value equality |
| N4-N5 | `InserterMixin.set_filter` engine + DB legs | FILT-1 fixed 2026-07-11: entity-level filter route (2.0 `use_filters` + `entity.set_filter{name=...}`) in EntityInterface + filter contract in serialize's inserter branch. DB shape: `raw_data.inserter.{use_filters, filter_mode, filters:[{index,name}]}`. CONF-1 stays open for splitters only |
| N6 | label survival through config upserts | PROV-2 fixed 2026-07-11: shared reducer (`apply_ops.py`) with the provenance fold rule — builder-less ops preserve row provenance, present builder is authoritative. Both writers route through it; path agreement certified by L1.13 (`check_replay_parity.py`, red-first: caught the placed_tick divergence pre-refactor). PROV-1 (re-gather epoch) remains open by design — soft-claim flag pending |

## Synthetic plants (deliberately mutated expectation on a LIVE surface)

| # | File | Shape |
|---|------|-------|
| S1 | recipe_and_spine | assert the engine recipe equals a recipe that was NOT set (mutated target) — must fail while the real set_recipe cases pass |
| S2 | container_io | assert an engine item count off by a fixed delta from the true transferred amount — must fail while the real transfer cases pass |

Synthetic plants are marked strict-xfail with reason `SYNTHETIC-PLANT` and
must never share an assert path with the real case they shadow (a shared
helper that fails both proves nothing).

## Adjudicated boundaries (do not re-derive; do not "fix" in this family)

- DB legs exist ONLY for promised surfaces: direction (column), recipe
  (raw_data via config-upsert spine), filters (CONF-1, dead). Inventory/fuel
  transfer accessors get NO DB assertion — DB = spatial reference + durable
  contracts; volatile state is ephemeral-bridge-only (Harshit 2026-07-09).
- DB legs use `accessor_spec.wait_ops_flushed`, NEVER
  `runtime.re_snapshot_and_wait` — a full re-gather masks the event spine
  (and squashes provenance, PROV-1).
- `FluidMixin.get_fluid` is a KNOWN lying read (STUB-1) owned by the
  ephemeral-bridge track. Not a plant here; not a case here.
