"""Verification data sources.

This module provides pluggable sources for production statistics:
- RCONSource: Query Lua storage directly (game paused or running)
- JSONLSource: Read from snapshot JSONL files (offline/batch evaluation)
- DuckDBSource: Query from loaded DuckDB database (if available)

All sources implement the VerificationSource protocol.
"""

import json
import logging
from pathlib import Path
from typing import Protocol, TypedDict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from FactoryVerse.infra.rcon_helper import RCONHelper
    import duckdb

logger = logging.getLogger(__name__)


class ProductionStats(TypedDict):
    """Force-level production statistics."""

    output: dict[str, int]  # Items produced: {item_name: count}
    input: dict[str, int]  # Items consumed: {item_name: count}


class ManualStats(TypedDict):
    """Manual production statistics for an agent."""

    crafted: dict[str, int]  # Hand-crafted items: {item_name: count}
    mined: dict[str, int]  # Hand-mined items: {item_name: count}
    agent_id: int
    tick: int


class VerificationSource(Protocol):
    """Protocol for any source of production data.

    Implementations can query data from different sources:
    - RCON: Direct Lua storage access
    - JSONL: Offline snapshot files
    - DuckDB: Loaded database

    All methods are async to support network-based sources.
    """

    async def get_force_production(self, agent_id: int) -> ProductionStats:
        """Get force-level production statistics.

        Args:
            agent_id: The agent ID to get stats for

        Returns:
            ProductionStats with output and input item counts
        """
        ...

    async def get_manual_production(self, agent_id: int) -> ManualStats:
        """Get manual production statistics for an agent.

        Args:
            agent_id: The agent ID to get stats for

        Returns:
            ManualStats with crafted and mined item counts
        """
        ...


class RCONSource:
    """Query Lua storage directly via RCON.

    This source queries the game directly, which is useful for:
    - Real-time verification during gameplay
    - Verification when game is paused
    - Testing verification logic

    Requires an active RCON connection.
    """

    def __init__(self, rcon_helper: "RCONHelper"):
        """Initialize with an RCONHelper.

        Args:
            rcon_helper: Configured RCONHelper instance
        """
        self._rcon = rcon_helper

    async def get_force_production(self, agent_id: int) -> ProductionStats:
        """Get force-level production statistics via RCON.

        Args:
            agent_id: The agent ID to get stats for

        Returns:
            ProductionStats with output and input item counts
        """
        result = self._rcon.run(
            category=str(agent_id),
            method="get_production_statistics",
            args={},
            safe=True,
            verbose=False,
        )

        # Handle safe wrapper response
        if "result" in result:
            result = result["result"]

        return ProductionStats(
            output=result.get("output", {}),
            input=result.get("input", {}),
        )

    async def get_manual_production(self, agent_id: int) -> ManualStats:
        """Get manual production statistics via RCON.

        Args:
            agent_id: The agent ID to get stats for

        Returns:
            ManualStats with crafted and mined item counts
        """
        result = self._rcon.run(
            category=str(agent_id),
            method="get_manual_production_statistics",
            args={},
            safe=True,
            verbose=False,
        )

        # Handle safe wrapper response
        if "result" in result:
            result = result["result"]

        return ManualStats(
            crafted=result.get("crafted", {}),
            mined=result.get("mined", {}),
            agent_id=result.get("agent_id", agent_id),
            tick=result.get("tick", 0),
        )


