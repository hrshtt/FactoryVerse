"""Live resource-lifecycle and crafting-inventory causality contracts.

These tests own a dedicated freeplay server.  They deliberately compare the
public Tier 4 API with direct Factorio engine truth; an open/default server is
never treated as permission to mutate it.

Run with the isolated ports assigned to this lane::

    COMPOSE_PROJECT_NAME=fv-repl-resource \
    FV_RCON_SERVER_PORT_BASE=40500 FV_RCON_CLIENT_PORT=40600 \
    FV_GAME_PORT_BASE=50197 FV_AGENT_PORT_BASE=50202 \
    FV_SNAPSHOT_PORT_BASE=50400 FV_CLIENT_SNAPSHOT_PORT=50500 \
    FV_ENABLE_UDP_PORT=50200 \
    FV_RUN_LIVE_RESOURCE_INVENTORY_CONTRACTS=1 \
    uv run pytest -q tests/live/test_resource_inventory_contracts.py -vv
"""

from __future__ import annotations

import json
import math
import os
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from FactoryVerse.environment.config import FactoryVerseConfig
from FactoryVerse.evals.freeplay import FreeplayCampaignStore
from FactoryVerse.evals.freeplay.supervisor import FreeplaySupervisor
from FactoryVerse.game.factory.types import MapPosition


pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_docker,
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("FV_RUN_LIVE_RESOURCE_INVENTORY_CONTRACTS") != "1",
        reason=(
            "set FV_RUN_LIVE_RESOURCE_INVENTORY_CONTRACTS=1 to own the "
            "dedicated resource/inventory server"
        ),
    ),
]

REPO_ROOT = Path(__file__).resolve().parents[2]
GAME_SPEED = 8


@pytest.fixture(scope="module")
async def resource_inventory_game(tmp_path_factory):
    campaigns_root = tmp_path_factory.mktemp("resource-inventory-contracts")
    store = FreeplayCampaignStore(campaigns_root, "resource-inventory-contracts")
    config = FactoryVerseConfig()
    FreeplaySupervisor.create_campaign(
        store,
        repo_root=REPO_ROOT,
        infra_config=config,
        seed=44340,
        agent_id="agent_1",
        harness="pytest",
        model="resource-inventory-contracts",
    )
    supervisor = FreeplaySupervisor(
        store,
        repo_root=REPO_ROOT,
        harness="pytest",
        model="resource-inventory-contracts",
    )
    try:
        await supervisor.start()
        tier3 = supervisor.environment.tier3
        tier4 = supervisor.environment.tier4
        # Keep this lane about mining causality. The isolated snapshot-port
        # boot defect is covered independently in test_database_coherence;
        # repair it explicitly here so destroy-event delivery can be observed.
        expected_snapshot_port = config.get_snapshot_port(tier3.instance)
        boot_snapshot_port = tier3.map_api.get_udp_port()
        if boot_snapshot_port != expected_snapshot_port:
            tier3.map_api.set_udp_port(expected_snapshot_port)
        assert tier3.run_lua("return game.speed") == GAME_SPEED
        yield {
            "supervisor": supervisor,
            "tier3": tier3,
            "tier4": tier4,
            "remote_view": tier4.remote_view,
            "reachable_view": tier4.reachable_view,
            "inventory": tier4.embodied_actions["inventory"],
            "crafting": tier4.embodied_actions["crafting"],
            "walking": tier4.embodied_actions["movement"],
            "mining": tier4.embodied_actions["mining"],
            "mined_tree_identities": set(),
            "boot_snapshot_port": boot_snapshot_port,
            "expected_snapshot_port": expected_snapshot_port,
        }
    finally:
        await supervisor.finish(
            reason="pytest_resource_inventory_contracts",
            checkpoint=False,
            execution_count=0,
        )


