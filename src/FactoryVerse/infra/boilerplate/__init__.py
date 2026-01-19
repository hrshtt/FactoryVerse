"""Modular boilerplate for FactoryVerse runtime setup.

This module provides composable, scope-based loading of FactoryVerse infrastructure.
Each scope builds on lower scopes, allowing MCP and tests to load only what they need.

Scopes (cumulative):
    RCON     - RCON connection only (low-level Lua mod access)
    SNAPSHOT - + Snapshot loading, DuckDB database
    AGENT    - + Agent creation, entity filter sync
    RUNTIME  - + Full AgentRuntime with all affordances

Usage:
    # Load full runtime (default)
    ctx = load()
    runtime = ctx['runtime']

    # Load just RCON for testing Lua commands
    ctx = load(scope=Scope.RCON)
    rcon = ctx['rcon']

    # Load snapshot scope for testing DuckDB queries
    ctx = load(scope=Scope.SNAPSHOT, instance='server_0')
    db = ctx['database']

    # Session management for MCP
    session = create_session(scope=Scope.AGENT, session_id='dev_1')
    session.reload(reload_lua=True)
    session.close()
"""

from enum import IntEnum
from pathlib import Path
from typing import Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from FactoryVerse.runtime import AgentRuntime


class Scope(IntEnum):
    """Runtime scopes - each includes all lower scopes.

    Scopes define what infrastructure is loaded:
    - RCON: Just RCON connection for raw Lua mod access
    - SNAPSHOT: Add snapshot loading and DuckDB database
    - AGENT: Add agent creation and entity filter sync
    - RUNTIME: Full AgentRuntime with all affordances
    """

    RCON = 0
    SNAPSHOT = 1
    AGENT = 2
    RUNTIME = 3


