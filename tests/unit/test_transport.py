"""Belt topology is derived from geometry and never stored (TRANSPORT §2–§5, §9.7).

These tests build the rows by hand, so the expected components are authored
independently of the code under test (Constitution §14). The live fixture
check (tests/live/test_transport_fixture.py) is the certification at scale.
"""

from __future__ import annotations

import duckdb
import pytest

from FactoryVerse.game.agent import transport as T
from FactoryVerse.game.infra.duckdb import apply_ops
from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase


def belt(x, y, d, name="transport-belt", b2g=None, tiles=None):
    return T.BeltRow(
        name=name,
        x=float(x),
        y=float(y),
        direction=d,
        kind=T.classify(name),
        belt_to_ground_type=b2g,
        tiles=tuple(tiles) if tiles else (T._tile_of(float(x), float(y)),),
    )


E, S, W, N = 4, 8, 12, 0


def test_a_straight_run_is_one_component_with_one_head_and_one_tail():
    rows = [belt(x + 0.5, 0.5, E) for x in range(5)]
    comps = T.components(rows, "test")
    assert len(comps) == 1
    c = comps[0]
    assert c.count == 5
    assert c.heads == [("transport-belt", 0.5, 0.5)]
    assert c.tails == [("transport-belt", 4.5, 0.5)]
    assert c.merges == []
    assert c.source == "test"


def test_a_gap_makes_two_components():
    rows = [belt(x + 0.5, 0.5, E) for x in (0, 1, 3, 4)]
    comps = T.components(rows, "t")
    assert [c.count for c in comps] == [2, 2]


def test_two_belts_facing_each_other_are_not_connected():
    rows = [belt(0.5, 0.5, E), belt(1.5, 0.5, W)]
    assert len(T.components(rows, "t")) == 2


def test_a_side_load_is_a_merge_with_two_heads():
    # main line east along y=0; a feeder from the south points north into (2,0)
    rows = [belt(x + 0.5, 0.5, E) for x in range(5)] + [belt(2.5, y + 0.5, N) for y in (2, 1)]
    comps = T.components(rows, "t")
    assert len(comps) == 1
    c = comps[0]
    assert c.count == 7
    assert set(c.heads) == {("transport-belt", 0.5, 0.5), ("transport-belt", 2.5, 2.5)}
    assert c.merges == [("transport-belt", 2.5, 0.5)]
    assert c.tails == [("transport-belt", 4.5, 0.5)]


def test_a_corner_is_two_legs_in_one_component():
    rows = [belt(x + 0.5, 0.5, E) for x in range(3)] + [belt(2.5, y + 0.5, S) for y in range(1, 4)]
    # the east leg's last belt at (2,0) faces east into nothing; the south leg starts at (2,1)
    # — to curve, the belt at (2,0) must itself face south:
    rows[2] = belt(2.5, 0.5, S)
    comps = T.components(rows, "t")
    assert len(comps) == 1
    assert comps[0].heads == [("transport-belt", 0.5, 0.5)]
    assert comps[0].tails == [("transport-belt", 2.5, 3.5)]


def test_underground_pair_bridges_within_reach_and_not_beyond():
    # entrance at x=0 facing east, exit at x=5 (centre-to-centre 5 = max for underground-belt)
    def run(gap):
        return [
            belt(0.5, 0.5, E, "underground-belt", "input"),
            belt(gap + 0.5, 0.5, E, "underground-belt", "output"),
            belt(gap + 1.5, 0.5, E),
        ]

    ok = T.components(run(5), "t")
    assert len(ok) == 1 and ok[0].count == 3
    too_far = T.components(run(6), "t")
    assert len(too_far) == 2


def test_an_exit_is_fed_only_by_its_pair():
    rows = [
        belt(0.5, 0.5, E),  # a belt pointing into the exit from behind — not accepted
        belt(1.5, 0.5, E, "underground-belt", "output"),
        belt(2.5, 0.5, E),
    ]
    comps = T.components(rows, "t")
    assert [c.count for c in comps] == [2, 1]


