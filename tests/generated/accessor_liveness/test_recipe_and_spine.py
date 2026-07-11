"""accessor_liveness / recipe_and_spine group.

Cases (frozen spec: cases_for_group("recipe_and_spine")):
- SetRecipeMixin.set_recipe   engine LIVE, db LIVE  (THE LIVE SPINE EXEMPLAR:
  set_entity_recipe raises the config event -> full-entity upsert ->
  raw_data.recipe; both legs expected green, the DB leg certifies the
  event-driven config-upsert spine end to end).

Plus two extra frozen claims that hang off this group with no accessor of
their own (accessor_spec.py LABEL_SURVIVAL_GROUP / SYNTHETIC_PLANT_GROUPS
both name "recipe_and_spine"):
- LABEL SURVIVAL: a config-upsert (set_recipe) on a TYPED-placed, labeled
  entity must not squash map_entity.label — the config-change re-serialize
  is the event-path leg of PROV-1 (the full re-gather squash is PROV-1
  itself and NOT this family's claim).
- SYNTHETIC PLANT S1 (mandatory): a deliberately mutated expectation on the
  live surface, must fail while the real cases stay green.

Rig: four assembling-machine-1s within reach of the agent spawn, one per
case (machine_a/b/c/d) so no case's mutation contaminates another case's
precondition. machine_a/b/d are script-placed (placement itself is COVERED
per spec, not under test); machine_c goes through the TYPED placement path
with a label, because only that path raises the on_agent_entity_built event
that carries the label into the DB in the first place.
"""

from __future__ import annotations

import json

import pytest

from _frozen import runtime
from _frozen.accessor_spec import (
    ENGINE_READS,
    MIN_DISTINCT_TARGETS,
    REQUIRE_PRECONDITION_DELTA,
    wait_ops_flushed,
)
from conftest import engine_read, give_items, spawn_offset

pytestmark = pytest.mark.live

RIG_LABEL = "recipe-spine-label"


# --- rig ---------------------------------------------------------------------

@pytest.fixture(scope="module")
def rig(rcon, cell, typed):
    """Four assembling-machine-1s within reach of spawn:
    - machine_a: script-placed; SetRecipeMixin.set_recipe engine leg (case A)
    - machine_b: script-placed; DB spine leg (case B)
    - machine_c: TYPED placement WITH a label; label-survival claim (case C)
    - machine_d: script-placed; synthetic plant S1 target only
    """
    from FactoryVerse.game.factory.types import MapPosition

    # allocate_cell's create_agent_in_cell charts the cell and enqueues its
    # own background re_snapshot (SNAP-1b docstring, runtime.allocate_cell).
    # That chunk-init snapshot can race the rig's own placements/events: if
    # it finishes AFTER our rig entities exist, its generic full-chunk scan
    # (label = "pre-existing", no builder info) becomes the chunk's init
    # baseline, and the loader drops our earlier build/config events as
    # "older than the chunk's init snapshot tick" (loader.py:366 log).
    # wait_ops_flushed alone is NOT enough: it samples IDLE in the gap
    # between the re-gather being enqueued and started (flaked ~40% on
    # back-to-back runs, 2026-07-11). Drain until the re-gather has LANDED —
    # every cell chunk's snapshot_tick >= the allocation tick.
    from conftest import drain_cell_snapshots
    drain_cell_snapshots(rcon, cell)

    # assembling-machine-1 is a 3x3 (odd x odd) footprint: create_entity
    # snaps the center onto the nearest valid half-tile position, so the
    # ACTUAL placed position can differ from the requested one by up to
    # 0.5 on each axis. Always read positions back from the placement
    # result, never assume the requested x/y round-trips exactly.
    ax, ay = spawn_offset(cell, -4.0, -4.0)
    bx, by = spawn_offset(cell, 4.0, -4.0)
    cx, cy = spawn_offset(cell, -4.0, 4.0)
    dx, dy = spawn_offset(cell, 4.0, 4.0)

    res_a = runtime.place(rcon, cell, "assembling-machine-1", ax, ay)
    res_b = runtime.place(rcon, cell, "assembling-machine-1", bx, by)
    res_d = runtime.place(rcon, cell, "assembling-machine-1", dx, dy)

    give_items(rcon, cell.agent_id, {"assembling-machine-1": 1})
    placed = typed["placement"].place(
        "assembling-machine-1",
        MapPosition(x=cx, y=cy),
        label=RIG_LABEL,
    )
    if placed.failed:
        raise runtime.SpecBug(
            f"typed placement of labeled machine_c failed: {placed}")

    wait_ops_flushed(rcon)
    return {
        "machine_a": (res_a["x"], res_a["y"]),
        "machine_b": (res_b["x"], res_b["y"]),
        "machine_c": (placed.position["x"], placed.position["y"]),
        "machine_d": (res_d["x"], res_d["y"]),
    }


