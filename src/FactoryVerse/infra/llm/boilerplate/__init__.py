"""Backward compatibility re-export.

The boilerplate module has moved to `FactoryVerse.infra.boilerplate`.
This file provides backward compatibility for existing imports.

DEPRECATED: Import from FactoryVerse.infra.boilerplate instead.
"""

import warnings

warnings.warn(
    "FactoryVerse.infra.llm.boilerplate is deprecated. "
    "Use FactoryVerse.infra.boilerplate instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export everything from new location
from FactoryVerse.infra.boilerplate import (
    Scope,
    BoilerplateContext,
    load,
    Session,
    create_session,
    get_session,
    list_sessions,
    destroy_session,
    destroy_all_sessions,
    get_runtime_script,
)

__all__ = [
    "Scope",
    "BoilerplateContext",
    "load",
    "Session",
    "create_session",
    "get_session",
    "list_sessions",
    "destroy_session",
    "destroy_all_sessions",
    "get_runtime_script",
]