def test_splitter_is_two_tiles_and_feeds_both_fronts():
    # splitter facing east occupying tiles (2,0) and (2,1); two input belts, two output belts
    rows = [
        belt(1.5, 0.5, E), belt(1.5, 1.5, E),
        belt(2.5, 1.0, E, "splitter", tiles=[(2, 0), (2, 1)]),
        belt(3.5, 0.5, E), belt(3.5, 1.5, E),
    ]
    comps = T.components(rows, "t")
    assert len(comps) == 1
    c = comps[0]
    assert c.count == 5
    assert set(c.heads) == {("transport-belt", 1.5, 0.5), ("transport-belt", 1.5, 1.5)}
    assert set(c.tails) == {("transport-belt", 3.5, 0.5), ("transport-belt", 3.5, 1.5)}
    assert c.merges == [("splitter", 2.5, 1.0)]


# --- §9.7 neighbour invalidation: derivation beats storage --------------------


def _payload(name, x, y, direction, b2g=None, entity_type="transport-belt"):
    tile = (int(x // 1), int(y // 1))
    data = {
        "name": name,
        "type": entity_type,
        "position": {"x": x, "y": y},
        "direction": direction,
        "footprint_tiles": [{"x": tile[0], "y": tile[1]}],
        "belt_data": {"belt_to_ground_type": b2g},
        "tile_width": 1,
        "tile_height": 1,
        "bounding_box": {"min": {"x": x - 0.5, "y": y - 0.5}, "max": {"x": x + 0.5, "y": y + 0.5}},
    }
    return data


@pytest.fixture
def db():
    d = SnapshotDatabase(":memory:")
    d.ensure_schema()
    return d.connection


def test_placing_b_changes_as_component_without_touching_as_row(db):
    apply_ops.upsert_entity(db, _payload("transport-belt", 0.5, 0.5, E), 0, 0)
    reads = T.TransportReads(lambda: db, lambda: "map_entity:seq1")
    before = reads.line((0.5, 0.5))
    assert before is not None and before.count == 1 and before.tails == [("transport-belt", 0.5, 0.5)]
    row_before = db.execute("SELECT * FROM map_entity").fetchall()

    # B is placed orthogonally, pointing into A's side; A's row is never rewritten.
    apply_ops.upsert_entity(db, _payload("transport-belt", 0.5, 1.5, N), 0, 0)
    row_after = db.execute("SELECT * FROM map_entity WHERE position_y = 0.5").fetchall()
    assert row_after == [r for r in row_before if r[2] == 0.5]

    after = reads.line((0.5, 0.5))
    assert after.count == 2
    assert after.heads == [("transport-belt", 0.5, 1.5)]
    assert after.source == "map_entity:seq1"
    assert reads.shares_line_with((0.5, 0.5), (0.5, 1.5))


def test_belt_to_ground_type_is_promoted_into_transport_belt(db):
    apply_ops.upsert_entity(db, _payload("underground-belt", 0.5, 0.5, E, "input", "underground-belt"), 0, 0)
    apply_ops.upsert_entity(db, _payload("underground-belt", 4.5, 0.5, E, "output", "underground-belt"), 0, 0)
    assert db.execute(
        "SELECT belt_to_ground_type FROM transport_belt ORDER BY position_x"
    ).fetchall() == [("input",), ("output",)]
    reads = T.TransportReads(lambda: db, lambda: "map_entity:seq1")
    assert reads.lines()[0].count == 2


def test_underground_reach_comes_from_the_prototype_or_the_vanilla_constants():
    assert T.underground_max_distance("underground-belt") == 5
    assert T.underground_max_distance("fast-underground-belt") == 7
    assert T.underground_max_distance("express-underground-belt") == 9
