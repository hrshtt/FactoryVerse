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
    ref = entity_reference("wooden-chest")
    result = [position for position in candidates if ref.can_place(position, Direction.NORTH)]
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
    """A research completion reaches the agent's turn stream — the file every
    datagram is appended to before it is sent (NOTIFICATIONS design) — with
    the unlocked recipes and effects the engine reported."""
    supervisor, host = live_harness
    environment = supervisor.environment
    tier3 = environment.tier3
    script_output = environment.config.infra_config.get_script_output_dir(tier3.instance)
    turn_file = script_output / "factoryverse" / "agent-snapshots" / "1" / "turn.jsonl"

    def _finished(tech: str):
        if not turn_file.exists():
            return None
        for line in turn_file.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                env = json.loads(line)
            except json.JSONDecodeError:
                continue  # torn tail line
            if env.get("event_type") == "research_finished" and env.get("data", {}).get("technology") == tech:
                return env
        return None

    assert _finished("automation") is None, "fixture already researched automation"
    unlocked = tier3.run_lua(
        "return remote.call('admin', 'unlock_technology', 1, 'automation')"
    )
    assert unlocked["success"] is True

    envelope = None
    for _ in range(300):
        envelope = _finished("automation")
        if envelope:
            break
        await asyncio.sleep(0.05)
    assert envelope, "research_finished never reached turn.jsonl within 15s"
    # The envelope is the stream unit's: epoch/seq/tick stamped once.
    assert envelope["epoch"] >= 1 and envelope["seq"] >= 1 and envelope["tick"] > 0, envelope
    event = envelope["data"]
    assert event["technology"] == "automation"
    assert set(event["unlocked_recipes"]) == set(unlocked["unlocked_recipes"])
    effect_recipes = {
        effect["recipe"]
        for effect in event["effects"]
        if effect["type"] == "unlock-recipe"
    }
    assert effect_recipes == set(event["unlocked_recipes"])

    # And the catalog read on the surviving surface reflects it (CATALOG-1).
    catalog = await _execute_json(
        host,
        """
import json
techs = research.list_technologies(name_filter="automation")
print(json.dumps({"researched": [t["name"] for t in techs if t.get("researched")]}, sort_keys=True))
""",
        "research-catalog",
    )
    assert "automation" in catalog["researched"], catalog


async def test_production_statistics_match_file_and_database_routes(live_harness):
    supervisor, host = live_harness
    environment = supervisor.environment
    tier3 = environment.tier3
    tier4 = environment.tier4
    script_output = environment.config.infra_config.get_script_output_dir(tier3.instance)
    file_source = AgentSnapshotSource(script_output)
    db_source = DuckDBSource(tier4.remote_view._database.connection, script_output_dir=script_output)

    before_force = await file_source.get_force_production(1)
    before_manual = await file_source.get_manual_production(1)
    tier3.run_lua("remote.call('admin', 'add_items', 1, {['iron-plate']=10}); return true")

    crafted = await _execute_json(
        host,
        """
import json
before = inventory.check_total("iron-gear-wheel")
crafting.enqueue("iron-gear-wheel", count=2)
got = await inventory.await_item("iron-gear-wheel", count=before + 2, timeout_ticks=1800)
print(json.dumps({"crafted": {"iron-gear-wheel": got.have - before}}, sort_keys=True))
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

    # The force production read is live and says so; hand-crafted comes from
    # the event-backed manual table. No production table exists (API §4.6).
    report = await _execute_json(
        host,
        """
import json
r = remote_view.production()
manual_rows = remote_view.query('''
    SELECT agent_id, tick FROM agent_manual_production_statistics
    WHERE agent_id = 1 ORDER BY tick DESC LIMIT 1
''')
print(json.dumps({
    "source": r.source,
    "produced_gears": r.produced.get("iron-gear-wheel", 0),
    "hand_gears": r.hand_crafted.get("iron-gear-wheel", 0),
    "manual": manual_rows,
}, sort_keys=True))
""",
        "production-live-read",
    )
    assert report["source"].startswith("live:"), report
    assert report["manual"], report
    # Measured on 2.0.76 (2026-08-29): hand-crafted products are not force
    # production; the event-backed manual series carries them.
    assert report["produced_gears"] == 0 and report["hand_gears"] >= 2, report

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
built = 0
failed = 0
chest_item = inventory.get_item("wooden-chest")
for g in ghosts:
    # The map-write idiom (GHOST §6): walk there and place the real entity over
    # the ghost; placement.lua replaces the ghost and inherits its label.
    await walking.walk_to(g.position)
    try:
        chest_item.place(g.position)
        built += 1
    except RuntimeError:
        failed += 1
result = {"built_count": built, "failed_count": failed}
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


# The two build_plan / planning-commit contracts that lived here were deleted
# 2026-08-29 with ghost_builder (API §2.4, GHOST §4): the executor verb is gone
# and the composed idiom (walk, build over the ghost) is exercised above.


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
    sites = entity_reference("offshore-pump").sites(
        near=center, radius=20, max_results=20
    ).value
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
