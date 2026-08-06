import asyncio
import json

import pytest

from FactoryVerse.game.agent.embodied_actions.inventory import AgentInventory
from FactoryVerse.game.agent.embodied_actions.walking import (
    MovementAction,
    WalkingTimeoutError,
)
from FactoryVerse.game.agent.infra.rcon_handler import RconHandler
from FactoryVerse.game.agent.infra.async_listener import AsyncActionListener
from FactoryVerse.game.factory.types import MapPosition
from FactoryVerse.game.infra.duckdb.query import QueryExecutor


class _RawRcon:
    def __init__(self, response):
        self.response = response

    def send_command(self, command):
        return self.response


def test_rcon_preserves_structured_domain_failure_for_typed_action():
    handler = RconHandler(
        _RawRcon(
            json.dumps(
                {
                    "success": False,
                    "failure_type": "entity_not_found",
                    "message": "iron-ore not found at position",
                }
            )
        ),
        "agent_1",
    )

    result = handler.execute_and_parse_json("return true")

    assert result["failure_type"] == "entity_not_found"
    assert "not found" in result["message"]


def test_remote_resource_tile_is_restored_to_factorio_entity_center():
    executor = object.__new__(QueryExecutor)

    tile = executor._row_to_resource_data(
        {"name": "iron-ore", "position_x": -19.0, "position_y": -50.0, "amount": 900}
    )
    rock = executor._row_to_resource_data(
        {
            "name": "rock-big",
            "entity_type": "simple-entity",
            "position_x": -19.0,
            "position_y": -50.0,
        }
    )

    assert tile["position"] == {"x": -18.5, "y": -49.5}
    assert rock["position"] == {"x": -19.0, "y": -50.0}


class _WalkingRcon:
    def __init__(self):
        self.methods = []

    def build_command(self, method, *args):
        self.methods.append(method)
        return method

    def execute_and_parse_json(self, command):
        if command == "walk_to":
            return {"success": True, "queued": True, "action_id": "walk-7"}
        if command == "stop_walking":
            return {"success": True, "position": {"x": 0, "y": 0}}
        raise AssertionError(command)


class _TimeoutListener:
    async def await_action(self, response, timeout=None):
        raise asyncio.TimeoutError


@pytest.mark.asyncio
async def test_walking_timeout_cancels_factorio_action_before_returning():
    rcon = _WalkingRcon()
    movement = MovementAction(rcon, _TimeoutListener())

    with pytest.raises(WalkingTimeoutError, match="stop_walking was issued"):
        await movement.walk_to(MapPosition(x=10, y=20), timeout=0.01)

    assert rcon.methods == ["walk_to", "stop_walking"]


@pytest.mark.asyncio
async def test_action_wait_honors_progress_extended_deadline():
    listener = object.__new__(AsyncActionListener)
    action_id = "walk-progress"
    event = asyncio.Event()
    loop = asyncio.get_running_loop()
    listener.timeout = 0.05
    listener.pending_actions = {action_id: event}
    listener.action_results = {action_id: None}
    listener.action_progress = {action_id: {}}
    listener.action_timeouts = {}
    # The implementation uses wall-clock time for cross-thread UDP updates.
    import time

    listener.action_timeouts[action_id] = time.time() + 0.01
    listener.event_loops = {action_id: loop}

    async def complete_after_extension():
        await asyncio.sleep(0.005)
        listener.action_timeouts[action_id] = time.time() + 0.05
        await asyncio.sleep(0.02)
        listener.action_results[action_id] = {"status": "completed"}
        event.set()

    task = asyncio.create_task(complete_after_extension())
    result = await listener.wait_for_action(action_id, timeout=0.01)
    await task

    assert result == {"status": "completed"}


def test_item_stack_default_means_one_exact_transfer_stack(monkeypatch):
    inventory = object.__new__(AgentInventory)
    inventory._placement = object()
    monkeypatch.setattr(inventory, "check_total", lambda _name: 25)

    stacks = inventory.create_item_stacks("coal", 12, strict=True)
    all_stacks = inventory.create_item_stacks(
        "coal", 12, number_of_stacks="max", strict=True
    )

    assert [stack.count for stack in stacks] == [12]
    assert [stack.count for stack in all_stacks] == [12, 12]
