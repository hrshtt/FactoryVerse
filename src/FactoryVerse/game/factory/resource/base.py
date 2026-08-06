from __future__ import annotations
from typing import List, Optional, Dict, Any, Union, TYPE_CHECKING
from FactoryVerse.game.factory.types import (
    MapPosition,
    ResourcePatchData,
    ProductData,
    EntityInspectionData,
)
import asyncio

if TYPE_CHECKING:
    from FactoryVerse.game.factory.item.base import ItemStack
    from FactoryVerse.game.agent.embodied_actions.mining import MiningAction
    from FactoryVerse.game.agent.embodied_actions.entity_operations import EntityOperationsAction
    from FactoryVerse.game.agent.embodied_actions.walking import MovementAction
    from FactoryVerse.game.factory.entity.base_entity import EntityView

# =============================================================================
# RESOURCE TYPE MAPPING (Agent-facing <-> Game-facing)
# =============================================================================
# Rocks are represented as "simple-entity" in Factorio, but agents use "rock"
# These utilities handle bidirectional mapping between agent and game representations

def _agent_to_game_resource_type(resource_type: str) -> str:
    """Convert agent-facing resource type to game-facing type.
    
    Maps "rock" -> "simple-entity" for game queries.
    All other types pass through unchanged.
    
    Args:
        resource_type: Agent-facing resource type (e.g., "rock", "tree", "resource")
    
    Returns:
        Game-facing resource type (e.g., "simple-entity", "tree", "resource")
    """
    if resource_type == "rock":
        return "simple-entity"
    return resource_type


def _game_to_agent_resource_type(resource_type: str) -> str:
    """Convert game-facing resource type to agent-facing type.
    
    Maps "simple-entity" -> "rock" for agent representation.
    All other types pass through unchanged.
    
    Args:
        resource_type: Game-facing resource type (e.g., "simple-entity", "tree", "resource")
    
    Returns:
        Agent-facing resource type (e.g., "rock", "tree", "resource")
    """
    if resource_type == "simple-entity":
        return "rock"
    return resource_type


