"""LLM layer for FactoryVerse agent orchestration.

This module contains LLM-specific components:
- `client/`: LLM client abstraction (OpenAI-compatible, Anthropic, etc.)
- `prompts/`: System prompt assembly and documentation generation
- `orchestrator.py`: Agent turn loop and tool execution
- `trajectory.py`: Action history and context compression
- `context/`: Context management (compressor, validator, initial_state)

The LLM layer receives:
- Session for code execution (from infra/session)
- Tool definitions from session
- System prompt (generated or provided)

Usage:
    from FactoryVerse.infra.llm.prompts import generate_system_prompt
    from FactoryVerse.infra.llm.client import create_openai_client
    from FactoryVerse.infra.llm.orchestrator import AgentOrchestrator
"""

# Re-export key classes for convenience
from FactoryVerse.infra.llm.prompts import (
    generate_system_prompt,
    generate_api_reference,
    generate_schema_reference,
)
from FactoryVerse.infra.llm.trajectory import TrajectoryManager, ActionStatus, ActionRecord
from FactoryVerse.infra.llm.context import (
    OutputCompressor,
    CompressedOutput,
    ToolValidator,
    ValidationResult,
    InitialStateGenerator,
)

__all__ = [
    "generate_system_prompt",
    "generate_api_reference",
    "generate_schema_reference",
    "TrajectoryManager",
    "ActionStatus",
    "ActionRecord",
    "OutputCompressor",
    "CompressedOutput",
    "ToolValidator",
    "ValidationResult",
    "InitialStateGenerator",
]
