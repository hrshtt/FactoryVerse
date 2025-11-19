"""File watcher for monitoring snapshot file changes via UDP notifications."""

import queue
from pathlib import Path
from typing import Dict, Any, Optional

from FactoryVerse.infra.udp_dispatcher import UDPDispatcher, get_udp_dispatcher


class FileWatcher:
    """Monitors snapshot files and listens to UDP notifications for incremental updates."""
    
    def __init__(self, snapshot_dir: Path, udp_dispatcher: Optional[UDPDispatcher] = None):
        """
        Initialize the file watcher.
        
        Args:
            snapshot_dir: Path to snapshot directory (script-output/factoryverse/snapshots)
            udp_dispatcher: Optional UDPDispatcher instance. If None, uses global dispatcher.
        """
        self.snapshot_dir = Path(snapshot_dir)
        self.udp_dispatcher = udp_dispatcher
        self.running = False
        self.event_queue = queue.Queue()  # Thread-safe queue
    
    async def start(self):
        """Subscribe to UDP dispatcher for file events."""
        # Get dispatcher (use provided one or global)
        if self.udp_dispatcher is None:
            self.udp_dispatcher = get_udp_dispatcher()
        
        # Ensure dispatcher is running
        if not self.udp_dispatcher.is_running():
            await self.udp_dispatcher.start()
        
        # Subscribe to file events
        self.udp_dispatcher.subscribe("file_created", self._handle_udp_message)
        self.udp_dispatcher.subscribe("file_updated", self._handle_udp_message)
        self.udp_dispatcher.subscribe("file_deleted", self._handle_udp_message)
        
        self.running = True
        print(f"✅ FileWatcher subscribed to UDP dispatcher")
    
    def _handle_udp_message(self, payload: Dict[str, Any]):
        """Handle UDP message from dispatcher (called by dispatcher thread)."""
        event_type = payload.get('event_type')
        
        # Only process file events (safety check)
        if event_type in ('file_created', 'file_updated', 'file_deleted'):
            # Put event in thread-safe queue
            try:
                self.event_queue.put_nowait(payload)
            except queue.Full:
                print(f"⚠️  Event queue full, dropping event: {event_type}")
    
    def get_event(self, timeout: float = 0.1) -> Optional[Dict[str, Any]]:
        """Get next file event from queue (thread-safe)."""
        try:
            return self.event_queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    async def stop(self):
        """Unsubscribe from UDP dispatcher."""
        if self.udp_dispatcher and self.running:
            self.udp_dispatcher.unsubscribe("file_created", self._handle_udp_message)
            self.udp_dispatcher.unsubscribe("file_updated", self._handle_udp_message)
            self.udp_dispatcher.unsubscribe("file_deleted", self._handle_udp_message)
        
        self.running = False
        print("✅ FileWatcher stopped")

