"""Integration tests for GhostBuilder focusing on placement operations.

Requirements:
- Factorio server running with test-ground scenario on port 27100
"""

import pytest
from factorio_rcon import RCONClient

from unittest.mock import MagicMock

from FactoryVerse.config import get_config
from FactoryVerse.infra.instance_manager import FactorioInstanceManager
from FactoryVerse.factory.types import MapPosition, Direction
from FactoryVerse.agent.infra.rcon_handler import RconHandler
from FactoryVerse.agent.embodied_actions.place_entity import PlacementAction
from FactoryVerse.agent.embodied_actions.entity_operations import EntityOperationsAction
from FactoryVerse.agent.placement_hints import PlacementHints


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture(scope="function")
def rcon_client():
    """RCON client for test-ground scenario."""
    config = get_config()
    instance = FactorioInstanceManager.from_env(config)
    client = RCONClient(instance.rcon_host, instance.rcon_port, instance.rcon_password)
    yield client


@pytest.fixture(scope="function")
def agent_name(rcon_client):
    """Create a fresh agent for each test."""
    # Create agent via RCON
    cmd = '/c local result = remote.call("agent", "create_agent", 34210, true, false, "player", {}); rcon.print(result.interface_name)'
    result = rcon_client.send_command(cmd)
    interface_name = result.strip()

    # Extract agent index (e.g., "agent_4" -> 4)
    agent_idx = int(interface_name.split("_")[1])

    yield interface_name

    # Cleanup after test - destroy this specific agent
    rcon_client.send_command(
        f'/c remote.call("agent", "destroy_agents", {{{agent_idx}}})'
    )


@pytest.fixture(scope="function")
def rcon_handler(rcon_client, agent_name):
    """RconHandler for actions."""
    return RconHandler(rcon_client, agent_id=agent_name)


@pytest.fixture(scope="function")
def entity_ops(rcon_handler):
    """EntityOperationsAction instance."""
    return EntityOperationsAction(rcon_handler)


@pytest.fixture(scope="function")
def walking_action():
    """Mock MovementAction for tests that don't need actual walking."""
    return MagicMock()


@pytest.fixture(scope="function")
def placement(rcon_handler, entity_ops, walking_action):
    """PlacementAction instance."""
    return PlacementAction(rcon_handler, entity_ops, walking_action)


@pytest.fixture(scope="function")
def hints(rcon_handler):
    """PlacementHints instance."""
    return PlacementHints(rcon_handler)


@pytest.fixture(scope="function")
def test_area(rcon_client, agent_name):
    """Clear test area and setup agent."""
    import random

    base_x = 100 + random.randint(0, 50)
    base_y = 100 + random.randint(0, 50)

    # Clear area
    clear_cmd = f"""
    /c local surface = game.surfaces[1]
    local area = {{left_top = {{x = {base_x - 20}, y = {base_y - 20}}}, right_bottom = {{x = {base_x + 20}, y = {base_y + 20}}}}}
    for _, entity in pairs(surface.find_entities_filtered{{area = area}}) do
        if entity.name ~= "character" then entity.destroy() end
    end
    """
    rcon_client.send_command(clear_cmd)

    # Teleport agent using /c command (confirmed working format)
    teleport_cmd = f'/c rcon.print(helpers.table_to_json(remote.call("{agent_name}", "teleport", {{x={base_x}, y={base_y}}})))'
    rcon_client.send_command(teleport_cmd)

    # Extract agent index from name (e.g., "agent_4" -> 4)
    agent_idx = int(agent_name.split("_")[1])

    # Give agent items for building using admin interface
    items_cmd = f'/c remote.call("admin", "add_items", {agent_idx}, {{["transport-belt"]=50, ["iron-chest"]=10, ["wooden-chest"]=10, ["inserter"]=10, ["pipe"]=20}})'
    rcon_client.send_command(items_cmd)

    yield MapPosition(x=float(base_x), y=float(base_y))

    rcon_client.send_command(clear_cmd)


# =============================================================================
# GHOST BUILDER UNIT TESTS
# =============================================================================


