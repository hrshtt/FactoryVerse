import json
import logging
import time
import uuid
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

import nbformat
import httpx
from websocket import create_connection

logger = logging.getLogger(__name__)

class FactoryVerseRuntime:
    """
    Manages a connection to an existing Jupyter Server kernel for the FactoryVerse agent.
    
    Responsibilities:
    1. Connects to Jupyter Server (default localhost:8888).
    2. Finds or starts the target kernel (e.g., 'fv').
    3. Executes code via WebSocket.
    4. Logs input/output to a local .ipynb file for visibility.
    5. Provides OpenAI-compatible tool definitions.
    """

    def __init__(self, notebook_path: str = "runtime_log.ipynb", 
                 kernel_name: str = "fv",
                 server_url: str = "http://localhost:8888",
                 token: str = ""):
        self.notebook_path = Path(notebook_path)
        self.kernel_name = kernel_name
        self.server_url = server_url
        self.token = token
        self.kernel_id: Optional[str] = None
        self.ws = None
        
        self.session_id = str(uuid.uuid4())
        
        self._init_notebook()
        self._connect_to_kernel()

    def _init_notebook(self):
        """Create or load the runtime log notebook."""
        if not self.notebook_path.exists():
            nb = nbformat.v4.new_notebook()
            nb.metadata.kernelspec = {
                "display_name": self.kernel_name,
                "language": "python",
                "name": self.kernel_name
            }
            with open(self.notebook_path, 'w') as f:
                nbformat.write(nb, f)
            logger.info(f"Created new runtime log at {self.notebook_path}")

    def _append_to_notebook(self, code: str, outputs: List[Dict[str, Any]]):
        """Append a cell to the notebook and save it."""
        try:
            with open(self.notebook_path, 'r') as f:
                nb = nbformat.read(f, as_version=4)
            
            # Create new code cell
            cell = nbformat.v4.new_code_cell(source=code)
            
            # Format outputs for nbformat
            formatted_outputs = []
            for output in outputs:
                msg_type = output.get('msg_type')
                content = output.get('content', {})
                
                if msg_type == 'stream':
                    formatted_outputs.append(
                        nbformat.v4.new_output(
                            output_type='stream',
                            name=content.get('name'),
                            text=content.get('text')
                        )
                    )
                elif msg_type == 'execute_result':
                    formatted_outputs.append(
                        nbformat.v4.new_output(
                            output_type='execute_result',
                            data=content.get('data'),
                            execution_count=content.get('execution_count')
                        )
                    )
                elif msg_type == 'error':
                     formatted_outputs.append(
                        nbformat.v4.new_output(
                            output_type='error',
                            ename=content.get('ename'),
                            evalue=content.get('evalue'),
                            traceback=content.get('traceback')
                        )
                    )
            
            cell.outputs = formatted_outputs
            nb.cells.append(cell)
            
            with open(self.notebook_path, 'w') as f:
                nbformat.write(nb, f)
                
        except Exception as e:
            logger.error(f"Failed to update notebook log: {e}")

    def _connect_to_kernel(self):
        """Find or start the kernel via Jupyter Server API."""
        headers = {"Authorization": f"Token {self.token}"} if self.token else {}
        
        # 1. List kernels
        resp = httpx.get(f"{self.server_url}/api/kernels", headers=headers)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to list kernels: {resp.text}")
        
        kernels = resp.json()
        # Sort by last_activity descending to find the most active/recenet one
        kernels.sort(key=lambda k: k.get('last_activity', ''), reverse=True)
        
        logger.info(f"Found running kernels (sorted by activity): {[k['id'] for k in kernels]}")
        
        # Try to find existing 'fv' kernel
        for k in kernels:
            # Note: Jupyter might not expose the 'name' spec clearly in list sometimes, 
            # usually it matches the kernel spec name.
            if self.kernel_name in k.get('name', ''): 
                self.kernel_id = k['id']
                logger.info(f"Connected to existing kernel {self.kernel_id} (last active: {k.get('last_activity')})")
                break
        
        # 2. Start if not found
        if not self.kernel_id:
            logger.info(f"Starting new kernel '{self.kernel_name}'...")
            resp = httpx.post(f"{self.server_url}/api/kernels", 
                              headers=headers, 
                              json={"name": self.kernel_name})
            if resp.status_code != 201:
                raise RuntimeError(f"Failed to start kernel: {resp.text}")
            self.kernel_id = resp.json()['id']
            logger.info(f"Started new kernel {self.kernel_id}")

        # 3. Connect WebSocket
        ws_url = self.server_url.replace("http", "ws")
        url = f"{ws_url}/api/kernels/{self.kernel_id}/channels"
        if self.token:
            url += f"?token={self.token}"
            
        logger.info(f"Connecting to WebSocket: {url}")
        self.ws = create_connection(url)
        logger.info("WebSocket connected.")

    def stop(self):
        """Close WebSocket connection."""
        if self.ws:
            self.ws.close()
            logger.info("WebSocket closed.")

    def execute_code(self, code: str) -> str:
        """
        Execute code in the kernel via WebSocket and return text result.
        Updates the notebook log.
        """
        if not self.ws:
            raise RuntimeError("WebSocket not connected.")

        msg_id = str(uuid.uuid4())
        execute_request = {
            "header": {
                "msg_id": msg_id,
                "username": "agent",
                "session": self.session_id,
                "msg_type": "execute_request",
                "version": "5.3",
                "date": datetime.datetime.now().isoformat()
            },
            "parent_header": {},
            "metadata": {},
            "content": {
                "code": code,
                "silent": False,
                "store_history": True,
                "user_expressions": {},
                "allow_stdin": False
            }
        }
        
        self.ws.send(json.dumps(execute_request))
        
        outputs = []
        text_output_parts = []
        
        # Execution loop
        while True:
            resp_str = self.ws.recv()
            resp = json.loads(resp_str)
            
            parent_id = resp.get("parent_header", {}).get("msg_id")
            if parent_id != msg_id:
                continue
                
            msg_type = resp["msg_type"]
            content = resp["content"]
            
            if msg_type == "status" and content["execution_state"] == "idle":
                break
                
            if msg_type in ["stream", "execute_result", "error"]:
                outputs.append({'msg_type': msg_type, 'content': content})
                
                if msg_type == "stream":
                    text_output_parts.append(content.get("text", ""))
                elif msg_type == "execute_result":
                    data = content.get("data", {})
                    text_output_parts.append(data.get("text/plain", ""))
                elif msg_type == "error":
                    text_output_parts.append(f"Error: {content.get('evalue')}")

        # Update notebook
        self._append_to_notebook(code, outputs)
        
        return "".join(text_output_parts).strip()

    def execute_duckdb(self, query: str) -> str:
        """
        Tool: execute_duckdb
        Description: Execute a SQL query against the FactoryVerse database.
        """
        wrapped_code = f"""
try:
    print(con.sql(f\"\"\"{query}\"\"\").show())
except Exception as e:
    print(e)
"""
        return self.execute_code(wrapped_code)

    def execute_dsl(self, code: str) -> str:
        """
        Tool: execute_dsl
        Description: Execute Python code using the FactoryVerse DSL.
        """
        return self.execute_code(code)

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return OpenAI-compatible tool definitions."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "execute_duckdb",
                    "description": "Execute a SQL query against the FactoryVerse database to analyze map state.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The SQL query to execute (DuckDB dialect)."
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
                    "description": "Execute Python code using the FactoryVerse DSL to perform actions in the game.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {
                                "type": "string",
                                "description": "The Python code block to execute."
                            }
                        },
                        "required": ["code"]
                    }
                }
            }
        ]
