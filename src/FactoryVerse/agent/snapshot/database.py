from typing import Optional


class _DuckDBAccessor:
    """Accessor for DuckDB map database operations.

    Provides read-only access to entities across the entire map via SQL queries.
    Returns RemoteViewEntity instances that can be inspected and used for planning,
    but cannot be mutated (no pickup, add_fuel, etc.).
    """

    def __init__(self, connection):
        """Initialize accessor with DuckDB connection.

        Args:
            connection: DuckDB connection instance
        """
        self.connection = connection

    def get_entity(self, query: str) -> Optional["RemoteViewEntity"]:
        """Get single read-only entity from DuckDB query.

        Args:
            query: SQL SELECT query with LIMIT 1 (enforced)

        Returns:
            RemoteViewEntity instance or None if no results

        Raises:
            ValueError: If query is invalid, unsafe, or missing LIMIT 1

        Example:
            >>> entity = map_db.get_entity('''
            ...     SELECT * FROM map_entity me
            ...     JOIN mining_drill md ON me.entity_key = md.entity_key
            ...     WHERE entity_name = 'burner-mining-drill'
            ...     LIMIT 1
            ... ''')
            >>> entity.output_position  # Planning capability
            >>> entity.inspect()  # Requires context manager
        """
        from FactoryVerse.dsl.entity.base import create_entity_from_db

        # Validate query
        self._validate_query(query)

        # Enforce LIMIT 1
        query_upper = query.upper()
        if "LIMIT 1" not in query_upper:
            raise ValueError("get_entity() requires LIMIT 1 in query")

        # Execute query
        cursor = self.connection.execute(query)
        result = cursor.fetchone()

        if result is None:
            return None

        # Convert to RemoteViewEntity
        entity_data = self._row_to_dict(result, cursor)
        return create_entity_from_db(entity_data)

    def get_entities(self, query: str) -> List["RemoteViewEntity"]:
        """Get read-only entities from DuckDB query.

        Args:
            query: SQL SELECT query (validated for safety)

        Returns:
            List of RemoteViewEntity instances (read-only)

        Raises:
            ValueError: If query is invalid or unsafe

        Example:
            >>> drills = map_db.get_entities('''
            ...     SELECT * FROM map_entity me
            ...     JOIN mining_drill md ON me.entity_key = md.entity_key
            ...     WHERE entity_name = 'burner-mining-drill'
            ... ''')
            >>> for drill in drills:
            ...     print(drill.output_position)  # Planning capability
        """
        from FactoryVerse.dsl.entity.base import create_entity_from_db

        # Validate query
        self._validate_query(query)

        # Execute query
        cursor = self.connection.execute(query)
        results = cursor.fetchall()

        # Convert to RemoteViewEntity instances
        entities = []
        for row in results:
            entity_data = self._row_to_dict(row, cursor)
            entity = create_entity_from_db(entity_data)
            entities.append(entity)

        return entities

    async def sync(self, timeout: float = 5.0) -> None:
        """Explicitly sync the database before queries.

        Call this before critical queries that require up-to-date data:
            await map_db.sync()
            entities = map_db.get_entities(...)

        Args:
            timeout: Maximum time to wait for sync (seconds)
        """
        from FactoryVerse.dsl.types import _playing_factory

        factory = _playing_factory.get()
        if factory and factory._game_data_sync and factory._game_data_sync.is_running:
            await factory._game_data_sync.ensure_synced(timeout=timeout)

    def _validate_query(self, query: str) -> None:
        """Validate that query is safe and read-only.

        Raises:
            ValueError: If query contains forbidden operations
        """
        query_upper = query.upper().strip()

        # Must be SELECT
        if not query_upper.startswith("SELECT"):
            raise ValueError("Only SELECT queries allowed")

        # No aggregations (agents should query raw data)
        forbidden_keywords = [
            "INSERT",
            "UPDATE",
            "DELETE",
            "CREATE",
            "ALTER",
            "DROP",
            "GROUP BY",
            "HAVING",
            "DISTINCT",
        ]

        for keyword in forbidden_keywords:
            if keyword in query_upper:
                raise ValueError(f"Query operation not allowed: {keyword}")

    def _row_to_dict(self, row, cursor) -> Dict[str, Any]:
        """Convert DuckDB row to entity data dict.

        Args:
            row: DuckDB query result row (tuple-like)
            cursor: DuckDB cursor with description

        Returns:
            Entity data dictionary compatible with create_entity_from_db
        """
        # DuckDB rows are tuples, get column names from cursor description
        if not cursor.description:
            raise ValueError(
                "Cursor has no description - cannot determine column names"
            )

        # Extract column names from cursor description
        # cursor.description is a list of tuples: [(name, type_code, ...), ...]
        column_names = [desc[0] for desc in cursor.description]

        # Convert row tuple to dict
        entity_data = dict(zip(column_names, row))

        return entity_data