class JSONLSource:
    """Read from snapshot JSONL files.

    This source reads from pre-recorded snapshot files, useful for:
    - Offline/batch evaluation
    - Replaying and analyzing past runs
    - CI/CD testing without running Factorio

    Expected file format:
    - Each line is a JSON object with snapshot data
    - Agent stats are in the 'agents' key
    - Force production is in agent's 'production_statistics'
    - Manual production is in agent's 'manual_production_statistics'
    """

    def __init__(self, snapshot_path: Path):
        """Initialize with path to snapshot JSONL file.

        Args:
            snapshot_path: Path to the JSONL file
        """
        self._path = snapshot_path
        self._cache: Optional[dict] = None

    def _load_latest_snapshot(self) -> dict:
        """Load the latest snapshot from the JSONL file."""
        if self._cache is not None:
            return self._cache

        if not self._path.exists():
            raise FileNotFoundError(f"Snapshot file not found: {self._path}")

        # Read the last line (most recent snapshot)
        last_line = None
        with open(self._path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    last_line = line

        if last_line is None:
            raise ValueError(f"Snapshot file is empty: {self._path}")

        self._cache = json.loads(last_line)
        return self._cache

    def _get_agent_data(self, agent_id: int) -> dict:
        """Get agent data from snapshot."""
        snapshot = self._load_latest_snapshot()

        agents = snapshot.get("agents", [])
        for agent in agents:
            if agent.get("agent_id") == agent_id:
                return agent

        raise KeyError(f"Agent {agent_id} not found in snapshot")

    async def get_force_production(self, agent_id: int) -> ProductionStats:
        """Get force-level production statistics from snapshot.

        Args:
            agent_id: The agent ID to get stats for

        Returns:
            ProductionStats with output and input item counts
        """
        agent = self._get_agent_data(agent_id)
        production = agent.get("production_statistics", {})

        return ProductionStats(
            output=production.get("output", {}),
            input=production.get("input", {}),
        )

    async def get_manual_production(self, agent_id: int) -> ManualStats:
        """Get manual production statistics from snapshot.

        Args:
            agent_id: The agent ID to get stats for

        Returns:
            ManualStats with crafted and mined item counts
        """
        agent = self._get_agent_data(agent_id)
        manual = agent.get("manual_production_statistics", {})
        snapshot = self._load_latest_snapshot()

        return ManualStats(
            crafted=manual.get("crafted", {}),
            mined=manual.get("mined", {}),
            agent_id=agent_id,
            tick=snapshot.get("tick", 0),
        )

    def clear_cache(self) -> None:
        """Clear the cached snapshot data."""
        self._cache = None


class DuckDBSource:
    """Query from loaded DuckDB database.

    This source queries the DuckDB database, useful for:
    - SQL-based verification queries
    - Aggregating data across multiple agents
    - Complex filtering and analysis

    Requires a DuckDB connection with loaded snapshot data.
    """

    def __init__(self, connection: "duckdb.DuckDBPyConnection"):
        """Initialize with a DuckDB connection.

        Args:
            connection: Active DuckDB connection with loaded data
        """
        self._conn = connection

    async def get_force_production(self, agent_id: int) -> ProductionStats:
        """Get force-level production statistics from DuckDB.

        Queries the agent_production_statistics table (or similar).

        Args:
            agent_id: The agent ID to get stats for

        Returns:
            ProductionStats with output and input item counts
        """
        # Query output items
        output_query = """
            SELECT item_name, count
            FROM agent_production_statistics
            WHERE agent_id = ? AND direction = 'output'
        """
        output_result = self._conn.execute(output_query, [agent_id]).fetchall()
        output = {row[0]: row[1] for row in output_result}

        # Query input items
        input_query = """
            SELECT item_name, count
            FROM agent_production_statistics
            WHERE agent_id = ? AND direction = 'input'
        """
        input_result = self._conn.execute(input_query, [agent_id]).fetchall()
        input_items = {row[0]: row[1] for row in input_result}

        return ProductionStats(
            output=output,
            input=input_items,
        )

    async def get_manual_production(self, agent_id: int) -> ManualStats:
        """Get manual production statistics from DuckDB.

        Queries the agent_manual_production_statistics table.

        Args:
            agent_id: The agent ID to get stats for

        Returns:
            ManualStats with crafted and mined item counts
        """
        # Query crafted items
        crafted_query = """
            SELECT item_name, count
            FROM agent_manual_production_statistics
            WHERE agent_id = ? AND source = 'crafted'
        """
        crafted_result = self._conn.execute(crafted_query, [agent_id]).fetchall()
        crafted = {row[0]: row[1] for row in crafted_result}

        # Query mined items
        mined_query = """
            SELECT item_name, count
            FROM agent_manual_production_statistics
            WHERE agent_id = ? AND source = 'mined'
        """
        mined_result = self._conn.execute(mined_query, [agent_id]).fetchall()
        mined = {row[0]: row[1] for row in mined_result}

        # Get tick from latest snapshot metadata (or use 0)
        tick = 0
        try:
            tick_result = self._conn.execute(
                "SELECT MAX(tick) FROM snapshot_metadata"
            ).fetchone()
            if tick_result and tick_result[0]:
                tick = tick_result[0]
        except Exception:
            pass

        return ManualStats(
            crafted=crafted,
            mined=mined,
            agent_id=agent_id,
            tick=tick,
        )
