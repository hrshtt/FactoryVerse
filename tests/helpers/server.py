"""
Factorio server management for tests.

Handles Docker container lifecycle and RCON connection.
"""

import subprocess
import time
import json
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass

from factorio_rcon import RCONClient


@dataclass
class ServerConfig:
    """Server connection configuration."""

    host: str = "localhost"
    rcon_port: int = 27000
    rcon_password: str = "factorio"
    container_name: str = "factorio_0"
    startup_timeout: int = 30
    compose_path: Optional[Path] = None

    def __post_init__(self):
        if self.compose_path is None:
            # Default to project root
            self.compose_path = (
                Path(__file__).parent.parent.parent / "docker-compose.yml"
            )


class RconConnection:
    """
    RCON connection with xpcall wrapper for error handling.

    All commands use xpcall to capture Lua tracebacks.
    """

    def __init__(self, client: RCONClient):
        self.client = client

    def execute(self, lua_code: str) -> Dict[str, Any]:
        """
        Execute Lua code with xpcall wrapper.

        Args:
            lua_code: Lua code to execute (without /c prefix)

        Returns:
            Dict with 'success' and either 'result' or 'error'
        """
        # Wrap in xpcall to catch errors and get tracebacks
        wrapped = (
            f"/c local success, result = xpcall(function() {lua_code} end, debug.traceback); "
            f"if success then "
            f"rcon.print(helpers.table_to_json({{success = true, result = result}})) "
            f"else "
            f"rcon.print(helpers.table_to_json({{success = false, error = result}})) "
            f"end"
        )

        response = self.client.send_command(wrapped)

        if response is None:
            return {"success": False, "error": "No response from RCON"}

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return {"success": False, "error": f"JSON parse error: {response[:500]}"}

    def call(self, interface: str, method: str, *args) -> Any:
        """
        Call a remote interface method.

        Args:
            interface: Remote interface name (e.g., "agent", "test_ground")
            method: Method name
            *args: Arguments (will be converted to Lua syntax)

        Returns:
            Result from remote call

        Raises:
            RuntimeError: If call fails
        """
        lua_args = ", ".join(self._to_lua(arg) for arg in args)
        if lua_args:
            lua_code = f'return remote.call("{interface}", "{method}", {lua_args})'
        else:
            lua_code = f'return remote.call("{interface}", "{method}")'

        result = self.execute(lua_code)

        if not result.get("success"):
            raise RuntimeError(
                f"{interface}.{method} failed: {result.get('error', 'unknown error')}"
            )

        return result.get("result")

    def _to_lua(self, value: Any) -> str:
        """Convert Python value to Lua literal."""
        if value is None:
            return "nil"
        elif isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, str):
            return f'"{value}"'
        elif isinstance(value, dict):
            items = [f'["{k}"] = {self._to_lua(v)}' for k, v in value.items()]
            return "{" + ", ".join(items) + "}"
        elif isinstance(value, (list, tuple)):
            items = [self._to_lua(v) for v in value]
            return "{" + ", ".join(items) + "}"
        else:
            raise ValueError(f"Cannot convert {type(value)} to Lua")

    def ping(self) -> bool:
        """Check if RCON is responsive."""
        try:
            result = self.client.send_command('/c rcon.print("pong")')
            return result == "pong"
        except Exception:
            return False

    def list_interfaces(self) -> list[str]:
        """Get list of available remote interfaces."""
        result = self.execute(
            "local ifaces = {}; "
            "for name, _ in pairs(remote.interfaces) do table.insert(ifaces, name) end; "
            "return ifaces"
        )
        if result.get("success"):
            return result.get("result", [])
        return []


class FactorioServer:
    """
    Manages Factorio server lifecycle for testing.

    Handles:
    - Docker container start/stop
    - RCON connection management
    - Server health checks
    """

    def __init__(self, config: Optional[ServerConfig] = None):
        self.config = config or ServerConfig()
        self._rcon: Optional[RconConnection] = None
        self._started_by_us = False

    def ensure_running(self) -> RconConnection:
        """
        Ensure server is running and return RCON connection.

        Starts the Docker container if not running.
        """
        if self._rcon and self._rcon.ping():
            return self._rcon

        # Check if container is running
        if not self._is_container_running():
            self._start_container()
            self._started_by_us = True

        # Wait for RCON to be ready
        self._rcon = self._wait_for_rcon()
        return self._rcon

    def restart(self) -> RconConnection:
        """
        Restart the server and return new RCON connection.

        Kicks all connected players first to allow smooth reconnection.
        Use when mod source code has changed.
        """
        # Kick players before restart to allow reconnection without client restart
        if self._rcon and self._rcon.ping():
            self._kick_all_players("Server restarting")

        self._restart_container()
        self._rcon = self._wait_for_rcon()
        return self._rcon

    def stop(self):
        """Stop the server if we started it."""
        if self._started_by_us:
            self._stop_container()
            self._started_by_us = False
        self._rcon = None

    @property
    def rcon(self) -> RconConnection:
        """Get current RCON connection, ensuring server is running."""
        return self.ensure_running()

    def _is_container_running(self) -> bool:
        """Check if Docker container is running."""
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(self.config.compose_path),
                "ps",
                "-q",
                self.config.container_name,
            ],
            capture_output=True,
            text=True,
        )
        return bool(result.stdout.strip())

    def _start_container(self):
        """Start the Docker container."""
        print(f"Starting {self.config.container_name}...")
        subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(self.config.compose_path),
                "up",
                "-d",
                self.config.container_name,
            ],
            check=True,
            capture_output=True,
        )

    def _stop_container(self):
        """Stop the Docker container."""
        print(f"Stopping {self.config.container_name}...")
        subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(self.config.compose_path),
                "stop",
                self.config.container_name,
            ],
            check=True,
            capture_output=True,
        )

    def _restart_container(self):
        """Restart the Docker container."""
        print(f"Restarting {self.config.container_name}...")
        subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(self.config.compose_path),
                "restart",
                self.config.container_name,
            ],
            check=True,
            capture_output=True,
        )

    def _kick_all_players(self, reason: str = "Server restarting"):
        """
        Kick all connected players before restart.

        This allows clients to reconnect after restart without needing
        to restart the client as well.
        """
        if not self._rcon:
            return

        try:
            # Get all connected players
            result = self._rcon.execute(
                "local players = {}; "
                "for _, p in pairs(game.players) do "
                "if p.connected then table.insert(players, p.name) end "
                "end; "
                "return players"
            )

            if result.get("success") and result.get("result"):
                players = result["result"]
                for player_name in players:
                    # Use /kick command (not Lua) for proper disconnection
                    self._rcon.client.send_command(f"/kick {player_name} {reason}")
                    print(f"Kicked player: {player_name}")
        except Exception as e:
            # Don't fail restart if kick fails
            print(f"Warning: Could not kick players: {e}")

    def _wait_for_rcon(self) -> RconConnection:
        """Wait for RCON to become available."""
        start = time.time()
        last_error = None

        while time.time() - start < self.config.startup_timeout:
            try:
                client = RCONClient(
                    self.config.host, self.config.rcon_port, self.config.rcon_password
                )
                conn = RconConnection(client)
                if conn.ping():
                    elapsed = time.time() - start
                    print(f"RCON ready in {elapsed:.1f}s")
                    return conn
            except Exception as e:
                last_error = e
            time.sleep(0.5)

        raise TimeoutError(
            f"Server did not become ready in {self.config.startup_timeout}s. "
            f"Last error: {last_error}"
        )
