from __future__ import annotations

import json
import logging
import re
import threading
from typing import List, Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb
    from FactoryVerse.factory.resource.base import BaseResource
    from FactoryVerse.factory.entity.base_entity import BaseEntity
    from FactoryVerse.agent.actions.walking import MovementAction
    from FactoryVerse.agent.actions.entity_operations import EntityOperationsAction
    from FactoryVerse.agent.actions.place_entity import PlacementAction
    from FactoryVerse.agent.actions.mining import MiningAction
    from FactoryVerse.agent.snapshot.sync import SyncService

logger = logging.getLogger(__name__)


def _preprocess_resource_sql(sql: str) -> str:
    """Preprocess SQL queries to map agent-facing "rock" to game-facing "simple-entity".
    
    Converts SQL queries that use "rock" in entity_type comparisons to use "simple-entity"
    instead, since the database stores the game-facing type.
    
    This allows agents to write natural queries like:
        SELECT * FROM resource_entity WHERE entity_type = 'rock'
    
    Which gets converted to:
        SELECT * FROM resource_entity WHERE entity_type = 'simple-entity'
    
    Args:
        sql: SQL query string
    
    Returns:
        Preprocessed SQL with "rock" -> "simple-entity" mapping applied
    """
    # Pattern to match entity_type = 'rock' or entity_type = "rock" in WHERE clauses
    # Handles various SQL formats: =, !=, IN, etc.
    # Uses word boundaries to avoid matching "rock" in other contexts
    
    # Replace 'rock' and "rock" in entity_type comparisons
    # Pattern: entity_type = 'rock' or entity_type = "rock"
    sql = re.sub(
        r"entity_type\s*=\s*['\"]rock['\"]",
        "entity_type = 'simple-entity'",
        sql,
        flags=re.IGNORECASE
    )
    
    # Handle IN clauses: entity_type IN ('rock', 'tree')
    sql = re.sub(
        r"entity_type\s+IN\s*\([^)]*['\"]rock['\"][^)]*\)",
        lambda m: m.group(0).replace("'rock'", "'simple-entity'").replace('"rock"', '"simple-entity"'),
        sql,
        flags=re.IGNORECASE
    )
    
    # Handle != and <> operators
    sql = re.sub(
        r"entity_type\s*(!=|<>)\s*['\"]rock['\"]",
        lambda m: f"entity_type {m.group(1)} 'simple-entity'",
        sql,
        flags=re.IGNORECASE
    )
    
    return sql

# SQL keywords that are not allowed in queries
FORBIDDEN_KEYWORDS = frozenset(
    [
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "CREATE",
        "ALTER",
        "TRUNCATE",
        "GRANT",
        "REVOKE",
        "EXEC",
        "EXECUTE",
        "CALL",
        "MERGE",
        "UPSERT",
    ]
)


