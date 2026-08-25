"""Unified FactoryVerse session combining execution + domain.

FactoryVerseSession wraps the Environment module to provide a consistent
interface for agent runs. It bridges:
- Execution: WHERE code runs (Jupyter kernel or in-process via Environment)
- Domain: WHAT objects are available (Environment's tier4 runtime)

This is used by AgentService for agent orchestration.

For direct Environment usage, see FactoryVerse.environment module.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, List

from FactoryVerse.infra.execution.base import ExecutionEnvironment, ExecutionResult

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of code execution."""
    output: Optional[str] = None
    error: Optional[str] = None
    is_error: bool = False

    @classmethod
    def success(cls, output: str) -> "ExecutionResult":
        return cls(output=output, is_error=False)

    @classmethod
    def failure(cls, error: str) -> "ExecutionResult":
        return cls(error=error, is_error=True)


class FactoryVerseSession:
    """Unified session combining execution environment + domain context.

    This class wraps the Environment module to provide backward compatibility
    for AgentService and other consumers that expect the session abstraction.

    Example:
        from FactoryVerse.infra.session import FactoryVerseSession
        from FactoryVerse.infra.execution import JupyterExecutor

        # Create with Jupyter for full agent runs
        executor = JupyterExecutor("/path/to/notebook.ipynb")
        session = FactoryVerseSession(
            session_id="run_001",
            executor=executor,
            agent_id="agent_1"
        )

        await session.start()

        # Execute code with full domain available
        result = session.execute("print(walking)")

        await session.stop()
    """

    def __init__(
        self,
        session_id: str,
        executor: Optional[ExecutionEnvironment] = None,
        scope: Optional[int] = None,  # Deprecated, kept for compatibility
        instance: Optional[str] = None,
        agent_id: str = "agent_1",
        session_dir: Optional[Path] = None,
        udp_port: Optional[int] = None,
        **kwargs: Any,
    ):
        """Initialize a FactoryVerse session.

        Args:
            session_id: Unique identifier for this session
            executor: Execution environment (Jupyter or InProcess)
            scope: Deprecated - kept for backward compatibility
            instance: Factorio instance name (auto-detect if None)
            agent_id: Agent identifier
            session_dir: Directory for session artifacts
            udp_port: UDP port for notifications
            **kwargs: Additional args (ignored, for backward compat)
        """
        self.session_id = session_id
        self.executor = executor
        self._instance = instance
        self._agent_id = agent_id
        self._session_dir = session_dir
        self._udp_port = udp_port

        # Environment-based context
        self._env = None
        self._started = False

    @property
    def context(self) -> Any:
        """Get the environment context (for backward compatibility).

        Returns the tier4 runtime components as a dict-like object.
        """
        if not self._started or self._env is None:
            raise RuntimeError("Session not started. Call start() first.")

        # Return a compatibility wrapper
        return _ContextWrapper(self._env)

    async def start(self) -> None:
        """Start the session.

        Initializes the Environment and optionally the Jupyter executor.
        """
        if self._started:
            logger.warning(f"Session {self.session_id} already started")
            return

        logger.info(f"Starting session {self.session_id}")

        # Create and initialize Environment
        from FactoryVerse.environment import Environment, Tier
        from FactoryVerse.environment.config import (
            EnvironmentConfig,
            PythonConfig,
            RuntimeConfig,
            RuntimeVariant,
        )

        config = EnvironmentConfig(
            tier3=PythonConfig(
                instance=self._instance,
                agent_id=self._agent_id,
            ),
            tier4=RuntimeConfig(
                agent_id=self._agent_id,
                variant=RuntimeVariant.FULL,
            ),
        )

        self._env = Environment(config=config)
        await self._env.initialize(up_to=Tier.RUNTIME)

        # Start Jupyter executor if provided (for agent runs)
        if self.executor is not None:
            await self.executor.start()

            # Inject runtime setup into Jupyter kernel
            self._inject_runtime_setup()

        self._started = True
        logger.info(f"Session {self.session_id} started")

    def _inject_runtime_setup(self) -> None:
        """Inject runtime setup code into Jupyter kernel."""
        if self.executor is None or self._env is None:
            return

        # Generate setup code that imports from Environment's components
        setup_code = self._generate_setup_code()
        result = self.executor.execute(setup_code)

        if result.is_error:
            logger.error(f"Failed to inject runtime setup: {result.error}")
            raise RuntimeError(f"Runtime setup failed: {result.error}")

        logger.debug("Runtime setup injected into Jupyter kernel")

    def _generate_setup_code(self) -> str:
        """Generate Python code to set up the runtime namespace in Jupyter."""
        tier3 = self._env.tier3
        tier4 = self._env.tier4

        # Get instance and port info
        instance = tier3.instance if tier3 else "client"
        agent_id = self._agent_id

        return f'''
# FactoryVerse Runtime Setup (auto-generated)
import asyncio

# Core infrastructure
from FactoryVerse.environment.config import get_config
from FactoryVerse.infra.instance_manager import FactorioInstanceManager
from factorio_rcon import RCONClient

config = get_config()

# Get instance
instance_name = "{instance}"
if instance_name == "client":
    instance = FactorioInstanceManager.get_client(config)
elif instance_name.startswith("server_"):
    server_id = int(instance_name.split("_")[1])
    instance = FactorioInstanceManager.get_server(server_id, config)
else:
    instance = FactorioInstanceManager.get_active(require_single=True)

# RCON client
rcon_client = RCONClient(instance.rcon_host, instance.rcon_port, instance.rcon_password)
rcon_client.connect()

# Agent ID
agent_id = "{agent_id}"

# Database
from FactoryVerse.game.infra.duckdb import SnapshotLoader, FactorioDatabase
snapshot_loader = SnapshotLoader(instance.snapshot_dir)
database = FactorioDatabase()
database.load_from_snapshot(snapshot_loader.get_latest())

# Embodied actions
from FactoryVerse.game.agent.embodied_actions import (
    Walking,
    Crafting,
    Research,
    Inventory,
    PlaceEntity,
    EntityOperations,
    Resources,
)
from FactoryVerse.game.agent.infra.rcon_handler import RCONHandler
from FactoryVerse.game.agent.infra.async_listener import AsyncNotificationListener

rcon_handler = RCONHandler(rcon_client, agent_id)

# Calculate UDP port for agent
def _get_agent_port(agent_id: str, instance_name: str) -> int:
    agent_num = int(agent_id.split("_")[1]) if "_" in agent_id else 1
    if instance_name == "client":
        return config.get_agent_port_range(instance="client")[agent_num - 1]
    elif instance_name.startswith("server_"):
        server_id = int(instance_name.split("_")[1])
        return config.get_agent_port_range(server_index=server_id)[agent_num - 1]
    return 34202 + (agent_num - 1)

udp_port = _get_agent_port(agent_id, instance_name)
async_listener = AsyncNotificationListener(udp_port)
async_listener.start()

# Create action modules
walking = Walking(rcon_handler, database, async_listener)
crafting = Crafting(rcon_handler, database, async_listener)
research = Research(rcon_handler, database, async_listener)
inventory = Inventory(rcon_handler, database)
placement = PlaceEntity(rcon_handler, database)
entity_ops = EntityOperations(rcon_handler, database)
resources = Resources(rcon_handler, database)

# Views
from FactoryVerse.game.agent.reachable_view import ReachableView
from FactoryVerse.game.agent.remote_view import RemoteView

reachable_view = ReachableView(rcon_handler, database)
remote_view = RemoteView(database)

# PlacementHints and GhostBuilder
from FactoryVerse.game.agent.placement_hints import PlacementHints
from FactoryVerse.game.agent.ghost_builder import GhostBuilder

placement_hints = PlacementHints(rcon_handler, database)
ghost_builder = GhostBuilder(rcon_handler, database)

# VerifyView (live power/coverage confirmation)
from FactoryVerse.game.agent.verify_view import VerifyView

verify = VerifyView(rcon_handler)

# Common types (pre-imported for convenience)
from FactoryVerse.game.factory.types import MapPosition, Direction, BoundingBox  # noqa: F401
from FactoryVerse.game.agent.placement_hints import ConnectionType, GhostPlan  # noqa: F401
from FactoryVerse.game.factory.item.base import Item, PlaceableItem, ItemStack  # noqa: F401

print(f"✅ FactoryVerse runtime ready for agent {{agent_id}}")
print(f"   Instance: {{instance_name}}")
print(f"   UDP Port: {{udp_port}}")
'''

    async def stop(self) -> None:
        """Stop the session and cleanup.

        Stops the Environment and executor.
        """
        if not self._started:
            logger.warning(f"Session {self.session_id} not started")
            return

        logger.info(f"Stopping session {self.session_id}")

        # Stop executor first
        if self.executor is not None:
            await self.executor.stop()

        # Shutdown environment
        if self._env is not None:
            await self._env.shutdown()
            self._env = None

        self._started = False
        logger.info(f"Session {self.session_id} stopped")

    def is_running(self) -> bool:
        """Check if session is running."""
        if self.executor is not None:
            return self._started and self.executor.is_running()
        return self._started

    def execute(
        self, code: str, compress_output: bool = False, **kwargs
    ) -> ExecutionResult:
        """Execute code in session context.

        If a Jupyter executor is available, code runs there.
        Otherwise, uses Environment's in-process execution.

        Args:
            code: Python code to execute
            compress_output: Whether to compress large outputs
            **kwargs: Additional execution options

        Returns:
            ExecutionResult with output and status

        Raises:
            RuntimeError: If session not started
        """
        if not self._started:
            raise RuntimeError("Session not started. Call start() first.")

        if self.executor is not None:
            # Use Jupyter executor
            return self.executor.execute(code, compress_output=compress_output, **kwargs)
        else:
            # Use Environment's in-process execution
            import asyncio
            try:
                result = asyncio.get_event_loop().run_until_complete(
                    self._env.tier4.execute_code(code)
                )
                return ExecutionResult.success(result.get("stdout", "") or str(result.get("result", "")))
            except Exception as e:
                return ExecutionResult.failure(str(e))

    def execute_dsl(self, code: str, **kwargs) -> ExecutionResult:
        """Execute FactoryVerse DSL code.

        Convenience wrapper that always compresses output.

        Args:
            code: DSL code to execute
            **kwargs: Additional options

        Returns:
            ExecutionResult
        """
        return self.execute(code, compress_output=True, **kwargs)

    def execute_duckdb(self, query: str, **kwargs) -> ExecutionResult:
        """Execute DuckDB query against game state.

        Wraps query to use remote_view.query().

        Args:
            query: SQL query (DuckDB dialect)
            **kwargs: Additional options

        Returns:
            ExecutionResult with query results
        """
        wrapped = f"""result = remote_view.query('''{query}''')
for row in result:
    print(row)
"""
        return self.execute(wrapped, compress_output=True, **kwargs)

    def get_tool_definitions(self, mode: str = "autonomous") -> List[Dict[str, Any]]:
        """Return OpenAI-compatible tool definitions.

        Delegates to the single shared definition so this path can never
        describe the tools differently from the live tier6 adapter.

        Args:
            mode: 'assisted' or 'autonomous'
        """
        from FactoryVerse.environment.tool_definitions import (
            get_tool_definitions as _shared_tool_definitions,
        )

        return _shared_tool_definitions(mode=mode)

    async def reload(self, reload_lua: bool = False) -> None:
        """Reload the session (Python modules and optionally Lua).

        Args:
            reload_lua: If True, also trigger Factorio script reload
        """
        logger.info(f"Reloading session {self.session_id}")

        if self.executor is not None:
            # For Jupyter, execute reload code in kernel
            reload_code = self._get_reload_code(reload_lua)
            result = self.executor.execute(reload_code)
            if result.is_error:
                logger.error(f"Reload failed: {result.error}")
        else:
            # For in-process, reset Environment's tier4
            if self._env is not None:
                from FactoryVerse.environment import Tier
                await self._env.reset(from_tier=Tier.RUNTIME)
                await self._env.initialize(up_to=Tier.RUNTIME)

        if reload_lua and self._env and self._env.tier3:
            try:
                self._env.tier3.rcon.send_command(
                    "/c game.reload_script();game.print('Scripts reloaded');rcon.print('Scripts reloaded')"
                )
                logger.info("Lua scripts reloaded")
            except Exception as e:
                logger.warning(f"Failed to reload Lua: {e}")

        logger.info(f"Session {self.session_id} reloaded")

    def _get_reload_code(self, reload_lua: bool) -> str:
        """Generate code to reload modules in Jupyter."""
        return f"""
import importlib
import sys

# Modules to reload
_modules_to_reload = [
    'FactoryVerse.config',
    'FactoryVerse.infra.instance_manager',
    'FactoryVerse.agent.infra.rcon_handler',
    'FactoryVerse.agent.infra.async_listener',
    'FactoryVerse.agent.embodied_actions.walking',
    'FactoryVerse.agent.embodied_actions.mining',
    'FactoryVerse.agent.embodied_actions.crafting',
    'FactoryVerse.agent.embodied_actions.research',
    'FactoryVerse.agent.embodied_actions.inventory',
    'FactoryVerse.agent.embodied_actions.entity_operations',
    'FactoryVerse.agent.embodied_actions.place_entity',
    'FactoryVerse.agent.ghost_builder',
    'FactoryVerse.agent.placement_hints',
    'FactoryVerse.agent.reachable_view',
    'FactoryVerse.agent.remote_view',
    'FactoryVerse.agent.infra.snapshot',
    'FactoryVerse.factory.entity',
    'FactoryVerse.factory.item',
]

_reloaded = []
for _mod_name in _modules_to_reload:
    if _mod_name in sys.modules:
        try:
            importlib.reload(sys.modules[_mod_name])
            _reloaded.append(_mod_name)
        except Exception as e:
            print(f"Failed to reload {{_mod_name}}: {{e}}")

print(f"Reloaded {{len(_reloaded)}} modules")

{
            ""
            if not reload_lua
            else '''
try:
    if 'rcon_client' in globals():
        rcon_client.send_command("/c game.reload_script();game.print('Scripts reloaded');rcon.print('Scripts reloaded')")
        print("✅ Triggered Factorio script reload")
except Exception as e:
    print(f"⚠️ Could not reload Factorio scripts: {e}")
'''
        }
"""


class _ContextWrapper:
    """Wrapper to provide backward-compatible context access."""

    def __init__(self, env):
        self._env = env

    def __getitem__(self, key: str) -> Any:
        """Dict-like access for backward compatibility."""
        return getattr(self, key, None)

    @property
    def rcon(self):
        return self._env.tier3.rcon if self._env.tier3 else None

    @property
    def database(self):
        return self._env.tier4.database if self._env.tier4 else None

    @property
    def runtime(self):
        return self._env.tier4.embodied_actions if self._env.tier4 else None

    @property
    def walking(self):
        ea = self._env.tier4.embodied_actions if self._env.tier4 else None
        return ea.walking if ea else None

    @property
    def crafting(self):
        ea = self._env.tier4.embodied_actions if self._env.tier4 else None
        return ea.crafting if ea else None
