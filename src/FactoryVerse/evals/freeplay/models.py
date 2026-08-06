"""Durable schemas for freeplay campaigns and embodied actor sessions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


SCHEMA_VERSION = 1


def utc_now() -> str:
    """UTC ISO timestamp with an explicit timezone."""
    return datetime.now(timezone.utc).isoformat()


class CampaignStatus(str, Enum):
    DEFINED = "defined"
    PROVISIONING = "provisioning"
    PREFLIGHT = "preflight"
    READY = "ready"
    LEASED = "leased"
    RUNNING = "running"
    CHECKPOINTING = "checkpointing"
    PAUSED = "paused"
    GRADING = "grading"
    ARCHIVED = "archived"
    INVALID = "invalid"


@dataclass(frozen=True)
class CheckpointRecord:
    checkpoint_id: str
    parent_checkpoint_id: Optional[str]
    reason: str
    created_at: str
    game_tick_before: int
    game_tick_after: int
    save_name: str
    save_path: str
    save_sha256: str
    save_size_bytes: int
    database_path: str
    database_sha256: str
    database_fingerprint: Dict[str, Any]
    score: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RuntimeSessionRecord:
    session_id: str
    actor_id: str
    started_at: str
    access_profile: str
    harness: str
    model: str
    parent_actor_id: Optional[str] = None
    resume_checkpoint_id: Optional[str] = None
    ended_at: Optional[str] = None
    status: str = "starting"
    execution_count: int = 0
    last_game_tick: Optional[int] = None
    invalid_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
