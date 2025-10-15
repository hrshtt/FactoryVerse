"""
ExperimentManager: Orchestrates Factorio servers, agent state, and Jupyter notebooks.

This manager coordinates:
1. Factorio server lifecycle (spawn, stop, restart)
2. Agent state persistence (checkpoints, restore)
3. Jupyter notebook tracking (kernel IDs, state injection)
4. PostgreSQL state synchronization
"""

import asyncio
import json
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor
from factorio_rcon import RCONClient

from ..docker.docker_manager import ClusterManager


@dataclass
class ExperimentConfig:
    """Configuration for creating a new experiment."""
    agent_id: str
    scenario: str = "factorio_verse"
    mode: str = "scenario"  # 'scenario' or 'save-based'
    checkpoint_id: Optional[str] = None
    notebook_name: Optional[str] = None  # If None, defaults to {agent_id}.ipynb


@dataclass
class ExperimentInfo:
    """Runtime information about an experiment."""
    experiment_id: str
    agent_id: str
    server_instance_id: str
    server_rcon_port: int
    server_game_port: int
    notebook_path: str
    kernel_id: Optional[str]
    status: str
    current_tick: int


class ExperimentManager:
    """
    Manages the lifecycle of FactoryVerse experiments.

    Each experiment pairs:
    - One Factorio server instance
    - One agent (with Jupyter notebook)
    - Persistent state in PostgreSQL

    Multiple experiments can run in parallel on different servers.
    """

    def __init__(
        self,
        pg_dsn: str,
        notebooks_dir: Path,
        jupyter_url: str = "http://localhost:8888",
        state_dir: Optional[Path] = None
    ):
        """
        Initialize the ExperimentManager.

        Args:
            pg_dsn: PostgreSQL connection string
            notebooks_dir: Directory where agent notebooks are stored
            jupyter_url: URL of the Jupyter server
            state_dir: State directory for Docker compose and saves
        """
        self.pg_dsn = pg_dsn
        self.notebooks_dir = Path(notebooks_dir)
        self.notebooks_dir.mkdir(parents=True, exist_ok=True)

        self.jupyter_url = jupyter_url

        # ClusterManager handles Factorio server orchestration
        self.cluster_manager = ClusterManager()
        if state_dir:
            self.cluster_manager.state_dir = state_dir

        # Track active experiments in memory
        self._active_experiments: Dict[str, ExperimentInfo] = {}

        # Ensure database schema exists
        self._ensure_schema()

    def _ensure_schema(self):
        """Ensure the experiment management schema exists in PostgreSQL."""
        schema_path = Path(__file__).parent.parent / "db" / "experiment_schema.sql"

        if not schema_path.exists():
            raise FileNotFoundError(
                f"Database schema file not found: {schema_path}\n"
                "Cannot initialize experiment management without schema."
            )

        with psycopg2.connect(self.pg_dsn) as conn:
            with conn.cursor() as cur:
                schema_sql = schema_path.read_text()
                cur.execute(schema_sql)
            conn.commit()

    def _get_connection(self):
        """Get a PostgreSQL connection."""
        return psycopg2.connect(self.pg_dsn)

    def create_experiment(
        self,
        config: ExperimentConfig,
        server_rcon_port: Optional[int] = None,
        server_game_port: Optional[int] = None
    ) -> ExperimentInfo:
        """
        Create a new experiment.

        This will:
        1. Start a Factorio server (or restore from checkpoint)
        2. Create or load a Jupyter notebook
        3. Register the experiment in PostgreSQL

        Args:
            config: Experiment configuration
            server_rcon_port: RCON port (auto-assigned if None)
            server_game_port: Game port (auto-assigned if None)

        Returns:
            ExperimentInfo with experiment details
        """
        experiment_id = str(uuid.uuid4())

        # Determine notebook path
        notebook_name = config.notebook_name or f"{config.agent_id}.ipynb"
        notebook_path = self.notebooks_dir / notebook_name

        # Determine server instance ID (simple sequential naming)
        existing_count = len(self._active_experiments)
        server_instance_id = f"factorio_{existing_count}"

        # Auto-assign ports if not provided
        from ..docker.docker_manager import START_RCON_PORT, START_GAME_PORT
        if server_rcon_port is None:
            server_rcon_port = START_RCON_PORT + existing_count
        if server_game_port is None:
            server_game_port = START_GAME_PORT + existing_count

        # Handle checkpoint restoration
        factorio_save_path = None
        agent_state = None

        if config.checkpoint_id:
            checkpoint_data = self._load_checkpoint(config.checkpoint_id)
            factorio_save_path = checkpoint_data['factorio_save_path']
            agent_state = {
                'variables': checkpoint_data['agent_variables'],
                'history': checkpoint_data['episode_history']
            }
            config.mode = checkpoint_data['mode']
            config.scenario = checkpoint_data['scenario']

        # Start Factorio server
        self._start_factorio_server(
            instance_id=server_instance_id,
            mode=config.mode,
            scenario=config.scenario,
            save_file=factorio_save_path,
            rcon_port=server_rcon_port,
            game_port=server_game_port
        )

        # Create or restore notebook
        if agent_state:
            self._restore_notebook(notebook_path, config.agent_id, experiment_id, agent_state)
        else:
            self._create_notebook(notebook_path, config.agent_id, experiment_id)

        # Register experiment in PostgreSQL
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT create_experiment(%s, %s, %s, %s, %s)
                """, (
                    config.agent_id,
                    server_instance_id,
                    config.scenario,
                    config.mode,
                    str(notebook_path)
                ))
                db_experiment_id = cur.fetchone()[0]

                # Update with port information
                cur.execute("""
                    UPDATE experiments
                    SET server_rcon_port = %s,
                        server_game_port = %s
                    WHERE experiment_id = %s
                """, (server_rcon_port, server_game_port, db_experiment_id))
            conn.commit()

            # Use database-generated UUID
            experiment_id = str(db_experiment_id)

        # Create experiment info
        exp_info = ExperimentInfo(
            experiment_id=experiment_id,
            agent_id=config.agent_id,
            server_instance_id=server_instance_id,
            server_rcon_port=server_rcon_port,
            server_game_port=server_game_port,
            notebook_path=str(notebook_path),
            kernel_id=None,  # Will be set when notebook is opened
            status='running',
            current_tick=0
        )

        self._active_experiments[experiment_id] = exp_info

        return exp_info

    def _start_factorio_server(
        self,
        instance_id: str,
        mode: str,
        scenario: str,
        save_file: Optional[str],
        rcon_port: int,
        game_port: int
    ):
        """
        Start a Factorio server instance.

        Uses ClusterManager to handle Docker orchestration.
        """
        # For now, we'll use the existing ClusterManager's start method
        # In the future, we might want to support per-instance control

        # Count how many instances we need (based on active experiments)
        num_instances = len(self._active_experiments) + 1

        attach_mod = True  # Always attach the factorio_verse mod

        self.cluster_manager.start(
            num_instances=num_instances,
            scenario=scenario,
            attach_mod=attach_mod,
            save_file=save_file
        )

    def _create_notebook(
        self,
        notebook_path: Path,
        agent_id: str,
        experiment_id: str
    ):
        """Create a new Jupyter notebook from template."""
        from .jupyter_state import create_notebook_from_template

        create_notebook_from_template(
            notebook_path=notebook_path,
            agent_id=agent_id,
            experiment_id=experiment_id,
            pg_dsn=self.pg_dsn
        )

    def _restore_notebook(
        self,
        notebook_path: Path,
        agent_id: str,
        experiment_id: str,
        agent_state: Dict[str, Any]
    ):
        """Restore a notebook with checkpointed state."""
        from .jupyter_state import create_notebook_with_state

        create_notebook_with_state(
            notebook_path=notebook_path,
            agent_id=agent_id,
            experiment_id=experiment_id,
            pg_dsn=self.pg_dsn,
            agent_state=agent_state
        )

    def _load_checkpoint(self, checkpoint_id: str) -> Dict[str, Any]:
        """Load checkpoint data from PostgreSQL."""
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM get_checkpoint_data(%s)
                """, (checkpoint_id,))
                row = cur.fetchone()

                if not row:
                    raise ValueError(f"Checkpoint not found: {checkpoint_id}")

                return dict(row)

    def save_checkpoint(
        self,
        experiment_id: str,
        checkpoint_type: str = "manual",
        description: Optional[str] = None
    ) -> str:
        """
        Save a checkpoint for an experiment.

        This will:
        1. Trigger Factorio to save the game
        2. Extract agent state from Jupyter notebook
        3. Create checkpoint entry in PostgreSQL

        Args:
            experiment_id: Experiment ID
            checkpoint_type: 'manual', 'auto', or 'milestone'
            description: Optional checkpoint description

        Returns:
            Checkpoint ID
        """
        exp_info = self._active_experiments.get(experiment_id)
        if not exp_info:
            raise ValueError(f"Experiment not found: {experiment_id}")

        # Get current game tick from Factorio
        current_tick = self._get_current_tick(exp_info.server_rcon_port)

        # Trigger Factorio save
        save_path = self._trigger_factorio_save(
            exp_info.server_rcon_port,
            current_tick
        )

        # Extract agent state from notebook
        agent_state = self._extract_notebook_state(exp_info.notebook_path)

        # Save to PostgreSQL
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Save agent state
                cur.execute("""
                    INSERT INTO agent_state (
                        experiment_id,
                        game_tick,
                        agent_variables,
                        episode_history
                    ) VALUES (%s, %s, %s, %s)
                    RETURNING state_id
                """, (
                    experiment_id,
                    current_tick,
                    json.dumps(agent_state.get('variables', {})),
                    json.dumps(agent_state.get('history', {}))
                ))
                state_id = cur.fetchone()['state_id']

                # Create checkpoint
                cur.execute("""
                    SELECT save_checkpoint(%s, %s, %s, %s, %s)
                """, (
                    experiment_id,
                    current_tick,
                    save_path,
                    checkpoint_type,
                    description
                ))
                checkpoint_id = cur.fetchone()[0]

            conn.commit()

        return str(checkpoint_id)

    def _get_current_tick(self, rcon_port: int) -> int:
        """Get current game tick via RCON."""
        try:
            client = RCONClient('localhost', rcon_port, 'factorio')
            response = client.send_command('/sc return game.tick')
            # Parse the tick from response
            # Response format is typically just the number
            tick = int(response.strip())
            return tick
        except Exception as e:
            print(f"Warning: Could not get current tick: {e}")
            return 0

    def _trigger_factorio_save(self, rcon_port: int, tick: int) -> str:
        """
        Trigger Factorio to save the game via RCON.

        Returns the path to the save file.
        """
        save_name = f"experiment-{tick}"

        try:
            client = RCONClient('localhost', rcon_port, 'factorio')
            client.send_command(f'/server-save {save_name}')

            # Save path is in the container's saves directory
            # We need to map this to host path
            save_path = self.cluster_manager.state_dir / "saves" / f"{save_name}.zip"
            return str(save_path)

        except Exception as e:
            raise RuntimeError(f"Failed to trigger Factorio save: {e}")

    def _extract_notebook_state(self, notebook_path: str) -> Dict[str, Any]:
        """
        Extract agent state from Jupyter notebook.

        This reads the .ipynb file and extracts user-defined variables
        from the last execution state.
        """
        from .jupyter_state import extract_state_from_notebook

        return extract_state_from_notebook(Path(notebook_path))

    def list_experiments(self, status: Optional[str] = None) -> List[ExperimentInfo]:
        """
        List experiments from PostgreSQL.

        Args:
            status: Filter by status ('running', 'paused', 'completed', 'failed')

        Returns:
            List of ExperimentInfo objects
        """
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if status:
                    cur.execute("""
                        SELECT * FROM experiment_summary
                        WHERE status = %s
                        ORDER BY created_at DESC
                    """, (status,))
                else:
                    cur.execute("""
                        SELECT * FROM experiment_summary
                        ORDER BY created_at DESC
                    """)

                rows = cur.fetchall()

                return [
                    ExperimentInfo(
                        experiment_id=str(row['experiment_id']),
                        agent_id=row['agent_id'],
                        server_instance_id=row['server_instance_id'],
                        server_rcon_port=row.get('server_rcon_port', 0),
                        server_game_port=row.get('server_game_port', 0),
                        notebook_path=row.get('notebook_path', ''),
                        kernel_id=row.get('kernel_id'),
                        status=row['status'],
                        current_tick=row.get('current_tick', 0)
                    )
                    for row in rows
                ]

    def stop_experiment(self, experiment_id: str):
        """
        Stop an experiment (pause it).

        This updates the status but doesn't tear down the server.
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE experiments
                    SET status = 'paused'
                    WHERE experiment_id = %s
                """, (experiment_id,))
            conn.commit()

        if experiment_id in self._active_experiments:
            exp_info = self._active_experiments[experiment_id]
            exp_info.status = 'paused'

    def complete_experiment(self, experiment_id: str):
        """Mark an experiment as completed."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE experiments
                    SET status = 'completed',
                        completed_at = NOW()
                    WHERE experiment_id = %s
                """, (experiment_id,))
            conn.commit()

        if experiment_id in self._active_experiments:
            del self._active_experiments[experiment_id]

    def get_experiment_info(self, experiment_id: str) -> ExperimentInfo:
        """Get information about an experiment."""
        # Check memory cache first
        if experiment_id in self._active_experiments:
            return self._active_experiments[experiment_id]

        # Otherwise query database
        experiments = self.list_experiments()
        for exp in experiments:
            if exp.experiment_id == experiment_id:
                return exp

        raise ValueError(f"Experiment not found: {experiment_id}")
