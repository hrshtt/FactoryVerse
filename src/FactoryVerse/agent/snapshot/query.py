from __future__ import annotations

import json
import logging
import re
from typing import List, Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb
    from FactoryVerse.factory.entity.views import RemoteView
    from FactoryVerse.factory.resource.remote_view_resource import RemoteViewResource
    from FactoryVerse.factory.entity.base_entity import BaseEntity

logger = logging.getLogger(__name__)

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

    def __init__(self, db: "duckdb.DuckDBPyConnection"):
        """Initialize query executor.

        Args:
            db: Active DuckDB connection with schema created
        """
        self._db = db

    def query(self, sql: str) -> List[Dict[str, Any]]:
        """Execute raw SQL, return list of dicts.

        Validates query is read-only SELECT.

        Args:
            sql: SQL query string (must be SELECT)

        Returns:
            List of row dictionaries

        Raises:
            ValueError: If query is not read-only
        """
        self._validate_query(sql)

        try:
            result = self._db.execute(sql)
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()

            return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"Query failed: {e}")
            raise

    def get_entities(self, sql: str) -> List["RemoteView"]:
        """Execute SQL, construct RemoteView entity instances.

        Query should return rows from map_entity table (or joins with it).
        Each row is converted to a RemoteView-wrapped entity object.

        Args:
            sql: SQL query against map_entity table

        Returns:
            List of RemoteView[BaseEntity] instances
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

    def get_entity(self, sql: str) -> Optional["RemoteView"]:
        """Execute SQL with LIMIT 1, return single entity.

        Args:
            sql: SQL query (should include LIMIT 1 for efficiency)

        Returns:
            Single RemoteView[BaseEntity] or None

        Raises:
            ValueError: If query doesn't include LIMIT 1
        """
        upper_sql = sql.upper()
        if "LIMIT" not in upper_sql:
            # Add LIMIT 1 for safety
            sql = sql.rstrip(";") + " LIMIT 1"

        entities = self.get_entities(sql)
        return entities[0] if entities else None

    def get_resources(self, sql: str) -> List["RemoteViewResource"]:
        """Execute SQL, construct RemoteViewResource instances.

        Query should return rows from resource_tile or resource_entity tables.

        Args:
            sql: SQL query against resource tables

        Returns:
            List of RemoteViewResource instances
        """
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

    def _construct_entity(self, row: Dict[str, Any]) -> Optional["RemoteView"]:
        """Create RemoteView-wrapped entity from row data.

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
        from FactoryVerse.factory.entity.factory import create_remote_view_entity

        try:
            # Create a minimal entity_ops for inspection (RemoteView is read-only)
            # Note: This is a limitation - RemoteView entities from map queries
            # won't have full inspection capability without RCON access
            entity = create_remote_view_entity(
                entity_data,
                entity_ops=None,  # type: ignore  # Read-only, no ops needed
                place_ops=None,
                is_ghost=entity_data.get("is_ghost", False),
            )
            return entity
        except ValueError as e:
            logger.debug(f"Could not create entity: {e}")
            return None

    def _row_to_entity_data(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Convert row columns to entity data dict."""
        return {
            "key": row.get("entity_key"),
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

    def _construct_resource(
        self, row: Dict[str, Any]
    ) -> Optional["RemoteViewResource"]:
        """Create RemoteViewResource from row data."""
        from FactoryVerse.factory.resource.remote_view_resource import (
            RemoteViewResource,
        )
        from FactoryVerse.factory.resource.base import _create_resource_from_data

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
            resource = _create_resource_from_data(resource_data)
            return RemoteViewResource(resource)
        except Exception as e:
            logger.debug(f"Could not create resource: {e}")
            return None

    def _row_to_resource_data(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Convert row to resource data dict."""
        return {
            "name": row.get("name"),
            "x": row.get("position_x", 0),
            "y": row.get("position_y", 0),
            "amount": row.get("amount"),
            "type": row.get("entity_type", "resource"),
        }

    def _construct_ghost(self, row: Dict[str, Any]) -> Optional["RemoteView"]:
        """Create ghost entity from row data."""
        from FactoryVerse.factory.entity.factory import create_remote_view_entity

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
                entity_ops=None,  # type: ignore
                place_ops=None,
                is_ghost=True,
            )
            return entity
        except ValueError as e:
            logger.debug(f"Could not create ghost entity: {e}")
            return None

    def _row_to_ghost_data(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Convert row to ghost data dict."""
        return {
            "key": row.get("entity_key"),
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