def _engine_resource(tier3, name: str, x: float, y: float) -> dict[str, Any]:
    """Return the exact engine entity and its declared mineable products."""
    return tier3.run_lua(
        f"""
        local surface = game.surfaces[1]
        local position = {{x={x}, y={y}}}
        local matches = surface.find_entities_filtered{{
            name={json.dumps(name)}, position=position, radius=0.01, type='tree'
        }}
        local entity = matches[1]
        if not (entity and entity.valid) then return {{exists=false}} end
        local products = {{}}
        local mineable = entity.prototype.mineable_properties
        for _, product in pairs((mineable and mineable.products) or {{}}) do
            table.insert(products, {{
                name=product.name,
                type=product.type,
                amount=product.amount,
                amount_min=product.amount_min,
                amount_max=product.amount_max,
                probability=product.probability,
            }})
        end
        return {{
            exists=true,
            name=entity.name,
            type=entity.type,
            position={{x=entity.position.x, y=entity.position.y}},
            products=products,
        }}
        """
    )


def _engine_recipe(tier3, recipe_name: str) -> dict[str, Any]:
    """Read the active force recipe prototype used by begin_crafting()."""
    return tier3.run_lua(
        f"""
        local state = remote.call('admin', 'get_agent_state', 1)
        local force = game.forces[state.force]
        local recipe = force.recipes[{json.dumps(recipe_name)}]
        if not recipe then return {{exists=false}} end
        local prototype = recipe.prototype
        local ingredients = {{}}
        for _, ingredient in pairs(prototype.ingredients or {{}}) do
            table.insert(ingredients, {{
                name=ingredient.name,
                type=ingredient.type,
                amount=ingredient.amount,
            }})
        end
        local products = {{}}
        for _, product in pairs(prototype.products or {{}}) do
            table.insert(products, {{
                name=product.name,
                type=product.type,
                amount=product.amount,
                amount_min=product.amount_min,
                amount_max=product.amount_max,
                probability=product.probability,
            }})
        end
        return {{
            exists=true,
            enabled=recipe.enabled,
            category=prototype.category,
            ingredients=ingredients,
            products=products,
        }}
        """
    )


def _engine_stand_position(tier3, x: float, y: float) -> dict[str, float]:
    """Choose a collision-free point strictly inside resource reach."""
    return tier3.run_lua(
        f"""
        local surface = game.surfaces[1]
        local target = {{x={x}, y={y}}}
        local position = surface.find_non_colliding_position(
            'character', target, 1.75, 0.05, false
        )
        if not position then error('no stand position inside resource reach') end
        local distance = math.sqrt(
            (position.x - target.x)^2 + (position.y - target.y)^2
        )
        if distance >= 2.0 then
            error('stand position was not safely inside resource reach: ' .. distance)
        end
        return {{x=position.x, y=position.y}}
        """
    )


def _engine_inventory_counts(tier3, names: set[str]) -> dict[str, int]:
    name_array = ", ".join(json.dumps(name) for name in sorted(names))
    return tier3.run_lua(
        f"""
        local state = remote.call('admin', 'get_agent_state', 1)
        local wanted = {{}}
        for _, name in pairs({{{name_array}}}) do wanted[name] = true end
        local result = {{}}
        for name, _ in pairs(wanted) do result[name] = 0 end
        for _, item in pairs(state.inventory or {{}}) do
            if wanted[item.name] then
                result[item.name] = (result[item.name] or 0) + item.count
            end
        end
        return result
        """
    )


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _lua_item_map(items: dict[str, int]) -> str:
    pairs = ", ".join(
        f"[{json.dumps(name)}]={int(count)}" for name, count in sorted(items.items())
    )
    return "{" + pairs + "}"


