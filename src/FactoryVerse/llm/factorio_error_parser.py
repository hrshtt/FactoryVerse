"""Tunable error parser for Factorio validation errors.

This module provides configurable error parsing for Factorio Lua errors,
allowing control over traceback verbosity for LLM consumption.
"""

import re
from enum import Enum
from typing import List, Optional, Tuple
from dataclasses import dataclass


class ErrorVerbosity(Enum):
    """Verbosity levels for error output."""
    MINIMAL = "minimal"      # Just the error message, no traceback
    MODERATE = "moderate"    # Error message + limited traceback frames
    FULL = "full"           # Complete traceback with all frames


@dataclass
class ParsedError:
    """Structured representation of a parsed error."""
    error_type: str          # e.g., "LuaError", "ValidationError", "PythonError"
    error_message: str       # The main error message
    traceback_frames: List[str]  # List of traceback frame strings
    original_error: str      # The original unparsed error
    is_factorio_error: bool  # Whether this is a Factorio/Lua error


class FactorioErrorParser:
    """Parser for Factorio validation and Lua errors with tunable verbosity.
    
    This parser handles errors from Factorio's Lua runtime and formats them
    appropriately for LLM consumption, with configurable verbosity levels.
    """
    
    # Patterns for identifying Factorio/Lua errors
    LUA_ERROR_PATTERNS = [
        r"__.*?__/control\.lua:\d+:",  # Factorio mod control.lua errors
        r"stack traceback:",            # Lua stack traceback marker
        r"Error while running event",  # Factorio event errors
        r"attempt to \w+ a nil value", # Common Lua nil errors
        r"bad argument #\d+",          # Lua argument errors
    ]
    
    # Patterns for internal Factorio frames to filter out
    INTERNAL_FRAME_PATTERNS = [
        r"__core__/",
        r"__base__/",
        r"/lualib/",
    ]
    
    def __init__(
        self,
        verbosity: ErrorVerbosity = ErrorVerbosity.MODERATE,
        max_traceback_frames: int = 2,
        show_internal_frames: bool = False,
        highlight_user_code: bool = True,
        include_frame_numbers: bool = True,
    ):
        """Initialize the error parser.
        
        Args:
            verbosity: Level of detail in error output
            max_traceback_frames: Maximum number of traceback frames to show (for MODERATE)
            show_internal_frames: Whether to show internal Factorio frames
            highlight_user_code: Whether to add markers for user code vs system code
            include_frame_numbers: Whether to include frame numbers in output
        """
        self.verbosity = verbosity
        self.max_traceback_frames = max_traceback_frames
        self.show_internal_frames = show_internal_frames
        self.highlight_user_code = highlight_user_code
        self.include_frame_numbers = include_frame_numbers
    
    def parse_error(self, error_text: str) -> ParsedError:
        """Parse an error string into structured components.
        
        Args:
            error_text: Raw error text from execution
            
        Returns:
            ParsedError object with structured error information
        """
        # Detect if this is a Factorio/Lua error
        is_factorio_error = self._is_factorio_error(error_text)
        
        if is_factorio_error:
            return self._parse_lua_error(error_text)
        else:
            return self._parse_python_error(error_text)
    
    def format_error(self, parsed_error: ParsedError) -> str:
        """Format a parsed error according to verbosity settings.
        
        Args:
            parsed_error: Structured error information
            
        Returns:
            Formatted error string for LLM consumption
        """
        if self.verbosity == ErrorVerbosity.MINIMAL:
            return self._format_minimal(parsed_error)
        elif self.verbosity == ErrorVerbosity.MODERATE:
            return self._format_moderate(parsed_error)
        else:  # FULL
            return self._format_full(parsed_error)
    
    def parse_and_format(self, error_text: str) -> str:
        """Convenience method to parse and format in one call.
        
        Args:
            error_text: Raw error text
            
        Returns:
            Formatted error string
        """
        parsed = self.parse_error(error_text)
        return self.format_error(parsed)
    
    def _is_factorio_error(self, error_text: str) -> bool:
        """Check if error text contains Factorio/Lua error patterns."""
        return any(re.search(pattern, error_text, re.IGNORECASE) 
                   for pattern in self.LUA_ERROR_PATTERNS)
    
    def _parse_lua_error(self, error_text: str) -> ParsedError:
        """Parse a Lua/Factorio error."""
        lines = error_text.split('\n')
        
        # Find the main error message (usually first non-empty line or before "stack traceback:")
        error_message = ""
        traceback_frames = []
        in_traceback = False
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            
            if not line_stripped:
                continue
            
            # Check for stack traceback marker
            if "stack traceback:" in line_stripped.lower():
                in_traceback = True
                # Error message is everything before this
                if not error_message:
                    error_message = '\n'.join(lines[:i]).strip()
                continue
            
            if in_traceback:
                # This is a traceback frame
                if line_stripped:
                    traceback_frames.append(line.rstrip())
            elif not error_message and ("error" in line_stripped.lower() or ":" in line_stripped):
                # Potential error message line
                error_message = line_stripped
        
        # If we didn't find a clear error message, use the first line
        if not error_message:
            error_message = lines[0].strip() if lines else "Unknown error"
        
        # Determine error type
        error_type = "LuaError"
        if "validation" in error_message.lower():
            error_type = "ValidationError"
        elif "event" in error_message.lower():
            error_type = "EventError"
        
        return ParsedError(
            error_type=error_type,
            error_message=error_message,
            traceback_frames=traceback_frames,
            original_error=error_text,
            is_factorio_error=True
        )
    
    def _parse_python_error(self, error_text: str) -> ParsedError:
        """Parse a Python error."""
        lines = error_text.split('\n')
        
        # Python errors typically have "Traceback (most recent call last):" 
        # followed by frames, then the error message at the end
        traceback_frames = []
        error_message = ""
        in_traceback = False
        
        for line in lines:
            line_stripped = line.strip()
            
            if "Traceback" in line and "most recent call last" in line:
                in_traceback = True
                continue
            
            if in_traceback:
                if line_stripped and (line.startswith('  ') or line.startswith('File')):
                    # This is a traceback frame
                    traceback_frames.append(line.rstrip())
                elif line_stripped and not line.startswith(' '):
                    # This is the error message (no leading whitespace)
                    error_message = line_stripped
                    in_traceback = False
        
        # If no error message found, use last non-empty line
        if not error_message:
            for line in reversed(lines):
                if line.strip():
                    error_message = line.strip()
                    break
        
        # Determine error type from message
        error_type = "PythonError"
        if ":" in error_message:
            error_type = error_message.split(":")[0].strip()
        
        return ParsedError(
            error_type=error_type,
            error_message=error_message,
            traceback_frames=traceback_frames,
            original_error=error_text,
            is_factorio_error=False
        )
    
    def _filter_frames(self, frames: List[str]) -> List[str]:
        """Filter traceback frames based on settings."""
        if self.show_internal_frames:
            return frames
        
        # Filter out internal Factorio frames
        filtered = []
        for frame in frames:
            is_internal = any(re.search(pattern, frame) 
                            for pattern in self.INTERNAL_FRAME_PATTERNS)
            if not is_internal:
                filtered.append(frame)
        
        return filtered
    
    def _format_minimal(self, parsed_error: ParsedError) -> str:
        """Format error with minimal verbosity (message only)."""
        return f"❌ {parsed_error.error_type}: {parsed_error.error_message}"
    
    def _format_moderate(self, parsed_error: ParsedError) -> str:
        """Format error with moderate verbosity (message + limited frames)."""
        result = [f"❌ {parsed_error.error_type}: {parsed_error.error_message}"]
        
        # Filter and limit frames
        frames = self._filter_frames(parsed_error.traceback_frames)
        
        if frames:
            # Take the most relevant frames (last N frames, which are closest to error)
            relevant_frames = frames[-self.max_traceback_frames:]
            
            if len(frames) > self.max_traceback_frames:
                omitted = len(frames) - self.max_traceback_frames
                result.append(f"\nTraceback (last {self.max_traceback_frames} of {len(frames)} frames):")
                result.append(f"  ... [{omitted} frames omitted]")
            else:
                result.append("\nTraceback:")
            
            for i, frame in enumerate(relevant_frames, 1):
                if self.include_frame_numbers:
                    result.append(f"  {i}. {frame.strip()}")
                else:
                    result.append(f"  {frame.strip()}")
        
        return '\n'.join(result)
    
    def _format_full(self, parsed_error: ParsedError) -> str:
        """Format error with full verbosity (complete traceback)."""
        result = [f"❌ {parsed_error.error_type}: {parsed_error.error_message}"]
        
        frames = self._filter_frames(parsed_error.traceback_frames)
        
        if frames:
            result.append("\nFull Traceback:")
            for i, frame in enumerate(frames, 1):
                if self.include_frame_numbers:
                    result.append(f"  {i}. {frame.strip()}")
                else:
                    result.append(f"  {frame.strip()}")
        
        return '\n'.join(result)
