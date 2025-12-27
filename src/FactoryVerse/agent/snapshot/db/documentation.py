"""DuckDB schema documentation for generating schema summaries.

Generates lean, precise documentation of DuckDB schemas for LLM agents:
- Custom types (ENUMs, STRUCTs)
- Table schemas with columns and types
- Indexes and relationships
- Foreign key constraints

Output is formatted for easy LLM consumption with enum summarization to avoid verbosity.
"""

from typing import Dict, List, Any, Optional, Tuple
import duckdb


def _format_enum_type(enum_name: str, values: List[str], max_samples: int = 10) -> str:
    """Format enum type with sample values to avoid verbosity.
    
    Args:
        enum_name: Name of the enum type
        values: List of enum values
        max_samples: Maximum number of sample values to show
        
    Returns:
        Formatted enum string with samples and total count
    """
    if len(values) <= max_samples:
        # Show all values if under threshold
        values_str = ", ".join(values)
        return f"{enum_name}: {values_str} ({len(values)} total)"
    else:
        # Show sample + count
        samples = ", ".join(values[:max_samples])
        return f"{enum_name}: {samples}, ... ({len(values)} total)"


def _format_struct_type(struct_name: str, fields: Dict[str, str]) -> str:
    """Format struct type definition.
    
    Args:
        struct_name: Name of the struct type
        fields: Dictionary mapping field names to types
        
    Returns:
        Formatted struct string
    """
    fields_str = ", ".join(f"{name} {typ}" for name, typ in fields.items())
    return f"{struct_name}: STRUCT({fields_str})"


def _simplify_type(type_str: str) -> str:
    """Simplify type representation by removing verbose enum value lists.
    
    Args:
        type_str: Type string from information_schema (may contain full ENUM definition)
        
    Returns:
        Simplified type string (e.g., "ENUM" instead of "ENUM('val1', 'val2', ...)")
    """
    # If it's an ENUM with values listed, just show "ENUM"
    if type_str.startswith("ENUM("):
        return "ENUM"
    return type_str


def extract_custom_types(con: duckdb.DuckDBPyConnection) -> Dict[str, Any]:
    """Extract ENUM and STRUCT types from the database.
    
    Args:
        con: DuckDB connection
        
    Returns:
        Dictionary with 'enums' and 'structs' keys containing type information
    """
    result = {"enums": {}, "structs": {}}
    
    try:
        # Get all custom types
        types_query = """
            SELECT type_name, type_category, logical_type
            FROM duckdb_types()
            WHERE database_name = 'memory' OR database_name = current_database()
        """
        types_result = con.execute(types_query).fetchall()
        
        for type_name, type_category, logical_type in types_result:
            # Skip built-in types
            if type_name.upper() in ('BIGINT', 'BOOLEAN', 'BLOB', 'DATE', 'DOUBLE', 'FLOAT', 
                            'HUGEINT', 'INTEGER', 'INTERVAL', 'SMALLINT', 'TIME', 
                            'TIMESTAMP', 'TINYINT', 'UBIGINT', 'UHUGEINT', 'UINTEGER', 
                            'USMALLINT', 'UTINYINT', 'UUID', 'VARCHAR', 'GEOMETRY',
                            'POINT_2D', 'LINESTRING_2D', 'POLYGON_2D', 'BIGNUM', 'BINARY',
                            'BIT', 'BITSTRING', 'BPCHAR', 'BYTEA', 'CHAR', 'DATETIME',
                            'DEC', 'DECIMAL', 'ENUM', 'FLOAT4', 'FLOAT8', 'INT', 'INT1',
                            'INT2', 'INT4', 'INT8', 'LOGICAL', 'LONG', 'NUMERIC', 'REAL',
                            'SHORT', 'SIGNED', 'STRING', 'TEXT', 'VARBINARY'):
                continue
            
            # Check if it's an ENUM (logical_type is 'ENUM' for custom enums)
            if logical_type == 'ENUM':
                # Get enum values
                try:
                    enum_values_query = f"SELECT unnest(enum_range(NULL::{type_name}))"
                    enum_values = [row[0] for row in con.execute(enum_values_query).fetchall()]
                    result["enums"][type_name] = enum_values
                except Exception as e:
                    # If we can't get values, skip this enum
                    pass
            
            # Check if it's a STRUCT (type_category is 'COMPOSITE' or logical_type contains 'STRUCT')
            elif type_category == 'COMPOSITE' or 'STRUCT' in logical_type.upper():
                # Get struct fields by querying the type directly
                try:
                    # Use DESCRIBE to get struct fields
                    describe_query = f"DESCRIBE SELECT NULL::{type_name} as col"
                    describe_result = con.execute(describe_query).fetchone()
                    if describe_result:
                        # Parse the column type which will be like "STRUCT(x DOUBLE, y DOUBLE)"
                        col_type = describe_result[1]  # column_type is second field
                        if 'STRUCT' in col_type.upper():
                            # Extract field definitions
                            fields_str = col_type[col_type.index('(')+1:col_type.rindex(')')]
                            fields = {}
                            # Handle quoted field names
                            import re
                            # Match either "field_name" TYPE or field_name TYPE
                            field_pattern = r'(?:"([^"]+)"|(\w+))\s+([A-Z][A-Z0-9_()]+(?:\([^)]+\))?)'
                            for match in re.finditer(field_pattern, fields_str):
                                field_name = match.group(1) or match.group(2)
                                field_type = match.group(3)
                                fields[field_name] = field_type
                            if fields:
                                result["structs"][type_name] = fields
                except Exception as e:
                    # If we can't parse the struct, skip it
                    pass
    
    except Exception as e:
        # If introspection fails, return empty result
        pass
    
    return result