@pytest.mark.parametrize("_sample", range(5), ids=lambda value: f"sample-{value + 1}")
async def test_tree_resource_row_matches_engine_and_mining_inventory_causality(
    resource_inventory_game, _sample,
):
    """A tree is a resource_entity whose removal and products match Factorio."""
    tier3 = resource_inventory_game["tier3"]
    remote_view = resource_inventory_game["remote_view"]
    reachable_view = resource_inventory_game["reachable_view"]
    inventory = resource_inventory_game["inventory"]
    walking = resource_inventory_game["walking"]

    actor_position = tier3.run_lua("return remote.call('agent_1', 'get_position')")
    candidates = remote_view.get_resources(
        f"""
        SELECT * FROM resource_entity
        WHERE entity_type = 'tree'
        ORDER BY power(position_x - {float(actor_position['x'])}, 2)
               + power(position_y - {float(actor_position['y'])}, 2)
        LIMIT 20
        """
    )
    assert candidates, "initial resource_entity snapshot contained no trees"

    # Bind one DuckDB row to an exact, still-live Factorio entity.  This avoids
    # mistaking a stale nearest-row failure for a movement/mining failure.
    selected = None
    engine_before = None
    for candidate in candidates:
        observed = _engine_resource(
            tier3, candidate.name, candidate.position.x, candidate.position.y
        )
        if observed.get("exists") and any(
            product.get("name") == "wood" for product in observed["products"]
        ):
            selected = candidate
            engine_before = observed
            break
    assert selected is not None, "no sampled resource_entity tree matched engine truth"
    selected_identity = (
        selected.name,
        float(selected.position.x),
        float(selected.position.y),
    )
    assert selected_identity not in resource_inventory_game["mined_tree_identities"], (
        "five-sample contract selected a previously mined tree identity"
    )
    resource_inventory_game["mined_tree_identities"].add(selected_identity)
    assert engine_before["exists"] is True
    assert engine_before["name"] == selected.name
    assert engine_before["type"] == "tree"
    assert engine_before["position"] == {
        "x": selected.position.x,
        "y": selected.position.y,
    }

    declared_products = {
        product["name"] for product in engine_before["products"]
        if product.get("type", "item") == "item"
    }
    stand = _engine_stand_position(
        tier3, selected.position.x, selected.position.y
    )
    final_position = await walking.walk_to(
        MapPosition(x=stand["x"], y=stand["y"]),
        strict_goal=True,
        timeout=90,
    )
    assert math.hypot(
        final_position.x - selected.position.x,
        final_position.y - selected.position.y,
    ) < 2.0, "walk did not establish an unambiguous in-range mining position"
    reachable_tree = reachable_view.get_resource(selected.name, selected.position)
    assert reachable_tree is not None, (
        "engine-validated stand position did not expose the exact tree in get_reachable"
    )

    before = {name: inventory.check_total(name) for name in declared_products}
    depletion_error = None
    try:
        mined_stacks = await reachable_tree.mine(max_count=1, timeout=90)
    except TimeoutError as exc:
        # Preserve post-action evidence when the engine completed mining but
        # the causal DuckDB depletion barrier itself is the regression.
        depletion_error = exc
        mined_stacks = []
    returned = Counter()
    for stack in mined_stacks:
        returned[stack.name] += stack.count
    after = {name: inventory.check_total(name) for name in declared_products}

    inventory_delta = {name: after[name] - before[name] for name in declared_products}
    if depletion_error is None:
        reported_products = dict(returned)
    else:
        reported_products = {}

    engine_after = _engine_resource(
        tier3, selected.name, selected.position.x, selected.position.y
    )
    rows = remote_view.query(
        f"""
        SELECT count(*) AS count FROM resource_entity
        WHERE name = {_sql_string(selected.name)}
          AND position_x = {float(selected.position.x)}
          AND position_y = {float(selected.position.y)}
        """
    )
    assert engine_after == {"exists": False}, (
        "mining reported depletion but the exact Factorio tree still exists; "
        f"inventory_delta={inventory_delta}, returned={reported_products}, "
        f"resource_entity_rows={rows[0]['count']}"
    )
    assert inventory_delta["wood"] > 0
    assert returned, "engine reported a completed tree mine with no products"
    assert set(returned) <= declared_products
    assert returned["wood"] > 0
    assert {name: inventory_delta[name] for name in returned} == dict(returned)
    assert rows[0]["count"] == 0, (
        "Factorio removed the exact tree and credited its products, but "
        f"resource_entity retained the row; barrier error={depletion_error!r}"
    )
    assert depletion_error is None

    causal_facts = resource_inventory_game["mining"].last_causal_facts
    assert causal_facts["identity"] == {
        "name": selected.name,
        "type": "tree",
        "position": {
            "x": selected.position.x,
            "y": selected.position.y,
        },
    }
    assert causal_facts["engine_exists"] is False
    assert causal_facts["inventory_delta"] == dict(returned)
    assert causal_facts["destroy_event_tick"] is not None
    assert causal_facts["engine_destroy_event_tick"] == causal_facts["destroy_event_tick"]
    assert causal_facts["snapshot_destroy_event_tick"] == causal_facts["destroy_event_tick"]
    assert causal_facts["duckdb_delete_tick"] == causal_facts["destroy_event_tick"]
    assert causal_facts["duckdb_rows_removed"] == 1
    assert causal_facts["resource_present_at_action_start"] is True
    assert causal_facts["destroy_event_sequence"] > causal_facts["entity_sequence_floor"]
    assert causal_facts["destroy_action_id"]
    assert causal_facts["duckdb_depleted"] is True


