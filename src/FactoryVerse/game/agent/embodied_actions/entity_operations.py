"""Entity operations action implementation with dataclass response types.

Handles entity configuration and inventory operations:
- set_entity_recipe: Configure machine recipes
- set_entity_filter: Set inventory filters
- set_inventory_limit: Set inventory slot limits
- take_inventory_item: Transfer items from entity to agent
- put_inventory_item: Transfer items from agent to entity
- inspect_entity: Get comprehensive entity state
- pickup_entity: Mine entity into inventory
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Union, TYPE_CHECKING
import logging

from FactoryVerse.game.factory.types import MapPosition
from FactoryVerse.game.agent.models import ActionResponse

# Import ItemStack for runtime isinstance checks
from FactoryVerse.game.factory.item.base import ItemStack

if TYPE_CHECKING:
    from ..infra.rcon_handler import RconHandler
    from FactoryVerse.game.agent.embodied_actions.place_entity import PlacementAction

logger = logging.getLogger(__name__)


# =============================================================================
# ACTION RESPONSE TYPES
# =============================================================================


@dataclass
class EntityRecipeSet(ActionResponse):
    """Response when entity recipe is set.

    RCON Contract: RemoteInterface.lua set_entity_recipe.returns
    """

    entity_name: str = ""
    position: Optional[Dict[str, float]] = None
    recipe_name: Optional[str] = None

    @property
    def entity_position(self) -> Optional[MapPosition]:
        """Get entity position as MapPosition."""
        if self.position:
            return MapPosition(x=self.position["x"], y=self.position["y"])
        return None


@dataclass
class EntityFilterSet(ActionResponse):
    """Response when entity filter is set.

    RCON Contract: RemoteInterface.lua set_entity_filter.returns
    """

    entity_name: str = ""
    position: Optional[Dict[str, float]] = None
    inventory_type: str = ""
    filter_index: Optional[int] = None
    filter_item: Optional[str] = None


@dataclass
class InventoryLimitSet(ActionResponse):
    """Response when inventory limit is set.

    RCON Contract: RemoteInterface.lua set_inventory_limit.returns
    """

    entity_name: str = ""
    position: Optional[Dict[str, float]] = None
    inventory_type: str = ""
    limit: Optional[int] = None


@dataclass
class InventoryItemTaken(ActionResponse):
    """Response when items are taken from entity inventory.

    RCON Contract: RemoteInterface.lua take_inventory_item.returns

    Note: count is the actual number transferred, which may be less than
    requested_count if the destination inventory couldn't accept all items.
    """

    entity_name: str = ""
    position: Optional[Dict[str, float]] = None
    inventory_type: str = ""
    item_name: str = ""
    count: int = 0  # Actual count transferred
    requested_count: Optional[int] = None  # Originally requested count
    items: Optional[list] = field(default_factory=list)  # For "take all" operations

    @property
    def has_multiple_items(self) -> bool:
        """True if multiple item types were taken."""
        return bool(self.items and len(self.items) > 1)

    @property
    def is_partial(self) -> bool:
        """True if fewer items were transferred than requested."""
        if self.requested_count is None:
            return False
        return self.count < self.requested_count

    def to_item_stacks(self, placement: Optional["PlacementAction"] = None) -> List["ItemStack"]:
        """Convert to list of ItemStacks with placement injected.
        
        Args:
            placement: PlacementAction to inject into items (required for .place() to work)
            
        Returns:
            List of ItemStack instances with placement injected
        """
        from FactoryVerse.game.factory.item.create_item import create_item_stack
        
        if self.items:
            return [
                create_item_stack(
                    name=item["name"],
                    count=item["count"],
                    placement=placement,
                    subgroup="raw-material",
                )
                for item in self.items
            ]
        return [create_item_stack(self.item_name, self.count, placement=placement)]


@dataclass
class InventoryItemPut(ActionResponse):
    """Response when items are put into entity inventory.

    RCON Contract: RemoteInterface.lua put_inventory_item.returns

    Note: count is the actual number transferred, which may be less than
    requested_count if the destination inventory couldn't accept all items.
    """

    entity_name: str = ""
    position: Optional[Dict[str, float]] = None
    inventory_type: str = ""
    item_name: str = ""
    count: int = 0  # Actual count transferred
    requested_count: Optional[int] = None  # Originally requested count

    @property
    def is_partial(self) -> bool:
        """True if fewer items were transferred than requested."""
        if self.requested_count is None:
            return False
        return self.count < self.requested_count


@dataclass
class EntityPickedUp(ActionResponse):
    """Response when entity is picked up.

    RCON Contract: RemoteInterface.lua pickup_entity.returns
    """

    entity_name: str = ""
    position: Optional[Dict[str, float]] = None
    extracted_items: Optional[Dict[str, int]] = None

    @property
    def has_items(self) -> bool:
        """True if any items were extracted."""
        return bool(self.extracted_items)


# =============================================================================
# ENTITY OPERATIONS ACTION
# =============================================================================


class EntityOperationsAction:
    """Entity operations action implementation.

    Owns all entity configuration and inventory operations:
    - set_entity_recipe(): Configure machine recipes
    - set_entity_filter(): Set inventory filters
    - set_inventory_limit(): Set inventory slot limits
    - take_inventory_item(): Transfer items from entity to agent
    - put_inventory_item(): Transfer items from agent to entity
    - inspect_entity(): Get raw entity state dict (parsed at DSL entity level)
    - pickup_entity(): Mine entity into inventory

    Note: inspect_entity returns a raw dict that should be parsed by entity-specific
    classes at the DSL level, allowing each entity type to define its own inspection
    data structure.

    All methods return structured dataclass response types for type safety,
    except inspect_entity which returns raw dict for entity-level parsing.
    """

    def __init__(self, rcon_handler: "RconHandler"):
        """Initialize entity operations action.

        Args:
            rcon_handler: RCON handler for command execution
        """
        self._rcon = rcon_handler

    def set_entity_recipe(
        self,
        entity_name: str,
        recipe_name: Optional[str] = None,
        position: Optional[MapPosition] = None,
    ) -> EntityRecipeSet:
        """Set recipe on a machine (assembler, furnace, chemical plant).

        Args:
            entity_name: Entity prototype name
            recipe_name: Recipe to set (None = clear recipe)
            position: Entity position (None = nearest within reach)

        Returns:
            EntityRecipeSet response with result

        Raises:
            RuntimeError: If RCON command fails
        """
        cmd = self._rcon.build_command(
            "set_entity_recipe", entity_name, position, recipe_name
        )
        response_dict = self._rcon.execute_and_parse_json(cmd)
        return EntityRecipeSet.from_dict(response_dict)

    def set_entity_filter(
        self,
        entity_name: str,
        position: MapPosition,
        inventory_type: str,
        filter_index: Optional[int] = None,
        filter_item: Optional[str] = None,
    ) -> EntityFilterSet:
        """Set inventory filter on an entity (inserter, filtered container).

        Args:
            entity_name: Entity prototype name
            inventory_type: Inventory type to filter
            filter_index: Slot index (None = first slot)
            filter_item: Item to filter (None = clear filter)
            position: Entity position (None = nearest within reach)

        Returns:
            EntityFilterSet response with result

        Raises:
            RuntimeError: If RCON command fails
        """
        cmd = self._rcon.build_command(
            "set_entity_filter",
            entity_name,
            position,
            inventory_type,
            filter_index,
            filter_item,
        )
        response_dict = self._rcon.execute_and_parse_json(cmd)
        return EntityFilterSet.from_dict(response_dict)

    def set_inventory_limit(
        self,
        entity_name: str,
        inventory_type: str,
        limit: Optional[int] = None,
        position: Optional[MapPosition] = None,
    ) -> InventoryLimitSet:
        """Set inventory bar limit on a container.

        Args:
            entity_name: Entity prototype name
            inventory_type: Inventory type to limit
            limit: Slot limit (None = no limit)
            position: Entity position (None = nearest within reach)

        Returns:
            InventoryLimitSet response with result

        Raises:
            RuntimeError: If RCON command fails
        """
        cmd = self._rcon.build_command(
            "set_inventory_limit", entity_name, position, inventory_type, limit
        )
        response_dict = self._rcon.execute_and_parse_json(cmd)
        return InventoryLimitSet.from_dict(response_dict)

    def take_inventory_item(
        self,
        entity_name: str,
        inventory_type: str,
        item_name: str,
        count: Optional[int] = None,
        position: Optional[MapPosition] = None,
    ) -> InventoryItemTaken:
        """Take items from entity's inventory into agent's inventory.

        Args:
            entity_name: Entity prototype name
            inventory_type: Inventory type to take from
            item_name: Item name to take
            count: Count to take (None = all available)
            position: Entity position (None = nearest within reach)

        Returns:
            InventoryItemTaken response with actual count taken

        Raises:
            RuntimeError: If RCON command fails
        """
        cmd = self._rcon.build_command(
            "take_inventory_item",
            entity_name,
            position,
            inventory_type,
            item_name,
            count,
        )
        response_dict = self._rcon.execute_and_parse_json(cmd)
        return InventoryItemTaken.from_dict(response_dict)

    def put_inventory_item(
        self,
        entity_name: str,
        inventory_type: str,
        items: Union["ItemStack", List["ItemStack"]],
        position: Optional[MapPosition] = None,
    ) -> Union[InventoryItemPut, List[InventoryItemPut]]:
        """Put items from agent's inventory into entity's inventory.

        Accepts either a single ItemStack or a list of ItemStacks.
        For lists, performs multiple transfers in sequence.

        Args:
            entity_name: Entity prototype name
            inventory_type: Inventory type to put into
            items: ItemStack or List[ItemStack] to transfer
            position: Entity position (None = nearest within reach)

        Returns:
            InventoryItemPut response (or list of responses for List[ItemStack])

        Raises:
            RuntimeError: If RCON command fails
        """
        # Handle single ItemStack
        if isinstance(items, ItemStack):
            cmd = self._rcon.build_command(
                "put_inventory_item",
                entity_name,
                position,
                inventory_type,
                items.name,
                items.count,
            )
            response_dict = self._rcon.execute_and_parse_json(cmd)
            return InventoryItemPut.from_dict(response_dict)

        # Handle List[ItemStack]
        results = []
        for item_stack in items:
            cmd = self._rcon.build_command(
                "put_inventory_item",
                entity_name,
                position,
                inventory_type,
                item_stack.name,
                item_stack.count,
            )
            response_dict = self._rcon.execute_and_parse_json(cmd)
            results.append(InventoryItemPut.from_dict(response_dict))
        return results

    def inspect_entity(
        self,
        entity_name: str,
        position: MapPosition,
    ) -> Dict[str, Any]:
        """Get comprehensive volatile state for a specific entity.

        Returns raw dict with detailed information including status, recipe,
        progress, inventories, energy, etc. The dict structure matches the
        entity type and should be parsed by entity-specific classes at the
        DSL level.

        Args:
            entity_name: Entity prototype name
            position: Entity position

        Returns:
            Raw dict with complete entity state (structure varies by entity type)

        Raises:
            RuntimeError: If RCON command fails
        """
        cmd = self._rcon.build_command("inspect_entity", entity_name, position)
        return self._rcon.execute_and_parse_json(cmd)

    def pickup_entity(
        self,
        entity_name: str,
        position: Optional[MapPosition] = None,
    ) -> EntityPickedUp:
        """Pick up an entity from the map into agent's inventory.

        The entity must be within reach and mineable/deconstructable.

        Args:
            entity_name: Entity prototype name to pick up
            position: Entity position (None = nearest within reach)

        Returns:
            EntityPickedUp response with extracted items

        Raises:
            RuntimeError: If RCON command fails
        """
        cmd = self._rcon.build_command("pickup_entity", entity_name, position)
        response_dict = self._rcon.execute_and_parse_json(cmd)
        return EntityPickedUp.from_dict(response_dict)
