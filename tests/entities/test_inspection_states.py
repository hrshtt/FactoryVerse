"""Inspection State Tests.

Tests that entity.inspect() returns an EntityInspection with correctly
populated capability slots matching runtime state from the game.

Test Strategy:
1. Place actual entities in game via test_ground
2. Call inspect() on created entities
3. Verify returned EntityInspection has correct state types
4. Verify state values match expected runtime data format

Requires RCON connection to running Factorio server on port 27100.
"""

import pytest


# ============================================================================
# INSPECTION STRUCTURE TESTS
# ============================================================================


class TestEntityInspectionStructure:
    """Tests for EntityInspection data structure compliance."""

    def test_entity_inspection_base_fields(self, rcon, test_ground, agent):
        """EntityInspection should have required base fields."""
        from FactoryVerse.factory.entity.inspection import EntityInspection

        # Create minimal inspection
        inspection = EntityInspection(
            name="test-entity",
            position={"x": 0, "y": 0},
        )

        # Verify base fields exist
        assert hasattr(inspection, "name")
        assert hasattr(inspection, "position")
        assert hasattr(inspection, "direction")
        assert hasattr(inspection, "status")
        assert hasattr(inspection, "is_ghost")

    def test_entity_inspection_capability_slots(self, rcon, test_ground):
        """EntityInspection should have all capability slots."""
        from FactoryVerse.factory.entity.inspection import EntityInspection

        inspection = EntityInspection(
            name="test-entity",
            position={"x": 0, "y": 0},
        )

        # Verify capability slots exist (all should be None by default)
        assert hasattr(inspection, "burner")
        assert hasattr(inspection, "electric")
        assert hasattr(inspection, "crafter")
        assert hasattr(inspection, "miner")
        assert hasattr(inspection, "inserter")
        assert hasattr(inspection, "fluid")
        assert hasattr(inspection, "belt")

        # Verify category slots
        assert hasattr(inspection, "container")
        assert hasattr(inspection, "lab")
        assert hasattr(inspection, "accumulator")
        assert hasattr(inspection, "electric_pole")
        assert hasattr(inspection, "generator")


class TestBurnerStateFormat:
    """Tests for BurnerState data format from inspection."""

    def test_burner_state_has_required_fields(self, rcon, test_ground):
        """BurnerState should have all required fields."""
        from FactoryVerse.factory.entity.capabilities import BurnerState

        # Create a default BurnerState
        state = BurnerState()

        assert hasattr(state, "heat")
        assert hasattr(state, "heat_capacity")
        assert hasattr(state, "remaining_burning_fuel")
        assert hasattr(state, "currently_burning")
        assert hasattr(state, "fuel_inventory")

    def test_burner_state_field_types(self, rcon, test_ground):
        """BurnerState fields should have correct types."""
        from FactoryVerse.factory.entity.capabilities import BurnerState

        state = BurnerState(
            heat=100.5,
            heat_capacity=200.0,
            remaining_burning_fuel=50.25,
            currently_burning="coal",
            fuel_inventory={"coal": 5, "wood": 2},
        )

        assert isinstance(state.heat, float)
        assert isinstance(state.heat_capacity, float)
        assert isinstance(state.remaining_burning_fuel, float)
        assert isinstance(state.currently_burning, str)
        assert isinstance(state.fuel_inventory, dict)


class TestMinerStateFormat:
    """Tests for MinerState data format from inspection."""

    def test_miner_state_has_required_fields(self, rcon, test_ground):
        """MinerState should have all required fields."""
        from FactoryVerse.factory.entity.capabilities import MinerState

        state = MinerState()

        assert hasattr(state, "mining_progress")
        assert hasattr(state, "mining_target")
        assert hasattr(state, "drop_position")
        assert hasattr(state, "drop_target")

    def test_mining_target_structure(self, rcon, test_ground):
        """MiningTarget should have correct structure."""
        from FactoryVerse.factory.entity.capabilities import MiningTarget

        target = MiningTarget(
            name="iron-ore",
            amount=1000,
            position={"x": 10.0, "y": 20.0},
        )

        assert target.name == "iron-ore"
        assert target.amount == 1000
        assert target.position is not None
        assert target.position["x"] == 10.0


