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
    host: Optional[str] = None,
    port: Optional[int] = None,
    password: Optional[str] = None,
    initialize: bool = True
) -> RCONClient:
    """
    Create and optionally initialize an RCON client.
    
    Args:
        host: RCON server host (defaults to config.rcon_host)
        port: RCON server port (defaults to config.rcon_client_port)
        password: RCON password (defaults to config.rcon_password)
        initialize: If True, run initialization to clear first-command warning
        
    Returns:
        RCONClient instance ready to use
        
    Example:
        >>> rcon = create_rcon_client()  # Uses config defaults
        >>> # Client is ready to use immediately
    """
    from FactoryVerse.config import get_config
    
    cfg = get_config()
    host = host or cfg.rcon_host
    port = port or cfg.rcon_client_port
    password = password or cfg.rcon_password
    
    client = RCONClient(host, port, password)
    
    if initialize:
        initialize_rcon_connection(client)
    
    return client


def validate_rcon_connection(
    host: Optional[str] = None,
    port: Optional[int] = None,
    password: Optional[str] = None
) -> tuple[bool, Optional[str]]:
    """
    Validate that Factorio RCON is available.
    
    This function attempts to establish an RCON connection and send a test
    command to verify that the Factorio server is running and accessible.
    
    Args:
        host: RCON server host (defaults to config.rcon_host)
        port: RCON server port (defaults to config.rcon_client_port)
        password: RCON password (defaults to config.rcon_password)
        
    Returns:
        (success, error_message) tuple where:
        - success is True if connection works, False otherwise
        - error_message is None on success, error description on failure
        
    Example:
        >>> success, error = validate_rcon_connection()  # Uses config defaults
        >>> if not success:
        ...     print(f"Connection failed: {error}")
    """
    from FactoryVerse.config import get_config
    
    cfg = get_config()
    host = host or cfg.rcon_host
    port = port or cfg.rcon_client_port
    password = password or cfg.rcon_password
    
    try:
        # Attempt to create client
        client = RCONClient(host, port, password)
        
        # Send test command (Factorio sends warning on first command)
        client.send_command("/c rcon.print('connection_test')")
        result = client.send_command("/c rcon.print('connection_test')")
        
        # Verify we got a response
        if result is None:
            return False, "RCON connection established but no response received"
        
        if "connection_test" not in result:
            return False, f"RCON connection test failed. Expected 'connection_test', got: {result}"
        
        return True, None
        
    except ConnectionRefusedError:
        return False, f"Connection refused. Is Factorio running on {host}:{port}?"
    except TimeoutError:
        return False, f"Connection timeout. Server at {host}:{port} not responding"
    except Exception as e:
        return False, f"Connection error: {type(e).__name__}: {e}"


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
