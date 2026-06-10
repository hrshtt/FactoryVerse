"""File loading and replay for snapshot data.

Single responsibility: Read JSONL files and populate DuckDB tables.
Does NOT manage connection (receives it) or handle UDP sync.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Optional, Iterator, Dict, Any, List

import duckdb

from FactoryVerse.game.snapshot.types import LoadResult, ChunkKey, EntityOperation

logger = logging.getLogger(__name__)


class SnapshotLoader:
    """Loads snapshot files into DuckDB.

    Responsibilities:
    - Find and parse JSONL snapshot files
    - Insert data into DuckDB tables
    - Replay update files in sequence order

    Does NOT:
    - Manage database connection (receives it)
    - Create schema (database.py does that)
    - Handle UDP sync (sync.py does that)
    """

    def __init__(self, db: duckdb.DuckDBPyConnection, snapshot_dir: Path):
        """Initialize loader.

        Args:
            db: Active DuckDB connection (schema should exist)
            snapshot_dir: Path to snapshot directory (or script-output root)
        """
        self._db = db
        self._snapshot_dir = self._normalize_path(snapshot_dir)

    def _normalize_path(self, path: Path) -> Path:
        """Ensure path points to snapshot directory."""
        path = Path(path)
        # Check if this is script-output root
        snapshot_subdir = path / "factoryverse" / "snapshots"
        if snapshot_subdir.exists():
            return snapshot_subdir
        return path

    def load_all(self) -> LoadResult:
        """Load all init files and replay all updates.

        Returns:
            LoadResult with counts and last sequence
        """
        result = LoadResult()

        if not self._snapshot_dir.exists():
            logger.warning(f"Snapshot directory does not exist: {self._snapshot_dir}")
            return result

        # Find all chunk directories
        chunks = self._find_chunks()
        logger.info(f"Found {len(chunks)} chunks to load")

        # Load each chunk
        for chunk in chunks:
            chunk_result = self._load_chunk(chunk)
            result.entity_count += chunk_result.get("entities", 0)
            result.resource_count += chunk_result.get("resources", 0)
            result.ghost_count += chunk_result.get("ghosts", 0)
            result.water_count += chunk_result.get("water", 0)
            result.chunks.append(chunk)

        # Replay all update files
        result.last_sequence = self.replay_updates()

        logger.info(f"Load complete: {result}")
        return result

    def _find_chunks(self) -> List[ChunkKey]:
        """Find all chunk directories."""
        chunks = []

        if not self._snapshot_dir.exists():
            return chunks

        # Iterate chunk_x directories
        for x_dir in self._snapshot_dir.iterdir():
            if not x_dir.is_dir():
                continue
            try:
                chunk_x = int(x_dir.name)
            except ValueError:
                continue

            # Iterate chunk_y directories
            for y_dir in x_dir.iterdir():
                if not y_dir.is_dir():
                    continue
                try:
                    chunk_y = int(y_dir.name)
                    chunks.append(ChunkKey(x=chunk_x, y=chunk_y))
                except ValueError:
                    continue

        return chunks

    def _load_chunk(self, chunk: ChunkKey) -> Dict[str, int]:
        """Load a single chunk's init files.

        Returns dict with counts per type.
        """
        chunk_dir = self._snapshot_dir / str(chunk.x) / str(chunk.y)
        counts = {
            "entities": 0,
            "resources": 0,
            "ghosts": 0,
            "water": 0,
            "trees_rocks": 0,
        }

        # Load entities-init.jsonl
        entities_file = chunk_dir / "entities-init.jsonl"
        if entities_file.exists():
            counts["entities"] = self._load_entities_file(entities_file, chunk)

        # Load resources-init.jsonl
        resources_file = chunk_dir / "resources-init.jsonl"
        if resources_file.exists():
            counts["resources"] = self._load_resources_file(resources_file, chunk)

        # Load water-init.jsonl
        water_file = chunk_dir / "water-init.jsonl"
        if water_file.exists():
            counts["water"] = self._load_water_file(water_file, chunk)

        # Load trees_rocks-init.jsonl
        trees_file = chunk_dir / "trees_rocks-init.jsonl"
        if trees_file.exists():
            counts["trees_rocks"] = self._load_trees_rocks_file(trees_file, chunk)

        # Load ghosts-init.jsonl (chunk-wise)
        ghosts_file = chunk_dir / "ghosts-init.jsonl"
        if ghosts_file.exists():
            counts["ghosts"] = self._load_ghosts_file(ghosts_file, chunk)

        return counts

    def _load_entities_file(self, path: Path, chunk: ChunkKey) -> int:
        """Load entities init file into map_entity table."""
        count = 0
        for data in self._iter_jsonl(path):
            try:
                self._insert_entity(data, chunk)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to load entity: {e}")
        return count

    def _load_resources_file(self, path: Path, chunk: ChunkKey) -> int:
        """Load resources init file into resource_tile table."""
        count = 0
        for data in self._iter_jsonl(path):
            try:
                self._insert_resource_tile(data, chunk)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to load resource: {e}")
        return count

    def _load_water_file(self, path: Path, chunk: ChunkKey) -> int:
        """Load water init file into water_tile table."""
        count = 0
        for data in self._iter_jsonl(path):
            try:
                self._insert_water_tile(data, chunk)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to load water tile: {e}")
        return count

    def _load_trees_rocks_file(self, path: Path, chunk: ChunkKey) -> int:
        """Load trees/rocks init file into resource_entity table."""
        count = 0
        for data in self._iter_jsonl(path):
            try:
                self._insert_resource_entity(data, chunk)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to load tree/rock: {e}")
        return count

    def _load_ghosts_file(self, path: Path, chunk: ChunkKey) -> int:
        """Load ghosts init file into ghost table."""
        count = 0
        for data in self._iter_jsonl(path):
            try:
                # Add chunk info if not present
                if "chunk" not in data:
                    data["chunk"] = {"x": chunk.x, "y": chunk.y}
                self._insert_ghost(data)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to load ghost: {e}")
        return count

    def replay_updates(self, from_sequence: Optional[int] = None) -> int:
        """Replay all update files in sequence order.

        Args:
            from_sequence: Only replay operations after this sequence

        Returns:
            Last sequence number processed
        """
        # Collect all operations from update files
        operations = []

        # Chunk-wise update files
        for chunk in self._find_chunks():
            chunk_dir = self._snapshot_dir / str(chunk.x) / str(chunk.y)

            # Entity updates
            updates_file = chunk_dir / "entities-updates.jsonl"
            if updates_file.exists():
                for data in self._iter_jsonl(updates_file):
                    data["chunk"] = {"x": chunk.x, "y": chunk.y}
                    operations.append(data)

            # Trees/rocks updates
            trees_updates = chunk_dir / "trees_rocks-updates.jsonl"
            if trees_updates.exists():
                for data in self._iter_jsonl(trees_updates):
                    data["chunk"] = {"x": chunk.x, "y": chunk.y}
                    data["_type"] = "resource_entity"
                    operations.append(data)

            # Chunk-wise ghost updates
            ghost_updates = chunk_dir / "ghosts-updates.jsonl"
            if ghost_updates.exists():
                for data in self._iter_jsonl(ghost_updates):
                    data["chunk"] = {"x": chunk.x, "y": chunk.y}
                    data["_type"] = "ghost"
                    operations.append(data)

        # Sort by sequence number
        operations.sort(key=lambda x: x.get("sequence", 0))

        # Filter by from_sequence
        if from_sequence is not None:
            operations = [
                op for op in operations if op.get("sequence", 0) > from_sequence
            ]

        # Apply operations
        last_sequence = from_sequence or 0
        for op_data in operations:
            try:
                self._apply_operation(op_data)
                seq = op_data.get("sequence", 0)
                if seq > last_sequence:
                    last_sequence = seq
            except Exception as e:
                logger.warning(f"Failed to apply operation: {e}")

        logger.info(
            f"Replayed {len(operations)} operations, last_sequence={last_sequence}"
        )
        return last_sequence

    def _apply_operation(self, data: Dict[str, Any]) -> None:
        """Apply a single operation (upsert or remove)."""
        op = data.get("op")
        op_type = data.get("_type", "entity")

        if op_type == "ghost":
            self._apply_ghost_operation(data)
        elif op_type == "resource_entity":
            self._apply_resource_entity_operation(data)
        else:
            self._apply_entity_operation(data)

    def _apply_entity_operation(self, data: Dict[str, Any]) -> None:
        """Apply entity operation."""
        op = data.get("op")
        chunk = ChunkKey(
            x=data.get("chunk", {}).get("x", 0), y=data.get("chunk", {}).get("y", 0)
        )

        if op == "upsert":
            entity_data = data.get("entity", {})
            self._insert_entity(entity_data, chunk)
        elif op == "remove":
            entity_name = data.get("name", "")
            position = data.get("position", {})
            pos_x = float(position.get("x", 0))
            pos_y = float(position.get("y", 0))
            if entity_name:
                self._db.execute(
                    "DELETE FROM map_entity WHERE entity_name = ? AND position_x = ? AND position_y = ?",
                    [entity_name, pos_x, pos_y],
                )
        elif op == "rotated":
            entity_name = data.get("name", "")
            position = data.get("position", {})
            pos_x = float(position.get("x", 0))
            pos_y = float(position.get("y", 0))
            direction = data.get("direction")
            if entity_name and direction is not None:
                self._db.execute(
                    "UPDATE map_entity SET direction = ? WHERE entity_name = ? AND position_x = ? AND position_y = ?",
                    [direction, entity_name, pos_x, pos_y],
                )

    def _apply_ghost_operation(self, data: Dict[str, Any]) -> None:
        """Apply ghost operation."""
        op = data.get("op")

        if op == "upsert":
            ghost_data = data.get("ghost", {})
            self._insert_ghost(ghost_data)
        elif op == "remove":
            ghost_name = data.get("name", "")
            position = data.get("position", {})
            pos_x = float(position.get("x", 0))
            pos_y = float(position.get("y", 0))
            if ghost_name:
                self._db.execute(
                    "DELETE FROM ghost WHERE ghost_name = ? AND position_x = ? AND position_y = ?",
                    [ghost_name, pos_x, pos_y],
                )
        elif op == "rotated":
            ghost_name = data.get("name", "")
            position = data.get("position", {})
            pos_x = float(position.get("x", 0))
            pos_y = float(position.get("y", 0))
            direction = data.get("direction")
            if ghost_name and direction is not None:
                self._db.execute(
                    "UPDATE ghost SET direction = ? WHERE ghost_name = ? AND position_x = ? AND position_y = ?",
                    [direction, ghost_name, pos_x, pos_y],
                )

    def _apply_resource_entity_operation(self, data: Dict[str, Any]) -> None:
        """Apply resource entity (tree/rock) operation."""
        op = data.get("op")

        if op == "remove":
            entity_name = data.get("name", "")
            position = data.get("position", {})
            pos_x = float(position.get("x", 0))
            pos_y = float(position.get("y", 0))
            if entity_name:
                self._db.execute(
                    "DELETE FROM resource_entity WHERE name = ? AND position_x = ? AND position_y = ?",
                    [entity_name, pos_x, pos_y],
                )

    # =========================================================================
    # Insert helpers
    # =========================================================================

    def _insert_entity(self, data: Dict[str, Any], chunk: ChunkKey) -> None:
        """Insert or replace entity in map_entity table."""
        position = data.get("position", {})
        pos_x = float(position.get("x", 0))
        pos_y = float(position.get("y", 0))
        entity_name = data.get("name", "")

        bbox = data.get("bounding_box", {})

        # Extract builder metadata
        builder = data.get("builder", {})
        agent_id = builder.get("agent_id") if builder else None
        player_id = builder.get("player_id") if builder else None
        label = builder.get("label") if builder else None
        placed_tick = builder.get("placed_tick") if builder else None

        self._db.execute(
            """
            INSERT OR REPLACE INTO map_entity 
            (entity_name, position_x, position_y, chunk_x, chunk_y,
             direction, bbox_min_x, bbox_min_y, bbox_max_x, bbox_max_y,
             agent_id, player_id, label, placed_tick, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                entity_name,
                pos_x,
                pos_y,
                chunk.x,
                chunk.y,
                data.get("direction"),
                bbox.get("min_x"),
                bbox.get("min_y"),
                bbox.get("max_x"),
                bbox.get("max_y"),
                agent_id,
                player_id,
                label,
                placed_tick,
                json.dumps(data),
            ],
        )

    def _insert_ghost(self, data: Dict[str, Any]) -> None:
        """Insert or replace ghost in ghost table."""
        position = data.get("position", {})
        pos_x = float(position.get("x", 0))
        pos_y = float(position.get("y", 0))

        ghost_name = data.get("ghost_name") or data.get("name", "")
        chunk_x = math.floor(pos_x / 32)
        chunk_y = math.floor(pos_y / 32)

        self._db.execute(
            """
            INSERT OR REPLACE INTO ghost
            (ghost_name, position_x, position_y, chunk_x, chunk_y,
             direction, placed_tick, placed_by, label, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ghost_name,
                pos_x,
                pos_y,
                chunk_x,
                chunk_y,
                data.get("direction"),
                data.get("placed_tick"),
                data.get("placed_by"),
                data.get("label"),
                json.dumps(data),
            ],
        )

    def _insert_resource_tile(self, data: Dict[str, Any], chunk: ChunkKey) -> None:
        """Insert resource tile into resource_tile table."""
        pos_x = float(data.get("x", 0))
        pos_y = float(data.get("y", 0))
        name = data.get("kind") or data.get("name", "")

        self._db.execute(
            """
            INSERT OR REPLACE INTO resource_tile
            (name, position_x, position_y, chunk_x, chunk_y, amount)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [name, pos_x, pos_y, chunk.x, chunk.y, data.get("amount")],
        )

    def _insert_water_tile(self, data: Dict[str, Any], chunk: ChunkKey) -> None:
        """Insert water tile into water_tile table."""
        pos_x = float(data.get("x", 0))
        pos_y = float(data.get("y", 0))

        self._db.execute(
            """
            INSERT OR REPLACE INTO water_tile
            (position_x, position_y, chunk_x, chunk_y)
            VALUES (?, ?, ?, ?)
            """,
            [pos_x, pos_y, chunk.x, chunk.y],
        )

    def _insert_resource_entity(self, data: Dict[str, Any], chunk: ChunkKey) -> None:
        """Insert tree/rock into resource_entity table."""
        position = data.get("position", {})
        pos_x = float(position.get("x", 0))
        pos_y = float(position.get("y", 0))
        name = data.get("name", "")

        self._db.execute(
            """
            INSERT OR REPLACE INTO resource_entity
            (name, entity_type, position_x, position_y, chunk_x, chunk_y, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                name,
                data.get("type", "unknown"),
                pos_x,
                pos_y,
                chunk.x,
                chunk.y,
                json.dumps(data),
            ],
        )


    def _iter_jsonl(self, path: Path) -> Iterator[Dict[str, Any]]:
        """Iterate over JSONL file, yielding parsed dicts.

        First line of mod-written init files is a kind=chunk_meta record
        (snapshot tick); it is recorded into chunk_snapshot_meta and not
        yielded. Detection is exact-match because resource lines also carry
        a 'kind' field (the ore name).
        """
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON in {path}: {e}")
                        continue
                    if (
                        isinstance(data, dict)
                        and data.get("kind") == "chunk_meta"
                        and "tick" in data
                    ):
                        self._record_chunk_meta(data)
                        continue
                    yield data

    def _record_chunk_meta(self, data: Dict[str, Any]) -> None:
        """Record per-chunk snapshot tick from an init file's meta line."""
        try:
            self._db.execute(
                """
                INSERT OR REPLACE INTO chunk_snapshot_meta
                (chunk_x, chunk_y, tick)
                VALUES (?, ?, ?)
                """,
                [int(data["chunk_x"]), int(data["chunk_y"]), int(data["tick"])],
            )
        except Exception as e:
            logger.warning(f"Failed to record chunk_snapshot_meta: {e}")


__all__ = ["SnapshotLoader"]
