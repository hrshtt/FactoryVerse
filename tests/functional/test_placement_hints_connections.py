"""Functional tests for Placement Hints connection solving.

Tests the implemented connection types (ITEM_DROP, FLUID_PIPE) with real entities
placed in the game world. These tests verify that the connection solving algorithms
correctly identify valid positions for connecting entities.

Tests follow the pattern from test_complex_inspection.py:
- Use TestGroundHelper to place entities
- Use RCON to interact with game state
- Verify connection positions are valid and correctly aligned
"""

import pytest
import asyncio
from typing import Dict, Generator

from FactoryVerse.factory.types import MapPosition, Direction
from FactoryVerse.agent.placement_hints import (
    PlacementHints,
    ConnectionType,
    ConnectionPosition,
    EntityValidationError,
)
from FactoryVerse.infra.boilerplate.test_ground import TestGroundHelper


@pytest.fixture(scope="function")
def test_ground(rcon) -> Generator[TestGroundHelper, None, None]:
    """Fixture to provide TestGroundHelper."""
    # TestGroundHelper expects a dict-like context with 'rcon' key
    mock_ctx = {"rcon": rcon.rcon_client}
    tg = TestGroundHelper(mock_ctx)
    yield tg


@pytest.fixture(scope="function")
def placement_hints(tier4) -> PlacementHints:
    """Fixture to provide PlacementHints from tier4 runtime."""
    return tier4.placement_hints


