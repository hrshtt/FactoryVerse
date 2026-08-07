"""Live domain contracts for the owned free-play game and harness services.

Run explicitly with::

    FV_RUN_LIVE_FREEPLAY_TESTS=1 uv run pytest -q \
        tests/live/test_freeplay_harness_domains.py

These tests own ``server_0`` for the module and therefore must not run beside
another FactoryVerse environment using the default ports.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from FactoryVerse.environment.config import FactoryVerseConfig
from FactoryVerse.evals.freeplay import FreeplayCampaignStore
from FactoryVerse.evals.freeplay.runtime_host import FreeplayRuntimeHost
from FactoryVerse.evals.freeplay.supervisor import FreeplaySupervisor
from FactoryVerse.game.tasks.sources import AgentSnapshotSource, DuckDBSource


pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_docker,
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("FV_RUN_LIVE_FREEPLAY_TESTS") != "1",
        reason="set FV_RUN_LIVE_FREEPLAY_TESTS=1 to own server_0 and run live contracts",
    ),
]

REPO_ROOT = Path(__file__).resolve().parents[2]
GAME_SPEED = 8

OPEN_CHEST_POSITIONS_CODE = """
import math

def open_chest_positions(count, min_distance=2, max_distance=6, ghost=False):
    origin = walking.current_position
    candidates = []
    base_x, base_y = math.floor(origin.x), math.floor(origin.y)
    radius = math.ceil(max_distance)
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            distance = math.hypot(dx, dy)
            if min_distance <= distance <= max_distance:
                candidates.append(MapPosition(base_x + dx + 0.5, base_y + dy + 0.5))
    validity = placement_hints.validator.validate_batch(
        "wooden-chest", candidates, [Direction.NORTH] * len(candidates), ghost=ghost
    )
    result = [position for position, valid in zip(candidates, validity) if valid]
    if len(result) < count:
        raise AssertionError(f"needed {count} open chest positions, found {len(result)}")
    return result[:count]
"""


@pytest.fixture(scope="module")
async def live_harness(tmp_path_factory):
    campaigns_root = tmp_path_factory.mktemp("freeplay-domain-contracts")
    store = FreeplayCampaignStore(campaigns_root, "domain-contracts")
    config = FactoryVerseConfig()
    FreeplaySupervisor.create_campaign(
        store,
        repo_root=REPO_ROOT,
        infra_config=config,
        seed=44340,
        agent_id="agent_1",
        harness="pytest",
        model="domain-contracts",
    )
    supervisor = FreeplaySupervisor(
        store,
        repo_root=REPO_ROOT,
        harness="pytest",
        model="domain-contracts",
    )
    await supervisor.start()
    actual_game_speed = supervisor.environment.tier3.run_lua(
        "return game.speed"
    )
    assert actual_game_speed == GAME_SPEED
    host = FreeplayRuntimeHost(
        supervisor,
        default_timeout=300,
        maximum_timeout=600,
    )
    try:
        yield supervisor, host
    finally:
        await supervisor.finish(
            reason="pytest_domain_contracts",
            checkpoint=False,
            execution_count=host.execution_count,
        )


async def _execute_json(host: FreeplayRuntimeHost, code: str, request_id: str):
    response = await host.handle(
        {
            "id": request_id,
            "op": "execute",
            "code": code,
            "timeout_seconds": 300,
        }
    )
    assert response["ok"], response
    lines = [line for line in response["output"].splitlines() if line.strip()]
    assert lines, response
    return json.loads(lines[-1])


async def test_preflight_ignores_noncombat_enemy_force_character(live_harness):
    """A connected/non-allied character is not a biter-presence failure."""
    supervisor, _ = live_harness
    tier3 = supervisor.environment.tier3
    created = tier3.run_lua(
        """
        local surface = game.surfaces[1]
        local position = surface.find_non_colliding_position(
            "character", {100, 100}, 64, 1
        )
        if not position then error("no test character position") end
        local character = surface.create_entity{
            name="character", position=position, force="enemy"
        }
        if not character then error("failed to create enemy-force test character") end
        return {x=position.x, y=position.y}
        """
    )
    try:
        preflight = await supervisor._preflight(None)
        assert preflight["valid"] is True, preflight
        assert preflight["enemy_state"]["enemy_force_entity_count"] >= 1
        assert preflight["enemy_state"]["hostile_combat_entity_count"] == 0
    finally:
        tier3.run_lua(
            f"""
            local entity = game.surfaces[1].find_entity(
                "character", {{x={created['x']}, y={created['y']}}}
            )
            if entity and entity.valid then entity.destroy() end
            return true
            """
        )


@pytest.mark.parametrize("resource_type", ["tree", "rock"])
async def test_db_nearest_resource_advances_after_five_exhaustive_mines(
    live_harness, resource_type
):
    """Each query is made only after the preceding entity disappears."""
    supervisor, host = live_harness
    tier3 = supervisor.environment.tier3
    position = tier3.run_lua("return remote.call('agent_1', 'get_position')")

    code = f"""
