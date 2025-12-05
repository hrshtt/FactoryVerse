from src.FactoryVerse.dsl.entity.base import BaseEntity
from src.FactoryVerse.dsl.item.base import ItemStack, GhostEntity
from src.FactoryVerse.dsl.types import MapPosition, BoundingBox, Position, Direction
from src.FactoryVerse.dsl.agent import PlayingFactory, _playing_factory, WalkingAction, MiningAction, CraftingAction, ResearchAction

from typing import List, Optional, Dict, Any
import json


def _get_factory() -> PlayingFactory:
    """Get the current playing factory context."""
    factory = _playing_factory.get()
    if factory is None:
        raise RuntimeError(
            "No active gameplay session. "
            "Use 'with playing_factorio(rcon, agent_id):' to enable operations."
        )
    return factory


# Top-level action accessors - available in DSL context
class _WalkingAccessor:
    """Top-level walking action accessor."""
    
    async def to(self, position: MapPosition, strict_goal: bool = False, options: Optional[dict] = None, timeout: Optional[int] = None):
        """Walk to a position (async/await)."""
        return await _get_factory().walking.to(position, strict_goal, options, timeout)
    
    def cancel(self):
        """Cancel current walking action."""
        return _get_factory().walking.cancel()


class _MiningAccessor:
    """Top-level mining action accessor."""
    
    async def mine(self, resource_name: str, max_count: Optional[int] = None, timeout: Optional[int] = None):
        """Mine a resource (async/await)."""
        return await _get_factory().mining.mine(resource_name, max_count, timeout)
    
    def cancel(self):
        """Cancel current mining action."""
        return _get_factory().mining.cancel()


class _CraftingAccessor:
    """Top-level crafting action accessor."""
    
    async def craft(self, recipe: str, count: int = 1, timeout: Optional[int] = None):
        """Craft a recipe (async/await)."""
        return await _get_factory().crafting.craft(recipe, count, timeout)
    
    def enqueue(self, recipe: str, count: int = 1):
        """Enqueue a recipe for crafting."""
        return _get_factory().crafting.enqueue(recipe, count)
    
    def dequeue(self, recipe: str, count: Optional[int] = None):
        """Cancel queued crafting."""
        return _get_factory().crafting.dequeue(recipe, count)
    
    def status(self):
        """Get current crafting status."""
        return _get_factory().crafting.status()


class _ResearchAccessor:
    """Top-level research action accessor."""
    
    def enqueue(self, technology: str):
        """Start researching a technology."""
        return _get_factory().research.enqueue(technology)
    
    def dequeue(self):
        """Cancel current research."""
        return _get_factory().research.dequeue()
    
    def status(self):
        """Get current research status."""
        return _get_factory().research.status()


# Top-level action instances - use these in DSL context
walking = _WalkingAccessor()
mining = _MiningAccessor()
crafting = _CraftingAccessor()
research = _ResearchAccessor()


def get_inventory_items() -> List[ItemStack]:
    """Get the inventory items of the agent.
    
    Returns:
        List of ItemStack objects from the agent's inventory
    """
    factory = _get_factory()
    # Use the inventory property which already handles parsing
    return factory.inventory


def get_reachable_entities() -> List[BaseEntity]:
    """Get the reachable entities.
    
    Returns:
        List of BaseEntity objects within reach
    """
    factory = _get_factory()
    result = factory.get_reachable_full()
    data = json.loads(result)
    
    entities = []
    entities_data = data.get("entities", [])
    
    for entity_data in entities_data:
        # Parse entity data and create BaseEntity
        name = entity_data.get("name", "")
        position_data = entity_data.get("position", {})
        position = MapPosition(x=position_data.get("x", 0), y=position_data.get("y", 0))
        
        # Parse bounding box if available
        bbox_data = entity_data.get("bounding_box")
        if bbox_data:
            left_top = Position(x=bbox_data["left_top"]["x"], y=bbox_data["left_top"]["y"])
            right_bottom = Position(x=bbox_data["right_bottom"]["x"], y=bbox_data["right_bottom"]["y"])
            bounding_box = BoundingBox(left_top=left_top, right_bottom=right_bottom)
        else:
            # Create minimal bounding box
            
            bounding_box = BoundingBox(
                left_top=Position(x=position.x, y=position.y),
                right_bottom=Position(x=position.x + 1, y=position.y + 1)
            )
        
        # Parse direction if available
        direction = None
        if "direction" in entity_data:
            try:
                direction = Direction(entity_data["direction"])
            except (ValueError, KeyError):
                pass
        
        entity = BaseEntity(
            name=name,
            position=position,
            bounding_box=bounding_box,
            direction=direction
        )
        entities.append(entity)
    
    return entities

"""
with playing_factorio(rcon, 'agent_1'):
    # Async/await actions
    await walking.to(MapPosition(x=10, y=20))
    await mining.mine('iron-ore', max_count=50)
    await crafting.craft('iron-plate', count=10)
    
    # Sync actions
    walking.cancel()
    mining.cancel()
    crafting.enqueue('iron-plate', count=10)
    crafting.dequeue('iron-plate')
    crafting.status()
    
    research.enqueue('automation')
    research.dequeue()
    research.status()
    
    # Top-level utilities
    get_inventory_items()
    get_reachable_entities()
"""