"""Resource capability protocols for structural subtyping.

This module defines Protocol-based interfaces for resource capabilities, enabling
clear separation between resource categories (Reachable vs RemoteView) while
maintaining the same underlying resource classes.

Resource Categories:
- ReachableResource: Full interface - can mine resources
- RemoteViewResource: Read-only interface - can only inspect, cannot mine
"""

from typing import Protocol, runtime_checkable, List, Optional, TYPE_CHECKING

from FactoryVerse.dsl.types import MapPosition

if TYPE_CHECKING:
    from FactoryVerse.dsl.item.base import ItemStack


# ============================================
# MUTATION CAPABILITIES
# ============================================

@runtime_checkable
class Mineable(Protocol):
    """Resource that can be mined.
    
    Available ONLY on: ReachableResource
    
    Mining extracts resources from the world and adds them to inventory.
    """
    
    async def mine(self, max_count: Optional[int] = None, timeout: Optional[int] = None) -> List["ItemStack"]:
        """Mine the resource.
        
        Args:
            max_count: Maximum number of items to mine
            timeout: Timeout in seconds
        
        Returns:
            List of ItemStack objects mined
        """
        ...


# ============================================
# RESOURCE CATEGORIES
# ============================================

@runtime_checkable
class ReachableResource(Mineable, Protocol):
    """Full resource interface - resources within mining distance.
    
    Source: reachable_resources.get_resource() / reachable_resources.get_resources()
    
    Capabilities:
    - Spatial properties (position, amount)
    - Mine (extract resource from world)
    
    Examples:
    - IronOre: Can be mined
    - CopperOre: Can be mined
    - TreeEntity: Can be mined (chopped)
    - RockEntity: Can be mined
    - ResourceOrePatch: Consolidated ore tiles, can mine first tile
    
    Use Case:
    - Extract resources within mining distance
    - Automated resource gathering
    """
    
    name: str
    """Resource name (e.g., 'iron-ore', 'copper-ore', 'tree')."""
    
    position: MapPosition
    """Resource position on the map."""
    
    amount: Optional[int]
    """Amount of resource available (None for trees/rocks)."""


@runtime_checkable
class RemoteViewResource(Protocol):
    """Read-only resource interface - resources from map database.
    
    Source: map_db.get_resources() (not yet implemented)
    
    Capabilities:
    - Spatial properties (position, amount)
    - Does NOT have mine() method
    
    Use Case:
    - Spatial planning and resource surveying
    - Identifying resource locations across entire map
    - Planning mining operations
    
    To mine a RemoteViewResource:
    1. Navigate to it (walk to position)
    2. Use reachable_resources.get_resource() to get ReachableResource interface
    3. Now you can mine()
    
    Example:
        >>> # Query all iron ore patches on map
        >>> patches = map_db.get_resources('''
        ...     SELECT * FROM resource_patch
        ...     WHERE resource_name = 'iron-ore'
        ... ''')
        >>> 
        >>> # Find largest patch
        >>> largest = max(patches, key=lambda p: p.total_amount)
        >>> 
        >>> # Navigate and mine
        >>> await walking.to(largest.centroid)
        >>> reachable_patch = reachable_resources.get_resource('iron-ore')
        >>> await reachable_patch.mine(max_count=50)
    """
    
    name: str
    """Resource name (e.g., 'iron-ore', 'copper-ore')."""
    
    position: MapPosition
    """Resource position on the map."""
    
    amount: Optional[int]
    """Amount of resource available."""


__all__ = [
    'Mineable',
    'ReachableResource',
    'RemoteViewResource',
]
