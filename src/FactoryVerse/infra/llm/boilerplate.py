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

from FactoryVerse.config import get_config
from FactoryVerse.infra.instance_manager import FactorioInstanceManager
from FactoryVerse.runtime import create_runtime
from FactoryVerse.factory.types import MapPosition, Direction  # noqa: F401
from FactoryVerse.agent.placement_hints import ConnectionType  # noqa: F401
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

# =============================================================================
# Agent Creation/Reuse (with Profile Reconciliation)
# =============================================================================


# Define reconciliation logic helper
def reconcile_agent(agent_id, instance_name, requested_port):
    """
    Reconcile agent identity using AgentRegistry (filesystem) and Lua state.
    Matches logic in Tier4Runtime._reconcile_and_create_agent.
    """
    from pathlib import Path
    import json
    import uuid
    from datetime import datetime

    # 1. Check Registry (Filesystem)
    try:
        # Access fv_output_dir directly from FactoryVerseConfig
        registry_dir = config.fv_output_dir / "agents"
        registry_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Fallback if config structure differs
        registry_dir = Path(".fv-output/agents")
        registry_dir.mkdir(parents=True, exist_ok=True)

    profile_path = None
    profile_data = None

    # Scan for profile by name
    for p in registry_dir.glob("*.json"):
        try:
            data = json.loads(p.read_text())
            if data.get("name") == agent_id:
                profile_path = p
                profile_data = data
                break
        except Exception:
            continue

    # Check Lua state - verification only, logic is handled by try-create

    if profile_data:
        # Case 2: Resume (Profile Exists)
        print(f"✅ Found persistent profile for '{agent_id}' ({profile_data['id']})")

        # Verify/Create Entity (Bind) w/ destroy_existing=False
        rcon_client.send_command(
            f"/c local res = remote.call('agent', 'create_agent', {requested_port}, false); rcon.print(helpers.table_to_json(res))"
        )

        # Update Profile
        profile_data["status"] = "active"
        profile_data["updated_at"] = datetime.now().isoformat()
        if profile_path:
            profile_path.write_text(json.dumps(profile_data, indent=2))

    else:
        # Case 1: New (Spawn)
        print(f"✨ Creating NEW persistent profile for '{agent_id}'")

        # Create Entity (Destroy potential orphan)
        # initial inventory: burner mining drill, stone furnace, and wood
        inv_str = '{["burner-mining-drill"] = 1, ["stone-furnace"] = 1, ["wood"] = 1}'
        rcon_client.send_command(
            f"/c local inv = {inv_str}; local res = remote.call('agent', 'create_agent', {requested_port}, true, 'player', inv); rcon.print(helpers.table_to_json(res))"
        )

        # Register Profile
        new_id = str(uuid.uuid4())
        profile_data = {
            "id": new_id,
            "name": agent_id,
            "description": "Created via Boilerplate",
            "instance_id": instance_name,
            "model": "unknown",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "status": "active",
            "stats": {},
            "metadata": {"source": "boilerplate"},
        }
        (registry_dir / f"{new_id}.json").write_text(json.dumps(profile_data, indent=2))

    return requested_port


# Determine UDP port first
if udp_port_override:
    requested_udp_port = int(udp_port_override)
else:
    from FactoryVerse.utils.port_utils import find_free_udp_port

    requested_udp_port = find_free_udp_port(
        start_port=config.agent_port_base, max_attempts=200, host=instance.rcon_host
    )

# Run reconciliation
actual_udp_port = reconcile_agent(agent_id, instance.name, requested_udp_port)
print(f"✅ Agent '{agent_id}' ready on port {actual_udp_port}")

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
reachable_view = runtime.reachable_view
resources = runtime.resources  # Alias for reachable_view (backward compatibility)
entity_ops = runtime.entity_ops
placement = runtime.placement
ghost_builder = runtime.ghost_builder
placement_hints = runtime.placement_hints
remote_view = runtime.remote_view

print("\n💡 Tech/recipe info available in initial_state.md")
print("   Use research.queue('tech-name') to start researching!")
print("\n📦 Available affordances:")
print("   reachable_view (unified entity & resource queries)")
print("   resources (alias for reachable_view, for backward compatibility)")
print("   walking, crafting, research, inventory")
print(
    "   ghost_builder (build ghost entities), remote_view (map-wide queries via DuckDB)"
)
print("\n⛏️  Mining: Get resources via 'reachable_view' then call .mine() on them")
print(
    "   Example: iron = reachable_view.get_resource('iron-ore'); await iron.mine(max_count=25)"
)
print(
    "   Or use: iron = resources.get_resource('iron-ore'); await iron.mine(max_count=25)"
)
print()
