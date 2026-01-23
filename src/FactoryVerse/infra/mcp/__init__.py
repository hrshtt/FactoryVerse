"""FactoryVerse MCP Servers.

Provides Model Context Protocol integration for FactoryVerse:

- Development Server (factoryverse-mcp): Full tools for testing, infrastructure,
  session management, and debugging. Use this when working on the codebase.

- Gameplay Server (factoryverse-play): Minimal tools (execute + query) for AI
  agents playing Factorio. Abstracts away all infrastructure details.
"""

from .server import create_mcp_server, run_mcp_server, main
from .gameplay_server import GameplayMCPServer, run_gameplay_server

__all__ = [
    # Development server
    "create_mcp_server",
    "run_mcp_server",
    "main",
    # Gameplay server
    "GameplayMCPServer",
    "run_gameplay_server",
]
