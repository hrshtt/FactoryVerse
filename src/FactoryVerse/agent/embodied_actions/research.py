"""Research action implementation.

Handles all research-related operations synchronously via RconHandler.
"""

from typing import TYPE_CHECKING, Dict, Any, Optional, List
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from ..infra.rcon_handler import RconHandler


@dataclass
class ResearchQueueItem:
    """Single item in research queue."""

    technology: str
    progress: float = 0.0
    level: int = 1


@dataclass
class QueuedTechnology:
    """Basic information about a queued technology.
    
    Used in ResearchStatus when technologies are queued.
    """

    position: int
    """Position in the research queue (1-based)."""
    name: str
    """Technology name."""
    is_current: bool
    """True if this is the currently active research (position 1)."""


@dataclass
class ResearchStatus:
    """Comprehensive research status with progressive detail levels.
    
    **For Agents**: Use this to check research state and progress.
    
    The status provides different levels of detail based on research state:
    - **Minimal**: If no research is queued or active
    - **Queued**: If research is queued but not active (includes queue info)
    - **Active**: If research is actively progressing (includes full progress details)
    
    All status objects include:
    - `queued`: Whether technologies are queued beyond current
    - `active`: Whether research is actively being worked on
    - `progress`: Current progress (0.0 to 1.0)
    - `status`: Human-readable status message
    - `tick`: Game tick when status was retrieved
    
    Additional fields are populated based on state:
    - If queued: `queue_length`, `current_research`, `queue`
    - If active: `units_completed`, `units_total`, `units_remaining`, 
                 `research_unit_count`, `research_unit_energy`, 
                 `research_unit_ingredients`, `saved_progress`
    """

    # Core fields (always present)
    queued: bool
    """True if technologies are queued beyond the current research."""
    active: bool
    """True if research is actively being worked on (labs consuming science packs)."""
    progress: float
    """Current research progress as a float from 0.0 (0%) to 1.0 (100%)."""
    status: str
    """Human-readable status message describing the research state."""
    tick: int
    """Game tick when the status was retrieved."""

    # Queue information (present if queued or active)
    current_research: Optional[str] = None
    """Name of currently researching technology, or None if no research is active."""
    queue_length: int = 0
    """Number of technologies in the research queue."""
    queue: List[QueuedTechnology] = field(default_factory=list)
    """Array of queued technologies with position and name (only if queued)."""

    # Active research details (present only if active)
    units_completed: Optional[int] = None
    """Number of research units completed (only if active)."""
    units_total: Optional[int] = None
    """Total number of research units required (only if active)."""
    units_remaining: Optional[int] = None
    """Number of research units remaining (only if active)."""
    research_unit_count: Optional[int] = None
    """Total research unit count for the technology (only if active)."""
    research_unit_energy: Optional[float] = None
    """Energy required per research unit in seconds (only if active)."""
    research_unit_ingredients: Optional[List[Dict[str, Any]]] = None
    """Science pack ingredients required per research unit (only if active).
    
    Format: [{"name": "automation-science-pack", "amount": 1}, ...]
    """
    saved_progress: Optional[float] = None
    """Saved progress from the technology object (0.0-1.0, only if active).
    
    This is more accurate than force.research_progress for the current technology.
    """


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
        """Get comprehensive research status with progressive detail levels.

        Returns different levels of detail based on research state:
        - **Minimal**: If no research is queued or active (just queued/active flags)
        - **Queued**: If research is queued but not active (includes queue information)
        - **Active**: If research is actively progressing (includes full progress details)

        **For Agents**: Use this to check:
        - Whether research is queued or active
        - Current progress (0.0 to 1.0)
        - How many research units are completed/remaining
        - What science packs are needed per research unit
        - Queue information if multiple technologies are queued

        Returns:
            ResearchStatus with progressive detail based on research state

        Example:
            ```python
            status = research.status()
            if status.active:
                print(f"Researching {status.current_research}: {status.units_completed}/{status.units_total} units")
                print(f"Progress: {status.progress * 100:.1f}%")
            elif status.queued:
                print(f"{status.queue_length} technologies queued")
            else:
                print("No research active")
            ```
        """
        cmd = self._rcon.build_command("get_research_status")
        data = self._rcon.execute_and_parse_json(cmd)

        # Parse queue if present
        queue = []
        if "queue" in data and isinstance(data["queue"], list):
            for item in data["queue"]:
                queue.append(
                    QueuedTechnology(
                        position=item.get("position", 0),
                        name=item.get("name", ""),
                        is_current=item.get("is_current", False),
                    )
                )

        return ResearchStatus(
            queued=data.get("queued", False),
            active=data.get("active", False),
            progress=data.get("progress", 0.0),
            status=data.get("status", "Unknown"),
            tick=data.get("tick", 0),
            current_research=data.get("current_research"),
            queue_length=data.get("queue_length", 0),
            queue=queue,
            units_completed=data.get("units_completed"),
            units_total=data.get("units_total"),
            units_remaining=data.get("units_remaining"),
            research_unit_count=data.get("research_unit_count"),
            research_unit_energy=data.get("research_unit_energy"),
            research_unit_ingredients=data.get("research_unit_ingredients"),
            saved_progress=data.get("saved_progress"),
        )

    def get_queue(self) -> Dict[str, Any]:
        """Get current research queue with progress information.

        Returns:
            Research queue dict with queue, current_research, and tick
        """
        cmd = self._rcon.build_command("get_research_queue")
        return self._rcon.execute_and_parse_json(cmd)
