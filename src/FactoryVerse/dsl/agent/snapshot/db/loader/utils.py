"""
Shared utilities for snapshot loading.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def normalize_snapshot_dir(path: Path) -> Path:
    """
    Normalize snapshot directory path.
    
    Handles both:
    - script-output/factoryverse/snapshots (full path)
    - script-output (will append factoryverse/snapshots)
    - snapshots (direct snapshot directory)
    
    Args:
        path: Path to normalize
        
    Returns:
        Normalized path to snapshots directory
    """
    path = Path(path)
    
    # If it's script-output root, append factoryverse/snapshots
    if path.name == "script-output":
        return path / "factoryverse" / "snapshots"
    
    # If it already ends with snapshots, use as-is
    if path.name == "snapshots":
        return path
    
    # If it contains factoryverse/snapshots, use as-is
    if "snapshots" in path.parts:
        return path
    
    # Default: assume it's script-output root
    return path / "factoryverse" / "snapshots"


def load_jsonl_file(file_path: Path) -> List[Dict[str, Any]]:
    """
    Load a JSONL file, returning list of parsed JSON objects.
    
    Args:
        file_path: Path to JSONL file
        
    Returns:
        List of parsed JSON objects
    """
    if not file_path.exists():
        return []
    out: List[Dict[str, Any]] = []
    with file_path.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # Best-effort; skip bad lines
                continue
    return out


def iter_chunk_dirs(snapshots_root: Path) -> Iterable[Tuple[int, int, Path]]:
    """
    Yield (chunk_x, chunk_y, chunk_dir) for all chunk directories.
    
    Directory structure: snapshots_root/{chunk_x}/{chunk_y}/
    
    Args:
        snapshots_root: Root directory containing chunk subdirectories
        
    Yields:
        Tuple of (chunk_x, chunk_y, chunk_dir)
    """
    if not snapshots_root.exists():
        return

    for chunk_x_dir in snapshots_root.iterdir():
        if not chunk_x_dir.is_dir():
            continue
        try:
            chunk_x = int(chunk_x_dir.name)
        except ValueError:
            continue

        for chunk_y_dir in chunk_x_dir.iterdir():
            if not chunk_y_dir.is_dir():
                continue
            try:
                chunk_y = int(chunk_y_dir.name)
            except ValueError:
                continue

            yield chunk_x, chunk_y, chunk_y_dir

