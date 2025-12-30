"""Example: Resource with DI pattern.

This shows how ResourceOrePatch will use injected MiningAction.
"""

from typing import List, Optional, TYPE_CHECKING
from FactoryVerse.factory.types import MapPosition

if TYPE_CHECKING:
    from FactoryVerse.agent.actions.mining import MiningAction
    from FactoryVerse.factory.item.base import ItemStack


class ResourceOrePatch:
    """Example resource class using DI pattern.

    This demonstrates how DSL resources will receive action instances
    via constructor injection instead of using ContextVar.
    """

    def __init__(
        self,
        name: str,
        position: MapPosition,
        amount: int,
        mining_action: "MiningAction",  # Injected dependency!
    ):
        """Initialize resource with injected mining action.

        Args:
            name: Resource name (e.g., "iron-ore")
            position: Resource position
            amount: Amount available
            mining_action: Injected MiningAction instance for this agent
        """
        self.name = name
        self.position = position
        self.amount = amount
        self._mining = mining_action  # Store injected dependency

    async def mine(self, max_count: Optional[int] = None) -> List["ItemStack"]:
        """Mine this resource.

        Delegates to injected MiningAction instance.

        Args:
            max_count: Max items to mine (None = deplete)

        Returns:
            List of items obtained
        """
        # Delegate to injected action - no ContextVar needed!
        return await self._mining.mine(resource_name=self.name, max_count=max_count)


# Example usage pattern (this will be in reachable.py):
def create_resource_example(mining_action: "MiningAction") -> ResourceOrePatch:
    """Factory function showing how resources are created with DI.

    In the real implementation, this will be in agent/actions/reachable.py
    and will create resources from DB/RCON data with injected actions.
    """
    return ResourceOrePatch(
        name="iron-ore",
        position=MapPosition(x=10.0, y=20.0),
        amount=1000,
        mining_action=mining_action,  # Inject the action!
    )
