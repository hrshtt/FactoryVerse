from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from FactoryVerse.game.agent.embodied_actions.place_entity import PlacementAction
from FactoryVerse.game.agent.remote_view import RemoteView
from FactoryVerse.game.factory.item.base import PlaceableItem
from FactoryVerse.game.factory.types import Direction, MapPosition
from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase
from FactoryVerse.game.infra.duckdb.query import QueryExecutor


class _PlacementRecorder:
    def __init__(self):
        self.calls = []

    def place(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return SimpleNamespace(success=True)


def test_placeable_item_ghost_forwards_the_public_label_contract():
    placement = _PlacementRecorder()
    item = PlaceableItem("wooden-chest", placement)
    position = MapPosition(x=4.5, y=-2.5)

    assert item.place_ghost(position, label="storage-intent") is True
    assert placement.calls == [
        (
            ("wooden-chest", position, Direction.NORTH),
            {"ghost": True, "label": "storage-intent"},
        )
    ]


class _PlacementRcon:
    def build_command(self, *args):
        return args

    def execute_and_parse_json(self, _command):
        return {
            "success": True,
            "entity_name": "wooden-chest",
            "position": {"x": 8.5, "y": 9.5},
            "direction": Direction.EAST.value,
        }


def test_placement_waits_for_owned_state_before_returning():
    placement = PlacementAction(_PlacementRcon(), SimpleNamespace(), SimpleNamespace())
    observed = []
    placement.set_state_barrier(
        lambda name, x, y, ghost, label: observed.append(
            (name, x, y, ghost, label)
        )
    )

    result = placement.place(
        "wooden-chest",
        MapPosition(x=8.5, y=9.5),
        direction=Direction.EAST,
        ghost=True,
        label="planned-storage",
    )

    assert result.success is True
    assert observed == [
        ("wooden-chest", 8.5, 9.5, True, "planned-storage")
    ]


class _DelayedPlacementSync:
    def __init__(self, connection, *, ghost: bool):
        self.connection = connection
        self.ghost = ghost
        self.flushes = 0

    def flush_pending(self):
        self.flushes += 1
        if self.flushes != 2:
            return 0
        if self.ghost:
            self.connection.execute(
                """
                INSERT INTO ghost
                    (ghost_name, position_x, position_y, chunk_x, chunk_y, label)
                VALUES ('wooden-chest', 8.5, 9.5, 0, 0, 'storage-intent')
                """
            )
        else:
            self.connection.execute(
                """
                DELETE FROM ghost
                WHERE ghost_name = 'wooden-chest'
                  AND position_x = 8.5 AND position_y = 9.5
                """
            )
            self.connection.execute(
                """
                INSERT INTO map_entity
                    (entity_name, position_x, position_y, chunk_x, chunk_y, label)
                VALUES ('wooden-chest', 8.5, 9.5, 0, 0, 'storage-intent')
                """
            )
        return 1


def _remote_view_for_barrier(database, sync):
    view = object.__new__(RemoteView)
    view._loaded = True
    view._database = database
    view._db_lock = threading.Lock()
    view._sync = sync
    return view


def test_remote_view_ghost_barrier_waits_for_late_snapshot_insert():
    database = SnapshotDatabase()
    database.ensure_schema()
    sync = _DelayedPlacementSync(database.connection, ghost=True)
    view = _remote_view_for_barrier(database, sync)

    view.wait_for_placement(
        "wooden-chest", 8.5, 9.5, True, "storage-intent", timeout=1.0
    )

    assert sync.flushes == 2
    database.close()


def test_remote_view_real_barrier_waits_for_atomic_ghost_conversion():
    database = SnapshotDatabase()
    database.ensure_schema()
    database.connection.execute(
        """
        INSERT INTO ghost
            (ghost_name, position_x, position_y, chunk_x, chunk_y, label)
        VALUES ('wooden-chest', 8.5, 9.5, 0, 0, 'storage-intent')
        """
    )
    sync = _DelayedPlacementSync(database.connection, ghost=False)
    view = _remote_view_for_barrier(database, sync)

    view.wait_for_placement(
        "wooden-chest", 8.5, 9.5, False, "storage-intent", timeout=1.0
    )

    assert sync.flushes == 2
    assert database.connection.execute("SELECT count(*) FROM ghost").fetchone()[0] == 0
    database.close()


def test_typed_ghost_route_keeps_north_direction_and_plan_label():
    database = SnapshotDatabase()
    database.ensure_schema()
    executor = QueryExecutor(
        database.connection,
        entity_ops=SimpleNamespace(),
        place_ops=SimpleNamespace(),
        walking_action=SimpleNamespace(),
        mining_action=SimpleNamespace(),
    )

    ghost = executor._construct_ghost(
        {
            "ghost_name": "wooden-chest",
            "position_x": 8.5,
            "position_y": 9.5,
            "direction": "north",
            "label": "storage-intent",
            "placed_tick": 42,
            "raw_data": (
                '{"name":"entity-ghost","ghost_name":"wooden-chest",'
                '"position":{"x":8.5,"y":9.5},"direction":0,'
                '"builder":{"label":"storage-intent","placed_tick":42}}'
            ),
        }
    )

    assert ghost is not None
    assert ghost.direction == Direction.NORTH
    assert ghost.label == "storage-intent"
    assert ghost.placed_tick == 42
    database.close()


class _Plan(SimpleNamespace):
    """What survives of GhostPlan: a validated position list (GHOST §4.2).
    ``validate`` mirrors the old commit-time revalidation the builder calls."""

    def validate(self, validator):
        results = validator.validate_batch(
            self.entity_name, [p for p, _ in self.positions], [d for _, d in self.positions]
        )
        self.valid = all(results)
        return self.valid


class _Inventory:
    def __init__(self, count):
        self.count = count

    def check_total(self, _name):
        return self.count

    @property
    def item_stacks(self):
        return [SimpleNamespace(name="wooden-chest", count=self.count)]


