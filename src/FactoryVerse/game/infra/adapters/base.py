"""Base class for remote interface adapters.

Provides common functionality for calling Lua remote interfaces via RCON.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Protocol, Union

logger = logging.getLogger(__name__)


class RCONClientProtocol(Protocol):
    """Protocol for RCON client used by adapters."""

    def send_command(self, command: str) -> str: ...


class RemoteInterfaceAdapter:
    """Base class for remote interface adapters.

    Provides:
    - Type-safe method wrappers for Lua remote.call()
    - Automatic JSON serialization/deserialization
    - Lua table construction from Python dicts
    - Error handling and logging
    """

    interface_name: str  # e.g., "agent", "admin", "map"

    def __init__(self, rcon: RCONClientProtocol):
        """Initialize adapter with RCON connection.

        Args:
            rcon: RCON client instance (factorio_rcon.RCONClient or compatible)
        """
        self._rcon = rcon

    def _call(
        self,
        method: str,
        *args: Any,
        returns_json: bool = True,
    ) -> Any:
        """Call a remote interface method.

        Args:
            method: Method name on the interface
            *args: Arguments to pass (will be serialized to Lua)
            returns_json: If True, parse response as JSON. If False, return raw string.

        Returns:
            Parsed JSON response, raw string, or None if empty response
        """
        # Build argument string
        lua_args = ", ".join(self._to_lua(arg) for arg in args)

        if returns_json:
            cmd = (
                f"/c local res = remote.call('{self.interface_name}', '{method}'"
                f"{', ' + lua_args if lua_args else ''}); "
                "rcon.print(helpers.table_to_json(res))"
            )
        else:
            cmd = (
                f"/c remote.call('{self.interface_name}', '{method}'"
                f"{', ' + lua_args if lua_args else ''})"
            )

        result = self._rcon.send_command(cmd)

        if not returns_json:
            return result

        if result and result.strip():
            try:
                return json.loads(result)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse JSON response: {e}")
                logger.debug(f"Raw response: {result}")
                return None
        return None

    def _to_lua(self, value: Any) -> str:
        """Convert Python value to Lua literal.

        Args:
            value: Python value to convert

        Returns:
            Lua literal string representation
        """
        if value is None:
            return "nil"
        elif isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, str):
            # Escape quotes and backslashes
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        elif isinstance(value, dict):
            items = ", ".join(
                f'["{k}"] = {self._to_lua(v)}' for k, v in value.items()
            )
            return "{" + items + "}"
        elif isinstance(value, (list, tuple)):
            items = ", ".join(self._to_lua(v) for v in value)
            return "{" + items + "}"
        else:
            raise TypeError(f"Cannot convert {type(value).__name__} to Lua: {value}")

    def is_available(self) -> bool:
        """Check if this interface is available in the running game.

        Returns:
            True if the remote interface exists
        """
        result = self._rcon.send_command(
            f"/silent-command rcon.print(remote.interfaces.{self.interface_name} ~= nil)"
        )
        return result.strip().lower() == "true"
