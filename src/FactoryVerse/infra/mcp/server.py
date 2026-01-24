"""FactoryVerse MCP Server Implementation.

Provides MCP tools for:
- Infrastructure lifecycle (server/client start/stop)
- Instance management (list, status)
- Session management (create, execute, reload, destroy, status)
- Development utilities (run tests, reload scripts)
"""

import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from FactoryVerse.infra.output.error_parser import FactorioErrorParser, ErrorVerbosity

logger = logging.getLogger(__name__)

# Module-level error parser for consistent error formatting
_error_parser = FactorioErrorParser(
    verbosity=ErrorVerbosity.MODERATE,
    max_traceback_frames=3,
    show_internal_frames=False,
)


class FactoryVerseMCPServer:
    """MCP Server for FactoryVerse development and testing."""

    def __init__(self):
        self.server = Server("factoryverse")
        self._setup_tools()

    def _setup_tools(self):
        """Register MCP tools."""

        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            """List available MCP tools."""
            return [
                Tool(
                    name="factoryverse_run_test",
                    description="Run a pytest test file or specific test function. Returns test output.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "test_path": {
                                "type": "string",
                                "description": "Test file path (e.g., 'tests/actions/test_inventory.py') or specific test (e.g., 'tests/actions/test_inventory.py::TestCreateItemStacks::test_create_item_stacks_with_sufficient_items')",
                            },
                            "verbose": {
                                "type": "boolean",
                                "description": "Run with verbose output (-v flag)",
                                "default": True,
                            },
                            "capture": {
                                "type": "boolean",
                                "description": "Capture output (default: True)",
                                "default": True,
                            },
                        },
                        "required": ["test_path"],
                    },
                ),
                Tool(
                    name="factoryverse_execute_code",
                    description="Execute Python code in a FactoryVerse runtime context for debugging. Code runs in a Jupyter-like environment with FactoryVerse boilerplate loaded.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "code": {
                                "type": "string",
                                "description": "Python code to execute (can use async/await)",
                            },
                            "agent_id": {
                                "type": "string",
                                "description": "Agent ID to use (default: 'agent_1')",
                                "default": "agent_1",
                            },
                        },
                        "required": ["code"],
                    },
                ),
                Tool(
                    name="factoryverse_server_reload",
                    description="Reload Factorio Lua scripts via RCON. Useful after making changes to mod files.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "instance": {
                                "type": "string",
                                "description": "Factorio instance name (default: auto-detect)",
                                "default": None,
                            },
                        },
                    },
                ),
                Tool(
                    name="factoryverse_inspect_inventory",
                    description="Get current agent inventory state. Returns inventory contents as JSON.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "agent_id": {
                                "type": "string",
                                "description": "Agent ID to inspect (default: 'agent_1')",
                                "default": "agent_1",
                            },
                        },
                    },
                ),
                Tool(
                    name="factoryverse_add_inventory",
                    description="""Add items to an agent's inventory.

Useful for setting up test scenarios or providing items for development.
Uses the Lua mod's agent.add_items API.

Example: Add 50 transport belts and 20 inserters to agent_1""",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "agent_id": {
                                "type": "string",
                                "description": "Agent ID (e.g., 'agent_1'). Must be a registered agent interface.",
                                "default": "agent_1",
                            },
                            "items": {
                                "type": "object",
                                "description": "Items to add: {item_name: count, ...}. Example: {'transport-belt': 50, 'inserter': 20}",
                                "additionalProperties": {"type": "integer"},
                            },
                        },
                        "required": ["items"],
                    },
                ),
                # ============================================================
                # Session Management Tools
                # ============================================================
                Tool(
                    name="factoryverse_create_session",
                    description="""Create a FactoryVerse session at specified scope.

Scopes (cumulative - each includes lower scopes):
- RCON (0): Just RCON connection for low-level Lua mod access
- SNAPSHOT (1): + Snapshot loading and DuckDB database queries
- AGENT (2): + Agent creation and entity filter sync
- RUNTIME (3): Full runtime with all affordances (walking, crafting, etc.)

Use this to create isolated environments for testing specific layers.""",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "Unique identifier for the session",
                            },
                            "scope": {
                                "type": "integer",
                                "enum": [0, 1, 2, 3],
                                "description": "Scope level: 0=RCON, 1=SNAPSHOT, 2=AGENT, 3=RUNTIME",
                                "default": 3,
                            },
                            "variant": {
                                "type": "string",
                                "enum": ["minimal", "full"],
                                "description": "Runtime variant: 'minimal' (no database) or 'full' (with DuckDB). Default: minimal",
                                "default": "minimal",
                            },
                            "instance": {
                                "type": "string",
                                "description": "Factorio instance ('client' or 'server_N'). Auto-detect if not specified.",
                            },
                            "agent_id": {
                                "type": "string",
                                "description": "Agent identifier (default: 'agent_1')",
                                "default": "agent_1",
                            },
                            "initial_inventory": {
                                "type": "object",
                                "description": "Initial inventory items to give agent: {item_name: count, ...}. Example: {'transport-belt': 50, 'inserter': 20}",
                                "additionalProperties": {"type": "integer"},
                            },
                        },
                        "required": ["session_id"],
                    },
                ),
                Tool(
                    name="factoryverse_execute_in_session",
                    description="""Execute Python code in an existing session context.

The code has access to all components loaded at the session's scope:
- RCON: config, instance, rcon
- SNAPSHOT: + database, snapshot_loader
- AGENT: + agent_id, udp_port
- RUNTIME: + runtime, walking, crafting, inventory, etc.

For async code (with 'await'), wrap automatically handled.""",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "Session to execute in",
                            },
                            "code": {
                                "type": "string",
                                "description": "Python code to execute",
                            },
                            "timeout": {
                                "type": "number",
                                "description": "Execution timeout in seconds (default: 120)",
                                "default": 120,
                                "minimum": 1,
                                "maximum": 600,
                            },
                        },
                        "required": ["session_id", "code"],
                    },
                ),
                Tool(
                    name="factoryverse_session_status",
                    description="""Get detailed status of a session including tier information.

Returns the initialization state of each tier (PYTHON_INFRA, RUNTIME, etc.)
and available components.""",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "Session to get status for",
                            },
                        },
                        "required": ["session_id"],
                    },
                ),
                Tool(
                    name="factoryverse_reload_session",
                    description="""Reload a session to pick up code changes.

This will:
1. Stop the current runtime/connections
2. Reload Python modules
3. Optionally reload Factorio Lua scripts
4. Recreate the session with fresh state

Use after making changes to FactoryVerse Python code.""",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "Session to reload",
                            },
                            "reload_lua": {
                                "type": "boolean",
                                "description": "Also trigger Factorio script reload via RCON",
                                "default": False,
                            },
                        },
                        "required": ["session_id"],
                    },
                ),
                Tool(
                    name="factoryverse_destroy_session",
                    description="Destroy a session and cleanup resources (RCON, UDP listeners, etc.)",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "Session to destroy",
                            },
                        },
                        "required": ["session_id"],
                    },
                ),
                Tool(
                    name="factoryverse_list_sessions",
                    description="List all active sessions with their scope and instance info.",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                Tool(
                    name="factoryverse_reload_python",
                    description="""Hot-reload Python modules in the MCP server process.

Use this after editing FactoryVerse Python code to pick up changes without restarting the MCP server.

Default behavior reloads common development modules:
- FactoryVerse.agent.embodied_actions.* (walking, mining, crafting, etc.)
- FactoryVerse.agent.placement_hints, ghost_builder
- FactoryVerse.environment.*

Caveats:
- Existing object instances won't pick up new methods
- Destroy and recreate sessions after reload for clean state
- Use clear_all=True for a complete reset (may require session recreation)""",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "modules": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Specific module patterns to reload (e.g., 'FactoryVerse.agent.embodied_actions.*'). If not specified, reloads default development modules.",
                            },
                            "clear_all": {
                                "type": "boolean",
                                "description": "Clear ALL FactoryVerse modules from cache (nuclear option)",
                                "default": False,
                            },
                        },
                    },
                ),
                # ============================================================
                # Infrastructure Lifecycle Tools
                # ============================================================
                Tool(
                    name="factoryverse_server_start",
                    description="""Start Factorio Docker server(s).

Starts one or more Factorio servers in Docker containers with the specified scenario.
Waits for servers to be ready (RCON responsive) before returning.

Returns server info including ports and connection details.""",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "num_servers": {
                                "type": "integer",
                                "description": "Number of servers to start (default: 1)",
                                "default": 1,
                                "minimum": 1,
                                "maximum": 3,
                            },
                            "scenario": {
                                "type": "string",
                                "description": "Scenario to load (default: test-ground)",
                                "default": "test-ground",
                            },
                            "max_agents": {
                                "type": "integer",
                                "description": "Max agents per server (default: 10)",
                                "default": 10,
                            },
                            "no_jupyter": {
                                "type": "boolean",
                                "description": "Skip starting Jupyter notebook server",
                                "default": True,
                            },
                        },
                    },
                ),
                Tool(
                    name="factoryverse_server_stop",
                    description="Stop all Factorio Docker servers and associated services.",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                Tool(
                    name="factoryverse_server_restart",
                    description="Restart all Factorio Docker servers (preserves configuration).",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                Tool(
                    name="factoryverse_client_start",
                    description="""Start the local Factorio client.

Launches the Factorio client with specified scenario or save file.
The client must have FactoryVerse mods installed.""",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "scenario": {
                                "type": "string",
                                "description": "Scenario to load (e.g., 'test-ground', 'freeplay')",
                            },
                            "save_file": {
                                "type": "string",
                                "description": "Path to save file to load (overrides scenario)",
                            },
                            "new_map": {
                                "type": "boolean",
                                "description": "Create a new map instead of loading existing",
                                "default": False,
                            },
                        },
                    },
                ),
                Tool(
                    name="factoryverse_client_stop",
                    description="Stop the running Factorio client.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "force": {
                                "type": "boolean",
                                "description": "Force kill (SIGKILL instead of SIGTERM)",
                                "default": False,
                            },
                        },
                    },
                ),
                # ============================================================
                # Instance Management Tools
                # ============================================================
                Tool(
                    name="factoryverse_list_instances",
                    description="""List all Factorio instances and their status.

Returns information about all available instances (client + servers 0-2),
including whether they are currently active (RCON responsive).""",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                Tool(
                    name="factoryverse_instance_status",
                    description="""Get detailed status of a specific instance.

Returns connection info, game state, and current tick if available.""",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "instance": {
                                "type": "string",
                                "description": "Instance name: 'client' or 'server_N' (e.g., 'server_0')",
                            },
                        },
                        "required": ["instance"],
                    },
                ),
                # ============================================================
                # Utility Tools
                # ============================================================
                Tool(
                    name="factoryverse_list_scenarios",
                    description="List available scenarios that can be loaded.",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            """Handle tool calls."""
            try:
                if name == "factoryverse_run_test":
                    return await self._run_test(arguments)
                elif name == "factoryverse_execute_code":
                    return await self._execute_code(arguments)
                elif name == "factoryverse_server_reload":
                    return await self._reload_server(arguments)
                elif name == "factoryverse_inspect_inventory":
                    return await self._inspect_inventory(arguments)
                elif name == "factoryverse_add_inventory":
                    return await self._add_inventory(arguments)
                # Session management tools
                elif name == "factoryverse_create_session":
                    return await self._create_session(arguments)
                elif name == "factoryverse_execute_in_session":
                    return await self._execute_in_session(arguments)
                elif name == "factoryverse_session_status":
                    return await self._session_status(arguments)
                elif name == "factoryverse_reload_session":
                    return await self._reload_session(arguments)
                elif name == "factoryverse_destroy_session":
                    return await self._destroy_session(arguments)
                elif name == "factoryverse_list_sessions":
                    return await self._list_sessions(arguments)
                elif name == "factoryverse_reload_python":
                    return await self._reload_python(arguments)
                # Infrastructure lifecycle tools
                elif name == "factoryverse_server_start":
                    return await self._server_start(arguments)
                elif name == "factoryverse_server_stop":
                    return await self._server_stop(arguments)
                elif name == "factoryverse_server_restart":
                    return await self._server_restart(arguments)
                elif name == "factoryverse_client_start":
                    return await self._client_start(arguments)
                elif name == "factoryverse_client_stop":
                    return await self._client_stop(arguments)
                # Instance management tools
                elif name == "factoryverse_list_instances":
                    return await self._list_instances(arguments)
                elif name == "factoryverse_instance_status":
                    return await self._instance_status(arguments)
                # Utility tools
                elif name == "factoryverse_list_scenarios":
                    return await self._list_scenarios(arguments)
                else:
                    return [
                        TextContent(
                            type="text",
                            text=f"Unknown tool: {name}",
                        )
                    ]
            except Exception as e:
                logger.exception(f"Error executing tool {name}")
                # Use error parser for better error messages
                error_text = f"{type(e).__name__}: {str(e)}"
                formatted_error = _error_parser.parse_and_format(error_text)
                return [
                    TextContent(
                        type="text",
                        text=formatted_error,
                    )
                ]

    async def _run_test(self, args: dict) -> list[TextContent]:
        """Run pytest test."""
        test_path = args["test_path"]
        verbose = args.get("verbose", True)
        capture = args.get("capture", True)

        # Build pytest command
        cmd = ["uv", "run", "pytest", test_path]
        if verbose:
            cmd.append("-v")
        if not capture:
            cmd.append("-s")

        logger.info(f"Running test: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                cwd=Path(__file__).parent.parent.parent.parent,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            output = []
            if result.stdout:
                output.append(result.stdout)
            if result.stderr:
                output.append(f"\n--- STDERR ---\n{result.stderr}")

            return [
                TextContent(
                    type="text",
                    text="".join(output) or "(no output)",
                )
            ]
        except subprocess.TimeoutExpired:
            return [
                TextContent(
                    type="text",
                    text="Test execution timed out after 5 minutes",
                )
            ]
        except Exception as e:
            return [
                TextContent(
                    type="text",
                    text=f"Error running test: {type(e).__name__}: {str(e)}",
                )
            ]

    async def _execute_code(self, args: dict) -> list[TextContent]:
        """Execute Python code in FactoryVerse runtime."""
        code = args["code"]
        agent_id = args.get("agent_id", "agent_1")

        logger.info(f"Executing code for agent {agent_id}")

        # Create a temporary script
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            temp_script = f.name

        try:
            # Execute with Python
            result = subprocess.run(
                [sys.executable, temp_script],
                cwd=Path(__file__).parent.parent.parent.parent,
                capture_output=True,
                text=True,
                timeout=60,
            )

            output = []
            if result.stdout:
                output.append(result.stdout)
            if result.stderr:
                output.append(f"\n--- STDERR ---\n{result.stderr}")

            return [
                TextContent(
                    type="text",
                    text="".join(output) or "(no output)",
                )
            ]
        except Exception as e:
            return [
                TextContent(
                    type="text",
                    text=f"Error executing code: {type(e).__name__}: {str(e)}",
                )
            ]
        finally:
            Path(temp_script).unlink(missing_ok=True)

    async def _reload_server(self, args: dict) -> list[TextContent]:
        """Reload Factorio server scripts."""
        instance = args.get("instance")

        try:
            from FactoryVerse.environment.config import get_config
            from FactoryVerse.infra.instance_manager import FactorioInstanceManager
            from factorio_rcon import RCONClient

            config = get_config()
            if instance:
                if instance == "client":
                    instance_mgr = FactorioInstanceManager.get_client(config)
                elif instance.startswith("server_"):
                    server_id = int(instance.split("_")[1])
                    instance_mgr = FactorioInstanceManager.get_server(server_id, config)
                else:
                    instance_mgr = FactorioInstanceManager.from_env(config)
            else:
                instance_mgr = FactorioInstanceManager.from_env(config)

            client = RCONClient(
                instance_mgr.rcon_host,
                instance_mgr.rcon_port,
                instance_mgr.rcon_password,
            )
            client.connect()

            response = client.send_command(
                "/c game.reload_script(); game.print('Scripts reloaded'); rcon.print('Scripts reloaded')"
            )

            client.close()

            return [
                TextContent(
                    type="text",
                    text=f"Server reloaded successfully. Response: {response}",
                )
            ]
        except Exception as e:
            logger.exception("Error reloading server")
            return [
                TextContent(
                    type="text",
                    text=f"Error reloading server: {type(e).__name__}: {str(e)}",
                )
            ]

    async def _inspect_inventory(self, args: dict) -> list[TextContent]:
        """Inspect agent inventory."""
        agent_id = args.get("agent_id", "agent_1")

        try:
            from FactoryVerse.environment.config import get_config
            from FactoryVerse.infra.instance_manager import FactorioInstanceManager
            from factorio_rcon import RCONClient

            config = get_config()
            instance_mgr = FactorioInstanceManager.from_env(config)

            client = RCONClient(
                instance_mgr.rcon_host,
                instance_mgr.rcon_port,
                instance_mgr.rcon_password,
            )
            client.connect()

            cmd = f'/c local result = remote.call("{agent_id}", "get_inventory_items"); rcon.print(helpers.table_to_json(result))'
            response = client.send_command(cmd)

            client.close()

            try:
                inventory = json.loads(response)
                formatted = json.dumps(inventory, indent=2)
            except json.JSONDecodeError:
                formatted = response

            return [
                TextContent(
                    type="text",
                    text=f"Agent {agent_id} inventory:\n{formatted}",
                )
            ]
        except Exception as e:
            logger.exception("Error inspecting inventory")
            return [
                TextContent(
                    type="text",
                    text=f"Error inspecting inventory: {type(e).__name__}: {str(e)}",
                )
            ]

    async def _add_inventory(self, args: dict) -> list[TextContent]:
        """Add items to agent inventory."""
        agent_id = args.get("agent_id", "agent_1")
        items = args.get("items", {})

        if not items:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": "No items specified",
                    }, indent=2),
                )
            ]

        try:
            from FactoryVerse.environment.config import get_config
            from FactoryVerse.infra.instance_manager import FactorioInstanceManager
            from FactoryVerse.game.agent.admin_adapter import AdminInterface
            from factorio_rcon import RCONClient

            config = get_config()
            instance_mgr = FactorioInstanceManager.from_env(config)

            client = RCONClient(
                instance_mgr.rcon_host,
                instance_mgr.rcon_port,
                instance_mgr.rcon_password,
            )
            client.connect()

            # Extract numeric agent ID from interface name (e.g., "agent_1" -> 1)
            try:
                numeric_id = int(agent_id.split("_")[1])
            except (ValueError, IndexError):
                numeric_id = 1  # Default to agent 1

            # Use the admin interface adapter for add_items
            admin_api = AdminInterface(client)
            admin_api.add_items(numeric_id, items)

            client.close()

            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": True,
                        "agent_id": agent_id,
                        "numeric_id": numeric_id,
                        "items_added": items,
                    }, indent=2),
                )
            ]
        except Exception as e:
            logger.exception("Error adding inventory")
            error_text = f"{type(e).__name__}: {str(e)}"
            formatted_error = _error_parser.parse_and_format(error_text)
            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": formatted_error,
                    }, indent=2),
                )
            ]

    # ========================================================================
    # SESSION MANAGEMENT METHODS (Environment-based)
    # ========================================================================

    async def _create_session(self, args: dict) -> list[TextContent]:
        """Create an Environment-based session."""
        from FactoryVerse.environment import (
            create_session,
            Tier,
            RuntimeVariant,
        )

        session_id = args["session_id"]
        scope_int = args.get("scope", 3)
        variant_str = args.get("variant", "minimal")
        instance = args.get("instance")
        agent_id = args.get("agent_id", "agent_1")
        initial_inventory = args.get("initial_inventory")

        # Map scope to tier
        scope_to_tier = {
            0: Tier.PYTHON_INFRA,  # RCON only
            1: Tier.RUNTIME,       # SNAPSHOT -> RUNTIME with database
            2: Tier.RUNTIME,       # AGENT -> RUNTIME
            3: Tier.RUNTIME,       # Full RUNTIME
        }
        up_to = scope_to_tier.get(scope_int, Tier.RUNTIME)

        # Map variant string to enum
        variant = RuntimeVariant.FULL if variant_str == "full" else RuntimeVariant.MINIMAL

        try:
            env = await create_session(
                session_id=session_id,
                up_to=up_to,
                scenario="test-ground",
                instance=instance,
                agent_id=agent_id,
                variant=variant,
                initial_inventory=initial_inventory,
            )

            result = {
                "success": True,
                "session_id": session_id,
                "initialized_up_to": up_to.name,
                "variant": variant_str,
                "instance": env.tier3.instance if env.tier3 else None,
                "agent_id": agent_id,
                "components": self._get_available_components(env),
            }
        except ValueError as e:
            result = {
                "success": False,
                "error": str(e),
                "error_type": "session_exists",
            }
        except Exception as e:
            result = {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__,
            }

        return [
            TextContent(
                type="text",
                text=json.dumps(result, indent=2),
            )
        ]

    def _get_available_components(self, env) -> list[str]:
        """Get list of available components in environment."""
        components = []
        if env.tier3:
            components.extend(["rcon", "instance"])
        if env.tier4:
            if env.tier4.database:
                components.append("database")
            if env.tier4.reachable_view:
                components.append("reachable_view")
            if env.tier4.remote_view:
                components.append("remote_view")
            if env.tier4.placement_hints:
                components.append("placement_hints")
            if env.tier4.ghost_builder:
                components.append("ghost_builder")
            if env.tier4.events:
                components.append("events")
            if env.tier4.embodied_actions:
                components.extend([
                    "walking", "crafting", "research", "inventory",
                    "placement", "entity_ops", "resources"
                ])
        return components

    async def _execute_in_session(self, args: dict) -> list[TextContent]:
        """Execute code in a session with proper output capture and timeout."""
        from FactoryVerse.environment import get_session, get_session_components
        import sys
        from io import StringIO
        import traceback

        session_id = args["session_id"]
        code = args["code"]
        timeout = args.get("timeout", 120)  # Default 120 seconds

        env = get_session(session_id)
        if env is None:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"Session '{session_id}' not found",
                        "error_type": "session_not_found",
                    }, indent=2),
                )
            ]

        try:
            # Build execution namespace from session components
            exec_globals = get_session_components(session_id)
            exec_globals["__builtins__"] = __builtins__
            exec_globals["asyncio"] = asyncio

            # Add common types
            from FactoryVerse.game.factory.types import MapPosition, Direction, BoundingBox
            from FactoryVerse.game.agent.placement_hints import ConnectionType, GhostPlan
            exec_globals.update({
                "MapPosition": MapPosition,
                "Direction": Direction,
                "BoundingBox": BoundingBox,
                "ConnectionType": ConnectionType,
                "GhostPlan": GhostPlan,
            })

            # Capture stdout
            stdout_capture = StringIO()
            old_stdout = sys.stdout

            async def execute_with_timeout():
                """Execute code with timeout wrapper."""
                nonlocal stdout_capture, old_stdout
                try:
                    sys.stdout = stdout_capture

                    # Execute code
                    if "await " in code:
                        # Wrap async code
                        indented = "\n".join("    " + line for line in code.split("\n"))
                        wrapped = f"async def __exec__():\n{indented}\n    return locals()"
                        exec(wrapped, exec_globals)
                        result = await exec_globals["__exec__"]()
                    else:
                        exec(code, exec_globals)
                        result = None

                    return result

                finally:
                    sys.stdout = old_stdout

            # Execute with timeout
            try:
                result = await asyncio.wait_for(
                    execute_with_timeout(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                sys.stdout = old_stdout  # Ensure stdout is restored
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({
                            "success": False,
                            "error": f"Execution timed out after {timeout} seconds",
                            "error_type": "timeout",
                            "partial_stdout": stdout_capture.getvalue()[:1000] if stdout_capture.getvalue() else None,
                        }, indent=2),
                    )
                ]

            stdout_output = stdout_capture.getvalue()

            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": True,
                        "session_id": session_id,
                        "stdout": stdout_output if stdout_output else None,
                        "result": str(result) if result else None,
                    }, indent=2),
                )
            ]

        except Exception as e:
            # Use error parser for cleaner error messages
            raw_traceback = traceback.format_exc()
            formatted_error = _error_parser.parse_and_format(raw_traceback)
            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "formatted_error": formatted_error,
                    }, indent=2),
                )
            ]

    async def _session_status(self, args: dict) -> list[TextContent]:
        """Get detailed status of a session including tier information."""
        from FactoryVerse.environment import get_session

        session_id = args["session_id"]

        env = get_session(session_id)
        if env is None:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"Session '{session_id}' not found",
                    }, indent=2),
                )
            ]

        try:
            status = await env.status()

            def tier_to_dict(tier_status):
                if tier_status is None:
                    return None
                return {
                    "is_ready": tier_status.is_ready,
                    "error": tier_status.error,
                }

            result = {
                "success": True,
                "session_id": session_id,
                "initialized_up_to": env._initialized_up_to.name if env._initialized_up_to else None,
                "tiers": {
                    "tier1_factorio": tier_to_dict(status.tier1),
                    "tier2_settings": tier_to_dict(status.tier2),
                    "tier3_python": tier_to_dict(status.tier3),
                    "tier4_runtime": tier_to_dict(status.tier4),
                    "tier5_spec": tier_to_dict(status.tier5),
                    "tier6_interaction": tier_to_dict(status.tier6),
                },
                "components": self._get_available_components(env),
            }

            return [
                TextContent(
                    type="text",
                    text=json.dumps(result, indent=2),
                )
            ]
        except Exception as e:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": str(e),
                        "error_type": type(e).__name__,
                    }, indent=2),
                )
            ]

    async def _reload_session(self, args: dict) -> list[TextContent]:
        """Reload a session."""
        from FactoryVerse.environment import reload_session, get_session, Tier

        session_id = args["session_id"]
        reload_lua = args.get("reload_lua", False)

        env = get_session(session_id)
        if env is None:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"Session '{session_id}' not found",
                    }, indent=2),
                )
            ]

        try:
            await reload_session(
                session_id=session_id,
                reload_lua=reload_lua,
                from_tier=Tier.RUNTIME,
            )

            result = {
                "success": True,
                "session_id": session_id,
                "lua_reloaded": reload_lua,
            }
        except Exception as e:
            result = {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__,
            }

        return [
            TextContent(
                type="text",
                text=json.dumps(result, indent=2),
            )
        ]

    async def _destroy_session(self, args: dict) -> list[TextContent]:
        """Destroy a session."""
        from FactoryVerse.environment import destroy_session

        session_id = args["session_id"]

        try:
            destroyed = await destroy_session(session_id)
            result = {
                "success": True,
                "session_id": session_id,
                "destroyed": destroyed,
            }
        except Exception as e:
            result = {
                "success": False,
                "error": str(e),
            }

        return [
            TextContent(
                type="text",
                text=json.dumps(result, indent=2),
            )
        ]

    async def _list_sessions(self, args: dict) -> list[TextContent]:
        """List active sessions."""
        from FactoryVerse.environment import list_sessions

        sessions = list_sessions()

        return [
            TextContent(
                type="text",
                text=json.dumps({
                    "success": True,
                    "count": len(sessions),
                    "sessions": list(sessions.values()),
                }, indent=2),
            )
        ]

    async def _reload_python(self, args: dict) -> list[TextContent]:
        """Hot-reload Python modules in the MCP server process."""
        import fnmatch

        modules_arg = args.get("modules", None)
        clear_all = args.get("clear_all", False)

        # Default modules to reload
        default_patterns = [
            "FactoryVerse.agent.embodied_actions.*",
            "FactoryVerse.agent.ghost_builder",
            "FactoryVerse.agent.placement_hints",
            "FactoryVerse.agent.reachable_view",
            "FactoryVerse.agent.remote_view",
            "FactoryVerse.agent.infra.snapshot.*",
            "FactoryVerse.environment.*",
            "FactoryVerse.factory.entity.*",
        ]

        patterns = modules_arg if modules_arg else default_patterns

        cleared = []
        errors = []

        if clear_all:
            to_clear = [
                name for name in list(sys.modules.keys())
                if name.startswith("FactoryVerse.")
            ]
            for name in to_clear:
                try:
                    del sys.modules[name]
                    cleared.append(name)
                except Exception as e:
                    errors.append({"module": name, "error": str(e)})
        else:
            all_modules = list(sys.modules.keys())
            matched_modules = set()

            for pattern in patterns:
                for mod_name in all_modules:
                    if pattern.endswith(".*"):
                        prefix = pattern[:-2]
                        if mod_name == prefix or mod_name.startswith(prefix + "."):
                            matched_modules.add(mod_name)
                    elif fnmatch.fnmatch(mod_name, pattern):
                        matched_modules.add(mod_name)

            sorted_modules = sorted(matched_modules, key=lambda x: x.count("."), reverse=True)

            for mod_name in sorted_modules:
                try:
                    if mod_name in sys.modules:
                        del sys.modules[mod_name]
                        cleared.append(mod_name)
                except Exception as e:
                    errors.append({"module": mod_name, "error": str(e), "action": "clear"})

        result = {
            "success": len(errors) == 0,
            "cleared_count": len(cleared),
            "cleared": cleared[:20] if len(cleared) > 20 else cleared,
            "truncated": len(cleared) > 20,
            "patterns_used": patterns if not clear_all else ["*"],
            "clear_all": clear_all,
            "errors": errors if errors else None,
            "note": "Destroy and recreate sessions for clean state" if cleared else None,
        }

        return [
            TextContent(
                type="text",
                text=json.dumps(result, indent=2),
            )
        ]

    # ========================================================================
    # INFRASTRUCTURE LIFECYCLE METHODS
    # ========================================================================

    async def _server_start(self, args: dict) -> list[TextContent]:
        """Start Factorio Docker servers."""
        num_servers = args.get("num_servers", 1)
        scenario = args.get("scenario", "test-ground")
        max_agents = args.get("max_agents", 10)
        no_jupyter = args.get("no_jupyter", True)

        try:
            from FactoryVerse.environment.config import get_config
            from FactoryVerse.infra.docker import (
                DockerComposeManager,
                FactorioServerManager,
                JupyterManager,
            )
            from FactoryVerse.utils.port_config import configure_all_server_snapshot_ports

            config = get_config()
            work_dir = config.project_root

            server_mgr = FactorioServerManager(work_dir, config)

            if not server_mgr.validate_scenario(scenario):
                available = server_mgr.list_scenarios()
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({
                            "success": False,
                            "error": f"Scenario '{scenario}' not found",
                            "available_scenarios": available,
                        }, indent=2),
                    )
                ]

            server_mgr.clear_all_server_snapshot_dirs(num_servers)
            server_mgr.prepare_mods(scenario)

            compose_mgr = DockerComposeManager(work_dir)

            if not no_jupyter:
                jupyter_mgr = JupyterManager(work_dir)
                compose_mgr.add_services("jupyter", jupyter_mgr.get_services())

            compose_mgr.add_services(
                "factorio",
                server_mgr.get_services(num_servers, scenario, max_agents=max_agents),
            )
            compose_mgr.write_compose()

            compose_mgr.up()

            configure_all_server_snapshot_ports(num_servers, config)

            from FactoryVerse.infra.instance_manager import FactorioInstanceManager
            import time

            ready_servers = []
            max_wait = 60
            start_time = time.time()

            while len(ready_servers) < num_servers and (time.time() - start_time) < max_wait:
                for i in range(num_servers):
                    if i not in ready_servers:
                        instance = FactorioInstanceManager.get_server(i, config)
                        if instance.test_connection():
                            ready_servers.append(i)
                if len(ready_servers) < num_servers:
                    await asyncio.sleep(2)

            server_info = []
            for i in range(num_servers):
                rcon_port = config.get_rcon_port(f"server_{i}")
                game_port = config.get_game_port(i)
                snapshot_port = config.get_snapshot_port(f"server_{i}")
                agent_range = config.get_agent_port_range(server_index=i)

                server_info.append({
                    "server_id": i,
                    "name": f"server_{i}",
                    "ready": i in ready_servers,
                    "rcon_port": rcon_port,
                    "game_port": game_port,
                    "snapshot_port": snapshot_port,
                    "agent_ports": f"{agent_range[0]}-{agent_range[-1]}",
                })

            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": True,
                        "scenario": scenario,
                        "num_servers": num_servers,
                        "servers": server_info,
                        "all_ready": len(ready_servers) == num_servers,
                    }, indent=2),
                )
            ]
        except Exception as e:
            logger.exception("Error starting servers")
            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"{type(e).__name__}: {str(e)}",
                    }, indent=2),
                )
            ]

    async def _server_stop(self, args: dict) -> list[TextContent]:
        """Stop all Factorio Docker servers."""
        try:
            from FactoryVerse.environment.config import get_config
            from FactoryVerse.infra.docker import DockerComposeManager

            config = get_config()
            compose_mgr = DockerComposeManager(config.project_root)
            compose_mgr.down()

            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": True,
                        "message": "All services stopped",
                    }, indent=2),
                )
            ]
        except Exception as e:
            logger.exception("Error stopping servers")
            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"{type(e).__name__}: {str(e)}",
                    }, indent=2),
                )
            ]

    async def _server_restart(self, args: dict) -> list[TextContent]:
        """Restart all Factorio Docker servers."""
        try:
            from FactoryVerse.environment.config import get_config
            from FactoryVerse.infra.docker import DockerComposeManager

            config = get_config()
            compose_mgr = DockerComposeManager(config.project_root)
            compose_mgr.restart()

            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": True,
                        "message": "All services restarted",
                    }, indent=2),
                )
            ]
        except Exception as e:
            logger.exception("Error restarting servers")
            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"{type(e).__name__}: {str(e)}",
                    }, indent=2),
                )
            ]

    async def _client_start(self, args: dict) -> list[TextContent]:
        """Start the Factorio client."""
        scenario = args.get("scenario")
        save_file = args.get("save_file")
        new_map = args.get("new_map", False)

        try:
            from FactoryVerse.environment.config import get_config
            from FactoryVerse.infra.factorio_client_manager import FactorioClientManager
            from FactoryVerse.infra.docker import FactorioServerManager

            config = get_config()
            work_dir = config.project_root
            client_mgr = FactorioClientManager(work_dir)
            server_mgr = FactorioServerManager(work_dir, config)

            save_path = Path(save_file) if save_file else None
            if save_path and not save_path.is_absolute():
                save_path = work_dir / save_path

            client_mgr.start(
                scenario=scenario,
                save_file=save_path,
                new_map=new_map,
                project_scenarios_dir=server_mgr.scenarios_dir,
            )

            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": True,
                        "message": "Client started",
                        "scenario": scenario,
                        "save_file": str(save_path) if save_path else None,
                        "new_map": new_map,
                    }, indent=2),
                )
            ]
        except Exception as e:
            logger.exception("Error starting client")
            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"{type(e).__name__}: {str(e)}",
                    }, indent=2),
                )
            ]

    async def _client_stop(self, args: dict) -> list[TextContent]:
        """Stop the Factorio client."""
        force = args.get("force", False)

        try:
            from FactoryVerse.environment.config import get_config
            from FactoryVerse.infra.factorio_client_manager import FactorioClientManager

            config = get_config()
            client_mgr = FactorioClientManager(config.project_root)
            client_mgr.stop(force=force)

            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": True,
                        "message": "Client stopped",
                    }, indent=2),
                )
            ]
        except Exception as e:
            logger.exception("Error stopping client")
            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"{type(e).__name__}: {str(e)}",
                    }, indent=2),
                )
            ]

    # ========================================================================
    # INSTANCE MANAGEMENT METHODS
    # ========================================================================

    async def _list_instances(self, args: dict) -> list[TextContent]:
        """List all Factorio instances."""
        try:
            from FactoryVerse.infra.instance_manager import FactorioInstanceManager

            instances = FactorioInstanceManager.list_available()
            result = []

            for inst in instances:
                is_active = inst.test_connection()
                result.append({
                    "name": inst.name,
                    "type": inst.type,
                    "active": is_active,
                    "rcon_host": inst.rcon_host,
                    "rcon_port": inst.rcon_port,
                    "script_output_dir": str(inst.script_output_dir),
                    "snapshot_dir": str(inst.snapshot_dir),
                })

            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "instances": result,
                        "active_count": sum(1 for i in result if i["active"]),
                        "total_count": len(result),
                    }, indent=2),
                )
            ]
        except Exception as e:
            logger.exception("Error listing instances")
            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"{type(e).__name__}: {str(e)}",
                    }, indent=2),
                )
            ]

    async def _instance_status(self, args: dict) -> list[TextContent]:
        """Get detailed status of a specific instance."""
        instance_name = args["instance"]

        try:
            from FactoryVerse.environment.config import get_config
            from FactoryVerse.infra.instance_manager import FactorioInstanceManager
            from factorio_rcon import RCONClient

            config = get_config()

            if instance_name == "client":
                instance = FactorioInstanceManager.get_client(config)
            elif instance_name.startswith("server_"):
                server_id = int(instance_name.split("_")[1])
                instance = FactorioInstanceManager.get_server(server_id, config)
            else:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({
                            "success": False,
                            "error": f"Invalid instance name: {instance_name}. Use 'client' or 'server_N'",
                        }, indent=2),
                    )
                ]

            result = {
                "name": instance.name,
                "type": instance.type,
                "rcon_host": instance.rcon_host,
                "rcon_port": instance.rcon_port,
                "script_output_dir": str(instance.script_output_dir),
                "snapshot_dir": str(instance.snapshot_dir),
            }

            if instance.test_connection():
                result["active"] = True
                try:
                    client = RCONClient(
                        instance.rcon_host,
                        instance.rcon_port,
                        instance.rcon_password,
                    )
                    client.connect()

                    tick_response = client.send_command("/c rcon.print(game.tick)")
                    result["game_tick"] = int(tick_response.strip()) if tick_response.strip().isdigit() else None

                    surface_response = client.send_command(
                        '/c local s = game.surfaces[1]; rcon.print(string.format("%s,%d,%d", s.name, s.map_gen_settings.seed or 0, #game.players))'
                    )
                    if surface_response:
                        parts = surface_response.strip().split(",")
                        if len(parts) >= 3:
                            result["surface_name"] = parts[0]
                            result["seed"] = int(parts[1])
                            result["player_count"] = int(parts[2])

                    client.close()
                except Exception as e:
                    result["game_state_error"] = str(e)
            else:
                result["active"] = False

            return [
                TextContent(
                    type="text",
                    text=json.dumps(result, indent=2),
                )
            ]
        except Exception as e:
            logger.exception("Error getting instance status")
            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"{type(e).__name__}: {str(e)}",
                    }, indent=2),
                )
            ]

    # ========================================================================
    # UTILITY METHODS
    # ========================================================================

    async def _list_scenarios(self, args: dict) -> list[TextContent]:
        """List available scenarios."""
        try:
            from FactoryVerse.environment.config import get_config

            config = get_config()
            scenarios = config.list_scenarios(include_local=True)

            repo_scenarios = set(config._list_scenarios_in_dir(config.scenarios_dir))

            result = []
            for scenario in sorted(scenarios):
                is_repo = scenario in repo_scenarios
                result.append({
                    "name": scenario,
                    "source": "repo" if is_repo else "local",
                    "hot_reload": is_repo,
                })

            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "scenarios": result,
                        "count": len(result),
                        "repo_dir": str(config.scenarios_dir),
                        "local_dir": str(config.local_scenarios_dir),
                    }, indent=2),
                )
            ]
        except Exception as e:
            logger.exception("Error listing scenarios")
            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"{type(e).__name__}: {str(e)}",
                    }, indent=2),
                )
            ]