import asyncio, json

resource_type = {resource_type!r}
x, y = {float(position['x'])!r}, {float(position['y'])!r}
history = []
for iteration in range(5):
    sql = f\"\"\"SELECT * FROM resource_entity
              WHERE entity_type = '{{resource_type}}'
              ORDER BY power(position_x - {{x}}, 2) + power(position_y - {{y}}, 2)
              LIMIT 1\"\"\"
    matches = remote_view.get_resources(sql)
    if not matches:
        raise AssertionError(f\"no {{resource_type}} available at iteration {{iteration + 1}}\")
    target = matches[0]
    target_x, target_y = target.position.x, target.position.y
    identity = [target.name, target_x, target_y]
    await target.walk_to(timeout=90)
    products = await target.mine(max_count=1, timeout=90)

    rows = remote_view.query(
        f\"\"\"SELECT count(*) AS count FROM resource_entity
                WHERE name = '{{target.name}}'
                  AND position_x = {{target_x}}
                  AND position_y = {{target_y}}\"\"\"
    )
    if rows[0][\"count\"] != 0:
        raise AssertionError(f\"mined resource remained in DuckDB: {{identity}}\")

    history.append({{
        \"query_index\": iteration + 1,
        \"name\": target.name,
        \"position\": [target_x, target_y],
        \"products\": [stack.name for stack in products],
    }})
    x, y = target_x, target_y

print(json.dumps(history, sort_keys=True))
"""
    history = await _execute_json(host, code, f"mine-{resource_type}")

    assert len(history) == 5
    assert [row["query_index"] for row in history] == [1, 2, 3, 4, 5]
    assert len({tuple(row["position"]) for row in history}) == 5


async def test_research_completion_push_exposes_recipes_and_effects(live_harness):
    supervisor, host = live_harness
    await _execute_json(
        host,
        "events_seen = await events.drain(timeout=0)\n"
        "print(__import__('json').dumps({'drained': len(events_seen)}))",
        "research-drain",
    )

    unlocked = supervisor.environment.tier3.run_lua(
        "return remote.call('admin', 'unlock_technology', 1, 'automation')"
    )
    assert unlocked["success"] is True

    event = await _execute_json(
        host,
        """
import json
event = await events.wait_for(
    "research_finished",
    predicate=lambda candidate: candidate.technology == "automation",
    timeout=15,
)
print(json.dumps({
    "technology": event.technology,
    "unlocked_recipes": event.unlocked_recipes,
    "effects": event.effects,
    "level": event.level,
}, sort_keys=True))
""",
        "research-wait",
    )

    assert event["technology"] == "automation"
    assert set(event["unlocked_recipes"]) == set(unlocked["unlocked_recipes"])
    effect_recipes = {
        effect["recipe"]
        for effect in event["effects"]
        if effect["type"] == "unlock-recipe"
    }
    assert effect_recipes == set(event["unlocked_recipes"])


async def test_production_statistics_match_file_and_database_routes(live_harness):
    supervisor, host = live_harness
    environment = supervisor.environment
    tier3 = environment.tier3
    tier4 = environment.tier4
    script_output = environment.config.infra_config.get_script_output_dir(tier3.instance)
    file_source = AgentSnapshotSource(script_output)
    db_source = DuckDBSource(tier4.remote_view._database.connection)

    before_force = await file_source.get_force_production(1)
    before_manual = await file_source.get_manual_production(1)
    tier3.run_lua("remote.call('admin', 'add_items', 1, {['iron-plate']=10}); return true")

    crafted = await _execute_json(
        host,
        """
import json
stacks = await crafting.craft("iron-gear-wheel", count=2, timeout=30)
print(json.dumps({"crafted": {stack.name: stack.count for stack in stacks}}, sort_keys=True))
""",
        "production-craft",
    )
    assert crafted["crafted"]["iron-gear-wheel"] == 2

    file_force = before_force
    file_manual = before_manual
    for _ in range(200):
        file_force = await file_source.get_force_production(1)
        file_manual = await file_source.get_manual_production(1)
        manual_delta = file_manual["crafted"].get(
            "iron-gear-wheel", 0
        ) - before_manual["crafted"].get("iron-gear-wheel", 0)
        if file_force["tick"] > before_force["tick"] and manual_delta >= 2:
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail(
            "production JSONL feeds did not expose two crafted iron gears within 10s"
        )

    # Any actor DB read must flush queued file_io reductions before returning.
    db_rows = await _execute_json(
        host,
        """
import json
rows = remote_view.query('''
    SELECT agent_id, tick FROM agent_production_statistics
    WHERE agent_id = 1 ORDER BY tick DESC LIMIT 1
''')
manual_rows = remote_view.query('''
    SELECT agent_id, tick FROM agent_manual_production_statistics
    WHERE agent_id = 1 ORDER BY tick DESC LIMIT 1
''')
print(json.dumps({"force": rows, "manual": manual_rows}, sort_keys=True))
""",
        "production-db-flush",
    )
    assert db_rows["force"] and db_rows["manual"]

    assert await db_source.get_force_production(1) == file_force
    assert await db_source.get_manual_production(1) == file_manual


async def test_item_placement_inventory_failure_and_stale_handle_contract(live_harness):
    """A persistent item handle never bypasses live inventory or collision truth."""
    supervisor, host = live_harness
    tier3 = supervisor.environment.tier3
    tier3.run_lua(
        "remote.call('admin', 'clear_inventory', 1); "
        "remote.call('admin', 'add_items', 1, {['wooden-chest']=2}); return true"
    )

    placed = await _execute_json(
        host,
        OPEN_CHEST_POSITIONS_CODE
        + """
import json
item_positions = open_chest_positions(3)
saved_chest = inventory.get_item("wooden-chest")
if saved_chest is None:
    raise AssertionError("trusted setup did not provide wooden chests")
before = inventory.check_total("wooden-chest")
saved_chest.place(item_positions[0])
after_first = inventory.check_total("wooden-chest")
first_rows = remote_view.query(f'''
    SELECT entity_name, position_x, position_y
    FROM map_entity
    WHERE entity_name = 'wooden-chest'
      AND position_x = {item_positions[0].x}
      AND position_y = {item_positions[0].y}
''')

collision_error = None
try:
    saved_chest.place(item_positions[0])
except RuntimeError as exc:
    collision_error = str(exc)
after_collision = inventory.check_total("wooden-chest")

saved_chest.place(item_positions[1])
after_second = inventory.check_total("wooden-chest")
print(json.dumps({
    "before": before,
    "after_first": after_first,
    "after_collision": after_collision,
    "after_second": after_second,
    "first_rows": len(first_rows),
    "collision_error": collision_error,
}, sort_keys=True))
""",
        "building-item-place",
    )
    assert placed == {
        "after_collision": 1,
        "after_first": 1,
        "after_second": 0,
        "before": 2,
        "collision_error": placed["collision_error"],
        "first_rows": 1,
    }
    assert placed["collision_error"] and "collid" in placed["collision_error"].lower()

    stale = await _execute_json(
        host,
        """
import json
stale_error = None
try:
    saved_chest.place(item_positions[2])
except RuntimeError as exc:
    stale_error = str(exc)
rows = remote_view.query(f'''
    SELECT count(*) AS count FROM map_entity
    WHERE entity_name = 'wooden-chest'
      AND position_x = {item_positions[2].x}
      AND position_y = {item_positions[2].y}
''')
print(json.dumps({
    "error": stale_error,
    "inventory": inventory.check_total("wooden-chest"),
    "rows": rows[0]["count"],
}, sort_keys=True))
""",
        "building-stale-item",
    )
    assert stale["error"] and "no wooden-chest" in stale["error"].lower()
    assert stale["inventory"] == 0
    assert stale["rows"] == 0


async def test_item_ghost_is_free_far_visible_and_conversion_is_atomic(live_harness):
    supervisor, host = live_harness
    tier3 = supervisor.environment.tier3
    tier3.run_lua(
        "remote.call('admin', 'clear_inventory', 1); "
        "remote.call('admin', 'add_items', 1, {['wooden-chest']=1}); return true"
    )

    ghost = await _execute_json(
        host,
        OPEN_CHEST_POSITIONS_CODE
        + """
import json
ghost_item = inventory.get_item("wooden-chest")
ghost_position = open_chest_positions(1, min_distance=14, max_distance=20, ghost=True)[0]
ghost_origin = walking.current_position
ghost_label = "pytest:far-storage-intent"
before = inventory.check_total("wooden-chest")
placed = ghost_item.place_ghost(ghost_position, label=ghost_label)
after = inventory.check_total("wooden-chest")
rows = remote_view.query(f'''
    SELECT ghost_name, position_x, position_y, label
    FROM ghost WHERE label = '{ghost_label}'
''')
print(json.dumps({
    "placed": placed,
    "before": before,
    "after": after,
    "distance": ((ghost_position.x - ghost_origin.x) ** 2 + (ghost_position.y - ghost_origin.y) ** 2) ** 0.5,
    "rows": rows,
}, sort_keys=True))
""",
        "building-far-ghost",
    )
    assert ghost["placed"] is True
    assert ghost["before"] == ghost["after"] == 1
    assert ghost["distance"] > 10
    assert len(ghost["rows"]) == 1
    assert ghost["rows"][0]["label"] == "pytest:far-storage-intent"

    tier3.run_lua(
        "remote.call('admin', 'clear_inventory', 1); "
        "remote.call('admin', 'add_items', 1, {['wooden-chest']=1}); return true"
    )
    converted = await _execute_json(
        host,
        """
import json
ghosts = remote_view.get_ghosts(f"SELECT * FROM ghost WHERE label = '{ghost_label}'")
result = await ghost_builder.build_ghosts(ghosts, strict=True)
real_rows = remote_view.query(f'''
    SELECT entity_name, position_x, position_y, label
    FROM map_entity WHERE label = '{ghost_label}'
''')
ghost_rows = remote_view.query(f"SELECT * FROM ghost WHERE label = '{ghost_label}'")
print(json.dumps({
    "built": result["built_count"],
    "failed": result["failed_count"],
    "real_rows": real_rows,
    "ghost_count": len(ghost_rows),
    "inventory": inventory.check_total("wooden-chest"),
}, sort_keys=True))
""",
        "building-ghost-conversion",
    )
    assert converted["built"] == 1
    assert converted["failed"] == 0
    assert converted["ghost_count"] == 0
    assert converted["inventory"] == 0
    assert len(converted["real_rows"]) == 1
    assert converted["real_rows"][0]["label"] == "pytest:far-storage-intent"


async def test_build_plan_commit_boundaries_and_non_strict_partial_state(live_harness):
    supervisor, host = live_harness
    tier3 = supervisor.environment.tier3

    # Strict inventory failure must occur before validation, ghost placement,
    # movement, or any other map mutation.
    tier3.run_lua(
        "remote.call('admin', 'clear_inventory', 1); "
        "remote.call('admin', 'add_items', 1, {['wooden-chest']=1}); return true"
    )
    strict = await _execute_json(
        host,
        OPEN_CHEST_POSITIONS_CODE
        + """
import json
strict_positions = open_chest_positions(2, min_distance=3, max_distance=7, ghost=True)
strict_label = "pytest:strict-preflight"
strict_plan = GhostPlan(
    "wooden-chest",
    [(position, Direction.NORTH) for position in strict_positions],
    strict_label,
    "strict inventory preflight",
    True,
)
strict_origin = walking.current_position
strict_result = await ghost_builder.build_plan(strict_plan, strict=True)
strict_after = walking.current_position
strict_ghosts = remote_view.query(f"SELECT * FROM ghost WHERE label = '{strict_label}'")
strict_reals = remote_view.query(f"SELECT * FROM map_entity WHERE label = '{strict_label}'")
print(json.dumps({
    "result": {key: value for key, value in strict_result.items() if not isinstance(value, list)},
    "same_position": [strict_origin.x, strict_origin.y] == [strict_after.x, strict_after.y],
    "ghosts": len(strict_ghosts),
    "reals": len(strict_reals),
    "inventory": inventory.check_total("wooden-chest"),
}, sort_keys=True))
""",
        "building-strict-plan",
    )
    assert strict["result"]["placed_count"] == 0
    assert "insufficient" in strict["result"]["error"].lower()
    assert strict["same_position"] is True
    assert strict["ghosts"] == strict["reals"] == 0
    assert strict["inventory"] == 1

    # Cache a valid plan, then occupy its position before commit. Commit-time
    # validation must reject it without leaving plan ghosts or real entities.
    tier3.run_lua(
        "remote.call('admin', 'clear_inventory', 1); "
        "remote.call('admin', 'add_items', 1, {['wooden-chest']=1}); return true"
    )
    prepared = await _execute_json(
        host,
        """
import json
stale_position = open_chest_positions(1, min_distance=2, max_distance=6)[0]
stale_label = "pytest:stale-plan"
stale_plan = GhostPlan(
    "wooden-chest", [(stale_position, Direction.NORTH)], stale_label,
    "plan made stale by a real obstruction", True,
)
blocker = inventory.get_item("wooden-chest")
blocker.place(stale_position)
print(json.dumps({"planned_valid": stale_plan.valid, "inventory": inventory.check_total("wooden-chest")}))
""",
        "building-stale-plan-prepare",
    )
    assert prepared == {"planned_valid": True, "inventory": 0}
    tier3.run_lua(
        "remote.call('admin', 'add_items', 1, {['wooden-chest']=1}); return true"
    )
    stale = await _execute_json(
        host,
        """
import json
stale_result = await ghost_builder.build_plan(stale_plan, strict=True)
stale_ghosts = remote_view.query(f"SELECT * FROM ghost WHERE label = '{stale_label}'")
stale_reals = remote_view.query(f"SELECT * FROM map_entity WHERE label = '{stale_label}'")
at_position = remote_view.query(f'''
    SELECT count(*) AS count FROM map_entity
    WHERE entity_name = 'wooden-chest'
      AND position_x = {stale_position.x} AND position_y = {stale_position.y}
''')
print(json.dumps({
    "result": {key: value for key, value in stale_result.items() if not isinstance(value, list)},
    "ghosts": len(stale_ghosts),
    "plan_reals": len(stale_reals),
    "entities_at_position": at_position[0]["count"],
    "inventory": inventory.check_total("wooden-chest"),
}, sort_keys=True))
""",
        "building-stale-plan-commit",
    )
    assert stale["result"]["placed_count"] == 0
    assert "revalidation" in stale["result"]["error"].lower()
    assert stale["ghosts"] == stale["plan_reals"] == 0
    assert stale["entities_at_position"] == 1
    assert stale["inventory"] == 1

    # Non-strict mode deliberately permits a partial commit, but its result and
    # final database state must identify the exact completed/remainder split.
    tier3.run_lua(
        "remote.call('admin', 'clear_inventory', 1); "
        "remote.call('admin', 'add_items', 1, {['wooden-chest']=1}); return true"
    )
    partial = await _execute_json(
        host,
        """
import json
partial_positions = open_chest_positions(2, min_distance=2, max_distance=6, ghost=True)
partial_label = "pytest:non-strict-partial"
partial_plan = GhostPlan(
    "wooden-chest",
    [(position, Direction.NORTH) for position in partial_positions],
    partial_label,
    "one item for two planned entities",
    True,
)
partial_result = await ghost_builder.build_plan(partial_plan, strict=False)
partial_reals = remote_view.query(f'''
    SELECT position_x, position_y, label FROM map_entity WHERE label = '{partial_label}'
''')
partial_ghosts = remote_view.query(f'''
    SELECT position_x, position_y, label FROM ghost WHERE label = '{partial_label}'
''')
print(json.dumps({
    "result": partial_result,
    "reals": partial_reals,
    "ghosts": partial_ghosts,
    "inventory": inventory.check_total("wooden-chest"),
}, sort_keys=True))
""",
        "building-partial-plan",
    )
    assert partial["result"]["placed_count"] == 2
    assert partial["result"]["built_count"] == 1
    assert partial["result"]["failed_count"] == 1
    assert len(partial["reals"]) == 1
    assert len(partial["ghosts"]) == 1
    assert partial["inventory"] == 0
    real_position = (partial["reals"][0]["position_x"], partial["reals"][0]["position_y"])
    ghost_position = (partial["ghosts"][0]["position_x"], partial["ghosts"][0]["position_y"])
    assert real_position != ghost_position


async def test_planning_is_pure_and_persisted_python_skill_commits_later(live_harness):
    """Python may preserve intent; only the later embodied commit mutates."""
    supervisor, host = live_harness
    tier3 = supervisor.environment.tier3
    tier3.run_lua(
        "remote.call('admin', 'clear_inventory', 1); "
        "remote.call('admin', 'add_items', 1, {['transport-belt']=2}); return true"
    )

    planned = await _execute_json(
        host,
        """
import json, math

def find_open_belt_line(length=2):
    origin = walking.current_position
    base_x, base_y = math.floor(origin.x), math.floor(origin.y)
    offsets = sorted(
        ((dx, dy) for dx in range(-3, 4) for dy in range(-3, 4)),
        key=lambda offset: math.hypot(*offset),
    )
    for dx, dy in offsets:
        positions = [
            MapPosition(base_x + dx + offset + 0.5, base_y + dy + 0.5)
            for offset in range(length)
        ]
        valid = placement_hints.validator.validate_batch(
            "transport-belt",
            positions,
            [Direction.EAST] * length,
            ghost=True,
        )
        if all(valid):
            return positions
    raise AssertionError("no open two-belt line found near the agent")

belt_positions = find_open_belt_line()
planning_origin = walking.current_position
inventory_before_plan = inventory.check_total("transport-belt")
saved_belt_plan = placement_hints.get_placement_line(
    "transport-belt", belt_positions[0], belt_positions[-1], validate=True
)

async def commit_saved_belt_plan():
    return await ghost_builder.build_plan(saved_belt_plan, strict=True)

inventory_after_plan = inventory.check_total("transport-belt")
planning_after = walking.current_position
planned_reals = remote_view.query(
    f"SELECT * FROM map_entity WHERE label = '{saved_belt_plan.label}'"
)
planned_ghosts = remote_view.query(
    f"SELECT * FROM ghost WHERE label = '{saved_belt_plan.label}'"
)
print(json.dumps({
    "valid": saved_belt_plan.valid,
    "positions": len(saved_belt_plan.positions),
    "inventory_before": inventory_before_plan,
    "inventory_after": inventory_after_plan,
    "same_position": [planning_origin.x, planning_origin.y] == [planning_after.x, planning_after.y],
    "reals": len(planned_reals),
    "ghosts": len(planned_ghosts),
}, sort_keys=True))
""",
        "building-pure-plan",
    )
    assert planned == {
        "ghosts": 0,
        "inventory_after": 2,
        "inventory_before": 2,
        "positions": 2,
        "reals": 0,
        "same_position": True,
        "valid": True,
    }

    committed = await _execute_json(
        host,
        """
import json
commit_result = await commit_saved_belt_plan()
committed_reals = remote_view.query(f'''
    SELECT entity_name, position_x, position_y, direction, label
    FROM map_entity WHERE label = '{saved_belt_plan.label}'
    ORDER BY position_x, position_y
''')
committed_ghosts = remote_view.query(
    f"SELECT * FROM ghost WHERE label = '{saved_belt_plan.label}'"
)
print(json.dumps({
    "result": commit_result,
    "reals": committed_reals,
    "ghosts": len(committed_ghosts),
    "inventory": inventory.check_total("transport-belt"),
}, sort_keys=True))
""",
        "building-persisted-skill-commit",
    )
    assert committed["result"]["placed_count"] == 2
    assert committed["result"]["built_count"] == 2
    assert committed["result"]["failed_count"] == 0
    assert committed["ghosts"] == 0
    assert committed["inventory"] == 0
    assert len(committed["reals"]) == 2
    assert {row["entity_name"] for row in committed["reals"]} == {"transport-belt"}


async def test_offshore_pump_site_supplies_actionable_approach_position(live_harness):
    """Pump discovery supplies the complete no-guessing walk-and-place path."""
    supervisor, host = live_harness
    supervisor.environment.tier3.run_lua(
        "remote.call('admin', 'clear_inventory', 1); "
        "remote.call('admin', 'add_items', 1, {['offshore-pump']=1}); return true"
    )

    result = await _execute_json(
        host,
        """
import json

origin = walking.current_position
water_hints = remote_view.find_water(near=origin, radius=250, limit=500)
if not water_hints:
    raise AssertionError("no water hint found in the live campaign")

sites = []
for hint in water_hints:
    center = MapPosition(x=hint["x"], y=hint["y"])
    sites = placement_hints.find_offshore_pump_sites(
        near=center, radius=20, max_results=20
    )
    if sites:
        break
if not sites:
    raise AssertionError("no actionable offshore-pump site found near live water")

pump_item = inventory.get_item("offshore-pump")
if pump_item is None:
    raise AssertionError("trusted setup did not provide an offshore pump")

attempt_errors = []
placed = None
selected = None
final_position = None
for site in sites:
    try:
        final_position = await walking.walk_to(
            site.approach_position, strict_goal=False, timeout=90
        )
        placed = pump_item.place(site.position, site.direction)
        selected = site
        break
    except RuntimeError as exc:
        attempt_errors.append(str(exc))

if placed is None or selected is None or final_position is None:
    raise AssertionError(f"all supplied pump sites failed: {attempt_errors}")

print(json.dumps({
    "anchor": [selected.position.x, selected.position.y],
    "approach": [selected.approach_position.x, selected.approach_position.y],
    "direction": selected.direction.value,
    "final_position": [final_position.x, final_position.y],
    "placed_position": [placed.position.x, placed.position.y],
    "anchor_approach_distance": selected.position.distance(
        selected.approach_position
    ),
    "remaining_inventory": inventory.check_total("offshore-pump"),
}, sort_keys=True))
""",
        "offshore-pump-actionable-site",
    )

    assert result["placed_position"] == result["anchor"]
    assert result["anchor_approach_distance"] <= 10
    assert result["remaining_inventory"] == 0
