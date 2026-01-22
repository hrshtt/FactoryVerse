"""Admin remote interface adapter.

Wraps the fv_embodied_agent mod's "admin" remote interface for testing utilities.

Lua API: remote.call("admin", method, ...)

Methods:
- add_items: Add items to agent inventory
- clear_inventory: Clear agent inventory
- unlock_technology: Research a technology
- set_crafting_speed: Set agent crafting speed multiplier
- get_agent_state: Get comprehensive agent state
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .base import RemoteInterfaceAdapter, RCONClientProtocol

logger = logging.getLogger(__name__)


@dataclass
class AgentState:
    """Comprehensive agent state for testing assertions."""

    agent_id: int
    position: Dict[str, float]
    force: str
    inventory: Dict[str, int]
    crafting_speed_modifier: float
    current_research: Optional[str]
    tick: int

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentState":
        return cls(
            agent_id=data.get("agent_id", 0),
            position=data.get("position", {"x": 0, "y": 0}),
            force=data.get("force", ""),
            inventory=data.get("inventory", {}),
            crafting_speed_modifier=data.get("crafting_speed_modifier", 0.0),
            current_research=data.get("current_research"),
            tick=data.get("tick", 0),
        )


@dataclass
class TechnologyUnlockResult:
    """Result from unlock_technology call."""

    success: bool
    technology: str
    unlocked_recipes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TechnologyUnlockResult":
        return cls(
            success=data.get("success", False),
            technology=data.get("technology", ""),
            unlocked_recipes=data.get("unlocked_recipes", []),
        )


class AdminInterface(RemoteInterfaceAdapter):
    """Adapter for the fv_embodied_agent "admin" remote interface.

    Provides testing utilities for inventory manipulation, technology unlocking,
    and agent state inspection. These are typically used in tests or debug scenarios.

    Note: This interface is only available when the admin API is enabled in
    Factorio settings (fv-embodied-agent-enable-admin-api).

    Usage:
        admin_api = AdminInterface(rcon)

        # Add items to agent inventory
        admin_api.add_items(agent_id=1, items={"iron-plate": 50, "copper-plate": 30})

        # Clear inventory
        admin_api.clear_inventory(agent_id=1)

        # Unlock technology
        result = admin_api.unlock_technology(agent_id=1, tech_name="automation")

        # Get agent state for assertions
        state = admin_api.get_agent_state(agent_id=1)
    """

    interface_name = "admin"

    def add_items(self, agent_id: int, items: Dict[str, int]) -> None:
        """Add items to an agent's inventory.

        Args:
            agent_id: Numeric agent ID (e.g., 1 for agent_1)
            items: Dict of {item_name: count} to add

        Example:
            admin_api.add_items(1, {"transport-belt": 50, "inserter": 20})
        """
        self._call("add_items", agent_id, items, returns_json=False)
        logger.debug(f"Added items to agent {agent_id}: {items}")

    def clear_inventory(self, agent_id: int) -> None:
        """Clear an agent's entire inventory.

        Args:
            agent_id: Numeric agent ID
        """
        self._call("clear_inventory", agent_id, returns_json=False)
        logger.debug(f"Cleared inventory for agent {agent_id}")

    def unlock_technology(self, agent_id: int, tech_name: str) -> TechnologyUnlockResult:
        """Research a technology for an agent's force.

        Args:
            agent_id: Numeric agent ID (technology is unlocked on agent's force)
            tech_name: Internal technology name (e.g., "automation", "logistics")

        Returns:
            TechnologyUnlockResult with success status and unlocked recipes
        """
        result = self._call("unlock_technology", agent_id, tech_name)
        if result:
            logger.info(f"Unlocked technology '{tech_name}' for agent {agent_id}")
            return TechnologyUnlockResult.from_dict(result)
        return TechnologyUnlockResult(success=False, technology=tech_name)

    def set_crafting_speed(self, agent_id: int, multiplier: float) -> Dict[str, Any]:
        """Set an agent's crafting speed multiplier.

        Args:
            agent_id: Numeric agent ID
            multiplier: Speed multiplier (1.0 = normal, 2.0 = 2x speed)

        Returns:
            Dict with success, speed, modifier, tick
        """
        result = self._call("set_crafting_speed", agent_id, multiplier)
        logger.debug(f"Set crafting speed for agent {agent_id} to {multiplier}x")
        return result or {}

    def get_agent_state(self, agent_id: int) -> AgentState:
        """Get comprehensive agent state for testing assertions.

        Args:
            agent_id: Numeric agent ID

        Returns:
            AgentState with position, force, inventory, crafting_speed, research, tick
        """
        result = self._call("get_agent_state", agent_id)
        if result:
            return AgentState.from_dict(result)
        raise RuntimeError(f"Failed to get state for agent {agent_id}")
