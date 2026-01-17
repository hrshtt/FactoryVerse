"""Abstract base class for execution environments.

The execution layer provides:
- Code execution (sync/async)
- Namespace management
- Error capture and formatting

The execution layer does NOT know about:
- Factorio, domain objects, boilerplate
- LLMs or orchestration
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from enum import Enum


class ExecutionStatus(Enum):
    """Status of code execution."""

    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass
class ExecutionResult:
    """Result of code execution.

    Attributes:
        status: Whether execution succeeded, failed, or timed out
        output: Captured stdout/stderr content
        result: Return value or final expression value (if any)
        error: Error message if execution failed
        error_traceback: Full traceback if execution failed
        execution_time_ms: Time taken to execute in milliseconds
        metadata: Additional execution metadata
    """

    status: ExecutionStatus
    output: str = ""
    result: Optional[Any] = None
    error: Optional[str] = None
    error_traceback: Optional[str] = None
    execution_time_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        """Check if execution was successful."""
        return self.status == ExecutionStatus.SUCCESS

    @property
    def is_error(self) -> bool:
        """Check if execution resulted in an error."""
        return self.status == ExecutionStatus.ERROR

    def to_display_string(self, include_traceback: bool = True) -> str:
        """Format result for display.

        Args:
            include_traceback: Whether to include full traceback on error

        Returns:
            Formatted string representation
        """
        parts = []

        if self.output:
            parts.append(self.output)

        if self.result is not None:
            parts.append(f"Result: {self.result}")

        if self.is_error:
            if self.error:
                parts.append(f"Error: {self.error}")
            if include_traceback and self.error_traceback:
                parts.append(f"\nTraceback:\n{self.error_traceback}")

        return "\n".join(parts) if parts else "(No output)"


class ExecutionEnvironment(ABC):
    """Abstract base for code execution environments.

    This class defines the contract for execution environments:
    - Start/stop lifecycle
    - Code execution with result capture
    - Namespace (globals) injection

    Implementations:
    - JupyterExecutor: Full Jupyter kernel (for agent runs with notebook logging)
    - InProcessExecutor: Simple exec() in current process (for MCP, testing)
    """

    @abstractmethod
    async def start(self) -> None:
        """Start the execution environment.

        Must be called before execute() can be used.
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop and cleanup the execution environment.

        After calling stop(), the environment cannot be used until start() is called again.
        """
        pass

    @abstractmethod
    def is_running(self) -> bool:
        """Check if environment is currently running.

        Returns:
            True if started and not stopped, False otherwise
        """
        pass

    @abstractmethod
    def execute(
        self,
        code: str,
        timeout: Optional[float] = None,
        compress_output: bool = False,
        **kwargs,
    ) -> ExecutionResult:
        """Execute code and return result.

        Args:
            code: Python code to execute
            timeout: Execution timeout in seconds (None for default)
            compress_output: Whether to compress large outputs
            **kwargs: Additional execution options

        Returns:
            ExecutionResult with status, output, and any error information

        Raises:
            RuntimeError: If environment is not running
        """
        pass

    @abstractmethod
    def inject_globals(self, globals_dict: Dict[str, Any]) -> None:
        """Inject variables into the execution namespace.

        Variables injected here will be available in subsequent execute() calls.

        Args:
            globals_dict: Dictionary of variable names to values
        """
        pass

    @abstractmethod
    def get_variable(self, name: str) -> Any:
        """Get a variable from the execution namespace.

        Args:
            name: Variable name to retrieve

        Returns:
            Variable value

        Raises:
            KeyError: If variable does not exist
        """
        pass

    def execute_and_get(self, code: str, variable_name: str, **kwargs) -> Any:
        """Execute code and return a specific variable.

        Convenience method that combines execute() and get_variable().

        Args:
            code: Python code to execute
            variable_name: Name of variable to retrieve after execution
            **kwargs: Additional arguments passed to execute()

        Returns:
            Value of the specified variable

        Raises:
            RuntimeError: If execution fails
            KeyError: If variable not found after execution
        """
        result = self.execute(code, **kwargs)
        if result.is_error:
            raise RuntimeError(f"Execution failed: {result.error}")
        return self.get_variable(variable_name)
