"""Runtime boilerplate code for agent sessions.

This script is intended to be read as a file and executed directly 
within the agent's Jupyter kernel.
"""
import os
import json
from pathlib import Path
from factorio_rcon import RCONClient
from FactoryVerse.config import get_runtime_config
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

# Load per-agent runtime configuration
# Session dir and agent ID injected by agent runtime via env vars
session_dir = Path(os.getenv("FV_SESSION_DIR", "."))
agent_id = os.getenv("FV_AGENT_ID", "agent_1")
udp_port_override = os.getenv("FV_AGENT_UDP_PORT")  # Optional explicit port

# Create runtime config (auto-allocates UDP port if not overridden)
runtime_config = get_runtime_config(
    session_dir=session_dir,
    agent_id=agent_id,
    udp_port=int(udp_port_override) if udp_port_override else None
)

# Connect to RCON
from FactoryVerse.utils.rcon_utils import create_rcon_client

rcon_client = create_rcon_client(
    runtime_config.rcon_host,
    runtime_config.rcon_port,
    runtime_config.rcon_password,
    initialize=True
)
print(f"✅ RCON connected to {runtime_config.rcon_host}:{runtime_config.rcon_port}")

# Check for existing agents in Factorio
agents_result = rcon_client.send_command(
    "/c local res = remote.call('agent', 'list_agents'); rcon.print(helpers.table_to_json(res))"
)
agents = json.loads(agents_result)

# Find or create agent with configured ID
existing = next((a for a in agents if a.get("interface_name") == runtime_config.agent_id), None)

if existing:
    actual_udp_port = existing.get('udp_port', runtime_config.udp_port)
    print(f"✅ Reusing agent '{runtime_config.agent_id}' on UDP port {actual_udp_port}")
else:
    # Create agent with initial inventory: burner mining drill, stone furnace, and wood
    initial_inventory = '{["burner-mining-drill"] = 1, ["stone-furnace"] = 1, ["wood"] = 1}'
    rcon_client.send_command(
        f"/c local res = remote.call('agent', 'create_agent', {runtime_config.udp_port}, true, false, nil, {initial_inventory})"
    )
    actual_udp_port = runtime_config.udp_port
    print(f"✅ Created agent '{runtime_config.agent_id}' on UDP port {actual_udp_port}")

# Sync filters to Lua mod
from FactoryVerse.prototype_data import get_prototype_manager

# Get filtered entity list from shared prototype manager
manager = get_prototype_manager()
entity_list = manager.get_filtered_entities()

# Sync to Lua mod via remote call
entity_list_lua = "{" + ", ".join(f'"{e}"' for e in entity_list) + "}"
rcon_client.send_command(
    f"/c remote.call('entities', 'set_entity_filter', {entity_list_lua})"
)
print(f"✅ Synced {len(entity_list)} entities to Lua mod filter")

# Configure DSL
configure(
    rcon_client,
    runtime_config.agent_id,
    snapshot_dir=runtime_config.snapshot_dir,
    db_path=runtime_config.db_path,
    agent_udp_port=actual_udp_port
)
print(f"✅ DSL configured")
print(f"   Agent: {runtime_config.agent_id}")
print(f"   UDP Port: {actual_udp_port}")
print(f"   DB: {runtime_config.db_path}")
print(f"   Snapshots: {runtime_config.snapshot_dir}")

# Map database loading code (Uses ipykernel's autoawait)
with playing_factorio():
    await map_db.load_snapshots()  # noqa: E999  # type: ignore
    con = map_db.connection
    print(f"✅ Map database loaded. Connection: {con}")

print("\n💡 Tech/recipe info available in initial_state.md")
print("   Use research.enqueue('tech-name') to start researching!\n")


