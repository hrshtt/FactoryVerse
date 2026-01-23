"""Domain models for Persistent Agents.

This module defines the core data structures for tracking agents as persistent
domain entities, separate from their execution environments.
"""

from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, List, Any
from uuid import UUID, uuid4
from pydantic import BaseModel, Field


class AgentStatus(str, Enum):
    """Lifecycle status of a persistent agent."""

    CREATED = "created"  # Profile created, not yet spawned
    ACTIVE = "active"  # Currently running in an environment
    IDLE = "idle"  # Spawned but not currently running
    PAUSED = "paused"  # Explicitly paused state
    ARCHIVED = "archived"  # Retired/Soft-deleted


class AgentStats(BaseModel):
    """Persistent statistics for an agent across all sessions."""

    total_play_time_seconds: float = 0.0
    total_sessions: int = 0
    total_turns: int = 0

    # Domain specific stats
    entities_placed: Dict[str, int] = Field(default_factory=dict)
    items_crafted: Dict[str, int] = Field(default_factory=dict)
    technologies_researched: List[str] = Field(default_factory=list)

    # Reliability stats
    errors_encountered: int = 0
    deaths: int = 0


class AgentProfile(BaseModel):
    """The persistent identity of an Agent.

    Acts as the 'Character Sheet' for an agent, tracking its identity,
    configuration, and long-term progress.
    """

    id: UUID = Field(default_factory=uuid4)
    name: str
    description: str = ""

    # The Factorio instance (world) this agent belongs to
    instance_id: str

    # Identity configuration
    model: str
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # State tracking
    status: AgentStatus = AgentStatus.CREATED
    current_session_id: Optional[str] = None

    # Domain Stats
    stats: AgentStats = Field(default_factory=AgentStats)

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def update_activity(self):
        """Update the last active timestamp."""
        self.updated_at = datetime.now()
