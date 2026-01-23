"""Base class for all tiers."""

from abc import ABC, abstractmethod
from enum import IntEnum
from typing import Optional, TYPE_CHECKING

from ..status import TierStatus, TierState, PrerequisiteResult

if TYPE_CHECKING:
    from ..environment import Environment


class Tier(IntEnum):
    """Tier levels in the Environment stack.

    Each tier depends on all lower tiers being ready.
    """

    FACTORIO_INFRA = 1
    SETTINGS = 2
    PYTHON_INFRA = 3
    RUNTIME = 4
    SPECIFICATION = 5
    INTERACTION = 6


class TierBase(ABC):
    """Abstract base class for all tiers.

    Each tier implements the verification protocol and lifecycle management.
    """

    tier_level: Tier

    def __init__(self, environment: "Environment"):
        """Initialize tier with reference to parent environment.

        Args:
            environment: Parent Environment instance
        """
        self._env = environment
        self._state = TierState.NOT_INITIALIZED
        self._error: Optional[str] = None

    @property
    def state(self) -> TierState:
        """Current tier state."""
        return self._state

    @property
    def is_ready(self) -> bool:
        """Check if tier is ready."""
        return self._state == TierState.READY

    @abstractmethod
    async def verify_prerequisites(self) -> PrerequisiteResult:
        """Check that lower tier(s) are ready.

        Returns:
            PrerequisiteResult indicating satisfaction or missing requirements
        """
        pass

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize this tier.

        Called after prerequisites are verified.
        Should set self._state to READY on success, ERROR on failure.

        Raises:
            TierInitializationError: If initialization fails
        """
        pass

    @abstractmethod
    async def verify_ready(self) -> TierStatus:
        """Verify this tier is fully operational.

        Returns:
            TierStatus with current state and details
        """
        pass

    @abstractmethod
    async def reset(self) -> None:
        """Reset this tier to initial state.

        Should also reset all higher tiers.
        """
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Shutdown this tier.

        Should clean up resources gracefully.
        """
        pass

    def _set_state(self, state: TierState, error: Optional[str] = None) -> None:
        """Update tier state."""
        self._state = state
        self._error = error


class TierError(Exception):
    """Base exception for tier errors."""

    def __init__(self, tier: Tier, message: str):
        self.tier = tier
        self.message = message
        super().__init__(f"Tier {tier.name}: {message}")


class TierPrerequisiteError(TierError):
    """Raised when tier prerequisites are not met."""

    def __init__(self, tier: Tier, missing: list[str], message: Optional[str] = None):
        self.missing = missing
        msg = f"Prerequisites not met: {', '.join(missing)}"
        if message:
            msg += f" - {message}"
        super().__init__(tier, msg)


class TierInitializationError(TierError):
    """Raised when tier initialization fails."""

    pass
