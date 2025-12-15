from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING
import json
import math
from pathlib import Path
from src.FactoryVerse.dsl.types import MapPosition
from src.FactoryVerse.dsl.item.base import ItemStack

if TYPE_CHECKING:
    from src.FactoryVerse.dsl.agent import PlayingFactory


class GhostManager:
    """Manages tracked ghost entities for an agent.
    
    Provides methods to list, filter, and check buildability of ghosts.
    All ghost tracking is Python-only and does not affect the mod.
    """
    
    
    def __init__(self, factory: "PlayingFactory", agent_id: Optional[str] = None):
        """Initialize GhostManager with reference to factory.
        
        Args:
            factory: PlayingFactory instance for accessing inventory and other methods
            agent_id: Agent ID (e.g., "agent_1"). If provided, persistence is enabled.
        """
        self._factory = factory
        self.__tracked_ghosts: Dict[str, Dict[str, Any]] = {}  # Key: f"{position.x},{position.y}:{entity_name}"
        
        # Persistence setup
        if agent_id:
            self.filepath = Path(".fv-output") / agent_id / "ghosts.json"
            self._load()
        else:
            self.filepath = None
    
    def _load(self):
        """Load tracked ghosts from disk."""
        if self.filepath and self.filepath.exists():
            try:
                with open(self.filepath, "r") as f:
                    self.__tracked_ghosts = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                # Log error but don't crash, start with empty
                print(f"Warning: Failed to load ghost file {self.filepath}: {e}")
                self.__tracked_ghosts = {}
    
    def _save(self):
        """Save tracked ghosts to disk."""
        if self.filepath:
            try:
                # Ensure directory exists
                self.filepath.parent.mkdir(parents=True, exist_ok=True)
                # Atomic write pattern
                temp_path = self.filepath.with_suffix(".tmp")
                with open(temp_path, "w") as f:
                    json.dump(self.__tracked_ghosts, f, indent=2)
                temp_path.replace(self.filepath)
            except IOError as e:
                print(f"Warning: Failed to save ghost file {self.filepath}: {e}")

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
        self._save()
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
            self._save()
            return True
        return False
    
    async def build_ghosts(
        self,
        ghosts: Optional[List[str]] = None,
        area: Optional[Dict[str, Any]] = None,
        count: int = 64,
        strict: bool = True,
        label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build tracked ghost entities in bulk.
        
        This is an async method that walks to ghost locations and builds them.
        Prints progress as it goes: (1/n) placed, etc.
        
        Args:
            ghosts: Optional list of ghost keys to build (default: all tracked ghosts)
            area: Optional area constraint (max 5x5 chunks = 160x160 tiles, default: 5x5 chunks)
            count: Max entities to build (cannot exceed 64, default: 64)
            strict: If True, validate agent has all items before building (default: True)
            label: Optional label filter - only build ghosts with matching label
            
        Returns:
            Result dict with:
                - built_count: int (number of ghosts built)
                - failed_count: int (number of ghosts that couldn't be built)
                - total_processed: int (total ghosts processed)
                - built_ghosts: List[Dict] (ghosts that were built)
                - failed_ghosts: List[Dict] (ghosts that failed)
        """
        # Step 1: Filter ghosts
        candidate_ghosts = []
        
        if ghosts is not None:
            # Filter by provided ghost keys
            for ghost_key in ghosts:
                if ghost_key in self.__tracked_ghosts:
                    candidate_ghosts.append((ghost_key, self.__tracked_ghosts[ghost_key]))
        else:
            # Use all tracked ghosts
            for ghost_key, ghost_data in self.__tracked_ghosts.items():
                candidate_ghosts.append((ghost_key, ghost_data))
        
        # Filter by label if provided
        if label is not None:
            candidate_ghosts = [
                (key, data) for key, data in candidate_ghosts
                if data.get("label") == label
            ]
        
        # Filter by area if provided
        if area is not None:
            filtered = []
            for ghost_key, ghost_data in candidate_ghosts:
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
                
                filtered.append((ghost_key, ghost_data))
            candidate_ghosts = filtered
        
        # Step 2: Get agent position
        agent_pos = self._factory.get_position()
        
        # Step 3: Calculate distances and sort
        ghost_distances = []
        for ghost_key, ghost_data in candidate_ghosts:
            pos = ghost_data.get("position", {})
            if isinstance(pos, dict):
                x = pos.get("x", 0)
                y = pos.get("y", 0)
            else:
                x = getattr(pos, "x", 0)
                y = getattr(pos, "y", 0)
            
            dx = x - agent_pos.x
            dy = y - agent_pos.y
            distance = math.sqrt(dx * dx + dy * dy)
            ghost_distances.append((distance, ghost_key, ghost_data))
        
        # Sort by distance
        ghost_distances.sort(key=lambda x: x[0])
        
        # Step 4: If strict=True, validate inventory
        if strict:
            # Get inventory
            inventory = self._factory.inventory.item_stacks
            inventory_dict = {item.name: item.count for item in inventory}
            
            # Count required items
            required = {}
            for _, ghost_key, ghost_data in ghost_distances[:count]:
                entity_name = ghost_data.get("entity_name", "")
                if entity_name:
                    required[entity_name] = required.get(entity_name, 0) + 1
            
            # Check if we have enough
            missing = {}
            for entity_name, needed in required.items():
                available = inventory_dict.get(entity_name, 0)
                if available < needed:
                    missing[entity_name] = needed - available
            
            if missing:
                return {
                    "built_count": 0,
                    "failed_count": 0,
                    "total_processed": 0,
                    "built_ghosts": [],
                    "failed_ghosts": [],
                    "error": f"Insufficient items: {missing}"
                }
        
        # Step 5: Simple clustering (group within reach_distance ~2.5 tiles)
        REACH_DISTANCE = 2.5
        clusters = []
        used = set()
        
        for distance, ghost_key, ghost_data in ghost_distances[:count]:
            if ghost_key in used:
                continue
            
            # Start new cluster
            cluster = [(ghost_key, ghost_data)]
            used.add(ghost_key)
            
            # Find nearby ghosts
            pos = ghost_data.get("position", {})
            if isinstance(pos, dict):
                cluster_x = pos.get("x", 0)
                cluster_y = pos.get("y", 0)
            else:
                cluster_x = getattr(pos, "x", 0)
                cluster_y = getattr(pos, "y", 0)
            
            for other_dist, other_key, other_data in ghost_distances[:count]:
                if other_key in used:
                    continue
                
                other_pos = other_data.get("position", {})
                if isinstance(other_pos, dict):
                    other_x = other_pos.get("x", 0)
                    other_y = other_pos.get("y", 0)
                else:
                    other_x = getattr(other_pos, "x", 0)
                    other_y = getattr(other_pos, "y", 0)
                
                dx = other_x - cluster_x
                dy = other_y - cluster_y
                dist = math.sqrt(dx * dx + dy * dy)
                
                if dist <= REACH_DISTANCE * 2:  # Allow slightly larger clusters
                    cluster.append((other_key, other_data))
                    used.add(other_key)
            
            clusters.append(cluster)
        
        # Step 6: Build ghosts cluster by cluster
        built_count = 0
        failed_count = 0
        built_ghosts = []
        failed_ghosts = []
        total_to_build = sum(len(cluster) for cluster in clusters)
        
        print(f"Building {total_to_build} ghosts in {len(clusters)} clusters...")
        
        for cluster_idx, cluster in enumerate(clusters, 1):
            # Calculate cluster center (average position)
            total_x = 0
            total_y = 0
            for _, ghost_data in cluster:
                pos = ghost_data.get("position", {})
                if isinstance(pos, dict):
                    total_x += pos.get("x", 0)
                    total_y += pos.get("y", 0)
                else:
                    total_x += getattr(pos, "x", 0)
                    total_y += getattr(pos, "y", 0)
            
            center_x = total_x / len(cluster)
            center_y = total_y / len(cluster)
            cluster_center = MapPosition(x=center_x, y=center_y)
            
            # Walk to cluster center
            print(f"Cluster {cluster_idx}/{len(clusters)}: Walking to ({center_x:.1f}, {center_y:.1f})...")
            await self._factory.walking.to(cluster_center, strict_goal=False)
            
            # Get reachable ghosts after walking
            reachable_data = self._factory.get_reachable(attach_ghosts=True)
            reachable_ghosts = reachable_data.get("ghosts", [])
            
            # Create position lookup for reachable ghosts
            reachable_positions = {}
            for ghost in reachable_ghosts:
                pos = ghost.get("position", {})
                if isinstance(pos, dict):
                    key = f"{pos.get('x', 0)},{pos.get('y', 0)}"
                else:
                    key = f"{getattr(pos, 'x', 0)},{getattr(pos, 'y', 0)}"
                reachable_positions[key] = ghost
            
            # Build ghosts in cluster
            for ghost_key, ghost_data in cluster:
                entity_name = ghost_data.get("entity_name", "")
                pos = ghost_data.get("position", {})
                
                if isinstance(pos, dict):
                    pos_key = f"{pos.get('x', 0)},{pos.get('y', 0)}"
                    position = MapPosition(x=pos.get("x", 0), y=pos.get("y", 0))
                else:
                    pos_key = f"{getattr(pos, 'x', 0)},{getattr(pos, 'y', 0)}"
                    position = MapPosition(x=getattr(pos, "x", 0), y=getattr(pos, "y", 0))
                
                # Check if ghost is reachable
                if pos_key not in reachable_positions:
                    print(f"  Ghost {entity_name} at {pos_key} not reachable, skipping")
                    failed_count += 1
                    failed_ghosts.append(ghost_data)
                    continue
                
                # Try to build
                try:
                    result = self._factory.place_entity(
                        entity_name=entity_name,
                        position=position,
                        ghost=False
                    )
                    
                    if result.get("success"):
                        built_count += 1
                        built_ghosts.append(ghost_data)
                        print(f"  ({built_count}/{total_to_build}) Built {entity_name} at {pos_key}")
                        
                        # Remove from tracking (place_entity should do this, but be safe)
                        if ghost_key in self.__tracked_ghosts:
                            del self.__tracked_ghosts[ghost_key]
                    else:
                        failed_count += 1
                        failed_ghosts.append(ghost_data)
                        print(f"  Failed to build {entity_name} at {pos_key}: {result.get('error', 'Unknown error')}")
                except Exception as e:
                    failed_count += 1
                    failed_ghosts.append(ghost_data)
                    print(f"  Error building {entity_name} at {pos_key}: {e}")
        
        # Save updated tracking
        self._save()
        
        # Summary
        print(f"\nBuild summary: {built_count} built, {failed_count} failed out of {total_to_build} total")
        
        return {
            "built_count": built_count,
            "failed_count": failed_count,
            "total_processed": total_to_build,
            "built_ghosts": built_ghosts,
            "failed_ghosts": failed_ghosts,
        }

