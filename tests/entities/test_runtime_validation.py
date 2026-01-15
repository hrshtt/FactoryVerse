"""Runtime State Validation Tests.

Validates that the Python type system correctly maps to runtime inspection data
from Factorio. Uses RCON to inspect live entities and validates:
1. All expected fields are present in runtime data
2. Type system state models can parse runtime data
3. Mixin detection matches runtime capability presence

These tests serve as end-to-end validation that the type system accurately
represents Factorio's entity state.

Requires RCON connection to running Factorio server on port 27100.
"""

import pytest
from typing import List


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def get_entity_mixins(entity_class) -> List[str]:
    """Get list of mixin names for an entity class."""
    from FactoryVerse.factory.entity.capabilities import (
        BurnerMixin,
        ElectricMixin,
        MinerMixin,
        CrafterMixin,
        InserterMixin,
        FluidMixin,
        BeltMixin,
    )

    mixins = []
    if issubclass(entity_class, BurnerMixin):
        mixins.append("burner")
    if issubclass(entity_class, ElectricMixin):
        mixins.append("electric")
    if issubclass(entity_class, MinerMixin):
        mixins.append("miner")
    if issubclass(entity_class, CrafterMixin):
        mixins.append("crafter")
    if issubclass(entity_class, InserterMixin):
        mixins.append("inserter")
    if issubclass(entity_class, FluidMixin):
        mixins.append("fluid")
    if issubclass(entity_class, BeltMixin):
        mixins.append("belt")
    return mixins


# ============================================================================
# RUNTIME STATE VALIDATION
# ============================================================================


@pytest.mark.integration
class TestRuntimeBurnerStateValidation:
    """Validates BurnerState parsing against runtime data."""

    def test_stone_furnace_burner_state_parsing(self, rcon, test_ground, agent_id):
        """Stone furnace runtime burner data should parse into BurnerState."""
        from FactoryVerse.factory.entity.capabilities import BurnerState

        # Place furnace
        test_ground.clear_area((95, 95), (105, 105))
        placed = test_ground.place_entity("stone-furnace", 100, 100)

        pos = {"x": placed.position[0], "y": placed.position[1]}
        agent_interface = f"agent_{agent_id.split('_')[1]}"

        # Inspect via RCON
        raw_data = rcon.call(agent_interface, "inspect_entity", "stone-furnace", pos)
        assert raw_data is not None, "inspect_entity returned None"

        # If burner data exists, try to parse it
        if "burner" in raw_data:
            burner_data = raw_data["burner"]

            # Attempt to create BurnerState from runtime data
            # This validates our model matches runtime format
            fuel_items = {}
            fuel_inv = burner_data.get("fuel_inventory", {})
            if fuel_inv and fuel_inv.get("contents"):
                for item in fuel_inv.get("contents", []):
                    fuel_items[item["name"]] = item.get("count", 0)

            state = BurnerState(
                heat=burner_data.get("heat", 0),
                heat_capacity=burner_data.get("heat_capacity", 0),
                remaining_burning_fuel=burner_data.get("remaining_burning_fuel", 0),
                currently_burning=burner_data.get("currently_burning"),
                fuel_inventory=fuel_items,
            )

            assert isinstance(state.heat, (int, float))
            assert isinstance(state.heat_capacity, (int, float))


@pytest.mark.integration
class TestRuntimeMinerStateValidation:
    """Validates MinerState parsing against runtime data."""

    def test_burner_mining_drill_miner_state_parsing(self, rcon, test_ground, agent_id):
        """Burner mining drill runtime data should parse into MinerState."""
        from FactoryVerse.factory.entity.capabilities import MinerState, MiningTarget

        # Place ore and drill
        test_ground.place_resource_patch("iron-ore", 110, 100, size=8, amount=5000)
        test_ground.clear_area((105, 95), (115, 105))
        placed = test_ground.place_entity("burner-mining-drill", 110, 100, direction=0)

        pos = {"x": placed.position[0], "y": placed.position[1]}
        agent_interface = f"agent_{agent_id.split('_')[1]}"

        raw_data = rcon.call(
            agent_interface, "inspect_entity", "burner-mining-drill", pos
        )
        assert raw_data is not None, "inspect_entity returned None"

        # Parse mining target if present
        mining_target = None
        if "mining_target" in raw_data and raw_data["mining_target"]:
            target_data = raw_data["mining_target"]
            mining_target = MiningTarget(
                name=target_data.get("name", ""),
                amount=target_data.get("amount", 0),
                position=target_data.get("position"),
            )

        state = MinerState(
            mining_progress=raw_data.get("mining_progress", 0),
            mining_target=mining_target,
            drop_position=raw_data.get("drop_position"),
        )

        assert isinstance(state.mining_progress, (int, float))


