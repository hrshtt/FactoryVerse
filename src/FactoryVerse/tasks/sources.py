"""Verification data sources.

This module provides pluggable sources for production statistics:
- RCONSource: Query force-level stats via RCON, manual stats from snapshot files
- AgentSnapshotSource: Read from agent-snapshots JSONL files (offline/batch evaluation)
- DuckDBSource: Query from loaded DuckDB database (if available)

All sources implement the VerificationSource protocol.

File Structure (written by fv_snapshot mod):
    factoryverse/agent-snapshots/{agent_id}/
        production-statistics.jsonl  - Force-level production (polled every 300 ticks)
        crafting-statistics.jsonl    - Hand-crafted items (event-driven)
        mining-statistics.jsonl      - Hand-mined items (event-driven)
"""

import json
import logging
from pathlib import Path
from typing import Protocol, TypedDict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from FactoryVerse.infra.rcon_helper import RCONHelper
    import duckdb

logger = logging.getLogger(__name__)


class ProductionStats(TypedDict):
    """Force-level production statistics."""

    output: dict[str, int]  # Items produced: {item_name: count}
    input: dict[str, int]  # Items consumed: {item_name: count}
    tick: int  # Game tick when these stats were recorded


class ManualStats(TypedDict):
    """Manual production statistics for an agent."""

    crafted: dict[str, int]  # Hand-crafted items: {item_name: count}
    mined: dict[str, int]  # Hand-mined items: {item_name: count}
    agent_id: int
    tick: int


