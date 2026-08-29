"""Walking action implementation with dataclass response types.

Handles all walking-related operations: walk to position, walk to entity, stop walking.

Walking Modes:
- Position-only: walk_to(goal) - walks to a map position
- Entity-aware: _walk_to_entity(name, position) - internal; reached as entity.walk_to() / resource.walk_to()
"""

from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING, Dict
import asyncio
import logging

from FactoryVerse.game.factory.types import MapPosition
from FactoryVerse.game.agent.models import (
    AsyncActionResponse,
    AsyncActionCompletion,
    ActionResponse,
)

if TYPE_CHECKING:
    from ..infra.rcon_handler import RconHandler
    from ..infra.async_listener import AsyncActionListener

logger = logging.getLogger(__name__)


# =============================================================================
# ERROR TYPES
# =============================================================================


class WalkingError(RuntimeError):
    """Base walking error."""

    pass


class WalkingUnreachableError(WalkingError):
    """Target is definitively unreachable after exhausting all approach options.

    This means:
    - For entity-aware walking: all candidate tiles were tried, no path found
    - For position-only walking: no path to position exists

    The agent may need to destroy/deconstruct obstacles to reach the target.
    """

    def __init__(
        self,
        message: str,
        failure_type: str = "blocked_path",
        candidates_tried: int = 1,
        agent_position: Optional[MapPosition] = None,
        target_position: Optional[MapPosition] = None,
    ):
        spatial = ""
        if agent_position is not None and target_position is not None:
            dx = target_position.x - agent_position.x
            dy = target_position.y - agent_position.y
            distance = (dx * dx + dy * dy) ** 0.5
            ns = "south" if dy > 0 else "north"
            ew = "east" if dx > 0 else "west"
            spatial = (
                f" [you are at ({agent_position.x:.1f}, {agent_position.y:.1f}); "
                f"target ({target_position.x:.1f}, {target_position.y:.1f}) is "
                f"{distance:.1f} tiles to the {ns}-{ew}. If this is far beyond "
                f"your working area, the target may be outside your reachable "
                f"map bounds rather than merely obstructed]"
            )
        super().__init__(message + spatial)
        self.failure_type = failure_type
        self.candidates_tried = candidates_tried
        self.agent_position = agent_position
        self.target_position = target_position


class WalkingEntityNotFoundError(WalkingError):
    """Entity reference is no longer valid.

    The entity may have been destroyed, picked up, or moved.
    Refresh the entity reference and try again.
    """

    def __init__(self, entity_name: str, position: MapPosition):
        super().__init__(f"Entity '{entity_name}' not found at {position}")
        self.entity_name = entity_name
        self.position = position


class WalkingNoStandableTilesError(WalkingError):
    """No standable tiles exist within reach of the target entity.

    The entity may be completely surrounded by obstacles.
    """

    def __init__(self, entity_name: str):
        super().__init__(f"No standable tiles within reach of '{entity_name}'")
        self.entity_name = entity_name


class WalkingTimeoutError(WalkingError):
    """Walking exceeded its deadline and was cancelled in Factorio."""

    def __init__(self, action_id: Optional[str], target: MapPosition):
        super().__init__(
            f"Walking action {action_id or '<unknown>'} timed out while moving "
            f"toward {target}; stop_walking was issued before returning control"
        )
        self.action_id = action_id
        self.target = target


# =============================================================================
# ACTION RESPONSE TYPES
# =============================================================================


@dataclass
class WalkingStarted(AsyncActionResponse):
    """Response when walking action is queued/started.

    RCON Contract: RemoteInterface.lua walk_to.returns.schema

    Returned immediately when walk() is called. If queued=True, the action
    is running asynchronously and completion will come via UDP.

    If queued=False and success=True, agent was already at destination.
    If queued=False and success=False, walking failed immediately (entity not found, etc).
    """

    failure_type: Optional[str] = None
    position: Optional[Dict[str, float]] = None  # Present if already at destination
    interaction_reachable: Optional[bool] = None

    @property
    def already_at_destination(self) -> bool:
        """True if agent was already at destination (no walking needed)."""
        return self.success and not self.queued and self.position is not None


@dataclass
class WalkingCompleted(AsyncActionCompletion):
    """Response when walking action completes.

    RCON Contract: RemoteInterface.lua walk_to.returns.completion

    Received via UDP when walking completes. Contains final position and timing.
    """

    position: Dict[str, float] = field(default_factory=dict)
    interaction_reachable: Optional[bool] = None

    @property
    def final_position(self) -> MapPosition:
        """Get final position as MapPosition."""
        if not self.position or "x" not in self.position:
            raise ValueError(
                f"WalkingCompleted has no position data. "
                f"Current position value: {self.position!r}. "
                f"Check if UDP payload includes 'position' field."
            )
        return MapPosition(x=self.position["x"], y=self.position["y"])