class ResourceOrePatch:
    """Resource ore patch representing multiple resource tiles consolidated.

    Similar to ItemStack but for resources. Consolidates multiple resource
    entries with the same name into a single patch for cleaner agent interface.

    Uses dependency injection pattern - receives MiningAction to enable mining.
    Resources own their view (REMOTE or REACHABLE) like entities do.
    """

    # Blocked methods by view
    _REMOTE_ONLY = frozenset({"mine"})  # Block mine() when REMOTE
    _REACHABLE_ONLY = frozenset({"walk_to"})  # Block walk_to() when REACHABLE

    def __init__(
        self,
        name: str,
        resource_data_list: List[Dict[str, Any]],
        mining_action: "MiningAction",
        entity_ops: "EntityOperationsAction",
        walking_action: "MovementAction",
        view: "EntityView" = None,
    ):
        """Initialize ResourceOrePatch from a list of resource data dicts.

        Args:
            name: Resource name (e.g., "copper-ore", "iron-ore")
            resource_data_list: List of resource data dicts from get_reachable
            mining_action: Injected MiningAction for mining operations
            entity_ops: Injected EntityOperationsAction for inspection
            walking_action: Injected MovementAction for navigation
            view: Resource view type (REMOTE or REACHABLE). Defaults to REACHABLE.
        """
        from FactoryVerse.game.factory.entity.base_entity import EntityView

        self.name = name
        self._resource_data_list = resource_data_list
        self._resource_instances: Optional[List["BaseResource"]] = None
        self._mining = mining_action
        self._entity_ops = entity_ops
        self._walking_action = walking_action
        self._view = view if view is not None else EntityView.REACHABLE

    @property
    def view(self) -> "EntityView":
        """Whether this patch is REMOTE or REACHABLE."""
        return self._view

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
        """Get the resource type (resource, tree, rock).
        
        Returns agent-facing representation: "rock" instead of "simple-entity".
        """
        if self._resource_data_list:
            game_type = self._resource_data_list[0].get("type", "resource")
            return _game_to_agent_resource_type(game_type)
        return "resource"

    @property
    def position(self) -> MapPosition:
        """Get the average position of all resource tiles in the patch.

        Returns:
            MapPosition with average x and y coordinates
        """
        if not self._resource_data_list:
            return MapPosition(x=0, y=0)

        total_x = 0.0
        total_y = 0.0
        count = 0

        for data in self._resource_data_list:
            pos_data = data.get("position", {})
            x = pos_data.get("x", 0)
            y = pos_data.get("y", 0)
            total_x += x
            total_y += y
            count += 1

        if count == 0:
            return MapPosition(x=0, y=0)

        avg_x = total_x / count
        avg_y = total_y / count
        return MapPosition(x=avg_x, y=avg_y)

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
                return _create_resource_from_data(
                    data, self._mining, self._entity_ops, self._walking_action, view=self._view
                )
        return None

    def __getitem__(self, index: int) -> "BaseResource":
        """Get a resource tile by index.

        Args:
            index: Index of the resource tile (must be < count)

        Returns:
            BaseResource instance for that tile
        """
        if index < 0 or index >= len(self._resource_data_list):
            raise IndexError(
                f"Index {index} out of range for patch with {len(self._resource_data_list)} tiles"
            )

        data = self._resource_data_list[index]
        return _create_resource_from_data(
            data, self._mining, self._entity_ops, self._walking_action, view=self._view
        )

    def inspect(
        self, raw_data: bool = False, live: bool = False
    ) -> Union[str, ResourcePatchData]:
        """Return a representation of the resource patch.

        Args:
            raw_data: If False (default), returns a formatted string representation.
                      If True, returns the raw dictionary data.
            live: If True, fetches live data from game via batch inspection (slower but current).
                  If False (default), uses cached data from get_reachable.

        Returns:
            If raw_data=False: Formatted string representation
            If raw_data=True: Dictionary with patch data including:
                - name (str): Resource name
                - type (str): Resource type
                - total_amount (int): Total amount across all tiles
                - tile_count (int): Number of tiles in patch
                - position (dict): Average position {x, y}
                - tiles (list): List of tile data dicts (live if live=True)
        """
        tiles_data = self._resource_data_list

        # If live inspection requested, fetch current amounts from game
        if live and self._entity_ops:
            tiles_data = self._inspect_tiles_batch()

        # Calculate total from tiles
        total_amount = sum(
            data.get("amount", 0) for data in tiles_data if "amount" in data
        )

        if raw_data:
            return {
                "name": self.name,
                "type": self.resource_type,
                "total_amount": total_amount,
                "tile_count": len(tiles_data),
                "position": {"x": self.position.x, "y": self.position.y},
                "tiles": tiles_data,
            }

        # Format as readable string
        lines = [
            f"ResourceOrePatch(name='{self.name}', type='{self.resource_type}')",
            f"  Total amount: {total_amount}",
            f"  Tile count: {len(tiles_data)}",
            f"  Average position: ({self.position.x:.1f}, {self.position.y:.1f})",
        ]

        # Show amount range if applicable
        if tiles_data:
            amounts = [data.get("amount", 0) for data in tiles_data if "amount" in data]
            if amounts:
                lines.append(
                    f"  Amount range: {min(amounts)} - {max(amounts)} per tile"
                )

        return "\n".join(lines)

    def _inspect_tiles_batch(self) -> List[Dict[str, Any]]:
        """Batch inspect all tiles in this patch using efficient Lua loop.

        Similar to placement_hints batch validation pattern - generates Lua code
        that inspects multiple resources in one RCON call.

        Returns:
            List of updated tile data dicts with current amounts
        """
        if not self._entity_ops:
            # Fallback to cached data if no entity_ops
            return self._resource_data_list

        # Build Lua command for batch inspection
        lua_code = f"""
local surface = game.surfaces[1]
local inspection = require("agent_actions.inspection")
local results = {{}}

"""

        # Add each tile inspection
        for i, tile_data in enumerate(self._resource_data_list):
            pos = tile_data.get("position", {})
            lua_code += f"""
local entity_{i} = surface.find_entity("{self.name}", {{x = {pos.get("x", 0)}, y = {pos.get("y", 0)}}})
if entity_{i} and entity_{i}.valid then
    results[{i + 1}] = inspection.inspect_entity(entity_{i})
else
    results[{i + 1}] = nil
end
"""

        lua_code += "\nrcon.print(helpers.table_to_json(results))"

        try:
            import json
            from FactoryVerse.game.agent.infra.rcon_handler import RconHandler

            # Execute batch inspection
            result = self._entity_ops._rcon.execute(lua_code)
            if not result:
                return self._resource_data_list

            # Parse results
            parsed = json.loads(result.strip())

            # Update tile data with live inspection results
            updated_tiles = []
            for i, tile_data in enumerate(self._resource_data_list):
                inspection_data = (
                    parsed.get(str(i + 1))
                    if isinstance(parsed, dict)
                    else (parsed[i] if i < len(parsed) else None)
                )

                if inspection_data:
                    # Merge inspection data with cached tile data
                    updated_tile = tile_data.copy()
                    updated_tile["amount"] = inspection_data.get(
                        "amount", tile_data.get("amount", 0)
                    )
                    updated_tiles.append(updated_tile)
                else:
                    # Resource no longer exists or couldn't be inspected
                    updated_tiles.append(tile_data)

            return updated_tiles

        except Exception as e:
            # On error, return cached data
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(f"Batch resource inspection failed: {e}, using cached data")
            return self._resource_data_list

    async def mine(
        self, max_count: Optional[int] = None, timeout: Optional[int] = None
    ) -> List["ItemStack"]:
        """Mine a resource tile from this patch.

        Mines the first tile in the patch without requiring position.
        Delegates to the injected MiningAction.

        Args:
            max_count: Max items to mine (None = mine up to 25, max 25)
            timeout: Optional timeout in seconds

        Returns:
            List of ItemStack objects obtained from mining

        Raises:
            ValueError: If max_count exceeds 25
            RuntimeError: If MiningAction not injected
        """
        if self._mining is None:
            raise RuntimeError(
                f"Cannot mine {self.name}: MiningAction not injected. "
                "Resource must be created through Reachable.get_resource() or Reachable.get_resources()."
            )

        # Enforce 25-item limit per operation
        if max_count is not None and max_count > 25:
            raise ValueError(
                f"Cannot mine more than 25 items in a single operation. "
                f"Requested: {max_count}. Please mine in smaller batches."
            )
        # Cap at 25 even if None (to enforce hard limit)
        effective_max_count = min(max_count, 25) if max_count is not None else 25

        # Mine the first tile in the patch
        if not self._resource_data_list:
            raise RuntimeError("Cannot mine from empty patch")

        # Get position of first tile for mining
        first_tile_data = self._resource_data_list[0]
        pos_data = first_tile_data.get("position", {})
        position = MapPosition(x=pos_data.get("x", 0), y=pos_data.get("y", 0))

        # Delegate to injected MiningAction
        return await self._mining.mine(
            resource_name=self.name,
            max_count=effective_max_count,
            position=position,
            timeout=timeout,
        )

    def __getattribute__(self, name: str):
        """Filter method access based on view."""
        attr = super().__getattribute__(name)

        if not callable(attr) or name.startswith("_"):
            return attr

        view = super().__getattribute__("_view")

        if view.value == "remote" and name in ResourceOrePatch._REMOTE_ONLY:
            raise AttributeError(
                f"Cannot {name}() remotely. Resource not reachable. "
                "Use reachable.get_resource() for full access."
            )

        if view.value == "reachable" and name in ResourceOrePatch._REACHABLE_ONLY:
            raise AttributeError(
                f"Cannot {name}() on reachable resource. "
                "Resource is already within reach."
            )

        return attr

    def __repr__(self) -> str:
        """Clean summary of the resource patch."""
        tiles_info = []
        for i, data in enumerate(self._resource_data_list):
            pos = data.get("position", {})
            amount = data.get("amount", "N/A")
            tiles_info.append(
                f"  [{i}] pos=({pos.get('x', 0)}, {pos.get('y', 0)}) amount={amount}"
            )

        tiles_str = "\n".join(tiles_info) if tiles_info else "  (no tiles)"
        view_prefix = self._view.value.capitalize()
        return f"""{view_prefix}[ResourceOrePatch](name='{self.name}', type='{self.resource_type}', total={self.total}, tiles={self.count})
{tiles_str}"""