def _engine_recipe(rcon, cell, pos):
    res = engine_read(rcon, cell, "assembling-machine-1", pos[0], pos[1],
                       ENGINE_READS["recipe"])
    if res.get("missing"):
        raise runtime.SpecBug(f"rig entity missing at {pos}")
    return res["value"]


def _typed_entity_at(typed, name, pos):
    """Fetch the ONE typed entity at `pos` out of several same-named rig
    entities. Tolerance-based match rather than get_entity(position=...),
    which relies on MapPosition.__eq__ exact-float equality — fragile
    across an RCON JSON round-trip when several same-named rigs exist."""
    candidates = [
        e for e in typed["view"].get_entities(name)
        if abs(e.position.x - pos[0]) < 0.01 and abs(e.position.y - pos[1]) < 0.01
    ]
    if not candidates:
        raise runtime.SpecBug(
            f"typed view returned no {name} at {pos} (reachable gate?)")
    if len(candidates) > 1:
        raise runtime.SpecBug(
            f"ambiguous typed lookup: {len(candidates)} {name} at {pos}")
    return candidates[0]


def _db_row(instance, rcon, name, pos):
    con = runtime.load_db(instance, runtime.game_tick(rcon))
    rows = con.execute(
        "SELECT raw_data, label FROM map_entity WHERE entity_name = ? "
        "AND abs(position_x - ?) < 0.01 AND abs(position_y - ?) < 0.01",
        [name, pos[0], pos[1]],
    ).fetchall()
    return rows


# --- Case A: SetRecipeMixin.set_recipe -- engine leg (LIVE) ------------------

def test_set_recipe_mutates_engine(rcon, cell, typed, rig):
    pos = rig["machine_a"]
    pre = _engine_recipe(rcon, cell, pos)
    assert pre == "", (
        f"rig precondition violated: machine_a already has recipe {pre!r}; "
        "the rig must start with no recipe for the precondition-delta floor")

    targets = ["iron-gear-wheel", "copper-cable"]
    assert len(set(targets)) >= MIN_DISTINCT_TARGETS
    if REQUIRE_PRECONDITION_DELTA:
        assert pre != targets[0], (
            "precondition-delta floor unmet: engine pre-state already "
            "equals the first target")

    machine = _typed_entity_at(typed, "assembling-machine-1", pos)
    seen = []
    for target in targets:
        machine.set_recipe(target)  # promises an engine recipe change
        after = _engine_recipe(rcon, cell, pos)
        assert after == target, (
            f"accessor returned success but engine recipe is {after!r}, "
            f"not the requested {target!r} — client-state lie")
        seen.append(after)
    assert len(set(seen)) == MIN_DISTINCT_TARGETS, (
        f"distinct-targets floor: expected {MIN_DISTINCT_TARGETS} distinct "
        f"engine recipes, saw {seen}")


# --- Case B: DB spine leg (LIVE, THE LIVE SPINE EXEMPLAR) -------------------

