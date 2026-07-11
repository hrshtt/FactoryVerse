# Generated test families

Template-generated tests: an orchestrator authors a **frozen spec** per family;
sub-agents mechanically instantiate tests inside its boundaries, iterating
against a live server. Quality lives in the template, audited once per family
(see the Audit log in `docs/FLOOR_CERTIFICATION.md`) — instantiated tests
inherit that audit instead of each needing their own.

## The two layers

- **Frozen (`_frozen/`)** — the claim: truth channels, pass criteria,
  anti-vacuity floors, plants, failure semantics. Owned by the orchestrator.
  Sub-agents MUST NOT edit anything under `_frozen/`; acceptance is a diff
  gate (changes only inside the family dir), not trust. A `_frozen/` change
  voids the family's audit-log entry.
- **Free (family dirs, e.g. `db_column_liveness/`)** — the mechanics: rig
  layouts, probe wiring, cleanup. Sub-agents iterate here freely.

## Failure semantics (three terminal states)

| State | Meaning | What happens |
|-------|---------|--------------|
| GREEN | test passes AND the family's plants still fail | ship |
| RED-FINDING | test implements the spec faithfully; the engine/DB disagrees | a *deliverable*: file/point at a tracker issue; encode as `strict=True` xfail with the tracker ID in `reason` |
| SPEC-BUG | the claim can't be executed as written (`SpecBug`/`AntiVacuityError` raised) | escalate to the orchestrator; NEVER reinterpret the claim to get past it |

"Adjusted the claim until green" is not a state.

Strict-xfail is the RED-FINDING register in executable form: the suite stays
green while a known mirage persists, and goes red (XPASS) the moment someone
fixes the underlying surface without reconciling the spec + ledger — that's
deliberate; it forces the reconciliation.

## Plants (negative controls)

Every family declares plants in `PLANTS.md`: known-dead surfaces that MUST
come out red, plus at least one synthetic plant (a deliberately mutated
expectation on a live surface). A family whose plants pass is broken — that is
the executable form of audit question 1 ("can it pass vacuously?").

## Sub-agent protocol

1. Read this file, your family's `PLANTS.md`, and `docs/RUNTIME_PLAYBOOK.md`
   §0/§2/§5. Do NOT read broad project docs; your spec is your family's
   `_frozen/` spec module (`liveness_spec.py` / `accessor_spec.py`)
   `::cases_for_group("<your group>")`.
2. Factorio API questions: grep `resources/factorio-api/2.0.76/INDEX.md`, read
   only the per-item file you need. Never web-search what is answerable there.
3. You are assigned a FIXED cell index. Only ever allocate that cell
   (`runtime.allocate_cell(rcon, YOUR_CELL)`); never find-empty, never touch
   another cell.
4. Iterate: write test -> run -> fix MECHANICS until green-on-real AND
   red-on-plant. You may not edit `_frozen/`, `src/`, `scripts/`, or another
   family's files. If green requires any of those, that's a RED-FINDING or a
   SPEC-BUG — report it.
5. Always release your cell (`runtime.release_cell`) in fixture teardown, even
   on failure. Cleanup is not done until the cell's re-snapshot ran
   (playbook §5) — `release_cell` handles this.
6. Return the playbook §6 verdict block, with STATUS extended to
   GREEN / RED-FINDING / SPEC-BUG per test.

## Running

Live-gated like the rest of the repo's live suites. Run PER FILE, each with
its own cell — the `cell` fixture is session-scoped, so running multiple files
in one pytest session would pile every rig into one cell and collide:

```bash
# db_column_liveness runner (cells match the per-group assignments used at generation)
for spec in test_map_entity_core.py:7 test_map_entity_builder.py:10 \
            test_map_entity_dead.py:11 test_ghost.py:12 \
            test_terrain_and_meta.py:13 test_resource_entity.py:14 \
            test_dead_tables_and_docs.py:15; do
  FV_LIVE_TESTS=1 FV_INSTANCE=server_0 FV_CELL_INDEX=${spec##*:} \
    uv run pytest tests/generated/db_column_liveness/${spec%%:*} -q || break
done

# accessor_liveness runner
for spec in test_rotate_direction.py:16 test_filters_and_limits.py:17 \
            test_recipe_and_spine.py:18 test_burner_crafter_io.py:19 \
            test_container_io.py:20; do
  FV_LIVE_TESTS=1 FV_INSTANCE=server_0 FV_CELL_INDEX=${spec##*:} \
    uv run pytest tests/generated/accessor_liveness/${spec%%:*} -q || break
done
```

Pass criterion for the family (= ledger L1.11): every file green with 0
failures and **0 xpassed** — an xpassed plant means the machinery went vacuous
or a mirage got fixed without reconciling the spec + ledger.

Requires a running lab-grid instance (`uv run fv server start --num 1
--scenario lab-grid`). Without `FV_LIVE_TESTS=1` the whole tree skips
(offline CI stays green).

## Families

| Family | Claim | Ledger row |
|--------|-------|-----------|
| `db_column_liveness` | every documented DB table/column is live or ledger-red | L1.11 |
| `accessor_liveness` | every public write accessor mutates the engine state it promises (+ DB where a contract surface promises it) or is registered red | L1.12 |
