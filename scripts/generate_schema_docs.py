#!/usr/bin/env python3
"""Generate DuckDB schema documentation for LLMs.

This script generates comprehensive schema documentation for the FactoryVerse
DuckDB database by introspecting the schema definitions module.

Usage:
    # From project root:
    uv run python scripts/generate_schema_docs.py

    # Output: docs/for-llms/schema_reference.md
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime

# Add src to path for imports
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Import schema definitions (single source of truth)
from FactoryVerse.agent.snapshot.schema_definitions import (
    CORE_TABLES,
    COMPONENT_TABLES,
    TableDefinition,
    ColumnDefinition,
)

# Forbidden SQL keywords
FORBIDDEN_KEYWORDS = [
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


# =============================================================================
# DOCUMENT SECTIONS
# =============================================================================


def generate_header() -> str:
    return f"""# FactoryVerse Schema Reference

> Auto-generated on {datetime.now().strftime("%Y-%m-%d %H:%M")}

This document describes the DuckDB database schema used for map-wide queries via `remote_view`. 
The database is read-only from the LLM's perspective - data is synchronized from the game automatically.

---

"""


def generate_query_constraints() -> str:
    return f"""## Query Constraints

### Read-Only Access

All queries must be **read-only** (`SELECT` or `WITH` for CTEs). The following SQL keywords are forbidden:

`{", ".join(FORBIDDEN_KEYWORDS)}`

### Scoped Query Methods

> [!IMPORTANT]
> Methods that return **typed objects** (`get_entities`, `get_ghosts`, `get_resources`) require queries 
> that return **full row data** - they cannot use aggregates (COUNT, SUM, GROUP BY, etc.) because 
> entity/resource objects are constructed from each row.

| Method | Returns | Aggregate Allowed? |
|--------|---------|-------------------|
| `remote_view.query(sql)` | `List[Dict[str, Any]]` | ✓ Yes |
| `remote_view.get_entities(sql)` | `List[BaseEntity]` | ✗ No |
| `remote_view.get_entity(sql)` | `Optional[BaseEntity]` | ✗ No |
| `remote_view.get_ghosts(sql)` | `List[BaseEntity]` | ✗ No |
| `remote_view.get_resources(sql)` | `List[BaseResource]` (REMOTE view) | ✗ No |
| `remote_view.count_entities(name)` | `int` | (built-in) |
| `remote_view.count_ghosts(name)` | `int` | (built-in) |

### Examples: Correct vs Incorrect Usage

```python
# ✓ CORRECT: Full row data for entity construction
drills = remote_view.get_entities(
    "SELECT * FROM map_entity WHERE entity_name = 'burner-mining-drill'"
)

# ✗ INCORRECT: Aggregates break entity construction (missing position_x, position_y, etc.)
# This will fail or return empty list
remote_view.get_entities(
    "SELECT entity_name, COUNT(*) FROM map_entity GROUP BY entity_name"
)

# ✓ CORRECT: Use query() for aggregates, returns dicts
counts = remote_view.query(
    "SELECT entity_name, COUNT(*) as cnt FROM map_entity GROUP BY entity_name"
)

# ✓ CORRECT: Use built-in count methods
drill_count = remote_view.count_entities("burner-mining-drill")
```

---

"""


def generate_return_types() -> str:
    return """## Return Types

### `BaseEntity` (from `get_entities`, `get_ghosts`)

Entities returned from remote queries have **REMOTE view** - they are read-only and cannot be mutated.

```python
class BaseEntity:
    name: str                    # Factorio entity name
    position: MapPosition        # (x, y) coordinates
    direction: Direction         # NORTH, EAST, SOUTH, WEST, etc.
    is_ghost: bool               # True if this is a ghost entity
    view: EntityView             # REMOTE (read-only) or REACHABLE (full access)
    
    # Available methods (read-only on REMOTE view):
    def inspect() -> EntityInspection  # Get current state
    async def walk_to() -> MapPosition  # Navigate to entity (entity-aware pathfinding)
    
    # Blocked on REMOTE view (must walk to entity first):
    # - add_fuel(), take_fuel()
    # - add_ingredients(), take_products()
    # - set_recipe(), rotate()
    # - pickup()
```

