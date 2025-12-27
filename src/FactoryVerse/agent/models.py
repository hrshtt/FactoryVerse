"""Shared dataclass models for agent actions and responses.

This module contains dataclass definitions used across action modules,
async listener, and other agent components.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any, Self


# =============================================================================
# BASE ACTION RESPONSES
# =============================================================================


@dataclass
class ActionResponse:
    """Base response type for all action responses.

    All action responses inherit from this base type, which provides
    common fields for success/failure tracking and helper properties.
    """

    success: bool = True
    reason: Optional[str] = None
    message: Optional[str] = None

    @property
    def failed(self) -> bool:
        """True if action failed."""
        return not self.success

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Self:
        """Create instance from dict, ignoring unknown fields."""
        valid_fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid_fields)


@dataclass
class AsyncActionResponse(ActionResponse):
    """Base response type for async action initiation.

    Used by async_listener.await_action() and returned by async actions
    like walk_to, mine_resource, craft_enqueue when they start.

    All async action "Started" responses should inherit from this type.
    """

    queued: bool = False
    action_id: Optional[str] = None
    estimated_ticks: Optional[int] = None

    @property
    def is_queued(self) -> bool:
        """True if action was queued successfully."""
        return self.queued

    @property
    def has_action_id(self) -> bool:
        """True if action has an ID for tracking."""
        return self.action_id is not None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        """Create instance from dict, ignoring unknown fields."""
        valid_fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid_fields)


@dataclass
class AsyncActionCompletion(ActionResponse):
    """Base response type for async action completion.

    Received via UDP when async actions complete.
    """

    action_id: str = ""
    agent_id: str = ""
    tick: int = 0
    elapsed_ticks: int = 0

    @property
    def has_elapsed_time(self) -> bool:
        """True if elapsed time is available."""
        return self.elapsed_ticks > 0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Self:
        """Create instance from dict, ignoring unknown fields."""
        valid_fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid_fields)
