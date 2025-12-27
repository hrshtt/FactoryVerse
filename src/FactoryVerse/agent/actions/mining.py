"""Mining action implementation with dataclass response types.

Handles all mining-related operations: mine resources, cancel mining.
"""

from dataclasses import dataclass
from typing import List, Optional, TYPE_CHECKING, Dict
import logging

from FactoryVerse.dsl.item.base import ItemStack
from FactoryVerse.dsl.types import MapPosition
from FactoryVerse.agent.models import (
    AsyncActionResponse,
    AsyncActionCompletion,
    ActionResponse,
)

if TYPE_CHECKING:
    from ..infra.rcon_handler import RconHandler
    from ..infra.async_listener import AsyncActionListener

logger = logging.getLogger(__name__)


# =============================================================================
# ACTION RESPONSE TYPES
# =============================================================================


@dataclass
class MiningStarted(AsyncActionResponse):
    """Response when mining action is queued/started.

    RCON Contract: RemoteInterface.lua mine_resource.returns.immediate

    Returned immediately when mine() is called. If queued=True, the action
    is running asynchronously and completion will come via UDP.
    """

    entity_name: str = ""
    entity_position: Optional[Dict[str, float]] = None

    @property
    def resource_position(self) -> Optional[MapPosition]:
        """Get resource position as MapPosition."""
        if self.entity_position:
            return MapPosition(x=self.entity_position["x"], y=self.entity_position["y"])
        return None


@dataclass
class MiningCompleted(AsyncActionCompletion):
    """Response when mining action completes successfully.

    RCON Contract: RemoteInterface.lua mine_resource.returns.completion

    Received via UDP when mining completes. Contains the actual items obtained.
    """

    actual_products: Optional[Dict[str, int]] = None

    def __post_init__(self):
        if self.actual_products is None:
            self.actual_products = {}

    @property
    def has_products(self) -> bool:
        """True if any products were obtained."""
        return bool(self.actual_products)

    def to_item_stacks(self) -> List[ItemStack]:
        """Convert products to ItemStack list."""
        items = []
        for name, count in (self.actual_products or {}).items():
            items.append(ItemStack(name=name, count=count, subgroup="raw-resource"))
        return items


@dataclass
class MiningCancelled(ActionResponse):
    """Response when mining action is cancelled.

    RCON Contract: RemoteInterface.lua stop_mining.returns

    Returned when stop_mining() is called or mining is interrupted.
    """

    action_id: Optional[str] = None
    items_obtained: Optional[Dict[str, int]] = None

    @property
    def was_active(self) -> bool:
        """True if there was an active mining action."""
        return self.action_id is not None


# =============================================================================
# MINING ACTION
# =============================================================================


class MiningAction:
    """Mining action implementation.

    Owns all mining logic:
    - mine(): Mine a resource with optional count limit
    - cancel(): Stop current mining operation

    All methods return structured dataclass response types for type safety.
    """

    def __init__(
        self, rcon_handler: "RconHandler", async_listener: "AsyncActionListener"
    ):
        """Initialize mining action.

        Args:
            rcon_handler: RCON handler for command execution
            async_listener: Async listener for action completion
        """
        self._rcon = rcon_handler
        self._listener = async_listener

    async def mine(
        self,
        resource_name: str,
        max_count: Optional[int] = None,
        position: Optional[MapPosition] = None,
        timeout: Optional[int] = None,
    ) -> List[ItemStack]:
        """Mine a resource.

        Args:
            resource_name: Resource prototype name (e.g., "iron-ore", "coal")
            max_count: Max items to mine (None = deplete resource)
            position: Optional position to mine at
            timeout: Optional timeout in seconds

        Returns:
            List of ItemStack objects obtained from mining

        Raises:
            RuntimeError: If mining fails to start or times out
        """
        # Enforce 25 limit for safety
        if max_count and max_count > 25:
            logger.warning(f"Capping mining count from {max_count} to 25")
            max_count = 25

        # Build and execute RCON command
        cmd = self._rcon.build_command(
            "mine_resource",
            resource_name,
            max_count,
            position,
        )
        response_dict = self._rcon.execute_and_parse_json(cmd)
        response = MiningStarted.from_dict(response_dict)

        # Check if mining started successfully
        if not response.is_queued:
            reason = response.reason or "unknown"
            raise RuntimeError(f"Failed to start mining: {reason}")

        # Wait for completion via UDP
        completion_dict = await self._listener.await_action(response, timeout=timeout)
        completion = MiningCompleted.from_dict(completion_dict)

        # Return items as ItemStack list
        return completion.to_item_stacks()

    def cancel(self) -> MiningCancelled:
        """Cancel current mining action.

        Returns:
            MiningCancelled response with cancellation status and any items obtained
        """
        cmd = self._rcon.build_command("stop_mining")
        response_dict = self._rcon.execute_and_parse_json(cmd)
        return MiningCancelled.from_dict(response_dict)
