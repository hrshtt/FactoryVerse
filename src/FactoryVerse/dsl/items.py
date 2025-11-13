"""Item and ingredient classes."""

from typing import Dict, Optional
from abc import ABC


class Ingredient(ABC):
    """Base ingredient type."""
    
    def __init__(self, name: str):
        """
        Initialize ingredient.
        
        Args:
            name: Item name
        """
        self.name = name
    
    def __repr__(self):
        return f"{self.__class__.__name__}({self.name!r})"
    
    def __eq__(self, other):
        if not isinstance(other, Ingredient):
            return False
        return self.name == other.name
    
    def __hash__(self):
        return hash(self.name)


class OreIngredient(Ingredient):
    """Ore ingredient."""
    pass


class FuelIngredient(Ingredient):
    """Fuel ingredient."""
    pass


class PlateIngredient(Ingredient):
    """Plate ingredient."""
    pass


def ingredient_factory(name: str) -> Ingredient:
    """
    Factory method for ingredients.
    
    Args:
        name: Item name
    
    Returns:
        Appropriate Ingredient subclass
    """
    if name in ("iron-ore", "copper-ore", "stone", "coal"):
        return OreIngredient(name)
    elif name in ("coal", "wood", "solid-fuel"):
        return FuelIngredient(name)
    elif name.endswith("-plate"):
        return PlateIngredient(name)
    return Ingredient(name)


class ItemStack:
    """Item stack - can be in inventory or placed."""
    
    def __init__(self, ingredient: Ingredient, count: int = 1):
        """
        Initialize item stack.
        
        Args:
            ingredient: Ingredient object
            count: Stack count
        """
        self.ingredient = ingredient
        self.count = count
        self.name = ingredient.name
    
    def __repr__(self):
        return f"ItemStack({self.name}, {self.count})"
    
    def place(self, position: Dict[str, float], agent: 'Agent'):
        """
        Place this item as an entity.
        
        Args:
            position: Position to place at
            agent: Agent instance to use for placement
        
        Returns:
            Created Entity object
        """
        return agent.place(self.name, position)

