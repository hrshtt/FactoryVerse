"""Live engine-versus-DuckDB coherence contracts.

These tests deliberately compare Factorio engine truth with the materialized
DuckDB view after a mutation.  They are not model or harness-policy tests.

Run this file on ports that are not owned by another campaign::

    FV_RUN_LIVE_DATABASE_COHERENCE_TESTS=1 \
    FV_RCON_SERVER_PORT_BASE=39300 FV_RCON_CLIENT_PORT=39400 \
    FV_GAME_PORT_BASE=48197 FV_AGENT_PORT_BASE=48202 \
    FV_SNAPSHOT_PORT_BASE=48400 FV_CLIENT_SNAPSHOT_PORT=48500 \
    FV_ENABLE_UDP_PORT=48200 \
    uv run pytest -q tests/live/test_database_coherence.py -vv

The module fixture records the snapshot port observed immediately after boot,
then repairs a mismatch for the remainder of the test-only campaign.  This
keeps the boot wiring regression visible while allowing the rest of the
database feeds to be tested independently.
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
        os.environ.get("FV_RUN_LIVE_DATABASE_COHERENCE_TESTS") != "1",
        reason="set FV_RUN_LIVE_DATABASE_COHERENCE_TESTS=1 to run live DB contracts",
    ),
]

REPO_ROOT = Path(__file__).resolve().parents[2]
GAME_SPEED = 8

# Every runtime table has an explicit live contract below.  Keeping this list
# beside the tests makes a newly added schema table fail review visibly instead
# of silently acquiring no engine-versus-view coverage.
DATABASE_TABLE_COVERAGE = {
    "map_entity": "test_agent_placement_reaches_map_entity",
    "ghost": "test_ghost_create_rotate_remove_matches_engine",
    "resource_tile": "test_bootstrap_spatial_tables_match_engine_samples",
    "resource_entity": "test_resource_entity_removal_matches_engine",
    "water_tile": "test_bootstrap_spatial_tables_match_engine_samples",
    "chunk_snapshot_meta": "test_bootstrap_spatial_tables_match_engine_samples",
    "footprint_tiles": "test_live_entity_updates_all_derived_tables",
    "inserter": "test_live_entity_updates_all_derived_tables",
    "transport_belt": "test_live_entity_updates_all_derived_tables",
    "mining_drill": "test_live_entity_updates_all_derived_tables",
    "assembler": "test_live_entity_updates_all_derived_tables",
    "agent_manual_production_statistics": "test_agent_statistics_feeds_advance",
}
# Not tables (Constitution §10 — no event backs them; cut 2026-08-29, API §4.6):
# status, power and force production are read on demand through remote_view
# and stamped with their source. Their live contracts are the two feed tests
# below, which now exercise the readers rather than a reducer.


@pytest.fixture(scope="module")
async def coherent_game(tmp_path_factory):
    campaigns_root = tmp_path_factory.mktemp("database-coherence")
    store = FreeplayCampaignStore(campaigns_root, "database-coherence")
    config = FactoryVerseConfig()
    FreeplaySupervisor.create_campaign(
        store,
        repo_root=REPO_ROOT,
        infra_config=config,
        seed=44340,
        agent_id="agent_1",
        harness="pytest",
        model="database-coherence",
    )
    supervisor = FreeplaySupervisor(
        store,
        repo_root=REPO_ROOT,
        harness="pytest",
        model="database-coherence",
    )
    try:
        await supervisor.start()

        tier3 = supervisor.environment.tier3
        actual_speed = tier3.run_lua("return game.speed")
        assert actual_speed == GAME_SPEED

        expected_snapshot_port = config.get_snapshot_port(tier3.instance)
        boot_snapshot_port = tier3.map_api.get_udp_port()
        if boot_snapshot_port != expected_snapshot_port:
            # Test-only compensation: preserve the boot mismatch for the first
            # assertion, then unblock every downstream live-feed contract.
            tier3.map_api.set_udp_port(expected_snapshot_port)
        repaired_snapshot_port = tier3.map_api.get_udp_port()
        assert repaired_snapshot_port == expected_snapshot_port

        context = {
            "supervisor": supervisor,
            "tier3": tier3,
            "remote_view": supervisor.environment.tier4.remote_view,
            "boot_snapshot_port": boot_snapshot_port,
            "expected_snapshot_port": expected_snapshot_port,
        }
        yield context
    finally:
        await supervisor.finish(
            reason="pytest_database_coherence",
            checkpoint=False,
            execution_count=0,
        )


async def _eventually(
    probe: Callable[[], Any],
    predicate: Callable[[Any], bool] = bool,
    *,
    timeout: float = 8.0,
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


def _find_open_position(tier3, entity_name: str, *, offset: int = 0) -> dict[str, float]:
    name = json.dumps(entity_name)
    return tier3.run_lua(
        f"""
        local agent = remote.call('agent_1', 'get_position')
        local surface = game.surfaces[1]
        local base_x = math.floor(agent.x)
        local base_y = math.floor(agent.y)
        for radius = 2, 9 do
            for dx = -radius, radius do
                for dy = -radius, radius do
                    if math.max(math.abs(dx), math.abs(dy)) == radius then
                        local p = {{x=base_x + dx + 0.5, y=base_y + dy + 0.5}}
                        if (dx * 31 + dy * 17) % 7 == {offset % 7} and
                           surface.can_place_entity{{
                               name={name}, position=p, force='player',
                               build_check_type=defines.build_check_type.manual
                           }} then
                            return p
                        end
                    end
                end
            end
        end
        error('no open position for ' .. {name})
        """
    )


def _place_with_agent(
    tier3,
    entity_name: str,
    *,
    ghost: bool = False,
    label: str | None = None,
    direction: int = 0,
    offset: int = 0,
) -> dict[str, Any]:
    position = _find_open_position(tier3, entity_name, offset=offset)
    if not ghost:
        tier3.run_lua(
            "remote.call('admin', 'add_items', 1, {["
            + json.dumps(entity_name)
            + "]=1}); return true"
        )
    label_lua = "nil" if label is None else json.dumps(label)
    result = tier3.run_lua(
        "return remote.call('agent_1', 'place_entity', "
        f"{json.dumps(entity_name)}, "
        f"{{x={position['x']}, y={position['y']}}}, "
        f"{direction}, {str(ghost).lower()}, {label_lua})"
    )
    assert result["success"] is True, result
    return result


def _place_mining_drill_with_engine(tier3) -> dict[str, Any]:
    """Create a drill over live ore without making agent reach a test concern."""
    return tier3.run_lua(
        """
        local surface = game.surfaces[1]
        local resources = surface.find_entities_filtered{type='resource'}
        for _, resource in pairs(resources) do
            local base_x = math.floor(resource.position.x)
            local base_y = math.floor(resource.position.y)
            for dx = -1, 1 do
                for dy = -1, 1 do
                    local p = {x=base_x + dx + 0.5, y=base_y + dy + 0.5}
                    if surface.can_place_entity{
                        name='burner-mining-drill', position=p, force='player'
                    } then
                        local entity = surface.create_entity{
                            name='burner-mining-drill', position=p,
                            force='player', raise_built=true
                        }
                        if entity then
                            return {
                                success=true, entity_name=entity.name,
                                position={x=entity.position.x, y=entity.position.y}
                            }
                        end
                    end
                end
            end
        end
        error('no live ore position accepted a burner mining drill')
        """
    )


def _destroy_at(tier3, entity_name: str, position: dict[str, float]) -> None:
    tier3.run_lua(
        f"""
        local surface = game.surfaces[1]
        local p = {{x={position['x']}, y={position['y']}}}
        local entity = surface.find_entity({json.dumps(entity_name)}, p)
        if entity and entity.valid then entity.destroy{{raise_destroy=true}} end
        local ghosts = surface.find_entities_filtered{{
            position=p, radius=0.2, type='entity-ghost',
            ghost_name={json.dumps(entity_name)}
        }}
        for _, ghost in pairs(ghosts) do
            if ghost.valid then ghost.destroy{{raise_destroy=true}} end
        end
        return true
        """
    )


async def test_schema_catalog_is_fully_assigned_to_live_contracts(coherent_game):
    from FactoryVerse.game.infra.duckdb.schema_definitions import TABLE_BY_NAME

    assert set(DATABASE_TABLE_COVERAGE) == set(TABLE_BY_NAME)


async def test_snapshot_udp_port_is_configured_before_actor_use(coherent_game):
    assert coherent_game["boot_snapshot_port"] == coherent_game["expected_snapshot_port"], (
        "fv_snapshot booted on a different UDP destination than the sidecar and "
        "RemoteView listener; live writes will reach JSONL but not DuckDB"
    )


async def test_bootstrap_spatial_tables_match_engine_samples(coherent_game):
    tier3 = coherent_game["tier3"]
    view = coherent_game["remote_view"]

    resource = view.query(
        "SELECT name, position_x, position_y, amount FROM resource_tile LIMIT 1"
    )[0]
    natural = view.query(
        "SELECT name, entity_type, position_x, position_y FROM resource_entity LIMIT 1"
    )[0]
    water = view.query("SELECT position_x, position_y FROM water_tile LIMIT 1")[0]
    meta = view.query(
        "SELECT count(*) AS count, min(tick) AS oldest, max(tick) AS newest "
        "FROM chunk_snapshot_meta"
    )[0]

    engine = tier3.run_lua(
        f"""
        local surface = game.surfaces[1]
        local ores = surface.find_entities_filtered{{
            name={_sql_literal(resource['name'])},
            area={{{{x={resource['position_x']}, y={resource['position_y']}}},
                   {{x={resource['position_x'] + 1}, y={resource['position_y'] + 1}}}}}
        }}
        local ore = ores[1]
        local natural = surface.find_entity({_sql_literal(natural['name'])},
            {{x={natural['position_x']}, y={natural['position_y']}}})
        local tile = surface.get_tile({water['position_x']}, {water['position_y']})
        return {{
            ore_valid=ore ~= nil and ore.valid,
            ore_amount=ore and ore.amount or nil,
            natural_valid=natural ~= nil and natural.valid,
            natural_type=natural and natural.type or nil,
            water_name=tile and tile.name or nil,
            tick=game.tick,
        }}
        """
    )

    assert engine["ore_valid"] is True
    assert engine["ore_amount"] == resource["amount"]
    assert engine["natural_valid"] is True
    assert engine["natural_type"] == natural["entity_type"]
    assert "water" in engine["water_name"]
    assert meta["count"] > 0
    assert 0 < meta["oldest"] <= meta["newest"] <= engine["tick"]


async def test_agent_placement_reaches_map_entity(coherent_game):
    tier3 = coherent_game["tier3"]
    view = coherent_game["remote_view"]
    placed = _place_with_agent(
        tier3, "wooden-chest", label="pytest:map-entity", offset=1
    )
    position = placed["position"]
    try:
        engine_exists = tier3.run_lua(
            "return game.surfaces[1].find_entity('wooden-chest', "
            f"{{x={position['x']}, y={position['y']}}}) ~= nil"
        )
        rows = await _eventually(
            lambda: view.query(
                "SELECT entity_name, agent_id, label, placed_tick FROM map_entity "
                "WHERE entity_name='wooden-chest' "
                f"AND position_x={position['x']} AND position_y={position['y']}"
            )
        )
        assert engine_exists is True
        assert len(rows) == 1
        assert rows[0]["agent_id"] == 1
        assert rows[0]["label"] == "pytest:map-entity"
        assert rows[0]["placed_tick"] is not None
    finally:
        _destroy_at(tier3, "wooden-chest", position)


@pytest.mark.parametrize(
    ("entity_name", "component_table"),
    [
        ("inserter", "inserter"),
        ("transport-belt", "transport_belt"),
        ("burner-mining-drill", "mining_drill"),
        ("assembling-machine-1", "assembler"),
    ],
)
async def test_live_entity_updates_all_derived_tables(
    coherent_game, entity_name, component_table
):
    tier3 = coherent_game["tier3"]
    view = coherent_game["remote_view"]
    if entity_name == "burner-mining-drill":
        placed = _place_mining_drill_with_engine(tier3)
    else:
        placed = _place_with_agent(tier3, entity_name, offset=len(entity_name))
    position = placed["position"]
    try:
        map_rows = await _eventually(
            lambda: view.query(
                "SELECT raw_data FROM map_entity "
                f"WHERE entity_name={_sql_literal(entity_name)} "
                f"AND position_x={position['x']} AND position_y={position['y']}"
            )
        )
        footprint_rows = await _eventually(
            lambda: view.query(
                "SELECT * FROM footprint_tiles "
                f"WHERE entity_name={_sql_literal(entity_name)} "
                f"AND entity_position_x={position['x']} "
                f"AND entity_position_y={position['y']}"
            )
        )
        component_rows = await _eventually(
            lambda: view.query(
                f"SELECT * FROM {component_table} "
                f"WHERE entity_name={_sql_literal(entity_name)} "
                f"AND position_x={position['x']} AND position_y={position['y']}"
            )
        )
        observed = {
            "map_entity": len(map_rows),
            "footprint_tiles": len(footprint_rows),
            component_table: len(component_rows),
        }
        assert all(count > 0 for count in observed.values()), observed
        serialized = json.loads(map_rows[0]["raw_data"])
        assert len(footprint_rows) == len(serialized["footprint_tiles"])
        component = component_rows[0]
        if component_table == "inserter":
            assert component["pickup_position_x"] is not None
            assert component["drop_position_x"] is not None
        elif component_table == "transport_belt":
            assert component["belt_speed"] > 0
        elif component_table == "mining_drill":
            assert component["mining_target"] is not None
        elif component_table == "assembler":
            assert component["crafting_speed"] > 0
    finally:
        _destroy_at(tier3, entity_name, position)


async def test_ghost_create_rotate_remove_matches_engine(coherent_game):
    tier3 = coherent_game["tier3"]
    view = coherent_game["remote_view"]
    placed = _place_with_agent(
        tier3,
        "transport-belt",
        ghost=True,
        label="pytest:ghost-lifecycle",
        offset=4,
    )
    position = placed["position"]
    try:
        created = await _eventually(
            lambda: view.query(
                "SELECT direction, label FROM ghost "
                "WHERE ghost_name='transport-belt' "
                f"AND position_x={position['x']} AND position_y={position['y']}"
            )
        )
        assert len(created) == 1
        assert created[0]["label"] == "pytest:ghost-lifecycle"

        rotated = tier3.run_lua(
            "return remote.call('agent_1', 'rotate_entity', 'transport-belt', "
            f"{{x={position['x']}, y={position['y']}}}, 4, true)"
        )
        assert rotated["success"] is True
        rows = await _eventually(
            lambda: view.query(
                "SELECT direction FROM ghost WHERE ghost_name='transport-belt' "
                f"AND position_x={position['x']} AND position_y={position['y']}"
            ),
            lambda value: bool(value) and str(value[0]["direction"]) == "4",
        )
        assert str(rows[0]["direction"]) == "4"

        removed = tier3.run_lua(
            "return remote.call('agent_1', 'remove_ghost', 'transport-belt', "
            f"{{x={position['x']}, y={position['y']}}})"
        )
        assert removed["success"] is True
        remaining = await _eventually(
            lambda: view.query(
                "SELECT * FROM ghost WHERE ghost_name='transport-belt' "
                f"AND position_x={position['x']} AND position_y={position['y']}"
            ),
            lambda value: not value,
        )
        engine_remaining = tier3.run_lua(
            "return #game.surfaces[1].find_entities_filtered{"
            f"position={{x={position['x']}, y={position['y']}}}, radius=0.2, "
            "type='entity-ghost', ghost_name='transport-belt'}"
        )
        assert engine_remaining == 0
        assert remaining == []
    finally:
        _destroy_at(tier3, "transport-belt", position)


async def test_real_entity_rotate_and_remove_matches_engine(coherent_game):
    tier3 = coherent_game["tier3"]
    view = coherent_game["remote_view"]
    placed = _place_with_agent(tier3, "transport-belt", offset=5)
    position = placed["position"]
    try:
        created = await _eventually(
            lambda: view.query(
                "SELECT direction FROM map_entity WHERE entity_name='transport-belt' "
                f"AND position_x={position['x']} AND position_y={position['y']}"
            )
        )
        assert len(created) == 1

        rotated = tier3.run_lua(
            "return remote.call('agent_1', 'rotate_entity', 'transport-belt', "
            f"{{x={position['x']}, y={position['y']}}}, 4, false)"
        )
        assert rotated["success"] is True
        rows = await _eventually(
            lambda: view.query(
                "SELECT direction FROM map_entity WHERE entity_name='transport-belt' "
                f"AND position_x={position['x']} AND position_y={position['y']}"
            ),
            lambda value: bool(value) and str(value[0]["direction"]) == "4",
        )
        assert str(rows[0]["direction"]) == "4"

        picked_up = tier3.run_lua(
            "return remote.call('agent_1', 'pickup_entity', 'transport-belt', "
            f"{{x={position['x']}, y={position['y']}}})"
        )
        assert picked_up["success"] is True
        remaining = await _eventually(
            lambda: view.query(
                "SELECT * FROM map_entity WHERE entity_name='transport-belt' "
                f"AND position_x={position['x']} AND position_y={position['y']}"
            ),
            lambda value: not value,
        )
        engine_exists = tier3.run_lua(
            "return game.surfaces[1].find_entity('transport-belt', "
            f"{{x={position['x']}, y={position['y']}}}) ~= nil"
        )
        assert engine_exists is False
        assert remaining == []
    finally:
        _destroy_at(tier3, "transport-belt", position)


async def test_resource_entity_removal_matches_engine(coherent_game):
    tier3 = coherent_game["tier3"]
    view = coherent_game["remote_view"]
    target = view.query(
        "SELECT name, position_x, position_y FROM resource_entity "
        "ORDER BY position_x * position_x + position_y * position_y LIMIT 1"
    )[0]
    tier3.run_lua(
        f"""
        local entity = game.surfaces[1].find_entity(
            {_sql_literal(target['name'])},
            {{x={target['position_x']}, y={target['position_y']}}})
        if not (entity and entity.valid) then error('resource missing in engine') end
        entity.destroy{{raise_destroy=true}}
        return true
        """
    )
    remaining = await _eventually(
        lambda: view.query(
            "SELECT * FROM resource_entity "
            f"WHERE name={_sql_literal(target['name'])} "
            f"AND position_x={target['position_x']} AND position_y={target['position_y']}"
        ),
        lambda value: not value,
    )
    assert remaining == []


async def test_agent_statistics_feeds_advance(coherent_game):
    """Hand-crafting reaches the event-backed manual table AND the live
    force-production read on remote_view (source-declared, never a table)."""
    tier3 = coherent_game["tier3"]
    view = coherent_game["remote_view"]
    view.set_agent_id(1)
    before = view.query(
        "SELECT coalesce(max(tick), 0) AS tick FROM agent_manual_production_statistics"
    )[0]["tick"]
    before_force = view.production(agent_id=1)
    assert before_force.source.startswith("live:"), before_force.source
    # Measured on 2.0.76 (2026-08-29): hand-crafted products never enter force
    # production statistics; only their ingredients are consumed there.
    before_plates_consumed = before_force.consumed.get("iron-plate", 0)
    before_hand = before_force.hand_crafted.get("iron-gear-wheel", 0)
    tier3.run_lua(
        "remote.call('admin', 'add_items', 1, {['iron-plate']=2}); return true"
    )

    started = tier3.run_lua(
        "return remote.call('agent_1', 'craft_enqueue', 'iron-gear-wheel', 1)"
    )
    assert started is not None

    manual = await _eventually(
        lambda: view.query(
            "SELECT tick, crafted FROM agent_manual_production_statistics "
            "WHERE agent_id=1 ORDER BY tick DESC LIMIT 1"
        ),
        lambda rows: bool(rows)
        and rows[0]["tick"] > before
        and json.loads(rows[0]["crafted"]).get("iron-gear-wheel", 0) >= 1,
        timeout=15,
    )
    assert manual and json.loads(manual[0]["crafted"])["iron-gear-wheel"] >= 1

    force = await _eventually(
        lambda: view.production(agent_id=1),
        lambda report: report.hand_crafted.get("iron-gear-wheel", 0) > before_hand,
        timeout=15,
    )
    assert force.source.startswith("live:"), force
    assert force.produced.get("iron-gear-wheel", 0) == 0, force  # hand crafts are not force production
    assert force.consumed.get("iron-plate", 0) >= before_plates_consumed + 2, force
    assert force.hand_crafted.get("iron-gear-wheel", 0) > before_hand, force
    assert force.automated() == {k: v for k, v in force.produced.items() if v > 0}, force


async def test_power_and_status_feeds_advance(coherent_game):
    """A new pole and assembler show up in the power sample and the status
    dump, read through remote_view.power() / remote_view.status() with their
    source declared — not through any table."""
    tier3 = coherent_game["tier3"]
    view = coherent_game["remote_view"]
    before_power = view.power().sample_tick or 0

    assembler_position = _find_open_position(tier3, "assembling-machine-1", offset=6)
    pole_position = _find_open_position(tier3, "small-electric-pole", offset=2)
    created = tier3.run_lua(
        f"""
        local surface = game.surfaces[1]
        local assembler = surface.create_entity{{
            name='assembling-machine-1',
            position={{x={assembler_position['x']}, y={assembler_position['y']}}},
            force='player', raise_built=true
        }}
        local pole = surface.create_entity{{
            name='small-electric-pole',
            position={{x={pole_position['x']}, y={pole_position['y']}}},
            force='player', raise_built=true
        }}
        if not (assembler and pole) then error('failed to create state-feed fixtures') end
        return {{
            assembler={{x=assembler.position.x, y=assembler.position.y}},
            pole={{x=pole.position.x, y=pole.position.y}},
            network_id=pole.electric_network_id,
            tick=game.tick,
        }}
        """
    )
    try:
        power = await _eventually(
            lambda: view.power(),
            lambda report: (report.sample_tick or 0) > before_power
            and any(n.network_id == created["network_id"] for n in report.networks),
            timeout=20,
        )
        assert power.source.startswith("power_dump:"), power.source
        assert (power.sample_tick or 0) > before_power, power
        network = next(n for n in power.networks if n.network_id == created["network_id"])
        assert network.pole_count >= 1, network
        assert network.anchor_pole_position is not None, network

        def _status_row(summary):
            for group in summary.groups.values():
                for name, x, y in group.entities:
                    if (
                        name == "assembling-machine-1"
                        and abs(x - created["assembler"]["x"]) < 1e-6
                        and abs(y - created["assembler"]["y"]) < 1e-6
                    ):
                        return group.status
            return None

        status = await _eventually(
            lambda: view.status(max_positions=100000),
            lambda summary: (summary.tick or 0) >= created["tick"]
            and _status_row(summary) is not None,
            timeout=20,
        )
        assert status.source.startswith("status_dump:"), status.source
        assert (status.tick or 0) >= created["tick"], status
        assert _status_row(status) is not None, status
        assert status.total >= 1
    finally:
        _destroy_at(tier3, "assembling-machine-1", created["assembler"])
        _destroy_at(tier3, "small-electric-pole", created["pole"])
