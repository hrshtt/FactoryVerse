"""FactoryVerse MCP Server.

Provides Model Context Protocol integration for FactoryVerse,
enabling IDE integration (Cursor, Claude Desktop, etc.) for testing
and development workflows.
"""

from .server import create_mcp_server, run_mcp_server


def main():
    """Entry point for factoryverse-mcp command."""
    import asyncio
    import sys

    print("Starting FactoryVerse MCP server...")
    print("Connect your IDE (Cursor, Claude Desktop, etc.) to use FactoryVerse tools.")
    print("Press Ctrl+C to stop.")
    try:
        asyncio.run(run_mcp_server())
    except KeyboardInterrupt:
        print("\nMCP server stopped.")
        sys.exit(0)


__all__ = ["create_mcp_server", "run_mcp_server", "main"]
