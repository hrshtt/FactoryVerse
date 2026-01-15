"""Output compression for LLM agent context management."""

import re
from dataclasses import dataclass
from typing import Literal, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class CompressedOutput:
    """Compressed output with metadata."""
    text: str  # Compressed text
    original_length: int  # Original character count
    compressed_length: int  # Compressed character count
    compression_ratio: float  # compressed_length / original_length
    strategy_used: str  # Name of compression strategy
    metadata: dict  # Additional metadata


class OutputCompressor:
    """Compress tool outputs for LLM context management."""
    
    def __init__(
        self,
        default_max_chars: int = 5000,
        default_max_rows: int = 100
    ):
        """
        Initialize compressor with default limits.
        
        Args:
            default_max_chars: Default maximum characters for output
            default_max_rows: Default maximum rows for query results
        """
        self.default_max_chars = default_max_chars
        self.default_max_rows = default_max_rows
    
    def compress_query_result(
        self,
        result: str,
        max_rows: Optional[int] = None,
        max_chars: Optional[int] = None
    ) -> CompressedOutput:
        """
        Compress DuckDB query results.
        
        Strategy:
        1. Parse tabular output
        2. Truncate to max_rows
        3. Add summary line
        4. If still over max_chars, truncate columns
        
        Args:
            result: Raw query result string
            max_rows: Maximum rows to keep (default: self.default_max_rows)
            max_chars: Maximum characters (default: self.default_max_chars)
            
        Returns:
            CompressedOutput with compressed result
        """
        max_rows = max_rows or self.default_max_rows
        max_chars = max_chars or self.default_max_chars
        original_length = len(result)
        
        # If already under limit, return as-is
        if original_length <= max_chars:
            return CompressedOutput(
                text=result,
                original_length=original_length,
                compressed_length=original_length,
                compression_ratio=1.0,
                strategy_used="no_compression",
                metadata={}
            )
        
        # Try to parse tabular output
        lines = result.strip().split('\n')
        
        # Look for row count in output (e.g., "Rows: 1247")
        row_count_match = re.search(r'Rows?:\s*(\d+)', result, re.IGNORECASE)
        total_rows = int(row_count_match.group(1)) if row_count_match else None
        
        # Look for column info
        column_match = re.search(r'Columns?:\s*(.+)', result, re.IGNORECASE)
        columns_info = column_match.group(1).strip() if column_match else None
        
        # Find table separator (usually a line with |---|---|)
        separator_idx = None
        for i, line in enumerate(lines):
            if re.match(r'^\s*\|[\s\-\|]+\|\s*$', line):
                separator_idx = i
                break
        
        if separator_idx is not None and separator_idx > 0:
            # We have a table - extract header and rows
            header_lines = lines[:separator_idx]
            data_lines = lines[separator_idx + 1:]
            
            # Truncate data rows
            if len(data_lines) > max_rows:
                truncated_data = data_lines[:max_rows]
                omitted_count = len(data_lines) - max_rows
                
                # Rebuild output
                compressed_lines = header_lines + [lines[separator_idx]] + truncated_data
                compressed_lines.append(f"\n[{omitted_count} more rows omitted]")
                
                if total_rows:
                    compressed_lines.insert(0, f"Showing {max_rows} of {total_rows} rows")
                
                compressed_text = '\n'.join(compressed_lines)
            else:
                compressed_text = result
        else:
            # Not a table format - simple truncation
            if len(result) > max_chars:
                compressed_text = result[:max_chars] + f"\n\n[... truncated {len(result) - max_chars} characters]"
            else:
                compressed_text = result
        
        # Final length check
        if len(compressed_text) > max_chars:
            compressed_text = compressed_text[:max_chars] + "\n[... output truncated]"
        
        compressed_length = len(compressed_text)
        
        return CompressedOutput(
            text=compressed_text,
            original_length=original_length,
            compressed_length=compressed_length,
            compression_ratio=compressed_length / original_length if original_length > 0 else 1.0,
            strategy_used="truncate_with_summary",
            metadata={
                "total_rows": total_rows,
                "shown_rows": max_rows if total_rows and total_rows > max_rows else total_rows,
                "columns": columns_info
            }
        )
    
    def compress_action_result(
        self,
        result: str,
        action_type: Literal["execute_dsl", "execute_duckdb"],
        max_chars: Optional[int] = None
    ) -> CompressedOutput:
        """
        Compress DSL action results.
        
        Strategy:
        1. Extract success/failure indicators
        2. Extract key metrics (counts, positions, etc.)
        3. Truncate verbose logs
        4. Preserve error messages
        
        Args:
            result: Raw action result string
            action_type: Type of action executed
            max_chars: Maximum characters (default: self.default_max_chars)
            
        Returns:
            CompressedOutput with compressed result
        """
        max_chars = max_chars or self.default_max_chars
        original_length = len(result)
        
        # If already under limit, return as-is
        if original_length <= max_chars:
            return CompressedOutput(
                text=result,
                original_length=original_length,
                compressed_length=original_length,
                compression_ratio=1.0,
                strategy_used="no_compression",
                metadata={}
            )
        
        # Extract important lines (success/error indicators)
        lines = result.split('\n')
        important_lines = []
        
        # Patterns to preserve
        preserve_patterns = [
            r'✅.*',  # Success messages
            r'❌.*',  # Error messages
            r'Error:.*',  # Error details
            r'Traceback.*',  # Stack traces (will be truncated separately)
            r'Exception.*',  # Exceptions
            r'WARNING:.*',  # Warnings
            r'Executing.*',  # Execution status
            r'completed in.*',  # Timing info
        ]
        
        for line in lines:
            if any(re.match(pattern, line, re.IGNORECASE) for pattern in preserve_patterns):
                important_lines.append(line)
        
        # If we have important lines, use those
        if important_lines:
            compressed_text = '\n'.join(important_lines)
            
            # Add summary of omitted lines
            omitted_count = len(lines) - len(important_lines)
            if omitted_count > 0:
                compressed_text += f"\n\n[{omitted_count} verbose log lines omitted]"
        else:
            # No important lines found - simple truncation
            compressed_text = result[:max_chars]
        
        # Final length check
        if len(compressed_text) > max_chars:
            compressed_text = compressed_text[:max_chars] + "\n[... output truncated]"
        
        compressed_length = len(compressed_text)
        
        return CompressedOutput(
            text=compressed_text,
            original_length=original_length,
            compressed_length=compressed_length,
            compression_ratio=compressed_length / original_length if original_length > 0 else 1.0,
            strategy_used="extract_key_facts",
            metadata={
                "important_lines_count": len(important_lines),
                "total_lines": len(lines)
            }
        )
    
    def compress_error(
        self,
        error: str,
        max_chars: int = 1000
    ) -> CompressedOutput:
        """
        Compress error messages while preserving critical info.
        
        Strategy:
        1. Always keep error type and message
        2. Truncate traceback to last 3 frames
        3. Remove duplicate frames
        4. Preserve line numbers and file names
        
        Args:
            error: Raw error string (including traceback)
            max_chars: Maximum characters
            
        Returns:
            CompressedOutput with compressed error
        """
        original_length = len(error)
        
        # If already under limit, return as-is
        if original_length <= max_chars:
            return CompressedOutput(
                text=error,
                original_length=original_length,
                compressed_length=original_length,
                compression_ratio=1.0,
                strategy_used="no_compression",
                metadata={}
            )
        
        lines = error.split('\n')
        
        # Find the actual error message (usually at the end)
        error_message_lines = []
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i]
            if line.strip():
                error_message_lines.insert(0, line)
                # Stop after we have the error type and message
                if 'Error:' in line or 'Exception:' in line:
                    break
            if len(error_message_lines) >= 3:
                break
        
        # Find traceback frames
        traceback_frames = []
        current_frame = []
        in_traceback = False
        
        for line in lines:
            if line.strip().startswith('File "'):
                if current_frame:
                    traceback_frames.append('\n'.join(current_frame))
                current_frame = [line]
                in_traceback = True
            elif in_traceback and line.strip():
                current_frame.append(line)
        
        if current_frame:
            traceback_frames.append('\n'.join(current_frame))
        
        # Keep last 3 frames
        if len(traceback_frames) > 3:
            kept_frames = traceback_frames[-3:]
            omitted_count = len(traceback_frames) - 3
            compressed_traceback = f"Traceback (most recent call last):\n  ... [{omitted_count} frames omitted]\n" + '\n'.join(kept_frames)
        else:
            compressed_traceback = '\n'.join(traceback_frames)
        
        # Combine
        compressed_text = compressed_traceback + '\n' + '\n'.join(error_message_lines)
        
        # Final length check
        if len(compressed_text) > max_chars:
            compressed_text = compressed_text[:max_chars] + "\n[... error truncated]"
        
        compressed_length = len(compressed_text)
        
        return CompressedOutput(
            text=compressed_text,
            original_length=original_length,
            compressed_length=compressed_length,
            compression_ratio=compressed_length / original_length if original_length > 0 else 1.0,
            strategy_used="truncate_traceback",
            metadata={
                "total_frames": len(traceback_frames),
                "kept_frames": min(3, len(traceback_frames))
            }
        )
