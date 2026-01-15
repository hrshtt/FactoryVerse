"""Runtime boilerplate code for agent sessions.

This script is intended to be read as a file and executed directly
within the agent's Jupyter kernel.

Uses the proper instance detection and configuration system to work
seamlessly with both local Factorio client and Docker servers.

Key env vars (all optional - will auto-detect if not set):
- FV_INSTANCE: 'client' or 'server_N' to select instance explicitly
- FV_AGENT_ID: Agent identifier (default: 'agent_1')
- FV_AGENT_UDP_PORT: Explicit UDP port (auto-allocates if not set)
- FV_SESSION_DIR: Session directory for artifacts (default: '.')
"""

import os
import json
from pathlib import Path

from FactoryVerse.config import FactoryVerseConfig, get_config
from FactoryVerse.infra.instance_manager import FactorioInstanceManager
from FactoryVerse.runtime import create_runtime
from FactoryVerse.factory.types import MapPosition, Direction  # noqa: F401
from FactoryVerse.agent.actions.placement_hints import ConnectionType  # noqa: F401
# =============================================================================
# Instance Detection (client vs server)
# =============================================================================

# Get global config and detect active Factorio instance
config = get_config()
instance = FactorioInstanceManager.from_env(config)

print(f"🎮 Detected Factorio instance: {instance.name}")
print(f"   RCON: {instance.rcon_host}:{instance.rcon_port}")
print(f"   Script-output: {instance.script_output_dir}")

# =============================================================================
# Agent Configuration
# =============================================================================

# Session dir for agent artifacts (notebooks, trajectories, etc.)
session_dir = Path(os.getenv("FV_SESSION_DIR", "."))
agent_id = os.getenv("FV_AGENT_ID", "agent_1")
udp_port_override = os.getenv("FV_AGENT_UDP_PORT")

# Ensure session directory exists
session_dir.mkdir(parents=True, exist_ok=True)

# DB path in session dir for persistence
db_path = session_dir / "map.duckdb"

# =============================================================================
# RCON Connection
# =============================================================================

from FactoryVerse.utils.rcon_utils import create_rcon_client  # noqa: E402

rcon_client = create_rcon_client(
    instance.rcon_host,
    instance.rcon_port,
    instance.rcon_password,
    initialize=True,
)
print(f"✅ RCON connected to {instance.rcon_host}:{instance.rcon_port}")

# =============================================================================
# Agent Creation/Reuse
# =============================================================================

# Check for existing agents in Factorio
agents_result = rcon_client.send_command(
    "/c local res = remote.call('agent', 'list_agents'); rcon.print(helpers.table_to_json(res))"
)
agents = json.loads(agents_result)

# Determine UDP port
if udp_port_override:
    requested_udp_port = int(udp_port_override)
else:
    # Auto-allocate UDP port
    from FactoryVerse.utils.port_utils import find_free_udp_port

    requested_udp_port = find_free_udp_port(
        start_port=config.agent_port_base, max_attempts=200, host=instance.rcon_host
    )

# Find or create agent with configured ID
existing = next((a for a in agents if a.get("interface_name") == agent_id), None)

if existing:
    actual_udp_port = existing.get("udp_port", requested_udp_port)
    print(f"✅ Reusing agent '{agent_id}' on UDP port {actual_udp_port}")
else:
    # Create agent with initial inventory: burner mining drill, stone furnace, and wood
    # set_unique_forces=false ensures agent uses the 'player' force, which is required
    # for entity status tracking (status dumps filter on force='player')
    rcon_client.send_command(
        f'/c local inv = {{["burner-mining-drill"] = 1, ["stone-furnace"] = 1, ["wood"] = 1}}; local res = remote.call(\'agent\', \'create_agent\', {requested_udp_port}, false, "player", inv); rcon.print(helpers.table_to_json(res))'
    )
    actual_udp_port = requested_udp_port
    print(f"✅ Created agent '{agent_id}' on UDP port {actual_udp_port}")

# =============================================================================
# Entity Filter Sync
# =============================================================================

from FactoryVerse.prototype_data import get_prototype_manager  # noqa: E402

# Get filtered entity list from shared prototype manager
manager = get_prototype_manager()
entity_list = manager.get_filtered_entities()

# Sync to Lua mod via remote call
entity_list_lua = "{" + ", ".join(f'"{e}"' for e in entity_list) + "}"
rcon_client.send_command(
    f"/c remote.call('entities', 'set_entity_filter', {entity_list_lua})"
)
print(f"✅ Synced {len(entity_list)} entities to Lua mod filter")

# =============================================================================
# Snapshot UDP Port Sync
# =============================================================================

# Configure the snapshot mod to send UDP updates to the correct port
# This ensures Lua mod UDP port matches what Python's UDP dispatcher listens on
snapshot_udp_port = config.get_snapshot_port(instance.name)
rcon_client.send_command(
    f"/c remote.call('snapshot', 'set_udp_port', {snapshot_udp_port})"
)
print(f"✅ Configured snapshot mod UDP port: {snapshot_udp_port}")

# =============================================================================
# Runtime Creation
# =============================================================================

# Use the detected instance's script-output directory for snapshots
# SnapshotLoader._normalize_path() will handle finding /factoryverse/snapshots
snapshot_dir = instance.script_output_dir

runtime = create_runtime(
    rcon_client=rcon_client,
    agent_id=agent_id,
    udp_port=actual_udp_port,
    snapshot_dir=snapshot_dir,
    db_path=db_path,
)

# Start the runtime (enables async listener, loads RemoteView data)
await runtime.start()  # noqa: E999  # type: ignore

print(f"✅ Runtime created")
print(f"   Instance: {instance.name}")
print(f"   Agent: {agent_id}")
print(f"   UDP Port: {actual_udp_port}")
print(f"   DB: {db_path}")
print(f"   Snapshots: {instance.snapshot_dir}")

# =============================================================================
# Convenience Accessors
# =============================================================================

# Make these available in the notebook namespace
walking = runtime.walking
crafting = runtime.crafting
research = runtime.research
inventory = runtime.inventory
reachable = runtime.reachable
resources = runtime.resources  # Alias for reachable (backward compatibility)
entity_ops = runtime.entity_ops
placement = runtime.placement
ghost_builder = runtime.ghost_builder
placement_hints = runtime.placement_hints
remote_view = runtime.remote_view

print("\n💡 Tech/recipe info available in initial_state.md")
print("   Use research.queue('tech-name') to start researching!")
print("\n📦 Available affordances:")
print("   reachable (unified entity & resource queries)")
print("   resources (alias for reachable, for backward compatibility)")
print("   walking, crafting, research, inventory")
print(
    "   ghost_builder (build ghost entities), remote_view (map-wide queries via DuckDB)"
)
print("\n⛏️  Mining: Get resources via 'reachable' then call .mine() on them")
print(
    "   Example: iron = reachable.get_resource('iron-ore'); await iron.mine(max_count=25)"
)
print(
    "   Or use: iron = resources.get_resource('iron-ore'); await iron.mine(max_count=25)"
)
print()
