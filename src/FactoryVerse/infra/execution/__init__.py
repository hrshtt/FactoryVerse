"""Unified execution layer for FactoryVerse.

This module provides execution environments that abstract WHERE code runs,
separating execution concerns from domain logic (boilerplate) and orchestration (LLM).

Key abstractions:
- ExecutionEnvironment: ABC defining the execution contract
- JupyterExecutor: Full Jupyter kernel execution (for agent runs)
- InProcessExecutor: Lightweight in-process execution (for MCP, testing)

Usage:
    from FactoryVerse.infra.execution import JupyterExecutor, InProcessExecutor

    # For full agent runs with notebook logging
    executor = JupyterExecutor(notebook_path="/path/to/notebook.ipynb")
    await executor.start()
    result = executor.execute("print('hello')")

    # For lightweight execution (MCP, tests)
    executor = InProcessExecutor()
    await executor.start()
    result = executor.execute("x = 1 + 2")
"""

from FactoryVerse.infra.execution.base import ExecutionEnvironment, ExecutionResult
from FactoryVerse.infra.execution.jupyter import JupyterExecutor
from FactoryVerse.infra.execution.inprocess import InProcessExecutor

__all__ = [
    "ExecutionEnvironment",
    "ExecutionResult",
    "JupyterExecutor",
    "InProcessExecutor",
]
