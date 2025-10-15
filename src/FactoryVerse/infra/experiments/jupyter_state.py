"""
Jupyter notebook state management utilities.

Handles:
- Creating notebooks from templates
- Injecting checkpointed state into notebooks
- Extracting state from running notebooks
"""

import json
import nbformat
from pathlib import Path
from typing import Dict, Any, Optional


def create_notebook_from_template(
    notebook_path: Path,
    agent_id: str,
    experiment_id: str,
    pg_dsn: str,
    factorio_host: str = "localhost",
    factorio_rcon_port: int = 27000
) -> None:
    """
    Create a new agent notebook from template.

    The notebook includes:
    - Auto-configured connection to PostgreSQL
    - Auto-configured RCON connection to Factorio
    - AgentContext helper for common operations
    - Checkpoint/restore utilities

    Args:
        notebook_path: Path where notebook will be created
        agent_id: Agent identifier
        experiment_id: Experiment UUID
        pg_dsn: PostgreSQL DSN
        factorio_host: Factorio server host
        factorio_rcon_port: Factorio RCON port
    """
    nb = nbformat.v4.new_notebook()

    # Cell 1: Setup and imports
    setup_cell = nbformat.v4.new_code_cell(f"""# FactoryVerse Agent: {agent_id}
# Experiment: {experiment_id}

import json
import psycopg2
from psycopg2.extras import RealDictCursor

# Experiment context (metadata only)
from FactoryVerse.infra.experiments import AgentContext

ctx = AgentContext(
    experiment_id='{experiment_id}',
    agent_id='{agent_id}',
    factorio_host='{factorio_host}',
    factorio_rcon_port={factorio_rcon_port},
    pg_dsn='{pg_dsn}'
)

# TODO: Import action/observation interface once implemented
# from factorio_actions import move_to, place_entity, craft_item, harvest_resource
# from factorio_observations import query_db, nearest_resource, agent_position

# Agent state (will be checkpointed)
episode_history = {{
    'actions': [],
    'observations': [],
    'step': 0
}}

print(f"Agent {{ctx.agent_id}} initialized")
print(f"Experiment: {{ctx.experiment_id}}")
print(f"PostgreSQL: {{ctx.pg_dsn.split('@')[1]}}")
print(f"Factorio RCON: {{ctx.factorio_host}}:{{ctx.factorio_rcon_port}}")
print()
print("TODO: Implement action/observation wrappers")
""")

    # Cell 2: Database query helpers (temporary until UDFs are implemented)
    helpers_cell = nbformat.v4.new_code_cell("""# Temporary database query helpers
# TODO: Replace with proper UDFs (nearest_resource, agent_position, etc.)

def query_db(sql: str, params=None):
    \"\"\"Execute SQL query and return results.\"\"\"
    with ctx.db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]

# Example queries
def find_nearest_iron():
    \"\"\"Find nearest iron ore patch.\"\"\"
    return query_db(\"\"\"
        SELECT resource_name, total_amount,
               ST_X(centroid) as x, ST_Y(centroid) as y,
               ST_Distance(centroid, ST_Point(0, 0)) AS distance
        FROM sp_resource_patches
        WHERE resource_name = 'iron-ore'
        ORDER BY distance
        LIMIT 1
    \"\"\")

def get_current_tick():
    \"\"\"Get current game tick.\"\"\"
    return ctx.get_current_tick()

print("Helper functions loaded")
print("Try: find_nearest_iron(), get_current_tick()")
""")

    # Cell 3: Agent development area
    main_loop_cell = nbformat.v4.new_code_cell("""# Agent Development Area

# TODO: Once action/observation wrappers are implemented, agent loop will look like:
#
# for step in range(100):
#     # Observe
#     coal = query_db("SELECT * FROM nearest_resource('coal', 0, 0, 200)")
#
#     # Act
#     move_to(x=coal[0]['x'], y=coal[0]['y'])
#     harvest_resource(x=coal[0]['x'], y=coal[0]['y'], amount=10)
#
#     # Place entity
#     place_entity('burner-mining-drill', x=10, y=10)
#
#     # Track
#     episode_history['step'] = step

# For now, test database queries
print("Current tick:", get_current_tick())
print("Nearest iron ore:")
print(find_nearest_iron())

print()
print("Next steps:")
print("1. Implement action wrappers (move_to, place_entity, craft_item, etc.)")
print("2. Implement observation wrappers (query_db with UDFs)")
print("3. Build your agent logic using these functions")
""")

    # Add cells to notebook
    nb.cells = [setup_cell, helpers_cell, main_loop_cell]

    # Add metadata
    nb.metadata = {
        'kernelspec': {
            'display_name': 'Python 3',
            'language': 'python',
            'name': 'python3'
        },
        'language_info': {
            'name': 'python',
            'version': '3.12.0'
        },
        'factoryverse': {
            'agent_id': agent_id,
            'experiment_id': experiment_id
        }
    }

    # Write notebook
    with open(notebook_path, 'w') as f:
        nbformat.write(nb, f)


