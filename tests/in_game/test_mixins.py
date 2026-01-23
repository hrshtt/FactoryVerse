"""
In-game tests for entity type verification.

These tests verify that various entity types can be placed and
have expected properties. Uses root conftest fixtures.
"""

from FactoryVerse.game.factory.types import Direction


class TestFuelableEntities:
    """Test burner-type entities."""

    def test_stone_furnace_placement(self, clean_area):
        """Stone furnace can be placed."""
        furnace = clean_area.place_entity(
            entity_name="stone-furnace",
            x=100,
            y=100,
        )

        assert furnace.name == "stone-furnace"

    def test_burner_inserter_placement(self, clean_area):
        """Burner inserter can be placed."""
        inserter = clean_area.place_entity(
            entity_name="burner-inserter",
            x=0,
            y=0,
            direction=Direction.NORTH.value,
        )

        assert inserter.name == "burner-inserter"

    def test_burner_mining_drill_placement(self, clean_area):
        """Burner mining drill can be placed on ore."""
        clean_area.place_resource_patch(
            resource_name="coal",
            center_x=5,
            center_y=5,
            size=3,
            amount=1000,
        )

        drill = clean_area.place_entity(
            entity_name="burner-mining-drill",
            x=5,
            y=5,
            direction=Direction.SOUTH.value,
        )

        assert drill.name == "burner-mining-drill"


class TestContainerEntities:
    """Test container entities."""

    def test_iron_chest_placement(self, clean_area):
        """Iron chest can be placed."""
        chest = clean_area.place_entity(
            entity_name="iron-chest",
            x=110,
            y=110,
        )

        assert chest.name == "iron-chest"

    def test_wooden_chest_placement(self, clean_area):
        """Wooden chest can be placed."""
        chest = clean_area.place_entity(
            entity_name="wooden-chest",
            x=2,
            y=0,
        )

        assert chest.name == "wooden-chest"

    def test_steel_chest_placement(self, clean_area):
        """Steel chest can be placed."""
        chest = clean_area.place_entity(
            entity_name="steel-chest",
            x=4,
            y=0,
        )

        assert chest.name == "steel-chest"


class TestCrafterEntities:
    """Test crafting entities."""

    def test_assembler_placement(self, clean_area):
        """Assembling machine can be placed."""
        assembler = clean_area.place_entity(
            entity_name="assembling-machine-1",
            x=120,
            y=120,
        )

        assert assembler.name == "assembling-machine-1"

    def test_chemical_plant_placement(self, clean_area):
        """Chemical plant can be placed."""
        plant = clean_area.place_entity(
            entity_name="chemical-plant",
            x=10,
            y=0,
        )

        assert plant.name == "chemical-plant"

    def test_oil_refinery_placement(self, clean_area):
        """Oil refinery can be placed."""
        refinery = clean_area.place_entity(
            entity_name="oil-refinery",
            x=20,
            y=0,
        )

        assert refinery.name == "oil-refinery"


class TestDirectionalEntities:
    """Test directional entity placement."""

    def test_inserter_direction_north(self, clean_area):
        """Inserter respects NORTH direction."""
        inserter = clean_area.place_entity(
            entity_name="inserter",
            x=0,
            y=0,
            direction=Direction.NORTH.value,
        )

        assert inserter.direction == Direction.NORTH.value

    def test_inserter_direction_east(self, clean_area):
        """Inserter respects EAST direction."""
        inserter = clean_area.place_entity(
            entity_name="inserter",
            x=2,
            y=0,
            direction=Direction.EAST.value,
        )

        assert inserter.direction == Direction.EAST.value

    def test_transport_belt_direction(self, clean_area):
        """Transport belt respects direction."""
        belt = clean_area.place_entity(
            entity_name="transport-belt",
            x=5,
            y=0,
            direction=Direction.SOUTH.value,
        )

        assert belt.direction == Direction.SOUTH.value

    def test_mining_drill_direction(self, clean_area):
        """Mining drill respects direction."""
        clean_area.place_resource_patch(
            resource_name="iron-ore",
            center_x=10,
            center_y=10,
            size=3,
            amount=1000,
        )

        drill = clean_area.place_entity(
            entity_name="electric-mining-drill",
            x=10,
            y=10,
            direction=Direction.WEST.value,
        )

        assert drill.direction == Direction.WEST.value


class TestPlacedEntityMetadata:
    """Test PlacedEntity metadata from TestGround."""

    def test_placed_entity_has_name(self, clean_area):
        """PlacedEntity should have name."""
        furnace = clean_area.place_entity(
            entity_name="stone-furnace",
            x=130,
            y=130,
        )

        assert furnace.name == "stone-furnace"

    def test_placed_entity_has_position(self, clean_area):
        """PlacedEntity should have position tuple."""
        furnace = clean_area.place_entity(
            entity_name="stone-furnace",
            x=5,
            y=7,
        )

        assert furnace.position == (5, 7)

    def test_placed_entity_has_direction(self, clean_area):
        """PlacedEntity should store direction."""
        inserter = clean_area.place_entity(
            entity_name="inserter",
            x=0,
            y=0,
            direction=Direction.SOUTH.value,
        )

        assert inserter.direction == Direction.SOUTH.value
