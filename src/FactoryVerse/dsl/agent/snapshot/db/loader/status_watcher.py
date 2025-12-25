"""
Status file watcher for real-time status updates.

Watches for new status files and automatically loads them into DuckDB.
Can be used with file watcher or polling.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional, Callable

import duckdb

from .status_loader import load_latest_status, get_latest_status_file, StatusSubscriber


class StatusWatcher:
    """
    Watches for new status files and loads them automatically.
    Can be used with file system watcher or polling.
    """
    
    def __init__(
        self,
        con: duckdb.DuckDBPyConnection,
        status_dir: Path,
        on_update: Optional[Callable[[int], None]] = None,
    ):
        """
        Initialize status watcher.
        
        Args:
            con: DuckDB connection
            status_dir: Path to status directory
            on_update: Optional callback when new status is loaded (receives tick)
        """
        self.con = con
        self.status_dir = Path(status_dir)
        self.on_update = on_update
        self.last_tick: int = 0
        self.subscribers: list[StatusSubscriber] = []
    
    def add_subscriber(self, subscriber: StatusSubscriber) -> None:
        """Add a status subscriber."""
        self.subscribers.append(subscriber)
    
    def check_for_updates(self) -> bool:
        """
        Check for new status file and load if available.
        
        Returns:
            True if new status was loaded, False otherwise
        """
        result = get_latest_status_file(self.status_dir)
        if not result:
            return False
        
        latest_file, tick = result
        
        # Only load if it's newer than what we've seen
        if tick <= self.last_tick:
            return False
        
        # Load the new status
        count = load_latest_status(self.con, self.status_dir)
        if count > 0:
            self.last_tick = tick
            
            # Notify callback
            if self.on_update:
                self.on_update(tick)
            
            # Notify subscribers
            for subscriber in self.subscribers:
                subscriber.get_updates()
            
            return True
        
        return False
    
    def poll(self, interval: float = 1.0, stop_event: Optional[Callable[[], bool]] = None) -> None:
        """
        Poll for status updates continuously.
        
        Args:
            interval: Polling interval in seconds
            stop_event: Optional callable that returns True to stop polling
        """
        while True:
            if stop_event and stop_event():
                break
            
            self.check_for_updates()
            time.sleep(interval)


def watch_status_files(
    con: duckdb.DuckDBPyConnection,
    status_dir: Path,
    on_update: Optional[Callable[[int], None]] = None,
) -> StatusWatcher:
    """
    Create a status watcher for real-time status monitoring.
    
    Args:
        con: DuckDB connection
        status_dir: Path to status directory
        on_update: Optional callback when new status is loaded
    
    Returns:
        StatusWatcher instance
    """
    return StatusWatcher(con, status_dir, on_update)


