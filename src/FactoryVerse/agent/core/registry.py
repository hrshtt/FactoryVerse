"""Agent Registry Service.

This module provides the orchestrator for AgentProfiles. It manages the lifecycle,
persistence, and retrieval of agent domain identities.

It belongs to Tier 3 (Infrastructure) as it provides the 'Directory Service'
for agents, distinct from the runtime execution (Tier 4).
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from uuid import UUID

from FactoryVerse.agent.core.profile import AgentProfile, AgentStatus

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Orchestrator for Agent Profiles.

    Manages persistence and lookup of agents. This service typically runs
    as part of Tier 3 (Control Plane).
    """

    def __init__(self, storage_dir: Path):
        """Initialize the registry.

        Args:
            storage_dir: Directory where agent profiles are persisted.
        """
        self._storage_dir = storage_dir
        self._profiles: Dict[UUID, AgentProfile] = {}
        self._ensure_storage()

    def _ensure_storage(self):
        """Ensure storage directory exists."""
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def _get_profile_path(self, agent_id: UUID) -> Path:
        return self._storage_dir / f"{agent_id}.json"

    def register(self, profile: AgentProfile) -> AgentProfile:
        """Register a new agent profile."""
        if profile.id in self._profiles:
            raise ValueError(f"Agent {profile.id} already registered")

        self.save(profile)
        self._profiles[profile.id] = profile
        logger.info(f"Registered new agent: {profile.name} ({profile.id})")
        return profile

    def get(self, agent_id: UUID) -> Optional[AgentProfile]:
        """Get an agent profile by ID."""
        if agent_id in self._profiles:
            return self._profiles[agent_id]

        # Try loading from disk
        path = self._get_profile_path(agent_id)
        if path.exists():
            return self._load_from_disk(path)

        return None

    def get_by_name(self, name: str) -> Optional[AgentProfile]:
        """Get profile by name (case-insensitive)."""
        # First check memory
        for profile in self._profiles.values():
            if profile.name.lower() == name.lower():
                return profile

        # Then scan disk (slower, but necessary if not loaded)
        # In a real DB this would be an index lookup
        for path in self._storage_dir.glob("*.json"):
            try:
                profile = self._load_from_disk(path)
                if profile.name.lower() == name.lower():
                    return profile
            except Exception:
                continue

        return None

    def list_agents(self) -> List[AgentProfile]:
        """List all registered agents."""
        profiles = []
        for path in self._storage_dir.glob("*.json"):
            try:
                profiles.append(self._load_from_disk(path))
            except Exception as e:
                logger.warning(f"Failed to load agent profile {path}: {e}")
        return profiles

    def save(self, profile: AgentProfile) -> None:
        """Persist agent profile to disk."""
        profile.updated_at = profile.updated_at  # Ensure timestamp updated
        path = self._get_profile_path(profile.id)
        path.write_text(profile.model_dump_json(indent=2))
        self._profiles[profile.id] = profile

    def _load_from_disk(self, path: Path) -> AgentProfile:
        """Load profile from disk."""
        data = json.loads(path.read_text())
        profile = AgentProfile.model_validate(data)
        self._profiles[profile.id] = profile
        return profile

    def delete(self, agent_id: UUID) -> None:
        """Delete an agent profile (archival)."""
        profile = self.get(agent_id)
        if profile:
            profile.status = AgentStatus.ARCHIVED
            self.save(profile)
            logger.info(f"Archived agent: {agent_id}")