def create_notebook_with_state(
    notebook_path: Path,
    agent_id: str,
    experiment_id: str,
    pg_dsn: str,
    agent_state: Dict[str, Any],
    factorio_host: str = "localhost",
    factorio_rcon_port: int = 27000
) -> None:
    """
    Create a notebook with checkpointed state injected.

    This creates a fresh notebook and injects a state restoration cell
    at the beginning.

    Args:
        notebook_path: Path where notebook will be created
        agent_id: Agent identifier
        experiment_id: Experiment UUID
        pg_dsn: PostgreSQL DSN
        agent_state: Dict with 'variables' and 'history' keys
        factorio_host: Factorio server host
        factorio_rcon_port: Factorio RCON port
    """
    # First create the base notebook
    create_notebook_from_template(
        notebook_path=notebook_path,
        agent_id=agent_id,
        experiment_id=experiment_id,
        pg_dsn=pg_dsn,
        factorio_host=factorio_host,
        factorio_rcon_port=factorio_rcon_port
    )

    # Read the notebook back
    with open(notebook_path) as f:
        nb = nbformat.read(f, as_version=4)

    # Serialize state (using dill for complex objects)
    import dill
    serialized_state = {}
    for key, value in agent_state.get('variables', {}).items():
        try:
            # Try to JSON serialize first (more readable)
            json.dumps(value)
            serialized_state[key] = {'type': 'json', 'value': value}
        except (TypeError, ValueError):
            # Fall back to dill
            serialized_state[key] = {
                'type': 'dill',
                'value': dill.dumps(value).hex()
            }

    # Create state restoration cell
    restore_code = f"""# === CHECKPOINT RESTORATION ===
# This cell was auto-injected from checkpoint

import json
import dill

print("Restoring agent state from checkpoint...")

_checkpoint_state = {json.dumps(serialized_state, indent=2)}

# Restore variables
for _var_name, _var_data in _checkpoint_state.items():
    if _var_data['type'] == 'json':
        globals()[_var_name] = _var_data['value']
    elif _var_data['type'] == 'dill':
        globals()[_var_name] = dill.loads(bytes.fromhex(_var_data['value']))

# Restore episode history
episode_history = {json.dumps(agent_state.get('history', {}), indent=2)}

print(f"Restored {{len(_checkpoint_state)}} variables")
print(f"Resuming from step {{episode_history.get('step', 0)}}")

# Clean up restoration variables
del _checkpoint_state, _var_name, _var_data
"""

    restore_cell = nbformat.v4.new_code_cell(restore_code)

    # Insert as first cell
    nb.cells.insert(0, restore_cell)

    # Write back
    with open(notebook_path, 'w') as f:
        nbformat.write(nb, f)


def extract_state_from_notebook(notebook_path: Path) -> Dict[str, Any]:
    """
    Extract agent state from a Jupyter notebook.

    This reads the .ipynb file and extracts:
    - episode_history variable
    - current_plan variable
    - policy_state variable
    - Any other user-defined variables

    Args:
        notebook_path: Path to notebook

    Returns:
        Dict with 'variables' and 'history' keys
    """
    if not notebook_path.exists():
        return {'variables': {}, 'history': {}}

    with open(notebook_path) as f:
        nb = nbformat.read(f, as_version=4)

    # Extract outputs from cells
    # Look for the last executed cell that defines our key variables
    variables = {}
    history = {}

    # Try to find cells with variable definitions
    for cell in nb.cells:
        if cell.cell_type != 'code':
            continue

        # Look for episode_history in cell outputs
        if 'episode_history' in cell.source:
            # Try to parse the value from outputs
            for output in cell.get('outputs', []):
                if output.get('output_type') == 'execute_result':
                    data = output.get('data', {})
                    if 'text/plain' in data:
                        try:
                            # This is a heuristic - in practice, we'd use
                            # Jupyter kernel API to get live values
                            pass
                        except:
                            pass

    # For now, return empty state
    # In production, this would use Jupyter Kernel API to introspect
    # the running kernel's namespace
    return {
        'variables': variables,
        'history': history
    }