def create_mcp_server() -> FactoryVerseMCPServer:
    """Create and configure MCP server."""
    return FactoryVerseMCPServer()


async def run_mcp_server():
    """Run MCP server with stdio transport."""
    logger.info("Creating MCP server instance...")
    server = create_mcp_server()
    logger.info("MCP server created, starting stdio transport...")

    async with stdio_server() as (read_stream, write_stream):
        logger.info("MCP server ready, waiting for client connections...")
        await server.server.run(
            read_stream,
            write_stream,
            server.server.create_initialization_options(),
        )


def main():
    """Entry point for MCP server."""
    import sys

    if len(sys.argv) > 1 and sys.argv[1] in ("--help", "-h"):
        print("FactoryVerse MCP Server")
        print("\nThis server provides MCP tools for FactoryVerse development:")
        print("\n=== Development Tools ===")
        print("  - factoryverse_run_test: Run pytest tests")
        print("  - factoryverse_execute_code: Execute Python code for debugging")
        print("  - factoryverse_server_reload: Reload Factorio Lua scripts")
        print("  - factoryverse_inspect_inventory: Get agent inventory state")
        print("  - factoryverse_add_inventory: Add items to agent inventory")
        print("\n=== Session Management ===")
        print("  - factoryverse_create_session: Create session at scope (RCON/SNAPSHOT/AGENT/RUNTIME)")
        print("  - factoryverse_execute_in_session: Execute code in session context")
        print("  - factoryverse_session_status: Get detailed session status with tier info")
        print("  - factoryverse_reload_session: Reload session (Python modules + optional Lua)")
        print("  - factoryverse_destroy_session: Destroy session and cleanup")
        print("  - factoryverse_list_sessions: List active sessions")
        print("\n=== Infrastructure Lifecycle ===")
        print("  - factoryverse_server_start: Start Docker Factorio servers")
        print("  - factoryverse_server_stop: Stop all Docker servers")
        print("  - factoryverse_server_restart: Restart all Docker servers")
        print("  - factoryverse_client_start: Start local Factorio client")
        print("  - factoryverse_client_stop: Stop local Factorio client")
        print("\n=== Instance Management ===")
        print("  - factoryverse_list_instances: List all instances with status")
        print("  - factoryverse_instance_status: Get detailed instance status")
        print("\n=== Utilities ===")
        print("  - factoryverse_list_scenarios: List available scenarios")
        print("  - factoryverse_reload_python: Hot-reload Python modules")
        print("\nThe server communicates via stdio (JSON-RPC).")
        print("Configure it in your IDE's MCP settings (see mcp.json.example).")
        print("\nUsage: factoryverse-mcp [--verbose]")
        print("  --verbose, -v: Enable verbose logging to stderr")
        sys.exit(0)

    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    log_level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=log_level,
        format="[MCP] %(asctime)s - %(levelname)s - %(message)s",
        stream=sys.stderr,
        datefmt="%H:%M:%S",
    )

    logger.info("=" * 60)
    logger.info("FactoryVerse MCP Server Starting")
    logger.info("=" * 60)
    if verbose:
        logger.info("Verbose mode enabled (DEBUG level)")
    logger.info("Server will communicate via stdio (JSON-RPC)")
    logger.info("Logs are sent to stderr to avoid interfering with protocol")

    asyncio.run(run_mcp_server())


if __name__ == "__main__":
    main()
