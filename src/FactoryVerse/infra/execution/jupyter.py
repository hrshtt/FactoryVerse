"""Jupyter kernel execution environment.

JupyterExecutor provides full Jupyter kernel execution with:
- Isolated kernel process
- Notebook logging of all executions
- Output capture and error parsing
- Async code support via ipykernel autoawait
"""

import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

import nbformat
from jupyter_client import BlockingKernelClient
from jupyter_client.manager import KernelManager

from FactoryVerse.infra.execution.base import (
    ExecutionEnvironment,
    ExecutionResult,
    ExecutionStatus,
)
from FactoryVerse.infra.llm.context.compressor import OutputCompressor
from FactoryVerse.infra.output.error_parser import (
    FactorioErrorParser,
    ErrorVerbosity,
)

logger = logging.getLogger(__name__)


class JupyterExecutor(ExecutionEnvironment):
    """Jupyter kernel execution environment.

    This executor runs code in an isolated Jupyter kernel process,
    logging all executions to a notebook file. Best suited for:
    - Full agent runs requiring persistent state
    - Notebook-based logging and debugging
    - Async code execution (via ipykernel autoawait)

    Example:
        executor = JupyterExecutor(
            notebook_path="/path/to/run.ipynb",
            kernel_name="fv"
        )
        await executor.start()
        result = executor.execute("x = 1 + 2; print(x)")
        print(result.output)  # "3"
        await executor.stop()
    """

    def __init__(
        self,
        notebook_path: Path | str,
        kernel_name: str = "fv",
        error_verbosity: ErrorVerbosity = ErrorVerbosity.MODERATE,
        max_traceback_frames: int = 2,
        kernel_timeout: float = 60.0,
    ):
        """Initialize JupyterExecutor.

        Args:
            notebook_path: Path to notebook file for logging executions
            kernel_name: Jupyter kernel name (must be installed)
            error_verbosity: How verbose error messages should be
            max_traceback_frames: Max frames to show in tracebacks (for MODERATE)
            kernel_timeout: Timeout for kernel startup in seconds
        """
        self.notebook_path = Path(notebook_path)
        self.kernel_name = kernel_name
        self.kernel_timeout = kernel_timeout

        # Output processing
        self.output_compressor = OutputCompressor()
        self.error_parser = FactorioErrorParser(
            verbosity=error_verbosity,
            max_traceback_frames=max_traceback_frames,
        )

        # Kernel state (initialized on start)
        self._km: Optional[KernelManager] = None
        self._kc: Optional[BlockingKernelClient] = None
        self._started = False

        # Execution namespace for get_variable support
        self._namespace_cache: Dict[str, Any] = {}

    async def start(self) -> None:
        """Start Jupyter kernel and initialize notebook.

        Creates the notebook file and starts the kernel process.
        Blocks until kernel is ready for execution.
        """
        if self._started:
            logger.warning("JupyterExecutor already started")
            return

        # Create notebook file
        self._init_notebook()

        # Start kernel
        logger.info(f"Starting Jupyter kernel: {self.kernel_name}")
        self._km = KernelManager(kernel_name=self.kernel_name)
        self._km.start_kernel()

        # Create client and wait for ready
        self._kc = self._km.client()
        self._kc.start_channels()
        self._kc.wait_for_ready(timeout=self.kernel_timeout)

        self._started = True
        logger.info(f"JupyterExecutor started with kernel: {self.kernel_name}")

    async def stop(self) -> None:
        """Stop kernel and cleanup resources.

        Stops kernel client channels and shuts down kernel process.
        After calling stop(), start() must be called before using execute().
        """
        if not self._started:
            logger.warning("JupyterExecutor not started, nothing to stop")
            return

        cleanup_success = True
        logger.info("Stopping JupyterExecutor...")

        # Stop kernel client channels
        if self._kc is not None:
            try:
                if self._kc.is_alive():
                    logger.debug("Stopping kernel client channels...")
                    self._kc.stop_channels()
                    time.sleep(0.2)  # Allow channels to stop

                    if self._kc.is_alive():
                        logger.warning("Kernel client channels still alive after stop")
                        cleanup_success = False
            except Exception as e:
                logger.error(f"Error stopping kernel client: {e}")
                cleanup_success = False

        # Shutdown kernel
        if self._km is not None:
            try:
                if self._km.is_alive():
                    logger.debug("Shutting down kernel...")
                    self._km.shutdown_kernel(now=True)
                    time.sleep(0.5)  # Allow kernel to shutdown

                    if self._km.is_alive():
                        logger.error("Kernel still alive after shutdown!")
                        cleanup_success = False
            except Exception as e:
                logger.error(f"Error shutting down kernel: {e}")
                cleanup_success = False

        self._km = None
        self._kc = None
        self._started = False
        self._namespace_cache.clear()

        if cleanup_success:
            logger.info("JupyterExecutor stopped successfully")
        else:
            logger.warning("JupyterExecutor stopped with warnings")

    def is_running(self) -> bool:
        """Check if kernel is running."""
        return self._started and self._km is not None and self._km.is_alive()

    def execute(
        self,
        code: str,
        timeout: Optional[float] = None,
        compress_output: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> ExecutionResult:
        """Execute code in Jupyter kernel.

        Args:
            code: Python code to execute
            timeout: Execution timeout (default: 60s)
            compress_output: Whether to compress large outputs
            metadata: Notebook cell metadata
            **kwargs: Additional options (ignored)

        Returns:
            ExecutionResult with output, result, and error info

        Raises:
            RuntimeError: If executor not started
        """
        if not self._started or self._kc is None:
            raise RuntimeError("JupyterExecutor not started. Call start() first.")

        timeout = timeout or 60.0
        metadata = metadata or {}
        start_time = time.time()

        # Log to notebook before execution
        cell_id = self._append_to_notebook_before_execution(code, metadata)

        # Collect outputs
        outputs: List[Dict] = []
        text_parts: List[str] = []
        error_parts: List[str] = []
        status = ExecutionStatus.SUCCESS

        def output_hook(msg):
            """Hook to collect output messages."""
            msg_type = msg["msg_type"]
            content = msg["content"]
            outputs.append({"msg_type": msg_type, "content": content})

            if msg_type == "stream":
                text_parts.append(content.get("text", ""))
            elif msg_type == "execute_result":
                text_parts.append(content.get("data", {}).get("text/plain", ""))
            elif msg_type == "error":
                # Parse and format error
                # Join traceback lines with newlines and strip ANSI codes
                traceback_lines = content.get('traceback', [])
                traceback_text = '\n'.join(traceback_lines)
                # Strip ANSI escape codes for proper parsing
                traceback_text = _strip_ansi_codes(traceback_text)
                raw_error = f"Error: {content.get('evalue', '')}\n{traceback_text}"
                parsed_error = self.error_parser.parse_and_format(raw_error)
                error_parts.append(parsed_error)

        # Execute code
        try:
            self._kc.execute_interactive(code, output_hook=output_hook, timeout=timeout)
        except Exception as e:
            status = ExecutionStatus.ERROR
            outputs.append(
                {
                    "msg_type": "error",
                    "content": {
                        "ename": type(e).__name__,
                        "evalue": str(e),
                        "traceback": [str(e)],
                    },
                }
            )
            error_parts.append(self.error_parser.parse_and_format(f"Error: {str(e)}"))

        execution_time = (time.time() - start_time) * 1000  # ms

        # Update notebook with outputs
        self._update_notebook_cell_outputs(cell_id, outputs)

        # Build result
        output_text = "".join(text_parts).strip()
        error_text = "\n".join(error_parts) if error_parts else None

        if error_text:
            status = ExecutionStatus.ERROR

        # Compress if requested
        if compress_output and output_text:
            compressed = self.output_compressor.compress_action_result(
                output_text, action_type="execute_code"
            )
            output_text = compressed.text

        return ExecutionResult(
            status=status,
            output=output_text,
            error=error_text,
            execution_time_ms=execution_time,
            metadata={"cell_id": cell_id},
        )

    def inject_globals(self, globals_dict: Dict[str, Any]) -> None:
        """Inject variables into kernel namespace.

        Serializes variables and injects them into the kernel using exec.
        Note: Only JSON-serializable or repr-able values are supported.

        Args:
            globals_dict: Variables to inject
        """
        if not self._started:
            raise RuntimeError("JupyterExecutor not started")

        # For complex objects, we need to actually execute code that creates them
        # For now, cache and inject via repr
        for name, value in globals_dict.items():
            try:
                # Try to inject via repr
                code = f"{name} = {repr(value)}"
                self.execute(code)
                self._namespace_cache[name] = value
            except Exception as e:
                logger.warning(f"Could not inject {name}: {e}")

    def get_variable(self, name: str) -> Any:
        """Get a variable from kernel namespace.

        Executes code in kernel to retrieve and serialize the variable.

        Args:
            name: Variable name

        Returns:
            Variable value

        Raises:
            KeyError: If variable doesn't exist
        """
        if not self._started:
            raise RuntimeError("JupyterExecutor not started")

        # Execute code to get variable
        code = f"import json; print(json.dumps({name}))"
        result = self.execute(code)

        if result.is_error:
            raise KeyError(f"Variable '{name}' not found: {result.error}")

        import json

        return json.loads(result.output)

    def _init_notebook(self) -> None:
        """Create or reset notebook file."""
        self.notebook_path.parent.mkdir(parents=True, exist_ok=True)

        nb = nbformat.v4.new_notebook()
        nb.metadata.update(
            {
                "kernelspec": {
                    "display_name": "Python 3",
                    "language": "python",
                    "name": "python3",
                }
            }
        )

        with open(self.notebook_path, "w") as f:
            nbformat.write(nb, f)

        logger.debug(f"Created notebook: {self.notebook_path}")

    def _append_to_notebook_before_execution(
        self, code: str, metadata: Dict[str, Any]
    ) -> str:
        """Append code cell before execution, return cell ID for later update."""
        with open(self.notebook_path, "r") as f:
            nb = nbformat.read(f, as_version=4)

        cell = nbformat.v4.new_code_cell(source=code)
        cell.metadata.update(metadata)
        cell.outputs = []  # Empty initially

        cell_id = len(nb.cells)
        nb.cells.append(cell)

        with open(self.notebook_path, "w") as f:
            nbformat.write(nb, f)

        return str(cell_id)

    def _update_notebook_cell_outputs(self, cell_id: str, outputs: List[Dict]) -> None:
        """Update cell outputs after execution."""
        with open(self.notebook_path, "r") as f:
            nb = nbformat.read(f, as_version=4)

        cell_index = int(cell_id)
        if cell_index >= len(nb.cells):
            logger.warning(f"Cell index {cell_index} out of range")
            return

        cell = nb.cells[cell_index]
        cell_outputs = []

        for out in outputs:
            msg_type = out["msg_type"]
            content = out["content"]

            if msg_type == "stream":
                cell_outputs.append(
                    nbformat.v4.new_output(
                        output_type="stream",
                        name=content.get("name", "stdout"),
                        text=content.get("text", ""),
                    )
                )
            elif msg_type == "execute_result":
                cell_outputs.append(
                    nbformat.v4.new_output(
                        output_type="execute_result",
                        data=content.get("data", {}),
                        execution_count=content.get("execution_count"),
                    )
                )
            elif msg_type == "error":
                cell_outputs.append(
                    nbformat.v4.new_output(
                        output_type="error",
                        ename=content.get("ename", ""),
                        evalue=content.get("evalue", ""),
                        traceback=content.get("traceback", []),
                    )
                )

        cell.outputs = cell_outputs

        with open(self.notebook_path, "w") as f:
            nbformat.write(nb, f)


def _strip_ansi_codes(text: str) -> str:
    """Strip ANSI escape codes from text.

    Jupyter tracebacks contain ANSI color codes that can interfere
    with error parsing. This removes them for cleaner parsing.

    Args:
        text: Text potentially containing ANSI codes

    Returns:
        Text with ANSI codes stripped
    """
    import re
    # Match ANSI escape sequences: ESC[ ... m (where ... is numbers/semicolons)
    ansi_pattern = re.compile(r'\x1b\[[0-9;]*m')
    return ansi_pattern.sub('', text)