class QueryExecutor:
    """Executes validated queries and constructs entities.

    Responsibilities:
    - Validate that queries are read-only SELECT
    - Execute SQL against DuckDB
    - Construct typed entity objects from results

    Does NOT:
    - Manage database connection (receives it)
    - Handle sync (sync.py does that)
    - Load data (loader.py does that)
    """

    def __init__(
        self,
        db: "duckdb.DuckDBPyConnection",
        entity_ops: "EntityOperationsAction",
        place_ops: "PlacementAction",
        walking_action: "MovementAction",
        mining_action: "MiningAction",
        sync_service: Optional["SyncService"] = None,
        db_lock: Optional[threading.Lock] = None,
    ):
        """Initialize query executor.

        Args:
            db: Active DuckDB connection with schema created
            entity_ops: Entity operations action for inspection
            place_ops: Placement action for ghost operations
            walking_action: Movement action for navigation
            mining_action: Mining action (required for resources)
            sync_service: Sync service for flushing pending writes before reads
            db_lock: Shared lock for thread-safe database access
        """
        self._db = db
        self._entity_ops = entity_ops
        self._place_ops = place_ops
        self._walking_action = walking_action
        self._mining_action = mining_action
        self._sync_service = sync_service
        self._db_lock = db_lock if db_lock is not None else threading.Lock()

    def query(self, sql: str) -> List[Dict[str, Any]]:
        """Execute raw SQL, return list of dicts.

        Validates query is read-only SELECT.
        Flushes pending writes before reading to ensure consistency.

        Args:
            sql: SQL query string (must be SELECT)

        Returns:
            List of row dictionaries

        Raises:
            ValueError: If query is not read-only
        """
        self._validate_query(sql)

        # CRITICAL: Flush pending writes before reading
        print(
            f"[QUERY] About to flush, sync_service exists: {self._sync_service is not None}"
        )
        if self._sync_service:
            flushed = self._sync_service.flush_pending()
            print(f"[QUERY] Flushed {flushed} operations")
            if flushed > 0:
                logger.info(f"Flushed {flushed} operations before query")

        try:
            # Execute with lock to prevent concurrent writes
            with self._db_lock:
                result = self._db.execute(sql)
                columns = [desc[0] for desc in result.description]
                rows = result.fetchall()

            return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"Query failed: {e}")
            raise

    def get_entities(self, sql: str) -> List["BaseEntity"]:
        """Execute SQL, construct entity instances with REMOTE view.

        Query should return rows from map_entity table (or joins with it).
        Each row is converted to an entity object with REMOTE view.

        Args:
            sql: SQL query against map_entity table

        Returns:
            List of BaseEntity instances with REMOTE view
        """
        rows = self.query(sql)
        entities = []

        for row in rows:
            try:
                entity = self._construct_entity(row)
                if entity:
                    entities.append(entity)
            except Exception as e:
                logger.warning(f"Failed to construct entity: {e}")

        return entities

    def get_entity(self, sql: str) -> Optional["BaseEntity"]:
        """Execute SQL with LIMIT 1, return single entity.

        Args:
            sql: SQL query (should include LIMIT 1 for efficiency)

        Returns:
            Single BaseEntity with REMOTE view or None

        Raises:
            ValueError: If query doesn't include LIMIT 1
        """
        upper_sql = sql.upper()
        if "LIMIT" not in upper_sql:
            # Add LIMIT 1 for safety
            sql = sql.rstrip(";") + " LIMIT 1"

        entities = self.get_entities(sql)
        return entities[0] if entities else None

    def get_resources(self, sql: str) -> List["BaseResource"]:
        """Execute SQL, construct resource instances with REMOTE view.

        Query should return rows from resource_tile or resource_entity tables.
        Each row is converted to a resource object with REMOTE view.
        
        Note: You can use "rock" in entity_type filters - it will be automatically
        converted to "simple-entity" (the database storage format).

        Args:
            sql: SQL query against resource tables (can use "rock" for entity_type)

        Returns:
            List of BaseResource instances with REMOTE view
        """
        # Preprocess SQL to map "rock" -> "simple-entity" for entity_type filters
        sql = _preprocess_resource_sql(sql)
        rows = self.query(sql)
        resources = []

        for row in rows:
            try:
                resource = self._construct_resource(row)
                if resource:
                    resources.append(resource)
            except Exception as e:
                logger.warning(f"Failed to construct resource: {e}")

        return resources

    def get_ghosts(self, sql: str) -> List["BaseEntity"]:
        """Execute SQL against ghost table, construct Ghost entity views.

        Args:
            sql: SQL query against ghost table

        Returns:
            List of BaseEntity instances with is_ghost=True
        """
        rows = self.query(sql)
        ghosts = []

        for row in rows:
            try:
                ghost = self._construct_ghost(row)
                if ghost:
                    ghosts.append(ghost)
            except Exception as e:
                logger.warning(f"Failed to construct ghost: {e}")

        return ghosts

    # =========================================================================
    # Query Validation
    # =========================================================================

    def _validate_query(self, sql: str) -> None:
        """Ensure query is read-only SELECT.

        Raises:
            ValueError: If query contains forbidden keywords
        """
        stripped = sql.strip()
        upper = stripped.upper()

        # Must start with SELECT or WITH (for CTEs)
        if not upper.startswith("SELECT") and not upper.startswith("WITH"):
            raise ValueError(
                "Only SELECT queries are allowed (may start with WITH for CTEs)"
            )

        # Check for forbidden keywords
        # Use word boundaries to avoid false positives (e.g., "CASCADE_DELETE" column name)
        for keyword in FORBIDDEN_KEYWORDS:
            # Match keyword as whole word
            pattern = r"\b" + keyword + r"\b"
            if re.search(pattern, upper):
                raise ValueError(f"Forbidden SQL keyword: {keyword}")

    # =========================================================================
    # Entity Construction
    # =========================================================================

    def _construct_entity(self, row: Dict[str, Any]) -> Optional["BaseEntity"]:
        """Create entity with REMOTE view from row data.

        Uses raw_data if available, otherwise constructs from columns.
        """
        # Try to use raw_data for full entity info
        raw_data = row.get("raw_data")
        if raw_data:
            if isinstance(raw_data, str):
                try:
                    entity_data = json.loads(raw_data)
                except json.JSONDecodeError:
                    entity_data = self._row_to_entity_data(row)
            else:
                entity_data = raw_data
        else:
            entity_data = self._row_to_entity_data(row)

        # Import factory function
        from FactoryVerse.factory.entity.create_entity import create_remote_view_entity

        try:
            entity = create_remote_view_entity(
                entity_data,
                entity_ops=self._entity_ops,
                place_ops=self._place_ops,
                walking_action=self._walking_action,
                is_ghost=entity_data.get("is_ghost", False),
            )
            return entity
        except ValueError as e:
            logger.debug(f"Could not create entity: {e}")
            return None

    def _row_to_entity_data(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Convert row columns to entity data dict."""
        return {
            "name": row.get("entity_name"),
            "position": {
                "x": row.get("position_x", 0),
                "y": row.get("position_y", 0),
            },
            "direction": row.get("direction"),
            "bounding_box": {
                "min_x": row.get("bbox_min_x"),
                "min_y": row.get("bbox_min_y"),
                "max_x": row.get("bbox_max_x"),
                "max_y": row.get("bbox_max_y"),
            },
        }

    def _construct_resource(self, row: Dict[str, Any]) -> Optional["BaseResource"]:
        """Create resource with REMOTE view from row data."""
        from FactoryVerse.factory.resource.base import create_resource_from_db

        # Build resource data
        raw_data = row.get("raw_data")
        if raw_data and isinstance(raw_data, str):
            try:
                resource_data = json.loads(raw_data)
            except json.JSONDecodeError:
                resource_data = self._row_to_resource_data(row)
        else:
            resource_data = self._row_to_resource_data(row)

        try:
            resource = create_resource_from_db(
                resource_data,
                mining_action=self._mining_action,
                entity_ops=self._entity_ops,
                walking_action=self._walking_action,
            )
            return resource
        except Exception as e:
            logger.debug(f"Could not create resource: {e}")
            return None

    def _row_to_resource_data(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Convert row to resource data dict."""
        return {
            "name": row.get("name"),
            "position": {
                "x": row.get("position_x", 0),
                "y": row.get("position_y", 0),
            },
            "amount": row.get("amount"),
            "type": row.get("entity_type", "resource"),
        }

    def _construct_ghost(self, row: Dict[str, Any]) -> Optional["BaseEntity"]:
        """Create ghost entity with REMOTE view from row data."""
        from FactoryVerse.factory.entity.create_entity import create_remote_view_entity

        # Build ghost data
        raw_data = row.get("raw_data")
        if raw_data and isinstance(raw_data, str):
            try:
                ghost_data = json.loads(raw_data)
            except json.JSONDecodeError:
                ghost_data = self._row_to_ghost_data(row)
        else:
            ghost_data = self._row_to_ghost_data(row)

        # Set up ghost entity data
        ghost_name = ghost_data.get("ghost_name") or row.get("ghost_name")
        entity_data = {
            "name": ghost_name,
            "position": ghost_data.get("position")
            or {
                "x": row.get("position_x", 0),
                "y": row.get("position_y", 0),
            },
            "direction": ghost_data.get("direction") or row.get("direction"),
            "ghost_name": ghost_name,
        }

        try:
            entity = create_remote_view_entity(
                entity_data,
                entity_ops=self._entity_ops,
                place_ops=self._place_ops,
                walking_action=self._walking_action,
                is_ghost=True,
            )
            return entity
        except ValueError as e:
            logger.debug(f"Could not create ghost entity: {e}")
            return None

    def _row_to_ghost_data(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Convert row to ghost data dict."""
        return {
            "ghost_name": row.get("ghost_name"),
            "position": {
                "x": row.get("position_x", 0),
                "y": row.get("position_y", 0),
            },
            "direction": row.get("direction"),
            "placed_tick": row.get("placed_tick"),
            "placed_by": row.get("placed_by"),
            "label": row.get("label"),
        }


__all__ = ["QueryExecutor"]
