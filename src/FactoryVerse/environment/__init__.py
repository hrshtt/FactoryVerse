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
    ExecutionMode,
    InteractionMode,
)
from .status import TierStatus, TierState, PrerequisiteResult
from .tiers.base import Tier, TierBase
from .environment import Environment
from .orchestrator import (
    Orchestrator,
    TaskResult,
    FreeplayResult,
    BatchResult,
    Job,
)
from .sessions import (
    create_session,
    get_session,
    list_sessions,
    destroy_session,
    destroy_all_sessions,
    reload_session,
    get_session_components,
)

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
    "ExecutionMode",
    "InteractionMode",
    # Status
    "TierStatus",
    "TierState",
    "PrerequisiteResult",
    # Orchestrator
    "Orchestrator",
    "TaskResult",
    "FreeplayResult",
    "BatchResult",
    "Job",
    # Session management
    "create_session",
    "get_session",
    "list_sessions",
    "destroy_session",
    "destroy_all_sessions",
    "reload_session",
    "get_session_components",
]
