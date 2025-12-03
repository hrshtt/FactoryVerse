from src.FactoryVerse.dsl.entity.base import BaseEntity
from src.FactoryVerse.dsl.item.base import Item, PlaceableItem, ItemStack
from src.FactoryVerse.dsl.types import MapPosition, BoundingBox, Direction
from src.FactoryVerse.dsl.agent import PlayingFactory, _playing_factory
from src.FactoryVerse.dsl.prototypes import EntityPrototypes, ItemPrototypes

from typing import List, Optional


def _get_factory() -> PlayingFactory:
    """Get the current playing factory context."""
    factory = _playing_factory.get()
    if factory is None:
        raise RuntimeError(
            "No active gameplay session. "
            "Use 'with playing_factory(rcon, agent_id):' to enable operations."
        )
    return factory


def get_inventory_items() -> List[ItemStack]:
    """Get the inventory items of the entity.
    
    Args:
        entity: Entity to get inventory from
        
    Returns:
        List of ItemStack objects from the entity's inventory
    """
    factory = _get_factory()
    # Use inspect to get entity inventory - this would need to be parsed from the result
    # For now, return empty list as placeholder until proper parsing is implemented
    result = factory.inspect(attach_inventory=True, attach_entities=True)
    # TODO: Parse result JSON and extract entity inventory items
    return []


async def walk_to(position: MapPosition, strict_goal: bool = False, options: Optional[dict] = None) -> str:
    """Walk to the position.
    
    Args:
        position: Target position to walk to
        strict_goal: If true, fail if exact position unreachable
        options: Additional pathfinding options
        
    Returns:
        Action ID string
    """
    factory = _get_factory()
    return factory.walk_to(position, strict_goal=strict_goal, options=options)


def cancel_walking() -> str:
    """Cancel the current walking action.
    
    Returns:
        Command result string
    """
    factory = _get_factory()
    return factory.stop_walking()


def get_reachable_entities() -> List[BaseEntity]:
    """Get the reachable entities.
    
    Returns:
        List of BaseEntity objects within reach
    """
    factory = _get_factory()
    result = factory.get_reachable_full()
    # TODO: Parse result JSON and convert to BaseEntity instances
    return []


def craft_enqueue(recipe: str, count: int = 1) -> str:
    """Enqueue a recipe for hand-crafting.
    
    Args:
        recipe: Recipe name to craft
        count: Number of times to craft the recipe
        
    Returns:
        Action ID string
    """
    factory = _get_factory()
    return factory.craft_enqueue(recipe, count=count)


def craft_dequeue(recipe: str, count: Optional[int] = None) -> str:
    """Cancel queued crafting for a recipe.
    
    Args:
        recipe: Recipe name to cancel
        count: Number to cancel (None = all)
        
    Returns:
        Command result string
    """
    factory = _get_factory()
    return factory.craft_dequeue(recipe, count=count)


def research_enqueue(technology: str) -> str:
    """Start researching a technology.
    
    Args:
        technology: Technology name to research
        
    Returns:
        Command result string
    """
    factory = _get_factory()
    return factory.enqueue_research(technology)


def research_dequeue() -> str:
    """Cancel the currently active research.
    
    Returns:
        Command result string
    """
    factory = _get_factory()
    return factory.cancel_current_research()

def build_ghosts(ghosts: List[Ghost]) -> bool:
    """Build the ghosts."""
    return _factory.build_ghosts(ghosts)