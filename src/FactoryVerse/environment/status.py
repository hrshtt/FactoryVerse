"""Tier status and verification result types."""

from enum import Enum
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field


class TierState(str, Enum):
    """State of a tier in the environment lifecycle."""

    NOT_INITIALIZED = "not_initialized"
    INITIALIZING = "initializing"
    READY = "ready"
    ERROR = "error"
    SHUTTING_DOWN = "shutting_down"
    SHUTDOWN = "shutdown"


@dataclass
class PrerequisiteResult:
    """Result of checking tier prerequisites."""

    satisfied: bool
    missing: List[str] = field(default_factory=list)
    message: Optional[str] = None

    @classmethod
    def ok(cls) -> "PrerequisiteResult":
        """All prerequisites satisfied."""
        return cls(satisfied=True)

    @classmethod
    def failed(
        cls, missing: List[str], message: Optional[str] = None
    ) -> "PrerequisiteResult":
        """Prerequisites not satisfied."""
        return cls(satisfied=False, missing=missing, message=message)


@dataclass
class TierStatus:
    """Status of a single tier.

    Each tier provides specific status fields in `details`.
    """

    tier_name: str
    state: TierState
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    @property
    def is_ready(self) -> bool:
        """Check if tier is ready."""
        return self.state == TierState.READY

    @property
    def is_error(self) -> bool:
        """Check if tier is in error state."""
        return self.state == TierState.ERROR


# Tier-specific status details
@dataclass
class Tier1Status(TierStatus):
    """Tier 1: Factorio Infrastructure status."""

    def __init__(
        self,
        state: TierState,
        factorio_installed: bool = False,
        mods_installed: bool = False,
        client_running: Optional[bool] = None,
        server_running: Optional[bool] = None,
        ports_available: Optional[Dict[str, bool]] = None,
        error: Optional[str] = None,
    ):
        super().__init__(
            tier_name="factorio_infra",
            state=state,
            details={
                "factorio_installed": factorio_installed,
                "mods_installed": mods_installed,
                "client_running": client_running,
                "server_running": server_running,
                "ports_available": ports_available or {},
            },
            error=error,
        )


@dataclass
class Tier2Status(TierStatus):
    """Tier 2: Factorio Settings status."""

    def __init__(
        self,
        state: TierState,
        game_loaded: bool = False,
        scenario_name: Optional[str] = None,
        tick: int = 0,
        error: Optional[str] = None,
    ):
        super().__init__(
            tier_name="factorio_settings",
            state=state,
            details={
                "game_loaded": game_loaded,
                "scenario_name": scenario_name,
                "tick": tick,
            },
            error=error,
        )


@dataclass
class Tier3Status(TierStatus):
    """Tier 3: Python Infrastructure status."""

    def __init__(
        self,
        state: TierState,
        rcon_connected: bool = False,
        rcon_responsive: bool = False,
        udp_listening: bool = False,
        instance_type: Optional[str] = None,
        error: Optional[str] = None,
    ):
        super().__init__(
            tier_name="python_infra",
            state=state,
            details={
                "rcon_connected": rcon_connected,
                "rcon_responsive": rcon_responsive,
                "udp_listening": udp_listening,
                "instance_type": instance_type,
            },
            error=error,
        )


@dataclass
class Tier4Status(TierStatus):
    """Tier 4: Runtime status."""

    def __init__(
        self,
        state: TierState,
        runtime_initialized: bool = False,
        database_connected: Optional[bool] = None,
        database_synced: Optional[bool] = None,
        modules_loaded: Optional[List[str]] = None,
        error: Optional[str] = None,
    ):
        super().__init__(
            tier_name="runtime",
            state=state,
            details={
                "runtime_initialized": runtime_initialized,
                "database_connected": database_connected,
                "database_synced": database_synced,
                "modules_loaded": modules_loaded or [],
            },
            error=error,
        )


@dataclass
class Tier5Status(TierStatus):
    """Tier 5: Specification status."""

    def __init__(
        self,
        state: TierState,
        system_prompt_generated: bool = False,
        prompt_length: int = 0,
        task_defined: bool = False,
        task_valid: bool = False,
        error: Optional[str] = None,
    ):
        super().__init__(
            tier_name="specification",
            state=state,
            details={
                "system_prompt_generated": system_prompt_generated,
                "prompt_length": prompt_length,
                "task_defined": task_defined,
                "task_valid": task_valid,
            },
            error=error,
        )


@dataclass
class Tier6Status(TierStatus):
    """Tier 6: Interaction status."""

    def __init__(
        self,
        state: TierState,
        llm_connected: bool = False,
        llm_responsive: bool = False,
        orchestrator_mode: Optional[str] = None,
        tools_registered: int = 0,
        error: Optional[str] = None,
    ):
        super().__init__(
            tier_name="interaction",
            state=state,
            details={
                "llm_connected": llm_connected,
                "llm_responsive": llm_responsive,
                "orchestrator_mode": orchestrator_mode,
                "tools_registered": tools_registered,
            },
            error=error,
        )


@dataclass
class EnvironmentStatus:
    """Complete environment status across all tiers."""

    tier1: Optional[TierStatus] = None
    tier2: Optional[TierStatus] = None
    tier3: Optional[TierStatus] = None
    tier4: Optional[TierStatus] = None
    tier5: Optional[TierStatus] = None
    tier6: Optional[TierStatus] = None

    def all_ready_up_to(self, tier_num: int) -> bool:
        """Check if all tiers up to tier_num are ready."""
        tiers = [self.tier1, self.tier2, self.tier3, self.tier4, self.tier5, self.tier6]
        for i in range(tier_num):
            tier = tiers[i]
            if tier is None or not tier.is_ready:
                return False
        return True

    def first_error(self) -> Optional[TierStatus]:
        """Get first tier with error, if any."""
        for tier in [
            self.tier1,
            self.tier2,
            self.tier3,
            self.tier4,
            self.tier5,
            self.tier6,
        ]:
            if tier is not None and tier.is_error:
                return tier
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {}
        for i, tier in enumerate(
            [self.tier1, self.tier2, self.tier3, self.tier4, self.tier5, self.tier6], 1
        ):
            if tier is not None:
                result[f"tier{i}"] = {
                    "name": tier.tier_name,
                    "state": tier.state.value,
                    "details": tier.details,
                    "error": tier.error,
                }
        return result
