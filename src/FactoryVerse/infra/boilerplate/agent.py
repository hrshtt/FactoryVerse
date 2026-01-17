"""Agent scope loader - Scope.AGENT

This module adds agent creation and entity filter synchronization.
Builds on SNAPSHOT scope.

Components loaded (in addition to SNAPSHOT):
    - agent_id: Agent interface name (e.g., 'agent_1')
    - udp_port: Agent's UDP port for notifications
    - entity_list: Filtered entity list synced to Lua mod

Usage:
    >>> from FactoryVerse.infra.llm.boilerplate import load, Scope
    >>> ctx = load(scope=Scope.AGENT, agent_id='agent_1')
    >>> print(f"Agent: {ctx['agent_id']} on UDP {ctx['udp_port']}")
"""

import os
import json
from typing import Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from . import BoilerplateContext


def load_agent_scope(
    ctx: "BoilerplateContext",
    agent_id: str = "agent_1",
    udp_port: Optional[int] = None,
) -> Dict[str, Any]:
    """Load agent scope components.

    Requires SNAPSHOT scope to be loaded first.

    Args:
        ctx: BoilerplateContext with SNAPSHOT scope loaded
        agent_id: Agent identifier (default: 'agent_1')
        udp_port: Explicit UDP port, auto-allocate if None

    Returns:
        Dict with: agent_id, udp_port, entity_list
    """
    from FactoryVerse.prototype_data import get_prototype_manager
    from FactoryVerse.utils.port_utils import find_free_udp_port

    rcon = ctx["rcon"]
    instance = ctx["instance"]
    config = ctx["config"]

    # Check for existing agents
    agents_result = rcon.send_command(
        "/c local res = remote.call('agent', 'list_agents'); rcon.print(helpers.table_to_json(res))"
    )
    agents = json.loads(agents_result)

    # Determine UDP port
    udp_port_override = os.getenv("FV_AGENT_UDP_PORT")
    if udp_port is not None:
        requested_udp_port = udp_port
    elif udp_port_override:
        requested_udp_port = int(udp_port_override)
    else:
        # Auto-allocate UDP port
        requested_udp_port = find_free_udp_port(
            start_port=config.agent_port_base,
            max_attempts=200,
            host=instance.rcon_host,
        )

    # Find or create agent
    existing = next((a for a in agents if a.get("interface_name") == agent_id), None)

    if existing:
        actual_udp_port = existing.get("udp_port", requested_udp_port)
    else:
        # Create agent with initial inventory
        # Args: udp_port, set_global_pos (bool), set_unique_forces (bool), force_name, initial_inventory
        # set_unique_forces=false ensures agent uses the 'player' force
        rcon.send_command(
            f'/c local inv = {{["burner-mining-drill"] = 1, ["stone-furnace"] = 1, ["wood"] = 1}}; '
            f"local res = remote.call('agent', 'create_agent', {requested_udp_port}, true, false, \"player\", inv); "
            f"rcon.print(helpers.table_to_json(res))"
        )
        actual_udp_port = requested_udp_port

    # Sync entity filter to Lua mod
    manager = get_prototype_manager()
    entity_list = manager.get_filtered_entities()

    entity_list_lua = "{" + ", ".join(f'"{e}"' for e in entity_list) + "}"
    rcon.send_command(
        f"/c remote.call('entities', 'set_entity_filter', {entity_list_lua})"
    )

    return {
        "agent_id": agent_id,
        "udp_port": actual_udp_port,
        "entity_list": entity_list,
    }


# For direct execution/testing
if __name__ == "__main__":
    from .rcon import load_rcon_scope
    from .snapshot import load_snapshot_scope
    from . import BoilerplateContext, Scope

    # Load prerequisites
    ctx = BoilerplateContext(Scope.AGENT)
    ctx.update(load_rcon_scope())
    ctx.update(load_snapshot_scope(ctx))

    # Then agent
    ctx.update(load_agent_scope(ctx))

    print("✅ Agent scope loaded")
    print(f"   Agent ID: {ctx['agent_id']}")
    print(f"   UDP Port: {ctx['udp_port']}")
    print(f"   Entity filter: {len(ctx['entity_list'])} entities")
