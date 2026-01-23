"""Base types and protocols for scenario adapters.

Scenario adapters provide type-safe Python interfaces to Factorio scenarios'
remote interfaces. They bridge Tier 2 (scenario loaded) with Tier 4 (runtime)
by exposing scenario-specific capabilities in a discoverable way.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable
import json


@runtime_checkable
class RCONClientProtocol(Protocol):
    """Protocol for RCON client used by adapters."""

    def send_command(self, command: str) -> str: ...


class ScenarioAdapter(ABC):
    """Base class for scenario-specific Python adapters.

    Adapters wrap a Factorio scenario's remote interface, providing:
    - Type-safe method signatures
    - Python dataclass return types
    - Automatic JSON serialization/deserialization

    Subclasses must implement:
    - scenario_name: The Factorio scenario name (e.g., "lab-grid")
    - interface_name: The Lua remote interface name (e.g., "lab_grid")
    - is_available(): Check if the interface exists in the running game
    """

    scenario_name: str  # e.g., "lab-grid"
    interface_name: str  # e.g., "lab_grid"

    def __init__(self, rcon: RCONClientProtocol):
        self._rcon = rcon

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this scenario's remote interface is available."""
        pass

    def _check_interface_exists(self) -> bool:
        """Check if the remote interface exists in Factorio."""
        result = self._rcon.send_command(
            f'/silent-command rcon.print(remote.interfaces.{self.interface_name} ~= nil)'
        )
        return result.strip().lower() == "true"

    def _remote_call(self, method: str, *args) -> Any:
        """Call a method on the scenario's remote interface.

        Args:
            method: Method name on the remote interface
            *args: Arguments to pass (will be serialized to Lua)

        Returns:
            Parsed result (JSON for tables, primitive for bool/number/string/nil)
        """
        lua_args = self._serialize_args(args)

        # Handle both table and primitive returns
        command = (
            f'/silent-command '
            f'local result = remote.call("{self.interface_name}", "{method}"{lua_args}); '
            f'if type(result) == "table" then '
            f'rcon.print(helpers.table_to_json(result)) '
            f'elseif result == nil then '
            f'rcon.print("__nil__") '
            f'elseif type(result) == "boolean" then '
            f'rcon.print(result and "__true__" or "__false__") '
            f'else '
            f'rcon.print(tostring(result)) '
            f'end'
        )

        result = self._rcon.send_command(command)

        if result.startswith("Cannot execute command"):
            raise ScenarioError(f"Remote call failed: {result}")

        result = result.strip()

        if not result or result == "__nil__":
            return None
        if result == "__true__":
            return True
        if result == "__false__":
            return False

        try:
            return json.loads(result)
        except json.JSONDecodeError:
            # Return as string if not JSON
            return result

    def _serialize_args(self, args: tuple) -> str:
        """Serialize Python arguments to Lua syntax."""
        if not args:
            return ""

        parts = []
        for arg in args:
            parts.append(self._to_lua(arg))

        return ", " + ", ".join(parts)

    def _to_lua(self, value: Any) -> str:
        """Convert a Python value to Lua syntax."""
        if value is None:
            return "nil"
        elif isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, str):
            # Escape quotes in string
            escaped = value.replace('\\', '\\\\').replace('"', '\\"')
            return f'"{escaped}"'
        elif isinstance(value, dict):
            pairs = []
            for k, v in value.items():
                # Always use bracket notation for safety (handles hyphens, spaces, etc.)
                pairs.append(f'[{self._to_lua(k)}] = {self._to_lua(v)}')
            return "{" + ", ".join(pairs) + "}"
        elif isinstance(value, (list, tuple)):
            items = [self._to_lua(v) for v in value]
            return "{" + ", ".join(items) + "}"
        else:
            raise ValueError(f"Cannot serialize {type(value)} to Lua")


class ScenarioError(Exception):
    """Error from scenario remote interface."""
    pass


# Common dataclasses used across scenarios

@dataclass
class Position:
    """A 2D position in tile coordinates."""
    x: float
    y: float

    @classmethod
    def from_dict(cls, d: dict) -> "Position":
        return cls(x=d["x"], y=d["y"])


@dataclass
class BoundingBox:
    """A rectangular area defined by two corners."""
    left_top: Position
    right_bottom: Position

    @classmethod
    def from_dict(cls, d: dict) -> "BoundingBox":
        return cls(
            left_top=Position.from_dict(d["left_top"]),
            right_bottom=Position.from_dict(d["right_bottom"])
        )

    @property
    def width(self) -> float:
        return self.right_bottom.x - self.left_top.x

    @property
    def height(self) -> float:
        return self.right_bottom.y - self.left_top.y

    @property
    def center(self) -> Position:
        return Position(
            x=(self.left_top.x + self.right_bottom.x) / 2,
            y=(self.left_top.y + self.right_bottom.y) / 2
        )
