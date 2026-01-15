"""Simplified Jupyter runtime using jupyter_client."""

import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

import nbformat
from jupyter_client import BlockingKernelClient
from jupyter_client.manager import KernelManager

from FactoryVerse.infra.llm.output_compressor import OutputCompressor
from FactoryVerse.infra.llm.factorio_error_parser import (
    FactorioErrorParser,
    ErrorVerbosity,
)

logger = logging.getLogger(__name__)


class FactoryVerseRuntime:
    """Simple Jupyter kernel runtime using jupyter_client."""

    def __init__(
        self,
        notebook_path: str,
        kernel_name: str = "fv",
        error_verbosity: ErrorVerbosity = ErrorVerbosity.MODERATE,
        max_traceback_frames: int = 2,
    ):
        """
        Initialize runtime and start kernel.

        Args:
            notebook_path: Path to notebook file for logging
            kernel_name: Kernel name to use
            error_verbosity: Verbosity level for error messages (MINIMAL, MODERATE, FULL)
            max_traceback_frames: Maximum traceback frames to show (for MODERATE verbosity)
        """
        self.notebook_path = Path(notebook_path)
        self.kernel_name = kernel_name
        self.output_compressor = OutputCompressor()
        self.error_parser = FactorioErrorParser(
            verbosity=error_verbosity, max_traceback_frames=max_traceback_frames
        )

        # Create notebook
        self._init_notebook()

        # Start kernel using jupyter_client
        self.km = KernelManager(kernel_name=kernel_name)
        self.km.start_kernel()
        self.kc: BlockingKernelClient = self.km.client()
        self.kc.start_channels()
        self.kc.wait_for_ready(timeout=60)

        logger.info(f"Runtime initialized with kernel: {kernel_name}")

    def _init_notebook(self):
        """Create empty notebook file."""
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
        logger.info(f"Created notebook: {self.notebook_path}")

    def execute_code(
        self,
        code: str,
        compress_output: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Execute code in kernel and return result.

        Args:
            code: Python code to execute
            compress_output: Whether to compress output
            metadata: Cell metadata

        Returns:
            Execution result
        """
        # Log to notebook BEFORE execution (with empty outputs)
        cell_id = self._append_to_notebook_before_execution(code, metadata or {})

        # Collect outputs using execute_interactive
        outputs = []
        text_parts = []

        def output_hook(msg):
            """Hook to collect output messages."""
            msg_type = msg["msg_type"]
            content = msg["content"]

            # Store for notebook
            outputs.append({"msg_type": msg_type, "content": content})

            # Collect text for return value
            if msg_type == "stream":
                text_parts.append(content.get("text", ""))
            elif msg_type == "execute_result":
                text_parts.append(content.get("data", {}).get("text/plain", ""))
            elif msg_type == "error":
                # Parse and format error using error parser
                raw_error = f"Error: {content.get('evalue', '')}\n{''.join(content.get('traceback', []))}"
                parsed_error = self.error_parser.parse_and_format(raw_error)
                text_parts.append(parsed_error)

        # Execute with interactive hook - much simpler!
        try:
            self.kc.execute_interactive(code, output_hook=output_hook, timeout=60)
        except Exception as e:
            # If execution fails, still update notebook with error
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
            # Parse and format error
            parsed_error = self.error_parser.parse_and_format(f"Error: {str(e)}")
            text_parts.append(parsed_error)

        raw_output = "".join(text_parts).strip()

        # Update notebook with outputs AFTER execution
        self._update_notebook_cell_outputs(cell_id, outputs)

        # Compress if needed
        if compress_output and raw_output:
            compressed = self.output_compressor.compress_action_result(
                raw_output, action_type="execute_code"
            )
            return compressed.text

        return raw_output

    def _append_to_notebook_before_execution(
        self, code: str, metadata: Dict[str, Any]
    ) -> str:
        """
        Append code cell to notebook BEFORE execution.
        Returns cell ID for later updating with outputs.
        """
        with open(self.notebook_path, "r") as f:
            nb = nbformat.read(f, as_version=4)

        cell = nbformat.v4.new_code_cell(source=code)
        cell.metadata.update(metadata)
        cell.outputs = []  # Empty outputs initially

        # Use cell index as ID
        cell_id = len(nb.cells)
        nb.cells.append(cell)

        with open(self.notebook_path, "w") as f:
            nbformat.write(nb, f)

        return str(cell_id)

    def _update_notebook_cell_outputs(self, cell_id: str, outputs: List[Dict]):
        """Update a cell's outputs after execution."""
        with open(self.notebook_path, "r") as f:
            nb = nbformat.read(f, as_version=4)

        cell_index = int(cell_id)
        if cell_index >= len(nb.cells):
            logger.warning(f"Cell index {cell_index} out of range")
            return

        cell = nb.cells[cell_index]

        # Convert outputs to nbformat outputs
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

    def _append_to_notebook(
        self, code: str, outputs: List[Dict], metadata: Dict[str, Any]
    ):
        """Append code cell to notebook (legacy method for backward compatibility)."""
        cell_id = self._append_to_notebook_before_execution(code, metadata)
        self._update_notebook_cell_outputs(cell_id, outputs)

    def setup_boilerplate(self):
        """Execute boilerplate setup code from boilerplate.py."""
        logger.info("Executing boilerplate...")
        boilerplate_path = Path(__file__).parent / "infra" / "llm" / "boilerplate.py"
        with open(boilerplate_path, "r") as f:
            code = f.read()

        result = self.execute_code(code, compress_output=False)
        logger.info(f"Boilerplate complete")
        return result

    def reload_boilerplate(self, reload_factorio: bool = False):
        """Reload boilerplate modules and recreate runtime.
        
        This method:
        1. Extracts current state (agent_id, udp_port, session_dir, etc.)
        2. Stops old runtime gracefully
        3. Reloads Python modules
        4. Optionally reloads Factorio scripts (if reload_factorio=True)
        5. Re-executes boilerplate to create new runtime objects
        
        Args:
            reload_factorio: If True, also triggers Factorio script reload via RCON
        
        Returns:
            Result string from boilerplate execution
        """
        logger.info("Reloading boilerplate...")
        
        # Step 1: Extract current state from kernel
        extract_code = """
import os
import json
from pathlib import Path

# Extract state that we need to preserve
_state = {
    'agent_id': os.getenv('FV_AGENT_ID', 'agent_1'),
    'session_dir': os.getenv('FV_SESSION_DIR', '.'),
    'udp_port': os.getenv('FV_AGENT_UDP_PORT'),
}

# Try to get runtime state if it exists
try:
    if 'runtime' in globals():
        _state['udp_port'] = runtime._config.udp_port if hasattr(runtime, '_config') else _state['udp_port']
        _state['agent_id'] = runtime.agent_id if hasattr(runtime, 'agent_id') else _state['agent_id']
except:
    pass

json.dumps(_state)
"""
        
        try:
            state_json = self.execute_code(extract_code, compress_output=False)
            import json
            state = json.loads(state_json.strip())
        except Exception as e:
            logger.warning(f"Could not extract state: {e}, using defaults")
            state = {
                'agent_id': 'agent_1',
                'session_dir': '.',
                'udp_port': None,
            }
        
        # Step 2: Stop old runtime gracefully
        stop_code = """
try:
    if 'runtime' in globals() and hasattr(runtime, 'stop'):
        import asyncio
        # Try to stop runtime if it's started
        if hasattr(runtime, '_started') and runtime._started:
            try:
                # Try to get running loop
                try:
                    loop = asyncio.get_running_loop()
                    # If we have a running loop, we can't use run_until_complete
                    # Just mark as stopped - cleanup will happen on GC
                    runtime._started = False
                    print("Runtime marked for cleanup (event loop is running)")
                except RuntimeError:
                    # No running loop, we can stop synchronously
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(runtime.stop())
                        print("Runtime stopped gracefully")
                    finally:
                        loop.close()
            except Exception as e:
                print(f"Note: Could not stop old runtime gracefully: {e}")
                # Force cleanup
                if hasattr(runtime, '_started'):
                    runtime._started = False
except Exception as e:
    print(f"Note: Could not access runtime: {e}")
"""
        
        self.execute_code(stop_code, compress_output=False)
        
        # Step 3: Optionally reload Factorio scripts
        if reload_factorio:
            reload_factorio_code = """
try:
    if 'rcon_client' in globals():
        rcon_client.send_command("/c game.reload_script();game.print('Scripts reloaded');rcon.print('Scripts reloaded')")
        print("✅ Triggered Factorio script reload")
    else:
        print("⚠️  RCON client not available, skipping Factorio reload")
except Exception as e:
    print(f"⚠️  Could not reload Factorio scripts: {e}")
"""
            self.execute_code(reload_factorio_code, compress_output=False)
        
        # Step 4: Reload Python modules
        reload_code = """
import importlib
import sys

# Modules to reload (from boilerplate.py imports)
_modules_to_reload = [
    'FactoryVerse.config',
    'FactoryVerse.infra.instance_manager',
    'FactoryVerse.runtime',
    'FactoryVerse.agent.infra.rcon_handler',
    'FactoryVerse.agent.infra.async_listener',
    'FactoryVerse.agent.embodied_actions.walking',
    'FactoryVerse.agent.embodied_actions.mining',
    'FactoryVerse.agent.embodied_actions.crafting',
    'FactoryVerse.agent.embodied_actions.research',
    'FactoryVerse.agent.embodied_actions.inventory',
    'FactoryVerse.agent.embodied_actions.entity_operations',
    'FactoryVerse.agent.embodied_actions.place_entity',
    'FactoryVerse.agent.ghost_builder',
    'FactoryVerse.agent.placement_hints',
    'FactoryVerse.agent.embodied_actions.reachable',
    'FactoryVerse.agent.remote_view',
    'FactoryVerse.agent.infra.snapshot',
    'FactoryVerse.factory.entity',
    'FactoryVerse.factory.item',
]

_reloaded = []
_failed = []

for _mod_name in _modules_to_reload:
    if _mod_name in sys.modules:
        try:
            importlib.reload(sys.modules[_mod_name])
            _reloaded.append(_mod_name)
        except Exception as e:
            _failed.append(f"{_mod_name}: {e}")

print(f"Reloaded {len(_reloaded)} modules")
if _failed:
    print(f"Failed to reload {len(_failed)} modules:")
    for _f in _failed:
        print(f"  - {_f}")

del _modules_to_reload, _reloaded, _failed, _mod_name
"""
        
        self.execute_code(reload_code, compress_output=False)
        
        # Step 5: Re-execute boilerplate
        logger.info("Re-executing boilerplate...")
        return self.setup_boilerplate()

    def load_map_database(self):
        """Map database is now loaded as part of setup_boilerplate."""
        logger.info("Map database loaded via boilerplate")
        return ""

    def execute_dsl(self, code: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Execute DSL code (ipykernel autoawait handles async)."""
        return self.execute_code(code, compress_output=True, metadata=metadata)

    def execute_duckdb(
        self, query: str, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Execute DuckDB query using remote_view."""
        wrapped_code = f"""result = remote_view.query('''{query}''')
for row in result:
    print(row)
"""
        return self.execute_code(wrapped_code, compress_output=True, metadata=metadata)

    def respond(self, message: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Return a chat response (for assisted mode)."""
        return message

    def get_tool_definitions(self, mode: str = "autonomous") -> List[Dict[str, Any]]:
        """Return OpenAI-compatible tool definitions.

        Args:
            mode: 'assisted' or 'autonomous' - determines which tools are available
        """
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "execute_duckdb",
                    "description": "Execute SQL query against the FactoryVerse database to analyze map state.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "SQL query (DuckDB dialect)",
                            }
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "execute_dsl",
                    "description": "Execute Python code using FactoryVerse DSL. Code runs in ipykernel with autoawait - use 'await' directly for async functions. All objects (walking, reachable, inventory, etc.) are pre-loaded.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {
                                "type": "string",
                                "description": "Python code to execute",
                            }
                        },
                        "required": ["code"],
                    },
                },
            },
        ]

        # Add respond tool only in assisted mode
        if mode == "assisted":
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "respond",
                        "description": "Respond to the user with a text message. Use this when you want to chat, ask clarifying questions, explain your reasoning, or discuss strategy without taking any game actions.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "message": {
                                    "type": "string",
                                    "description": "Your message to the user",
                                }
                            },
                            "required": ["message"],
                        },
                    },
                }
            )

        return tools

    def stop(self):
        """Stop kernel client and shutdown kernel with verbose state verification."""
        print("\n🧹 Starting notebook cleanup...")
        cleanup_success = True

        # Step 1: Stop kernel client channels
        if hasattr(self, "kc"):
            try:
                # Check state before stopping
                is_alive_before = self.kc.is_alive()
                print(f"   Kernel client channels alive: {is_alive_before}")

                if is_alive_before:
                    print("   Stopping kernel client channels...")
                    self.kc.stop_channels()

                    # Wait a moment for channels to stop
                    import time

                    time.sleep(0.2)

                    # Verify channels stopped
                    is_alive_after = self.kc.is_alive()
                    print(
                        f"   Kernel client channels alive after stop: {is_alive_after}"
                    )

                    if is_alive_after:
                        logger.warning(
                            "Kernel client channels still alive after stop_channels()"
                        )
                        print("   ⚠️  Warning: Channels may still be stopping...")
                        # This is not critical, kernel shutdown will handle it
                    else:
                        logger.info("Kernel client stopped successfully")
                else:
                    print("   Kernel client channels already stopped")

            except Exception as e:
                logger.error(f"Error stopping kernel client: {e}")
                print(f"   ❌ Error stopping kernel client: {e}")
                cleanup_success = False
        else:
            print("   No kernel client to stop")

        # Step 2: Shutdown kernel
        if hasattr(self, "km"):
            try:
                # Check state before shutdown
                is_alive_before = self.km.is_alive()
                print(f"   Kernel manager alive: {is_alive_before}")

                if is_alive_before:
                    print("   Shutting down kernel (now=True)...")
                    self.km.shutdown_kernel(now=True)

                    # Wait a moment for shutdown to complete
                    import time

                    time.sleep(0.5)

                    # Verify kernel shutdown
                    is_alive_after = self.km.is_alive()
                    print(f"   Kernel manager alive after shutdown: {is_alive_after}")

                    if is_alive_after:
                        logger.error(
                            "Kernel still alive after shutdown_kernel(now=True)"
                        )
                        print("   ❌ CRITICAL: Kernel failed to shutdown!")
                        print("   This will cause port conflicts on next run.")
                        cleanup_success = False
                    else:
                        logger.info("Kernel shutdown successfully")
                else:
                    print("   Kernel already shutdown")

            except Exception as e:
                logger.error(f"Error shutting down kernel: {e}")
                print(f"   ❌ Error shutting down kernel: {e}")
                cleanup_success = False
        else:
            print("   No kernel manager to shutdown")

        # Final status
        if cleanup_success:
            print("✅ Notebook cleanup completed successfully\n")
        else:
            print("⚠️  Notebook cleanup completed with warnings/errors")
            print("   You may need to manually cleanup jupyter kernels")
            print("   Run: uv run python scripts/cleanup_jupyter_kernels.py\n")