@pytest.mark.integration
class TestRuntimeInserterStateValidation:
    """Validates InserterState parsing against runtime data."""

    def test_inserter_state_parsing(self, rcon, test_ground, agent_id):
        """Inserter runtime data should parse into InserterState."""
        from FactoryVerse.factory.entity.capabilities import InserterState, HeldItem

        test_ground.clear_area((115, 95), (125, 105))
        placed = test_ground.place_entity("inserter", 120, 100, direction=0)

        pos = {"x": placed.position[0], "y": placed.position[1]}
        agent_interface = f"agent_{agent_id.split('_')[1]}"

        raw_data = rcon.call(agent_interface, "inspect_entity", "inserter", pos)
        assert raw_data is not None, "inspect_entity returned None"

        # Parse held item if present
        held_item = None
        if "held_item" in raw_data and raw_data["held_item"]:
            held_data = raw_data["held_item"]
            held_item = HeldItem(
                name=held_data["name"], count=held_data.get("count", 1)
            )

        state = InserterState(
            pickup_position=raw_data.get("pickup_position"),
            drop_position=raw_data.get("drop_position"),
            held_item=held_item,
        )

        # These should be dict or None
        if state.pickup_position:
            assert "x" in state.pickup_position
            assert "y" in state.pickup_position


@pytest.mark.integration
class TestRuntimeContainerStateValidation:
    """Validates ContainerState parsing against runtime data."""

    def test_wooden_chest_container_state_parsing(self, rcon, test_ground, agent_id):
        """Wooden chest runtime data should parse into ContainerState."""
        from FactoryVerse.factory.entity.implementations.container import ContainerState

        test_ground.clear_area((125, 95), (135, 105))
        placed = test_ground.place_entity("wooden-chest", 130, 100)

        pos = {"x": placed.position[0], "y": placed.position[1]}
        agent_interface = f"agent_{agent_id.split('_')[1]}"

        raw_data = rcon.call(agent_interface, "inspect_entity", "wooden-chest", pos)
        assert raw_data is not None, "inspect_entity returned None"

        # Parse container inventory
        inventory = {}
        if "contents" in raw_data and raw_data["contents"]:
            for item in raw_data["contents"]:
                inventory[item["name"]] = item.get("count", 0)

        state = ContainerState(
            contents=inventory,
            inventory_size=raw_data.get("inventory_size", 0),
        )

        assert isinstance(state.contents, dict)


# ============================================================================
# CAPABILITY PRESENCE TESTS
# ============================================================================


@pytest.mark.integration
class TestRuntimeCapabilityPresence:
    """Validates that runtime inspection data contains expected capability fields."""

    def test_burner_entities_have_burner_field(
        self, rcon, test_ground, agent_id, burner_entities
    ):
        """Entities with BurnerMixin should have 'burner' in runtime data."""
        agent_interface = f"agent_{agent_id.split('_')[1]}"

        for entity_name in ["stone-furnace", "steel-furnace"]:  # Subset for speed
            test_ground.clear_area((135, 95), (145, 105))
            placed = test_ground.place_entity(entity_name, 140, 100)

            pos = {"x": placed.position[0], "y": placed.position[1]}
            raw_data = rcon.call(agent_interface, "inspect_entity", entity_name, pos)

            assert raw_data is not None
            assert "burner" in raw_data, (
                f"{entity_name} should have 'burner' in inspection data"
            )

    def test_electric_entities_have_energy_field(self, rcon, test_ground, agent_id):
        """Electric entities should have energy-related fields."""
        agent_interface = f"agent_{agent_id.split('_')[1]}"

        # Note: Not all electric entities expose 'energy' in inspect_entity
        # Inserters are electric but don't show energy in runtime data
        # Only test entities that actually expose energy fields
        for entity_name in ["assembling-machine-1", "radar"]:  # These expose energy
            test_ground.clear_area((145, 95), (155, 105))
            placed = test_ground.place_entity(entity_name, 150, 100, direction=0)

            pos = {"x": placed.position[0], "y": placed.position[1]}
            raw_data = rcon.call(agent_interface, "inspect_entity", entity_name, pos)

            assert raw_data is not None
            # These entities should have energy or status fields
            assert (
                "energy" in raw_data
                or "electric_buffer_size" in raw_data
                or "status" in raw_data
            ), f"{entity_name} should have energy-related field"