class TestGhostBuilderUnit:
    """Unit tests for GhostBuilder."""

    def test_ghost_info_dataclass(self):
        """Test GhostInfo dataclass."""
        from FactoryVerse.agent.ghost_builder import GhostInfo

        info = GhostInfo(
            name="transport-belt", position=MapPosition(x=10.0, y=20.0), direction=4
        )

        assert info.name == "transport-belt"
        assert info.position.x == 10.0
        assert info.direction == 4

    def test_ghost_builder_imports(self):
        """Test GhostBuilder can be imported."""
        from FactoryVerse.agent.ghost_builder import GhostBuilderAction

        assert GhostBuilderAction is not None


# =============================================================================
# GHOST PLACEMENT TESTS
# =============================================================================


class TestGhostPlacement:
    """Test ghost placement via PlacementAction."""

    def test_place_single_ghost(self, placement, test_area):
        """Test placing a single ghost entity."""
        pos = test_area

        result = placement.place(
            "transport-belt",
            MapPosition(x=pos.x + 5, y=pos.y),
            direction=Direction.EAST,
            ghost=True,
            label="test_ghost",
        )

        assert result.success
        assert result.is_ghost, f"Expected is_ghost=True, got {result}"
        assert result.entity_name == "transport-belt"

    def test_place_multiple_ghosts(self, placement, test_area):
        """Test placing multiple ghost entities."""
        pos = test_area

        placed = 0
        for i in range(5):
            result = placement.place(
                "transport-belt",
                MapPosition(x=pos.x + i, y=pos.y + 5),
                direction=Direction.EAST,
                ghost=True,
            )
            if result.success:
                placed += 1

        assert placed == 5

    def test_place_ghost_with_direction(self, placement, test_area):
        """Test placing ghost with specific direction."""
        pos = test_area

        for direction in [
            Direction.NORTH,
            Direction.EAST,
            Direction.SOUTH,
            Direction.WEST,
        ]:
            result = placement.place(
                "inserter",
                MapPosition(x=pos.x + direction.value, y=pos.y + 8),
                direction=direction,
                ghost=True,
            )
            assert result.success

    def test_place_real_entity_within_reach(self, placement, test_area):
        """Test placing a real entity within agent reach (~6 tiles)."""
        pos = test_area

        # Place close to agent - within reach distance
        result = placement.place(
            "iron-chest", MapPosition(x=pos.x + 2, y=pos.y + 2), ghost=False
        )

        assert result.success
        assert not result.is_ghost


# =============================================================================
# GHOST PLAN TESTS
# =============================================================================


class TestGhostPlanIntegration:
    """Test GhostPlan creation and ghost placement."""

    def test_create_validated_plan(self, hints, test_area):
        """Test creating a validated GhostPlan."""
        pos = test_area

        plan = hints.get_placement_line(
            "transport-belt",
            MapPosition(x=pos.x, y=pos.y + 10),
            MapPosition(x=pos.x + 5, y=pos.y + 10),
            validate=True,
        )

        assert plan.valid
        assert plan.entity_name == "transport-belt"
        assert len(plan.positions) == 6

    def test_place_ghosts_from_plan(self, hints, placement, test_area):
        """Test placing ghosts from a GhostPlan."""
        pos = test_area

        plan = hints.get_placement_line(
            "transport-belt",
            MapPosition(x=pos.x + 6, y=pos.y),
            MapPosition(x=pos.x + 10, y=pos.y),
            validate=True,
        )

        assert plan.valid

        # Place ghosts from plan
        placed_count = 0
        for gpos, direction in plan.positions:
            result = placement.place(
                plan.entity_name,
                gpos,
                direction=direction,
                ghost=True,
                label=plan.label,
            )
            if result.success:
                placed_count += 1

        assert placed_count == 5

    def test_place_ghosts_via_rcon_directly(self, hints, rcon_client, test_area):
        """Test placing ghosts from a plan directly via RCON."""
        pos = test_area

        plan = hints.get_placement_line(
            "pipe",
            MapPosition(x=pos.x, y=pos.y + 15),
            MapPosition(x=pos.x + 3, y=pos.y + 15),
            validate=True,
        )

        assert plan.valid

        # Place via RCON
        placed = 0
        for gpos, _ in plan.positions:
            cmd = f"""
            /sc local ghost = game.surfaces[1].create_entity{{
                name = "entity-ghost",
                position = {{x = {gpos.x}, y = {gpos.y}}},
                inner_name = "pipe",
                force = "player"
            }}
            rcon.print(ghost and "ok" or "fail")
            """
            result = rcon_client.send_command(cmd)
            if "ok" in result:
                placed += 1

        assert placed == len(plan.positions)


