"""
AgentContext: Minimal metadata holder for experiments.

TODO: This is a placeholder. The actual action/observation interface
should be implemented as direct Python functions available in the notebook
environment (see factorio-verse.md for the vision).

Expected interface (to be implemented):
    - move_to(position)
    - place_entity(prototype, position)
    - craft_item(prototype, count)
    - harvest_resource(position, amount)
    - query_db(sql) -> results
    - connect_entities(unit_number)
    - etc.

This class only provides experiment metadata and low-level DB/RCON access
for building the higher-level action/observation wrappers.
"""

import json
from typing import Optional, Dict, Any
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from factorio_rcon import RCONClient


class AgentContext:
    """
    Minimal context for experiment metadata.

    Provides:
    - experiment_id, agent_id
    - PostgreSQL connection (db_connection, db_query, db_execute)
    - RCON connection (rcon_call, rcon_command)

    DOES NOT implement the action/observation interface for agents.
    That should be separate modules providing direct functions.

    TODO: Implement action/observation wrappers (see factorio-verse.md):
        from factorio_actions import move_to, place_entity, craft_item, ...
        from factorio_observations import query_db, nearest_resource, ...
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

    def rcon_command(self, command: str) -> str:
        """
        Low-level RCON command execution.

        For building action/observation wrappers.
        Agents should NOT use this directly.
        """
        return self.rcon_call(command)

    def get_current_tick(self) -> int:
        """Get current game tick via RCON."""
        response = self.rcon_call('/sc return game.tick')
        return int(response.strip())

    def __repr__(self) -> str:
        return (
            f"AgentContext(experiment_id='{self.experiment_id}', "
            f"agent_id='{self.agent_id}', "
            f"factorio={self.factorio_host}:{self.factorio_rcon_port})"
        )
