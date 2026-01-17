"""Output utilities for FactoryVerse.

This module provides generic output formatting and error parsing utilities
that can be used by any consumer (CLI, MCP, agents, tests).

NOT LLM-specific - these are infrastructure utilities.
"""

from FactoryVerse.infra.output.console import ConsoleOutput
from FactoryVerse.infra.output.error_parser import (
    FactorioErrorParser,
    ErrorVerbosity,
    ParsedError,
)
from FactoryVerse.infra.output.web import (
    OutputHandler,
    WebOutput,
    AgentEvent,
    TurnData,
)

__all__ = [
    "ConsoleOutput",
    "FactorioErrorParser",
    "ErrorVerbosity",
    "ParsedError",
    "OutputHandler",
    "WebOutput",
    "AgentEvent",
    "TurnData",
]
