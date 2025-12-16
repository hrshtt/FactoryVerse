"""Simplified Jupyter runtime using jupyter_client."""
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

import nbformat
from jupyter_client import BlockingKernelClient
from jupyter_client.manager import KernelManager

from FactoryVerse.llm.output_compressor import OutputCompressor
from FactoryVerse.llm.boilerplate import BOILERPLATE_CODE, MAP_DB_CODE

logger = logging.getLogger(__name__)


class FactoryVerseRuntime:
    """Simple Jupyter kernel runtime using jupyter_client."""
    
    def __init__(
        self,
        notebook_path: str,
        kernel_name: str = "fv"
    ):
        """
        Initialize runtime and start kernel.
        
        Args:
            notebook_path: Path to notebook file for logging
            kernel_name: Kernel name to use
        """
        self.notebook_path = Path(notebook_path)
        self.kernel_name = kernel_name
        self.output_compressor = OutputCompressor()
        
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
        nb.metadata.update({
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3"
            }
        })
        with open(self.notebook_path, 'w') as f:
            nbformat.write(nb, f)
        logger.info(f"Created notebook: {self.notebook_path}")
    
    def execute_code(
        self,
        code: str,
        compress_output: bool = False,
        metadata: Optional[Dict[str, Any]] = None
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
        # Collect outputs using execute_interactive
        outputs = []
        text_parts = []
        
        def output_hook(msg):
            """Hook to collect output messages."""
            msg_type = msg['msg_type']
            content = msg['content']
            
            # Store for notebook
            outputs.append({'msg_type': msg_type, 'content': content})
            
            # Collect text for return value
            if msg_type == 'stream':
                text_parts.append(content.get('text', ''))
            elif msg_type == 'execute_result':
                text_parts.append(content.get('data', {}).get('text/plain', ''))
            elif msg_type == 'error':
                text_parts.append(f"Error: {content.get('evalue', '')}\n{''.join(content.get('traceback', []))}")
        
        # Execute with interactive hook - much simpler!
        self.kc.execute_interactive(code, output_hook=output_hook, timeout=60)
        
        raw_output = "".join(text_parts).strip()
        
        # Log to notebook
        self._append_to_notebook(code, outputs, metadata or {})
        
        # Compress if needed
        if compress_output and raw_output:
            compressed = self.output_compressor.compress_action_result(
                raw_output,
                action_type="execute_code"
            )
            return compressed.text
        
        return raw_output
    
    def _append_to_notebook(
        self,
        code: str,
        outputs: List[Dict],
        metadata: Dict[str, Any]
    ):
        """Append code cell to notebook."""
        with open(self.notebook_path, 'r') as f:
            nb = nbformat.read(f, as_version=4)
        
        cell = nbformat.v4.new_code_cell(source=code)
        cell.metadata.update(metadata)
        
        # Convert outputs to nbformat outputs
        cell_outputs = []
        for out in outputs:
            msg_type = out['msg_type']
            content = out['content']
            
            if msg_type == 'stream':
                cell_outputs.append(nbformat.v4.new_output(
                    output_type='stream',
                    name=content.get('name', 'stdout'),
                    text=content.get('text', '')
                ))
            elif msg_type == 'execute_result':
                cell_outputs.append(nbformat.v4.new_output(
                    output_type='execute_result',
                    data=content.get('data', {}),
                    execution_count=content.get('execution_count')
                ))
            elif msg_type == 'error':
                cell_outputs.append(nbformat.v4.new_output(
                    output_type='error',
                    ename=content.get('ename', ''),
                    evalue=content.get('evalue', ''),
                    traceback=content.get('traceback', [])
                ))
        
        cell.outputs = cell_outputs
        nb.cells.append(cell)
        
        with open(self.notebook_path, 'w') as f:
            nbformat.write(nb, f)
    
    def setup_boilerplate(self):
        """Execute boilerplate setup code."""
        logger.info("Executing boilerplate...")
        result = self.execute_code(BOILERPLATE_CODE, compress_output=False)
        logger.info(f"Boilerplate complete")
        return result
    
    def load_map_database(self):
        """Load map database snapshots."""
        logger.info("Loading map database...")
        result = self.execute_code(MAP_DB_CODE, compress_output=False)
        logger.info(f"Map DB loaded")
        return result
    
    def execute_dsl(
        self,
        code: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Execute DSL code (ipykernel autoawait handles async)."""
        return self.execute_code(code, compress_output=True, metadata=metadata)
    
    def execute_duckdb(
        self,
        query: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Execute DuckDB query."""
        wrapped_code = f"""
with playing_factorio():
    result = map_db.connection.sql('''{query}''').show()
    print(result)
"""
        return self.execute_code(wrapped_code, compress_output=True, metadata=metadata)
    
    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return OpenAI-compatible tool definitions."""
        return [
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
                                "description": "SQL query (DuckDB dialect)"
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "execute_dsl",
                    "description": "Execute Python code using FactoryVerse DSL. Code runs in ipykernel with autoawait - use 'await' directly for async functions. Must wrap DSL calls in 'with playing_factorio():' context.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {
                                "type": "string",
                                "description": "Python code to execute"
                            }
                        },
                        "required": ["code"]
                    }
                }
            }
        ]
    
    def stop(self):
        """Stop kernel client and shutdown kernel."""
        if hasattr(self, 'kc'):
            self.kc.stop_channels()
            logger.info("Kernel client stopped")
        
        if hasattr(self, 'km'):
            self.km.shutdown_kernel(now=True)
            logger.info("Kernel shutdown")
