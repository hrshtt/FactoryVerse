"""Tests for tool validator."""

import pytest
from FactoryVerse.llm.tool_validator import ToolValidator, ValidationResult


def test_validate_valid_dsl_code():
    """Test validation of valid DSL code."""
    validator = ToolValidator()
    
    code = """
await walking.to(MapPosition(x=100, y=200))
print("Arrived")
"""
    
    result = validator.validate_dsl_code(code)
    assert result.valid
    assert result.error is None
    assert result.parsed_arguments == {"code": code}


def test_validate_invalid_syntax():
    """Test validation of code with syntax errors."""
    validator = ToolValidator()
    
    code = """
await walking.to(MapPosition(x=100, y=200)
print("Missing closing paren")
"""
    
    result = validator.validate_dsl_code(code)
    assert not result.valid
    assert "Syntax error" in result.error


def test_validate_dangerous_import():
    """Test detection of dangerous imports."""
    validator = ToolValidator()
    
    code = """
import subprocess
subprocess.call(['rm', '-rf', '/'])
"""
    
    result = validator.validate_dsl_code(code)
    assert not result.valid
    assert "Dangerous import" in result.error


def test_validate_infinite_loop_warning():
    """Test warning for potential infinite loops."""
    validator = ToolValidator()
    
    code = """
while True:
    print("Forever")
"""
    
    result = validator.validate_dsl_code(code)
    assert result.valid  # Still valid, just warning
    assert len(result.warnings) > 0
    assert "infinite loop" in result.warnings[0].lower()


def test_validate_valid_query():
    """Test validation of valid SQL query."""
    validator = ToolValidator()
    
    query = "SELECT * FROM resource_patch WHERE resource_name = 'iron-ore' LIMIT 10"
    
    result = validator.validate_duckdb_query(query)
    assert result.valid
    assert result.error is None


def test_validate_mutation_query():
    """Test rejection of mutation queries."""
    validator = ToolValidator()
    
    query = "DELETE FROM resource_patch WHERE resource_name = 'iron-ore'"
    
    result = validator.validate_duckdb_query(query)
    assert not result.valid
    assert "DELETE" in result.error


def test_validate_multiple_statements():
    """Test rejection of multiple statements."""
    validator = ToolValidator()
    
    query = "SELECT * FROM resource_patch; DROP TABLE resource_patch;"
    
    result = validator.validate_duckdb_query(query)
    assert not result.valid
    assert "Multiple statements" in result.error


def test_validate_cte_query():
    """Test validation of CTE queries."""
    validator = ToolValidator()
    
    query = """
WITH iron_patches AS (
    SELECT * FROM resource_patch WHERE resource_name = 'iron-ore'
)
SELECT * FROM iron_patches LIMIT 5
"""
    
    result = validator.validate_duckdb_query(query)
    assert result.valid


def test_validate_cross_join_warning():
    """Test warning for CROSS JOIN."""
    validator = ToolValidator()
    
    query = "SELECT * FROM resource_patch CROSS JOIN map_entity"
    
    result = validator.validate_duckdb_query(query)
    assert result.valid
    assert len(result.warnings) > 0
    assert "CROSS JOIN" in result.warnings[0]


def test_validate_tool_call_unknown_tool():
    """Test validation of unknown tool."""
    validator = ToolValidator()
    
    result = validator.validate_tool_call("unknown_tool", {})
    assert not result.valid
    assert "Unknown tool" in result.error


def test_validate_tool_call_missing_argument():
    """Test validation with missing required argument."""
    validator = ToolValidator()
    
    result = validator.validate_tool_call("execute_dsl", {})
    assert not result.valid
    assert "Missing required argument" in result.error


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