async def test_burner_drill_craft_consumes_engine_recipe_and_creates_product(
    resource_inventory_game,
):
    """Craft deltas follow the active engine recipe, including its furnace."""
    tier3 = resource_inventory_game["tier3"]
    inventory = resource_inventory_game["inventory"]
    crafting = resource_inventory_game["crafting"]
    recipe_name = "burner-mining-drill"

    recipe = _engine_recipe(tier3, recipe_name)
    assert recipe["exists"] is True
    assert recipe["enabled"] is True
    assert recipe["category"] == "crafting"

    ingredients = {
        ingredient["name"]: int(ingredient["amount"])
        for ingredient in recipe["ingredients"]
        if ingredient.get("type", "item") == "item"
    }
    # This specific regression is meaningful only while the active recipe
    # actually declares a stone furnace; the amount itself remains engine-led.
    assert ingredients.get("stone-furnace", 0) > 0, recipe

    products: dict[str, int] = {}
    for product in recipe["products"]:
        if product.get("type", "item") != "item":
            continue
        assert product.get("amount") is not None, (
            "burner drill unexpectedly acquired a ranged product amount"
        )
        assert product.get("probability", 1) in (None, 1), (
            "burner drill unexpectedly acquired a probabilistic product"
        )
        products[product["name"]] = products.get(product["name"], 0) + int(
            product["amount"]
        )
    assert products.get(recipe_name, 0) > 0, recipe
    assert not (set(ingredients) & set(products)), recipe

    tier3.run_lua(
        "remote.call('admin', 'clear_inventory', 1); "
        f"remote.call('admin', 'add_items', 1, {_lua_item_map(ingredients)}); "
        "return true"
    )
    observed_names = set(ingredients) | set(products)
    engine_before = _engine_inventory_counts(tier3, observed_names)
    api_before = {name: inventory.check_total(name) for name in observed_names}
    assert engine_before == api_before == {
        **{name: count for name, count in ingredients.items()},
        **{name: 0 for name in products},
    }

    crafted_stacks = await crafting.craft(recipe_name, count=1, timeout=30)
    returned = Counter()
    for stack in crafted_stacks:
        returned[stack.name] += stack.count
    engine_after = _engine_inventory_counts(tier3, observed_names)
    api_after = {name: inventory.check_total(name) for name in observed_names}

    assert api_after == engine_after
    assert {
        name: engine_after[name] - engine_before[name]
        for name in ingredients
    } == {name: -count for name, count in ingredients.items()}
    assert {
        name: engine_after[name] - engine_before[name]
        for name in products
    } == products
    assert dict(returned) == products
    assert engine_after["stone-furnace"] == 0
