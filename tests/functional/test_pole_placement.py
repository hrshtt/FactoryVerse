"""Functional tests for pole placement API.

Tests the dry-run pole placement evaluation and connection position finding.
"""

import pytest
import asyncio
from typing import Dict, Generator

from FactoryVerse.game.factory.types import MapPosition, Direction
from FactoryVerse.game.agent.placement_hints import (
    PlacementHints,
    ConnectionType,
    ConnectionPosition,
    WireConnectionPosition,
    PolePlacementResult,
    EntityValidationError,
)
from FactoryVerse.game.scenarios import TestGroundHelper


@pytest.fixture(scope="function")
def test_ground(rcon) -> Generator[TestGroundHelper, None, None]:
    mock_ctx = {"rcon": rcon.rcon_client}
    tg = TestGroundHelper(mock_ctx)
    yield tg


@pytest.fixture(scope="function")
def placement_hints(tier4) -> PlacementHints:
    return tier4.placement_hints


@pytest.fixture(scope="function")
def reachable_view(tier4):
    return tier4.reachable_view


@pytest.mark.integration
class TestPoleConnectionPositions:
    """Tests for ELECTRIC_WIRE connection type (pole -> pole)."""

    @pytest.fixture(autouse=True)
    async def setup_teardown(self, test_ground):
        """Clear area before each test."""
        self.center_x = 200
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
    ):
        """Get an entity as BaseEntity by teleporting agent and fetching from reachable view."""
        from FactoryVerse.game.factory.types import MapPosition

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

    async def test_pole_connection_positions(
        self, rcon, test_ground, tier4, placement_hints, reachable_view
    ):
        """Test finding connection positions from a source pole."""
        agent_id = tier4.agent_id

        # 1. Place a source pole
        pole_x, pole_y = self.center_x, self.center_y
        pole_res = test_ground.place_entity(
            "medium-electric-pole", pole_x, pole_y
        )
        pole_pos = pole_res.get("position", {"x": pole_x, "y": pole_y})

        # 2. Wait for game update
        await asyncio.sleep(0.5)

        # 3. Get source pole as BaseEntity
        source_pole = await self._get_entity_as_base_entity(
            rcon, agent_id, reachable_view, "medium-electric-pole", pole_pos
        )

        # 4. Get connection positions for placing another pole
        connection_positions = placement_hints.get_connection_positions(
            source_entity=source_pole,
            target_entity_name="medium-electric-pole",
            connection_type=ConnectionType.ELECTRIC_WIRE,
        )

        # 5. Validate results
        assert len(connection_positions) > 0, "Should find at least one valid pole position"

        # All positions should be within wire distance (with small tolerance for floating point)
        # Get actual wire distance from prototype
        from FactoryVerse.game.factory.prototypes import get_entity_prototypes
        prototypes = get_entity_prototypes()
        pole_proto = prototypes.get_prototype("medium-electric-pole")
        max_wire_distance = pole_proto.get("maximum_wire_distance", 7.5)
        
        for conn_pos in connection_positions:
            # Verify it's a WireConnectionPosition instance
            assert isinstance(conn_pos, WireConnectionPosition), "ELECTRIC_WIRE connections should return WireConnectionPosition"
            
            distance = source_pole.position.distance(conn_pos.position)
            # Allow small tolerance for floating point precision and grid-based generation
            assert distance <= max_wire_distance + 0.1, f"Position {conn_pos.position} is beyond wire distance (distance: {distance:.3f}, max: {max_wire_distance})"
            assert conn_pos.direction is None, "Poles don't have direction"
            assert conn_pos.perpendicular_offset >= 0, "Distance should be non-negative"
            
            # Check wire distance and utilization are set and correct
            assert abs(conn_pos.wire_distance - distance) < 0.01, \
                f"wire_distance should be {distance:.3f}, got {conn_pos.wire_distance:.3f}"
            
            expected_utilization = distance / max_wire_distance if max_wire_distance > 0 else 0.0
            assert abs(conn_pos.wire_distance_utilization - expected_utilization) < 0.01, \
                f"wire_distance_utilization should be {expected_utilization:.3f}, got {conn_pos.wire_distance_utilization:.3f}"
            assert 0.0 <= conn_pos.wire_distance_utilization <= 1.0 + 0.01, \
                f"wire_distance_utilization should be between 0.0 and 1.0 (got {conn_pos.wire_distance_utilization:.3f})"

        # Positions should be sorted by distance (closest first)
        distances = [p.perpendicular_offset for p in connection_positions]
        assert distances == sorted(distances), "Positions should be sorted by distance"

        # Verify positions are validated
        validator = placement_hints.validator
        for conn_pos in connection_positions[:5]:  # Check first 5
            can_place = validator.validate_placement(
                "medium-electric-pole", conn_pos.position, None, ghost=True
            )
            assert can_place, f"Position {conn_pos.position} should be valid for pole placement"

        # 6. Verify wire_distance_utilization is set correctly
        # Check a few positions at different distances
        close_positions = [p for p in connection_positions if p.perpendicular_offset < max_wire_distance * 0.5]
        far_positions = [p for p in connection_positions if p.perpendicular_offset > max_wire_distance * 0.8]
        
        if close_positions:
            close_pos = close_positions[0]
            assert isinstance(close_pos, WireConnectionPosition)
            assert close_pos.wire_distance_utilization < 0.6, "Close positions should use less than 60% of wire distance"
            print(f"DEBUG: Close position: distance={close_pos.wire_distance:.2f} tiles, utilization={close_pos.wire_distance_utilization:.1%}")
        
        if far_positions:
            far_pos = far_positions[0]
            assert isinstance(far_pos, WireConnectionPosition)
            assert far_pos.wire_distance_utilization > 0.8, "Far positions should use more than 80% of wire distance"
            print(f"DEBUG: Far position: distance={far_pos.wire_distance:.2f} tiles, utilization={far_pos.wire_distance_utilization:.1%}")

        print(f"DEBUG: Found {len(connection_positions)} valid pole positions")

    async def test_pole_connection_rejects_non_pole(
        self, rcon, test_ground, tier4, placement_hints, reachable_view
    ):
        """Test that ELECTRIC_WIRE connection type rejects non-pole entities."""
        agent_id = tier4.agent_id

        # Place a chest (not a pole)
        chest_x, chest_y = self.center_x + 10, self.center_y
        chest_res = test_ground.place_entity("iron-chest", chest_x, chest_y)
        chest_pos = chest_res.get("position", {"x": chest_x, "y": chest_y})

        await asyncio.sleep(0.5)

        chest_entity = await self._get_entity_as_base_entity(
            rcon, agent_id, reachable_view, "iron-chest", chest_pos
        )

        with pytest.raises(EntityValidationError, match="ELECTRIC_WIRE.*not applicable"):
            placement_hints.get_connection_positions(
                source_entity=chest_entity,
                target_entity_name="medium-electric-pole",
                connection_type=ConnectionType.ELECTRIC_WIRE,
            )


