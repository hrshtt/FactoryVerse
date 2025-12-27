"""Assembling machine entity implementations.

Assembling machines craft items from recipes.
Includes: AssemblingMachine (all tiers), ChemicalPlant, OilRefinery, Centrifuge, RocketSilo
"""

from typing import Dict, Any, Union, Optional, TYPE_CHECKING
from FactoryVerse.dsl.types import MapPosition, Direction
from FactoryVerse.dsl.mixins import CrafterMixin
from FactoryVerse.dsl.entity.base_entity import BaseEntity

if TYPE_CHECKING:
    from FactoryVerse.dsl.recipe.base import BaseRecipe as Recipe


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
            data: Raw inspection data from the game

        Returns:
            Formatted string for agent consumption
        """
        from FactoryVerse.dsl.entity.inspect import BaseInspectionData

        inspection = BaseInspectionData(
            entity_name=data.get("entity_name", ""),
            entity_type=data.get("entity_type", ""),
            position=MapPosition.from_dict(data["position"]),
            direction=data.get("direction", 0),
            tick=data.get("tick", 0),
            health=data.get("health"),
            max_health=data.get("max_health"),
            status=data.get("status"),
        )

        # Add recipe and progress info if available
        lines = [str(inspection)]
        if data.get("recipe"):
            lines.append(f"  Recipe: {data['recipe']}")
            if data.get("crafting_progress") is not None:
                lines.append(f"  Progress: {data['crafting_progress'] * 100:.1f}%")

        # Add inventory info if available
        inventories = data.get("inventories", {})
        if inventories.get("input"):
            input_str = ", ".join(
                [f"{name}: {count}" for name, count in inventories["input"].items()]
            )
            lines.append(f"  Input: {input_str}")
        if inventories.get("output"):
            output_str = ", ".join(
                [f"{name}: {count}" for name, count in inventories["output"].items()]
            )
            lines.append(f"  Output: {output_str}")

        return "\n".join(lines)


class AssemblingMachine(ProcessingMachine):
    """An assembling machine entity."""

    pass


class ChemicalPlant(ProcessingMachine):
    """A chemical plant entity."""

    pass


class OilRefinery(ProcessingMachine):
    """An oil refinery entity."""

    pass


class Centrifuge(ProcessingMachine):
    """A centrifuge entity."""

    pass


class RocketSilo(ProcessingMachine):
    """A rocket silo entity."""

    pass
