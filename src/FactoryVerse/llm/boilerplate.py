"""Runtime boilerplate code for agent sessions.

This script is intended to be read as a file and executed directly 
within the agent's Jupyter kernel.
"""
import os
import json
from factorio_rcon import RCONClient
from FactoryVerse.dsl.dsl import (
    walking,
    crafting,
    research,
    inventory,
    reachable,
    ghost_manager,
    configure,
    playing_factorio,
    map_db,
    enable_logging,
)
from FactoryVerse.dsl.types import MapPosition, Direction

# Setup RCON and agent
rcon_host = os.getenv("RCON_HOST", "localhost")
rcon_port = int(os.getenv("RCON_PORT", "27100"))
rcon_pwd = os.getenv("RCON_PWD", "factorio")
agent_udp_port = int(os.getenv("AGENT_UDP_PORT", "24389"))

# Connect to RCON
from FactoryVerse.utils.rcon_utils import create_rcon_client

rcon_client = create_rcon_client(rcon_host, rcon_port, rcon_pwd, initialize=True)
print(f"✅ RCON connected to {rcon_host}:{rcon_port}")

# Check for existing agents
agents_result = rcon_client.send_command(
    "/c local res = remote.call('agent', 'list_agents'); rcon.print(helpers.table_to_json(res))"
)
agents = json.loads(agents_result)

# Find or create agent
agent_name = "agent_1"
existing = next((a for a in agents if a.get("interface_name") == agent_name), None)

if existing:
    udp_port = existing.get('udp_port', agent_udp_port)
    print(f"✅ Reusing agent '{agent_name}' on UDP port {udp_port}")
else:
    rcon_client.send_command(
        f"/c local res = remote.call('agent', 'create_agent', {agent_udp_port}, true)"
    )
    udp_port = agent_udp_port
    print(f"✅ Created agent '{agent_name}' on UDP port {udp_port}")

# Configure DSL
configure(rcon_client, agent_name, agent_udp_port=udp_port)
print("✅ DSL configured")

# Map database loading code (Uses ipykernel's autoawait)
with playing_factorio():
    await map_db.load_snapshots()
    con = map_db.connection
    print(f"✅ Map database loaded. Connection: {con}")

print("\n💡 Tech/recipe info available in initial_state.md")
print("   Use research.enqueue('tech-name') to start researching!\n")


