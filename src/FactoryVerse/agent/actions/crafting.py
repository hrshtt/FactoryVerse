"""Crafting action implementation.

Handles all crafting-related operations with async support via RconHandler and AsyncActionListener.
"""

from typing import List, Optional, Dict, Any, TYPE_CHECKING
from dataclasses import dataclass
import logging

from FactoryVerse.agent.models import AsyncActionResponse, AsyncActionCompletion

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..infra.rcon_handler import RconHandler
    from ..infra.async_listener import AsyncActionListener
    from FactoryVerse.factory.item.base import ItemStack
    from FactoryVerse.agent.actions.place_entity import PlacementAction


@dataclass
class CraftingStarted(AsyncActionResponse):
    """Response when crafting action is queued/started.

    RCON Contract: RemoteInterface.lua craft_enqueue.returns.immediate

    Returned immediately when craft() is called. If queued=True, the action
    is running asynchronously and completion will come via UDP.
    """

    recipe: str = ""


@dataclass
class CraftingCompleted(AsyncActionCompletion):
    """Response when crafting action completes successfully.

    RCON Contract: RemoteInterface.lua craft_enqueue.returns.completion

    Received via UDP when crafting completes. Contains the actual items crafted.
    """

    items: Optional[Dict[str, int]] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CraftingCompleted":
        """Create instance from dict, mapping 'products' to 'items' for compatibility."""
        # Handle both 'products' (from Lua) and 'items' (preferred)
        if "products" in data and "items" not in data:
            data = {**data, "items": data["products"]}
        return super().from_dict(data)

    def __post_init__(self):
        if self.items is None:
            self.items = {}

    @property
    def has_items(self) -> bool:
        """True if any items were crafted."""
        return bool(self.items)

    def to_item_stacks(self, placement: Optional["PlacementAction"] = None) -> List["ItemStack"]:
        """Convert crafted items to ItemStack list with placement injected.
        
        Always returns a list of ItemStack objects, even if empty.
        
        Args:
            placement: PlacementAction to inject into items (required for .place() to work)
            
        Returns:
            List of ItemStack objects (never None, never empty dict, always a list)
        """
        from FactoryVerse.factory.item.create_item import create_item_stack
        
        stacks = []
        
        # Ensure items is a dict (handle None, empty dict, etc.)
        items = self.items or {}
        if not isinstance(items, dict):
            logger.warning(f"CraftingCompleted.items is not a dict: {type(items)}, defaulting to empty dict")
            items = {}
        
        # Convert each item to ItemStack
        for name, count in items.items():
            if not name or not isinstance(name, str):
                logger.warning(f"Skipping invalid item name: {name}")
                continue
            if not isinstance(count, (int, float)) or count <= 0:
                logger.warning(f"Skipping invalid item count for {name}: {count}")
                continue
                
            try:
                item_stack = create_item_stack(
                    name=name,
                    count=int(count),
                    placement=placement,
                    subgroup="intermediate-product",
                )
                stacks.append(item_stack)
            except Exception as e:
                logger.error(f"Failed to create ItemStack for {name} (count={count}): {e}")
                # Continue processing other items even if one fails
        
        return stacks


class CraftingAction:
    """Crafting action implementation.

    Owns all crafting logic:
    - craft(): Craft a recipe asynchronously (waits for completion)
    - enqueue(): Queue a recipe for crafting (returns immediately)
    - dequeue(): Cancel queued crafting
    - status(): Get current crafting status
    """

    def __init__(
        self,
        rcon_handler: "RconHandler",
        async_listener: "AsyncActionListener",
        placement: Optional["PlacementAction"] = None,
    ):
        """Initialize crafting action.

        Args:
            rcon_handler: RCON handler for command execution
            async_listener: Async listener for action completion
            placement: PlacementAction for item injection (optional for now)
        """
        self._rcon = rcon_handler
        self._listener = async_listener
        self._placement = placement

    async def craft(
        self, recipe: str, count: int = 1, timeout: Optional[int] = None
    ) -> List["ItemStack"]:
        """Craft a recipe asynchronously.

        Args:
            recipe: Recipe name to craft
            count: Number of times to craft
            timeout: Optional timeout in seconds

        Returns:
            List of ItemStack objects crafted with placement injected

        Raises:
            RuntimeError: If crafting fails to start or times out
        """
        # Build and execute RCON command
        cmd = self._rcon.build_command("craft_enqueue", recipe, count)
        response_dict = self._rcon.execute_and_parse_json(cmd)
        response = CraftingStarted.from_dict(response_dict)

        # Check if crafting started successfully
        if not response.is_queued:
            reason = response.reason or "unknown"
            raise RuntimeError(f"Failed to start crafting: {reason}")

        # Wait for completion via UDP
        completion_dict = await self._listener.await_action(response, timeout=timeout)
        completion = CraftingCompleted.from_dict(completion_dict)

        # Return items as ItemStack list
        # Always returns a list of ItemStack objects (never None, never empty dict)
        item_stacks = completion.to_item_stacks(self._placement)
        if not isinstance(item_stacks, list):
            logger.error(f"CraftingCompleted.to_item_stacks() returned non-list: {type(item_stacks)}, returning empty list")
            return []
        return item_stacks

    def enqueue(self, recipe: str, count: int = 1) -> Dict[str, Any]:
        """Enqueue a recipe for crafting.

        Args:
            recipe: Recipe name to craft
            count: Number of times to craft

        Returns:
            Response dict with queued status
        """
        cmd = self._rcon.build_command("craft_enqueue", recipe, count)
        return self._rcon.execute_and_parse_json(cmd)

    def dequeue(self, recipe: str, count: Optional[int] = None) -> Dict[str, Any]:
        """Cancel queued crafting.

        Args:
            recipe: Recipe name to cancel
            count: Number to cancel (None = all)

        Returns:
            Response dict with cancellation status
        """
        cmd = self._rcon.build_command("craft_dequeue", recipe, count)
        return self._rcon.execute_and_parse_json(cmd)

    def status(self) -> Dict[str, Any]:
        """Get current crafting status.

        Returns:
            Crafting state dict with active, recipe, action_id
        """
        cmd = self._rcon.build_command("inspect", True)  # attach_state=True
        state = self._rcon.execute_and_parse_json(cmd)
        return state.get("state", {}).get("crafting", {})