@pytest.mark.integration
class TestPolePlacementEvaluation:
    """Tests for dry-run pole placement evaluation."""

    @pytest.fixture(autouse=True)
    async def setup_teardown(self, test_ground):
        """Clear area before each test."""
        self.center_x = 250
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
    ):
        """Get an entity as BaseEntity by teleporting agent and fetching from reachable view."""
        from FactoryVerse.game.factory.types import MapPosition

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

    async def test_evaluate_pole_placement_basic(
        self, rcon, test_ground, tier4, placement_hints, reachable_view
    ):
        """Test basic pole placement evaluation."""
        agent_id = tier4.agent_id

        # 1. Place a mining drill (entity that needs power)
        drill_x, drill_y = self.center_x, self.center_y
        test_ground.place_resource_patch("iron-ore", drill_x, drill_y, size=5, amount=5000)
        drill_res = test_ground.place_entity(
            "electric-mining-drill", drill_x, drill_y, direction=0
        )
        drill_pos = drill_res.get("position", {"x": drill_x, "y": drill_y})

        # 2. Wait for game update
        await asyncio.sleep(0.5)

        # 3. Teleport agent near drill
        await self._teleport_agent(rcon, agent_id, drill_x, drill_y)

        # 4. Evaluate a position for pole placement
        pole_position = MapPosition(x=drill_x + 5, y=drill_y)
        result = placement_hints.evaluate_pole_placement(
            position=pole_position,
            pole_name="medium-electric-pole",
            reachable_view=reachable_view,
        )

        # 5. Validate result structure
        assert isinstance(result, PolePlacementResult)
        assert result.position == pole_position
        assert result.pole_name == "medium-electric-pole"
        assert result.supply_area_distance > 0
        assert result.maximum_wire_distance > 0

        # 6. Check if drill would be powered (within supply area)
        if result.is_valid_placement:
            # Check if drill is in entities_powered
            drill_entities = [e for e in result.entities_powered if e.name == "electric-mining-drill"]
            if drill_entities:
                print(f"DEBUG: Drill would be powered at position {pole_position}")
            else:
                print(f"DEBUG: Drill would NOT be powered (distance: {pole_position.distance(MapPosition(drill_x, drill_y)):.2f}, supply: {result.supply_area_distance:.2f})")

        print(f"DEBUG: Evaluation result: valid={result.is_valid_placement}, entities_powered={result.entities_powered_count}")

    async def test_evaluate_pole_placement_with_source(
        self, rcon, test_ground, tier4, placement_hints, reachable_view
    ):
        """Test pole placement evaluation with source pole connectivity check."""
        agent_id = tier4.agent_id

        # 1. Place a source pole
        source_x, source_y = self.center_x, self.center_y
        source_res = test_ground.place_entity(
            "medium-electric-pole", source_x, source_y
        )
        source_pos = source_res.get("position", {"x": source_x, "y": source_y})

        # 2. Wait for game update
        await asyncio.sleep(0.5)

        # 3. Get source pole
        await self._teleport_agent(rcon, agent_id, source_x, source_y)
        await asyncio.sleep(0.3)
        
        # Get entity using helper method for consistency
        source_pole = await self._get_entity_as_base_entity(
            rcon, agent_id, reachable_view, "medium-electric-pole", source_pos
        )
        assert source_pole is not None

        # 4. Evaluate a position within wire distance
        close_position = MapPosition(x=source_x + 5, y=source_y)  # Within 7.5 tile wire distance
        result = placement_hints.evaluate_pole_placement(
            position=close_position,
            pole_name="medium-electric-pole",
            source_pole=source_pole,
            reachable_view=reachable_view,
        )

        # 5. Validate connectivity
        assert result.source_pole == source_pole
        assert result.distance_to_source is not None
        assert result.distance_to_source <= result.maximum_wire_distance
        assert result.connects_to_source, "Should connect to source pole within wire distance"

        # 6. Evaluate a position beyond wire distance (but still valid for placement)
        # Find a valid position that's beyond wire distance
        max_wire_distance = result.maximum_wire_distance
        far_x = source_x + int(max_wire_distance) + 5  # Well beyond wire distance
        
        # Try to find a valid position at this distance
        far_position = MapPosition(x=far_x, y=source_y)
        result_far = placement_hints.evaluate_pole_placement(
            position=far_position,
            pole_name="medium-electric-pole",
            source_pole=source_pole,
            reachable_view=reachable_view,
        )
        
        # If this position is invalid, try a different one
        if not result_far.is_valid_placement:
            # Try a few positions to find a valid one
            for offset in [1, 2, 3, -1, -2, -3]:
                test_pos = MapPosition(x=far_x + offset, y=source_y)
                test_result = placement_hints.evaluate_pole_placement(
                    position=test_pos,
                    pole_name="medium-electric-pole",
                    source_pole=source_pole,
                    reachable_view=reachable_view,
                )
                if test_result.is_valid_placement:
                    result_far = test_result
                    far_position = test_pos
                    break

        # 7. Should not connect to source (if we found a valid position)
        if result_far.is_valid_placement:
            assert result_far.distance_to_source is not None
            assert result_far.distance_to_source > result_far.maximum_wire_distance
            assert not result_far.connects_to_source, "Should NOT connect to source pole beyond wire distance"

        print(f"DEBUG: Close position connects: {result.connects_to_source} (distance: {result.distance_to_source:.2f})")
        print(f"DEBUG: Far position connects: {result_far.connects_to_source} (distance: {result_far.distance_to_source:.2f})")
