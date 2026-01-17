"""Complex Inspection Tests.

Tests for complex entity interactions and inspection validation.
These tests spawn multiple entities (e.g. power + drill + ore) and verify
that the inspection data correctly reflects the composed state.
"""

import pytest
import asyncio
from typing import Dict, Generator

from FactoryVerse.factory.entity.inspection import EntityInspection
from FactoryVerse.factory.entity.transform import transform_inspection_data
from FactoryVerse.infra.boilerplate.test_ground import TestGroundHelper


@pytest.fixture(scope="function")
def test_ground(rcon) -> Generator[TestGroundHelper, None, None]:
    """Fixture to provide TestGroundHelper."""
    # TestGroundHelper expects a dict-like context with 'rcon' key
    # pointing to an object with send_command method.
    # The 'rcon' fixture is RconHelper, so we access its rcon_client.
    mock_ctx = {"rcon": rcon.rcon_client}
    tg = TestGroundHelper(mock_ctx)
    yield tg
    # Cleanup if needed


@pytest.mark.integration
class TestComplexEntityInspection:
    """Tests for complex multi-entity inspection scenarios."""

    @pytest.fixture(autouse=True)
    async def setup_teardown(self, test_ground):
        """Clear area before each test."""
        # Use a safe area away from spawn to avoid collisions
        self.center_x = 100
        self.center_y = 100
        self.test_area_size = 50

        # Clear the test area
        test_ground.clear_area(
            (self.center_x - self.test_area_size, self.center_y - self.test_area_size),
            (self.center_x + self.test_area_size, self.center_y + self.test_area_size),
        )
        yield
        # Cleanup could go here but clearing before test is usually sufficient

    async def _teleport_agent(self, rcon, agent_id: str, x: float, y: float):
        """Teleport agent to a position."""
        # teleport expects position as a nested dict: {'position': {'x': x, 'y': y}}
        rcon.run(agent_id, "teleport", {"position": {"x": x, "y": y}})
        await asyncio.sleep(0.1)

    async def _inspect_entity(
        self, rcon, agent_id: str, name: str, pos: Dict[str, float]
    ) -> EntityInspection:
        """Helper to inspect an entity via RCON and transform to EntityInspection."""
        # Teleport agent to entity first
        await self._teleport_agent(rcon, agent_id, pos["x"], pos["y"])

        # Inspect entity
        args = {"entity_name": name, "position": pos}
        raw_data = rcon.run(agent_id, "inspect_entity", args)

        # Transform to EntityInspection model
        return transform_inspection_data(raw_data)

    async def test_mining_drill_inspection_impl(self, rcon, test_ground, tier4):
        """Actual implementation with correct fixtures."""
        agent_id = tier4.agent_id

        # 1. Spawn Iron Ore
        ore_x, ore_y = self.center_x, self.center_y
        test_ground.place_resource_patch("iron-ore", ore_x, ore_y, size=5, amount=5000)

        # 2. Spawn Drill
        drill_res = test_ground.place_entity(
            "electric-mining-drill", ore_x, ore_y, direction=0
        )
        print(f"DEBUG: drill_res={drill_res}")
        drill_pos = drill_res.get("position", {"x": ore_x, "y": ore_y})
        print(f"DEBUG: drill_pos={drill_pos}")

        # 3. Power
        test_ground.place_entity("electric-energy-interface", ore_x + 2, ore_y)

        # 4. Wait for game update
        cmd = "/c game.tick_paused = false"
        rcon.rcon_client.send_command(cmd)
        await asyncio.sleep(0.5)  # Wait for some ticks

        # 5. Inspect - returns EntityInspection model
        inspection = await self._inspect_entity(
            rcon, agent_id, "electric-mining-drill", drill_pos
        )

        # 6. Validate using EntityInspection model
        # Should have 'miner' capability
        assert inspection.miner is not None
        miner_state = inspection.miner

        # Validating MinerState fields
        assert miner_state.mining_target is not None
        assert miner_state.mining_target.name == "iron-ore"
        # Status might be working or no output space

        # Check energy status
        assert inspection.electric is not None
        # Energy might be 0 initially

        print(f"DEBUG: Inspection successful: {inspection}")

    async def test_furnace_burning_inspection(self, rcon, test_ground, tier4):
        """Test inspection of a burning furnace."""
        agent_id = tier4.agent_id
        pos_x, pos_y = self.center_x + 10, self.center_y

        # 1. Spawn Stone Furnace
        furnace_res = test_ground.place_entity("stone-furnace", pos_x, pos_y)
        furnace_pos = furnace_res.get("position", {"x": pos_x, "y": pos_y})

        # 2. Teleport agent to furnace
        await self._teleport_agent(rcon, agent_id, pos_x, pos_y)

        # 3. Add items via admin (using correct agent index)
        # Extract agent index from agent_id (e.g., "agent_1" -> 1)
        agent_index = int(agent_id.split("_")[1]) if "_" in agent_id else 1

        # Use raw RCON command to add items
        cmd = f"/c remote.call('admin', 'add_items', {agent_index}, {{['coal'] = 50, ['iron-ore'] = 50}})"
        rcon.rcon_client.send_command(cmd)
        await asyncio.sleep(0.1)

        # 4. Put items into furnace
        # Put Fuel
        rcon.run(
            agent_id,
            "put_inventory_item",
            {
                "entity_name": "stone-furnace",
                "position": furnace_pos,
                "inventory_type": "fuel",
                "item_name": "coal",
                "count": 5,
            },
        )

        # Put Input
        rcon.run(
            agent_id,
            "put_inventory_item",
            {
                "entity_name": "stone-furnace",
                "position": furnace_pos,
                "inventory_type": "input",
                "item_name": "iron-ore",
                "count": 5,
            },
        )

        # Wait for burning/smelting
        await asyncio.sleep(1.0)

        # 5. Inspect - returns EntityInspection model
        inspection = await self._inspect_entity(
            rcon, agent_id, "stone-furnace", furnace_pos
        )

        # 6. Validate using EntityInspection model
        assert inspection.burner is not None
        assert inspection.burner.remaining_burning_fuel > 0
        # Currently burning might be None if furnace hasn't started yet, but fuel should be present
        assert (
            inspection.burner.currently_burning == "coal"
            or "coal" in inspection.burner.fuel_inventory
        )

        # Furnaces also have crafter capability
        assert inspection.crafter is not None

        print(f"DEBUG: Furnace inspection successful: {inspection}")

    async def test_assembler_recipe_inspection(self, rcon, test_ground, tier4):
        """Test inspection of assembler with recipe."""
        agent_id = tier4.agent_id
        pos_x, pos_y = self.center_x + 20, self.center_y

        # 1. Assembler + Power
        asm_res = test_ground.place_entity("assembling-machine-1", pos_x, pos_y)
        asm_pos = asm_res.get("position", {"x": pos_x, "y": pos_y})
        test_ground.place_entity("electric-energy-interface", pos_x + 2, pos_y)

        # 2. Teleport agent to assembler
        await self._teleport_agent(rcon, agent_id, pos_x, pos_y)

        # 3. Set Recipe
        rcon.run(
            agent_id,
            "set_entity_recipe",
            {
                "entity_name": "assembling-machine-1",
                "position": asm_pos,
                "recipe_name": "iron-gear-wheel",
            },
        )

        await asyncio.sleep(0.1)

        # 4. Inspect - returns EntityInspection model
        inspection = await self._inspect_entity(
            rcon, agent_id, "assembling-machine-1", asm_pos
        )

        # 5. Validate using EntityInspection model
        assert inspection.crafter is not None
        assert inspection.crafter.recipe == "iron-gear-wheel"

        print(f"DEBUG: Assembler inspection successful: {inspection}")

    async def test_power_network_inspection(self, rcon, test_ground, tier4):
        """Test inspection of electric network components."""
        agent_id = tier4.agent_id
        pos_x, pos_y = self.center_x + 30, self.center_y

        # 1. Pole and Engine
        pole_res = test_ground.place_entity("small-electric-pole", pos_x, pos_y)
        # Use the actual position from the result
        pole_pos = pole_res.get("metadata", {}).get(
            "position", {"x": pos_x, "y": pos_y}
        )
        test_ground.place_entity("steam-engine", pos_x + 3, pos_y)

        # 2. Inspect Pole - returns EntityInspection model
        inspection = await self._inspect_entity(
            rcon, agent_id, "small-electric-pole", pole_pos
        )

        # 3. Validate using EntityInspection model
        assert inspection.electric_pole is not None
        # ElectricPoleState has network_id and connected_poles

        print(f"DEBUG: Electric pole inspection successful: {inspection}")