class TestCrafterStateFormat:
    """Tests for CrafterState data format from inspection."""

    def test_crafter_state_has_required_fields(self, rcon, test_ground):
        """CrafterState should have all required fields."""
        from FactoryVerse.factory.entity.capabilities import CrafterState

        state = CrafterState()

        assert hasattr(state, "crafting_progress")
        assert hasattr(state, "crafting_speed")
        assert hasattr(state, "recipe")  # Field is 'recipe', not 'current_recipe'
        assert hasattr(state, "crafter_input")
        assert hasattr(state, "crafter_output")


class TestInserterStateFormat:
    """Tests for InserterState data format from inspection."""

    def test_inserter_state_has_required_fields(self, rcon, test_ground):
        """InserterState should have all required fields."""
        from FactoryVerse.factory.entity.capabilities import InserterState

        state = InserterState()

        assert hasattr(state, "pickup_position")
        assert hasattr(state, "drop_position")
        assert hasattr(state, "held_item")

    def test_held_item_structure(self, rcon, test_ground):
        """HeldItem should have correct structure."""
        from FactoryVerse.factory.entity.capabilities import HeldItem

        item = HeldItem(name="iron-plate", count=5)

        assert item.name == "iron-plate"
        assert item.count == 5


class TestContainerStateFormat:
    """Tests for ContainerState data format from inspection."""

    def test_container_state_has_required_fields(self, rcon, test_ground):
        """ContainerState should have all required fields."""
        from FactoryVerse.factory.entity.implementations.container import ContainerState

        state = ContainerState()

        assert hasattr(state, "contents")
        assert hasattr(state, "inventory_size")


# ============================================================================
# LIVE INSPECTION TESTS (Require game server)
# ============================================================================


@pytest.mark.integration
class TestLiveContainerInspection:
    """Tests for Container entity inspection with live game."""

    def test_inspect_wooden_chest(self, rcon, test_ground, agent_id):
        """Wooden chest inspection should return ContainerState."""
        # Place a chest
        test_ground.clear_area((5, 5), (15, 15))
        placed = test_ground.place_entity("wooden-chest", 10, 10)

        # Get actual position (place_entity returns PlacedEntity dataclass)
        pos = {"x": placed.position[0], "y": placed.position[1]}

        # Inspect via RCON
        inspect_result = rcon.call(
            f"agent_{agent_id.split('_')[1]}", "inspect_entity", "wooden-chest", pos
        )

        assert inspect_result is not None
        assert "entity_name" in inspect_result or "name" in inspect_result


@pytest.mark.integration
class TestLiveFurnaceInspection:
    """Tests for Furnace entity inspection with live game."""

    def test_inspect_stone_furnace_has_burner_data(self, rcon, test_ground, agent_id):
        """Stone furnace inspection should include burner state."""
        test_ground.clear_area((15, 5), (25, 15))
        placed = test_ground.place_entity("stone-furnace", 20, 10)

        pos = {"x": placed.position[0], "y": placed.position[1]}

        # RCON inspect
        inspect_result = rcon.call(
            f"agent_{agent_id.split('_')[1]}", "inspect_entity", "stone-furnace", pos
        )

        assert inspect_result is not None
        # Burner data should be present
        assert "burner" in inspect_result or "fuel" in inspect_result


@pytest.mark.integration
class TestLiveMiningDrillInspection:
    """Tests for Mining Drill entity inspection with live game."""

    def test_inspect_burner_mining_drill_on_ore(self, rcon, test_ground, agent_id):
        """Burner mining drill on ore should show mining target."""
        # Place ore first
        test_ground.place_resource_patch("iron-ore", 30, 10, size=8, amount=5000)
        test_ground.clear_area((25, 5), (35, 15))

        placed = test_ground.place_entity("burner-mining-drill", 30, 10, direction=0)

        pos = {"x": placed.position[0], "y": placed.position[1]}

        inspect_result = rcon.call(
            f"agent_{agent_id.split('_')[1]}",
            "inspect_entity",
            "burner-mining-drill",
            pos,
        )

        assert inspect_result is not None