@dataclass
class WalkingFailed(AsyncActionCompletion):
    """Response when walking action fails.

    Received via UDP when walking fails after exhausting all options.
    """

    failure_type: str = "blocked_path"
    candidates_tried: int = 1
    goal: Optional[Dict[str, float]] = None
    message: Optional[str] = None


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
    - walk_to(): Walk to a target position
    - _walk_to_entity(): Walk to an entity with fallback logic (internal; the objects delegate here)
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
            WalkingUnreachableError: If position is unreachable
            RuntimeError: If walking fails for other reasons
        """
        return await self._walk_internal(
            goal=goal,
            strict_goal=strict_goal,
            options=options,
            entity_ref=None,
            timeout=timeout,
        )

    async def _walk_to_entity(
        self,
        entity_name: str,
        entity_position: MapPosition,
        timeout: Optional[int] = None,
    ) -> MapPosition:
        """Walk to an entity with fallback logic — INTERNAL.

        The agent-visible route is ``entity.walk_to()`` / ``resource.walk_to()``
        (API_AFFORDANCE_REDESIGN §2.1): the object promotes its view on arrival,
        which this flat form cannot do because it holds no object. Deleted from
        the namespace 2026-08-29; kept as the mechanism the objects delegate to.

        Uses entity-aware walking: computes candidate approach tiles around
        the entity and tries each until path succeeds or all exhausted.

        Args:
            entity_name: Name of the entity (e.g., "stone-furnace")
            entity_position: Position of the entity
            timeout: Optional timeout in seconds

        Returns:
            Final MapPosition reached

        Raises:
            WalkingEntityNotFoundError: If entity not found at position
            WalkingNoStandableTilesError: If no standable tiles around entity
            WalkingUnreachableError: If all approach paths are blocked
        """
        entity_ref = {
            "name": entity_name,
            "position": {"x": entity_position.x, "y": entity_position.y},
        }
        return await self._walk_internal(
            goal=entity_position,
            strict_goal=False,
            options=None,
            entity_ref=entity_ref,
            timeout=timeout,
        )

    async def _walk_internal(
        self,
        goal: MapPosition,
        strict_goal: bool,
        options: Optional[Dict],
        entity_ref: Optional[Dict],
        timeout: Optional[int],
    ) -> MapPosition:
        """Internal walk implementation handling both position and entity modes."""
        if options is None:
            options = {}

        # Build and execute RCON command
        cmd = self._rcon.build_command(
            "walk_to", goal, strict_goal, options, entity_ref
        )
        response_dict = self._rcon.execute_and_parse_json(cmd)
        response = WalkingStarted.from_dict(response_dict)

        # Check for immediate failures
        if not response.success:
            failure_type = response_dict.get("failure_type", "unknown")
            message = response_dict.get("message", "Walking failed")

            if failure_type == "entity_not_found" and entity_ref:
                raise WalkingEntityNotFoundError(entity_ref["name"], goal)
            elif failure_type == "no_standable_tiles" and entity_ref:
                raise WalkingNoStandableTilesError(entity_ref["name"])
            else:
                raise WalkingError(message)

        # Check if already at destination
        # Note: 'already_at_destination' and 'position' are fields on WalkingStarted dataclass
        if isinstance(response, WalkingStarted) and response.already_at_destination:
            if entity_ref and response.interaction_reachable is not True:
                raise WalkingUnreachableError(
                    message=(
                        "Entity walk completed without authoritative interaction "
                        "reach confirmation"
                    ),
                    failure_type="interaction_unvalidated",
                    agent_position=MapPosition.from_dict(response.position),
                    target_position=goal,
                )
            pos = response.position
            # Ensure pos is not None before accessing keys
            if pos:
                return MapPosition(x=pos["x"], y=pos["y"])

        # Check if walking was queued
        if not response.is_queued:
            reason = response.reason or "unknown"
            raise RuntimeError(f"Failed to start walking: {reason}")

        # Wait for completion via UDP
        try:
            completion_dict = await self._listener.await_action(
                response, timeout=timeout
            )
        except asyncio.TimeoutError as exc:
            try:
                self.stop()
            except Exception as stop_exc:
                logger.error(
                    "Failed to cancel timed-out walking action %s: %s",
                    response.action_id,
                    stop_exc,
                )
            raise WalkingTimeoutError(response.action_id, goal) from exc
        logger.debug(f"Walking completion_dict: {completion_dict}")

        # Check for failure status
        status = completion_dict.get("status")
        if status == "failed":
            failure_type = completion_dict.get("failure_type", "blocked_path")
            candidates_tried = completion_dict.get("candidates_tried", 1)
            message = completion_dict.get("message", "Walking failed")

            agent_pos: Optional[MapPosition] = None
            try:
                agent_pos = self.current_position
            except Exception:
                pass  # spatial context is best-effort; never mask the real error

            if failure_type == "entity_not_found" and entity_ref:
                raise WalkingEntityNotFoundError(entity_ref["name"], goal)

            raise WalkingUnreachableError(
                message=message,
                failure_type=failure_type,
                candidates_tried=candidates_tried,
                agent_position=agent_pos,
                target_position=goal,
            )

        # UDP payload nests action-specific data in 'result' field
        # Flatten result dict into completion_dict for from_dict parsing
        if "result" in completion_dict and isinstance(completion_dict["result"], dict):
            for key, value in completion_dict["result"].items():
                if key not in completion_dict:
                    completion_dict[key] = value

        completion = WalkingCompleted.from_dict(completion_dict)
        logger.debug(f"WalkingCompleted position: {completion.position}")

        if entity_ref and completion.interaction_reachable is not True:
            agent_position: Optional[MapPosition] = None
            try:
                agent_position = completion.final_position
            except ValueError:
                pass
            raise WalkingUnreachableError(
                message=(
                    "Entity walk completed without authoritative interaction "
                    "reach confirmation"
                ),
                failure_type="interaction_unvalidated",
                agent_position=agent_position,
                target_position=goal,
            )

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
