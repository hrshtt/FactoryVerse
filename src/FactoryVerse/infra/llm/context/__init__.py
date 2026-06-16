"""LLM context management utilities.

This module provides context management for LLM agents, including:
- Output compression for context window management
- Tool call validation before execution
- Initial state generation for agent sessions
- Task Progress dedupe for repeated verification blocks (OBS-2)
"""

from FactoryVerse.infra.llm.context.compressor import OutputCompressor, CompressedOutput
from FactoryVerse.infra.llm.context.validator import ToolValidator, ValidationResult
from FactoryVerse.infra.llm.context.initial_state import InitialStateGenerator
from FactoryVerse.infra.llm.context.progress_dedupe import ProgressDeduper

__all__ = [
    "OutputCompressor",
    "CompressedOutput",
    "ToolValidator",
    "ValidationResult",
    "InitialStateGenerator",
    "ProgressDeduper",
]
