"""FactoryVerse MCP Server Implementation."""

import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logger = logging.getLogger(__name__)


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
                # Session management tools
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
                            "instance": {
                                "type": "string",
                                "description": "Factorio instance ('client' or 'server_N'). Auto-detect if not specified.",
                            },
                            "agent_id": {
                                "type": "string",
                                "description": "Agent identifier (default: 'agent_1')",
                                "default": "agent_1",
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
                        },
                        "required": ["session_id", "code"],
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
                # Session management tools
                elif name == "factoryverse_create_session":
                    return await self._create_session(arguments)
                elif name == "factoryverse_execute_in_session":
                    return await self._execute_in_session(arguments)
                elif name == "factoryverse_reload_session":
                    return await self._reload_session(arguments)
                elif name == "factoryverse_destroy_session":
                    return await self._destroy_session(arguments)
                elif name == "factoryverse_list_sessions":
                    return await self._list_sessions(arguments)
                else:
                    return [
                        TextContent(
                            type="text",
                            text=f"Unknown tool: {name}",
                        )
                    ]
            except Exception as e:
                logger.exception(f"Error executing tool {name}")
                return [
                    TextContent(
                        type="text",
                        text=f"Error: {type(e).__name__}: {str(e)}",
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

        # For MVP, we'll use a simple subprocess approach
        # In future, we can integrate with actual FactoryVerseRuntime
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
            from FactoryVerse.config import get_config
            from FactoryVerse.infra.instance_manager import FactorioInstanceManager
            from factorio_rcon import RCONClient

            config = get_config()
            if instance:
                # Parse instance name to get the right instance
                if instance == "client":
                    instance_mgr = FactorioInstanceManager.get_client(config)
                elif instance.startswith("server_"):
                    server_id = int(instance.split("_")[1])
                    instance_mgr = FactorioInstanceManager.get_server(server_id, config)
                else:
                    # Fallback: try auto-detection
                    instance_mgr = FactorioInstanceManager.from_env(config)
            else:
                instance_mgr = FactorioInstanceManager.from_env(config)

            client = RCONClient(
                instance_mgr.rcon_host,
                instance_mgr.rcon_port,
                instance_mgr.rcon_password,
            )
            client.connect()

            # Reload scripts
            response = client.send_command(
                "/c game.reload_script(); game.print('Scripts reloaded'); rcon.print('Scripts reloaded')"
            )

            client.disconnect()

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
            from FactoryVerse.config import get_config
            from FactoryVerse.infra.instance_manager import FactorioInstanceManager
            from factorio_rcon import RCONClient
            import json

            config = get_config()
            instance_mgr = FactorioInstanceManager.from_env(config)

            client = RCONClient(
                instance_mgr.rcon_host,
                instance_mgr.rcon_port,
                instance_mgr.rcon_password,
            )
            client.connect()

            # Get inventory via RCON
            cmd = f'/c local result = remote.call("{agent_id}", "get_inventory_items"); rcon.print(helpers.table_to_json(result))'
            response = client.send_command(cmd)

            client.disconnect()

            # Try to parse as JSON
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

    # ========================================================================
    # SESSION MANAGEMENT METHODS
    # ========================================================================

    async def _create_session(self, args: dict) -> list[TextContent]:
        """Create a boilerplate session."""
        from FactoryVerse.infra.llm.boilerplate import Scope
        from FactoryVerse.infra.llm.boilerplate.mcp import mcp_create_session

        session_id = args["session_id"]
        scope_int = args.get("scope", 3)
        scope = Scope(scope_int)
        instance = args.get("instance")
        agent_id = args.get("agent_id", "agent_1")

        result = await mcp_create_session(
            session_id=session_id,
            scope=scope,
            instance=instance,
            agent_id=agent_id,
        )

        return [
            TextContent(
                type="text",
                text=json.dumps(result, indent=2),
            )
        ]

    async def _execute_in_session(self, args: dict) -> list[TextContent]:
        """Execute code in a session."""
        from FactoryVerse.infra.llm.boilerplate.mcp import mcp_execute_code

        session_id = args["session_id"]
        code = args["code"]

        result = await mcp_execute_code(session_id=session_id, code=code)

        return [
            TextContent(
                type="text",
                text=json.dumps(result, indent=2),
            )
        ]

    async def _reload_session(self, args: dict) -> list[TextContent]:
        """Reload a session."""
        from FactoryVerse.infra.llm.boilerplate.mcp import mcp_reload_session

        session_id = args["session_id"]
        reload_lua = args.get("reload_lua", False)

        result = await mcp_reload_session(session_id=session_id, reload_lua=reload_lua)

        return [
            TextContent(
                type="text",
                text=json.dumps(result, indent=2),
            )
        ]

    async def _destroy_session(self, args: dict) -> list[TextContent]:
        """Destroy a session."""
        from FactoryVerse.infra.llm.boilerplate.mcp import mcp_destroy_session

        session_id = args["session_id"]

        result = await mcp_destroy_session(session_id=session_id)

        return [
            TextContent(
                type="text",
                text=json.dumps(result, indent=2),
            )
        ]

    async def _list_sessions(self, args: dict) -> list[TextContent]:
        """List active sessions."""
        from FactoryVerse.infra.llm.boilerplate.mcp import mcp_list_sessions

        result = await mcp_list_sessions()

        return [
            TextContent(
                type="text",
                text=json.dumps(result, indent=2),
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

    # Handle --help flag
    if len(sys.argv) > 1 and sys.argv[1] in ("--help", "-h"):
        print("FactoryVerse MCP Server")
        print("\nThis server provides MCP tools for FactoryVerse development:")
        print("\nLegacy tools:")
        print("  - factoryverse_run_test: Run pytest tests")
        print("  - factoryverse_execute_code: Execute Python code for debugging")
        print("  - factoryverse_server_reload: Reload Factorio Lua scripts")
        print("  - factoryverse_inspect_inventory: Get agent inventory state")
        print("\nSession management (scoped boilerplate):")
        print(
            "  - factoryverse_create_session: Create session at scope (RCON/SNAPSHOT/AGENT/RUNTIME)"
        )
        print("  - factoryverse_execute_in_session: Execute code in session context")
        print(
            "  - factoryverse_reload_session: Reload session (Python modules + optional Lua)"
        )
        print("  - factoryverse_destroy_session: Destroy session and cleanup")
        print("  - factoryverse_list_sessions: List active sessions")
        print("\nThe server communicates via stdio (JSON-RPC).")
        print("Configure it in your IDE's MCP settings.")
        print("\nUsage: factoryverse-mcp [--verbose]")
        print("  --verbose, -v: Enable verbose logging to stderr")
        sys.exit(0)

    # Check for verbose flag
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    log_level = logging.DEBUG if verbose else logging.INFO

    # Configure logging to stderr (stdout is used for JSON-RPC)
    logging.basicConfig(
        level=log_level,
        format="[MCP] %(asctime)s - %(levelname)s - %(message)s",
        stream=sys.stderr,  # Important: use stderr so stdout is free for JSON-RPC
        datefmt="%H:%M:%S",
    )

    # Always log startup (even without verbose)
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
