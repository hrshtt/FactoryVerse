"""Live contracts for entity-aware walking and walking-state reconciliation.

This module owns a dedicated Factorio server. Run it only with its opt-in gate
and a port allocation that is not shared by another campaign::

    COMPOSE_PROJECT_NAME=fv-repl-reach \
    FV_RCON_SERVER_PORT_BASE=39500 FV_RCON_CLIENT_PORT=39600 \
    FV_GAME_PORT_BASE=49197 FV_AGENT_PORT_BASE=49202 \
    FV_SNAPSHOT_PORT_BASE=49400 FV_CLIENT_SNAPSHOT_PORT=49500 \
    FV_ENABLE_UDP_PORT=49200 FV_RUN_LIVE_REACH_CONTRACTS=1 \
    uv run pytest -q tests/live/test_reach_walking_contracts.py -vv

The tests compare returned walking outcomes with direct Factorio engine truth.
They deliberately do not assert strategy, path shape, or a fixed turn budget.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

import pytest

from FactoryVerse.environment.config import FactoryVerseConfig
from FactoryVerse.evals.freeplay import FreeplayCampaignStore
from FactoryVerse.evals.freeplay.supervisor import FreeplaySupervisor
from FactoryVerse.game.agent.embodied_actions.walking import (
    WalkingEntityNotFoundError,
    WalkingNoStandableTilesError,
    WalkingTimeoutError,
    WalkingUnreachableError,
)
from FactoryVerse.game.factory.types import MapPosition


pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_docker,
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("FV_RUN_LIVE_REACH_CONTRACTS") != "1",
        reason="set FV_RUN_LIVE_REACH_CONTRACTS=1 to own the reach-contract server",
    ),
]

REPO_ROOT = Path(__file__).resolve().parents[2]
STRUCTURED_WALK_FAILURES = (
    WalkingEntityNotFoundError,
    WalkingNoStandableTilesError,
    WalkingUnreachableError,
)


@pytest.fixture(scope="module")
async def live_reach_game(tmp_path_factory):
    campaigns_root = tmp_path_factory.mktemp("reach-walking-contracts")
    store = FreeplayCampaignStore(campaigns_root, "reach-walking-contracts")
    config = FactoryVerseConfig()
    FreeplaySupervisor.create_campaign(
        store,
        repo_root=REPO_ROOT,
        infra_config=config,
        seed=44340,
        agent_id="agent_1",
        harness="pytest",
        model="reach-walking-contracts",
    )
    supervisor = FreeplaySupervisor(
        store,
        repo_root=REPO_ROOT,
        harness="pytest",
        model="reach-walking-contracts",
    )
    try:
        await supervisor.start()
        tier3 = supervisor.environment.tier3
        expected_snapshot_port = config.get_snapshot_port(tier3.instance)
        if tier3.map_api.get_udp_port() != expected_snapshot_port:
            # This suite does not own the independent snapshot-port regression.
            tier3.map_api.set_udp_port(expected_snapshot_port)
        yield {
            "supervisor": supervisor,
            "tier3": tier3,
            "tier4": supervisor.environment.tier4,
        }
    finally:
        if supervisor.environment is not None:
            with contextlib.suppress(Exception):
                await supervisor.finish(
                    reason="pytest_reach_walking_contracts",
                    checkpoint=False,
                    execution_count=0,
                )


async def _eventually(
    probe: Callable[[], Any],
    predicate: Callable[[Any], bool] = bool,
    *,
    timeout: float = 12.0,
) -> Any:
    deadline = time.monotonic() + timeout
    last_value = None
    while time.monotonic() < deadline:
        last_value = probe()
        if predicate(last_value):
            return last_value
        await asyncio.sleep(0.1)
    return last_value


def _prepare_lane(tier3, *, lane_y: int, entity_name: str | None = None) -> dict:
    """Create a flat, obstacle-free lane and optionally a target entity."""
    name = json.dumps(entity_name) if entity_name is not None else "nil"
    return tier3.run_lua(
        f"""
        local reported = remote.call('agent_1', 'get_position')
        local surface = game.surfaces[1]
        local character = surface.find_entity('character', reported)
        if not (character and character.valid) then
            error('agent_1 character is unavailable')
        end
        local start = {{x=256.5, y={lane_y + 0.5}}}
        local target = {{x=304.5, y={lane_y + 0.5}}}
        surface.request_to_generate_chunks(start, 3)
        surface.force_generate_chunk_requests()
        local area = {{{{252, {lane_y - 3}}}, {{309, {lane_y + 4}}}}}
        for _, entity in pairs(surface.find_entities_filtered{{area=area}}) do
            if entity ~= character and entity.valid then entity.destroy() end
        end
        local tiles = {{}}
        for x=252,308 do
            for y={lane_y - 3},{lane_y + 3} do
                tiles[#tiles + 1] = {{name='grass-1', position={{x=x, y=y}}}}
            end
        end
        surface.set_tiles(tiles, true, true, true, true)
        character.teleport(start, surface)
        character.walking_state = {{walking=false}}
        local created = nil
        if {name} then
            created = surface.create_entity{{name={name}, position=target}}
            if not created then error('failed to create target ' .. {name}) end
        end
        return {{
            start={{x=start.x, y=start.y}},
            target={{x=target.x, y=target.y}},
            name=created and created.name or nil
        }}
        """
    )


def _engine_target_truth(tier3, name: str, position: MapPosition) -> dict:
    quoted_name = json.dumps(name)
    return tier3.run_lua(
        f"""
        local reported = remote.call('agent_1', 'get_position')
        local surface = game.surfaces[1]
        local character = surface.find_entity('character', reported)
        local target = surface.find_entity(
            {quoted_name}, {{x={position.x}, y={position.y}}}
        )
        local p = character.position
        return {{
            target_valid=target ~= nil and target.valid,
            can_reach=target ~= nil and target.valid and character.can_reach_entity(target),
            distance=target and math.sqrt(
                (target.position.x-p.x)^2 + (target.position.y-p.y)^2
            ) or nil,
            character_position={{x=p.x, y=p.y}},
            character_walking=character.walking_state.walking
        }}
        """
    )


def _activity_state(tier3) -> dict:
    return tier3.run_lua(
        "return remote.call('agent_1', 'inspect', true)"
    )["state"]["walking"]


def _teleport_agent_character(tier3, position: MapPosition) -> None:
    tier3.run_lua(
        f"""
        local reported = remote.call('agent_1', 'get_position')
        local surface = game.surfaces[1]
        local character = surface.find_entity('character', reported)
        if not (character and character.valid) then
            error('agent_1 character is unavailable')
        end
        character.teleport({{x={position.x}, y={position.y}}}, surface)
        return true
        """
    )


def _insert_agent_item(tier3, item_name: str, count: int = 1) -> None:
    quoted_name = json.dumps(item_name)
    inserted = tier3.run_lua(
        f"""
        local reported = remote.call('agent_1', 'get_position')
        local character = game.surfaces[1].find_entity('character', reported)
        local inventory = character and character.get_main_inventory()
        if not inventory then error('agent_1 inventory is unavailable') end
        return inventory.insert{{name={quoted_name}, count={count}}}
        """
    )
    assert inserted == count


async def test_remote_entity_walk_success_establishes_engine_and_api_reach(
    live_reach_game,
):
    tier3 = live_reach_game["tier3"]
    tier4 = live_reach_game["tier4"]
    setup = _prepare_lane(tier3, lane_y=0)
    position = MapPosition(**setup["target"])
    start = MapPosition(**setup["start"])
    _teleport_agent_character(
        tier3, MapPosition(x=position.x - 3.0, y=position.y)
    )
    _insert_agent_item(tier3, "wooden-chest")
    placed = tier4._placement.place("wooden-chest", position)
    assert placed.success is True
    _teleport_agent_character(tier3, start)

    sql = (
        "SELECT * FROM map_entity WHERE entity_name = 'wooden-chest' "
        f"AND position_x = {position.x} AND position_y = {position.y} LIMIT 1"
    )
    remote_entity = await _eventually(lambda: tier4.remote_view.get_entity(sql))
    assert remote_entity is not None

    try:
        final_position = await remote_entity.walk_to(timeout=30)
    except STRUCTURED_WALK_FAILURES as exc:
        pytest.fail(f"clear-lane entity walk returned structured failure: {exc}")

    truth = _engine_target_truth(tier3, "wooden-chest", position)
    reachable = tier4.reachable_view.get_entity("wooden-chest", position)
    assert truth["target_valid"] is True
    assert truth["can_reach"] is True, {"final": final_position, "engine": truth}
    inspection = remote_entity.inspect()
    assert inspection is not None
    assert reachable is not None


async def test_direct_entity_aware_walk_to_resource_establishes_resource_reach(
    live_reach_game,
):
    tier3 = live_reach_game["tier3"]
    tier4 = live_reach_game["tier4"]
    setup = _prepare_lane(tier3, lane_y=16, entity_name="tree-01")
    position = MapPosition(**setup["target"])

    try:
        final_position = await tier4._movement.walk_to_entity(
            "tree-01", position, timeout=30
        )
    except STRUCTURED_WALK_FAILURES as exc:
        pytest.fail(f"clear-lane resource walk returned structured failure: {exc}")

    truth = _engine_target_truth(tier3, "tree-01", position)
    reachable = tier4.reachable_view.get_resource("tree-01", position)
    assert truth["target_valid"] is True
    assert truth["can_reach"] is True, {"final": final_position, "engine": truth}
    inspection = tier4._entity_ops.inspect_entity("tree-01", position)
    assert inspection is not None
    assert reachable is not None


async def test_stop_reconciles_reported_walking_activity(live_reach_game):
    tier3 = live_reach_game["tier3"]
    movement = live_reach_game["tier4"]._movement
    setup = _prepare_lane(tier3, lane_y=32)
    target = MapPosition(**setup["target"])

    await movement.walk_to(target, timeout=30)
    before_stop = _activity_state(tier3)
    assert before_stop["active"] is False
    assert before_stop.get("path_id") is None
    try:
        stop_result = movement.stop()
        stop_error = None
    except RuntimeError as exc:
        stop_result = None
        stop_error = str(exc)
    after_stop = _activity_state(tier3)

    assert after_stop["active"] is False, {
        "before_stop": before_stop,
        "stop_result": stop_result,
        "stop_error": stop_error,
        "after_stop": after_stop,
    }


async def test_timed_out_walk_allows_a_clean_second_walk(live_reach_game):
    tier3 = live_reach_game["tier3"]
    movement = live_reach_game["tier4"]._movement
    setup = _prepare_lane(tier3, lane_y=48)
    distant = MapPosition(**setup["target"])

    with pytest.raises(WalkingTimeoutError):
        await movement.walk_to(distant, timeout=0.001)

    current = movement.current_position
    second_target = MapPosition(x=current.x + 3.0, y=current.y)
    final = await movement.walk_to(second_target, timeout=15)
    assert abs(final.x - second_target.x) < 0.75
    assert abs(final.y - second_target.y) < 0.75
    engine_walking = tier3.run_lua(
        """
        local reported = remote.call('agent_1', 'get_position')
        local character = game.surfaces[1].find_entity('character', reported)
        return character.walking_state.walking
        """
    )
    assert engine_walking is False
