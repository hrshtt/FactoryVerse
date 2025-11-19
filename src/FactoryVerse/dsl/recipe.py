"""Recipe class for force-specific recipes."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from FactoryVerse.dsl.agent import Agent


class Recipe:
    """Recipe - force-specific."""
    
    def __init__(self, name: str, agent: 'Agent'):
        """
        Initialize recipe.
        
        Args:
            name: Recipe name
            agent: Agent instance (for force access)
        """
        self.name = name
        self._agent = agent
    
    def craftable(self) -> bool:
        """
        Check if recipe is craftable by agent's force.
        
        Returns:
            True if recipe is available to agent's force
        """
        # Check if recipe is in agent's recipes
        return self.name in self._agent.recipes
    
    def craft(self, count: int = 1):
        """
        Craft this recipe.
        
        Args:
            count: Number of items to craft
        
        Returns:
            Result from crafting action
        """
        return self._agent.crafting_enqueue(self.name, count)
    
    def __repr__(self):
        return f"Recipe({self.name!r})"

