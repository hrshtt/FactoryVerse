"""Live unattended entity-persistence contracts for freeplay.

This file owns a disposable FreeplaySupervisor server.  It compares direct
Factorio engine truth with the DuckDB materialization across multiple snapshot
and status-dump cycles while the embodied actor remains idle.

Run only on ports not owned by another campaign::

    COMPOSE_PROJECT_NAME=fv-repl-persistence \
    FV_RCON_SERVER_PORT_BASE=41500 FV_RCON_CLIENT_PORT=41600 \
    FV_GAME_PORT_BASE=51197 FV_AGENT_PORT_BASE=51202 \
    FV_SNAPSHOT_PORT_BASE=51400 FV_CLIENT_SNAPSHOT_PORT=51500 \
    FV_ENABLE_UDP_PORT=51200 \
    FV_RUN_LIVE_ENTITY_PERSISTENCE_CONTRACTS=1 \
    uv run pytest -q tests/live/test_entity_persistence_contracts.py -vv
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

import pytest

from FactoryVerse.environment.config import FactoryVerseConfig
from FactoryVerse.evals.freeplay import FreeplayCampaignStore
from FactoryVerse.evals.freeplay.supervisor import FreeplaySupervisor


pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_docker,
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("FV_RUN_LIVE_ENTITY_PERSISTENCE_CONTRACTS") != "1",
        reason=(
            "set FV_RUN_LIVE_ENTITY_PERSISTENCE_CONTRACTS=1 to run the live "
            "entity-persistence contract"
        ),
    ),
]

REPO_ROOT = Path(__file__).resolve().parents[2]
GAME_SPEED = 8


@pytest.fixture(scope="module")
async def persistence_game(tmp_path_factory):
    campaigns_root = tmp_path_factory.mktemp("entity-persistence")
    store = FreeplayCampaignStore(campaigns_root, "entity-persistence")
    config = FactoryVerseConfig()
    FreeplaySupervisor.create_campaign(
        store,
        repo_root=REPO_ROOT,
        infra_config=config,
        seed=44340,
        agent_id="agent_1",
        harness="pytest",
        model="entity-persistence-contract",
    )
    supervisor = FreeplaySupervisor(
        store,
        repo_root=REPO_ROOT,
        harness="pytest",
        model="entity-persistence-contract",
    )
    try:
        await supervisor.start()
        tier3 = supervisor.environment.tier3
        assert tier3.run_lua("return game.speed") == GAME_SPEED

        # Keep this contract about entity persistence rather than the separate
        # snapshot-port boot regression.  Record and repair only this disposable
        # test server if that independent wiring defect is present.
        expected_snapshot_port = config.get_snapshot_port(tier3.instance)
        boot_snapshot_port = tier3.map_api.get_udp_port()
        if boot_snapshot_port != expected_snapshot_port:
            tier3.map_api.set_udp_port(expected_snapshot_port)

        yield {
            "supervisor": supervisor,
            "tier3": tier3,
            "remote_view": supervisor.environment.tier4.remote_view,
            "boot_snapshot_port": boot_snapshot_port,
            "expected_snapshot_port": expected_snapshot_port,
        }
    finally:
        await supervisor.finish(
            reason="pytest_entity_persistence_contract",
            checkpoint=False,
            execution_count=0,
        )


async def _eventually(
    probe: Callable[[], Any],
    predicate: Callable[[Any], bool] = bool,
    *,
    timeout: float = 15.0,
) -> Any:
    deadline = time.monotonic() + timeout
    last_value = None
    while time.monotonic() < deadline:
        last_value = probe()
        if predicate(last_value):
            return last_value
        await asyncio.sleep(0.1)
    return last_value


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _create_stone_buffer_cell(tier3, view) -> dict[str, Any]:
    """Create a deterministic drill-to-chest cell on a rich natural patch."""
    candidates = view.query(
        "SELECT name, position_x, position_y, amount FROM resource_tile "
        "WHERE name='stone' AND amount >= 250 "
        "ORDER BY position_x * position_x + position_y * position_y LIMIT 256"
    )
    assert candidates, "bootstrap DuckDB contains no rich natural stone tiles"
    candidates_json = json.dumps(json.dumps(candidates))
    lua = """
        local surface = game.surfaces[1]
        local candidates = helpers.json_to_table(__CANDIDATES_JSON__)
        local directions = {
            defines.direction.north,
            defines.direction.east,
            defines.direction.south,
            defines.direction.west,
        }

        for _, candidate in pairs(candidates) do
            local resource = surface.find_entity(candidate.name, {
                x=candidate.position_x + 0.5,
                y=candidate.position_y + 0.5,
            })
            if resource and resource.valid and resource.amount >= 250 then
                -- Resource entities sit on half-tiles while the 2x2 drill's
                -- canonical centre is integral.  Centre the drill over this
                -- exact resource; merely placing near a resource is not proof
                -- that the engine considers it minable.
                local drill_position = {
                    x=math.floor(resource.position.x) + 1,
                    y=math.floor(resource.position.y) + 1,
                }
                for _, direction in pairs(directions) do
                    if surface.can_place_entity{
                                name='burner-mining-drill',
                                position=drill_position,
                                direction=direction,
                                force='player'
                            } then
                                local trial = surface.create_entity{
                                    name='burner-mining-drill',
                                    position=drill_position,
                                    direction=direction,
                                    force='player'
                                }
                                if trial then
                                    local drop = trial.drop_position
                                    local chest_position = {
                                        x=math.floor(drop.x) + 0.5,
                                        y=math.floor(drop.y) + 0.5,
                                    }
                                    trial.destroy()

                                    if surface.can_place_entity{
                                        name='wooden-chest',
                                        position=chest_position,
                                        force='player'
                                    } then
                                        local drill = surface.create_entity{
                                            name='burner-mining-drill',
                                            position=drill_position,
                                            direction=direction,
                                            force='player',
                                            raise_built=true
                                        }
                                        local chest = surface.create_entity{
                                            name='wooden-chest',
                                            position=chest_position,
                                            force='player',
                                            raise_built=true
                                        }
                                        if drill and chest then
                                            drill.get_fuel_inventory().insert{
                                                name='coal', count=50
                                            }
                                            return {
                                                created_tick=game.tick,
                                                drill={
                                                    name=drill.name,
                                                    position={
                                                        x=drill.position.x,
                                                        y=drill.position.y,
                                                    },
                                                    unit_number=drill.unit_number,
                                                },
                                                chest={
                                                    name=chest.name,
                                                    position={
                                                        x=chest.position.x,
                                                        y=chest.position.y,
                                                    },
                                                    unit_number=chest.unit_number,
                                                },
                                                seed_resource={
                                                    name=resource.name,
                                                    position={
                                                        x=resource.position.x,
                                                        y=resource.position.y,
                                                    },
                                                    amount=resource.amount,
                                                },
                                            }
                                        end
                                        if drill and drill.valid then drill.destroy() end
                                        if chest and chest.valid then chest.destroy() end
                                    end
                                end
                    end
                end
            end
        end
        error('no natural stone patch supports a burner drill-to-chest cell')
        """
    return tier3.run_lua(lua.replace("__CANDIDATES_JSON__", candidates_json))


def _engine_cell_state(tier3, rig: dict[str, Any]) -> dict[str, Any]:
    drill = rig["drill"]
    chest = rig["chest"]
    return tier3.run_lua(
        f"""
        local surface = game.surfaces[1]
        local drill = surface.find_entity(
            {_sql_literal(drill['name'])},
            {{x={drill['position']['x']}, y={drill['position']['y']}}})
        local chest = surface.find_entity(
            {_sql_literal(chest['name'])},
            {{x={chest['position']['x']}, y={chest['position']['y']}}})
        local result = {{tick=game.tick}}
        result.drill = {{exists=drill ~= nil and drill.valid}}
        if drill and drill.valid then
            local target = drill.mining_target
            local fuel = drill.get_fuel_inventory()
            result.drill.unit_number = drill.unit_number
            result.drill.status = drill.status
            result.drill.status_name = prototypes.entity[drill.name] and
                ({json.dumps('present')} or nil)
            for name, value in pairs(defines.entity_status) do
                if value == drill.status then result.drill.status_name = name end
            end
            result.drill.fuel_count = fuel and fuel.get_item_count('coal') or 0
            result.drill.target_name = target and target.name or nil
            result.drill.target_amount = target and target.amount or nil
        end
        result.chest = {{exists=chest ~= nil and chest.valid}}
        if chest and chest.valid then
            local inventory = chest.get_inventory(defines.inventory.chest)
            result.chest.unit_number = chest.unit_number
            result.chest.stone_count = inventory.get_item_count('stone')
            result.chest.is_full = inventory.is_full()
        end
        return result
        """
    )


def _status_rows(view, entity_name: str, position: dict[str, float]) -> list[dict[str, Any]]:
    summary = view.status(max_positions=100000)
    assert summary.source.startswith("status_dump:"), summary.source
    rows = []
    for group in summary.groups.values():
        for name, x, y in group.entities:
            if (
                name == entity_name
                and abs(x - position["x"]) < 1e-6
                and abs(y - position["y"]) < 1e-6
            ):
                rows.append({
                    "entity_name": name, "position_x": x, "position_y": y,
                    "status_name": group.status, "tick": summary.tick,
                })
    return rows


def _database_cell_state(view, rig: dict[str, Any]) -> dict[str, Any]:
    drill = rig["drill"]
    chest = rig["chest"]
    drill_key = (
        f"entity_name={_sql_literal(drill['name'])} "
        f"AND position_x={drill['position']['x']} "
        f"AND position_y={drill['position']['y']}"
    )
    chest_key = (
        f"entity_name={_sql_literal(chest['name'])} "
        f"AND position_x={chest['position']['x']} "
        f"AND position_y={chest['position']['y']}"
    )
    seed = rig["seed_resource"]
    return {
        "drill_map": view.query(
            "SELECT entity_name, position_x, position_y, direction, raw_data "
            f"FROM map_entity WHERE {drill_key}"
        ),
        "chest_map": view.query(
            "SELECT entity_name, position_x, position_y, raw_data "
            f"FROM map_entity WHERE {chest_key}"
        ),
        "drill_component": view.query(
            "SELECT entity_name, position_x, position_y, direction, mining_target "
            f"FROM mining_drill WHERE {drill_key}"
        ),
        # Status has no event backing and is not a table (Constitution §10):
        # read it from the newest status dump block through remote_view.status()
        # and keep the same row shape the old query produced.
        "status": _status_rows(view, drill["name"], drill["position"]),
        "seed_resource": view.query(
            "SELECT name, position_x, position_y, amount FROM resource_tile "
            f"WHERE name={_sql_literal(seed['name'])} "
            f"AND position_x={int(seed['position']['x'] // 1)} "
            f"AND position_y={int(seed['position']['y'] // 1)}"
        ),
    }


def _destroy_cell(tier3, rig: dict[str, Any]) -> None:
    drill = rig["drill"]
    chest = rig["chest"]
    tier3.run_lua(
        f"""
        local surface = game.surfaces[1]
        local drill = surface.find_entity(
            {_sql_literal(drill['name'])},
            {{x={drill['position']['x']}, y={drill['position']['y']}}})
        local chest = surface.find_entity(
            {_sql_literal(chest['name'])},
            {{x={chest['position']['x']}, y={chest['position']['y']}}})
        if drill and drill.valid then drill.destroy{{raise_destroy=true}} end
        if chest and chest.valid then chest.destroy{{raise_destroy=true}} end
        return true
        """
    )


async def test_fueled_drill_persists_in_engine_and_database_while_actor_is_idle(
    persistence_game,
):
    tier3 = persistence_game["tier3"]
    view = persistence_game["remote_view"]
    rig = _create_stone_buffer_cell(tier3, view)
    try:
        actor_before = tier3.run_lua("return remote.call('agent_1', 'inspect', true)")
        assert all(
            not actor_before["state"][activity]["active"]
            for activity in ("walking", "mining", "crafting")
        ), actor_before

        initial = await _eventually(
            lambda: {
                "engine": _engine_cell_state(tier3, rig),
                "database": _database_cell_state(view, rig),
            },
            lambda state: (
                state["engine"]["drill"]["exists"]
                and state["engine"]["drill"].get("target_name") == "stone"
                and len(state["database"]["drill_map"]) == 1
                and len(state["database"]["chest_map"]) == 1
                and len(state["database"]["status"]) == 1
                and len(state["database"]["seed_resource"]) == 1
            ),
        )
        assert len(initial["database"]["drill_map"]) == 1, initial
        assert len(initial["database"]["chest_map"]) == 1, initial
        assert len(initial["database"]["status"]) == 1, initial
        assert len(initial["database"]["seed_resource"]) == 1, initial

        initial_tick = initial["engine"]["tick"]
        initial_output = initial["engine"]["chest"].get("stone_count", 0)
        final = await _eventually(
            lambda: {
                "engine": _engine_cell_state(tier3, rig),
                "database": _database_cell_state(view, rig),
            },
            lambda state: (
                state["engine"]["tick"] >= initial_tick + 600
                and state["engine"]["chest"].get("stone_count", 0)
                > initial_output
                and len(state["database"]["drill_map"]) == 1
                and len(state["database"]["chest_map"]) == 1
                and len(state["database"]["status"]) == 1
                and state["database"]["status"][0]["tick"]
                > initial["database"]["status"][0]["tick"]
            ),
            timeout=20.0,
        )

        engine = final["engine"]
        database = final["database"]
        assert engine["drill"]["exists"] is True, final
        assert engine["drill"]["unit_number"] == rig["drill"]["unit_number"]
        assert engine["chest"]["exists"] is True, final
        assert engine["chest"]["unit_number"] == rig["chest"]["unit_number"]
        assert engine["chest"]["stone_count"] > initial_output, {
            "reason": "production_did_not_advance",
            "initial_output": initial_output,
            "engine": engine,
        }
        assert engine["drill"]["target_name"] == "stone"
        assert engine["drill"]["target_amount"] > 0
        assert engine["drill"]["fuel_count"] > 0
        assert engine["chest"]["is_full"] is False

        assert len(database["drill_map"]) == 1, final
        assert len(database["chest_map"]) == 1, final
        assert len(database["status"]) == 1, final
        assert database["status"][0]["tick"] > initial["database"]["status"][0]["tick"]
        assert len(database["seed_resource"]) == 1, final

        actor_after = tier3.run_lua("return remote.call('agent_1', 'inspect', true)")
        assert actor_after["position"] == actor_before["position"]
        assert all(
            not actor_after["state"][activity]["active"]
            for activity in ("walking", "mining", "crafting")
        ), actor_after
    finally:
        _destroy_cell(tier3, rig)


async def test_live_created_drill_reaches_mining_drill_component_table(
    persistence_game,
):
    """Keep the component-table defect separate from BUG-004 persistence."""
    tier3 = persistence_game["tier3"]
    view = persistence_game["remote_view"]
    rig = _create_stone_buffer_cell(tier3, view)
    try:
        rows = await _eventually(
            lambda: _database_cell_state(view, rig)["drill_component"],
            timeout=5.0,
        )
        assert len(rows) == 1
        assert rows[0]["mining_target"] == "stone"
    finally:
        _destroy_cell(tier3, rig)
