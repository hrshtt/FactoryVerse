"""Unified FactoryVerse session combining execution + domain.

FactoryVerseSession is the central abstraction that bridges:
- Execution: WHERE code runs (Jupyter kernel or in-process)
- Domain: WHAT objects are available (boilerplate context)

This is the single abstraction for run_agent, MCP, and tests.
"""

import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, TYPE_CHECKING

from FactoryVerse.infra.execution.base import ExecutionEnvironment, ExecutionResult

# Avoid circular imports - use TYPE_CHECKING for type hints
if TYPE_CHECKING:
    from FactoryVerse.infra.boilerplate import BoilerplateContext, Scope

logger = logging.getLogger(__name__)


class FactoryVerseSession:
    """Unified session combining execution environment + domain context.

    This class bridges the gap between:
    - Execution layer: JupyterExecutor or InProcessExecutor
    - Domain layer: BoilerplateContext with RCON, database, runtime

    It provides a single interface that both run_agent.py and MCP can use
    to manage the lifecycle of a Factorio interaction session.

    Example:
        from FactoryVerse.infra.session import FactoryVerseSession
        from FactoryVerse.infra.execution import JupyterExecutor
        from FactoryVerse.infra.llm.boilerplate import Scope

        # Create with Jupyter for full agent runs
        executor = JupyterExecutor("/path/to/notebook.ipynb")
        session = FactoryVerseSession(
            session_id="run_001",
            executor=executor,
            scope=Scope.RUNTIME,
            agent_id="agent_1"
        )

        await session.start()

        # Execute code with full domain available
        result = session.execute("print(runtime.agent_id)")

        # Access domain objects
        runtime = session.context.runtime

        await session.stop()
    """

    def __init__(
        self,
        session_id: str,
        executor: ExecutionEnvironment,
        scope: Optional["Scope"] = None,
        instance: Optional[str] = None,
        agent_id: str = "agent_1",
        session_dir: Optional[Path] = None,
        udp_port: Optional[int] = None,
        **boilerplate_kwargs: Any,
    ):
        """Initialize a FactoryVerse session.

        Args:
            session_id: Unique identifier for this session
            executor: Execution environment (Jupyter or InProcess)
            scope: Domain scope to load (default: RUNTIME)
            instance: Factorio instance name (auto-detect if None)
            agent_id: Agent identifier
            session_dir: Directory for session artifacts
            udp_port: UDP port for notifications
            **boilerplate_kwargs: Additional args passed to boilerplate.load()
        """
        self.session_id = session_id
        self.executor = executor
        self._scope: Optional["Scope"] = scope
        self._instance = instance
        self._agent_id = agent_id
        self._session_dir = session_dir
        self._udp_port = udp_port
        self._boilerplate_kwargs = boilerplate_kwargs

        # Lazily loaded context
        self._ctx: Optional["BoilerplateContext"] = None
        self._started = False

    @property
    def scope(self) -> "Scope":
        """Get the domain scope."""
        if self._scope is None:
            # Import here to avoid circular imports
            from FactoryVerse.infra.boilerplate import Scope

            return Scope.RUNTIME
        return self._scope

    @property
    def context(self) -> "BoilerplateContext":
        """Get or create the boilerplate context.

        Lazily loads the domain context on first access.

        Returns:
            BoilerplateContext with loaded domain objects

        Raises:
            RuntimeError: If session not started
        """
        if not self._started:
            raise RuntimeError("Session not started. Call start() first.")

        if self._ctx is None:
            self._load_context()

        # At this point _ctx is guaranteed to be set by _load_context()
        assert self._ctx is not None
        return self._ctx

    def _load_context(self) -> None:
        """Load boilerplate context."""
        from FactoryVerse.infra.boilerplate import load

        self._ctx = load(
            scope=self.scope,
            instance=self._instance,
            agent_id=self._agent_id,
            session_dir=self._session_dir,
            udp_port=self._udp_port,
            **self._boilerplate_kwargs,
        )

    async def start(self) -> None:
        """Start the session.

        Starts the executor and loads the domain context.
        For JupyterExecutor, this also executes the boilerplate script.
        """
        if self._started:
            logger.warning(f"Session {self.session_id} already started")
            return

        logger.info(f"Starting session {self.session_id}")

        # Start executor
        await self.executor.start()

        # Load domain context
        # For JupyterExecutor, we need to execute boilerplate in the kernel
        # For InProcessExecutor, we can load directly
        from FactoryVerse.infra.execution.jupyter import JupyterExecutor

        if isinstance(self.executor, JupyterExecutor):
            # Execute boilerplate.py script in kernel
            self._execute_jupyter_boilerplate()
        else:
            # Load context directly
            self._load_context()
            # Start async components (context is guaranteed to exist after _load_context)
            if self._ctx is not None:
                await self._ctx.start()

        self._started = True
        logger.info(f"Session {self.session_id} started with scope {self.scope}")

    def _execute_jupyter_boilerplate(self) -> None:
        """Execute boilerplate script in Jupyter kernel."""
        from FactoryVerse.infra.boilerplate import get_runtime_script

        # Generate and execute boilerplate code
        boilerplate_code = get_runtime_script(
            instance=self._instance,
            agent_id=self._agent_id,
            session_dir=str(self._session_dir) if self._session_dir else None,
            udp_port=self._udp_port,
        )

        result = self.executor.execute(boilerplate_code)
        if result.is_error:
            raise RuntimeError(f"Failed to execute boilerplate: {result.error}")

        logger.debug("Boilerplate executed in Jupyter kernel")

    async def stop(self) -> None:
        """Stop the session and cleanup.

        Stops the domain context and executor.
        """
        if not self._started:
            logger.warning(f"Session {self.session_id} not started")
            return

        logger.info(f"Stopping session {self.session_id}")

        # Stop domain context (if loaded)
        if self._ctx is not None:
            await self._ctx.stop()
            self._ctx = None

        # Stop executor
        await self.executor.stop()

        self._started = False
        logger.info(f"Session {self.session_id} stopped")

    def is_running(self) -> bool:
        """Check if session is running."""
        return self._started and self.executor.is_running()

    def execute(
        self, code: str, compress_output: bool = False, **kwargs
    ) -> ExecutionResult:
        """Execute code in session context.

        Code runs in the execution environment with domain objects available.

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

        return self.executor.execute(code, compress_output=compress_output, **kwargs)

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
        """Get OpenAI-compatible tool definitions.

        Args:
            mode: 'assisted' or 'autonomous'

        Returns:
            List of tool definitions for LLM consumption
        """
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "execute_duckdb",
                    "description": "Execute SQL query against the FactoryVerse database to analyze map state.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "SQL query (DuckDB dialect)",
                            }
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "execute_dsl",
                    "description": "Execute Python code using FactoryVerse DSL. Code runs in ipykernel with autoawait - use 'await' directly for async functions. All objects (walking, reachable, inventory, etc.) are pre-loaded.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {
                                "type": "string",
                                "description": "Python code to execute",
                            }
                        },
                        "required": ["code"],
                    },
                },
            },
        ]

        if mode == "assisted":
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "respond",
                        "description": "Respond to the user with a text message.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "message": {
                                    "type": "string",
                                    "description": "Your message to the user",
                                }
                            },
                            "required": ["message"],
                        },
                    },
                }
            )

        return tools

    async def reload(self, reload_lua: bool = False) -> None:
        """Reload the session (Python modules and optionally Lua).

        Args:
            reload_lua: If True, also trigger Factorio script reload
        """
        logger.info(f"Reloading session {self.session_id}")

        # For Jupyter, we need to reload via kernel
        from FactoryVerse.infra.execution.jupyter import JupyterExecutor

        if isinstance(self.executor, JupyterExecutor):
            # Use FactoryVerseRuntime.reload_boilerplate logic
            reload_code = self._get_reload_code(reload_lua)
            result = self.executor.execute(reload_code)
            if result.is_error:
                logger.error(f"Reload failed: {result.error}")
        else:
            # For InProcess, we can reload directly via Session
            if self._ctx is not None:
                # Get existing session from boilerplate
                from FactoryVerse.infra.boilerplate import Session

                # Create temporary session for reload
                session = Session(
                    session_id=self.session_id,
                    scope=self.scope,
                    instance=self._instance,
                    agent_id=self._agent_id,
                    session_dir=self._session_dir,
                    udp_port=self._udp_port,
                )
                session._ctx = self._ctx
                await session.reload(reload_lua=reload_lua)
                self._ctx = session._ctx

        logger.info(f"Session {self.session_id} reloaded")

    def _get_reload_code(self, reload_lua: bool) -> str:
        """Generate code to reload boilerplate in Jupyter."""
        # This replicates FactoryVerseRuntime.reload_boilerplate logic
        return f"""
import importlib
import sys

# Modules to reload
_modules_to_reload = [
    'FactoryVerse.config',
    'FactoryVerse.infra.instance_manager',
    'FactoryVerse.runtime',
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