class BaseResource:
    """Base class for all mineable resources.

    Resources can be mined directly using the async mine() method.
    Uses dependency injection pattern - receives MiningAction to enable mining.
    Resources own their view (REMOTE or REACHABLE) like entities do.
    """

    # Blocked methods by view
    _REMOTE_ONLY = frozenset({"mine"})  # Block mine() when REMOTE
    _REACHABLE_ONLY = frozenset({"walk_to"})  # Block walk_to() when REACHABLE

    def __init__(
        self,
        name: str,
        position: MapPosition,
        resource_type: str,
        data: Dict[str, Any],
        mining_action: "MiningAction",
        entity_ops: "EntityOperationsAction",
        walking_action: "MovementAction",
        view: "EntityView" = None,
    ):
        """Initialize BaseResource.

        Args:
            name: Resource name (e.g., "copper-ore", "tree", "big-rock")
            position: MapPosition of the resource
            resource_type: Factorio entity type ("resource", "tree", "simple-entity")
            data: Full resource data dict from get_reachable
            mining_action: Injected MiningAction for mining operations
            entity_ops: Injected EntityOperationsAction for inspection
            walking_action: Injected MovementAction for navigation
            view: Resource view type (REMOTE or REACHABLE). Defaults to REACHABLE.
        """
        from FactoryVerse.game.factory.entity.base_entity import EntityView

        self.name = name
        self.position = position
        # Store game-facing type internally, but expose agent-facing type via property
        self._resource_type = resource_type
        self._data = data
        self._amount = data.get("amount")
        self._products: List[ProductData] = data.get("products", [])
        self._mining = mining_action
        self._entity_ops = entity_ops
        self._walking_action = walking_action
        self._view = view if view is not None else EntityView.REACHABLE

    @property
    def view(self) -> "EntityView":
        """Whether this resource handle is REMOTE or REACHABLE."""
        return self._view

    @property
    def resource_type(self) -> str:
        """Get the resource type (resource, tree, rock).
        
        Returns agent-facing representation: "rock" instead of "simple-entity".
        """
        return _game_to_agent_resource_type(self._resource_type)
    
    @property
    def amount(self) -> Optional[int]:
        """Get resource amount (only for ore patches, None for trees/rocks)."""
        return self._amount

    @property
    def products(self) -> List[ProductData]:
        """Get mineable products from this resource.

        **For Agents**: Check what items you will get from mining this resource.
        """
        return self._products

    async def walk_to(self, timeout: Optional[int] = None) -> "MapPosition":
        """Walk to this resource.

        Delegates to the walking action to navigate to this resource.
        After successful walk, changes view from REMOTE to REACHABLE to enable mining.

        Args:
            timeout: Optional timeout in seconds

        Returns:
            Final position reached

        Raises:
            WalkingUnreachableError: If resource cannot be reached
            WalkingEntityNotFoundError: If resource no longer exists
        """
        final_position = await self._walking_action.walk_to_entity(
            entity_name=self.name,
            entity_position=self.position,
            timeout=timeout,
        )
        
        # After successful walk, change view from REMOTE to REACHABLE to enable mining
        if self._view.value == "remote":
            from FactoryVerse.game.factory.entity.base_entity import EntityView
            self._view = EntityView.REACHABLE
        
        return final_position

    def inspect(
        self, raw_data: bool = False, live: bool = False
    ) -> Union[str, EntityInspectionData]:
        """Return a representation of the resource.

        Args:
            raw_data: If False (default), returns a formatted string representation.
                      If True, returns the raw dictionary data.
            live: If True, fetches live data from game via inspection (slower but current).
                  If False (default), uses cached data from get_reachable.

        Returns:
            If raw_data=False: Formatted string representation
            If raw_data=True: Dictionary with resource data (live if live=True)
        """
        data = self._data

        # If live inspection requested, fetch current state from game
        if live:
            try:
                live_data = self._entity_ops.inspect_entity(self.name, self.position)
                # Merge live data with cached data (live takes precedence)
                data = {**self._data, **live_data}
                # Update cached amount if available
                if "amount" in live_data:
                    self._amount = live_data["amount"]
            except Exception as e:
                # On error, use cached data
                import logging

                logger = logging.getLogger(__name__)
                logger.warning(
                    f"Live resource inspection failed: {e}, using cached data"
                )

        if raw_data:
            return data

        # Format as readable string
        lines = [
            f"{self.__class__.__name__}(name='{self.name}', type='{self.resource_type}')",
            f"  Position: ({self.position.x:.1f}, {self.position.y:.1f})",
        ]

        amount = data.get("amount", self._amount)
        if amount is not None:
            lines.append(f"  Amount: {amount}")

        if self._products:
            products_str = ", ".join([p.get("name", "unknown") for p in self._products])
            lines.append(f"  Products: {products_str}")

        return "\n".join(lines)

    async def mine(
        self, max_count: Optional[int] = None, timeout: Optional[int] = None
    ) -> List["ItemStack"]:
        """Mine this resource.

        Delegates to the injected MiningAction.

        Args:
            max_count: Max items to mine (None = mine up to 25, max 25)
            timeout: Optional timeout in seconds

        Returns:
            List of ItemStack objects obtained from mining

        Raises:
            ValueError: If max_count exceeds 25
            RuntimeError: If MiningAction not injected
        """
        if self._mining is None:
            raise RuntimeError(
                f"Cannot mine {self.name}: MiningAction not injected. "
                "Resource must be created through Reachable.get_resource() or Reachable.get_resources()."
            )

        # Enforce 25-item limit per operation
        if max_count is not None and max_count > 25:
            raise ValueError(
                f"Cannot mine more than 25 items in a single operation. "
                f"Requested: {max_count}. Please mine in smaller batches."
            )
        # Cap at 25 even if None (to enforce hard limit)
        effective_max_count = min(max_count, 25) if max_count is not None else 25

        # Delegate to injected MiningAction
        return await self._mining.mine(
            resource_name=self.name,
            max_count=effective_max_count,
            position=self.position,
            timeout=timeout,
        )

    def __getattribute__(self, name: str):
        """Filter method access based on view."""
        attr = super().__getattribute__(name)

        if not callable(attr) or name.startswith("_"):
            return attr

        view = super().__getattribute__("_view")

        if view.value == "remote" and name in BaseResource._REMOTE_ONLY:
            raise AttributeError(
                f"Cannot {name}() remotely. Resource not reachable. "
                "Use reachable.get_resource() for full access."
            )

        if view.value == "reachable" and name in BaseResource._REACHABLE_ONLY:
            raise AttributeError(
                f"Cannot {name}() on reachable resource. "
                "Resource is already within reach."
            )

        return attr

    def __repr__(self) -> str:
        """String representation of the resource."""
        amount_str = f", amount={self._amount}" if self._amount is not None else ""
        view_prefix = self._view.value.capitalize()
        return f"{view_prefix}[{self.__class__.__name__}](name='{self.name}', position=MapPosition({self.position.x}, {self.position.y}){amount_str})"


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

    async def mine(
        self, max_count: Optional[int] = None, timeout: Optional[int] = None
    ) -> List:
        """Crude oil cannot be mined directly by the agent."""
        raise RuntimeError(
            "Cannot mine crude oil directly. Use a pumpjack to extract oil."
        )