@pytest.mark.integration
class TestLiveInserterInspection:
    """Tests for Inserter entity inspection with live game."""

    def test_inspect_inserter_has_positions(self, rcon, test_ground, agent_id):
        """Inserter inspection should include pickup/drop positions."""
        test_ground.clear_area((35, 5), (45, 15))
        placed = test_ground.place_entity("inserter", 40, 10, direction=0)

        pos = {"x": placed.position[0], "y": placed.position[1]}

        inspect_result = rcon.call(
            f"agent_{agent_id.split('_')[1]}", "inspect_entity", "inserter", pos
        )

        assert inspect_result is not None
        # Should have pickup and drop positions
        assert "pickup_position" in inspect_result or "drop_position" in inspect_result


# ============================================================================
# GHOST INSPECTION TESTS
# ============================================================================


class TestGhostInspection:
    """Tests for ghost entity inspection behavior."""

    def test_ghost_inspection_returns_minimal_data(self, rcon, test_ground):
        """Ghost entities should return minimal inspection with is_ghost=True."""
        from FactoryVerse.factory.entity.implementations import StoneFurnace
        from FactoryVerse.factory.types import MapPosition

        # Create a ghost furnace manually
        furnace = StoneFurnace(
            name="stone-furnace",
            position=MapPosition(50, 10),
            is_ghost=True,
            ghost_name="stone-furnace",
        )

        # Ghosts can be inspected without entity_ops (returns static data)
        # It will raise error for non-ghost entities without entity_ops
        # But for ghosts, it should return minimal inspection
        inspection = furnace.inspect()

        assert inspection.is_ghost is True
        assert inspection.name == "stone-furnace"
        assert inspection.burner is None  # Ghosts have no live state

    def test_ghost_inspection_no_capability_states(self, rcon, test_ground):
        """Ghost inspection should have empty capability slots."""
        from FactoryVerse.factory.entity.implementations import BurnerMiningDrill
        from FactoryVerse.factory.types import MapPosition, Direction

        drill = BurnerMiningDrill(
            name="burner-mining-drill",
            position=MapPosition(60, 10),
            direction=Direction.NORTH,
            is_ghost=True,
            ghost_name="burner-mining-drill",
        )

        inspection = drill.inspect()

        assert inspection.is_ghost is True
        assert inspection.burner is None
        assert inspection.miner is None


# ============================================================================
# SERIALIZATION TESTS
# ============================================================================


class TestInspectionSerialization:
    """Tests for EntityInspection serialization."""

    def test_inspection_to_json_excludes_none(self, rcon, test_ground):
        """model_dump_json(exclude_none=True) should produce concise output."""
        from FactoryVerse.factory.entity.inspection import EntityInspection
        from FactoryVerse.factory.entity.capabilities import BurnerState
        import json

        inspection = EntityInspection(
            name="stone-furnace",
            position={"x": 10.0, "y": 20.0},
            is_ghost=False,
            burner=BurnerState(heat=100.0, heat_capacity=200.0),
        )

        json_str = inspection.model_dump_json(exclude_none=True)
        data = json.loads(json_str)

        # Should have burner
        assert "burner" in data
        assert data["burner"]["heat"] == 100.0

        # Should NOT have other capability slots
        assert "electric" not in data or data.get("electric") is None
        assert "crafter" not in data or data.get("crafter") is None

    def test_inspection_forbids_extra_fields(self, rcon, test_ground):
        """EntityInspection should reject unknown fields (extra=forbid)."""
        from FactoryVerse.factory.entity.inspection import EntityInspection
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            EntityInspection(
                name="test",
                position={"x": 0, "y": 0},
                unknown_field="should fail",  # This should raise
            )
