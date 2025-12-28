"""Assembling machine entity implementations.

Assembling machines craft items from recipes.
Includes: AssemblingMachine (all tiers), ChemicalPlant, OilRefinery, Centrifuge, RocketSilo
"""

from typing import Dict, Any, Union, Optional, List, TYPE_CHECKING
from FactoryVerse.dsl.types import MapPosition, Direction
from FactoryVerse.dsl.mixins import CrafterMixin
from FactoryVerse.dsl.entity.base_entity import BaseEntity
from FactoryVerse.dsl.entity.inspect import (
    AssemblerInspection,
    ChemicalPlantInspection,
    OilRefineryInspection,
    RocketSiloInspection,
    EnergyData,
)

if TYPE_CHECKING:
    from FactoryVerse.dsl.recipe.base import BaseRecipe as Recipe


def _parse_energy(data: Optional[Dict]) -> Optional[EnergyData]:
    """Parse energy data from Lua response."""
    if data is None:
        return None
    return EnergyData(
        current=data.get("current", 0),
        capacity=data.get("capacity", 0),
    )


class ProcessingMachine(CrafterMixin, BaseEntity):
    """Base class for entities that process recipes (assemblers, chemical plants, etc)."""

    def set_recipe(self, recipe: Union[str, "Recipe"]) -> Dict[str, Any]:
        """Set the recipe of the machine (synchronous).

        Args:
            recipe: Recipe name (string) or Recipe object with .name attribute

        Returns:
            Result dictionary with success status
        """
        # Handle string, Recipe object, or None
        if recipe is None:
            recipe_name = None
        elif isinstance(recipe, str):
            recipe_name = recipe
        elif hasattr(recipe, "name"):
            recipe_name = recipe.name
        else:
            raise ValueError(
                f"recipe must be a string, Recipe object, or None, got {type(recipe)}"
            )

        # This will be called through the view wrapper which has _entity_ops
        if self._entity_ops is None:
            raise RuntimeError(
                f"Cannot set recipe for {self.__class__.__name__}: entity_ops not injected. "
                "Entity must be wrapped in a view (Reachable) for recipe operations."
            )
        result = self._entity_ops.set_entity_recipe(
            self.name, recipe_name, self.position
        )
        return {"success": result.success if hasattr(result, "success") else True}

    def get_recipe(self) -> Optional[str]:
        """Get the current recipe of the machine.

        Note: This method is not yet fully implemented.
        To get recipe information, use inspect() and check the 'recipe' field.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__}.get_recipe() is not yet fully implemented in the DSL. "
            "To get recipe information, use inspect() and check the 'recipe' field."
        )

    def _format_inspection(self, data: Dict) -> str:
        """Format processing machine inspection data.

        Args:
            data: Raw inspection data from Lua (matches inspect_crafting_machine output)

        Returns:
            Formatted string for agent consumption
        """
        # Parse position
        pos_data = data.get("position", {})
        position = MapPosition(x=pos_data.get("x", 0), y=pos_data.get("y", 0))

        # Build AssemblerInspection from Lua data
        # NOTE: Lua sends data.input, data.output, data.modules DIRECTLY
        inspection = AssemblerInspection(
            entity_name=data.get("entity_name", ""),
            entity_type=data.get("entity_type", ""),
            position=position,
            direction=data.get("direction", 0),
            tick=data.get("tick", 0),
            health=data.get("health"),
            max_health=data.get("max_health"),
            status=data.get("status"),
            recipe=data.get("recipe"),
            crafting_progress=data.get("crafting_progress"),
            bonus_progress=data.get("bonus_progress"),
            is_crafting=data.get("is_crafting"),
            input=data.get("input"),  # Direct from Lua
            output=data.get("output"),  # Direct from Lua
            modules=data.get("modules"),  # Direct from Lua
            energy=_parse_energy(data.get("energy")),
            beacons_count=data.get("beacons_count"),
        )
        return str(inspection)


class AssemblingMachine(ProcessingMachine):
    """An assembling machine entity."""

    pass


class ChemicalPlant(ProcessingMachine):
    """A chemical plant entity."""

    def _format_inspection(self, data: Dict) -> str:
        """Format chemical plant inspection data."""
        pos_data = data.get("position", {})
        position = MapPosition(x=pos_data.get("x", 0), y=pos_data.get("y", 0))

        inspection = ChemicalPlantInspection(
            entity_name=data.get("entity_name", ""),
            entity_type=data.get("entity_type", ""),
            position=position,
            direction=data.get("direction", 0),
            tick=data.get("tick", 0),
            health=data.get("health"),
            max_health=data.get("max_health"),
            status=data.get("status"),
            recipe=data.get("recipe"),
            crafting_progress=data.get("crafting_progress"),
            bonus_progress=data.get("bonus_progress"),
            is_crafting=data.get("is_crafting"),
            input=data.get("input"),
            output=data.get("output"),
            modules=data.get("modules"),
            energy=_parse_energy(data.get("energy")),
            beacons_count=data.get("beacons_count"),
        )
        return str(inspection)


class OilRefinery(ProcessingMachine):
    """An oil refinery entity."""

    def _format_inspection(self, data: Dict) -> str:
        """Format oil refinery inspection data."""
        pos_data = data.get("position", {})
        position = MapPosition(x=pos_data.get("x", 0), y=pos_data.get("y", 0))

        inspection = OilRefineryInspection(
            entity_name=data.get("entity_name", ""),
            entity_type=data.get("entity_type", ""),
            position=position,
            direction=data.get("direction", 0),
            tick=data.get("tick", 0),
            health=data.get("health"),
            max_health=data.get("max_health"),
            status=data.get("status"),
            recipe=data.get("recipe"),
            crafting_progress=data.get("crafting_progress"),
            bonus_progress=data.get("bonus_progress"),
            is_crafting=data.get("is_crafting"),
            input=data.get("input"),
            output=data.get("output"),
            modules=data.get("modules"),
            energy=_parse_energy(data.get("energy")),
            beacons_count=data.get("beacons_count"),
        )
        return str(inspection)


class Centrifuge(ProcessingMachine):
    """A centrifuge entity."""

    pass


class RocketSilo(ProcessingMachine):
    """A rocket silo entity."""

    def _format_inspection(self, data: Dict) -> str:
        """Format rocket silo inspection data."""
        pos_data = data.get("position", {})
        position = MapPosition(x=pos_data.get("x", 0), y=pos_data.get("y", 0))

        inspection = RocketSiloInspection(
            entity_name=data.get("entity_name", ""),
            entity_type=data.get("entity_type", ""),
            position=position,
            direction=data.get("direction", 0),
            tick=data.get("tick", 0),
            health=data.get("health"),
            max_health=data.get("max_health"),
            status=data.get("status"),
            recipe=data.get("recipe"),
            crafting_progress=data.get("crafting_progress"),
            bonus_progress=data.get("bonus_progress"),
            is_crafting=data.get("is_crafting"),
            input=data.get("input"),
            output=data.get("output"),
            modules=data.get("modules"),
            energy=_parse_energy(data.get("energy")),
            beacons_count=data.get("beacons_count"),
            rocket_parts=data.get("rocket_parts"),
            rocket_silo_status=data.get("rocket_silo_status"),
        )
        return str(inspection)
