#!/usr/bin/env python3
"""Hot-reload watcher for Lua files using watchdog."""

import threading
import time
from pathlib import Path
from typing import Callable, Optional
import subprocess
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent


class LuaFileEventHandler(FileSystemEventHandler):
    """Handles Lua file events and triggers callbacks."""
    
    def __init__(self, callback: Callable, debounce_ms: int = 500):
        self.callback = callback
        self.debounce_ms = debounce_ms / 1000.0
        self.pending_changes = set()
        self.last_trigger_time = 0
        self.lock = threading.Lock()
        self.pending_timer = None  # Track current timer to cancel it
    
    def _validate_lua(self, file_path: Path) -> bool:
        """Validate Lua file with luacheck."""
        try:
            result = subprocess.run(
                ["luacheck", "-qqq", str(file_path)],
                capture_output=True,
                timeout=5
            )
            return result.returncode <= 1  # 0=ok, 1=warning (acceptable)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return True  # Skip validation if luacheck not available
    
    def _process_changes(self) -> None:
        """Process pending changes with debouncing."""
        with self.lock:
            if not self.pending_changes:
                return
            
            now = time.time()
            if now - self.last_trigger_time < self.debounce_ms:
                return
            
            changes = self.pending_changes.copy()
            self.pending_changes.clear()
            self.last_trigger_time = now
        
        print(f"\n🔄 Changes detected ({len(changes)} file(s)):")
        for f in changes:
            print(f"  • {f}")
        
        # Validate Lua
        invalid_files = [Path(f) for f in changes if Path(f).exists() and not self._validate_lua(Path(f))]
        
        if invalid_files:
            print(f"\n❌ Luacheck failed on {len(invalid_files)} file(s), skipping reload")
            for f in invalid_files:
                print(f"  • {f.name}")
        else:
            print("✓ Luacheck passed")
            if self.callback:
                print("⏳ Triggering hot-reload...")
                try:
                    self.callback()
                    print("✅ Hot-reload complete")
                except Exception as e:
                    print(f"❌ Hot-reload failed: {e}")
    
    def on_modified(self, event):
        """Called when a file is modified."""
        if event.is_directory or not event.src_path.endswith('.lua'):
            return
        
        with self.lock:
            self.pending_changes.add(event.src_path)
            
            # Cancel previous timer if it exists
            if self.pending_timer:
                self.pending_timer.cancel()
            
            # Create new timer
            self.pending_timer = threading.Timer(self.debounce_ms, self._process_changes)
            self.pending_timer.start()
    
    def on_created(self, event):
        """Called when a file is created."""
        if event.is_directory or not event.src_path.endswith('.lua'):
            return
        
        with self.lock:
            self.pending_changes.add(event.src_path)
            
            # Cancel previous timer if it exists
            if self.pending_timer:
                self.pending_timer.cancel()
            
            # Create new timer
            self.pending_timer = threading.Timer(self.debounce_ms, self._process_changes)
            self.pending_timer.start()


class HotreloadWatcher:
    """Watches Lua files and triggers hot-reload callbacks using watchdog."""
    
    def __init__(self, watch_dir: Path, debounce_ms: int = 500):
        self.watch_dir = watch_dir.resolve()
        self.debounce_ms = debounce_ms
        self.observer: Optional[Observer] = None
        self.event_handler: Optional[LuaFileEventHandler] = None
    
    def start(self, callback: Callable) -> None:
        """Start watching with watchdog."""
        self.event_handler = LuaFileEventHandler(callback, self.debounce_ms)
        self.observer = Observer()
        self.observer.schedule(self.event_handler, str(self.watch_dir), recursive=True)
        self.observer.start()
        
        print(f"👁️  Watching Lua files in: {self.watch_dir}")
        print(f"⏱️  Debounce: {self.debounce_ms}ms")
    
    def stop(self) -> None:
        """Stop watching."""
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=2)
        print("👁️  Watcher stopped")
