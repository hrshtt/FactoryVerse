"""Map and Snapshot remote interface adapter.

Wraps the fv_snapshot mod's "map" and "snapshot" remote interfaces for
snapshot orchestration and map state management.

Lua API:
- remote.call("map", method, ...)
- remote.call("snapshot", method, ...)

Map interface methods:
- get_snapshot_status: Get current snapshot system status
- snapshot_area: Trigger snapshot for an area
- re_snapshot_area: Force re-snapshot an area
- get_orchestration_mode / set_orchestration_mode
- trigger_initial_snapshot
- get_charted_chunks, get_chunk_lookup
- get_map_area_state, set_map_area_state, clear_map_area

Snapshot interface methods:
- set_udp_port / get_udp_port
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Literal

from FactoryVerse.game.infra.adapters.base import RemoteInterfaceAdapter, RCONClientProtocol

logger = logging.getLogger(__name__)


OrchestrationMode = Literal["AUTO", "DEFERRED", "SELECTIVE"]


@dataclass
class SnapshotStatus:
    """Status of the snapshot system."""

    system_phase: str
    orchestration_mode: str
    total_chunks_tracked: int
    chunks_snapshotted: int
    chunks_pending: int
    chunks_processing: int
    last_snapshot_tick: int
    game_tick: int

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SnapshotStatus":
        return cls(
            system_phase=data.get("system_phase", ""),
            orchestration_mode=data.get("orchestration_mode", ""),
            total_chunks_tracked=data.get("total_chunks_tracked", 0),
            chunks_snapshotted=data.get("chunks_snapshotted", 0),
            chunks_pending=data.get("chunks_pending", 0),
            chunks_processing=data.get("chunks_processing", 0),
            last_snapshot_tick=data.get("last_snapshot_tick", 0),
            game_tick=data.get("game_tick", 0),
        )


@dataclass
class SnapshotAreaResult:
    """Result from snapshot_area call."""

    success: bool
    chunks_queued: int = 0
    error: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SnapshotAreaResult":
        return cls(
            success=data.get("success", False),
            chunks_queued=data.get("chunks_queued", 0),
            error=data.get("error"),
        )


@dataclass
class ChunkInfo:
    """Information about a tracked chunk."""

    x: int
    y: int
    state: str
    entity_count: int = 0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChunkInfo":
        return cls(
            x=data.get("x", 0),
            y=data.get("y", 0),
            state=data.get("state", ""),
            entity_count=data.get("entity_count", 0),
        )


class MapSnapshotInterface(RemoteInterfaceAdapter):
    """Adapter for fv_snapshot "map" and "snapshot" remote interfaces.

    Consolidates snapshot orchestration functionality:
    - Snapshot status monitoring
    - Area-based snapshot triggering
    - Orchestration mode control
    - UDP port configuration

    Usage:
        map_api = MapSnapshotInterface(rcon)

        # Get snapshot status
        status = map_api.get_snapshot_status()

        # Trigger snapshot for an area (e.g., a lab-grid cell)
        result = map_api.snapshot_area(left_top={"x": 0, "y": 0}, right_bottom={"x": 128, "y": 128})

        # Set orchestration mode
        map_api.set_orchestration_mode("SELECTIVE")

        # Configure UDP port
        map_api.set_udp_port(34500)
    """

    interface_name = "map"  # Primary interface

    # =========================================================================
    # Snapshot Status & Monitoring
    # =========================================================================

    def get_snapshot_status(self) -> SnapshotStatus:
        """Get current snapshot system status.

        Returns:
            SnapshotStatus with system_phase, orchestration_mode, chunk counts, etc.
        """
        result = self._call("get_snapshot_status")
        if result:
            return SnapshotStatus.from_dict(result)
        return SnapshotStatus(
            system_phase="unknown",
            orchestration_mode="unknown",
            total_chunks_tracked=0,
            chunks_snapshotted=0,
            chunks_pending=0,
            chunks_processing=0,
            last_snapshot_tick=0,
            game_tick=0,
        )

    def get_system_phase(self) -> str:
        """Get the current system phase.

        Returns:
            Phase string (e.g., "IDLE", "SNAPSHOTTING", "READY")
        """
        result = self._call("get_system_phase")
        return result if isinstance(result, str) else "unknown"

    # =========================================================================
    # Snapshot Triggering
    # =========================================================================

    def snapshot_area(
        self,
        left_top: Dict[str, float],
        right_bottom: Dict[str, float],
    ) -> SnapshotAreaResult:
        """Trigger snapshot for a rectangular area.

        Args:
            left_top: {"x": float, "y": float} - Top-left corner
            right_bottom: {"x": float, "y": float} - Bottom-right corner

        Returns:
            SnapshotAreaResult with success status and chunks_queued
        """
        bounds = {"left_top": left_top, "right_bottom": right_bottom}
        result = self._call("snapshot_area", bounds)
        if result:
            return SnapshotAreaResult.from_dict(result)
        return SnapshotAreaResult(success=False, error="Empty response")

    def re_snapshot_area(
        self,
        left_top: Dict[str, float],
        right_bottom: Dict[str, float],
    ) -> SnapshotAreaResult:
        """Force re-snapshot an area (even if already snapshotted).

        Args:
            left_top: {"x": float, "y": float} - Top-left corner
            right_bottom: {"x": float, "y": float} - Bottom-right corner

        Returns:
            SnapshotAreaResult with success status and chunks_queued
        """
        bounds = {"left_top": left_top, "right_bottom": right_bottom}
        result = self._call("re_snapshot_area", bounds)
        if result:
            return SnapshotAreaResult.from_dict(result)
        return SnapshotAreaResult(success=False, error="Empty response")

    def trigger_initial_snapshot(self) -> Dict[str, Any]:
        """Trigger initial snapshot of all tracked chunks.

        Only effective in DEFERRED mode. Queues all tracked chunks for snapshotting.

        Returns:
            Dict with result info
        """
        result = self._call("trigger_initial_snapshot")
        logger.info("Triggered initial snapshot")
        return result or {}

    def enqueue_chunk_for_snapshot(self, chunk_x: int, chunk_y: int) -> Dict[str, Any]:
        """Enqueue a specific chunk for snapshotting.

        Args:
            chunk_x: Chunk X coordinate
            chunk_y: Chunk Y coordinate

        Returns:
            Dict with result info
        """
        result = self._call("enqueue_chunk_for_snapshot", chunk_x, chunk_y)
        return result or {}

    # =========================================================================
    # Orchestration Mode
    # =========================================================================

    def get_orchestration_mode(self) -> str:
        """Get current orchestration mode.

        Returns:
            Mode string: "AUTO", "DEFERRED", or "SELECTIVE"
        """
        result = self._call("get_orchestration_mode")
        return result if isinstance(result, str) else "unknown"

    def set_orchestration_mode(self, mode: OrchestrationMode) -> Dict[str, Any]:
        """Set orchestration mode.

        Args:
            mode: "AUTO" - Snapshot chunks immediately when charted
                  "DEFERRED" - Track chunks, snapshot on trigger_initial_snapshot()
                  "SELECTIVE" - Only snapshot via explicit snapshot_area() calls

        Returns:
            Dict with result info
        """
        result = self._call("set_orchestration_mode", mode)
        logger.info(f"Set orchestration mode to: {mode}")
        return result or {}

    # =========================================================================
    # Map Area State
    # =========================================================================

    def get_charted_chunks(self) -> List[ChunkInfo]:
        """Get list of all charted chunks.

        Returns:
            List of ChunkInfo with x, y, state, entity_count
        """
        result = self._call("get_charted_chunks")
        if result and isinstance(result, list):
            return [ChunkInfo.from_dict(c) for c in result]
        return []

    def get_chunk_lookup(self) -> Dict[str, Any]:
        """Get chunk lookup table.

        Returns:
            Dict with chunk coordinate keys and state info
        """
        result = self._call("get_chunk_lookup")
        return result if isinstance(result, dict) else {}

    def get_map_area_state(
        self,
        left_top: Dict[str, float],
        right_bottom: Dict[str, float],
    ) -> Dict[str, Any]:
        """Get state of chunks in an area.

        Args:
            left_top: {"x": float, "y": float}
            right_bottom: {"x": float, "y": float}

        Returns:
            Dict with area state info
        """
        bounds = {"left_top": left_top, "right_bottom": right_bottom}
        result = self._call("get_map_area_state", bounds)
        return result or {}

    def set_map_area_state(
        self,
        left_top: Dict[str, float],
        right_bottom: Dict[str, float],
        state: str,
    ) -> Dict[str, Any]:
        """Set state for chunks in an area.

        Args:
            left_top: {"x": float, "y": float}
            right_bottom: {"x": float, "y": float}
            state: State to set

        Returns:
            Dict with result info
        """
        bounds = {"left_top": left_top, "right_bottom": right_bottom}
        result = self._call("set_map_area_state", bounds, state)
        return result or {}

    def clear_map_area(
        self,
        left_top: Dict[str, float],
        right_bottom: Dict[str, float],
    ) -> Dict[str, Any]:
        """Clear chunk tracking for an area.

        Args:
            left_top: {"x": float, "y": float}
            right_bottom: {"x": float, "y": float}

        Returns:
            Dict with result info
        """
        bounds = {"left_top": left_top, "right_bottom": right_bottom}
        result = self._call("clear_map_area", bounds)
        return result or {}

    # =========================================================================
    # Snapshot Configuration (from "snapshot" interface)
    # =========================================================================

    def set_udp_port(self, port: int) -> Dict[str, Any]:
        """Set UDP port for snapshot notifications.

        Args:
            port: UDP port (1024-65535)

        Returns:
            Dict with success and port
        """
        # This method is on the "snapshot" interface, not "map"
        cmd = (
            f"/c local res = remote.call('snapshot', 'set_udp_port', {port}); "
            "rcon.print(helpers.table_to_json(res))"
        )
        import json

        result = self._rcon.send_command(cmd)
        if result and result.strip():
            try:
                return json.loads(result)
            except json.JSONDecodeError:
                pass
        return {"success": True, "port": port}

    def get_udp_port(self) -> int:
        """Get current UDP port for snapshot notifications.

        Returns:
            UDP port number
        """
        # This method is on the "snapshot" interface, not "map"
        cmd = "/c rcon.print(remote.call('snapshot', 'get_udp_port'))"
        result = self._rcon.send_command(cmd)
        if result and result.strip():
            try:
                return int(result.strip())
            except ValueError:
                pass
        return 0

    def set_snapshot_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Set snapshot configuration.

        Args:
            config: Configuration dict

        Returns:
            Dict with result info
        """
        result = self._call("set_snapshot_config", config)
        return result or {}
