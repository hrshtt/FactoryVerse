"""Capability Detection Tests.

Tests that entities correctly inherit and expose their capabilities via mixins.
Each test verifies that specific entity types properly implement expected mixins.

Test Strategy:
1. Create entity instances via entity factory
2. Verify isinstance checks pass for expected mixins
3. Verify capability-specific methods are available
"""


# ============================================================================
# MIXIN DETECTION TESTS
# ============================================================================


class TestBurnerCapabilityDetection:
    """Tests for BurnerMixin detection on burner-powered entities."""

    def test_burner_mining_drill_has_burner_mixin(self, rcon, test_ground, agent_id):
        """Burner mining drill should have BurnerMixin."""
        from FactoryVerse.factory.entity.capabilities import BurnerMixin
        from FactoryVerse.factory.entity.implementations import BurnerMiningDrill
        from FactoryVerse.factory.types import MapPosition, Direction

        # Create entity manually (test type system, not live entity)
        drill = BurnerMiningDrill(
            name="burner-mining-drill",
            position=MapPosition(10, 10),
            direction=Direction.NORTH,
        )

        assert isinstance(drill, BurnerMixin), (
            "BurnerMiningDrill should inherit BurnerMixin"
        )
        assert hasattr(drill, "_get_burner_state"), (
            "BurnerMixin should provide _get_burner_state method"
        )
        # add_fuel is view-filtered (only available on REACHABLE entities)
        # Check the class has it, not the instance
        assert hasattr(BurnerMixin, "add_fuel"), (
            "BurnerMixin should define add_fuel method"
        )

    def test_stone_furnace_has_burner_mixin(self, rcon, test_ground):
        """Stone furnace should have BurnerMixin."""
        from FactoryVerse.factory.entity.capabilities import BurnerMixin
        from FactoryVerse.factory.entity.implementations import StoneFurnace
        from FactoryVerse.factory.types import MapPosition

        furnace = StoneFurnace(
            name="stone-furnace",
            position=MapPosition(20, 10),
        )

        assert isinstance(furnace, BurnerMixin), (
            "StoneFurnace should inherit BurnerMixin"
        )

    def test_burner_inserter_has_burner_mixin(self, rcon, test_ground):
        """Burner inserter should have BurnerMixin."""
        from FactoryVerse.factory.entity.capabilities import BurnerMixin
        from FactoryVerse.factory.entity.implementations import BurnerInserter
        from FactoryVerse.factory.types import MapPosition, Direction

        inserter = BurnerInserter(
            name="burner-inserter",
            position=MapPosition(30, 10),
            direction=Direction.NORTH,
        )

        assert isinstance(inserter, BurnerMixin), (
            "BurnerInserter should inherit BurnerMixin"
        )


class TestElectricCapabilityDetection:
    """Tests for ElectricMixin detection on electric-powered entities."""

    def test_electric_mining_drill_has_electric_mixin(self, rcon, test_ground):
        """Electric mining drill should have ElectricMixin."""
        from FactoryVerse.factory.entity.capabilities import ElectricMixin
        from FactoryVerse.factory.entity.implementations import ElectricMiningDrill
        from FactoryVerse.factory.types import MapPosition, Direction

        drill = ElectricMiningDrill(
            name="electric-mining-drill",
            position=MapPosition(10, 20),
            direction=Direction.NORTH,
        )

        assert isinstance(drill, ElectricMixin), (
            "ElectricMiningDrill should inherit ElectricMixin"
        )
        assert hasattr(drill, "_get_electric_state"), (
            "ElectricMixin should provide _get_electric_state method"
        )

    def test_assembling_machine_has_electric_mixin(self, rcon, test_ground):
        """Assembling machine should have ElectricMixin."""
        from FactoryVerse.factory.entity.capabilities import ElectricMixin
        from FactoryVerse.factory.entity.implementations import AssemblingMachine
        from FactoryVerse.factory.types import MapPosition

        machine = AssemblingMachine(
            name="assembling-machine-1",
            position=MapPosition(20, 20),
        )

        assert isinstance(machine, ElectricMixin), (
            "AssemblingMachine should inherit ElectricMixin"
        )


