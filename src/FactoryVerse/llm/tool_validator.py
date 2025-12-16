"""Tool call validation for LLM agent."""

import ast
import re
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of tool validation."""
    valid: bool
    parsed_arguments: Optional[Dict[str, Any]]
    error: Optional[str]
    warnings: List[str]


class ToolValidator:
    """Validate tool call arguments before execution."""
    
    # Dangerous imports to block
    DANGEROUS_IMPORTS = {
        'os.system', 'subprocess', 'eval', 'exec', 
        '__import__', 'compile', 'open',  # open is allowed in DSL context but not in user code
        'execfile', 'input', 'raw_input'
    }
    
    # SQL keywords that indicate mutations
    MUTATION_KEYWORDS = {
        'INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 
        'ALTER', 'TRUNCATE', 'REPLACE', 'MERGE'
    }
    
    def __init__(
        self,
        max_code_length: int = 10000,
        max_query_length: int = 5000
    ):
        """
        Initialize validator.
        
        Args:
            max_code_length: Maximum length for DSL code
            max_query_length: Maximum length for SQL queries
        """
        self.max_code_length = max_code_length
        self.max_query_length = max_query_length
    
    def validate_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> ValidationResult:
        """
        Validate tool call arguments.
        
        Args:
            tool_name: Name of tool
            arguments: Tool arguments dict
            
        Returns:
            ValidationResult with validation status
        """
        if tool_name == "execute_dsl":
            if "code" not in arguments:
                return ValidationResult(
                    valid=False,
                    parsed_arguments=None,
                    error="Missing required argument 'code'",
                    warnings=[]
                )
            return self.validate_dsl_code(arguments["code"])
        
        elif tool_name == "execute_duckdb":
            if "query" not in arguments:
                return ValidationResult(
                    valid=False,
                    parsed_arguments=None,
                    error="Missing required argument 'query'",
                    warnings=[]
                )
            return self.validate_duckdb_query(arguments["query"])
        
        else:
            return ValidationResult(
                valid=False,
                parsed_arguments=None,
                error=f"Unknown tool: {tool_name}",
                warnings=[]
            )
    
    def validate_dsl_code(self, code: str) -> ValidationResult:
        """
        Validate DSL Python code.
        
        Checks:
        1. Valid Python syntax (ast.parse)
        2. No dangerous imports
        3. Code length limits
        4. Basic infinite loop detection
        
        Args:
            code: Python code string
            
        Returns:
            ValidationResult with validation status
        """
        warnings = []
        
        # Check length
        if len(code) > self.max_code_length:
            return ValidationResult(
                valid=False,
                parsed_arguments=None,
                error=f"Code exceeds maximum length of {self.max_code_length} characters",
                warnings=[]
            )
        
        # Check syntax
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return ValidationResult(
                valid=False,
                parsed_arguments=None,
                error=f"Syntax error: {str(e)}",
                warnings=[]
            )
        
        # Check for dangerous imports
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if any(danger in alias.name for danger in self.DANGEROUS_IMPORTS):
                        return ValidationResult(
                            valid=False,
                            parsed_arguments=None,
                            error=f"Dangerous import detected: {alias.name}",
                            warnings=[]
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.module and any(danger in node.module for danger in self.DANGEROUS_IMPORTS):
                    return ValidationResult(
                        valid=False,
                        parsed_arguments=None,
                        error=f"Dangerous import detected: {node.module}",
                        warnings=[]
                    )
        
        # Basic infinite loop detection (heuristic)
        # Check for while True without break
        for node in ast.walk(tree):
            if isinstance(node, ast.While):
                # Check if condition is constant True
                if isinstance(node.test, ast.Constant) and node.test.value is True:
                    # Check if there's a break statement
                    has_break = any(
                        isinstance(n, ast.Break) 
                        for n in ast.walk(node)
                    )
                    if not has_break:
                        warnings.append("Potential infinite loop detected (while True without break)")
        
        return ValidationResult(
            valid=True,
            parsed_arguments={"code": code},
            error=None,
            warnings=warnings
        )
    
    def validate_duckdb_query(self, query: str) -> ValidationResult:
        """
        Validate DuckDB SQL query.
        
        Checks:
        1. Query is SELECT only (no mutations)
        2. No multiple statements
        3. Query length limits
        4. Basic SQL syntax validation
        
        Args:
            query: SQL query string
            
        Returns:
            ValidationResult with validation status
        """
        warnings = []
        
        # Check length
        if len(query) > self.max_query_length:
            return ValidationResult(
                valid=False,
                parsed_arguments=None,
                error=f"Query exceeds maximum length of {self.max_query_length} characters",
                warnings=[]
            )
        
        # Normalize query for checking
        query_upper = query.upper().strip()
        
        # Remove trailing semicolon if present
        if query_upper.endswith(';'):
            query_upper = query_upper[:-1].strip()
        
        # Check for multiple statements (semicolons in the middle)
        if ';' in query_upper:
            return ValidationResult(
                valid=False,
                parsed_arguments=None,
                error="Multiple statements detected. Only single SELECT queries are allowed.",
                warnings=[]
            )
        
        # Check for mutation keywords
        for keyword in self.MUTATION_KEYWORDS:
            # Use word boundaries to avoid false positives
            pattern = r'\b' + keyword + r'\b'
            if re.search(pattern, query_upper):
                return ValidationResult(
                    valid=False,
                    parsed_arguments=None,
                    error=f"Mutation operation detected: {keyword}. Only SELECT queries are allowed.",
                    warnings=[]
                )
        
        # Check that query starts with SELECT (or WITH for CTEs)
        if not (query_upper.startswith('SELECT') or query_upper.startswith('WITH')):
            return ValidationResult(
                valid=False,
                parsed_arguments=None,
                error="Query must start with SELECT or WITH (for CTEs)",
                warnings=[]
            )
        
        # Warn about potentially expensive operations
        if 'CROSS JOIN' in query_upper:
            warnings.append("CROSS JOIN detected - may be expensive")
        
        if query_upper.count('JOIN') > 5:
            warnings.append(f"Many JOINs detected ({query_upper.count('JOIN')}) - may be slow")
        
        return ValidationResult(
            valid=True,
            parsed_arguments={"query": query},
            error=None,
            warnings=warnings
        )
