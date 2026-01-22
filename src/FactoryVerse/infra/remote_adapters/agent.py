"""Agent remote interface adapter.

Wraps the fv_embodied_agent mod's "agent" remote interface for agent lifecycle management.

Lua API: remote.call("agent", method, ...)

Methods:
- create_agent: Create new agent character
- destroy_agents: Destroy agent(s)
- list_agents: List all agents
- list_agent_forces: Get agent-to-force mapping
- update_agent_friends: Set friendly forces
- update_agent_enemies: Set enemy forces
- reset_research: Reset research for a force
- inspect_research: Get research status for a force
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from .base import RemoteInterfaceAdapter, RCONClientProtocol

logger = logging.getLogger(__name__)


@dataclass
class AgentCreationResult:
    """Result from create_agent call."""

    agent_id: int
    force_name: str
    interface_name: str
    udp_port: int

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentCreationResult":
        return cls(
            agent_id=data.get("agent_id", 0),
            force_name=data.get("force_name", ""),
            interface_name=data.get("interface_name", ""),
            udp_port=data.get("udp_port", 0),
        )


@dataclass
class AgentInfo:
    """Information about an agent."""

    id: int
    interface_name: str
    force: str
    udp_port: int
    entity_valid: bool
    position: Optional[Dict[str, float]] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentInfo":
        return cls(
            id=data.get("id", 0),
            interface_name=data.get("interface_name", ""),
            force=data.get("force", ""),
            udp_port=data.get("udp_port", 0),
            entity_valid=data.get("entity_valid", False),
            position=data.get("position"),
        )


@dataclass
class ResearchInfo:
    """Research status for a force."""

    force_name: str
    current_research: Optional[str]
    queue_length: int

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResearchInfo":
        return cls(
            force_name=data.get("force_name", ""),
            current_research=data.get("current_research"),
            queue_length=data.get("queue_length", 0),
        )


class AgentInterface(RemoteInterfaceAdapter):
    """Adapter for the fv_embodied_agent "agent" remote interface.

    Handles agent lifecycle: creation, destruction, listing, force management.

    Usage:
        agent_api = AgentInterface(rcon)

        # Create agent with specific force
        result = agent_api.create_agent(udp_port=34202, force="cell_0")

        # Create agent with default player force
        result = agent_api.create_agent(udp_port=34202)

        # List all agents
        agents = agent_api.list_agents()

        # Destroy specific agents
        agent_api.destroy_agents([1, 2])

        # Destroy all agents
        agent_api.destroy_agents(0)
    """

    interface_name = "agent"

    def create_agent(
        self,
        udp_port: Optional[int] = None,
        set_unique_forces: bool = False,
        force: Optional[str] = None,
        initial_inventory: Optional[Dict[str, int]] = None,
    ) -> AgentCreationResult:
        """Create a new agent in Factorio.

        Args:
            udp_port: UDP port for agent notifications. If None, uses default (34202).
            set_unique_forces: If True, create unique force per agent (agent-{id}).
                              If False, use the force parameter or default to "player".
            force: Force name when set_unique_forces=False. Defaults to "player".
                   Use this to assign agent to scenario-specific forces (e.g., "cell_0").
            initial_inventory: Optional dict of {item_name: count} to give agent.

        Returns:
            AgentCreationResult with agent_id, force_name, interface_name, udp_port

        Example:
            # Create agent on player force (like a human player)
            result = agent_api.create_agent(udp_port=34202)

            # Create agent on cell-specific force (for lab-grid isolation)
            result = agent_api.create_agent(udp_port=34202, force="cell_0")
        """
        # Lua API: create_agent(udp_port, set_unique_forces, default_common_force, initial_inventory)
        default_force = force if force is not None else "player"

        result = self._call(
            "create_agent",
            udp_port,
            set_unique_forces,
            default_force,
            initial_inventory,
        )

        if result:
            logger.info(f"Created agent: {result}")
            return AgentCreationResult.from_dict(result)
        else:
            raise RuntimeError("Agent creation returned empty result")

    def destroy_agents(
        self,
        agent_refs: Union[int, List[int], str, List[str], None] = None,
        destroy_forces: bool = False,
    ) -> Dict[str, Any]:
        """Destroy agent(s).

        Args:
            agent_refs: Agent ID(s) or tag(s) to destroy. Can be:
                       - int: Single agent ID
                       - List[int]: Multiple agent IDs
                       - str: Single agent tag (e.g., "Agent-1")
                       - List[str]: Multiple agent tags
                       - 0: Destroy ALL agents
                       - None: Destroy all agents (same as 0)
            destroy_forces: If True, also destroy the agents' forces.

        Returns:
            Dict with destruction results
        """
        # Normalize to list or 0
        if agent_refs is None:
            refs = 0
        elif isinstance(agent_refs, (int, str)):
            refs = [agent_refs] if agent_refs != 0 else 0
        else:
            refs = list(agent_refs)

        result = self._call("destroy_agents", refs, destroy_forces)
        logger.info(f"Destroyed agents: {agent_refs}")
        return result or {}

    def list_agents(self) -> List[AgentInfo]:
        """List all agents in the game.

        Returns:
            List of AgentInfo with id, interface_name, force, udp_port, entity_valid
        """
        result = self._call("list_agents")
        if result and isinstance(result, list):
            return [AgentInfo.from_dict(a) for a in result]
        return []

    def list_agent_forces(self) -> Dict[int, str]:
        """Get mapping of agent IDs to their force names.

        Returns:
            Dict mapping agent_id (int) to force_name (str)
        """
        result = self._call("list_agent_forces")
        if result and isinstance(result, dict):
            # Convert string keys to int (JSON serialization converts int keys to strings)
            return {int(k): v for k, v in result.items()}
        return {}

    def update_agent_friends(self, agent_id: int, force_names: List[str]) -> None:
        """Set forces as friendly to an agent's force.

        Args:
            agent_id: Agent ID
            force_names: List of force names to set as friendly
        """
        self._call("update_agent_friends", agent_id, force_names, returns_json=False)
        logger.debug(f"Updated agent {agent_id} friends: {force_names}")

    def update_agent_enemies(self, agent_id: int, force_names: List[str]) -> None:
        """Set forces as enemies to an agent's force.

        Args:
            agent_id: Agent ID
            force_names: List of force names to set as enemies
        """
        self._call("update_agent_enemies", agent_id, force_names, returns_json=False)
        logger.debug(f"Updated agent {agent_id} enemies: {force_names}")

    def reset_research(self, force_name: str) -> Dict[str, Any]:
        """Reset research for a force.

        Args:
            force_name: Name of the force to reset research for

        Returns:
            Dict with success status
        """
        result = self._call("reset_research", force_name)
        logger.debug(f"Reset research for force: {force_name}")
        return result or {}

    def inspect_research(self, force_name: str) -> ResearchInfo:
        """Get research status for a force.

        Args:
            force_name: Name of the force to inspect

        Returns:
            ResearchInfo with current_research, queue_length
        """
        result = self._call("inspect_research", force_name)
        if result:
            return ResearchInfo.from_dict(result)
        return ResearchInfo(force_name=force_name, current_research=None, queue_length=0)
