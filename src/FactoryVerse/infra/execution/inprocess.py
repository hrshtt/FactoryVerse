"""In-process execution environment.

InProcessExecutor provides lightweight code execution using Python's exec(),
running code in the same process as the caller. Best suited for:
- MCP server tools (low overhead)
- Testing and development
- Simple scripting without notebook logging
"""

import asyncio
import io
import logging
import sys
import time
import traceback
from contextlib import redirect_stdout, redirect_stderr
from typing import Dict, Any, Optional

from FactoryVerse.infra.execution.base import (
    ExecutionEnvironment,
    ExecutionResult,
    ExecutionStatus,
)

logger = logging.getLogger(__name__)


class InProcessExecutor(ExecutionEnvironment):
    """In-process code execution environment.

    Executes code using Python's built-in exec() in the current process.
    All code shares a single namespace that persists across calls.

    This executor is much lighter weight than JupyterExecutor:
    - No kernel process startup
    - No notebook logging overhead
    - Direct access to namespace

    Tradeoffs vs JupyterExecutor:
    - No process isolation (errors can affect host process)
    - No notebook logging (use for dev/testing, not production runs)
    - Async code requires explicit asyncio.run() in the code

    Example:
        executor = InProcessExecutor()
        await executor.start()

        result = executor.execute("x = 1 + 2")
        result = executor.execute("print(x)")  # Prints: 3

        value = executor.get_variable("x")  # Returns: 3
        await executor.stop()
    """

    def __init__(
        self,
        initial_globals: Optional[Dict[str, Any]] = None,
        enable_async: bool = True,
    ):
        """Initialize InProcessExecutor.

        Args:
            initial_globals: Variables to inject into namespace at start
            enable_async: If True, attempts to run async code using asyncio
        """
        self._initial_globals = initial_globals or {}
        self._enable_async = enable_async

        # Execution namespace
        self._globals: Dict[str, Any] = {}
        self._started = False

    async def start(self) -> None:
        """Initialize execution namespace.

        Creates a fresh namespace with initial globals and builtins.
        """
        if self._started:
            logger.warning("InProcessExecutor already started")
            return

        # Create fresh namespace with builtins
        self._globals = {
            "__builtins__": __builtins__,
            "__name__": "__main__",
            "__doc__": None,
        }

        # Add initial globals
        self._globals.update(self._initial_globals)

        self._started = True
        logger.info("InProcessExecutor started")

    async def stop(self) -> None:
        """Clear execution namespace.

        Clears all variables and resets state. After stop(), start() must
        be called before using execute().
        """
        if not self._started:
            logger.warning("InProcessExecutor not started, nothing to stop")
            return

        self._globals.clear()
        self._started = False
        logger.info("InProcessExecutor stopped")

    def is_running(self) -> bool:
        """Check if executor is running."""
        return self._started

    def execute(
        self,
        code: str,
        timeout: Optional[float] = None,
        compress_output: bool = False,
        **kwargs,
    ) -> ExecutionResult:
        """Execute code in the current process.

        Captures stdout/stderr and handles exceptions. Code runs in a
        shared namespace that persists across calls.

        Args:
            code: Python code to execute
            timeout: Not implemented for in-process execution (ignored)
            compress_output: If True, truncates long outputs
            **kwargs: Additional options (ignored)

        Returns:
            ExecutionResult with captured output and any errors

        Raises:
            RuntimeError: If executor not started
        """
        if not self._started:
            raise RuntimeError("InProcessExecutor not started. Call start() first.")

        if timeout is not None:
            logger.warning("Timeout not implemented for InProcessExecutor")

        start_time = time.time()

        # Capture stdout/stderr
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        status = ExecutionStatus.SUCCESS
        result_value = None
        error_msg = None
        error_tb = None

        try:
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                # Check if code is async
                if self._enable_async and self._is_async_code(code):
                    result_value = self._execute_async(code)
                else:
                    # Try to eval for expression result, fall back to exec
                    try:
                        result_value = eval(code, self._globals)
                    except SyntaxError:
                        exec(code, self._globals)
                        result_value = None

        except Exception as e:
            status = ExecutionStatus.ERROR
            error_msg = f"{type(e).__name__}: {str(e)}"
            error_tb = traceback.format_exc()

        execution_time = (time.time() - start_time) * 1000  # ms

        # Combine captured output
        output = stdout_capture.getvalue()
        stderr_output = stderr_capture.getvalue()
        if stderr_output:
            output = output + ("\n" if output else "") + stderr_output

        # Compress if requested
        if compress_output and len(output) > 5000:
            output = (
                output[:2000]
                + f"\n\n... [{len(output) - 4000} chars truncated] ...\n\n"
                + output[-2000:]
            )

        return ExecutionResult(
            status=status,
            output=output.strip(),
            result=result_value,
            error=error_msg,
            error_traceback=error_tb,
            execution_time_ms=execution_time,
        )

    def inject_globals(self, globals_dict: Dict[str, Any]) -> None:
        """Inject variables into execution namespace.

        Variables injected are immediately available in subsequent execute() calls.

        Args:
            globals_dict: Variables to inject
        """
        if not self._started:
            raise RuntimeError("InProcessExecutor not started")

        self._globals.update(globals_dict)
        logger.debug(f"Injected {len(globals_dict)} variables into namespace")

    def get_variable(self, name: str) -> Any:
        """Get a variable from execution namespace.

        Args:
            name: Variable name

        Returns:
            Variable value

        Raises:
            KeyError: If variable doesn't exist
        """
        if not self._started:
            raise RuntimeError("InProcessExecutor not started")

        if name not in self._globals:
            raise KeyError(f"Variable '{name}' not found in namespace")

        return self._globals[name]

    def _is_async_code(self, code: str) -> bool:
        """Check if code contains async/await syntax."""
        # Simple heuristic - could be improved with AST parsing
        return "await " in code or "async " in code

    def _execute_async(self, code: str) -> Any:
        """Execute async code using asyncio.

        Wraps code in an async function and runs it.
        """
        # Wrap code in async function
        wrapped = f"""
async def __async_exec__():
{chr(10).join("    " + line for line in code.split(chr(10)))}
    return locals()
"""

        # Execute the wrapper definition
        exec(wrapped, self._globals)

        # Run the async function
        try:
            loop = asyncio.get_running_loop()
            # If there's already a running loop, we need to use it
            import nest_asyncio

            nest_asyncio.apply()
            coro = self._globals["__async_exec__"]()
            result = loop.run_until_complete(coro)
        except RuntimeError:
            # No running loop, create one
            result = asyncio.run(self._globals["__async_exec__"]())

        # Merge returned locals into globals
        if isinstance(result, dict):
            self._globals.update(result)

        # Cleanup
        del self._globals["__async_exec__"]

        return result


class AsyncInProcessExecutor(InProcessExecutor):
    """InProcessExecutor with native async execute method.

    For use in async contexts where you want to await code execution
    directly rather than wrapping async code manually.
    """

    async def execute_async(
        self, code: str, timeout: Optional[float] = None, **kwargs
    ) -> ExecutionResult:
        """Async version of execute.

        Runs sync execution in a thread pool to avoid blocking.

        Args:
            code: Python code to execute
            timeout: Execution timeout in seconds
            **kwargs: Additional options

        Returns:
            ExecutionResult
        """
        loop = asyncio.get_running_loop()

        if timeout is not None:
            try:
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: self.execute(code, **kwargs)),
                    timeout=timeout,
                )
                return result
            except asyncio.TimeoutError:
                return ExecutionResult(
                    status=ExecutionStatus.TIMEOUT,
                    error="Execution timed out",
                )
        else:
            return await loop.run_in_executor(
                None, lambda: self.execute(code, **kwargs)
            )
