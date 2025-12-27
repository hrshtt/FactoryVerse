"""RCON command building and execution handler.

Owns all RCON command creation, argument serialization, and response parsing.
"""

from factorio_rcon import RCONClient
import json
from typing import Dict, Any
import logging

from FactoryVerse.dsl.types import MapPosition, Direction

logger = logging.getLogger(__name__)


class RconHandler:
    """Handles RCON command building and execution for an agent.

    Responsibilities:
    - Build RCON commands with proper argument serialization
    - Execute commands via RCON client
    - Parse JSON responses with error handling
    """

    def __init__(self, rcon_client: RCONClient, agent_id: str):
        """Initialize RCON handler.

        Args:
            rcon_client: RCON client instance for communication
            agent_id: Agent ID for remote interface calls (e.g., "agent_1")
        """
        self._rcon = rcon_client
        self.agent_id = agent_id

    def execute(self, command: str, silent: bool = True) -> str | None:
        """Execute RCON command and return raw response.

        Args:
            command: RCON command string to execute
            silent: If True, use /sc (silent), else /c (chat output)

        Returns:
            Raw RCON response string
        """
        if silent:
            full_command = f"/sc {command}"
        else:
            full_command = f"/c {command}"

        logger.info(f"RCON TX: {full_command}")
        response = self._rcon.send_command(full_command)
        logger.info(f"RCON RX: {response}")
        return response

    def _serialize_arg(self, arg):
        """Convert argument to JSON-serializable format.

        Handles special types like MapPosition objects.

        Args:
            arg: Argument to serialize

        Returns:
            JSON-serializable representation
        """
        # Handle Position/MapPosition/EntityPosition objects
        if isinstance(arg, MapPosition):
            return {"x": arg.x, "y": arg.y}
        elif isinstance(arg, Direction):
            return arg.value
        return arg

    def build_command(self, method: str, *args) -> str:
        """Build RCON command string for remote interface method call.

        Args:
            method: Remote interface method name
            *args: Positional arguments for the method

        Returns:
            Complete RCON command string ready for execution

        Example:
            >>> handler.build_command("walk_to", {"x": 10, "y": 20}, True, {})
            "rcon.print(helpers.table_to_json(remote.call('agent_1', 'walk_to', ...)))"
        """
        remote_call = f"remote.call('{self.agent_id}', '{method}'"

        if args:
            # Convert args to JSON-serializable format and pass as table
            serialized_args = [self._serialize_arg(arg) for arg in args]
            args_json = json.dumps(serialized_args)
            remote_call += f", table.unpack(helpers.json_to_table('{args_json}'))"

        remote_call += ")"
        return f"rcon.print(helpers.table_to_json({remote_call}))"

    def execute_and_parse_json(self, command: str) -> Dict[str, Any]:
        """Execute RCON command and parse JSON response.

        Args:
            command: RCON command string to execute

        Returns:
            Parsed JSON response as dictionary

        Raises:
            RuntimeError: If command returns empty response or invalid JSON
        """
        result = self.execute(command)
        if not result or not result.strip():
            raise RuntimeError(
                f"RCON command returned empty response. Command: {command}"
            )

        try:
            return json.loads(result)
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode failed. Result: '{result}'")
            raise RuntimeError(
                f"Failed to decode JSON from RCON. Response: '{result}'. Error: {e}"
            ) from e
