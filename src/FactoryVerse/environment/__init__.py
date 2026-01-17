"""FactoryVerse Environment Module - Canonical Orchestrator.

The Environment module provides a tiered, principled approach to composing
the complete FactoryVerse runtime stack.

Example:
    >>> from FactoryVerse.environment import Environment, Tier
    >>> async with Environment.for_agent(mode="autonomous") as env:
    ...     await env.tier6.run_loop()
"""

from .config import (
    EnvironmentConfig,
    InfraConfig,
    SettingsConfig,
    PythonConfig,
    RuntimeConfig,
    SpecificationConfig,
    InteractionConfig,
    InfraMode,
    RuntimeVariant,
    InteractionMode,
)
from .status import TierStatus, TierState, PrerequisiteResult
from .tiers.base import Tier, TierBase
from .environment import Environment

__all__ = [
    # Main class
    "Environment",
    # Tier enum
    "Tier",
    "TierBase",
    # Config
    "EnvironmentConfig",
    "InfraConfig",
    "SettingsConfig",
    "PythonConfig",
    "RuntimeConfig",
    "SpecificationConfig",
    "InteractionConfig",
    "InfraMode",
    "RuntimeVariant",
    "InteractionMode",
    # Status
    "TierStatus",
    "TierState",
    "PrerequisiteResult",
]