class BoilerplateContext:
    """Container for loaded boilerplate components.

    Provides dict-like access to components with proper cleanup.
    """

    def __init__(self, scope: Scope):
        self.scope = scope
        self._components: Dict[str, Any] = {}
        self._started = False

    def __getitem__(self, key: str) -> Any:
        return self._components[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._components[key] = value

    def __contains__(self, key: str) -> bool:
        return key in self._components

    def get(self, key: str, default: Any = None) -> Any:
        return self._components.get(key, default)

    def update(self, data: Dict[str, Any]) -> None:
        self._components.update(data)

    def keys(self):
        return self._components.keys()

    @property
    def rcon(self):
        """RCON client (available at Scope.RCON+)."""
        return self._components.get("rcon")

    @property
    def instance(self):
        """FactorioInstance (available at Scope.RCON+)."""
        return self._components.get("instance")

    @property
    def database(self):
        """DuckDB connection (available at Scope.SNAPSHOT+)."""
        return self._components.get("database")

    @property
    def agent_id(self) -> Optional[str]:
        """Agent interface name (available at Scope.AGENT+)."""
        return self._components.get("agent_id")

    @property
    def runtime(self) -> Optional["AgentRuntime"]:
        """Full AgentRuntime (available at Scope.RUNTIME only)."""
        return self._components.get("runtime")

    async def start(self) -> None:
        """Start async components (runtime listener, etc.)."""
        if self._started:
            return

        runtime = self.runtime
        if runtime is not None:
            await runtime.start()

        self._started = True

    async def stop(self) -> None:
        """Stop and cleanup all components."""
        runtime = self.runtime
        if runtime is not None and self._started:
            await runtime.stop()

        # Stop global UDP dispatcher to release port
        from FactoryVerse.infra.udp_dispatcher import stop_global_dispatcher
        await stop_global_dispatcher()

        # Close database connection if present
        database = self.database
        if database is not None:
            try:
                database.close()
            except Exception:
                pass

        rcon = self.rcon
        if rcon is not None:
            try:
                rcon.disconnect()
            except Exception:
                pass

        self._started = False


def load(
    scope: Scope = Scope.RUNTIME,
    instance: Optional[str] = None,
    agent_id: str = "agent_1",
    session_dir: Optional[Path] = None,
    create_agent: bool = True,
    udp_port: Optional[int] = None,
) -> BoilerplateContext:
    """Load boilerplate components up to specified scope.

    Args:
        scope: Which scope to load (cumulative)
        instance: Instance name ('client' or 'server_N'), auto-detect if None
        agent_id: Agent identifier for Scope.AGENT+
        session_dir: Session directory for artifacts
        create_agent: Whether to create agent (Scope.AGENT+)
        udp_port: Explicit UDP port, auto-allocate if None

    Returns:
        BoilerplateContext with loaded components

    Example:
        >>> ctx = load(scope=Scope.RCON)
        >>> ctx.rcon.send_command('/c print("hello")')

        >>> ctx = load(scope=Scope.RUNTIME)
        >>> await ctx.start()
        >>> await ctx.runtime.walking.walk_to(MapPosition(10, 10))
    """
    from .rcon import load_rcon_scope
    from .snapshot import load_snapshot_scope
    from .agent import load_agent_scope
    from .runtime import load_runtime_scope

    ctx = BoilerplateContext(scope)

    # Scope 0: RCON
    ctx.update(load_rcon_scope(instance=instance))
    if scope == Scope.RCON:
        return ctx

    # Scope 1: SNAPSHOT
    ctx.update(load_snapshot_scope(ctx, session_dir=session_dir))
    if scope == Scope.SNAPSHOT:
        return ctx

    # Scope 2: AGENT
    if create_agent:
        ctx.update(load_agent_scope(ctx, agent_id=agent_id, udp_port=udp_port))
    if scope == Scope.AGENT:
        return ctx

    # Scope 3: RUNTIME
    ctx.update(load_runtime_scope(ctx))
    return ctx


# Session management for MCP
class Session:
    """Managed boilerplate session for MCP and testing.

    Provides lifecycle management, reload capability, and cleanup.
    """

    def __init__(
        self,
        session_id: str,
        scope: Scope = Scope.RUNTIME,
        instance: Optional[str] = None,
        agent_id: str = "agent_1",
        session_dir: Optional[Path] = None,
        udp_port: Optional[int] = None,
    ):
        self.session_id = session_id
        self.scope = scope
        self.instance = instance
        self.agent_id = agent_id
        self.session_dir = session_dir
        self.udp_port = udp_port
        self._ctx: Optional[BoilerplateContext] = None

    @property
    def ctx(self) -> BoilerplateContext:
        """Get or create the boilerplate context."""
        if self._ctx is None:
            self._ctx = load(
                scope=self.scope,
                instance=self.instance,
                agent_id=self.agent_id,
                session_dir=self.session_dir,
                udp_port=self.udp_port,
            )
        return self._ctx

    async def start(self) -> None:
        """Start the session (load boilerplate and start async components)."""
        await self.ctx.start()

    async def reload(self, reload_lua: bool = False) -> None:
        """Reload the session.

        Args:
            reload_lua: If True, also trigger Factorio script reload via RCON
        """
        # Stop old context
        if self._ctx is not None:
            await self._ctx.stop()

        # Optionally reload Lua
        if reload_lua and self._ctx is not None:
            rcon = self._ctx.rcon
            if rcon is not None:
                try:
                    rcon.send_command(
                        "/c game.reload_script();game.print('Scripts reloaded')"
                    )
                except Exception:
                    pass

        # Reload Python modules
        self._reload_modules()

        # Recreate context
        self._ctx = None
        await self.start()

    def _reload_modules(self) -> None:
        """Reload FactoryVerse Python modules."""
        import importlib
        import sys

        modules_to_reload = [
            "FactoryVerse.config",
            "FactoryVerse.infra.instance_manager",
            "FactoryVerse.runtime",
            "FactoryVerse.agent.embodied_actions.walking",
            "FactoryVerse.agent.embodied_actions.mining",
            "FactoryVerse.agent.embodied_actions.crafting",
            "FactoryVerse.agent.embodied_actions.research",
            "FactoryVerse.agent.embodied_actions.inventory",
            "FactoryVerse.agent.embodied_actions.entity_operations",
            "FactoryVerse.agent.embodied_actions.place_entity",
            "FactoryVerse.agent.ghost_builder",
            "FactoryVerse.agent.placement_hints",
            "FactoryVerse.agent.reachable_view",
            "FactoryVerse.agent.infra.snapshot",
        ]

        for mod_name in modules_to_reload:
            if mod_name in sys.modules:
                try:
                    importlib.reload(sys.modules[mod_name])
                except Exception:
                    pass

    async def close(self) -> None:
        """Close the session and cleanup resources."""
        if self._ctx is not None:
            await self._ctx.stop()
            self._ctx = None


# Session registry for MCP
_sessions: Dict[str, Session] = {}


def create_session(
    session_id: str,
    scope: Scope = Scope.RUNTIME,
    instance: Optional[str] = None,
    agent_id: str = "agent_1",
    session_dir: Optional[Path] = None,
    udp_port: Optional[int] = None,
) -> Session:
    """Create a new managed session.

    Args:
        session_id: Unique identifier for the session
        scope: Which scope to load
        instance: Instance name ('client' or 'server_N')
        agent_id: Agent identifier
        session_dir: Session directory for artifacts
        udp_port: Explicit UDP port, auto-allocate if None

    Returns:
        Session object

    Raises:
        ValueError: If session_id already exists
    """
    if session_id in _sessions:
        raise ValueError(f"Session '{session_id}' already exists")

    session = Session(
        session_id=session_id,
        scope=scope,
        instance=instance,
        agent_id=agent_id,
        session_dir=session_dir,
        udp_port=udp_port,
    )
    _sessions[session_id] = session
    return session


def get_session(session_id: str) -> Optional[Session]:
    """Get an existing session by ID."""
    return _sessions.get(session_id)


def list_sessions() -> Dict[str, Session]:
    """List all active sessions."""
    return dict(_sessions)


async def destroy_session(session_id: str) -> bool:
    """Destroy a session and cleanup resources.

    Returns:
        True if session was destroyed, False if not found
    """
    session = _sessions.pop(session_id, None)
    if session is not None:
        await session.close()
        return True
    return False


async def destroy_all_sessions() -> int:
    """Destroy all active sessions.

    Returns:
        Number of sessions destroyed
    """
    count = len(_sessions)
    for session in list(_sessions.values()):
        await session.close()
    _sessions.clear()
    return count


def get_runtime_script(
    instance: Optional[str] = None,
    agent_id: str = "agent_1",
    session_dir: Optional[str] = None,
    udp_port: Optional[int] = None,
) -> str:
    """Generate the boilerplate script for Jupyter kernel execution.

    This function generates a Python script that can be executed in a
    Jupyter kernel to set up the full FactoryVerse runtime environment.

    Args:
        instance: Instance name ('client' or 'server_N'), auto-detect if None
        agent_id: Agent identifier
        session_dir: Session directory path as string
        udp_port: Explicit UDP port, auto-allocate if None

    Returns:
        Python script as a string

    Example:
        >>> script = get_runtime_script(agent_id="my_agent")
        >>> executor.execute(script)
    """
    # Build environment setup
    env_lines = []
    if instance:
        env_lines.append(f"os.environ['FV_INSTANCE'] = '{instance}'")
    if agent_id != "agent_1":
        env_lines.append(f"os.environ['FV_AGENT_ID'] = '{agent_id}'")
    if session_dir:
        env_lines.append(f"os.environ['FV_SESSION_DIR'] = '{session_dir}'")
    if udp_port:
        env_lines.append(f"os.environ['FV_AGENT_UDP_PORT'] = '{udp_port}'")

    env_setup = "\n".join(env_lines) if env_lines else "# Using default environment"

    return f'''"""FactoryVerse Runtime Boilerplate (generated)"""

import os
import json
from pathlib import Path

# Environment configuration
{env_setup}

from FactoryVerse.config import FactoryVerseConfig, get_config
from FactoryVerse.infra.instance_manager import FactorioInstanceManager
from FactoryVerse.runtime import create_runtime
from FactoryVerse.factory.types import MapPosition, Direction  # noqa: F401
from FactoryVerse.agent.placement_hints import ConnectionType  # noqa: F401

# =============================================================================
# Instance Detection (client vs server)
# =============================================================================

config = get_config()
instance = FactorioInstanceManager.from_env(config)

print(f"🎮 Detected Factorio instance: {{instance.name}}")
print(f"   RCON: {{instance.rcon_host}}:{{instance.rcon_port}}")
print(f"   Script-output: {{instance.script_output_dir}}")

# =============================================================================
# Agent Configuration
# =============================================================================

session_dir = Path(os.getenv("FV_SESSION_DIR", "."))
agent_id = os.getenv("FV_AGENT_ID", "agent_1")
udp_port_override = os.getenv("FV_AGENT_UDP_PORT")

session_dir.mkdir(parents=True, exist_ok=True)
db_path = session_dir / "map.duckdb"

# =============================================================================
# RCON Connection
# =============================================================================

from FactoryVerse.utils.rcon_utils import create_rcon_client

rcon_client = create_rcon_client(
    instance.rcon_host,
    instance.rcon_port,
    instance.rcon_password,
    initialize=True,
)
print(f"✅ RCON connected to {{instance.rcon_host}}:{{instance.rcon_port}}")

# =============================================================================
# Agent Creation/Reuse
# =============================================================================

agents_result = rcon_client.send_command(
    "/c local res = remote.call('agent', 'list_agents'); rcon.print(helpers.table_to_json(res))"
)
agents = json.loads(agents_result)

if udp_port_override:
    requested_udp_port = int(udp_port_override)
else:
    from FactoryVerse.utils.port_utils import find_free_udp_port
    requested_udp_port = find_free_udp_port(
        start_port=config.agent_port_base, max_attempts=200, host=instance.rcon_host
    )

existing = next((a for a in agents if a.get("interface_name") == agent_id), None)

if existing:
    actual_udp_port = existing.get("udp_port", requested_udp_port)
    print(f"✅ Reusing agent '{{agent_id}}' on UDP port {{actual_udp_port}}")
else:
    # Create agent with starter inventory using string building (avoids f-string brace issues)
    lua_inv_str = '{{{{["burner-mining-drill"] = 1, ["stone-furnace"] = 1, ["wood"] = 1}}}}'
    create_cmd = '/c local inv = ' + lua_inv_str + '; local res = remote.call("agent", "create_agent", ' + str(requested_udp_port) + ', false, "player", inv); rcon.print(helpers.table_to_json(res))'
    rcon_client.send_command(create_cmd)
    actual_udp_port = requested_udp_port
    print(f"✅ Created agent '{{agent_id}}' on UDP port {{actual_udp_port}}")

# =============================================================================
# Entity Filter Sync
# =============================================================================

from FactoryVerse.prototype_data import get_prototype_manager

manager = get_prototype_manager()
entity_list = manager.get_filtered_entities()
# Build Lua table manually using string operations (avoid f-string issues with braces)
entity_quotes = ['"' + e + '"' for e in entity_list]
entity_list_lua = '{{{{' + ', '.join(entity_quotes) + '}}}}'
filter_cmd = "/c remote.call('entities', 'set_entity_filter', " + entity_list_lua + ")"
rcon_client.send_command(filter_cmd)
print(f"✅ Synced {{len(entity_list)}} entities to Lua mod filter")

# =============================================================================
# Snapshot UDP Port Sync
# =============================================================================

snapshot_udp_port = config.get_snapshot_port(instance.name)
rcon_client.send_command(f"/c remote.call('snapshot', 'set_udp_port', {{snapshot_udp_port}})")
print(f"✅ Configured snapshot mod UDP port: {{snapshot_udp_port}}")

# =============================================================================
# Runtime Creation
# =============================================================================

snapshot_dir = instance.script_output_dir

runtime = create_runtime(
    rcon_client=rcon_client,
    agent_id=agent_id,
    udp_port=actual_udp_port,
    snapshot_dir=snapshot_dir,
    db_path=db_path,
)

await runtime.start()

print(f"✅ Runtime created")
print(f"   Instance: {{instance.name}}")
print(f"   Agent: {{agent_id}}")
print(f"   UDP Port: {{actual_udp_port}}")
print(f"   DB: {{db_path}}")
print(f"   Snapshots: {{instance.snapshot_dir}}")

# =============================================================================
# Convenience Accessors
# =============================================================================

walking = runtime.walking
crafting = runtime.crafting
research = runtime.research
inventory = runtime.inventory
reachable_view = runtime.reachable_view
resources = runtime.resources
entity_ops = runtime.entity_ops
placement = runtime.placement
ghost_builder = runtime.ghost_builder
placement_hints = runtime.placement_hints
remote_view = runtime.remote_view

print("\\n💡 Tech/recipe info available in initial_state.md")
print("   Use research.queue('tech-name') to start researching!")
print("\\n📦 Available affordances:")
print("   reachable_view (unified entity & resource queries)")
print("   resources (alias for reachable_view)")
print("   walking, crafting, research, inventory")
print("   ghost_builder, remote_view (map-wide queries via DuckDB)")
print("\\n⛏️  Mining: Get resources via 'reachable_view' then call .mine() on them")
print("   Example: iron = reachable_view.get_resource('iron-ore'); await iron.mine(max_count=25)")
print()
'''


__all__ = [
    "Scope",
    "BoilerplateContext",
    "load",
    "Session",
    "create_session",
    "get_session",
    "list_sessions",
    "destroy_session",
    "destroy_all_sessions",
    "get_runtime_script",
]
