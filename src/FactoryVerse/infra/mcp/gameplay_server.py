"""FactoryVerse Gameplay MCP Server.

A minimal MCP server for AI agents to play Factorio. Exposes only two tools:
- execute: Run Python code in the game runtime
- query: Run DuckDB SQL queries against game state

The server manages all infrastructure internally - agents never see sessions,
tiers, initialization, or connection details. They just interact with the game.
"""

import asyncio
import json
import logging
import sys
import traceback
from io import StringIO
from typing import Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logger = logging.getLogger(__name__)


class GameplayMCPServer:
    """Minimal MCP server for Factorio gameplay.

    Maintains a persistent runtime environment internally.
    Agents only see execute_code and query tools.

    Notifications (research complete, crafting done, etc.) are piggybacked
    onto tool responses - they're drained and appended after each call.
    """

    def __init__(self):
        self.server = Server("factoryverse-play")
        self._env: Optional["Environment"] = None
        self._init_lock = asyncio.Lock()
        self._init_error: Optional[str] = None
        self._setup_tools()

    async def _drain_notifications(self) -> str:
        """Drain pending game notifications and format for output.

        Called after each tool execution to piggyback async events
        (research complete, crafting done, etc.) onto the response.

        Returns:
            Formatted notification string, or empty string if none.
        """
        if self._env is None or self._env.tier4 is None:
            return ""

        events = self._env.tier4.events
        if events is None:
            return ""

        try:
            # Drain with minimal timeout (we just want what's already queued)
            pending = await events.drain(timeout=0.01)
            if not pending:
                return ""

            # Format for agent consumption
            formatted = events.format_events(pending)
            return f"\n\n--- Game Notifications ---\n{formatted}"

        except Exception as e:
            logger.debug(f"Error draining notifications: {e}")
            return ""

    async def _ensure_initialized(self) -> tuple[bool, Optional[str]]:
        """Ensure runtime is initialized. Returns (success, error_message)."""
        if self._env is not None:
            return True, None

        if self._init_error is not None:
            return False, self._init_error

        async with self._init_lock:
            # Double-check after acquiring lock
            if self._env is not None:
                return True, None
            if self._init_error is not None:
                return False, self._init_error

            try:
                from FactoryVerse.environment import Environment, Tier, RuntimeVariant

                logger.info("Initializing gameplay runtime...")

                self._env = await Environment.for_mcp(
                    scenario="test-ground",
                    agent_id="agent_1",
                    variant=RuntimeVariant.FULL,
                )

                logger.info("Gameplay runtime initialized successfully")
                return True, None

            except Exception as e:
                error_msg = self._translate_error(e)
                self._init_error = error_msg
                logger.error(f"Failed to initialize gameplay runtime: {e}")
                return False, error_msg

    def _translate_error(self, error: Exception) -> str:
        """Translate infrastructure errors to user-friendly messages."""
        error_str = str(error).lower()
        error_type = type(error).__name__

        if "connection refused" in error_str or "rcon" in error_str:
            return "Game not running. Start Factorio before using gameplay tools."
        elif "timeout" in error_str:
            return "Game connection timed out. Ensure Factorio is responsive."
        elif "no active instances" in error_str:
            return "No Factorio instance found. Launch the game first."
        else:
            # For unexpected errors, include type but not full traceback
            return f"Game error: {error_type} - {str(error)[:200]}"

    def _setup_tools(self):
        """Register the two gameplay tools."""

        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="execute",
                    description="""Execute Python code in the Factorio game runtime.

Use this to perform actions in the game: move the agent, place buildings,
craft items, mine resources, etc.

The code runs in a context with these pre-loaded:
- walking: Move agent (await walking.walk_to(x, y))
- crafting: Craft items (await crafting.craft("item-name", count))
- inventory: Manage items (inventory.get_contents(), inventory.transfer_to(...))
- placement: Place entities (await placement.place("entity-name", x, y))
- entity_ops: Interact with entities (await entity_ops.mine(...))
- research: Queue research (await research.queue("technology-name"))
- resources: Find resources (resources.find_nearest("iron-ore"))
- reachable: Query nearby entities (reachable.get_entities_in_radius(...))
- remote: Query map-wide state via SQL (remote.query("SELECT ..."))
- ghost_builder: Plan and build structures
- placement_hints: Get valid placement locations

Common patterns:
- Walk to position: await walking.walk_to(10, 20)
- Place entity: await placement.place("transport-belt", 5, 5)
- Craft item: await crafting.craft("iron-gear-wheel", 10)
- Query nearby: entities = reachable.get_entities_in_radius(10)
- Print results: print(result)  # Output returned to you""",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "code": {
                                "type": "string",
                                "description": "Python code to execute. Use 'await' for async operations. Use 'print()' to see results.",
                            },
                        },
                        "required": ["code"],
                    },
                ),
                Tool(
                    name="query",
                    description="""Query the Factorio game state using SQL (DuckDB).

The database contains tables for all game entities, resources, and state.
Use this to understand the map, find resources, plan builds, etc.

Key tables:
- entities: All placed entities (buildings, belts, inserters, etc.)
- resources: Resource patches (iron-ore, copper-ore, coal, stone, etc.)
- tiles: Ground tiles and terrain

Common columns:
- name: Entity/resource type (e.g., "iron-ore", "transport-belt")
- x, y: Position on the map
- direction: Facing direction (0=north, 2=east, 4=south, 6=west)
- health: Current health
- type: Entity category

Example queries:
- Find iron ore: SELECT x, y, amount FROM resources WHERE name = 'iron-ore' ORDER BY amount DESC LIMIT 5
- Count entities: SELECT name, COUNT(*) as count FROM entities GROUP BY name
- Nearby entities: SELECT name, x, y FROM entities WHERE x BETWEEN -50 AND 50 AND y BETWEEN -50 AND 50""",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "sql": {
                                "type": "string",
                                "description": "SQL query to execute against the game database",
                            },
                        },
                        "required": ["sql"],
                    },
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            try:
                if name == "execute":
                    return await self._execute_code(arguments)
                elif name == "query":
                    return await self._execute_query(arguments)
                else:
                    return [TextContent(type="text", text=f"Unknown tool: {name}")]
            except Exception as e:
                logger.exception(f"Error in tool {name}")
                return [TextContent(type="text", text=self._translate_error(e))]

    async def _execute_code(self, args: dict) -> list[TextContent]:
        """Execute Python code in the game runtime."""
        # Ensure initialized
        success, error = await self._ensure_initialized()
        if not success:
            return [TextContent(type="text", text=error)]

        code = args.get("code", "")
        if not code.strip():
            return [TextContent(type="text", text="No code provided")]

        try:
            # Build execution namespace from runtime components
            exec_globals = self._build_exec_namespace()

            # Capture stdout
            stdout_capture = StringIO()
            old_stdout = sys.stdout

            result = None
            try:
                sys.stdout = stdout_capture

                # Handle async code
                if "await " in code:
                    # Wrap in async function
                    indented = "\n".join("    " + line for line in code.split("\n"))
                    wrapped = f"async def __exec__():\n{indented}\n    return locals()"
                    exec(wrapped, exec_globals)
                    result = await exec_globals["__exec__"]()
                else:
                    exec(code, exec_globals)

            finally:
                sys.stdout = old_stdout

            stdout_output = stdout_capture.getvalue()

            # Build response
            response_parts = []
            if stdout_output:
                response_parts.append(stdout_output.rstrip())
            if result and isinstance(result, dict):
                # Filter out internal vars
                user_vars = {k: v for k, v in result.items()
                           if not k.startswith('_') and k not in exec_globals}
                if user_vars:
                    response_parts.append(f"Variables: {user_vars}")

            # Drain and append any pending notifications
            notifications = await self._drain_notifications()

            if response_parts:
                response_text = "\n".join(response_parts) + notifications
                return [TextContent(type="text", text=response_text)]
            else:
                response_text = "(executed successfully, no output)" + notifications
                return [TextContent(type="text", text=response_text)]

        except Exception as e:
            # Format error nicely without full traceback
            tb = traceback.extract_tb(e.__traceback__)
            # Find the last frame that's in user code (not our wrapper)
            user_frames = [f for f in tb if "<string>" in f.filename or "exec" not in f.name]

            if user_frames:
                last_frame = user_frames[-1]
                error_msg = f"Line {last_frame.lineno}: {type(e).__name__}: {e}"
            else:
                error_msg = f"{type(e).__name__}: {e}"

            # Still drain notifications even on error
            notifications = await self._drain_notifications()
            return [TextContent(type="text", text=f"Error: {error_msg}{notifications}")]

    async def _execute_query(self, args: dict) -> list[TextContent]:
        """Execute SQL query against game database."""
        # Ensure initialized
        success, error = await self._ensure_initialized()
        if not success:
            return [TextContent(type="text", text=error)]

        sql = args.get("sql", "")
        if not sql.strip():
            return [TextContent(type="text", text="No SQL query provided")]

        try:
            # Get database from runtime
            database = self._env.tier4.database
            if database is None:
                return [TextContent(type="text", text="Database not available")]

            # Execute query
            result = database.execute(sql)

            # Format result
            if result is None:
                return [TextContent(type="text", text="(query executed, no results)")]

            # Convert to list of dicts for readability
            columns = result.columns if hasattr(result, 'columns') else None
            rows = result.fetchall() if hasattr(result, 'fetchall') else list(result)

            if not rows:
                return [TextContent(type="text", text="(no rows returned)")]

            # Format as table-like output
            if columns:
                col_names = [str(c) for c in columns]
                lines = [" | ".join(col_names)]
                lines.append("-" * len(lines[0]))
                for row in rows[:100]:  # Limit output
                    lines.append(" | ".join(str(v) for v in row))
                if len(rows) > 100:
                    lines.append(f"... ({len(rows)} total rows, showing first 100)")
                response_text = "\n".join(lines)
            else:
                # Just stringify
                response_text = str(rows[:100])

            # Drain and append any pending notifications
            notifications = await self._drain_notifications()
            return [TextContent(type="text", text=response_text + notifications)]

        except Exception as e:
            # Still drain notifications even on error
            notifications = await self._drain_notifications()
            error_text = f"Query error: {type(e).__name__}: {e}"
            return [TextContent(type="text", text=error_text + notifications)]

    def _build_exec_namespace(self) -> dict:
        """Build execution namespace with all runtime components."""
        ns = {"__builtins__": __builtins__, "asyncio": asyncio}

        # Add common types
        from FactoryVerse.game.factory.types import MapPosition, Direction, BoundingBox
        ns.update({
            "MapPosition": MapPosition,
            "Direction": Direction,
            "BoundingBox": BoundingBox,
        })

        # Add runtime components with short names
        tier4 = self._env.tier4
        if tier4:
            # Embodied actions
            if tier4.embodied_actions:
                ea = tier4.embodied_actions
                ns["walking"] = ea.walking
                ns["crafting"] = ea.crafting
                ns["inventory"] = ea.inventory
                ns["placement"] = ea.placement
                ns["entity_ops"] = ea.entity_ops
                ns["resources"] = ea.resources
                ns["research"] = ea.research

            # Views
            if tier4.reachable_view:
                ns["reachable"] = tier4.reachable_view
            if tier4.remote_view:
                ns["remote"] = tier4.remote_view

            # Planning
            if tier4.placement_hints:
                ns["placement_hints"] = tier4.placement_hints
            if tier4.ghost_builder:
                ns["ghost_builder"] = tier4.ghost_builder

            # Database direct access
            if tier4.database:
                ns["db"] = tier4.database

        return ns


async def run_gameplay_server():
    """Run the gameplay MCP server."""
    logger.info("Starting FactoryVerse Gameplay Server...")
    server = GameplayMCPServer()

    async with stdio_server() as (read_stream, write_stream):
        logger.info("Gameplay server ready")
        await server.server.run(
            read_stream,
            write_stream,
            server.server.create_initialization_options(),
        )


def main():
    """Entry point for gameplay MCP server."""
    if len(sys.argv) > 1 and sys.argv[1] in ("--help", "-h"):
        print("FactoryVerse Gameplay MCP Server")
        print()
        print("A minimal server for AI agents to play Factorio.")
        print("Exposes only two tools:")
        print("  - execute: Run Python code in the game runtime")
        print("  - query: Run SQL queries against game state")
        print()
        print("Prerequisites:")
        print("  - Factorio must be running with FactoryVerse mods")
        print("  - Use 'factoryverse-mcp' for development/infrastructure tasks")
        print()
        print("Usage: factoryverse-play [--verbose]")
        sys.exit(0)

    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    log_level = logging.DEBUG if verbose else logging.WARNING

    logging.basicConfig(
        level=log_level,
        format="[FV-Play] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    asyncio.run(run_gameplay_server())


if __name__ == "__main__":
    main()