class TestMinerCapabilityDetection:
    """Tests for MinerMixin detection on mining entities."""

    def test_burner_mining_drill_has_miner_mixin(self, rcon, test_ground):
        """Burner mining drill should have MinerMixin."""
        from FactoryVerse.factory.entity.capabilities import MinerMixin
        from FactoryVerse.factory.entity.implementations import BurnerMiningDrill
        from FactoryVerse.factory.types import MapPosition, Direction

        drill = BurnerMiningDrill(
            name="burner-mining-drill",
            position=MapPosition(10, 30),
            direction=Direction.NORTH,
        )

        assert isinstance(drill, MinerMixin), (
            "BurnerMiningDrill should inherit MinerMixin"
        )
        assert hasattr(drill, "_get_miner_state"), (
            "MinerMixin should provide _get_miner_state method"
        )
        assert hasattr(drill, "get_insert_target_positions"), (
            "MinerMixin should provide get_insert_target_positions method"
        )

    def test_electric_mining_drill_has_miner_mixin(self, rcon, test_ground):
        """Electric mining drill should have MinerMixin."""
        from FactoryVerse.factory.entity.capabilities import MinerMixin
        from FactoryVerse.factory.entity.implementations import ElectricMiningDrill
        from FactoryVerse.factory.types import MapPosition, Direction

        drill = ElectricMiningDrill(
            name="electric-mining-drill",
            position=MapPosition(20, 30),
            direction=Direction.NORTH,
        )

        assert isinstance(drill, MinerMixin), (
            "ElectricMiningDrill should inherit MinerMixin"
        )


class TestCrafterCapabilityDetection:
    """Tests for CrafterMixin detection on crafting entities."""

    def test_stone_furnace_has_crafter_mixin(self, rcon, test_ground):
        """Stone furnace should have CrafterMixin."""
        from FactoryVerse.factory.entity.capabilities import CrafterMixin
        from FactoryVerse.factory.entity.implementations import StoneFurnace
        from FactoryVerse.factory.types import MapPosition

        furnace = StoneFurnace(
            name="stone-furnace",
            position=MapPosition(10, 40),
        )

        assert isinstance(furnace, CrafterMixin), (
            "StoneFurnace should inherit CrafterMixin"
        )
        assert hasattr(furnace, "_get_crafter_state"), (
            "CrafterMixin should provide _get_crafter_state method"
        )

    def test_assembling_machine_has_crafter_mixin(self, rcon, test_ground):
        """Assembling machine should have CrafterMixin."""
        from FactoryVerse.factory.entity.capabilities import CrafterMixin
        from FactoryVerse.factory.entity.implementations import AssemblingMachine
        from FactoryVerse.factory.types import MapPosition

        machine = AssemblingMachine(
            name="assembling-machine-1",
            position=MapPosition(20, 40),
        )

        assert isinstance(machine, CrafterMixin), (
            "AssemblingMachine should inherit CrafterMixin"
        )


class TestInserterCapabilityDetection:
    """Tests for InserterMixin detection on inserter entities."""

    def test_inserter_has_inserter_mixin(self, rcon, test_ground):
        """Standard inserter should have InserterMixin."""
        from FactoryVerse.factory.entity.capabilities import InserterMixin
        from FactoryVerse.factory.entity.implementations import Inserter
        from FactoryVerse.factory.types import MapPosition, Direction

        inserter = Inserter(
            name="inserter",
            position=MapPosition(10, 50),
            direction=Direction.NORTH,
        )

        assert isinstance(inserter, InserterMixin), (
            "Inserter should inherit InserterMixin"
        )
        assert hasattr(inserter, "_get_inserter_state"), (
            "InserterMixin should provide _get_inserter_state method"
        )

    def test_fast_inserter_has_inserter_mixin(self, rcon, test_ground):
        """Fast inserter should have InserterMixin."""
        from FactoryVerse.factory.entity.capabilities import InserterMixin
        from FactoryVerse.factory.entity.implementations import FastInserter
        from FactoryVerse.factory.types import MapPosition, Direction

        inserter = FastInserter(
            name="fast-inserter",
            position=MapPosition(20, 50),
            direction=Direction.NORTH,
        )

        assert isinstance(inserter, InserterMixin), (
            "FastInserter should inherit InserterMixin"
        )

    def test_burner_inserter_has_both_burner_and_inserter_mixin(
        self, rcon, test_ground
    ):
        """Burner inserter should have both BurnerMixin and InserterMixin."""
        from FactoryVerse.factory.entity.capabilities import BurnerMixin, InserterMixin
        from FactoryVerse.factory.entity.implementations import BurnerInserter
        from FactoryVerse.factory.types import MapPosition, Direction

        inserter = BurnerInserter(
            name="burner-inserter",
            position=MapPosition(30, 50),
            direction=Direction.NORTH,
        )

        assert isinstance(inserter, InserterMixin), (
            "BurnerInserter should inherit InserterMixin"
        )
        assert isinstance(inserter, BurnerMixin), (
            "BurnerInserter should also inherit BurnerMixin"
        )


