"""Research action implementation.

Handles all research-related operations synchronously via RconHandler.
"""

from typing import TYPE_CHECKING, Dict, Any
from dataclasses import dataclass

if TYPE_CHECKING:
    from ..infra.rcon_handler import RconHandler


@dataclass
class ResearchQueueItem:
    """Single item in research queue."""

    technology: str
    progress: float = 0.0
    level: int = 1


@dataclass
class ResearchStatus:
    """Current research status."""

    queue: list["ResearchQueueItem"]
    queue_length: int
    current_research: str | None
    tick: int


class ResearchAction:
    """Research action implementation.

    Owns all research logic:
    - enqueue(): Start researching a technology
    - dequeue(): Cancel current research
    - status(): Get current research status
    - get_queue(): Get full research queue with progress
    """

    def __init__(self, rcon_handler: "RconHandler"):
        """Initialize research action.

        Args:
            rcon_handler: RCON handler for command execution
        """
        self._rcon = rcon_handler

    def enqueue(self, technology: str) -> Dict[str, Any]:
        """Start researching a technology.

        Args:
            technology: Technology name to research

        Returns:
            Response dict with success status and technology name
        """
        cmd = self._rcon.build_command("enqueue_research", technology)
        return self._rcon.execute_and_parse_json(cmd)

    def dequeue(self) -> Dict[str, Any]:
        """Cancel current research.

        Returns:
            Response dict with success status
        """
        cmd = self._rcon.build_command("cancel_current_research")
        return self._rcon.execute_and_parse_json(cmd)

    def status(self) -> ResearchStatus:
        """Get current research status.

        Returns:
            ResearchStatus with current research and progress
        """
        cmd = self._rcon.build_command(
            "get_technologies", False
        )  # only_available=False
        techs_data = self._rcon.execute_and_parse_json(cmd)

        # Build research status
        current_research = None
        queue = []

        # Note: get_technologies doesn't give the full queue order, but
        # it gives the currently researching tech.
        # For full queue, use get_queue()
        for tech in techs_data.get("technologies", []):
            if tech.get("researching", False):
                current_research = tech.get("name")
                queue.append(
                    ResearchQueueItem(
                        technology=tech.get("name"),
                        progress=tech.get("progress", 0.0),
                        level=tech.get("level", 1),
                    )
                )
                break  # Only one active

        return ResearchStatus(
            queue=queue,
            queue_length=len(queue),
            current_research=current_research,
            tick=techs_data.get("tick", 0),
        )

    def get_queue(self) -> Dict[str, Any]:
        """Get current research queue with progress information.

        Returns:
            Research queue dict with queue, current_research, and tick
        """
        cmd = self._rcon.build_command("get_research_queue")
        return self._rcon.execute_and_parse_json(cmd)
