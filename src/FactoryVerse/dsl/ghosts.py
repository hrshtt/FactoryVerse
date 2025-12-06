from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING
from src.FactoryVerse.dsl.types import MapPosition
from src.FactoryVerse.dsl.item.base import ItemStack

if TYPE_CHECKING:
    from src.FactoryVerse.dsl.agent import PlayingFactory


class GhostManager:
    """Manages tracked ghost entities for an agent.
    
    Provides methods to list, filter, and check buildability of ghosts.
    All ghost tracking is Python-only and does not affect the mod.
    """
    
    def __init__(self, factory: "PlayingFactory"):
        """Initialize GhostManager with reference to factory.
        
        Args:
            factory: PlayingFactory instance for accessing inventory and other methods
        """
        self._factory = factory
        self.__tracked_ghosts: Dict[str, Dict[str, Any]] = {}  # Key: f"{position.x},{position.y}:{entity_name}"
    
    @property
    def _tracked_ghosts(self) -> Dict[str, Dict[str, Any]]:
        """Get tracked ghosts dictionary.
        
        Returns:
            Dict mapping ghost_key -> {position, entity_name, placed_tick, label}
        """
        return self.__tracked_ghosts
    
    def list_ghosts(self) -> List[Dict[str, Any]]:
        """List all tracked ghosts.
        
        Returns:
            List of ghost data dictionaries
        """
        return list(self._tracked_ghosts.values())
    
    def list_labels(self) -> List[str]:
        """List all unique labels from tracked ghosts.
        
        Returns:
            List of unique label strings (excluding None)
        """
        labels = set()
        for ghost_data in self._tracked_ghosts.values():
            label = ghost_data.get("label")
            if label is not None:
                labels.add(label)
        return sorted(list(labels))
    
    def get_ghosts(
        self,
        area: Optional[Dict[str, Any]] = None,
        label: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get ghosts filtered by area and/or label.
        
        Args:
            area: Optional area constraint dict with keys:
                - min_x, min_y, max_x, max_y (bounding box)
                - OR center_x, center_y, radius (circular area)
            label: Optional label to filter by
        
        Returns:
            List of ghost data dictionaries matching filters
        """
        filtered = []
        
        for ghost_data in self.__tracked_ghosts.values():
            # Filter by label
            if label is not None:
                if ghost_data.get("label") != label:
                    continue
            
            # Filter by area
            if area is not None:
                pos = ghost_data.get("position", {})
                if isinstance(pos, dict):
                    x = pos.get("x", 0)
                    y = pos.get("y", 0)
                else:
                    x = getattr(pos, "x", 0)
                    y = getattr(pos, "y", 0)
                
                # Check bounding box
                if "min_x" in area and "min_y" in area and "max_x" in area and "max_y" in area:
                    if not (area["min_x"] <= x <= area["max_x"] and 
                            area["min_y"] <= y <= area["max_y"]):
                        continue
                
                # Check circular area
                elif "center_x" in area and "center_y" in area and "radius" in area:
                    center_x = area["center_x"]
                    center_y = area["center_y"]
                    radius = area["radius"]
                    dx = x - center_x
                    dy = y - center_y
                    if dx * dx + dy * dy > radius * radius:
                        continue
            
            filtered.append(ghost_data)
        
        return filtered
    
    def can_build(self, agent_inventory: List[ItemStack]) -> Dict[str, Any]:
        """Check if agent can build all tracked ghosts based on inventory.
        
        Args:
            agent_inventory: List of ItemStack objects from agent inventory
        
        Returns:
            Dict with:
                - can_build_all: bool
                - buildable_count: int (number of ghosts that can be built)
                - total_count: int (total number of tracked ghosts)
                - missing_items: Dict[str, int] (item_name -> count needed)
                - buildable_ghosts: List[Dict] (ghosts that can be built)
                - unbuildable_ghosts: List[Dict] (ghosts that cannot be built)
        """
        # Create inventory lookup
        inventory_dict = {item.name: item.count for item in agent_inventory}
        
        # Count required items per entity type
        required_items: Dict[str, int] = {}
        ghost_counts: Dict[str, int] = {}  # entity_name -> count
        
        for ghost_data in self.__tracked_ghosts.values():
            entity_name = ghost_data.get("entity_name", "")
            if entity_name:
                ghost_counts[entity_name] = ghost_counts.get(entity_name, 0) + 1
                # Each ghost requires 1 of its entity item
                required_items[entity_name] = required_items.get(entity_name, 0) + 1
        
        # Check what can be built
        missing_items: Dict[str, int] = {}
        buildable_ghosts: List[Dict[str, Any]] = []
        unbuildable_ghosts: List[Dict[str, Any]] = []
        
        for ghost_data in self.__tracked_ghosts.values():
            entity_name = ghost_data.get("entity_name", "")
            available = inventory_dict.get(entity_name, 0)
            
            if available > 0:
                buildable_ghosts.append(ghost_data)
                # Consume one item for this ghost
                inventory_dict[entity_name] = available - 1
            else:
                unbuildable_ghosts.append(ghost_data)
                missing_items[entity_name] = missing_items.get(entity_name, 0) + 1
        
        can_build_all = len(unbuildable_ghosts) == 0
        
        return {
            "can_build_all": can_build_all,
            "buildable_count": len(buildable_ghosts),
            "total_count": len(self.__tracked_ghosts),
            "missing_items": missing_items,
            "buildable_ghosts": buildable_ghosts,
            "unbuildable_ghosts": unbuildable_ghosts,
        }
    
    def add_ghost(
        self,
        position: Union[Dict[str, float], MapPosition],
        entity_name: str,
        label: Optional[str] = None,
        placed_tick: int = 0
    ) -> str:
        """Add a ghost to tracking.
        
        Args:
            position: Ghost position (dict with x,y or MapPosition)
            entity_name: Entity name the ghost represents
            label: Optional label for grouping
            placed_tick: Game tick when ghost was placed (default: 0)
        
        Returns:
            Ghost key string
        """
        # Convert position to dict if needed
        if hasattr(position, 'x') and hasattr(position, 'y'):
            pos_dict = {"x": position.x, "y": position.y}
        else:
            pos_dict = position
        
        ghost_key = f"{pos_dict['x']},{pos_dict['y']}:{entity_name}"
        self.__tracked_ghosts[ghost_key] = {
            "position": pos_dict,
            "entity_name": entity_name,
            "placed_tick": placed_tick,
            "label": label,
        }
        return ghost_key
    
    def remove_ghost(
        self,
        position: Union[Dict[str, float], MapPosition],
        entity_name: str
    ) -> bool:
        """Remove a ghost from tracking.
        
        Args:
            position: Ghost position (dict with x,y or MapPosition)
            entity_name: Entity name the ghost represents
        
        Returns:
            True if ghost was removed, False if not found
        """
        # Convert position to dict if needed
        if hasattr(position, 'x') and hasattr(position, 'y'):
            pos_dict = {"x": position.x, "y": position.y}
        else:
            pos_dict = position
        
        ghost_key = f"{pos_dict['x']},{pos_dict['y']}:{entity_name}"
        if ghost_key in self.__tracked_ghosts:
            del self.__tracked_ghosts[ghost_key]
            return True
        return False
    
    # TODO: Implement build_ghosts method
    # Parameters:
    #   - ghosts: Optional list of ghost keys to build (default: all tracked ghosts)
    #   - area: Optional area constraint (max 5x5 chunks = 160x160 tiles, default: 5x5 chunks)
    #   - count: Max entities to build (cannot exceed 64, default: 64)
    #   - strict: If True, validate agent has all items before building (default: True)
    #   - label: Optional label filter - only build ghosts with matching label
    # 
    # Implementation steps:
    #   1. Filter ghosts by label if provided
    #   2. If strict=True, validate agent has all required items for up to count entities
    #   3. Sort ghosts by distance to agent
    #   4. Apply shallow reachable distance clustering to group nearby ghosts
    #   5. For each cluster:
    #      a. Walk to get ghosts in reachable distance
    #      b. Build entities if items are in inventory
    #   6. Remove built ghosts from tracking
    def build_ghosts(
        self,
        ghosts: Optional[List[str]] = None,
        area: Optional[Dict[str, Any]] = None,
        count: int = 64,
        strict: bool = True,
        label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build tracked ghost entities in bulk.
        
        Args:
            ghosts: Optional list of ghost keys to build (default: all tracked ghosts)
            area: Optional area constraint (max 5x5 chunks = 160x160 tiles, default: 5x5 chunks)
            count: Max entities to build (cannot exceed 64, default: 64)
            strict: If True, validate agent has all items before building (default: True)
            label: Optional label filter - only build ghosts with matching label
            
        Returns:
            Result dict with build status and details
            
        Raises:
            NotImplementedError: Method not yet implemented
        """
        raise NotImplementedError("build_ghosts is not yet implemented")

