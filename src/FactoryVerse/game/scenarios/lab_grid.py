"""Lab Grid scenario adapter with snapshot orchestration.

Provides type-safe Python interface to the lab-grid scenario's remote interface.
The lab-grid scenario creates an 8x8 grid of isolated play areas for parallel
multi-agent evaluation.

This adapter handles:
- Cell allocation/release with snapshot coordination
- Waiting for cell snapshots to complete
- Loading cell-specific data into DuckDB
- Agent lifecycle within cells

Usage:
    >>> adapter = LabGridAdapter(rcon_client, snapshot_loader=loader)
    >>> result = await adapter.allocate_cell(cell_index=5, starting_inventory={...})
    >>> # Cell is now ready with snapshot data loaded
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from FactoryVerse.game.scenarios.base import (
    ScenarioAdapter,
    ScenarioError,
    Position,
    BoundingBox,
    RCONClientProtocol,
)
from FactoryVerse.game.agent.adapter import AgentInterface
from FactoryVerse.game.agent.admin_adapter import AdminInterface
from FactoryVerse.game.snapshot import MapSnapshotInterface

if TYPE_CHECKING:
    import duckdb

logger = logging.getLogger(__name__)


@dataclass
class GridConfig:
    """Configuration of the lab-grid layout."""

    chunk_size: int  # Factorio chunk size (32 tiles)
    play_area_chunks: int  # Chunks per play area (4)
    gap_chunks: int  # Chunks for gap between cells (1)
    cell_chunks: int  # Total chunks per cell (5)
    play_area_size: int  # Tiles per play area (128)
    gap_size: int  # Tiles for gap (32)
    cell_size: int  # Tiles per cell (160)
    grid_size: int  # Grid dimension (8 = 8x8)
    total_cells: int  # Total cells (64)
    map_size: int  # Total map size in tiles (1280)

    @classmethod
    def from_dict(cls, d: dict) -> "GridConfig":
        return cls(
            chunk_size=d["chunk_size"],
            play_area_chunks=d["play_area_chunks"],
            gap_chunks=d["gap_chunks"],
            cell_chunks=d["cell_chunks"],
            play_area_size=d["play_area_size"],
            gap_size=d["gap_size"],
            cell_size=d["cell_size"],
            grid_size=d["grid_size"],
            total_cells=d["total_cells"],
            map_size=d["map_size"],
        )


@dataclass
class AgentInfo:
    """Information about an agent in a cell."""

    force: str
    position: Position

    @classmethod
    def from_dict(cls, d: dict) -> "AgentInfo":
        return cls(
            force=d["force"],
            position=Position.from_dict(d["position"])
        )


@dataclass
class CellStatus:
    """Status of a single cell in the grid."""

    cell_index: int
    bounds: BoundingBox
    spawn_position: Position
    entity_count: int
    force_exists: bool
    force_name: str
    has_agent: bool
    agent_info: Optional[AgentInfo] = None

    @classmethod
    def from_dict(cls, d: dict) -> "CellStatus":
        return cls(
            cell_index=d["cell_index"],
            bounds=BoundingBox.from_dict(d["bounds"]),
            spawn_position=Position.from_dict(d["spawn_position"]),
            entity_count=d["entity_count"],
            force_exists=d["force_exists"],
            force_name=d["force_name"],
            has_agent=d["has_agent"],
            agent_info=AgentInfo.from_dict(d["agent_info"]) if d.get("agent_info") else None,
        )


@dataclass
class AgentCreationResult:
    """Result of creating an agent in a cell."""

    success: bool
    agent_id: Optional[int] = None
    cell_index: Optional[int] = None
    spawn_position: Optional[Position] = None
    force_name: Optional[str] = None
    error: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "AgentCreationResult":
        return cls(
            success=d["success"],
            agent_id=d.get("agent_id"),
            cell_index=d.get("cell_index"),
            spawn_position=Position.from_dict(d["spawn_position"]) if d.get("spawn_position") else None,
            force_name=d.get("force_name"),
            error=d.get("error"),
        )


@dataclass
class ResetResult:
    """Result of resetting a cell or cells."""

    success: bool
    cell_index: Optional[int] = None
    cells_reset: Optional[int] = None

    @classmethod
    def from_dict(cls, d: dict) -> "ResetResult":
        return cls(
            success=d["success"],
            cell_index=d.get("cell_index"),
            cells_reset=d.get("cells_reset"),
        )


@dataclass
class CellSnapshotStatus:
    """Snapshot status for a cell."""

    complete: bool
    chunks_total: int
    chunks_snapshotted: int
    chunks_pending: int
    elapsed_seconds: float = 0.0


@dataclass
class CellAllocationResult:
    """Result of allocating a cell with snapshot coordination."""

    success: bool
    cell_index: Optional[int] = None
    agent_id: Optional[int] = None
    spawn_position: Optional[Position] = None
    force_name: Optional[str] = None
    snapshot_complete: bool = False
    chunks_snapshotted: int = 0
    error: Optional[str] = None


class LabGridAdapter(ScenarioAdapter):
    """Type-safe Python adapter for the lab-grid scenario.

    The lab-grid scenario provides:
    - 8x8 grid of isolated 128x128 tile play areas
    - Force-per-cell for production statistics isolation
    - Build restriction enforcement within cell bounds
    - Cell reset capability
    - On-demand charting (doesn't overwhelm fv_snapshot)

    Example:
        >>> adapter = LabGridAdapter(rcon)
        >>> if adapter.is_available():
        ...     # Get grid configuration
        ...     print(f"Grid: {adapter.config.grid_size}x{adapter.config.grid_size}")
        ...
        ...     # Create an agent in a specific cell
        ...     result = adapter.create_agent_in_cell(cell_index=5)
        ...     if result.success:
        ...         print(f"Agent {result.agent_id} in cell {result.cell_index}")
        ...
        ...     # Check cell status
        ...     status = adapter.get_cell_status(5)
        ...     print(f"Entities: {status.entity_count}, Agent: {status.has_agent}")
        ...
        ...     # Reset cell for next evaluation
        ...     adapter.reset_cell(5, preserve_agent=False)
    """

    scenario_name = "lab-grid"
    interface_name = "lab_grid"

    # Each cell is 4x4 chunks = 16 chunks
    CHUNKS_PER_CELL = 16

    def __init__(
        self,
        rcon: RCONClientProtocol,
        database: Optional["duckdb.DuckDBPyConnection"] = None,
        snapshot_dir: Optional[Path] = None,
    ):
        super().__init__(rcon)
        self._config: Optional[GridConfig] = None
        self._database = database
        self._snapshot_dir = snapshot_dir

        # Remote interface adapters
        self._agent_api = AgentInterface(rcon)
        self._admin_api = AdminInterface(rcon)
        self._map_api = MapSnapshotInterface(rcon)

    def is_available(self) -> bool:
        """Check if lab_grid remote interface is available."""
        return self._check_interface_exists()

    # =========================================================================
    # Grid Configuration
    # =========================================================================

    @property
    def config(self) -> GridConfig:
        """Get grid configuration (cached after first call)."""
        if self._config is None:
            result = self._remote_call("get_config")
            self._config = GridConfig.from_dict(result)
        return self._config

    def get_cell_bounds(self, cell_index: int) -> BoundingBox:
        """Get the play area bounds for a cell.

        Args:
            cell_index: Cell index (0-63)

        Returns:
            BoundingBox of the cell's play area
        """
        result = self._remote_call("get_cell_bounds", cell_index)
        return BoundingBox.from_dict(result)

    def get_spawn_position(self, cell_index: int) -> Position:
        """Get the spawn position (center) of a cell.

        Args:
            cell_index: Cell index (0-63)

        Returns:
            Position at center of cell's play area
        """
        result = self._remote_call("get_spawn_position", cell_index)
        return Position.from_dict(result)

    # =========================================================================
    # Cell Status
    # =========================================================================

    def get_cell_status(self, cell_index: int) -> CellStatus:
        """Get detailed status of a cell.

        Args:
            cell_index: Cell index (0-63)

        Returns:
            CellStatus with bounds, entity count, agent info, etc.
        """
        result = self._remote_call("get_cell_status", cell_index)
        return CellStatus.from_dict(result)

    def get_all_cell_status(self) -> Dict[int, CellStatus]:
        """Get status of all 64 cells.

        Returns:
            Dict mapping cell_index to CellStatus
        """
        result = self._remote_call("get_all_cell_status")
        return {int(k): CellStatus.from_dict(v) for k, v in result.items()}

    def get_occupied_cells(self) -> List[int]:
        """Get list of cell indices that have agents.

        Returns:
            List of cell indices with agents
        """
        all_status = self.get_all_cell_status()
        return [idx for idx, status in all_status.items() if status.has_agent]

    def get_empty_cells(self) -> List[int]:
        """Get list of cell indices without agents.

        Returns:
            List of empty cell indices
        """
        all_status = self.get_all_cell_status()
        return [idx for idx, status in all_status.items() if not status.has_agent]

    # =========================================================================
    # Agent Operations
    # =========================================================================

    def create_agent_in_cell(
        self,
        cell_index: Optional[int] = None,
        starting_inventory: Optional[Dict[str, int]] = None,
    ) -> AgentCreationResult:
        """Create an agent in a cell.

        Integrates with fv_embodied_agent to create a new agent character
        in the specified cell (or next available cell). The agent is assigned
        to the cell's force for production statistics isolation.

        Args:
            cell_index: Specific cell to use (0-63), or None to auto-assign
            starting_inventory: Optional dict of item_name -> count

        Returns:
            AgentCreationResult with agent_id, cell_index, spawn_position, force_name
        """
        args = {}
        if cell_index is not None:
            args["cell_index"] = cell_index
        if starting_inventory:
            args["starting_inventory"] = starting_inventory

        result = self._remote_call("create_agent_in_cell", args)
        return AgentCreationResult.from_dict(result)

    def get_agent_cell(self, agent_id: int) -> Optional[int]:
        """Get the cell index assigned to an agent.

        Args:
            agent_id: The agent's ID

        Returns:
            Cell index (0-63) or None if not assigned
        """
        result = self._remote_call("get_agent_cell", agent_id)
        return result

    def assign_agent_to_cell(self, agent_id: int, cell_index: int) -> bool:
        """Manually assign an existing agent to a cell.

        Args:
            agent_id: The agent's ID
            cell_index: Cell to assign (0-63)

        Returns:
            True if successful, False if cell occupied
        """
        return self._remote_call("assign_agent_to_cell", agent_id, cell_index)

    def unassign_agent(self, agent_id: int) -> None:
        """Remove an agent's cell assignment.

        Args:
            agent_id: The agent's ID
        """
        self._remote_call("unassign_agent", agent_id)

    def find_empty_cell(self) -> Optional[int]:
        """Find the first empty cell (no agent assigned).

        Returns:
            Cell index (0-63) or None if all cells are occupied
        """
        return self._remote_call("find_empty_cell")

    def teleport_agent_to_cell(self, agent_id: int) -> Position:
        """Teleport an agent to their assigned cell's spawn position.

        Args:
            agent_id: The agent's ID

        Returns:
            Position the agent was teleported to

        Raises:
            ScenarioError: If agent not assigned to a cell
        """
        result = self._remote_call("teleport_agent_to_cell", agent_id)
        if not result.get("success"):
            raise ScenarioError(result.get("error", "Failed to teleport agent"))
        return Position.from_dict(result["position"])

    # =========================================================================
    # Cell Reset
    # =========================================================================

    def reset_cell(self, cell_index: int, preserve_agent: bool = True) -> ResetResult:
        """Reset a cell to its initial state.

        Clears all entities (except agent if preserve_agent=True),
        regenerates tiles, and respawns resources.

        Args:
            cell_index: Cell to reset (0-63)
            preserve_agent: Whether to keep the agent character

        Returns:
            ResetResult indicating success
        """
        result = self._remote_call("reset_cell", cell_index, preserve_agent)
        return ResetResult.from_dict(result)

    def reset_all_cells(self, preserve_agents: bool = True) -> ResetResult:
        """Reset all 64 cells to initial state.

        Args:
            preserve_agents: Whether to keep agent characters

        Returns:
            ResetResult with cells_reset count
        """
        result = self._remote_call("reset_all_cells", preserve_agents)
        return ResetResult.from_dict(result)

    # =========================================================================
    # Force Management
    # =========================================================================

    def get_cell_force(self, cell_index: int) -> str:
        """Get the force name for a cell.

        Each cell has its own force (e.g., "cell_0", "cell_5") for
        production statistics isolation.

        Args:
            cell_index: Cell index (0-63)

        Returns:
            Force name (e.g., "cell_5")
        """
        return self._remote_call("get_cell_force", cell_index)

    # =========================================================================
    # Position Utilities
    # =========================================================================

    def is_in_play_area(self, position: Position, cell_index: int) -> bool:
        """Check if a position is within a cell's play area.

        Args:
            position: Position to check
            cell_index: Cell to check against

        Returns:
            True if position is within the cell's play area
        """
        pos_dict = {"x": position.x, "y": position.y}
        return self._remote_call("is_in_play_area", pos_dict, cell_index)

    def get_cell_at_position(self, position: Position) -> Optional[int]:
        """Get the cell index containing a position.

        Args:
            position: Position to look up

        Returns:
            Cell index (0-63) or None if outside grid
        """
        pos_dict = {"x": position.x, "y": position.y}
        return self._remote_call("get_cell_at_position", pos_dict)

    # =========================================================================
    # Convenience Methods
    # =========================================================================

    def cell_index_to_grid(self, cell_index: int) -> tuple[int, int]:
        """Convert cell index to grid coordinates.

        Args:
            cell_index: Cell index (0-63)

        Returns:
            Tuple of (grid_x, grid_y) where 0 <= x,y < 8
        """
        grid_size = self.config.grid_size
        return (cell_index % grid_size, cell_index // grid_size)

    def grid_to_cell_index(self, grid_x: int, grid_y: int) -> int:
        """Convert grid coordinates to cell index.

        Args:
            grid_x: X coordinate (0-7)
            grid_y: Y coordinate (0-7)

        Returns:
            Cell index (0-63)
        """
        return grid_y * self.config.grid_size + grid_x

    # =========================================================================
    # Snapshot Orchestration
    # =========================================================================

    def get_cell_chunk_coordinates(self, cell_index: int) -> List[Tuple[int, int]]:
        """Get chunk coordinates for a cell (4x4 = 16 chunks).

        Args:
            cell_index: Cell index (0-63)

        Returns:
            List of (chunk_x, chunk_y) tuples for the 16 chunks in this cell
        """
        cfg = self.config
        grid_x, grid_y = self.cell_index_to_grid(cell_index)

        # Cell origin in tiles
        cell_origin_x = grid_x * cfg.cell_size
        cell_origin_y = grid_y * cfg.cell_size

        # Convert to chunk coordinates (32 tiles per chunk)
        base_chunk_x = cell_origin_x // cfg.chunk_size
        base_chunk_y = cell_origin_y // cfg.chunk_size

        # 4x4 chunks per cell
        chunks = []
        for dy in range(cfg.play_area_chunks):
            for dx in range(cfg.play_area_chunks):
                chunks.append((base_chunk_x + dx, base_chunk_y + dy))

        return chunks

    def get_snapshot_status(self) -> Dict[str, Any]:
        """Get snapshot system status via RCON.

        Returns:
            Dict with system_phase, pending_chunks, completed_chunks, etc.
        """
        status = self._map_api.get_snapshot_status()
        return {
            "system_phase": status.system_phase,
            "orchestration_mode": status.orchestration_mode,
            "total_chunks_tracked": status.total_chunks_tracked,
            "chunks_snapshotted": status.chunks_snapshotted,
            "pending_chunks": status.chunks_pending,
            "chunks_processing": status.chunks_processing,
            "last_snapshot_tick": status.last_snapshot_tick,
            "game_tick": status.game_tick,
        }

    async def wait_for_cell_snapshot(
        self,
        cell_index: int,
        timeout: float = 60.0,
        poll_interval: float = 0.5,
    ) -> CellSnapshotStatus:
        """Wait for a cell's chunks to be fully snapshotted.

        The lab-grid scenario triggers snapshot_area() when resetting a cell.
        This method polls the snapshot system to check when those chunks complete.

        Args:
            cell_index: Cell to wait for
            timeout: Max seconds to wait
            poll_interval: Seconds between polls

        Returns:
            CellSnapshotStatus with completion info
        """
        start_time = time.time()
        cell_chunks = set(self.get_cell_chunk_coordinates(cell_index))
        chunks_total = len(cell_chunks)

        # CRITICAL: Give Lua time to queue chunks after reset_cell returns
        # RCON returns immediately but chunk processing happens over subsequent ticks
        await asyncio.sleep(0.5)

        # Track if we've seen any chunks being processed
        seen_processing = False

        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                return CellSnapshotStatus(
                    complete=False,
                    chunks_total=chunks_total,
                    chunks_snapshotted=0,
                    chunks_pending=chunks_total,
                    elapsed_seconds=elapsed,
                )

            # Check snapshot status
            status = self.get_snapshot_status()
            system_phase = status.get("system_phase", "")
            pending = status.get("pending_chunks", 0)
            snapshotted = status.get("chunks_snapshotted", 0)

            # Track if we've seen processing activity
            if pending > 0 or system_phase == "INITIAL_SNAPSHOTTING":
                seen_processing = True

            # In SELECTIVE mode, chunks are done when:
            # 1. We've seen processing activity (chunks were queued)
            # 2. AND pending == 0 (all queued chunks processed)
            # 3. OR system is in MAINTENANCE with no pending
            if seen_processing and pending == 0:
                # Give a brief moment for file writes to complete
                await asyncio.sleep(0.3)
                return CellSnapshotStatus(
                    complete=True,
                    chunks_total=chunks_total,
                    chunks_snapshotted=snapshotted,
                    chunks_pending=0,
                    elapsed_seconds=time.time() - start_time,
                )

            # If we haven't seen processing and it's been a while, check files directly
            if not seen_processing and elapsed > 2.0:
                # Fallback: check if snapshot files exist for this cell
                logger.warning(
                    f"LabGrid: No snapshot activity detected for cell {cell_index} after {elapsed:.1f}s, "
                    "proceeding anyway"
                )
                return CellSnapshotStatus(
                    complete=True,  # Assume complete, let loader handle missing files
                    chunks_total=chunks_total,
                    chunks_snapshotted=snapshotted,
                    chunks_pending=0,
                    elapsed_seconds=elapsed,
                )

            await asyncio.sleep(poll_interval)

    async def allocate_cell(
        self,
        cell_index: Optional[int] = None,
        agent_id: int = 1,
        starting_inventory: Optional[Dict[str, int]] = None,
        wait_for_snapshot: bool = True,
        snapshot_timeout: float = 60.0,
    ) -> CellAllocationResult:
        """Allocate a cell with full snapshot coordination.

        Orchestrates:
        1. Find/validate cell
        2. Reset cell (triggers re_snapshot_area in Lua)
        3. Assign agent to cell
        4. Teleport agent to cell center
        5. Wait for snapshot completion (if requested)
        6. Set starting inventory

        Args:
            cell_index: Specific cell (0-63), or None to auto-allocate
            agent_id: Numeric agent ID to assign
            starting_inventory: Items to give agent
            wait_for_snapshot: Whether to wait for snapshot completion
            snapshot_timeout: Max time to wait for snapshot

        Returns:
            CellAllocationResult with cell info and snapshot status
        """
        # 1. Find cell
        if cell_index is None:
            cell_index = self.find_empty_cell()
            if cell_index is None:
                return CellAllocationResult(
                    success=False,
                    error="No empty cells available",
                )

        # Validate cell index
        if cell_index < 0 or cell_index >= self.config.total_cells:
            return CellAllocationResult(
                success=False,
                error=f"Invalid cell index: {cell_index}",
            )

        logger.info(f"LabGrid: Allocating cell {cell_index} for agent {agent_id}")

        # 2. Reset cell (spawns resources, triggers re_snapshot_area)
        reset_result = self.reset_cell(cell_index, preserve_agent=True)
        if not reset_result.success:
            return CellAllocationResult(
                success=False,
                cell_index=cell_index,
                error="Failed to reset cell",
            )

        # 3. Check if agent entity is valid and has correct force, recreate if needed
        # Get the cell's force name (e.g., "cell_0", "cell_5")
        cell_force = self.get_cell_force(cell_index)

        agents = self._list_game_agents()
        existing = next((a for a in agents if a.get("id") == agent_id), None)

        if existing:
            entity_valid = existing.get("entity_valid", True)
            existing_force = existing.get("force", "")

            # Recreate if entity invalid OR if force doesn't match the cell's force
            needs_recreate = not entity_valid or existing_force != cell_force
            if needs_recreate:
                reasons = []
                if not entity_valid:
                    reasons.append("entity invalid")
                if existing_force != cell_force:
                    reasons.append(f"force mismatch ({existing_force} != {cell_force})")
                logger.info(f"LabGrid: Agent {agent_id} needs recreation: {', '.join(reasons)}")
                self._destroy_agent(agent_id)
                self._create_agent(agent_id, force=cell_force)
        else:
            logger.info(f"LabGrid: Creating agent {agent_id} with force {cell_force}")
            self._create_agent(agent_id, force=cell_force)

        # 4. Assign agent to cell
        assigned = self.assign_agent_to_cell(agent_id, cell_index)
        if not assigned:
            return CellAllocationResult(
                success=False,
                cell_index=cell_index,
                agent_id=agent_id,
                error=f"Failed to assign agent {agent_id} to cell {cell_index}",
            )

        # 5. Teleport agent to cell center
        try:
            position = self.teleport_agent_to_cell(agent_id)
        except ScenarioError as e:
            return CellAllocationResult(
                success=False,
                cell_index=cell_index,
                agent_id=agent_id,
                error=str(e),
            )

        # 6. Wait for snapshot if requested
        snapshot_status = CellSnapshotStatus(
            complete=False,
            chunks_total=self.CHUNKS_PER_CELL,
            chunks_snapshotted=0,
            chunks_pending=self.CHUNKS_PER_CELL,
        )
        if wait_for_snapshot:
            logger.info(f"LabGrid: Waiting for cell {cell_index} snapshot...")
            snapshot_status = await self.wait_for_cell_snapshot(
                cell_index, timeout=snapshot_timeout
            )
            if snapshot_status.complete:
                logger.info(
                    f"LabGrid: Cell {cell_index} snapshot complete "
                    f"({snapshot_status.elapsed_seconds:.1f}s)"
                )

        # 7. Set starting inventory
        if starting_inventory:
            self._set_agent_inventory(agent_id, starting_inventory)

        force_name = self.get_cell_force(cell_index)

        return CellAllocationResult(
            success=True,
            cell_index=cell_index,
            agent_id=agent_id,
            spawn_position=position,
            force_name=force_name,
            snapshot_complete=snapshot_status.complete,
            chunks_snapshotted=snapshot_status.chunks_snapshotted,
        )

    async def release_cell(
        self,
        cell_index: int,
        reset: bool = True,
    ) -> None:
        """Release a cell back to the pool.

        Args:
            cell_index: Cell to release
            reset: Whether to reset cell (clears entities, respawns resources)
        """
        if reset:
            self.reset_cell(cell_index, preserve_agent=False)
            logger.debug(f"LabGrid: Released and reset cell {cell_index}")
        else:
            logger.debug(f"LabGrid: Released cell {cell_index} (no reset)")

    def get_cell_query_bounds(self, cell_index: int) -> Dict[str, float]:
        """Get bounding box values for SQL WHERE clauses.

        Args:
            cell_index: Cell index (0-63)

        Returns:
            Dict with min_x, max_x, min_y, max_y for SQL filtering
        """
        bounds = self.get_cell_bounds(cell_index)
        return {
            "min_x": bounds.left_top.x,
            "max_x": bounds.right_bottom.x,
            "min_y": bounds.left_top.y,
            "max_y": bounds.right_bottom.y,
        }

    def get_verification_source(self, agent_id: Optional[int] = None):
        """Get a verification source for reading agent statistics.

        Returns an AgentSnapshotSource that reads from the statistics files
        written by fv_snapshot:
        - production-statistics.jsonl (force-level, written on change)
        - crafting-statistics.jsonl (manual crafting, event-driven)
        - mining-statistics.jsonl (manual mining, event-driven)

        For lab-grid, each agent is on a cell-specific force, so production
        statistics are isolated per cell.

        Args:
            agent_id: Optional agent ID (not used, but available for filtering)

        Returns:
            AgentSnapshotSource configured with snapshot_dir

        Raises:
            ValueError: If snapshot_dir was not provided to constructor
        """
        from FactoryVerse.game.tasks.sources import AgentSnapshotSource

        if self._snapshot_dir is None:
            raise ValueError(
                "Cannot create verification source: snapshot_dir not provided. "
                "Pass snapshot_dir to LabGridAdapter constructor."
            )

        return AgentSnapshotSource(self._snapshot_dir)

    # =========================================================================
    # Private Helpers for Agent Management
    # =========================================================================

    def _list_game_agents(self) -> List[Dict[str, Any]]:
        """List agents via RCON."""
        agents = self._agent_api.list_agents()
        # Convert to dict format for backward compatibility
        return [
            {
                "id": a.id,
                "interface_name": a.interface_name,
                "force": a.force,
                "udp_port": a.udp_port,
                "entity_valid": a.entity_valid,
                "position": a.position,
            }
            for a in agents
        ]

    def _create_agent(
        self,
        agent_id: int,
        udp_port: int = 34202,
        force: Optional[str] = None,
    ) -> None:
        """Create an agent via RCON.

        Args:
            agent_id: Numeric agent ID (not used by Lua, ID is auto-assigned)
            udp_port: UDP port for agent notifications
            force: Force name for the agent. If None, uses "player".
                   For lab-grid cells, use the cell's force (e.g., "cell_0").
        """
        self._agent_api.create_agent(
            udp_port=udp_port,
            set_unique_forces=False,
            force=force,
        )

    def _destroy_agent(self, agent_id: int) -> None:
        """Destroy an agent via RCON."""
        self._agent_api.destroy_agents([agent_id])

    def _set_agent_inventory(
        self, agent_id: int, inventory: Dict[str, int]
    ) -> None:
        """Set agent inventory via RCON using admin API.

        Uses the add_items and clear_inventory admin API methods which
        properly access the agent's character inventory by agent_id.
        """
        # First clear existing inventory
        self._admin_api.clear_inventory(agent_id)

        # Then add new items
        if inventory:
            self._admin_api.add_items(agent_id, inventory)

    def __repr__(self) -> str:
        if self._config:
            return f"LabGridAdapter({self._config.grid_size}x{self._config.grid_size}, {self._config.total_cells} cells)"
        return "LabGridAdapter(not loaded)"
