"""Crafter capability - state and mixin for crafting machines.

Co-locates CrafterState (Pydantic model) and CrafterMixin for entities
that craft items like assemblers, furnaces, chemical plants.
"""

from typing import Optional, List, Dict, Any, Union, TYPE_CHECKING
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from FactoryVerse.factory.item.base import ItemStack
    from FactoryVerse.agent.actions.entity_operations import EntityOperationsAction


class CrafterState(BaseModel):
    """State for crafting machines.

    Source: runtime_inspection.jsonl crafting_progress, recipe, inventories
    """

    recipe: Optional[str] = None
    crafting_progress: float = 0
    crafting_speed: float = 1.0
    is_crafting: bool = False
    crafter_input: Dict[str, int] = Field(default_factory=dict)
    crafter_output: Dict[str, int] = Field(default_factory=dict)
    crafter_modules: Dict[str, int] = Field(default_factory=dict)


class CrafterMixin:
    """Mixin for crafting machines (assemblers, furnaces, chemical plants).

    Provides:
    - _get_crafter_state() for inspection
    - add_ingredients() for adding input materials
    - take_products() for taking output products

    Requires entity to have:
    - is_ghost: bool
    - _entity_ops: EntityOperationsAction (injected)
    - name: str
    - position: Position
    """

    is_ghost: bool
    _entity_ops: "EntityOperationsAction"
    name: str

    def _get_crafter_state(self, inspection_data: dict) -> CrafterState:
        """Get crafter state from inspection data.

        Args:
            inspection_data: Raw inspection data from Lua

        Returns:
            CrafterState populated from inspection data
        """
        if self.is_ghost:
            return CrafterState()  # Ghosts have no crafting data

        # Get inventories
        inventories = inspection_data.get("inventories", {})

        # Parse inventory contents
        def parse_inventory(inv_data: dict) -> Dict[str, int]:
            if not inv_data:
                return {}
            contents = inv_data.get("contents", [])
            result = {}
            for item in contents:
                result[item["name"]] = item.get("count", 0)
            return result

        return CrafterState(
            recipe=inspection_data.get("current_recipe")
            or inspection_data.get("recipe"),
            crafting_progress=inspection_data.get("crafting_progress", 0),
            crafting_speed=inspection_data.get("crafting_speed", 1.0),
            is_crafting=inspection_data.get("crafting_progress", 0) > 0,
            crafter_input=parse_inventory(inventories.get("crafter_input", {})),
            crafter_output=parse_inventory(inventories.get("crafter_output", {})),
            crafter_modules=parse_inventory(inventories.get("crafter_modules", {})),
        )

    def add_ingredients(self, items: List["ItemStack"]) -> List:
        """Add ingredients to the entity's input buffer.

        **For Agents**: Use this to supply materials to crafting machines.

        Args:
            items: List of ItemStack containing ingredients

        Returns:
            List of results from ingredient addition
        """
        result = self._entity_ops.put_inventory_item(
            self.name,
            "input",
            items,
            self.position,  # type: ignore
        )
        return result if isinstance(result, list) else [result]

    def take_products(
        self, items: Optional[List["ItemStack"]] = None
    ) -> List["ItemStack"]:
        """Take products from the entity's output buffer.

        **For Agents**: Use this to collect finished products from crafting machines.

        Args:
            items: Optional list of ItemStack to take. If None, takes everything.

        Returns:
            List of ItemStack taken from output
        """
        from FactoryVerse.factory.item.create_item import create_item_stack

        if items is None:
            # Inspect to get output contents
            data = self._entity_ops.inspect_entity(self.name, self.position)  # type: ignore
            output_inv = data.get("inventories", {}).get("crafter_output", {})
            contents = output_inv.get("contents", [])
            items = [
                create_item_stack(item["name"], item["count"], placement=self._place_ops)
                for item in contents
            ]

        results = []
        for item in items:
            response = self._entity_ops.take_inventory_item(
                self.name,
                "output",
                item.name,
                item.count,
                self.position,  # type: ignore
            )
            results.extend(response.to_item_stacks(self._place_ops))
        return results


class SetRecipeMixin:
    """Mixin for entities that can have their recipe set.

    Used by assemblers, chemical plants, oil refineries.
    Not used by furnaces (auto-detect recipe from input).
    """

    _entity_ops: "EntityOperationsAction"
    name: str

    def set_recipe(self, recipe: Union[str, Any]) -> Dict[str, Any]:
        """Set the crafting recipe.

        Args:
            recipe: Recipe name (string) or Recipe object with .name attribute

        Returns:
            Result dictionary with success status
        """
        # Handle string or Recipe object
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

        result = self._entity_ops.set_entity_recipe(
            self.name,
            recipe_name,
            self.position,  # type: ignore
        )
        return {"success": result.success if hasattr(result, "success") else True}