class JupyterStateManager:
    """
    Manages Jupyter kernel state via Jupyter REST API.

    This class provides methods to:
    - List running kernels
    - Execute code in a kernel
    - Extract variables from a kernel
    - Inject variables into a kernel
    """

    def __init__(self, jupyter_url: str = "http://localhost:8888", token: Optional[str] = None):
        """
        Initialize the JupyterStateManager.

        Args:
            jupyter_url: Base URL of Jupyter server
            token: Jupyter auth token (if required)
        """
        self.jupyter_url = jupyter_url.rstrip('/')
        self.token = token

    def _headers(self) -> Dict[str, str]:
        """Get request headers with auth token if available."""
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = f'Token {self.token}'
        return headers

    def list_kernels(self) -> list:
        """List all running Jupyter kernels."""
        import requests
        response = requests.get(
            f"{self.jupyter_url}/api/kernels",
            headers=self._headers()
        )
        response.raise_for_status()
        return response.json()

    def get_kernel_id(self, notebook_path: str) -> Optional[str]:
        """
        Get kernel ID for a notebook path.

        Args:
            notebook_path: Path to notebook

        Returns:
            Kernel ID if found, None otherwise
        """
        import requests

        # List all sessions (notebooks)
        response = requests.get(
            f"{self.jupyter_url}/api/sessions",
            headers=self._headers()
        )
        response.raise_for_status()
        sessions = response.json()

        # Find matching session
        notebook_path = Path(notebook_path).name
        for session in sessions:
            if session['notebook']['path'] == notebook_path:
                return session['kernel']['id']

        return None

    def execute_code(self, kernel_id: str, code: str) -> Any:
        """
        Execute code in a Jupyter kernel and return result.

        Args:
            kernel_id: Kernel ID
            code: Python code to execute

        Returns:
            Execution result
        """
        # This would use Jupyter Kernel Gateway or Jupyter Server API
        # For simplicity, we'll use a synchronous approach via websockets
        # In production, you'd use jupyter_client library

        # TODO: Implement via jupyter_client or websockets
        raise NotImplementedError(
            "Kernel execution via API not yet implemented. "
            "Use jupyter_client library for kernel communication."
        )

    def extract_variables(self, kernel_id: str, variable_names: list) -> Dict[str, Any]:
        """
        Extract specific variables from a kernel.

        Args:
            kernel_id: Kernel ID
            variable_names: List of variable names to extract

        Returns:
            Dict mapping variable names to values
        """
        # Build code to extract variables
        code = f"""
import json
import dill

_vars = {{}}
for _name in {variable_names}:
    if _name in globals():
        try:
            # Try JSON first
            json.dumps(globals()[_name])
            _vars[_name] = {{'type': 'json', 'value': globals()[_name]}}
        except:
            # Fall back to dill
            _vars[_name] = {{'type': 'dill', 'value': dill.dumps(globals()[_name]).hex()}}

json.dumps(_vars)
"""

        result = self.execute_code(kernel_id, code)
        return json.loads(result)

    def inject_variables(self, kernel_id: str, variables: Dict[str, Any]):
        """
        Inject variables into a kernel.

        Args:
            kernel_id: Kernel ID
            variables: Dict mapping variable names to values
        """
        import dill

        # Serialize variables
        serialized = {}
        for name, value in variables.items():
            try:
                json.dumps(value)
                serialized[name] = {'type': 'json', 'value': value}
            except (TypeError, ValueError):
                serialized[name] = {'type': 'dill', 'value': dill.dumps(value).hex()}

        # Build injection code
        code = f"""
import json
import dill

_injected = {json.dumps(serialized)}

for _name, _data in _injected.items():
    if _data['type'] == 'json':
        globals()[_name] = _data['value']
    else:
        globals()[_name] = dill.loads(bytes.fromhex(_data['value']))

del _injected, _name, _data
"""

        self.execute_code(kernel_id, code)
