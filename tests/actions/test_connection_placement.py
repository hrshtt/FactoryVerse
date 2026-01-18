"""Runtime tests for connection placement and ghost builder.

Tests:
- Mining drill output positions
- Pipe connections for generators/boilers
- GhostBuilder build_ghosts and build_plan

Requirements:
- Factorio server running with test-ground scenario on port 27100
"""

import pytest
from factorio_rcon import RCONClient

from FactoryVerse.config import get_config
from FactoryVerse.infra.instance_manager import FactorioInstanceManager
from FactoryVerse.factory.prototypes import get_entity_prototypes, apply_cardinal_vector
from FactoryVerse.factory.types import MapPosition, Direction
from FactoryVerse.agent.infra.rcon_handler import RconHandler
from FactoryVerse.agent.placement_hints import (
    PlacementValidator,
    PlacementHints,
    ConnectionType,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture(scope="module")
def rcon_client():
    """RCON client for test-ground scenario."""
    config = get_config()
    instance = FactorioInstanceManager.from_env(config)
    client = RCONClient(instance.rcon_host, instance.rcon_port, instance.rcon_password)
    yield client


@pytest.fixture(scope="module")
def rcon_handler(rcon_client):
    """RconHandler for PlacementValidator."""
    return RconHandler(rcon_client, agent_id="test_validator")


@pytest.fixture(scope="module")
def validator(rcon_handler):
    """PlacementValidator instance."""
    return PlacementValidator(rcon_handler)


@pytest.fixture(scope="module")
def hints(rcon_handler):
    """PlacementHints instance."""
    return PlacementHints(rcon_handler)


@pytest.fixture(scope="module")
def prototypes():
    """Entity prototypes for static data lookup."""
    return get_entity_prototypes()


@pytest.fixture(scope="function")
def clear_area(rcon_client):
    """Clear test area and return center position."""
    base_x = 80
    base_y = 80

    clear_cmd = f"""
    /sc local surface = game.surfaces[1]
    local area = {{left_top = {{x = {base_x - 15}, y = {base_y - 15}}}, right_bottom = {{x = {base_x + 15}, y = {base_y + 15}}}}}
    for _, entity in pairs(surface.find_entities_filtered{{area = area}}) do
        if entity.name ~= "character" then entity.destroy() end
    end
    """
    rcon_client.send_command(clear_cmd)

    yield MapPosition(x=float(base_x), y=float(base_y))

    rcon_client.send_command(clear_cmd)


# =============================================================================
# MINING DRILL OUTPUT POSITION TESTS
# =============================================================================


class TestMiningDrillOutput:
    """Tests for mining drill output position calculations."""

    def test_electric_drill_output_vector(self, prototypes):
        """Verify electric mining drill has correct output vector."""
        drill = prototypes.get_prototype("electric-mining-drill")
        assert "vector_to_place_result" in drill
        vec = drill["vector_to_place_result"]
        # Electric drill drops at [0, -1.85] (above center when facing north)
        assert vec[0] == 0
        assert vec[1] == pytest.approx(-1.85, rel=0.1)

    def test_burner_drill_output_vector(self, prototypes):
        """Verify burner mining drill has correct output vector."""
        drill = prototypes.get_prototype("burner-mining-drill")
        assert "vector_to_place_result" in drill
        vec = drill["vector_to_place_result"]
        # Burner drill drops at [-0.5, -1.3]
        assert vec[0] == pytest.approx(-0.5, rel=0.1)
        assert vec[1] == pytest.approx(-1.3, rel=0.1)

    def test_drill_output_position_north(self, prototypes):
        """Test drill output position when facing NORTH."""
        from FactoryVerse.factory.prototypes import (
            apply_cardinal_vector,
            snap_to_tile_center,
        )

        drill_pos = MapPosition(x=10.0, y=10.0)
        vec = tuple(
            prototypes.get_prototype("electric-mining-drill")["vector_to_place_result"]
        )

        output = apply_cardinal_vector(drill_pos, vec, Direction.NORTH)
        snapped = snap_to_tile_center(output)

        # NORTH: output above (lower y)
        assert snapped.y < drill_pos.y
        assert snapped.x == pytest.approx(drill_pos.x, abs=0.5)

    def test_drill_output_position_all_directions(self, prototypes):
        """Test drill output position rotates correctly for all directions."""
        from FactoryVerse.factory.prototypes import (
            apply_cardinal_vector,
            snap_to_tile_center,
        )

        drill_pos = MapPosition(x=20.0, y=20.0)
        vec = tuple(
            prototypes.get_prototype("electric-mining-drill")["vector_to_place_result"]
        )

        outputs = {}
        for direction in [
            Direction.NORTH,
            Direction.EAST,
            Direction.SOUTH,
            Direction.WEST,
        ]:
            output = apply_cardinal_vector(drill_pos, vec, direction)
            outputs[direction] = snap_to_tile_center(output)

        # NORTH output should be above center
        assert outputs[Direction.NORTH].y < drill_pos.y
        # SOUTH output should be below center
        assert outputs[Direction.SOUTH].y > drill_pos.y
        # EAST output should be to the right
        assert outputs[Direction.EAST].x > drill_pos.x
        # WEST output should be to the left
        assert outputs[Direction.WEST].x < drill_pos.x


# =============================================================================
# GENERATOR PIPE CONNECTION TESTS
# =============================================================================


class TestGeneratorPipeConnections:
    """Tests for steam engine and boiler pipe connections."""

    def test_steam_engine_pipe_connection_data(self, prototypes):
        """Verify steam engine has correct pipe connection data."""
        engine = prototypes.get_prototype("steam-engine")
        assert "fluid_box" in engine

        fluid_box = engine["fluid_box"]
        connections = fluid_box["pipe_connections"]

        assert len(connections) == 2

        # Top connection: direction=0 (NORTH), position=[0, -2]
        # Bottom connection: direction=8 (SOUTH), position=[0, 2]
        top_conn = next(c for c in connections if c["direction"] == 0)
        bottom_conn = next(c for c in connections if c["direction"] == 8)

        assert top_conn["position"] == [0, -2]
        assert bottom_conn["position"] == [0, 2]

    def test_boiler_pipe_connection_data(self, prototypes):
        """Verify boiler has correct pipe connection data (input and output)."""
        boiler = prototypes.get_prototype("boiler")

        # Input fluid box (water)
        input_box = boiler["fluid_box"]
        input_conns = input_box["pipe_connections"]
        assert len(input_conns) == 2

        # Output fluid box (steam)
        output_box = boiler["output_fluid_box"]
        output_conns = output_box["pipe_connections"]
        assert len(output_conns) == 1
        assert output_conns[0]["flow_direction"] == "output"

    def test_pipe_connection_position_calculation(self, prototypes):
        """Test pipe connection position calculation with direction rotation."""
        # Steam engine at (50, 50) facing NORTH
        engine_pos = MapPosition(x=50.0, y=50.0)
        engine_dir = Direction.NORTH

        engine_proto = prototypes.get_prototype("steam-engine")
        connections = engine_proto["fluid_box"]["pipe_connections"]

        pipe_positions = []
        for conn in connections:
            pos_data = conn["position"]
            vec = tuple(pos_data)
            pipe_pos = apply_cardinal_vector(engine_pos, vec, engine_dir)
            pipe_positions.append(pipe_pos)

        # Engine facing NORTH:
        # - Top connection at (50, 50) + (0, -2) = (50, 48)
        # - Bottom connection at (50, 50) + (0, 2) = (50, 52)
        assert any(p.y == pytest.approx(48) for p in pipe_positions)
        assert any(p.y == pytest.approx(52) for p in pipe_positions)

    def test_pipe_connection_rotation_east(self, prototypes):
        """Test pipe connections when engine faces EAST."""
        engine_pos = MapPosition(x=50.0, y=50.0)
        engine_dir = Direction.EAST

        engine_proto = prototypes.get_prototype("steam-engine")
        connections = engine_proto["fluid_box"]["pipe_connections"]

        pipe_positions = []
        for conn in connections:
            pos_data = conn["position"]
            vec = tuple(pos_data)
            pipe_pos = apply_cardinal_vector(engine_pos, vec, engine_dir)
            pipe_positions.append(pipe_pos)

        # Engine facing EAST: top becomes left, bottom becomes right
        # Original (0, -2) rotated EAST -> (2, 0) -- to the right
        # Original (0, 2) rotated EAST -> (-2, 0) -- to the left
        assert any(p.x == pytest.approx(52) for p in pipe_positions)
        assert any(p.x == pytest.approx(48) for p in pipe_positions)


# =============================================================================
# PLACEMENT HINTS CONNECTION SOLVING TESTS
# =============================================================================


class TestPlacementHintsConnectionSolving:
    """Tests for PlacementHints.get_connection_positions()."""

    def test_fluid_pipe_positions_returns_list(self, hints, rcon_client, clear_area):
        """Test that _get_fluid_pipe_positions returns a list."""
        # Place a boiler
        boiler_pos = clear_area
        place_cmd = f"""
        /sc local e = game.surfaces[1].create_entity{{
            name = "boiler",
            position = {{x = {boiler_pos.x}, y = {boiler_pos.y}}},
            direction = defines.direction.north,
            force = "player"
        }}
        rcon.print(e and "placed" or "failed")
        """
        result = rcon_client.send_command(place_cmd)

        if "placed" not in result:
            pytest.skip("Could not place boiler for test")

        # Create a mock entity object
        class MockEntity:
            name = "boiler"
            position = boiler_pos
            direction = Direction.NORTH
            prototype = get_entity_prototypes().get_prototype("boiler")

        mock_boiler = MockEntity()

        # Note: get_connection_positions expects the source entity to have prototype attr
        positions = hints._get_fluid_pipe_positions(mock_boiler, "pipe")

        assert isinstance(positions, list)


# =============================================================================
# GHOST BUILDER TESTS
# =============================================================================


class TestGhostBuilderBasics:
    """Basic tests for GhostBuilder without full async infrastructure."""

    def test_ghost_builder_imports(self):
        """Verify ghost builder can be imported."""
        from FactoryVerse.agent.ghost_builder import (
            GhostBuilderAction,
            GhostInfo,
        )

        assert GhostBuilderAction is not None
        assert GhostInfo is not None

    def test_ghost_info_dataclass(self):
        """Test GhostInfo dataclass creation."""
        from FactoryVerse.agent.ghost_builder import GhostInfo

        info = GhostInfo(
            name="transport-belt", position=MapPosition(x=10.0, y=20.0), direction=4
        )

        assert info.name == "transport-belt"
        assert info.position.x == 10.0
        assert info.direction == 4

    def test_extract_ghost_info(self):
        """Test ghost info extraction from entity-like object."""
        from FactoryVerse.agent.ghost_builder import GhostBuilderAction

        # Create mock objects
        class MockMovement:
            async def walk_to(self, pos):
                pass

        class MockPlacement:
            def place(self, name, pos, direction=None, ghost=False, label=None):
                pass

        class MockInventory:
            item_stacks = []

        class MockGhostEntity:
            ghost_name = "inserter"
            name = "entity-ghost"
            position = MapPosition(x=5.0, y=10.0)
            direction = 2

        builder = GhostBuilderAction(
            movement=MockMovement(),
            placement=MockPlacement(),
            inventory=MockInventory(),
        )

        ghost = MockGhostEntity()
        info = builder._extract_ghost_info(ghost)

        assert info.name == "inserter"  # Uses ghost_name, not name
        assert info.position.x == 5.0
        assert info.direction == 2


class TestGhostPlacementRuntime:
    """Runtime tests for ghost placement via RCON."""

    def test_place_ghosts_via_rcon(self, rcon_client, clear_area):
        """Test placing ghost entities directly via RCON."""
        base = clear_area

        # Place 3 belt ghosts in a line
        for i in range(3):
            place_cmd = f"""
            /sc local ghost = game.surfaces[1].create_entity{{
                name = "entity-ghost",
                position = {{x = {base.x + i}, y = {base.y}}},
                direction = defines.direction.east,
                inner_name = "transport-belt",
                force = "player"
            }}
            rcon.print(ghost and "ok" or "fail")
            """
            result = rcon_client.send_command(place_cmd)
            assert "ok" in result, f"Failed to place ghost at position {i}"

        # Verify ghosts exist
        count_cmd = f"""
        /sc local ghosts = game.surfaces[1].find_entities_filtered{{
            ghost_name = "transport-belt",
            area = {{
                left_top = {{x = {base.x - 1}, y = {base.y - 1}}},
                right_bottom = {{x = {base.x + 4}, y = {base.y + 1}}}
            }}
        }}
        rcon.print(#ghosts)
        """
        count = rcon_client.send_command(count_cmd)
        assert count.strip() == "3"

    def test_convert_ghost_to_real_entity(self, rcon_client, clear_area):
        """Test converting a ghost to a real entity (simulating build)."""
        pos = clear_area

        # Place a ghost and immediately convert it to verify the flow
        # Do everything in one command to avoid any cleanup issues
        combined_cmd = f"""
        /sc local surface = game.surfaces[1]
        local pos = {{x = {pos.x}, y = {pos.y}}}
        
        -- Create ghost
        local ghost = surface.create_entity{{
            name = "entity-ghost",
            position = pos,
            direction = defines.direction.north,
            inner_name = "iron-chest",
            force = "player"
        }}
        
        if not ghost then
            rcon.print("ghost_creation_failed")
            return
        end
        
        -- Get ghost info
        local ghost_name = ghost.ghost_name
        local ghost_dir = ghost.direction
        local ghost_pos = ghost.position
        
        -- Destroy ghost
        ghost.destroy()
        
        -- Create real entity
        local real = surface.create_entity{{
            name = ghost_name,
            position = ghost_pos,
            direction = ghost_dir,
            force = "player"
        }}
        
        rcon.print(real and "built" or "real_creation_failed")
        """
        result = rcon_client.send_command(combined_cmd)
        assert "built" in result, f"Expected 'built', got: {result}"

        # Verify real entity exists (use area search since position may be snapped)
        verify_cmd = f"""
        /sc local chests = game.surfaces[1].find_entities_filtered{{
            name = "iron-chest",
            position = {{x = {pos.x}, y = {pos.y}}},
            radius = 1
        }}
        rcon.print(#chests > 0 and "exists" or "missing")
        """
        verify_result = rcon_client.send_command(verify_cmd)
        assert "exists" in verify_result


class TestGhostPlanIntegration:
    """Integration tests for GhostPlan + placement."""

    def test_create_and_place_belt_line_plan(self, hints, rcon_client, clear_area):
        """Test creating a belt line plan and placing ghosts from it."""
        start = clear_area
        end = MapPosition(x=start.x + 4, y=start.y)

        # Create validated plan
        plan = hints.get_placement_line("transport-belt", start, end, validate=True)

        assert plan.valid
        assert len(plan.positions) == 5

        # Place ghosts from plan positions
        placed = 0
        for pos, direction in plan.positions:
            dir_val = direction.value if direction else 0
            place_cmd = f"""
            /sc local ghost = game.surfaces[1].create_entity{{
                name = "entity-ghost",
                position = {{x = {pos.x}, y = {pos.y}}},
                direction = {dir_val},
                inner_name = "transport-belt",
                force = "player"
            }}
            rcon.print(ghost and "ok" or "fail")
            """
            result = rcon_client.send_command(place_cmd)
            if "ok" in result:
                placed += 1

        assert placed == 5, f"Expected 5 ghosts placed, got {placed}"

        # Verify ghosts in game
        count_cmd = f"""
        /sc local ghosts = game.surfaces[1].find_entities_filtered{{
            ghost_name = "transport-belt",
            area = {{
                left_top = {{x = {start.x - 0.5}, y = {start.y - 0.5}}},
                right_bottom = {{x = {end.x + 0.5}, y = {end.y + 0.5}}}
            }}
        }}
        rcon.print(#ghosts)
        """
        count = rcon_client.send_command(count_cmd)
        assert count.strip() == "5"


# =============================================================================
# EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Edge case tests for placement and ghost handling."""

    def test_place_ghost_at_occupied_position_fails(self, rcon_client, clear_area):
        """Test that placing a ghost at occupied position fails validation."""
        pos = clear_area

        # Place real entity first
        place_real_cmd = f"""
        /sc game.surfaces[1].create_entity{{
            name = "iron-chest",
            position = {{x = {pos.x}, y = {pos.y}}},
            force = "player"
        }}
        """
        rcon_client.send_command(place_real_cmd)

        # Try to validate ghost placement - should fail
        from FactoryVerse.agent.placement_hints import PlacementValidator

        validator = PlacementValidator(RconHandler(rcon_client, "test"))
        result = validator.validate_placement(
            "transport-belt", pos, direction=Direction.EAST, ghost=True
        )

        assert result is False, "Should not be able to place ghost on occupied tile"

    def test_drill_output_to_chest_calculation(self, prototypes):
        """Test calculating where to place a chest for drill output."""
        from FactoryVerse.factory.prototypes import (
            apply_cardinal_vector,
            snap_to_tile_center,
        )

        # Drill at (100, 100) facing NORTH
        drill_pos = MapPosition(x=100.0, y=100.0)
        drill_dir = Direction.NORTH

        vec = tuple(
            prototypes.get_prototype("electric-mining-drill")["vector_to_place_result"]
        )
        output_pos = snap_to_tile_center(
            apply_cardinal_vector(drill_pos, vec, drill_dir)
        )

        # Output when facing NORTH is above (lower y)
        # vector is [0, -1.85], so output is at approx (100, 98.15) -> snapped to (100.5, 97.5)
        assert output_pos.y < drill_pos.y

        # A 1x1 chest placed at output_pos would receive items
        # The drill drops items at the output position, which falls inside/on the chest's tile


# =============================================================================
# ENTITY VALIDATION TESTS
# =============================================================================


class TestEntityValidation:
    """Tests for entity validation on connection methods."""

    def test_item_drop_rejects_non_drill(self, hints, prototypes):
        """Test that ITEM_DROP fails for non-drill entities."""
        from FactoryVerse.agent.placement_hints import (
            EntityValidationError,
            ConnectionType,
        )

        # Create a mock chest entity
        class MockEntity:
            name = "iron-chest"
            position = MapPosition(x=50.0, y=50.0)
            prototype = prototypes.get_prototype("iron-chest")

        with pytest.raises(EntityValidationError, match="ITEM_DROP.*not applicable"):
            hints.get_connection_positions(
                MockEntity(), "transport-belt", ConnectionType.ITEM_DROP
            )

    def test_fluid_pipe_rejects_non_fluid_entity(self, hints, prototypes):
        """Test that FLUID_PIPE fails for non-fluid entities."""
        from FactoryVerse.agent.placement_hints import (
            EntityValidationError,
            ConnectionType,
        )

        class MockEntity:
            name = "inserter"
            position = MapPosition(x=50.0, y=50.0)
            direction = Direction.NORTH
            prototype = prototypes.get_prototype("inserter")

        with pytest.raises(EntityValidationError, match="FLUID_PIPE.*not applicable"):
            hints.get_connection_positions(
                MockEntity(), "pipe", ConnectionType.FLUID_PIPE
            )

    def test_item_drop_accepts_mining_drill(self, hints, prototypes):
        """Test that ITEM_DROP works for electric-mining-drill."""
        from FactoryVerse.agent.placement_hints import (
            ITEM_DROP_ENTITIES,
            ConnectionType,
        )

        # Verify entity is in the set
        assert "electric-mining-drill" in ITEM_DROP_ENTITIES

        class MockDrill:
            name = "electric-mining-drill"
            position = MapPosition(x=50.0, y=50.0)
            direction = Direction.NORTH
            prototype = prototypes.get_prototype("electric-mining-drill")

        # Should not raise - returns list (may be empty if no valid positions)
        positions = hints.get_connection_positions(
            MockDrill(), "iron-chest", ConnectionType.ITEM_DROP
        )
        assert isinstance(positions, list)

    def test_fluid_pipe_accepts_boiler(self, hints, prototypes):
        """Test that FLUID_PIPE works for boiler."""
        from FactoryVerse.agent.placement_hints import (
            FLUID_PIPE_ENTITIES,
            ConnectionType,
        )

        # Verify entity is in the set
        assert "boiler" in FLUID_PIPE_ENTITIES

        class MockBoiler:
            name = "boiler"
            position = MapPosition(x=50.0, y=50.0)
            direction = Direction.NORTH
            prototype = prototypes.get_prototype("boiler")

        # Should not raise - returns list (may be empty if prototype has no connections)
        positions = hints.get_connection_positions(
            MockBoiler(), "pipe", ConnectionType.FLUID_PIPE
        )
        assert isinstance(positions, list)

    def test_entity_sets_are_frozen(self):
        """Test that entity sets are immutable."""
        from FactoryVerse.agent.placement_hints import (
            ITEM_DROP_ENTITIES,
            FLUID_PIPE_ENTITIES,
            RESOURCE_PLACEMENT_ENTITIES,
            WATER_PLACEMENT_ENTITIES,
        )

        # FrozenSets should raise TypeError on modification attempts
        with pytest.raises(AttributeError):
            ITEM_DROP_ENTITIES.add("fake-entity")

        with pytest.raises(AttributeError):
            FLUID_PIPE_ENTITIES.add("fake-entity")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
