"""Mixins for entity functionality."""

from typing import Optional
from FactoryVerse.dsl.items import ItemStack
from FactoryVerse.dsl.recipe import Recipe


class InventoryMixin:
    """Mixin for entities with inventories."""
    
    def add_item(
        self,
        item: ItemStack,
        inventory_type: str = "input"
    ):
        """
        Add item to inventory.
        
        Args:
            item: ItemStack to add
            inventory_type: Inventory type string (e.g., "chest", "fuel", "input", "output")
        
        Returns:
            Result from action
        """
        if not self._helper or self._agent_id is None:
            raise RuntimeError("Entity not initialized with helper and agent_id")
        
        return self._helper.run_async(
            "action",
            "entity_inventory_set_item",
            {
                "agent_id": self._agent_id,
                "position_x": self.position['x'],
                "position_y": self.position['y'],
                "entity_name": self.name,
                "item": item.name,
                "count": item.count,
                "inventory_type": inventory_type,
            }
        )
    
    def get_item(
        self,
        item_name: str,
        count: Optional[int] = None,
        inventory_type: str = "input"
    ) -> ItemStack:
        """
        Get item from inventory.
        
        Args:
            item_name: Name of item to get
            count: Count to get (None for all available)
            inventory_type: Inventory type string
        
        Returns:
            ItemStack with retrieved items
        """
        if not self._helper or self._agent_id is None:
            raise RuntimeError("Entity not initialized with helper and agent_id")
        
        result = self._helper.run(
            "action",
            "entity_inventory_get_item",
            {
                "agent_id": self._agent_id,
                "position_x": self.position['x'],
                "position_y": self.position['y'],
                "entity_name": self.name,
                "item": item_name,
                "count": count,
                "inventory_type": inventory_type,
            }
        )
        
        from FactoryVerse.dsl.items import Ingredient, ingredient_factory
        ingredient = ingredient_factory(item_name)
        return ItemStack(ingredient, result.get('count', 0))


class PlaceableMixin:
    """Mixin for items that can be placed."""
    
    def place(self, position: Dict[str, float], agent: 'Agent'):
        """
        Place this entity.
        
        Args:
            position: Position to place at
            agent: Agent instance to use for placement
        
        Returns:
            Created Entity object
        """
        return agent.place(self.name, position)


class RecipeMixin:
    """Mixin for entities that can have recipes."""
    
    def set_recipe(self, recipe: Recipe):
        """
        Set recipe for this entity.
        
        Args:
            recipe: Recipe object to set
        
        Returns:
            Result from action
        """
        if not self._helper or self._agent_id is None:
            raise RuntimeError("Entity not initialized with helper and agent_id")
        
        return self._helper.run_async(
            "action",
            "entity_set_recipe",
            {
                "agent_id": self._agent_id,
                "position_x": self.position['x'],
                "position_y": self.position['y'],
                "entity_name": self.name,
                "recipe": recipe.name,
            }
        )

