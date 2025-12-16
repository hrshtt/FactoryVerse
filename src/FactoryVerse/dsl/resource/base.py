from __future__ import annotations
from typing import List, Optional, Dict, Any, Union, TYPE_CHECKING
from src.FactoryVerse.dsl.types import MapPosition
import asyncio

if TYPE_CHECKING:
    from src.FactoryVerse.dsl.agent import PlayingFactory

# Import _playing_factory safely
from src.FactoryVerse.dsl.agent import _playing_factory


def _get_factory() -> "PlayingFactory":
    """Get the current playing factory context."""
    factory = _playing_factory.get()
    if factory is None:
        raise RuntimeError(
            "No active gameplay session. "
            "Use 'with playing_factorio():' to enable operations."
        )
    return factory


class ResourceOrePatch:
    """Resource ore patch representing multiple resource tiles consolidated.
    
    Similar to ItemStack but for resources. Consolidates multiple resource
    entries with the same name into a single patch for cleaner agent interface.
    """
    
    def __init__(self, name: str, resource_data_list: List[Dict[str, Any]]):
        """Initialize ResourceOrePatch from a list of resource data dicts.
        
        Args:
            name: Resource name (e.g., "copper-ore", "iron-ore")
            resource_data_list: List of resource data dicts from get_reachable
        """
        self.name = name
        self._resource_data_list = resource_data_list
        self._resource_instances: Optional[List["BaseResource"]] = None
    
    @property
    def total(self) -> int:
        """Get total amount across all resource tiles in the patch."""
        total = 0
        for data in self._resource_data_list:
            if "amount" in data:
                total += data.get("amount", 0)
        return total
    
    @property
    def count(self) -> int:
        """Get number of resource tiles in this patch."""
        return len(self._resource_data_list)
    
    @property
    def resource_type(self) -> str:
        """Get the resource type (resource, tree, simple-entity)."""
        if self._resource_data_list:
            return self._resource_data_list[0].get("type", "resource")
        return "resource"
    
    def get_resource_tile(self, position: MapPosition) -> Optional["BaseResource"]:
        """Get a specific resource tile by position.
        
        Args:
            position: MapPosition to find resource at
            
        Returns:
            BaseResource instance if found, None otherwise
        """
        for data in self._resource_data_list:
            pos_data = data.get("position", {})
            if pos_data.get("x") == position.x and pos_data.get("y") == position.y:
                return _create_resource_from_data(data)
        return None
    
    def __getitem__(self, index: int) -> "BaseResource":
        """Get a resource tile by index.
        
        Args:
            index: Index of the resource tile (must be < count)
            
        Returns:
            BaseResource instance for that tile
        """
        if index < 0 or index >= len(self._resource_data_list):
            raise IndexError(f"Index {index} out of range for patch with {len(self._resource_data_list)} tiles")
        
        data = self._resource_data_list[index]
        return _create_resource_from_data(data)
    
    async def mine(self, max_count: Optional[int] = None, timeout: Optional[int] = None) -> List:
        """Mine a resource tile from this patch (async/await).
        
        Mines the first tile in the patch without requiring position.
        
        Args:
            max_count: Max items to mine (None = deplete resource)
            timeout: Optional timeout in seconds
            
        Returns:
            List of ItemStack objects obtained from mining
        """
        # Mine the first tile in the patch
        if not self._resource_data_list:
            raise RuntimeError("Cannot mine from empty patch")
        
        first_tile = self[0]
        return await first_tile.mine(max_count, timeout)
    
    def __repr__(self) -> str:
        """Clean summary of the resource patch."""
        tiles_info = []
        for i, data in enumerate(self._resource_data_list):
            pos = data.get("position", {})
            amount = data.get("amount", "N/A")
            tiles_info.append(f"  [{i}] pos=({pos.get('x', 0)}, {pos.get('y', 0)}) amount={amount}")
        
        tiles_str = "\n".join(tiles_info) if tiles_info else "  (no tiles)"
        return f"""ResourceOrePatch(name='{self.name}', type='{self.resource_type}', total={self.total}, tiles={self.count})
{tiles_str}"""


