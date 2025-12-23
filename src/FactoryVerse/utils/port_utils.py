"""Utilities for port management and validation."""
import socket
import logging

logger = logging.getLogger(__name__)


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a UDP port is available for binding.
    
    Args:
        port: Port number to check
        host: Host address to check (default: localhost)
        
    Returns:
        True if port is available, False if already in use
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((host, port))
        sock.close()
        return True
    except OSError:
        # Port is already in use
        return False
    finally:
        try:
            sock.close()
        except:
            pass


def validate_udp_port(port: int, host: str = "127.0.0.1") -> tuple[bool, str]:
    """Validate that a UDP port is available for binding.
    
    Similar to validate_rcon_connection, provides a clear success/error tuple.
    
    Args:
        port: Port number to validate
        host: Host address to validate (default: localhost)
        
    Returns:
        Tuple of (success: bool, error_message: str)
        If successful, error_message is empty string
    """
    try:
        if is_port_available(port, host):
            return True, ""
        else:
            return False, f"UDP port {port} is already in use"
    except Exception as e:
        return False, f"Error checking UDP port {port}: {e}"


def find_process_using_port(port: int) -> str:
    """Attempt to find what process is using a UDP port.
    
    This is a best-effort function that may not work on all systems.
    
    Args:
        port: Port number to check
        
    Returns:
        String describing the process, or empty string if not found
    """
    try:
        import subprocess
        # Try lsof on Unix-like systems
        result = subprocess.run(
            ["lsof", "-i", f"UDP:{port}", "-n", "-P"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0 and result.stdout:
            lines = result.stdout.strip().split('\n')
            if len(lines) > 1:
                # Skip header, return first process line
                return lines[1]
        return ""
    except Exception:
        return ""
