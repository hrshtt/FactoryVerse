"""File loading and replay for snapshot data.

Single responsibility: Read JSONL files and populate DuckDB tables.
Does NOT manage connection (receives it) or handle UDP sync.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional, Iterator, Dict, Any, List

import duckdb

from FactoryVerse.game.snapshot.types import LoadResult, ChunkKey
from FactoryVerse.game.infra.duckdb import apply_ops
from FactoryVerse.game.infra.duckdb import analytics_ops

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
        self._base_dir = Path(snapshot_dir)
        self._snapshot_dir = self._normalize_path(snapshot_dir)

    def _normalize_path(self, path: Path) -> Path:
        """Ensure path points to snapshot directory."""
        path = Path(path)
        # Check if this is script-output root
        snapshot_subdir = path / "factoryverse" / "snapshots"
        if snapshot_subdir.exists():
            return snapshot_subdir
        return path

    def load_all(self, current_game_tick: Optional[int] = None) -> LoadResult:
        """Load all init files and replay all updates.

        Args:
            current_game_tick: If given, init files whose chunk_meta tick is
                GREATER than this are skipped with a loud log — such files are
                "from the future" relative to the running game, i.e. leftovers
                from a previous boot whose tick counter was further along
                (CELL-2a: stale-boot contamination). None keeps the old
                load-everything behavior.

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
            chunk_result = self._load_chunk(chunk, current_game_tick=current_game_tick)
            result.entity_count += chunk_result.get("entities", 0)
            result.resource_count += chunk_result.get("resources", 0)
            result.ghost_count += chunk_result.get("ghosts", 0)
            result.water_count += chunk_result.get("water", 0)
            result.chunks.append(chunk)

        # Boot-aggregate the agent's event-driven crafting/mining records.
        # Polled feeds (status dumps, power samples, force production) are
        # NOT loaded: they are not tables (Constitution §10) — remote_view
        # reads their files on demand.
        manual_count = self._load_agent_statistics()
        logger.info(f"Loaded {manual_count} agent manual snapshot(s)")

        # Replay all update files
        result.last_sequence = self.replay_updates(
            current_game_tick=current_game_tick
        )

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

    def _load_chunk(
        self, chunk: ChunkKey, current_game_tick: Optional[int] = None
    ) -> Dict[str, int]:
        """Load a single chunk's init files.

        Args:
            chunk: Chunk to load
            current_game_tick: If given, init files with chunk_meta tick >
                this value are SKIPPED (previous-boot files are "from the
                future"). None = load everything (old behavior).

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

        def _fresh(path: Path) -> bool:
            """False if this init file is from a future tick (stale boot)."""
            if current_game_tick is None:
                return True
            file_tick = self._init_file_tick(path)
            if file_tick is not None and file_tick > current_game_tick:
                logger.warning(
                    f"SKIPPING stale-boot init file (tick {file_tick} > "
                    f"current game tick {current_game_tick}): {path} — "
                    f"this file is from a previous server boot and must not "
                    f"be loaded (CELL-2a)"
                )
                return False
            return True

        # Load entities-init.jsonl
        entities_file = chunk_dir / "entities-init.jsonl"
        if entities_file.exists() and _fresh(entities_file):
            counts["entities"] = self._load_entities_file(entities_file, chunk)

        # Load resources-init.jsonl
        resources_file = chunk_dir / "resources-init.jsonl"
        if resources_file.exists() and _fresh(resources_file):
            counts["resources"] = self._load_resources_file(resources_file, chunk)

        # Load water-init.jsonl
        water_file = chunk_dir / "water-init.jsonl"
        if water_file.exists() and _fresh(water_file):
            counts["water"] = self._load_water_file(water_file, chunk)

        # Load trees_rocks-init.jsonl
        trees_file = chunk_dir / "trees_rocks-init.jsonl"
        if trees_file.exists() and _fresh(trees_file):
            counts["trees_rocks"] = self._load_trees_rocks_file(trees_file, chunk)

        # Load ghosts-init.jsonl (chunk-wise)
        ghosts_file = chunk_dir / "ghosts-init.jsonl"
        if ghosts_file.exists() and _fresh(ghosts_file):
            counts["ghosts"] = self._load_ghosts_file(ghosts_file, chunk)

        return counts

    def _init_file_tick(self, path: Path) -> Optional[int]:
        """Read the chunk_meta tick from an init file's first line.

        Returns None if the file has no chunk_meta first line (legacy format)
        or is unreadable — such files keep the old load-always behavior.
        """
        try:
            with open(path, "r") as f:
                first_line = f.readline().strip()
            if not first_line:
                return None
            data = json.loads(first_line)
            if (
                isinstance(data, dict)
                and data.get("kind") == "chunk_meta"
                and "tick" in data
            ):
                return int(data["tick"])
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            pass
        return None

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

    # =========================================================================
    # Agent statistics (event-backed crafting/mining records)
    # =========================================================================

    def _agent_snapshots_dir(self) -> Path:
        """Resolve ``factoryverse/agent-snapshots`` for either input shape."""
        candidate = self._base_dir / "factoryverse" / "agent-snapshots"
        if candidate.exists():
            return candidate
        return self._snapshot_dir.parent / "agent-snapshots"

    def _load_agent_statistics(self) -> int:
        """Boot-aggregate each agent's crafting/mining event files."""
        root = self._agent_snapshots_dir()
        if not root.exists():
            return 0

        manual_count = 0
        for agent_dir in sorted(path for path in root.iterdir() if path.is_dir()):
            try:
                agent_id = int(agent_dir.name)
            except ValueError:
                continue

            try:
                if analytics_ops.apply_agent_manual_files(
                    self._db, agent_dir, agent_id=agent_id
                ):
                    manual_count += 1
            except Exception as exc:
                logger.warning(
                    f"Failed to apply manual production files from {agent_dir}: {exc}"
                )
        return manual_count

    def replay_updates(
        self,
        from_sequence: Optional[int] = None,
        current_game_tick: Optional[int] = None,
    ) -> int:
        """Replay all update files in sequence order.

        Update records that predate their chunk's init snapshot tick are
        dropped: the init files already reflect that state, and replaying a
        stale upsert over a fresher init resurrects old data (SNAP-5 / L2.2
        stale-pipe_neighbours finding). The per-chunk init tick comes from the
        kind=chunk_meta line recorded into chunk_snapshot_meta during the same
        load pass. Records without a tick keep the old replay-always behavior.

        Update records with tick GREATER than current_game_tick (if given)
        are also dropped: they are from a previous boot whose tick counter
        was further along (CELL-2a — replaying them resurrected destroyed
        entities in the 2026-06-11 field run).

        Args:
            from_sequence: Only replay operations after this sequence
            current_game_tick: If given, drop records with tick > this value

        Returns:
            Last sequence number processed
        """
        # Per-chunk init snapshot ticks (recorded by _iter_jsonl meta lines)
        init_ticks = self._chunk_init_ticks()
        stale_dropped = 0
        future_dropped = 0

        def _is_future(data: Dict[str, Any]) -> bool:
            """True if the record's tick is ahead of the running game."""
            tick = data.get("tick")
            return (
                current_game_tick is not None
                and isinstance(tick, (int, float))
                and tick > current_game_tick
            )

        def _is_stale(data: Dict[str, Any], chunk: ChunkKey) -> bool:
            tick = data.get("tick")
            init_tick = init_ticks.get((chunk.x, chunk.y))
            return (
                isinstance(tick, (int, float))
                and init_tick is not None
                and tick < init_tick
            )

        # Collect all operations from update files
        operations = []

        # Chunk-wise update files
        for chunk in self._find_chunks():
            chunk_dir = self._snapshot_dir / str(chunk.x) / str(chunk.y)

            # Entity updates
            updates_file = chunk_dir / "entities-updates.jsonl"
            if updates_file.exists():
                for data in self._iter_jsonl(updates_file):
                    if _is_future(data):
                        future_dropped += 1
                        continue
                    if _is_stale(data, chunk):
                        stale_dropped += 1
                        continue
                    data["chunk"] = {"x": chunk.x, "y": chunk.y}
                    operations.append(data)

            # Trees/rocks updates
            trees_updates = chunk_dir / "trees_rocks-updates.jsonl"
            if trees_updates.exists():
                for data in self._iter_jsonl(trees_updates):
                    if _is_future(data):
                        future_dropped += 1
                        continue
                    if _is_stale(data, chunk):
                        stale_dropped += 1
                        continue
                    data["chunk"] = {"x": chunk.x, "y": chunk.y}
                    data["_type"] = "resource_entity"
                    operations.append(data)

            # Chunk-wise ghost updates
            ghost_updates = chunk_dir / "ghosts-updates.jsonl"
            if ghost_updates.exists():
                for data in self._iter_jsonl(ghost_updates):
                    if _is_future(data):
                        future_dropped += 1
                        continue
                    if _is_stale(data, chunk):
                        stale_dropped += 1
                        continue
                    data["chunk"] = {"x": chunk.x, "y": chunk.y}
                    data["_type"] = "ghost"
                    operations.append(data)

        if stale_dropped:
            logger.info(
                f"Dropped {stale_dropped} update records older than their "
                f"chunk's init snapshot tick"
            )
        if future_dropped:
            logger.warning(
                f"SKIPPED {future_dropped} update records with tick > current "
                f"game tick ({current_game_tick}) — previous-boot leftovers "
                f"are 'from the future' and must not be replayed (CELL-2a)"
            )

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
        op_type = data.get("_type", "entity")

        if op_type == "ghost":
            self._apply_ghost_operation(data)
        elif op_type == "resource_entity":
            self._apply_resource_entity_operation(data)
        else:
            self._apply_entity_operation(data)

    def _apply_entity_operation(self, data: Dict[str, Any]) -> None:
        """Apply entity operation (normalizes the file envelope; all writes go
        through the shared reducer — see apply_ops module docstring)."""
        op = data.get("op")
        chunk = ChunkKey(
            x=data.get("chunk", {}).get("x", 0), y=data.get("chunk", {}).get("y", 0)
        )

        if op == "upsert":
            entity_data = data.get("entity", {})
            apply_ops.upsert_entity(
                self._db, entity_data, chunk.x, chunk.y,
                default_tick=data.get("tick"))
        elif op == "remove":
            entity_name = data.get("name", "")
            position = data.get("position", {})
            pos_x = float(position.get("x", 0))
            pos_y = float(position.get("y", 0))
            if entity_name:
                apply_ops.remove_entity(self._db, entity_name, pos_x, pos_y)
        elif op == "rotated":
            entity_name = data.get("name", "")
            position = data.get("position", {})
            pos_x = float(position.get("x", 0))
            pos_y = float(position.get("y", 0))
            direction = data.get("direction")
            if entity_name and direction is not None:
                apply_ops.rotate_entity(self._db, entity_name, pos_x, pos_y, direction)

    def _apply_ghost_operation(self, data: Dict[str, Any]) -> None:
        """Apply ghost operation."""
        op = data.get("op")

        if op == "upsert":
            ghost_data = data.get("ghost", {})
            apply_ops.upsert_ghost(self._db, ghost_data, default_tick=data.get("tick"))
        elif op == "remove":
            # The mod emits the key as ghost_name (make_ghost_remove_operation);
            # `name` kept as fallback for the UDP-payload shape
            ghost_name = data.get("ghost_name") or data.get("name", "")
            position = data.get("position", {})
            pos_x = float(position.get("x", 0))
            pos_y = float(position.get("y", 0))
            if ghost_name:
                apply_ops.remove_ghost(self._db, ghost_name, pos_x, pos_y)
            else:
                logger.warning(f"Ghost remove op without ghost_name/name — dropped: {data}")
        elif op == "rotated":
            ghost_name = data.get("ghost_name") or data.get("name", "")
            position = data.get("position", {})
            pos_x = float(position.get("x", 0))
            pos_y = float(position.get("y", 0))
            direction = data.get("direction")
            if ghost_name and direction is not None:
                apply_ops.rotate_ghost(self._db, ghost_name, pos_x, pos_y, direction)

    def _apply_resource_entity_operation(self, data: Dict[str, Any]) -> None:
        """Apply resource entity (tree/rock) operation."""
        op = data.get("op")

        if op == "remove":
            entity_name = data.get("name", "")
            position = data.get("position", {})
            pos_x = float(position.get("x", 0))
            pos_y = float(position.get("y", 0))
            if entity_name:
                apply_ops.remove_resource_entity(self._db, entity_name, pos_x, pos_y)

    # =========================================================================
    # Insert helpers
    # =========================================================================

    def _insert_entity(self, data: Dict[str, Any], chunk: ChunkKey) -> None:
        """Insert or replace entity in map_entity table (shared reducer)."""
        apply_ops.upsert_entity(self._db, data, chunk.x, chunk.y)

    def _insert_ghost(self, data: Dict[str, Any]) -> None:
        """Insert or replace ghost in ghost table (shared reducer)."""
        apply_ops.upsert_ghost(self._db, data)

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
        apply_ops.upsert_resource_entity(self._db, data, chunk.x, chunk.y)


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

    def _chunk_init_ticks(self) -> Dict[tuple, int]:
        """Per-chunk init snapshot ticks from chunk_snapshot_meta.

        Populated during the same load pass (init files' kind=chunk_meta lines
        via _record_chunk_meta). Empty dict if the table is missing/empty —
        replay then keeps its old apply-everything behavior.
        """
        try:
            rows = self._db.execute(
                "SELECT chunk_x, chunk_y, tick FROM chunk_snapshot_meta"
            ).fetchall()
            return {(int(x), int(y)): int(t) for x, y, t in rows}
        except Exception as e:
            logger.warning(f"Could not read chunk_snapshot_meta: {e}")
            return {}

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
