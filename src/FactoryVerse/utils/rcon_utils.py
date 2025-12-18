"""
RCON utility helpers for FactoryVerse.

Provides utilities for working with Factorio RCON, including handling
the first-command warning issue.
"""

from factorio_rcon import RCONClient
from typing import Optional


def initialize_rcon_connection(client: RCONClient) -> None:
    """
    Initialize RCON connection by sending a dummy command.
    
    Factorio sends a warning on the first command and only starts executing
    from the second command. This function handles that by sending a test
    command twice to ensure the connection is ready.
    
    Args:
        client: RCONClient instance to initialize
        
    Example:
        >>> rcon = RCONClient("localhost", 27100, "factorio")
        >>> initialize_rcon_connection(rcon)
        >>> # Now rcon is ready to use
    """
    # Send test command twice - first gets warning, second executes
    client.send_command("/c rcon.print('hello world')")
    result = client.send_command("/c rcon.print('hello world')")
    
    # Verify connection works
    if result is None or "hello world" not in result:
        raise RuntimeError(
            f"RCON connection test failed. Expected 'hello world', got: {result}"
        )


def create_rcon_client(
    host: str = "localhost",
    port: int = 27100,
    password: str = "factorio",
    initialize: bool = True
) -> RCONClient:
    """
    Create and optionally initialize an RCON client.
    
    Args:
        host: RCON server host
        port: RCON server port
        password: RCON password
        initialize: If True, run initialization to clear first-command warning
        
    Returns:
        RCONClient instance ready to use
        
    Example:
        >>> rcon = create_rcon_client()
        >>> # Client is ready to use immediately
    """
    client = RCONClient(host, port, password)
    
    if initialize:
        initialize_rcon_connection(client)
    
    return client


def safe_send_command(client: RCONClient, command: str) -> Optional[str]:
    """
    Send a command and handle None responses gracefully.
    
    Args:
        client: RCONClient instance
        command: Command to send
        
    Returns:
        Command result, or None if command failed
    """
    try:
        result = client.send_command(command)
        return result
    except Exception as e:
        print(f"RCON command failed: {e}")
        return None