@pytest.mark.integration
class TestItemDropConnection:
    """Tests for ITEM_DROP connection type (mining drill -> chest/belt)."""

    @pytest.fixture(autouse=True)
    async def setup_teardown(self, test_ground):
        """Clear area before each test."""
        self.center_x = 100
        self.center_y = 100
        self.test_area_size = 50

        # Clear the test area
        test_ground.clear_area(
            (self.center_x - self.test_area_size, self.center_y - self.test_area_size),
            (self.center_x + self.test_area_size, self.center_y + self.test_area_size),
        )
        yield

    async def _teleport_agent(self, rcon, agent_id: str, x: float, y: float):
        """Teleport agent to a position."""
        rcon.run(agent_id, "teleport", {"position": {"x": x, "y": y}})
        await asyncio.sleep(0.1)

    async def _get_entity_as_base_entity(
        self, rcon, agent_id: str, reachable_view, entity_name: str, pos: Dict[str, float]
    ) -> "BaseEntity":
        """Get an entity as BaseEntity by teleporting agent and fetching from reachable view."""
        from FactoryVerse.factory.types import MapPosition

        # Teleport agent to entity
        await self._teleport_agent(rcon, agent_id, pos["x"], pos["y"])

        # Wait for reachable view to update
        await asyncio.sleep(0.2)

        # Get entity from reachable view - try with position first
        entity_pos = MapPosition(x=pos["x"], y=pos["y"])
        entity = reachable_view.get_entity(entity_name, position=entity_pos)
        if entity is None:
            # Try getting all entities and filtering by proximity
            entities = reachable_view.get_entities(entity_name)
            for e in entities:
                if abs(e.position.x - pos["x"]) < 1.0 and abs(e.position.y - pos["y"]) < 1.0:
                    return e
            raise ValueError(f"Could not find entity {entity_name} at {pos}")

        return entity

    async def test_drill_to_chest_connection_north(
        self, rcon, test_ground, tier4, placement_hints, reachable_view
    ):
        """Test finding chest positions to receive items from a drill facing NORTH."""
        agent_id = tier4.agent_id

        # 1. Place iron ore patch
        ore_x, ore_y = self.center_x, self.center_y
        test_ground.place_resource_patch("iron-ore", ore_x, ore_y, size=5, amount=5000)

        # 2. Place mining drill facing NORTH
        drill_res = test_ground.place_entity(
            "electric-mining-drill", ore_x, ore_y, direction=0  # 0 = NORTH
        )
        drill_pos = drill_res.get("position", {"x": ore_x, "y": ore_y})

        # 3. Power the drill
        test_ground.place_entity("electric-energy-interface", ore_x + 2, ore_y)

        # 4. Wait for game update
        await asyncio.sleep(0.5)

        # 5. Get drill as BaseEntity
        drill_entity = await self._get_entity_as_base_entity(
            rcon, agent_id, reachable_view, "electric-mining-drill", drill_pos
        )

        # 6. Get connection positions for placing a chest
        connection_positions = placement_hints.get_connection_positions(
            source_entity=drill_entity,
            target_entity_name="iron-chest",
            connection_type=ConnectionType.ITEM_DROP,
        )

        # 7. Validate results
        assert len(connection_positions) > 0, "Should find at least one valid chest position"

        # All positions should be ConnectionPosition objects
        for conn_pos in connection_positions:
            assert isinstance(conn_pos, ConnectionPosition)
            assert conn_pos.position is not None
            assert conn_pos.perpendicular_offset >= 0.0

        # Best position should be aligned (low perpendicular_offset)
        best_pos = connection_positions[0]
        assert best_pos.perpendicular_offset <= 1.0, "Best position should be well-aligned"

        # Verify positions are validated (can actually place chests there)
        validator = placement_hints.validator
        for conn_pos in connection_positions[:3]:  # Check first 3 positions
            can_place = validator.validate_placement(
                "iron-chest", conn_pos.position, conn_pos.direction, ghost=True
            )
            assert can_place, f"Position {conn_pos.position} should be valid for chest placement"

        print(f"DEBUG: Found {len(connection_positions)} valid chest positions")
        print(f"DEBUG: Best position: {best_pos.position}, offset: {best_pos.perpendicular_offset}")

    async def test_drill_to_belt_connection_east(
        self, rcon, test_ground, tier4, placement_hints, reachable_view
    ):
        """Test finding belt positions to receive items from a drill facing EAST."""
        agent_id = tier4.agent_id

        # 1. Place ore patch
        ore_x, ore_y = self.center_x + 20, self.center_y
        test_ground.place_resource_patch("iron-ore", ore_x, ore_y, size=5, amount=5000)

        # 2. Place mining drill facing EAST (direction=2)
        drill_res = test_ground.place_entity(
            "electric-mining-drill", ore_x, ore_y, direction=2  # 2 = EAST
        )
        drill_pos = drill_res.get("position", {"x": ore_x, "y": ore_y})

        # 3. Power the drill
        test_ground.place_entity("electric-energy-interface", ore_x, ore_y + 2)

        # 4. Wait for game update
        await asyncio.sleep(0.5)

        # 5. Get drill as BaseEntity
        drill_entity = await self._get_entity_as_base_entity(
            rcon, agent_id, reachable_view, "electric-mining-drill", drill_pos
        )

        # 6. Get connection positions for placing a belt
        connection_positions = placement_hints.get_connection_positions(
            source_entity=drill_entity,
            target_entity_name="transport-belt",
            connection_type=ConnectionType.ITEM_DROP,
        )

        # 7. Validate results
        assert len(connection_positions) > 0, "Should find at least one valid belt position"

        # Check that positions are relative to drill's output (based on drill's actual direction)
        # The drill was placed facing EAST (direction=2), so output should be to the right
        # But we should check the actual entity direction to be safe
        actual_direction = drill_entity.direction
        best_pos = connection_positions[0]
        
        # For EAST-facing drill, output is to the right (higher x)
        # For NORTH-facing drill, output is above (lower y)
        # For SOUTH-facing drill, output is below (higher y)
        # For WEST-facing drill, output is to the left (lower x)
        if actual_direction == Direction.EAST:
            assert best_pos.position.x > drill_entity.position.x, "Belt should be to the right of EAST-facing drill"
        elif actual_direction == Direction.NORTH:
            assert best_pos.position.y < drill_entity.position.y, "Belt should be above NORTH-facing drill"
        elif actual_direction == Direction.SOUTH:
            assert best_pos.position.y > drill_entity.position.y, "Belt should be below SOUTH-facing drill"
        elif actual_direction == Direction.WEST:
            assert best_pos.position.x < drill_entity.position.x, "Belt should be to the left of WEST-facing drill"

        # Verify positions are validated
        validator = placement_hints.validator
        for conn_pos in connection_positions[:3]:
            can_place = validator.validate_placement(
                "transport-belt",
                conn_pos.position,
                conn_pos.direction,
                ghost=True,
            )
            assert can_place, f"Position {conn_pos.position} should be valid for belt placement"

        print(f"DEBUG: Found {len(connection_positions)} valid belt positions for EAST-facing drill")