# =============================================================================
# GHOST CONVERSION TESTS
# =============================================================================


class TestGhostConversion:
    """Test converting ghosts to real entities."""

    def test_ghost_to_real_entity_via_rcon(self, rcon_client, test_area):
        """Test converting ghost to real entity via RCON (admin bypass)."""
        pos = test_area
        ghost_pos = MapPosition(x=pos.x + 3, y=pos.y + 3)

        # Place ghost directly via RCON (bypasses agent.place_entity which may build real)
        place_ghost_cmd = f"""
        /c local ghost = game.surfaces[1].create_entity{{
            name = "entity-ghost",
            position = {{x = {ghost_pos.x}, y = {ghost_pos.y}}},
            inner_name = "iron-chest",
            force = "player"
        }}
        rcon.print(ghost and "ghost_placed" or "fail")
        """
        place_result = rcon_client.send_command(place_ghost_cmd)
        assert "ghost_placed" in place_result

        # Convert via RCON (admin bypass - no reach check)
        convert_cmd = f"""
        /c local surface = game.surfaces[1]
        local ghosts = surface.find_entities_filtered{{
            ghost_name = "iron-chest",
            position = {{x = {ghost_pos.x}, y = {ghost_pos.y}}},
            radius = 1
        }}
        if #ghosts > 0 then
            local ghost = ghosts[1]
            local name = ghost.ghost_name
            local gpos = ghost.position
            ghost.destroy()
            local real = surface.create_entity{{
                name = name,
                position = gpos,
                force = "player"
            }}
            rcon.print(real and "built" or "fail")
        else
            rcon.print("no_ghost")
        end
        """
        result = rcon_client.send_command(convert_cmd)
        assert "built" in result

    def test_ghost_then_real_via_rcon(self, rcon_client, test_area):
        """Test that placing ghost then converting to real works."""
        pos = test_area
        target = MapPosition(x=pos.x + 5, y=pos.y + 5)

        # Place ghost via RCON
        place_cmd = f"""
        /c local ghost = game.surfaces[1].create_entity{{
            name = "entity-ghost",
            position = {{x = {target.x}, y = {target.y}}},
            inner_name = "wooden-chest",
            force = "player"
        }}
        rcon.print(ghost and "placed" or "fail")
        """
        place_result = rcon_client.send_command(place_cmd)
        assert "placed" in place_result

        # Verify ghost exists
        verify_cmd = f"""
        /c local ghosts = game.surfaces[1].find_entities_filtered{{
            ghost_name = "wooden-chest",
            position = {{x = {target.x}, y = {target.y}}},
            radius = 1
        }}
        rcon.print(#ghosts > 0 and "exists" or "missing")
        """
        verify_result = rcon_client.send_command(verify_cmd)
        assert "exists" in verify_result

        # Convert to real via revive
        revive_cmd = f"""
        /c local surface = game.surfaces[1]
        local ghosts = surface.find_entities_filtered{{
            ghost_name = "wooden-chest",
            position = {{x = {target.x}, y = {target.y}}},
            radius = 1
        }}
        if #ghosts > 0 then
            local _, real = ghosts[1].revive()
            rcon.print(real and "revived" or "revive_failed")
        else
            rcon.print("no_ghost")
        end
        """
        revive_result = rcon_client.send_command(revive_cmd)
        assert "revived" in revive_result


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