def test_set_recipe_reaches_db_raw_data(instance, rcon, cell, typed, rig):
    pos = rig["machine_b"]
    target = "iron-gear-wheel"

    pre_rows = _db_row(instance, rcon, "assembling-machine-1", pos)
    if not pre_rows:
        raise runtime.SpecBug("DB control missing: rig row absent before set_recipe")

    machine = _typed_entity_at(typed, "assembling-machine-1", pos)
    machine.set_recipe(target)
    wait_ops_flushed(rcon)

    rows = _db_row(instance, rcon, "assembling-machine-1", pos)
    assert rows, f"DB spine leg: no map_entity row for machine_b at {pos} after set_recipe"
    raw_data = json.loads(rows[0][0])
    assert raw_data.get("recipe") == target, (
        f"DB spine leg: raw_data['recipe'] = {raw_data.get('recipe')!r}, "
        f"expected {target!r} — the event-driven config-upsert path never "
        "landed (raw_data keys present: "
        f"{sorted(raw_data.keys())})")


# --- Case C: LABEL SURVIVAL (frozen claim, LABEL_SURVIVAL_GROUP) -----------

# History: was strict-xfail PROV-2 (config upsert squashed label — the
# handler re-serializes without builder_info, so the upsert carried
# builder={} and INSERT-OR-REPLACE nulled provenance; live-confirmed
# 2026-07-11 cell 18). FIXED same day by the shared-reducer provenance fold
# (apply_ops.py: builder-less ops preserve row provenance; path agreement
# certified by L1.13 check_replay_parity). Flipped strict-XPASS, reconciled
# here to LIVE.
def test_set_recipe_preserves_label(instance, rcon, cell, typed, rig):
    pos = rig["machine_c"]

    pre_rows = _db_row(instance, rcon, "assembling-machine-1", pos)
    if not pre_rows:
        raise runtime.SpecBug(
            "label-survival control failed: no map_entity row for "
            "machine_c before set_recipe")
    pre_label = pre_rows[0][1]
    if pre_label != RIG_LABEL:
        raise runtime.SpecBug(
            f"label-survival control failed: label BEFORE set_recipe is "
            f"{pre_label!r}, expected {RIG_LABEL!r} — the typed placement "
            "itself didn't carry the label into the DB, so this isn't the "
            "config-upsert claim under test")

    machine = _typed_entity_at(typed, "assembling-machine-1", pos)
    target = "copper-cable"
    machine.set_recipe(target)
    wait_ops_flushed(rcon)

    rows = _db_row(instance, rcon, "assembling-machine-1", pos)
    assert rows, "label-survival case: machine_c row vanished after set_recipe"
    raw_data, label = rows[0]
    raw = json.loads(raw_data)
    assert raw.get("recipe") == target, (
        "label-survival case: the recipe leg itself broke, "
        f"raw_data['recipe'] = {raw.get('recipe')!r}")
    assert label == RIG_LABEL, (
        f"NEW-FINDING(accessor_liveness): config upsert squashes label — "
        f"map_entity.label = {label!r} after set_recipe, was {RIG_LABEL!r} "
        "before (PROV-1-adjacent: the config-change re-serialize path "
        "calls serialize_entity(entity) with no builder_info, so the "
        "replayed 'upsert' op carries builder={} and INSERT-OR-REPLACEs "
        "label to NULL)")


# --- SYNTHETIC PLANT S1 (mandatory, PLANTS.md) ------------------------------

@pytest.mark.xfail(strict=True, reason="SYNTHETIC-PLANT")
def test_set_recipe_synthetic_plant_wrong_target(rcon, cell, typed, rig):
    """Deliberately mutated expectation on the live surface: set
    'iron-gear-wheel', assert engine recipe == 'iron-stick'. Must fail while
    the real cases above stay green. Uses its OWN inline engine read (never
    _engine_recipe) so a shared-helper false negative can't launder this."""
    pos = rig["machine_d"]
    machine = _typed_entity_at(typed, "assembling-machine-1", pos)
    machine.set_recipe("iron-gear-wheel")

    res = engine_read(rcon, cell, "assembling-machine-1", pos[0], pos[1],
                       ENGINE_READS["recipe"])
    if res.get("missing"):
        raise runtime.SpecBug(f"plant rig entity missing at {pos}")
    engine_recipe = res["value"]
    assert engine_recipe == "iron-stick", (
        f"SYNTHETIC-PLANT S1: engine recipe is {engine_recipe!r}, mutated "
        "expectation was 'iron-stick' — this assertion must fail")