@pytest.mark.integration
class TestFluidPipeConnection:
    """Tests for FLUID_PIPE connection type (fluid entities -> pipes)."""

    @pytest.fixture(autouse=True)
    async def setup_teardown(self, test_ground):
        """Clear area before each test."""
        self.center_x = 150
        self.center_y = 100
        self.test_area_size = 50

        # Clear the test area
        test_ground.clear_area(
            (self.center_x - self.test_area_size, self.center_y - self.test_area_size),
            (self.center_x + self.test_area_size, self.center_y + self.test_area_size),
        )
        yield

    async def _teleport_agent(self, rcon, agent_id: str, x: float, y: float):
        """Teleport agent to a position."""
        rcon.run(agent_id, "teleport", {"position": {"x": x, "y": y}})
        await asyncio.sleep(0.1)

    async def _get_entity_as_base_entity(
        self, rcon, agent_id: str, reachable_view, entity_name: str, pos: Dict[str, float]
    ) -> "BaseEntity":
        """Get an entity as BaseEntity by teleporting agent and fetching from reachable view."""
        from FactoryVerse.factory.types import MapPosition

        # Teleport agent to entity
        await self._teleport_agent(rcon, agent_id, pos["x"], pos["y"])

        # Wait for reachable view to update
        await asyncio.sleep(0.2)

        # Get entity from reachable view - try with position first
        entity_pos = MapPosition(x=pos["x"], y=pos["y"])
        entity = reachable_view.get_entity(entity_name, position=entity_pos)
        if entity is None:
            # Try getting all entities and filtering by proximity
            entities = reachable_view.get_entities(entity_name)
            for e in entities:
                if abs(e.position.x - pos["x"]) < 1.0 and abs(e.position.y - pos["y"]) < 1.0:
                    return e
            raise ValueError(f"Could not find entity {entity_name} at {pos}")

        return entity

    async def test_boiler_pipe_connections(
        self, rcon, test_ground, tier4, placement_hints, reachable_view
    ):
        """Test finding pipe positions to connect to a boiler."""
        agent_id = tier4.agent_id

        # 1. Place boiler facing NORTH
        boiler_x, boiler_y = self.center_x, self.center_y
        boiler_res = test_ground.place_entity(
            "boiler", boiler_x, boiler_y, direction=0  # 0 = NORTH
        )
        boiler_pos = boiler_res.get("position", {"x": boiler_x, "y": boiler_y})

        # 2. Wait for game update
        await asyncio.sleep(0.5)

        # 3. Get boiler as BaseEntity
        boiler_entity = await self._get_entity_as_base_entity(
            rcon, agent_id, reachable_view, "boiler", boiler_pos
        )

        # 4. Get connection positions for placing pipes
        connection_positions = placement_hints.get_connection_positions(
            source_entity=boiler_entity,
            target_entity_name="pipe",
            connection_type=ConnectionType.FLUID_PIPE,
        )

        # 5. Validate results
        assert len(connection_positions) > 0, "Should find at least one valid pipe position"

        # Boiler should have input and output connections
        # Input connections (water): typically on left/right sides
        # Output connections (steam): typically on top/bottom
        # We should find multiple connection points
        assert len(connection_positions) >= 2, "Boiler should have multiple pipe connection points"

        # All positions should be ConnectionPosition objects
        for conn_pos in connection_positions:
            assert isinstance(conn_pos, ConnectionPosition)
            assert conn_pos.position is not None

        # Verify positions are validated (can actually place pipes there)
        validator = placement_hints.validator
        for conn_pos in connection_positions:
            can_place = validator.validate_placement(
                "pipe", conn_pos.position, conn_pos.direction, ghost=True
            )
            assert can_place, f"Position {conn_pos.position} should be valid for pipe placement"

        print(f"DEBUG: Found {len(connection_positions)} valid pipe positions for boiler")
        for i, conn_pos in enumerate(connection_positions):
            print(f"DEBUG: Position {i}: {conn_pos.position}")

    async def test_steam_engine_pipe_connections(
        self, rcon, test_ground, tier4, placement_hints, reachable_view
    ):
        """Test finding pipe positions to connect to a steam engine."""
        agent_id = tier4.agent_id

        # 1. Place steam engine facing NORTH
        engine_x, engine_y = self.center_x + 20, self.center_y
        engine_res = test_ground.place_entity(
            "steam-engine", engine_x, engine_y, direction=0  # 0 = NORTH
        )
        engine_pos = engine_res.get("position", {"x": engine_x, "y": engine_y})

        # 2. Wait for game update
        await asyncio.sleep(0.5)

        # 3. Get steam engine as BaseEntity
        engine_entity = await self._get_entity_as_base_entity(
            rcon, agent_id, reachable_view, "steam-engine", engine_pos
        )

        # 4. Get connection positions for placing pipes
        connection_positions = placement_hints.get_connection_positions(
            source_entity=engine_entity,
            target_entity_name="pipe",
            connection_type=ConnectionType.FLUID_PIPE,
        )

        # 5. Validate results
        assert len(connection_positions) > 0, "Should find at least one valid pipe position"

        # Steam engine typically has 2 connections (top and bottom)
        assert len(connection_positions) >= 2, "Steam engine should have top and bottom connections"

        # Verify positions are validated
        validator = placement_hints.validator
        for conn_pos in connection_positions:
            can_place = validator.validate_placement(
                "pipe", conn_pos.position, conn_pos.direction, ghost=True
            )
            assert can_place, f"Position {conn_pos.position} should be valid for pipe placement"

        print(f"DEBUG: Found {len(connection_positions)} valid pipe positions for steam engine")

    async def test_chemical_plant_pipe_connections(
        self, rcon, test_ground, tier4, placement_hints, reachable_view
    ):
        """Test finding pipe positions to connect to a chemical plant."""
        agent_id = tier4.agent_id

        # 1. Place chemical plant facing NORTH
        plant_x, plant_y = self.center_x + 40, self.center_y
        plant_res = test_ground.place_entity(
            "chemical-plant", plant_x, plant_y, direction=0  # 0 = NORTH
        )
        plant_pos = plant_res.get("position", {"x": plant_x, "y": plant_y})

        # 2. Power the plant
        test_ground.place_entity("electric-energy-interface", plant_x + 3, plant_y)

        # 3. Wait for game update
        await asyncio.sleep(0.5)

        # 4. Get chemical plant as BaseEntity
        plant_entity = await self._get_entity_as_base_entity(
            rcon, agent_id, reachable_view, "chemical-plant", plant_pos
        )

        # 5. Get connection positions for placing pipes
        connection_positions = placement_hints.get_connection_positions(
            source_entity=plant_entity,
            target_entity_name="pipe",
            connection_type=ConnectionType.FLUID_PIPE,
        )

        # 6. Validate results
        assert len(connection_positions) > 0, "Should find at least one valid pipe position"

        # Chemical plants typically have multiple fluid input/output connections
        assert (
            len(connection_positions) >= 2
        ), "Chemical plant should have multiple pipe connection points"

        # Verify positions are validated
        validator = placement_hints.validator
        for conn_pos in connection_positions:
            can_place = validator.validate_placement(
                "pipe", conn_pos.position, conn_pos.direction, ghost=True
            )
            assert can_place, f"Position {conn_pos.position} should be valid for pipe placement"

        print(f"DEBUG: Found {len(connection_positions)} valid pipe positions for chemical plant")