**IMPORTANT**: To interact with a remote entity, use `await entity.walk_to()`. After walking, the entity **automatically becomes REACHABLE** and you can use it directly - no need to get it again via `reachable.get_entity()`.

```python
# Preferred pattern:
drill = remote_view.get_entity("SELECT * FROM map_entity WHERE entity_name = 'burner-mining-drill' LIMIT 1")
await drill.walk_to()  # Automatically converts to REACHABLE
drill.add_fuel(inventory.create_item_stacks("coal", 5))  # Use directly
```

### `BaseResource` (from `get_resources`)

Resources from database queries have REMOTE view. They can be walked to and inspected, but cannot be mined directly.

```python
class BaseResource:
    name: str                    # Resource name (e.g., 'iron-ore')
    position: MapPosition        # (x, y) coordinates
    amount: int                  # Remaining amount (for ore tiles)
    view: EntityView            # REMOTE (from DB) or REACHABLE (from reachable)
    
    # Available methods (REMOTE view):
    def inspect() -> str         # Inspection string
    async def walk_to() -> MapPosition  # Navigate to resource
    
    # Blocked (REMOTE view):
    # - mine()  # Raises AttributeError - must walk to first
```

**IMPORTANT**: To mine a remote resource, use `await resource.walk_to()`. After walking, the resource **automatically becomes REACHABLE** and you can mine it directly - no need to get it again via `reachable.get_resource()`.

```python
# Preferred pattern:
iron_ore = remote_view.get_resources("SELECT * FROM resource_tile WHERE name = 'iron-ore' LIMIT 1")[0]
await iron_ore.walk_to()  # Automatically converts to REACHABLE
items = await iron_ore.mine(max_count=25)  # Use directly
```

### `Dict[str, Any]` (from `query`)

Raw query results as dictionaries with column names as keys.

```python
results = remote_view.query("SELECT entity_name, COUNT(*) as cnt FROM map_entity GROUP BY entity_name")
# results = [
#     {"entity_name": "burner-mining-drill", "cnt": 5},
#     {"entity_name": "stone-furnace", "cnt": 10},
#     ...
# ]
```

---

"""


def generate_table_reference() -> str:
    """Generate table reference documentation by introspecting schema definitions."""
    doc = "## Table Reference\n\n"

    # Main tables
    doc += "### Core Tables\n\n"
    for table in CORE_TABLES:
        doc += f"#### `{table.name}`\n\n"
        doc += f"{table.purpose}\n\n"
        doc += "| Column | Type | Description |\n"
        doc += "|--------|------|-------------|\n"
        for col in table.columns:
            doc += f"| `{col.name}` | `{col.type}` | {col.description} |\n"
        
        # Add notes if present
        if table.notes:
            doc += f"\n{table.notes}\n"
        
        # Handle multiple example queries if present
        if table.example_queries:
            doc += "\n**Examples:**\n```sql\n"
            doc += "\n".join(table.example_queries)
            doc += "\n```\n"
        elif table.example_query:
            doc += f"\n**Example:**\n```sql\n{table.example_query}\n```\n"
        doc += "\n"

    # Component tables
    doc += "### Component Tables\n\n"
    doc += (
        "These tables contain entity-specific data and are joined via foreign keys to `map_entity`.\n\n"
    )

    for table in COMPONENT_TABLES:
        doc += f"#### `{table.name}`\n\n"
        doc += f"{table.purpose}\n\n"
        doc += "| Column | Type | Description |\n"
        doc += "|--------|------|-------------|\n"
        for col in table.columns:
            doc += f"| `{col.name}` | `{col.type}` | {col.description} |\n"
        doc += "\n"

    doc += "---\n\n"
    return doc


def generate_common_queries() -> str:
    return """## Common Query Patterns

### Find Entities by Name

```python
# All drills on the map
drills = remote_view.get_entities(
    "SELECT * FROM map_entity WHERE entity_name = 'burner-mining-drill'"
)
```