def _create_resource_from_data(
    data: Dict[str, Any],
    mining_action: "MiningAction",
    entity_ops: "EntityOperationsAction",
    walking_action: "MovementAction",
    view: "EntityView" = None,
) -> BaseResource:
    """Create appropriate resource instance from data dict.

    Args:
        data: Resource data dict from get_reachable
        mining_action: MiningAction to inject for mining operations
        entity_ops: EntityOperationsAction to inject for inspection
        walking_action: MovementAction to inject for navigation
        view: Resource view type (REMOTE or REACHABLE). Defaults to REACHABLE.

    Returns:
        Appropriate BaseResource subclass instance with injected actions
    """
    from FactoryVerse.game.factory.entity.base_entity import EntityView

    name = data.get("name", "")
    # Keep game-facing type for internal operations
    resource_type = data.get("type", "resource")
    position_data = data.get("position", {})
    position = MapPosition(x=position_data.get("x", 0), y=position_data.get("y", 0))
    resource_view = view if view is not None else EntityView.REACHABLE

    # Map to specific resource classes - all receive mining_action, entity_ops, walking_action, and view
    # Use game-facing type for classification
    if resource_type == "simple-entity":
        return RockEntity(
            name, position, resource_type, data, mining_action, entity_ops, walking_action, view=resource_view
        )
    elif resource_type == "tree":
        return TreeEntity(
            name, position, resource_type, data, mining_action, entity_ops, walking_action, view=resource_view
        )
    elif name == "copper-ore":
        return CopperOre(name, position, resource_type, data, mining_action, entity_ops, walking_action, view=resource_view)
    elif name == "iron-ore":
        return IronOre(name, position, resource_type, data, mining_action, entity_ops, walking_action, view=resource_view)
    elif name == "coal":
        return Coal(name, position, resource_type, data, mining_action, entity_ops, walking_action, view=resource_view)
    elif name == "crude-oil":
        return CrudeOil(name, position, resource_type, data, mining_action, entity_ops, walking_action, view=resource_view)
    else:
        # Default to BaseResource for unknown resources
        return BaseResource(
            name, position, resource_type, data, mining_action, entity_ops, walking_action, view=resource_view
        )