class BaseResource:
    """Base class for all mineable resources.
    
    Resources can be mined directly using the async mine() method.
    """
    
    def __init__(self, name: str, position: MapPosition, resource_type: str, data: Dict[str, Any]):
        """Initialize BaseResource.
        
        Args:
            name: Resource name (e.g., "copper-ore", "tree", "big-rock")
            position: MapPosition of the resource
            resource_type: Factorio entity type ("resource", "tree", "simple-entity")
            data: Full resource data dict from get_reachable
        """
        self.name = name
        self.position = position
        self.resource_type = resource_type
        self._data = data
        self._amount = data.get("amount")
        self._products = data.get("products", [])
    
    @property
    def amount(self) -> Optional[int]:
        """Get resource amount (only for ore patches, None for trees/rocks)."""
        return self._amount
    
    @property
    def products(self) -> List[Dict[str, Any]]:
        """Get mineable products from this resource."""
        return self._products
    
    @property
    def _factory(self) -> "PlayingFactory":
        """Get the current playing factory context."""
        return _get_factory()
    
    async def mine(self, max_count: Optional[int] = None, timeout: Optional[int] = None) -> List:
        """Mine this resource (async/await).
        
        Args:
            max_count: Max items to mine (None = deplete resource)
            timeout: Optional timeout in seconds
            
        Returns:
            List of ItemStack objects obtained from mining
        """
        from src.FactoryVerse.dsl.item.base import ItemStack
        
        # Use the factory's mine_resource method with this resource's position
        # We need to find the resource by name and position
        response = self._factory.mine_resource(self.name, max_count)
        result_payload = await self._factory._await_action(response, timeout=timeout)
        
        # Parse result for items
        items = []
        result_data = result_payload.get("result", {})
        if "actual_products" in result_data:
            for name, count in result_data["actual_products"].items():
                items.append(ItemStack(name=name, count=count, subgroup="raw-resource"))
        
        return items
    
    def __repr__(self) -> str:
        """String representation of the resource."""
        amount_str = f", amount={self._amount}" if self._amount is not None else ""
        return f"{self.__class__.__name__}(name='{self.name}', position=MapPosition({self.position.x}, {self.position.y}){amount_str})"


class RockEntity(BaseResource):
    """Rock resource entity (simple-entity type)."""
    pass


class TreeEntity(BaseResource):
    """Tree resource entity (tree type)."""
    pass


class CopperOre(BaseResource):
    """Copper ore resource patch."""
    pass


class IronOre(BaseResource):
    """Iron ore resource patch."""
    pass


class Coal(BaseResource):
    """Coal resource patch."""
    pass


class Stone(BaseResource):
    """Stone resource (from rocks)."""
    pass


class CrudeOil(BaseResource):
    """Crude oil resource (requires pumpjack, not directly mineable by agent)."""
    
    async def mine(self, max_count: Optional[int] = None, timeout: Optional[int] = None) -> List:
        """Crude oil cannot be mined directly by the agent."""
        raise RuntimeError("Cannot mine crude oil directly. Use a pumpjack to extract oil.")


def _create_resource_from_data(data: Dict[str, Any]) -> BaseResource:
    """Create appropriate resource instance from data dict.
    
    Args:
        data: Resource data dict from get_reachable
        
    Returns:
        Appropriate BaseResource subclass instance
    """
    name = data.get("name", "")
    resource_type = data.get("type", "resource")
    position_data = data.get("position", {})
    position = MapPosition(x=position_data.get("x", 0), y=position_data.get("y", 0))
    
    # Map to specific resource classes
    if resource_type == "simple-entity":
        return RockEntity(name, position, resource_type, data)
    elif resource_type == "tree":
        return TreeEntity(name, position, resource_type, data)
    elif name == "copper-ore":
        return CopperOre(name, position, resource_type, data)
    elif name == "iron-ore":
        return IronOre(name, position, resource_type, data)
    elif name == "coal":
        return Coal(name, position, resource_type, data)
    elif name == "crude-oil":
        return CrudeOil(name, position, resource_type, data)
    else:
        # Default to BaseResource for unknown resources
        return BaseResource(name, position, resource_type, data)

