"""Remote interface adapters for Factorio mods.

Provides type-safe Python wrappers for Lua remote interfaces exposed by:
- fv_embodied_agent mod (agent, admin interfaces)
- fv_snapshot mod (map, snapshot interfaces)

Usage:
    from factorio_rcon import RCONClient
    from FactoryVerse.infra.remote_adapters import AgentInterface, AdminInterface, MapSnapshotInterface

    rcon = RCONClient("localhost", 27100, "factorio")

    # Agent lifecycle management
    agent_api = AgentInterface(rcon)
    result = agent_api.create_agent(udp_port=34202, force="cell_0")
    agents = agent_api.list_agents()

    # Testing utilities (inventory, tech)
    admin_api = AdminInterface(rcon)
    admin_api.add_items(agent_id=1, items={"iron-plate": 50})

    # Snapshot orchestration
    map_api = MapSnapshotInterface(rcon)
    status = map_api.get_snapshot_status()
"""

from .agent import AgentInterface
from .admin import AdminInterface
from .map_snapshot import MapSnapshotInterface

__all__ = [
    "AgentInterface",
    "AdminInterface",
    "MapSnapshotInterface",
]