def create_resource_from_reachable(
    data: Dict[str, Any],
    mining_action: "MiningAction",
    entity_ops: "EntityOperationsAction",
    walking_action: "MovementAction",
):
    """Create resource with REACHABLE view from reachable data.

    Returns a resource instance with REACHABLE view:
    - Has spatial properties (position, amount)
    - Can be mined
    - Can be inspected
    - Cannot walk_to (already reachable)

    Args:
        data: Resource data dict from get_reachable()
        mining_action: MiningAction to inject for mining operations
        entity_ops: EntityOperationsAction to inject for inspection
        walking_action: MovementAction to inject for navigation

    Returns:
        Resource instance (BaseResource subclass) with REACHABLE view

    Example:
        >>> ore = create_resource_from_reachable(data, mining_action, entity_ops, walking_action)
        >>> type(ore)
        <class 'IronOre'>
        >>> await ore.mine(max_count=25)  # ✓ Works
        >>> ore.inspect(live=True)  # ✓ Works
        >>> await ore.walk_to()  # ✗ AttributeError - already reachable
    """
    from FactoryVerse.game.factory.entity.base_entity import EntityView

    # Create resource with REACHABLE view
    resource = _create_resource_from_data(data, mining_action, entity_ops, walking_action, view=EntityView.REACHABLE)
    return resource


