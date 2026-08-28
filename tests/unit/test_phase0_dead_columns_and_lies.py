"""Phase 0C: columns that were declared-but-never-written, and two live lies
on surfaces that survive the refactor (Constitution §14/§15 — a column the
agent is told about that is never populated renders as an answer).

- map_entity.tile_x/tile_y had no writer in any language (apply_ops omitted
  them; the serializer's anchor_tile was dropped into raw_data).
- ghost.placed_by had no write path although the mod emits agent_id/player_id
  in the builder block.
- reachable_view.get_resources(resource_type="ore") rebound a local and never
  filtered, so "ore" returned trees and rocks (RESOURCE-FILTER-1).
- ContainerState.contents is Dict[str,int] but Factorio 2.0 get_contents()
  returns a list of stacks, so inspecting any non-empty chest raised
  (CONTAINER-CONTENTS-1).
- infra/session/session.py's kernel bootstrap imported seven nonexistent
  classes; it is deleted, not fixed.
"""

from __future__ import annotations

import pytest

from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase
from FactoryVerse.game.infra.duckdb import apply_ops
from FactoryVerse.game.factory.entity.transform import _normalize_contents


@pytest.fixture()
def db():
    d = SnapshotDatabase(db_path=None)
    d.ensure_schema()
    return d.connection


def _entity(name="iron-chest", x=10.5, y=20.5, extra=None):
    data = {
        "name": name,
        "position": {"x": x, "y": y},
        "direction": 0,
        "bounding_box": {"min_x": x - 0.4, "min_y": y - 0.4,
                         "max_x": x + 0.4, "max_y": y + 0.4},
    }
    if extra:
        data.update(extra)
    return data


# --- tile_x / tile_y -------------------------------------------------------

def test_tile_xy_written_from_anchor_tile(db):
    apply_ops.upsert_entity(db, _entity(x=10.5, y=-20.5,
                                        extra={"anchor_tile": {"x": 10, "y": -21}}), 0, -1)
    row = db.execute("SELECT tile_x, tile_y FROM map_entity").fetchone()
    assert row == (10, -21)


def test_tile_xy_fall_back_to_floor_of_position(db):
    apply_ops.upsert_entity(db, _entity(x=3.5, y=-0.5), 0, -1)
    row = db.execute("SELECT tile_x, tile_y FROM map_entity").fetchone()
    assert row == (3, -1)
    assert db.execute("SELECT count(*) FROM map_entity WHERE tile_x IS NULL").fetchone()[0] == 0


# --- ghost.placed_by -------------------------------------------------------

def _ghost(builder):
    return {"ghost_name": "transport-belt", "position": {"x": 5.5, "y": 6.5},
            "direction": 0, "builder": builder}


@pytest.mark.parametrize("builder,expected", [
    ({"agent_id": 1, "placed_tick": 7}, "agent:1"),
    ({"player_id": 3, "placed_tick": 7}, "player:3"),
    ({"placed_by": "agent:9", "agent_id": 1}, "agent:9"),
])
def test_ghost_placed_by_is_derived_from_builder(db, builder, expected):
    apply_ops.upsert_ghost(db, _ghost(builder))
    assert db.execute("SELECT placed_by FROM ghost").fetchone()[0] == expected


def test_ghost_placed_by_null_without_builder(db):
    apply_ops.upsert_ghost(db, {"ghost_name": "transport-belt",
                                "position": {"x": 5.5, "y": 6.5}, "direction": 0})
    assert db.execute("SELECT placed_by FROM ghost").fetchone()[0] is None


# --- RESOURCE-FILTER-1 -----------------------------------------------------

class _NoActions:
    pass


def _reachable_view_with(data):
    from FactoryVerse.game.agent.reachable_view import ReachableView
    view = ReachableView.__new__(ReachableView)
    view._mining_action = None
    view._entity_ops = None
    view._walking_action = None
    view._fetch_fresh_resources_data = lambda: list(data)
    return view


MIXED = [
    {"name": "tree-01", "type": "tree", "position": {"x": 1.5, "y": 1.5}},
    {"name": "iron-ore", "type": "resource", "position": {"x": 2.5, "y": 2.5}, "amount": 100},
]


def test_get_resources_ore_excludes_trees(monkeypatch):
    import FactoryVerse.game.factory.resource.base as rb
    monkeypatch.setattr(rb, "_create_resource_from_data",
                        lambda data, *a, **k: data["name"])
    view = _reachable_view_with(MIXED)
    assert view.get_resources(resource_type="ore") == ["iron-ore"]
    assert view.get_resources(resource_type="resource") == ["iron-ore"]
    assert view.get_resources(resource_type="entity") == ["tree-01"]


# --- CONTAINER-CONTENTS-1 --------------------------------------------------

def test_normalize_contents_list_of_stacks():
    lua = [{"name": "coal", "count": 20, "quality": "normal"},
           {"name": "coal", "count": 5, "quality": "uncommon"},
           {"name": "iron-plate", "count": 3}]
    assert _normalize_contents(lua) == {"coal": 25, "iron-plate": 3}


def test_normalize_contents_dict_and_empty():
    assert _normalize_contents({"coal": 4}) == {"coal": 4}
    assert _normalize_contents({}) == {}
    assert _normalize_contents(None) == {}
    assert _normalize_contents([]) == {}


def test_transform_container_accepts_lua_list():
    from FactoryVerse.game.factory.entity.transform import _transform_container
    state = _transform_container({"contents": [{"name": "coal", "count": 2}]}, "container")
    assert state.contents == {"coal": 2}


# --- dead kernel bootstrap -------------------------------------------------

def test_session_kernel_bootstrap_is_gone():
    from FactoryVerse.infra.session.session import FactoryVerseSession
    assert not hasattr(FactoryVerseSession, "_generate_setup_code")
    assert not hasattr(FactoryVerseSession, "_inject_runtime_setup")


def test_factoriopedia_module_is_gone():
    with pytest.raises(ImportError):
        import FactoryVerse.game.factory.factoriopedia  # noqa: F401
