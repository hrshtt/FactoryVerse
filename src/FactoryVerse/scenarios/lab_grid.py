"""Lab Grid scenario adapter.

Provides type-safe Python interface to the lab-grid scenario's remote interface.
The lab-grid scenario creates an 8x8 grid of isolated play areas for parallel
multi-agent evaluation.

Usage:
    >>> from FactoryVerse.scenarios.lab_grid import LabGridAdapter
    >>> adapter = LabGridAdapter(rcon_client)
    >>> if adapter.is_available():
    ...     config = adapter.config
    ...     result = adapter.create_agent_in_cell(cell_index=5)
    ...     print(f"Agent {result.agent_id} in cell {result.cell_index}")
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from FactoryVerse.scenarios.base import (
    ScenarioAdapter,
    ScenarioError,
    Position,
    BoundingBox,
    RCONClientProtocol,
)


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

    def __init__(self, rcon: RCONClientProtocol):
        super().__init__(rcon)
        self._config: Optional[GridConfig] = None

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

    def __repr__(self) -> str:
        if self._config:
            return f"LabGridAdapter({self._config.grid_size}x{self._config.grid_size}, {self._config.total_cells} cells)"
        return "LabGridAdapter(not loaded)"
