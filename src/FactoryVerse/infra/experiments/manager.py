"""
ExperimentManager: Orchestrates all FactoryVerse services and experiments.

This manager is the single source of truth for:
1. Platform lifecycle (PostgreSQL + Jupyter)
2. Experiment lifecycle (Factorio servers + databases + notebooks)
3. Service coupling and state management
4. Multi-agent experiment support

Architecture:
- 1 Platform = 1 PostgreSQL + 1 Jupyter (shared across all experiments)
- 1 Experiment = 1 Factorio Server + 1 Database + N Agents + N Notebooks
- All orchestration goes through this manager
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

from ..docker.docker_manager import ClusterManager, START_RCON_PORT, START_GAME_PORT


@dataclass
class ExperimentInfo:
    """Information about a running experiment."""
    experiment_id: str
    experiment_name: str
    factorio_instance_id: int
    database_name: str
    scenario: str
    status: str
    rcon_port: int
    game_port: int
    agents: List['AgentInfo']
    created_at: datetime


@dataclass
class AgentInfo:
    """Information about an agent in an experiment."""
    agent_id: str
    agent_name: str
    notebook_path: str
    jupyter_kernel_id: Optional[str]
    status: str


class ExperimentManager:
    """
    Single orchestrator for all FactoryVerse services and experiments.
    
    This manager handles:
    - Platform services (PostgreSQL + Jupyter)
    - Experiment lifecycle (Factorio + Database + Notebooks)
    - Service coupling and state management
    - Multi-agent experiment support
    """
    
    def __init__(
        self,
        state_dir: Optional[Path] = None,
        work_dir: Optional[Path] = None,
        pg_dsn: Optional[str] = None
    ):
        """
        Initialize ExperimentManager.
        
        Args:
            state_dir: Directory for Docker state files
            work_dir: Working directory for notebooks and data
            pg_dsn: PostgreSQL connection string (auto-detected if None)
        """
        self.cluster_manager = ClusterManager(state_dir, work_dir)
        self.work_dir = work_dir or Path.cwd()
        self.notebooks_dir = self.work_dir / "notebooks"
        self.notebooks_dir.mkdir(parents=True, exist_ok=True)
        
        # Auto-detect PostgreSQL DSN if not provided
        # Connect to factoryverse_template database where experiments table exists
        base_dsn = pg_dsn or self.cluster_manager.get_postgres_dsn()
        self.pg_dsn = base_dsn.replace('/postgres', '/factoryverse_template')
        
        # Track active experiments in memory
        self._active_experiments: Dict[str, ExperimentInfo] = {}
        
        # Ensure database schema exists
        self._ensure_schema()
    
    def _ensure_schema(self):
        """Ensure the experiment management schema exists in PostgreSQL.
        
        Note: Schema is automatically loaded by Docker container initialization scripts.
        This method is kept for compatibility but does nothing since the container
        handles all schema setup during startup.
        """
        # Schema is handled by Docker container initialization scripts
        # No need to manually load schema here
        pass
    
    def _ensure_template_database(self):
        """Ensure factoryverse_template database exists and is properly initialized."""
        base_dsn = self.cluster_manager.get_postgres_dsn()
        
        # Check if template database exists
        try:
            conn = psycopg2.connect(self.pg_dsn)
            conn.close()
            print("✅ Template database exists")
        except psycopg2.OperationalError as e:
            if "database \"factoryverse_template\" does not exist" in str(e):
                print("Creating factoryverse_template database...")
                conn = psycopg2.connect(base_dsn)
                conn.autocommit = True
                with conn.cursor() as cur:
                    cur.execute("CREATE DATABASE factoryverse_template;")
                conn.close()
                print("✅ Template database created")
            else:
                raise
        
        # Check if template database has proper schema
        try:
            conn = psycopg2.connect(self.pg_dsn)
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'factoryverse';")
                table_count = cur.fetchone()[0]
                if table_count == 0:
                    print("Template database is empty, running setup scripts...")
                    self._setup_template_database()
                    print("✅ Template database initialized")
                else:
                    print(f"✅ Template database has {table_count} tables")
            conn.close()
        except Exception as e:
            print(f"Error checking template database: {e}")
            raise
    
    def _setup_template_database(self):
        """Setup the factoryverse_template database with required schema."""
        import subprocess
        
        # Get the schema directory path
        schema_dir = Path(__file__).parent.parent / "db" / "schema"
        
        # Run the setup scripts in order using psql through the container
        setup_scripts = [
            "01_setup_template.sql",
            "01_experiments.sql", 
            "02_map_snapshot.sql",
            "03_recurring_snapshot.sql",
            "04_ondemand_snapshot.sql",
            "05_spatial_views.sql",
            "06_load_functions.sql"
        ]
        
        for script in setup_scripts:
            script_path = schema_dir / script
            if script_path.exists():
                print(f"Running {script}...")
                
                # Execute the SQL script using psql through the container
                cmd = [
                    "docker", "exec", "-i", "-e", "PGPASSWORD=factoryverse",
                    "factoryverse-postgres-1", "psql", "-U", "factoryverse", 
                    "-d", "factoryverse_template", "-h", "localhost"
                ]
                
                try:
                    with open(script_path, 'r') as f:
                        result = subprocess.run(cmd, stdin=f, capture_output=True, text=True, check=True)
                        print(f"✅ {script} executed successfully")
                except subprocess.CalledProcessError as e:
                    print(f"❌ Error executing {script}:")
                    print(f"stdout: {e.stdout}")
                    print(f"stderr: {e.stderr}")
                    raise
    
    def _get_connection(self):
        """Get a PostgreSQL connection."""
        return psycopg2.connect(self.pg_dsn)
    
    def is_platform_running(self) -> bool:
        """Check if platform services (PostgreSQL + Jupyter) are running."""
        return (
            self.cluster_manager.is_service_running("postgres") and
            self.cluster_manager.is_service_running("jupyter")
        )
    
    def start_platform(self) -> None:
        """
        Start platform services (PostgreSQL + Jupyter).
        
        This starts the shared services that all experiments use.
        """
        print("Starting FactoryVerse platform services...")
        
        # Generate compose file with 0 Factorio instances (platform only)
        self.cluster_manager.generate_compose(
            num_instances=0,
            scenario="factorio_verse",  # Default scenario
            attach_mod=True
        )
        
        # Start services
        self.cluster_manager.start_services()
        
        # Wait for PostgreSQL to be ready
        print("Waiting for PostgreSQL to be ready...")
        import time
        for _ in range(30):  # Wait up to 30 seconds
            try:
                # First check if we can connect to postgres database
                base_dsn = self.cluster_manager.get_postgres_dsn()
                conn = psycopg2.connect(base_dsn)
                conn.close()
                break
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                time.sleep(1)
        else:
            raise RuntimeError("PostgreSQL failed to start within 30 seconds")
        
        # Wait a bit more for initialization scripts to complete
        print("Waiting for database initialization to complete...")
        time.sleep(5)
        
        # Ensure factoryverse_template database exists and is properly initialized
        self._ensure_template_database()
        
        print("✅ Platform services started!")
        print(f"  📊 PostgreSQL: localhost:5432")
        print(f"  📓 Jupyter: http://localhost:8888")
        print(f"  📁 Notebooks: {self.notebooks_dir}")
    
    def stop_platform(self) -> None:
        """Stop all platform services."""
        print("Stopping FactoryVerse platform services...")
        self.cluster_manager.stop_services()
        print("✅ Platform services stopped.")
    
    def create_experiment(
        self,
        experiment_name: str,
        scenario: str = "factorio_verse",
        agent_names: List[str] = None
    ) -> ExperimentInfo:
        """
        Create a new experiment.
        
        This will:
        1. Assign a new Factorio instance ID
        2. Create/clean the database
        3. Start the Factorio server
        4. Create notebooks for each agent
        5. Register the experiment in PostgreSQL
        
        Args:
            experiment_name: Name of the experiment
            scenario: Factorio scenario to use
            agent_names: List of agent names (default: ['agent_0'])
            
        Returns:
            ExperimentInfo with experiment details
        """
        if agent_names is None:
            agent_names = ['agent_0']
        
        # Check if platform is running
        if not self.is_platform_running():
            raise RuntimeError(
                "Platform services not running. Call start_platform() first."
            )
        
        # Assign instance ID (find next available)
        instance_id = self._get_next_instance_id()
        database_name = f"factoryverse_{instance_id}"
        
        # Calculate ports
        rcon_port = START_RCON_PORT + instance_id
        game_port = START_GAME_PORT + instance_id
        
        # Create/clean database
        self._create_database(instance_id)
        
        # Start Factorio server
        self._start_factorio_server(instance_id, scenario, rcon_port, game_port)
        
        # Create agent notebooks
        agents = []
        for agent_name in agent_names:
            agent_info = self._create_agent_notebook(
                experiment_name, instance_id, agent_name
            )
            agents.append(agent_info)
        
        # Register experiment in PostgreSQL
        experiment_id = self._register_experiment(
            experiment_name, instance_id, database_name, scenario, agents
        )
        
        # Create experiment info
        exp_info = ExperimentInfo(
            experiment_id=experiment_id,
            experiment_name=experiment_name,
            factorio_instance_id=instance_id,
            database_name=database_name,
            scenario=scenario,
            status='running',
            rcon_port=rcon_port,
            game_port=game_port,
            agents=agents,
            created_at=datetime.now()
        )
        
        self._active_experiments[experiment_id] = exp_info
        
        return exp_info
    
    def stop_experiment(self, experiment_id: str) -> None:
        """
        Stop an experiment.
        
        This stops the Factorio server and updates the experiment status.
        The database and notebooks are preserved.
        """
        exp_info = self._get_experiment_info(experiment_id)
        
        # Stop Factorio server
        self._stop_factorio_server(exp_info.factorio_instance_id)
        
        # Update status in database
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE experiments 
                    SET status = 'paused', updated_at = NOW()
                    WHERE experiment_id = %s
                """, (experiment_id,))
            conn.commit()
        
        # Update in-memory status
        if experiment_id in self._active_experiments:
            self._active_experiments[experiment_id].status = 'paused'
        
        print(f"✅ Experiment '{exp_info.experiment_name}' stopped.")
    
    def restart_experiment(self, experiment_id: str, clean_db: bool = True) -> None:
        """
        Restart an experiment.
        
        Args:
            experiment_id: Experiment to restart
            clean_db: Whether to reload database snapshots
        """
        exp_info = self._get_experiment_info(experiment_id)
        
        # Stop current server
        self._stop_factorio_server(exp_info.factorio_instance_id)
        
        # Clean database if requested
        if clean_db:
            self._reload_database_snapshots(exp_info.factorio_instance_id)
        
        # Start server again
        self._start_factorio_server(
            exp_info.factorio_instance_id,
            exp_info.scenario,
            exp_info.rcon_port,
            exp_info.game_port
        )
        
        # Update status
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE experiments 
                    SET status = 'running', updated_at = NOW()
                    WHERE experiment_id = %s
                """, (experiment_id,))
            conn.commit()
        
        if experiment_id in self._active_experiments:
            self._active_experiments[experiment_id].status = 'running'
        
        print(f"✅ Experiment '{exp_info.experiment_name}' restarted.")
    
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
                        SELECT e.*, STRING_AGG(a.agent_name, ', ' ORDER BY a.agent_name) as agent_names
                        FROM experiments e
                        LEFT JOIN agents a ON e.experiment_id = a.experiment_id
                        WHERE e.status = %s
                        GROUP BY e.experiment_id
                        ORDER BY e.created_at DESC
                    """, (status,))
                else:
                    cur.execute("""
                        SELECT e.*, STRING_AGG(a.agent_name, ', ' ORDER BY a.agent_name) as agent_names
                        FROM experiments e
                        LEFT JOIN agents a ON e.experiment_id = a.experiment_id
                        GROUP BY e.experiment_id
                        ORDER BY e.created_at DESC
                    """)
                
                rows = cur.fetchall()
                
                experiments = []
                for row in rows:
                    # Get agents for this experiment
                    cur.execute("""
                        SELECT agent_id, agent_name, notebook_path, jupyter_kernel_id, status
                        FROM agents
                        WHERE experiment_id = %s
                        ORDER BY agent_name
                    """, (row['experiment_id'],))
                    
                    agent_rows = cur.fetchall()
                    agents = [
                        AgentInfo(
                            agent_id=str(agent['agent_id']),
                            agent_name=agent['agent_name'],
                            notebook_path=agent['notebook_path'],
                            jupyter_kernel_id=agent['jupyter_kernel_id'],
                            status=agent['status']
                        )
                        for agent in agent_rows
                    ]
                    
                    experiments.append(ExperimentInfo(
                        experiment_id=str(row['experiment_id']),
                        experiment_name=row['experiment_name'],
                        factorio_instance_id=row['factorio_instance_id'],
                        database_name=row['database_name'],
                        scenario=row['scenario'],
                        status=row['status'],
                        rcon_port=row.get('rcon_port', START_RCON_PORT + row['factorio_instance_id']),
                        game_port=row.get('game_port', START_GAME_PORT + row['factorio_instance_id']),
                        agents=agents,
                        created_at=row['created_at']
                    ))
                
                return experiments
    
    def get_experiment_info(self, experiment_id: str) -> ExperimentInfo:
        """Get information about a specific experiment."""
        # Check memory cache first
        if experiment_id in self._active_experiments:
            return self._active_experiments[experiment_id]
        
        # Query database
        experiments = self.list_experiments()
        for exp in experiments:
            if exp.experiment_id == experiment_id:
                return exp
        
        raise ValueError(f"Experiment not found: {experiment_id}")
    
    def _get_next_instance_id(self) -> int:
        """Get the next available Factorio instance ID."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COALESCE(MAX(factorio_instance_id), -1) + 1
                    FROM experiments
                """)
                return cur.fetchone()[0]
    
    def _create_database(self, instance_id: int) -> str:
        """Create or clean database for instance."""
        db_name = f"factoryverse_{instance_id}"
        
        # Connect to postgres database (not template) for database creation
        # Use the cluster manager's base DSN
        base_dsn = self.cluster_manager.get_postgres_dsn()
        
        # Use autocommit connection for CREATE DATABASE
        conn = psycopg2.connect(base_dsn)
        conn.autocommit = True
        
        try:
            with conn.cursor() as cur:
                # Check if database exists
                cur.execute("SELECT EXISTS(SELECT FROM pg_database WHERE datname = %s)", (db_name,))
                if not cur.fetchone()[0]:
                    # Create database from template
                    cur.execute(f"CREATE DATABASE {db_name} TEMPLATE factoryverse_template")
                    print(f"✅ Created database: {db_name}")
                else:
                    print(f"📊 Database already exists: {db_name}")
        finally:
            conn.close()
        
        # Reload snapshots to ensure clean state
        self._reload_database_snapshots(instance_id)
        
        return db_name
    
    def _reload_database_snapshots(self, instance_id: int) -> None:
        """Reload database snapshots from CSV files."""
        db_name = f"factoryverse_{instance_id}"
        # Extract base connection info and connect to instance database
        base_dsn = self.pg_dsn.replace('/factoryverse_template', '')
        instance_dsn = f"{base_dsn}/{db_name}"
        
        try:
            with psycopg2.connect(instance_dsn) as conn:
                with conn.cursor() as cur:
                    # Call the load function if it exists
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.routines 
                            WHERE routine_name = 'load_map_snapshot_from_csv'
                        )
                    """)
                    if cur.fetchone()[0]:
                        cur.execute("SELECT * FROM load_map_snapshot_from_csv(%s);", (instance_id,))
                        results = cur.fetchall()
                        print(f"Reloaded snapshots for {db_name}: {len(results)} tables")
        except psycopg2.OperationalError as e:
            print(f"Warning: Could not reload snapshots for {db_name}: {e}")
    
    def _start_factorio_server(self, instance_id: int, scenario: str, rcon_port: int, game_port: int) -> None:
        """Start a Factorio server instance and wait for initial snapshot."""
        print(f"Starting Factorio server {instance_id}...")
        
        # Regenerate compose file with this instance
        self.cluster_manager.generate_compose(
            num_instances=instance_id + 1,
            scenario=scenario,
            attach_mod=True
        )
        
        # Start the Factorio service
        self.cluster_manager.start_services()
        
        # Wait for Factorio to take initial snapshot
        print(f"Waiting for Factorio server {instance_id} to take initial snapshot...")
        self._wait_for_initial_snapshot(instance_id)
        
        print(f"✅ Factorio server {instance_id} started (RCON: {rcon_port}, Game: {game_port})")
    
    def _wait_for_initial_snapshot(self, instance_id: int) -> None:
        """Wait for Factorio to take initial snapshot and load it into database."""
        import time
        import subprocess
        
        rcon_port = START_RCON_PORT + instance_id
        
        # Wait for Factorio server to be ready
        print(f"Waiting for Factorio server {instance_id} to be ready...")
        time.sleep(5)  # Give Factorio time to start
        
        # Trigger map snapshot via RCON
        print(f"Triggering map snapshot via RCON...")
        try:
            # Use rcon-cli to send the command
            cmd = [
                "docker", "exec", "factoryverse-factorio_0-1",
                "rcon-cli", "--host", "localhost", "--port", str(rcon_port), "--password", "factorio",
                "take_map_snapshot"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                print("✅ Map snapshot triggered successfully")
            else:
                print(f"⚠️  RCON command failed: {result.stderr}")
        except Exception as e:
            print(f"⚠️  Could not trigger map snapshot: {e}")
        
        # Wait for snapshot files to be created
        snapshot_dir = self.work_dir / ".fv" / "snapshots" / f"factorio_{instance_id}" / "chunks"
        max_wait = 30  # 30 seconds timeout
        for i in range(max_wait):
            if snapshot_dir.exists() and any(snapshot_dir.iterdir()):
                print(f"✅ Snapshot directory found: {snapshot_dir}")
                break
            time.sleep(1)
        else:
            print(f"⚠️  Warning: No snapshot found after {max_wait} seconds")
            return
        
        # Load the snapshot data into the database
        print(f"Loading snapshot data for instance {instance_id}...")
        self._reload_database_snapshots(instance_id)
    
    def _stop_factorio_server(self, instance_id: int) -> None:
        """Stop a Factorio server instance."""
        # For now, we'll stop all services and restart without this instance
        # In the future, we could implement per-instance control
        print(f"Stopping Factorio server {instance_id}...")
        # Note: This is a simplified implementation
        # Full implementation would require per-container control
    
    def _create_agent_notebook(self, experiment_name: str, instance_id: int, agent_name: str) -> AgentInfo:
        """Create a notebook for an agent."""
        notebook_name = f"{experiment_name}_{agent_name}.ipynb"
        notebook_path = self.notebooks_dir / notebook_name
        
        # Create basic notebook structure
        notebook_content = {
            "cells": [
                {
                    "cell_type": "markdown",
                    "metadata": {},
                    "source": [
                        f"# {agent_name} - {experiment_name}\n",
                        f"\n",
                        f"Agent notebook for experiment {experiment_name} on Factorio instance {instance_id}.\n",
                        f"\n",
                        f"## Connection Info\n",
                        f"- Database: factoryverse_{instance_id}\n",
                        f"- RCON Port: {START_RCON_PORT + instance_id}\n",
                        f"- Game Port: {START_GAME_PORT + instance_id}"
                    ]
                },
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": [
                        "# Import required libraries\n",
                        "import psycopg2\n",
                        "from factorio_rcon import RCONClient\n",
                        "import json\n",
                        "import pandas as pd\n",
                        "\n",
                        "# Connection settings\n",
                        f"DB_NAME = 'factoryverse_{instance_id}'\n",
                        f"RCON_PORT = {START_RCON_PORT + instance_id}\n",
                        f"GAME_PORT = {START_GAME_PORT + instance_id}\n",
                        "\n",
                        "# Database connection\n",
                        "db_conn = psycopg2.connect(f'postgresql://factoryverse:factoryverse@localhost:5432/{DB_NAME}')\n",
                        "\n",
                        "# RCON connection\n",
                        "rcon_client = RCONClient('localhost', RCON_PORT, 'factorio')\n",
                        "\n",
                        "print(f'Connected to {DB_NAME} database and Factorio RCON')"
                    ]
                }
            ],
            "metadata": {
                "kernelspec": {
                    "display_name": "Python 3",
                    "language": "python",
                    "name": "python3"
                }
            },
            "nbformat": 4,
            "nbformat_minor": 4
        }
        
        # Write notebook file
        with open(notebook_path, 'w') as f:
            json.dump(notebook_content, f, indent=2)
        
        return AgentInfo(
            agent_id=str(uuid.uuid4()),
            agent_name=agent_name,
            notebook_path=str(notebook_path),
            jupyter_kernel_id=None,
            status='running'
        )
    
    def _register_experiment(
        self,
        experiment_name: str,
        instance_id: int,
        database_name: str,
        scenario: str,
        agents: List[AgentInfo]
    ) -> str:
        """Register experiment and agents in PostgreSQL."""
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Create experiment
                cur.execute("""
                    SELECT create_experiment(%s, %s, %s, %s)
                """, (experiment_name, instance_id, database_name, scenario))
                result = cur.fetchone()
                experiment_id = result['create_experiment']
                
                # Add agents
                for agent in agents:
                    cur.execute("""
                        SELECT add_agent(%s, %s, %s)
                    """, (experiment_id, agent.agent_name, agent.notebook_path))
                    agent_result = cur.fetchone()
                    agent.agent_id = str(agent_result['add_agent'])
                
            conn.commit()
        
        return str(experiment_id)