class TestBeltCapabilityDetection:
    """Tests for BeltMixin detection on transport belt entities."""

    def test_transport_belt_has_belt_mixin(self, rcon, test_ground):
        """Transport belt should have BeltMixin."""
        from FactoryVerse.factory.entity.capabilities import BeltMixin
        from FactoryVerse.factory.entity.implementations import TransportBelt
        from FactoryVerse.factory.types import MapPosition, Direction

        belt = TransportBelt(
            name="transport-belt",
            position=MapPosition(10, 60),
            direction=Direction.NORTH,
        )

        assert isinstance(belt, BeltMixin), "TransportBelt should inherit BeltMixin"
        assert hasattr(belt, "_get_belt_state"), (
            "BeltMixin should provide _get_belt_state method"
        )


class TestContainerDetection:
    """Tests for Container implementation detection."""

    def test_wooden_chest_is_container(self, rcon, test_ground):
        """Wooden chest should be a Container."""
        from FactoryVerse.factory.entity.implementations import WoodenChest, Container
        from FactoryVerse.factory.types import MapPosition

        chest = WoodenChest(
            name="wooden-chest",
            position=MapPosition(10, 70),
        )

        assert isinstance(chest, Container), "WoodenChest should inherit Container"
        assert hasattr(chest, "_get_container_state"), (
            "Container should provide _get_container_state method"
        )

    def test_iron_chest_is_container(self, rcon, test_ground):
        """Iron chest should be a Container."""
        from FactoryVerse.factory.entity.implementations import IronChest, Container
        from FactoryVerse.factory.types import MapPosition

        chest = IronChest(
            name="iron-chest",
            position=MapPosition(20, 70),
        )

        assert isinstance(chest, Container), "IronChest should inherit Container"


# ============================================================================
# COMPOSITE CAPABILITY TESTS
# ============================================================================


class TestCompositeCapabilities:
    """Tests for entities with multiple capabilities."""

    def test_burner_mining_drill_composite_capabilities(self, rcon, test_ground):
        """Burner mining drill should have both BurnerMixin and MinerMixin."""
        from FactoryVerse.factory.entity.capabilities import BurnerMixin, MinerMixin
        from FactoryVerse.factory.entity.implementations import BurnerMiningDrill
        from FactoryVerse.factory.types import MapPosition, Direction

        drill = BurnerMiningDrill(
            name="burner-mining-drill",
            position=MapPosition(10, 80),
            direction=Direction.NORTH,
        )

        assert isinstance(drill, BurnerMixin), "Should have BurnerMixin"
        assert isinstance(drill, MinerMixin), "Should have MinerMixin"

    def test_electric_mining_drill_composite_capabilities(self, rcon, test_ground):
        """Electric mining drill should have both ElectricMixin and MinerMixin."""
        from FactoryVerse.factory.entity.capabilities import ElectricMixin, MinerMixin
        from FactoryVerse.factory.entity.implementations import ElectricMiningDrill
        from FactoryVerse.factory.types import MapPosition, Direction

        drill = ElectricMiningDrill(
            name="electric-mining-drill",
            position=MapPosition(20, 80),
            direction=Direction.NORTH,
        )

        assert isinstance(drill, ElectricMixin), "Should have ElectricMixin"
        assert isinstance(drill, MinerMixin), "Should have MinerMixin"

    def test_electric_furnace_composite_capabilities(self, rcon, test_ground):
        """Electric furnace should have ElectricMixin and CrafterMixin."""
        from FactoryVerse.factory.entity.capabilities import ElectricMixin, CrafterMixin
        from FactoryVerse.factory.entity.implementations import ElectricFurnace
        from FactoryVerse.factory.types import MapPosition

        furnace = ElectricFurnace(
            name="electric-furnace",
            position=MapPosition(30, 80),
        )

        assert isinstance(furnace, ElectricMixin), "Should have ElectricMixin"
        assert isinstance(furnace, CrafterMixin), "Should have CrafterMixin"

    def test_stone_furnace_composite_capabilities(self, rcon, test_ground):
        """Stone furnace should have BurnerMixin and CrafterMixin."""
        from FactoryVerse.factory.entity.capabilities import BurnerMixin, CrafterMixin
        from FactoryVerse.factory.entity.implementations import StoneFurnace
        from FactoryVerse.factory.types import MapPosition

        furnace = StoneFurnace(
            name="stone-furnace",
            position=MapPosition(40, 80),
        )

        assert isinstance(furnace, BurnerMixin), "Should have BurnerMixin"
        assert isinstance(furnace, CrafterMixin), "Should have CrafterMixin"