def create_resource_from_db(
    data: Dict[str, Any],
    mining_action: "MiningAction",
    entity_ops: "EntityOperationsAction",
    walking_action: "MovementAction",
):
    """Create resource with REMOTE view from DB data.

    Returns a resource instance with REMOTE view:
    - Has all spatial properties and prototype data
    - Can be inspected (cached data only, no live inspection)
    - Can walk_to
    - Cannot mine (must walk to first, then get via reachable)

    Args:
        data: Resource data dict from DuckDB query
        mining_action: MiningAction (required but mine() blocked by REMOTE view)
        entity_ops: EntityOperationsAction (required but live inspection limited)
        walking_action: MovementAction for navigation

    Returns:
        Resource instance (BaseResource subclass) with REMOTE view

    Example:
        >>> db_ore = create_resource_from_db(data, mining_action, entity_ops, walking_action)
        >>> type(db_ore)
        <class 'IronOre'>
        >>> db_ore.position  # ✓ Works
        >>> db_ore.amount  # ✓ Works
        >>> db_ore.inspect()  # ✓ Works (cached data)
        >>> await db_ore.walk_to()  # ✓ Works
        >>> await db_ore.mine()  # ✗ AttributeError - REMOTE view blocks mine()
    """
    from FactoryVerse.game.factory.entity.base_entity import EntityView

    # Create resource with REMOTE view (blocks mine())
    resource = _create_resource_from_data(data, mining_action, entity_ops, walking_action, view=EntityView.REMOTE)
    return resource