@pytest.mark.integration
class TestConnectionValidation:
    """Tests for connection type validation and error handling."""

    async def test_item_drop_rejects_non_drill(self, placement_hints, reachable_view):
        """Test that ITEM_DROP connection type rejects non-drill entities."""
        # Create a mock chest entity (not a drill)
        class MockChest:
            name = "iron-chest"
            position = MapPosition(x=50.0, y=50.0)
            prototype = {"name": "iron-chest"}

        with pytest.raises(EntityValidationError, match="ITEM_DROP.*not applicable"):
            placement_hints.get_connection_positions(
                MockChest(), "transport-belt", ConnectionType.ITEM_DROP
            )

    async def test_fluid_pipe_rejects_non_fluid_entity(
        self, placement_hints, reachable_view
    ):
        """Test that FLUID_PIPE connection type rejects non-fluid entities."""
        # Create a mock inserter entity (not a fluid entity)
        class MockInserter:
            name = "inserter"
            position = MapPosition(x=50.0, y=50.0)
            direction = Direction.NORTH
            prototype = {"name": "inserter"}

        with pytest.raises(EntityValidationError, match="FLUID_PIPE.*not applicable"):
            placement_hints.get_connection_positions(
                MockInserter(), "pipe", ConnectionType.FLUID_PIPE
            )
