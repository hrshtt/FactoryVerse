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
        # Technologies THIS agent enqueued in this session. Research is
        # force-scoped and shared; cancelling something you did not start is
        # a griefing primitive (HUD plan §10), so dequeue is caller-scoped.
        self._enqueued: set = set()

    def enqueue(self, technology: str) -> Dict[str, Any]:
        """Queue a technology for research (the technology screen's queue).

        Args:
            technology: Technology name to research

        Returns:
            Response dict with success status and technology name. Unknown or
            locked technologies come back as a game-rule failure in data —
            use ``list_technologies()`` to discover names; never probe by
            enqueueing.
        """
        cmd = self._rcon.build_command("enqueue_research", technology)
        response = self._rcon.execute_and_parse_json(cmd)
        if isinstance(response, dict) and response.get("success"):
            self._enqueued.add(technology)
        return response

    def dequeue(self, force: bool = False) -> Dict[str, Any]:
        """Cancel the current research — only if you queued it.

        Research is shared force state. If the active research is not one
        this agent enqueued in this session, this returns a game-rule failure
        (data, not an exception) naming what is active, and cancels nothing.
        Pass ``force=True`` to cancel anyway. Cancellation is non-destructive:
        per-technology progress is kept.
        """
        current = None
        try:
            current = self.status().current_research
        except Exception:
            current = None
        if not force and current is not None and current not in self._enqueued:
            return {
                "success": False,
                "game_rule_failure": True,
                "reason": (
                    f"active research {current!r} was not enqueued by you in this session; "
                    f"pass force=True to cancel shared research anyway"
                ),
                "current_research": current,
                "enqueued_by_you": sorted(self._enqueued),
            }
        cmd = self._rcon.build_command("cancel_current_research")
        response = self._rcon.execute_and_parse_json(cmd)
        if isinstance(response, dict) and response.get("success") and current:
            self._enqueued.discard(current)
        return response

    def list_technologies(
        self,
        name_filter: Optional[str] = None,
        available: Optional[bool] = None,
        researched: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """The technology catalog, as the research screen lists it (HUD plan §2 as amended).

        A read; nothing is queued. Each entry: ``name``, ``researched``,
        ``available`` (every prerequisite researched — can be queued now),
        ``prerequisites``, ``science_packs`` (name → amount per unit),
        ``unit_count``, ``unit_energy`` (seconds per unit), ``unlocks``
        (recipe names), ``progress`` (saved, 0–1).

        Args:
            name_filter: substring match on the technology name
            available: True → only researchable now; False → only locked or done
            researched: True → only researched; False → only unresearched
        """
        cmd = self._rcon.build_command("get_technologies", False)
        data = self._rcon.execute_and_parse_json(cmd)
        techs = data if isinstance(data, list) else data.get("technologies", [])
        by_name = {t.get("name"): t for t in techs}
        out: List[Dict[str, Any]] = []
        for t in techs:
            name = t.get("name", "")
            if name_filter and name_filter not in name:
                continue
            done = bool(t.get("researched"))
            prereqs = list((t.get("prerequisites") or {}).keys()) if isinstance(t.get("prerequisites"), dict) \
                else list(t.get("prerequisites") or [])
            avail = (not done) and all(bool((by_name.get(p) or {}).get("researched")) for p in prereqs)
            if available is not None and avail != available:
                continue
            if researched is not None and done != researched:
                continue
            packs = {}
            for ing in t.get("research_unit_ingredients") or []:
                if isinstance(ing, dict) and ing.get("name"):
                    packs[ing["name"]] = ing.get("amount", 1)
            unlocks = [
                e.get("recipe") for e in (t.get("effects") or [])
                if isinstance(e, dict) and e.get("type") == "unlock-recipe" and e.get("recipe")
            ]
            out.append({
                "name": name,
                "researched": done,
                "available": avail,
                "prerequisites": prereqs,
                "science_packs": packs,
                "unit_count": t.get("research_unit_count"),
                "unit_energy": t.get("research_unit_energy"),
                "unlocks": unlocks,
                "progress": t.get("saved_progress") or 0.0,
            })
        out.sort(key=lambda x: (x["researched"], not x["available"], x["name"]))
        return out

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