class VerificationSource(Protocol):
    """Protocol for any source of production data.

    Implementations can query data from different sources:
    - RCON + Snapshot files: Live game with snapshot files
    - AgentSnapshot: Offline snapshot files
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


def _get_agent_snapshot_dir(script_output_dir: Path, agent_id: int) -> Path:
    """Get the agent snapshot directory path.

    Args:
        script_output_dir: Path to Factorio script-output directory
        agent_id: The agent ID

    Returns:
        Path to agent-snapshots/{agent_id}/ directory
    """
    return script_output_dir / "factoryverse" / "agent-snapshots" / str(agent_id)


def _load_latest_production_stats(agent_dir: Path) -> tuple[dict[str, int], dict[str, int], int]:
    """Load the latest production statistics from JSONL file.

    Args:
        agent_dir: Path to agent's snapshot directory

    Returns:
        Tuple of (output_items, input_items, tick)
    """
    stats_file = agent_dir / "production-statistics.jsonl"
    if not stats_file.exists():
        return {}, {}, 0

    # Read the last line (most recent snapshot)
    last_line = None
    with open(stats_file, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                last_line = line

    if last_line is None:
        return {}, {}, 0

    data = json.loads(last_line)
    return (
        data.get("output", {}),
        data.get("input", {}),
        data.get("tick", 0),
    )


def _aggregate_crafting_stats(agent_dir: Path) -> tuple[dict[str, int], int]:
    """Aggregate crafting statistics from JSONL file.

    Each line in crafting-statistics.jsonl is an event:
    {"tick": N, "agent_id": M, "recipe": "...", "count_crafted": K, "products": {...}}

    We aggregate the products dict across all events.

    Args:
        agent_dir: Path to agent's snapshot directory

    Returns:
        Tuple of (crafted_items, latest_tick)
    """
    stats_file = agent_dir / "crafting-statistics.jsonl"
    if not stats_file.exists():
        return {}, 0

    crafted: dict[str, int] = {}
    latest_tick = 0

    with open(stats_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                tick = data.get("tick", 0)
                if tick > latest_tick:
                    latest_tick = tick
                # Aggregate products from each crafting event
                products = data.get("products", {})
                for item_name, count in products.items():
                    crafted[item_name] = crafted.get(item_name, 0) + count
            except json.JSONDecodeError:
                continue

    return crafted, latest_tick


def _aggregate_mining_stats(agent_dir: Path) -> tuple[dict[str, int], int]:
    """Aggregate mining statistics from JSONL file.

    Each line in mining-statistics.jsonl is an event:
    {"tick": N, "agent_id": M, "entity_name": "...", "products": {...}, ...}

    We aggregate the products dict across all events.

    Args:
        agent_dir: Path to agent's snapshot directory

    Returns:
        Tuple of (mined_items, latest_tick)
    """
    stats_file = agent_dir / "mining-statistics.jsonl"
    if not stats_file.exists():
        return {}, 0

    mined: dict[str, int] = {}
    latest_tick = 0

    with open(stats_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                tick = data.get("tick", 0)
                if tick > latest_tick:
                    latest_tick = tick
                # Aggregate products from each mining event
                products = data.get("products", {})
                for item_name, count in products.items():
                    mined[item_name] = mined.get(item_name, 0) + count
            except json.JSONDecodeError:
                continue

    return mined, latest_tick


class RCONSource:
    """Query production stats via RCON and manual stats from snapshot files.

    This source queries force-level production directly via RCON, and reads
    manual production (crafting/mining) from snapshot JSONL files.

    Useful for:
    - Real-time verification during gameplay
    - Testing verification logic with live game

    Requires an active RCON connection and access to script-output directory.
    """

    def __init__(self, rcon_helper: "RCONHelper", script_output_dir: Optional[Path] = None):
        """Initialize with an RCONHelper and optional script output directory.

        Args:
            rcon_helper: Configured RCONHelper instance
            script_output_dir: Path to Factorio script-output directory.
                             If None, manual stats will return empty.
        """
        self._rcon = rcon_helper
        self._script_output_dir = script_output_dir

    async def get_force_production(self, agent_id: int) -> ProductionStats:
        """Get force-level production statistics via RCON.

        Args:
            agent_id: The agent ID to get stats for

        Returns:
            ProductionStats with output, input item counts, and tick
        """
        # Use "agent_N" format for the remote interface category
        category = f"agent_{agent_id}"
        result = self._rcon.run(
            category=category,
            method="get_production_statistics",
            args={},
            safe=True,
            verbose=False,
        )

        # Handle safe wrapper response
        if "result" in result:
            result = result["result"]

        # Get current game tick for staleness tracking
        tick = self._rcon.run(
            category="map",
            method="get_game_tick",
            args={},
            safe=True,
            verbose=False,
        )
        if isinstance(tick, dict) and "result" in tick:
            tick = tick["result"]

        return ProductionStats(
            output=result.get("output", {}),
            input=result.get("input", {}),
            tick=tick if isinstance(tick, int) else 0,
        )

    async def get_manual_production(self, agent_id: int) -> ManualStats:
        """Get manual production statistics from snapshot files.

        Reads from agent-snapshots JSONL files written by fv_snapshot mod.

        Args:
            agent_id: The agent ID to get stats for

        Returns:
            ManualStats with crafted and mined item counts
        """
        if self._script_output_dir is None:
            return ManualStats(
                crafted={},
                mined={},
                agent_id=agent_id,
                tick=0,
            )

        agent_dir = _get_agent_snapshot_dir(self._script_output_dir, agent_id)

        crafted, crafted_tick = _aggregate_crafting_stats(agent_dir)
        mined, mined_tick = _aggregate_mining_stats(agent_dir)

        return ManualStats(
            crafted=crafted,
            mined=mined,
            agent_id=agent_id,
            tick=max(crafted_tick, mined_tick),
        )


class AgentSnapshotSource:
    """Read from agent-snapshots JSONL files.

    This source reads from snapshot files written by fv_snapshot mod:
    - production-statistics.jsonl: Force-level production (polled every 300 ticks)
    - crafting-statistics.jsonl: Hand-crafted items (event-driven)
    - mining-statistics.jsonl: Hand-mined items (event-driven)

    Useful for:
    - Offline/batch evaluation
    - Replaying and analyzing past runs
    - CI/CD testing without running Factorio
    """

    def __init__(self, script_output_dir: Path):
        """Initialize with path to Factorio script-output directory.

        Args:
            script_output_dir: Path to Factorio's script-output directory
                             (contains factoryverse/agent-snapshots/)

        Raises:
            ValueError: If path looks malformed (contains duplicate factoryverse segments)
        """
        self._script_output_dir = Path(script_output_dir)

        # Guard against common misconfiguration: passing get_snapshot_dir() instead of get_script_output_dir()
        # get_snapshot_dir returns script-output/factoryverse/snapshots, but we need just script-output
        path_str = str(self._script_output_dir)
        if "factoryverse/snapshots" in path_str or "factoryverse\\snapshots" in path_str:
            raise ValueError(
                f"AgentSnapshotSource received path containing 'factoryverse/snapshots': {path_str}\n"
                f"This suggests get_snapshot_dir() was used instead of get_script_output_dir().\n"
                f"Expected: script-output directory (e.g., ~/Library/.../factorio/script-output)\n"
                f"Received: {script_output_dir}"
            )

        # Validate the expected directory structure exists
        agent_snapshots_dir = self._script_output_dir / "factoryverse" / "agent-snapshots"
        if not agent_snapshots_dir.exists():
            logger.warning(
                f"AgentSnapshotSource: agent-snapshots directory does not exist: {agent_snapshots_dir}\n"
                f"Verification will return empty data until fv_snapshot writes statistics."
            )

    async def get_force_production(self, agent_id: int) -> ProductionStats:
        """Get force-level production statistics from snapshot.

        Args:
            agent_id: The agent ID to get stats for

        Returns:
            ProductionStats with output, input item counts, and tick
        """
        agent_dir = _get_agent_snapshot_dir(self._script_output_dir, agent_id)
        stats_file = agent_dir / "production-statistics.jsonl"

        # Warn if stats file doesn't exist - helps catch path misconfiguration early
        if not stats_file.exists():
            logger.warning(
                f"AgentSnapshotSource: production-statistics.jsonl not found at {stats_file}\n"
                f"Returning empty stats. Check if fv_snapshot mod is writing to expected location."
            )

        output, input_items, tick = _load_latest_production_stats(agent_dir)

        # Warn if we got empty data from an existing file (unusual)
        if stats_file.exists() and tick == 0 and not output:
            logger.warning(
                f"AgentSnapshotSource: File exists but returned empty data: {stats_file}\n"
                f"File may be empty or malformed."
            )

        return ProductionStats(
            output=output,
            input=input_items,
            tick=tick,
        )

    async def get_manual_production(self, agent_id: int) -> ManualStats:
        """Get manual production statistics from snapshot.

        Aggregates crafting and mining events from JSONL files.

        Args:
            agent_id: The agent ID to get stats for

        Returns:
            ManualStats with crafted and mined item counts
        """
        agent_dir = _get_agent_snapshot_dir(self._script_output_dir, agent_id)

        crafted, crafted_tick = _aggregate_crafting_stats(agent_dir)
        mined, mined_tick = _aggregate_mining_stats(agent_dir)

        return ManualStats(
            crafted=crafted,
            mined=mined,
            agent_id=agent_id,
            tick=max(crafted_tick, mined_tick),
        )

    def clear_cache(self) -> None:
        """Clear any cached data (no-op for this source, reads fresh each time)."""
        pass


# Keep JSONLSource as alias for backwards compatibility
JSONLSource = AgentSnapshotSource


class DuckDBSource:
    """Query from loaded DuckDB database.

    This source queries the DuckDB database, useful for:
    - SQL-based verification queries
    - Aggregating data across multiple agents
    - Complex filtering and analysis

    Requires a DuckDB connection with loaded snapshot data.

    Expected tables:
    - agent_production_statistics: Latest production stats per agent/item
    - agent_crafting_statistics: Crafting events
    - agent_mining_statistics: Mining events
    """

    def __init__(self, connection: "duckdb.DuckDBPyConnection"):
        """Initialize with a DuckDB connection.

        Args:
            connection: Active DuckDB connection with loaded data
        """
        self._conn = connection

    async def get_force_production(self, agent_id: int) -> ProductionStats:
        """Get force-level production statistics from DuckDB.

        Queries the latest production statistics for the agent.

        Args:
            agent_id: The agent ID to get stats for

        Returns:
            ProductionStats with output, input item counts, and tick
        """
        output: dict[str, int] = {}
        input_items: dict[str, int] = {}
        tick: int = 0

        try:
            # Get latest production snapshot for this agent
            result = self._conn.execute(
                """
                SELECT output, input, tick
                FROM agent_production_statistics
                WHERE agent_id = ?
                ORDER BY tick DESC
                LIMIT 1
                """,
                [agent_id],
            ).fetchone()

            if result:
                output = result[0] if result[0] else {}
                input_items = result[1] if result[1] else {}
                tick = result[2] if result[2] else 0
        except Exception as e:
            logger.warning(f"Failed to query production stats: {e}")

        return ProductionStats(
            output=output,
            input=input_items,
            tick=tick,
        )

    async def get_manual_production(self, agent_id: int) -> ManualStats:
        """Get manual production statistics from DuckDB.

        Aggregates crafting and mining events for the agent.

        Args:
            agent_id: The agent ID to get stats for

        Returns:
            ManualStats with crafted and mined item counts
        """
        crafted: dict[str, int] = {}
        mined: dict[str, int] = {}
        tick = 0

        try:
            # Aggregate crafting products
            crafted_result = self._conn.execute(
                """
                SELECT products, tick
                FROM agent_crafting_statistics
                WHERE agent_id = ?
                """,
                [agent_id],
            ).fetchall()

            for row in crafted_result:
                products = row[0] if row[0] else {}
                for item_name, count in products.items():
                    crafted[item_name] = crafted.get(item_name, 0) + count
                if row[1] and row[1] > tick:
                    tick = row[1]
        except Exception as e:
            logger.warning(f"Failed to query crafting stats: {e}")

        try:
            # Aggregate mining products
            mined_result = self._conn.execute(
                """
                SELECT products, tick
                FROM agent_mining_statistics
                WHERE agent_id = ?
                """,
                [agent_id],
            ).fetchall()

            for row in mined_result:
                products = row[0] if row[0] else {}
                for item_name, count in products.items():
                    mined[item_name] = mined.get(item_name, 0) + count
                if row[1] and row[1] > tick:
                    tick = row[1]
        except Exception as e:
            logger.warning(f"Failed to query mining stats: {e}")

        return ManualStats(
            crafted=crafted,
            mined=mined,
            agent_id=agent_id,
            tick=tick,
        )
