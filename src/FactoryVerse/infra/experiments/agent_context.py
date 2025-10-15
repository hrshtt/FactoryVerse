"""
AgentContext: Convenience wrapper for agent notebooks.

Provides a unified interface to:
- PostgreSQL database queries
- RCON commands to Factorio
- Experiment metadata
"""

import json
from typing import Optional, Dict, Any
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from factorio_rcon import RCONClient


class AgentContext:
    """
    Context object for agent notebooks.

    Provides convenient access to:
    - Database queries (PostgreSQL)
    - Game commands (RCON)
    - Experiment metadata

    Usage in notebook:
        ctx = AgentContext(
            experiment_id='...',
            agent_id='agent1',
            factorio_host='localhost',
            factorio_rcon_port=27000,
            pg_dsn='postgresql://...'
        )

        # Query game state
        with ctx.db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM sp_resource_patches LIMIT 10")
            resources = cur.fetchall()

        # Execute game command
        result = ctx.rcon_call('game.print("Hello from agent!")')
    """

    def __init__(
        self,
        experiment_id: str,
        agent_id: str,
        factorio_host: str,
        factorio_rcon_port: int,
        pg_dsn: str,
        rcon_password: str = "factorio"
    ):
        """
        Initialize AgentContext.

        Args:
            experiment_id: Experiment UUID
            agent_id: Agent identifier
            factorio_host: Factorio server hostname/IP
            factorio_rcon_port: Factorio RCON port
            pg_dsn: PostgreSQL connection string
            rcon_password: RCON password (default: 'factorio')
        """
        self.experiment_id = experiment_id
        self.agent_id = agent_id
        self.factorio_host = factorio_host
        self.factorio_rcon_port = factorio_rcon_port
        self.pg_dsn = pg_dsn
        self.rcon_password = rcon_password

        # Lazy connections
        self._rcon_client: Optional[RCONClient] = None

    @contextmanager
    def db_connection(self):
        """
        Get a PostgreSQL connection as a context manager.

        Usage:
            with ctx.db_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT ...")
        """
        conn = psycopg2.connect(self.pg_dsn)
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise
        finally:
            conn.close()

    def db_query(self, query: str, params: tuple = None) -> list:
        """
        Execute a database query and return results as list of dicts.

        Args:
            query: SQL query
            params: Query parameters (for %s placeholders)

        Returns:
            List of result rows as dicts
        """
        with self.db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                return [dict(row) for row in cur.fetchall()]

    def db_execute(self, query: str, params: tuple = None):
        """
        Execute a database command (INSERT, UPDATE, DELETE).

        Args:
            query: SQL command
            params: Query parameters
        """
        with self.db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)

    @property
    def rcon(self) -> RCONClient:
        """
        Get RCON client (lazy initialization).

        Returns:
            RCONClient instance
        """
        if self._rcon_client is None:
            self._rcon_client = RCONClient(
                self.factorio_host,
                self.factorio_rcon_port,
                self.rcon_password
            )
        return self._rcon_client

    def rcon_call(self, command: str) -> str:
        """
        Execute RCON command in Factorio.

        Args:
            command: Lua command to execute

        Returns:
            Command response string
        """
        return self.rcon.send_command(command)

    def call_action(self, action_name: str, params: Dict[str, Any]) -> Any:
        """
        Call a Factorio action via the action system.

        Args:
            action_name: Action name (e.g., 'agent.walk', 'entity.place')
            params: Action parameters

        Returns:
            Action result (parsed from Lua table)
        """
        from ..rcon import _lua2python

        params_json = json.dumps(params)
        command = f'remote.call("actions", "{action_name}", {params_json})'
        response = self.rcon_call(command)

        # Parse Lua response
        result, _ = _lua2python(command, response)
        return result

    def enqueue_action(
        self,
        action_name: str,
        params: Dict[str, Any],
        key: Optional[str] = None,
        priority: int = 0
    ) -> str:
        """
        Enqueue action in the action queue.

        Args:
            action_name: Action name
            params: Action parameters
            key: Queue key (for batching, defaults to agent_id)
            priority: Action priority (higher = earlier execution)

        Returns:
            Correlation ID for tracking
        """
        from ..rcon import _lua2python

        if key is None:
            key = self.agent_id

        params_json = json.dumps(params)
        command = f'remote.call("action_queue", "enqueue", "{action_name}", {params_json}, "{key}", {priority})'
        response = self.rcon_call(command)

        # Parse correlation ID
        result, _ = _lua2python(command, response)
        return result.get('correlation_id') if result else None

    def get_action_result(self, correlation_id: str) -> Optional[Dict[str, Any]]:
        """
        Get result of a queued action.

        Args:
            correlation_id: Correlation ID from enqueue_action

        Returns:
            Action result if available, None if still pending
        """
        from ..rcon import _lua2python

        command = f'remote.call("action_queue", "get_result", "{correlation_id}")'
        response = self.rcon_call(command)

        result, _ = _lua2python(command, response)
        return result

    def get_current_tick(self) -> int:
        """
        Get current game tick.

        Returns:
            Current tick number
        """
        response = self.rcon_call('/sc return game.tick')
        return int(response.strip())

    def take_snapshot(self, snapshot_type: str = "entities"):
        """
        Trigger a snapshot capture in Factorio.

        Args:
            snapshot_type: 'entities' or 'resource'
        """
        if snapshot_type == "entities":
            self.rcon_call('/c remote.call("admin", "take_entities_snapshot")')
        elif snapshot_type == "resource":
            self.rcon_call('/c remote.call("admin", "take_resource_snapshot")')
        else:
            raise ValueError(f"Unknown snapshot type: {snapshot_type}")

    def get_experiment_info(self) -> Dict[str, Any]:
        """
        Get experiment metadata from database.

        Returns:
            Experiment info dict
        """
        results = self.db_query("""
            SELECT * FROM experiment_summary
            WHERE experiment_id = %s
        """, (self.experiment_id,))

        if not results:
            raise ValueError(f"Experiment not found: {self.experiment_id}")

        return results[0]

    def get_latest_checkpoint(self) -> Optional[Dict[str, Any]]:
        """
        Get latest checkpoint for this experiment.

        Returns:
            Checkpoint info dict or None
        """
        results = self.db_query("""
            SELECT * FROM latest_checkpoint
            WHERE experiment_id = %s
        """, (self.experiment_id,))

        return results[0] if results else None

    def save_metric(self, metric_name: str, metric_value: float, tick: Optional[int] = None):
        """
        Save a metric for this experiment.

        Args:
            metric_name: Metric name (e.g., 'reward', 'items_crafted')
            metric_value: Numeric value
            tick: Game tick (defaults to current tick)
        """
        if tick is None:
            tick = self.get_current_tick()

        self.db_execute("""
            INSERT INTO experiment_metrics (experiment_id, game_tick, metric_name, metric_value)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (experiment_id, game_tick, metric_name)
            DO UPDATE SET metric_value = EXCLUDED.metric_value
        """, (self.experiment_id, tick, metric_name, metric_value))

    def get_metrics(self, metric_name: str, limit: int = 100) -> list:
        """
        Get historical metrics for this experiment.

        Args:
            metric_name: Metric name
            limit: Maximum number of results

        Returns:
            List of metric records
        """
        return self.db_query("""
            SELECT game_tick, metric_value, created_at
            FROM experiment_metrics
            WHERE experiment_id = %s AND metric_name = %s
            ORDER BY game_tick DESC
            LIMIT %s
        """, (self.experiment_id, metric_name, limit))

    def __repr__(self) -> str:
        return (
            f"AgentContext(experiment_id='{self.experiment_id}', "
            f"agent_id='{self.agent_id}', "
            f"factorio={self.factorio_host}:{self.factorio_rcon_port})"
        )