# ============================================================================
# MRO (METHOD RESOLUTION ORDER) TESTS
# ============================================================================


class TestMROCompliance:
    """Tests that entity class MRO is correct for mixin resolution."""

    def test_burner_mining_drill_mro_correctness(self, rcon, test_ground):
        """BurnerMiningDrill MRO should have mixins before BaseEntity."""
        from FactoryVerse.factory.entity.implementations import BurnerMiningDrill

        mro = BurnerMiningDrill.__mro__
        mro_names = [cls.__name__ for cls in mro]

        # Mixins should come before BaseEntity
        assert mro_names.index("MinerMixin") < mro_names.index("BaseEntity")
        assert mro_names.index("BurnerMixin") < mro_names.index("BaseEntity")

    def test_inserter_mro_correctness(self, rcon, test_ground):
        """Inserter MRO should have InserterMixin before BaseEntity."""
        from FactoryVerse.factory.entity.implementations import Inserter

        mro = Inserter.__mro__
        mro_names = [cls.__name__ for cls in mro]

        # Mixins should come before BaseEntity
        assert mro_names.index("InserterMixin") < mro_names.index("BaseEntity")
        assert mro_names.index("ElectricMixin") < mro_names.index("BaseEntity")


# ============================================================================
# NEGATIVE TESTS (Entities Should NOT Have Certain Capabilities)
# ============================================================================


class TestCapabilityExclusion:
    """Tests that entities don't have inappropriate capabilities."""

    def test_container_does_not_have_burner_mixin(self, rcon, test_ground):
        """Containers should NOT have BurnerMixin."""
        from FactoryVerse.factory.entity.capabilities import BurnerMixin
        from FactoryVerse.factory.entity.implementations import WoodenChest
        from FactoryVerse.factory.types import MapPosition

        chest = WoodenChest(
            name="wooden-chest",
            position=MapPosition(10, 90),
        )

        assert not isinstance(chest, BurnerMixin), (
            "WoodenChest should NOT inherit BurnerMixin"
        )

    def test_electric_entities_do_not_have_burner_mixin(self, rcon, test_ground):
        """Electric entities should NOT have BurnerMixin."""
        from FactoryVerse.factory.entity.capabilities import BurnerMixin
        from FactoryVerse.factory.entity.implementations import (
            ElectricMiningDrill,
            Inserter,
        )
        from FactoryVerse.factory.types import MapPosition, Direction

        drill = ElectricMiningDrill(
            name="electric-mining-drill",
            position=MapPosition(20, 90),
            direction=Direction.NORTH,
        )

        inserter = Inserter(
            name="inserter",
            position=MapPosition(30, 90),
            direction=Direction.NORTH,
        )

        assert not isinstance(drill, BurnerMixin), (
            "ElectricMiningDrill should NOT inherit BurnerMixin"
        )
        assert not isinstance(inserter, BurnerMixin), (
            "Inserter should NOT inherit BurnerMixin"
        )

    def test_belts_do_not_have_miner_mixin(self, rcon, test_ground):
        """Belt entities should NOT have MinerMixin."""
        from FactoryVerse.factory.entity.capabilities import MinerMixin
        from FactoryVerse.factory.entity.implementations import TransportBelt
        from FactoryVerse.factory.types import MapPosition, Direction

        belt = TransportBelt(
            name="transport-belt",
            position=MapPosition(40, 90),
            direction=Direction.NORTH,
        )

        assert not isinstance(belt, MinerMixin), (
            "TransportBelt should NOT inherit MinerMixin"
        )