### Find Entities in a Region

```python
# Entities in chunk (0, 0)
entities = remote_view.get_entities(
    "SELECT * FROM map_entity WHERE chunk_x = 0 AND chunk_y = 0"
)

# Entities within a bounding box
entities = remote_view.get_entities('''
    SELECT * FROM map_entity 
    WHERE position_x BETWEEN -50 AND 50 
    AND position_y BETWEEN -50 AND 50
''')
```

### Find Ore Deposits

```python
# Rich iron ore tiles
iron_ore = remote_view.get_resources(
    "SELECT * FROM resource_tile WHERE name = 'iron-ore' AND amount > 1000"
)

# Closest ore to a position
closest = remote_view.get_resources('''
    SELECT *, 
           sqrt(power(position_x - 0, 2) + power(position_y - 0, 2)) as distance
    FROM resource_tile 
    WHERE name = 'coal'
    ORDER BY distance
    LIMIT 1
''')
```

### Count Entities

```python
# Using built-in method
drill_count = remote_view.count_entities("burner-mining-drill")
ghost_count = remote_view.count_ghosts("stone-furnace")

# Custom aggregates via query()
counts = remote_view.query('''
    SELECT entity_name, COUNT(*) as count
    FROM map_entity
    GROUP BY entity_name
    ORDER BY count DESC
''')
```

### Find Ghosts

```python
# All pending ghosts
ghosts = remote_view.get_ghosts("SELECT * FROM ghost")

# Ghosts of a specific type
furnace_ghosts = remote_view.get_ghosts(
    "SELECT * FROM ghost WHERE ghost_name = 'stone-furnace'"
)
```

### Join Component Tables

```python
# Get drills with their mining targets
results = remote_view.query('''
    SELECT m.entity_name, m.position_x, m.position_y, d.mining_target
    FROM map_entity m
    JOIN mining_drill d ON m.entity_key = d.entity_key
''')

# Get inserters with their pickup/drop positions
results = remote_view.query('''
    SELECT m.*, i.pickup_position_x, i.pickup_position_y, 
           i.drop_position_x, i.drop_position_y
    FROM map_entity m
    JOIN inserter i ON m.entity_key = i.entity_key
''')
```

---

"""


def generate_workflow_example() -> str:
    return """## Complete Workflow Example

```python
# 1. QUERY: Find resources via database
iron_deposits = remote_view.get_resources('''
    SELECT * FROM resource_tile 
    WHERE name = 'iron-ore' 
    ORDER BY amount DESC 
    LIMIT 5
''')

# 2. NAVIGATE: Walk to the best deposit - it automatically becomes REACHABLE
target = iron_deposits[0]
await target.walk_to()  # Entity-aware pathfinding

# 3. MINE: Use it directly - no need to get it again!
items = await target.mine(max_count=50)

# 4. QUERY: Find existing infrastructure
drills = remote_view.get_entities('''
    SELECT * FROM map_entity 
    WHERE entity_name = 'burner-mining-drill'
    AND chunk_x = 0 AND chunk_y = 0
''')

# 5. NAVIGATE & INTERACT: Fuel the drills
for drill in drills:
    await drill.walk_to()  # Automatically becomes REACHABLE
    drill.add_fuel(inventory.create_item_stacks("coal", 5))  # Use directly
```

"""


def generate_document() -> str:
    sections = [
        generate_header(),
        generate_query_constraints(),
        generate_return_types(),
        generate_table_reference(),
        generate_common_queries(),
        generate_workflow_example(),
    ]
    return "\n".join(sections)


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Generate DuckDB schema documentation for LLMs"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=str(PROJECT_ROOT / "docs" / "for-llms" / "schema_reference.md"),
        help="Output file path",
    )
    args = parser.parse_args()

    doc = generate_document()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(doc)

    print(f"✅ Schema documentation written to {output_path}")
    print(f"   Size: {len(doc):,} characters")
    print(f"   Lines: {len(doc.splitlines()):,}")


if __name__ == "__main__":
    main()
