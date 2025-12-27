"""Walking action implementation with dataclass response types.

Handles all walking-related operations: walk to position, stop walking.
"""

from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING, Dict
import logging

from FactoryVerse.dsl.types import MapPosition
from FactoryVerse.agent.models import (
    AsyncActionResponse,
    AsyncActionCompletion,
    ActionResponse,
)

if TYPE_CHECKING:
    from ..infra.rcon_handler import RconHandler
    from ..infra.async_listener import AsyncActionListener

logger = logging.getLogger(__name__)


# =============================================================================
# ACTION RESPONSE TYPES
# =============================================================================


@dataclass
class WalkingStarted(AsyncActionResponse):
    """Response when walking action is queued/started.

    RCON Contract: RemoteInterface.lua walk_to.returns.schema

    Returned immediately when walk() is called. If queued=True, the action
    is running asynchronously and completion will come via UDP.
    """

    pass  # Inherits all fields from AsyncActionResponse


@dataclass
class WalkingCompleted(AsyncActionCompletion):
    """Response when walking action completes.

    RCON Contract: RemoteInterface.lua walk_to.returns.completion

    Received via UDP when walking completes. Contains final position and timing.
    """

    position: Dict[str, float] = field(default_factory=dict)

    @property
    def final_position(self) -> MapPosition:
        """Get final position as MapPosition."""
        return MapPosition(x=self.position["x"], y=self.position["y"])


@dataclass
class WalkingStopped(ActionResponse):
    """Response when walking action is stopped.

    RCON Contract: RemoteInterface.lua stop_walking.returns

    Returned when stop_walking() is called.
    """

    position: Optional[Dict[str, float]] = None


# =============================================================================
# WALKING ACTION
# =============================================================================


class MovementAction:
    """Walking action implementation.

    Owns all walking logic:
    - walk(): Walk to a target position
    - stop(): Stop current walking action

    All methods return structured dataclass response types for type safety.
    """

    def __init__(
        self, rcon_handler: "RconHandler", async_listener: "AsyncActionListener"
    ):
        """Initialize walking action.

        Args:
            rcon_handler: RCON handler for command execution
            async_listener: Async listener for action completion
        """
        self._rcon = rcon_handler
        self._listener = async_listener

    async def walk_to(
        self,
        goal: MapPosition,
        strict_goal: bool = False,
        options: Optional[Dict] = None,
        timeout: Optional[int] = None,
    ) -> MapPosition:
        """Walk to a target position.

        Args:
            goal: Target position to walk to
            strict_goal: If True, fail if exact position unreachable
            options: Additional pathfinding options (optional)
            timeout: Optional timeout in seconds

        Returns:
            Final MapPosition reached

        Raises:
            RuntimeError: If walking fails to start or times out
        """
        if options is None:
            options = {}

        # Build and execute RCON command
        cmd = self._rcon.build_command("walk_to", goal, strict_goal, options)
        response_dict = self._rcon.execute_and_parse_json(cmd)
        response = WalkingStarted.from_dict(response_dict)

        # Check if walking started successfully
        if not response.is_queued:
            reason = response.reason or "unknown"
            raise RuntimeError(f"Failed to start walking: {reason}")

        # Wait for completion via UDP
        completion_dict = await self._listener.await_action(response, timeout=timeout)
        completion = WalkingCompleted.from_dict(completion_dict)

        # Return final position
        return completion.final_position

    def stop(self) -> WalkingStopped:
        """Stop current walking action.

        Returns:
            WalkingStopped response with stop status
        """
        cmd = self._rcon.build_command("stop_walking")
        response_dict = self._rcon.execute_and_parse_json(cmd)
        return WalkingStopped.from_dict(response_dict)

    @property
    def current_position(self) -> MapPosition:
        """Get current agent position."""
        cmd = self._rcon.build_command("get_position")
        response_dict = self._rcon.execute_and_parse_json(cmd)
        return MapPosition.from_dict(response_dict)

    def _teleport(self, goal: MapPosition) -> None:
        """Teleport to a target position."""
        cmd = self._rcon.build_command("teleport", goal)
        self._rcon.execute_and_parse_json(cmd)
