"""FactoryVerse MCP Server.

Provides Model Context Protocol integration for FactoryVerse,
enabling IDE integration (Cursor, Claude Desktop, etc.) for testing
and development workflows.
"""

from .server import create_mcp_server, run_mcp_server, main

__all__ = ["create_mcp_server", "run_mcp_server", "main"]