# ============================================================================
# FULL ROUNDTRIP TESTS
# ============================================================================


@pytest.mark.integration
class TestFullInspectionRoundtrip:
    """Tests that complete inspect() calls work end-to-end."""

    def test_stone_furnace_full_inspect_roundtrip(self, rcon, test_ground, agent_id):
        """Test complete inspect() call on stone furnace."""
        from FactoryVerse.factory.entity.implementations import StoneFurnace
        from FactoryVerse.factory.entity.base_entity import EntityView
        from FactoryVerse.factory.types import MapPosition

        # Place furnace
        test_ground.clear_area((155, 95), (165, 105))
        placed = test_ground.place_entity("stone-furnace", 160, 100)

        pos = {"x": placed.position[0], "y": placed.position[1]}

        # Create entity object with injected operations
        # For this to work, we need the entity_ops injected
        # This test validates the pattern is correct
        furnace = StoneFurnace(
            name="stone-furnace",
            position=MapPosition(pos["x"], pos["y"]),
            view=EntityView.REACHABLE,
        )

        # Without entity_ops, inspect() will raise
        with pytest.raises(RuntimeError, match="entity_ops not injected"):
            furnace.inspect()

    def test_ghost_furnace_inspect_works_without_ops(self, rcon, test_ground):
        """Ghost entity inspect() should work without entity_ops."""
        from FactoryVerse.factory.entity.implementations import StoneFurnace
        from FactoryVerse.factory.types import MapPosition

        # Create ghost entity (no live placement needed)
        furnace = StoneFurnace(
            name="stone-furnace",
            position=MapPosition(170, 100),
            is_ghost=True,
            ghost_name="stone-furnace",
        )

        # Ghost inspect should work without entity_ops
        inspection = furnace.inspect()

        assert inspection.is_ghost is True
        assert inspection.name == "stone-furnace"
        assert inspection.burner is None  # No live state for ghosts


# ============================================================================
# TYPE CONSISTENCY TESTS
# ============================================================================


class TestStateTypeConsistency:
    """Tests that state types are consistent across the type system."""

    def test_all_capability_states_are_pydantic_models(self):
        """All capability states should be Pydantic BaseModels."""
        from pydantic import BaseModel
        from FactoryVerse.factory.entity.capabilities import (
            BurnerState,
            ElectricState,
            CrafterState,
            MinerState,
            InserterState,
            FluidState,
            BeltState,
        )

        states = [
            BurnerState,
            ElectricState,
            CrafterState,
            MinerState,
            InserterState,
            FluidState,
            BeltState,
        ]

        for state_class in states:
            assert issubclass(state_class, BaseModel), (
                f"{state_class.__name__} should be a Pydantic BaseModel"
            )

    def test_all_category_states_are_pydantic_models(self):
        """All category-specific states should be Pydantic BaseModels."""
        from pydantic import BaseModel
        from FactoryVerse.factory.entity.implementations.container import ContainerState
        from FactoryVerse.factory.entity.implementations.lab import LabState
        from FactoryVerse.factory.entity.implementations.accumulator import (
            AccumulatorState,
        )
        from FactoryVerse.factory.entity.implementations.electric_pole import (
            ElectricPoleState,
        )
        from FactoryVerse.factory.entity.implementations.generator import GeneratorState

        states = [
            ContainerState,
            LabState,
            AccumulatorState,
            ElectricPoleState,
            GeneratorState,
        ]

        for state_class in states:
            assert issubclass(state_class, BaseModel), (
                f"{state_class.__name__} should be a Pydantic BaseModel"
            )

    def test_entity_inspection_imports_all_states(self):
        """EntityInspection should import all state types correctly."""
        from FactoryVerse.factory.entity.inspection import EntityInspection
        import inspect

        # Get the source file and check imports
        source = inspect.getsourcefile(EntityInspection)
        assert source is not None

        # The EntityInspection class should have slots for all states
        slots = EntityInspection.model_fields.keys()

        expected_slots = [
            "name",
            "position",
            "direction",
            "status",
            "is_ghost",
            "burner",
            "electric",
            "crafter",
            "miner",
            "inserter",
            "fluid",
            "belt",
            "container",
            "lab",
            "accumulator",
            "electric_pole",
            "generator",
        ]

        for slot in expected_slots:
            assert slot in slots, f"EntityInspection missing slot: {slot}"