def extract_table_schemas(con: duckdb.DuckDBPyConnection) -> Dict[str, List[Dict[str, Any]]]:
    """Extract all table schemas with column information.
    
    Args:
        con: DuckDB connection
        
    Returns:
        Dictionary mapping table names to lists of column definitions
    """
    tables = {}
    
    try:
        # Get all tables
        tables_query = """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'main' AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """
        table_names = [row[0] for row in con.execute(tables_query).fetchall()]
        
        for table_name in table_names:
            # Get column information
            columns_query = f"""
                SELECT 
                    column_name,
                    data_type,
                    is_nullable,
                    column_default
                FROM information_schema.columns
                WHERE table_name = '{table_name}'
                ORDER BY ordinal_position
            """
            columns = []
            for col_name, data_type, is_nullable, col_default in con.execute(columns_query).fetchall():
                col_info = {
                    "name": col_name,
                    "type": _simplify_type(data_type),  # Simplify enum types
                    "nullable": is_nullable == "YES",
                    "default": col_default
                }
                columns.append(col_info)
            
            tables[table_name] = columns
    
    except Exception as e:
        pass
    
    return tables


def extract_indexes(con: duckdb.DuckDBPyConnection) -> Dict[str, List[str]]:
    """Extract index information for all tables.
    
    Args:
        con: DuckDB connection
        
    Returns:
        Dictionary mapping table names to lists of index descriptions
    """
    indexes = {}
    
    try:
        # DuckDB doesn't have a standard information_schema for indexes
        # We'll use duckdb_indexes() if available
        indexes_query = """
            SELECT 
                table_name,
                index_name,
                sql
            FROM duckdb_indexes()
            WHERE database_name = 'memory' OR database_name = current_database()
            ORDER BY table_name, index_name
        """
        
        for table_name, index_name, sql in con.execute(indexes_query).fetchall():
            if table_name not in indexes:
                indexes[table_name] = []
            
            # Extract indexed columns from SQL if possible
            # Format is typically: CREATE INDEX idx_name ON table(columns) USING method
            index_desc = index_name
            if 'USING RTREE' in sql.upper():
                index_desc += " (RTREE spatial index)"
            
            indexes[table_name].append(index_desc)
    
    except Exception as e:
        pass
    
    return indexes


def _get_table_relationships(con: duckdb.DuckDBPyConnection) -> Dict[str, List[str]]:
    """Extract foreign key relationships.
    
    Args:
        con: DuckDB connection
        
    Returns:
        Dictionary mapping table names to lists of foreign key descriptions
    """
    relationships = {}
    
    try:
        # Get foreign key constraints
        fk_query = """
            SELECT 
                kcu.table_name,
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.key_column_usage AS kcu
            JOIN information_schema.constraint_column_usage AS ccu
                ON kcu.constraint_name = ccu.constraint_name
            WHERE kcu.constraint_name LIKE '%fkey%'
            ORDER BY kcu.table_name
        """
        
        for table_name, column_name, foreign_table, foreign_column in con.execute(fk_query).fetchall():
            if table_name not in relationships:
                relationships[table_name] = []
            
            fk_desc = f"{column_name} -> {foreign_table}({foreign_column})"
            relationships[table_name].append(fk_desc)
    
    except Exception as e:
        pass
    
    return relationships


def generate_schema_doc(con: duckdb.DuckDBPyConnection, include_enum_details: bool = False) -> str:
    """Generate complete DuckDB schema documentation.
    
    Args:
        con: DuckDB connection
        include_enum_details: If True, show all enum values; if False, use sample-based summary
        
    Returns:
        Formatted schema documentation string
    """
    output = []
    
    # Extract schema information
    custom_types = extract_custom_types(con)
    tables = extract_table_schemas(con)
    indexes = extract_indexes(con)
    relationships = _get_table_relationships(con)
    
    # Custom Types Section
    output.append("=== CUSTOM TYPES ===\n")
    
    # ENUMs - Only show type names and counts, not values
    if custom_types["enums"]:
        output.append("ENUMS:")
        for enum_name, values in sorted(custom_types["enums"].items()):
            # Always show just the count, never the values
            output.append(f"  {enum_name} ({len(values)} values)")
        output.append("")
    
    # STRUCTs
    if custom_types["structs"]:
        output.append("STRUCTS:")
        for struct_name, fields in sorted(custom_types["structs"].items()):
            output.append(f"  {_format_struct_type(struct_name, fields)}")
        output.append("")
    
    # Tables Section
    output.append("=== TABLES ===\n")
    
    for table_name, columns in sorted(tables.items()):
        output.append(f"{table_name}:")
        
        # Show columns
        for col in columns:
            constraints = []
            
            # Check for primary key (heuristic: entity_key, patch_id, etc.)
            if col["name"] in ("entity_key", "patch_id", "line_id", "segment_id"):
                constraints.append("PRIMARY KEY")
            
            if not col["nullable"]:
                constraints.append("NOT NULL")
            
            if col["default"]:
                constraints.append(f"DEFAULT {col['default']}")
            
            constraints_str = f" ({', '.join(constraints)})" if constraints else ""
            output.append(f"  {col['name']}: {col['type']}{constraints_str}")
        
        # Show indexes if any
        if table_name in indexes:
            output.append(f"  Indexes: {', '.join(indexes[table_name])}")
        
        # Show foreign keys if any
        if table_name in relationships:
            output.append(f"  Foreign Keys: {', '.join(relationships[table_name])}")
        
        output.append("")
    
    return "\n".join(output)


__all__ = [
    "extract_custom_types",
    "extract_table_schemas",
    "extract_indexes",
    "generate_schema_doc",
]
