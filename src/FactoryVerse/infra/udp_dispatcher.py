"""Centralized UDP dispatcher for routing messages to multiple subscribers.

This module provides a single UDP socket listener that dispatches incoming
messages to registered subscribers based on event type. This solves the
OS limitation where only one socket can bind to a UDP port at a time.

Usage:
    dispatcher = UDPDispatcher(host="127.0.0.1", port=34202)
    await dispatcher.start()
    
    # Subscribe to specific event types
    dispatcher.subscribe("file_created", handler_function)
    dispatcher.subscribe("action_completed", handler_function)
    
    # Or subscribe to all events
    dispatcher.subscribe("*", handler_function)
"""

import json
import socket
import threading
from typing import Callable, Dict, List, Optional, Any
from collections import defaultdict


class UDPDispatcher:
    """Centralized UDP listener that dispatches messages to subscribers.
    
    Only one instance should be created per process to avoid port conflicts.
    Multiple components can subscribe to receive messages based on event_type.
    """
    
    def __init__(self, host: str = "127.0.0.1", port: int = 34202):
        """
        Initialize the UDP dispatcher.
        
        Args:
            host: Host to bind UDP socket to
            port: Port to bind UDP socket to
        """
        self.host = host
        self.port = port
        self.subscribers: Dict[str, List[Callable[[Dict[str, Any]], None]]] = defaultdict(list)
        self.sock: Optional[socket.socket] = None
        self.listener_thread: Optional[threading.Thread] = None
        self.running = False
        self._lock = threading.Lock()
    
    def subscribe(self, event_type: str, handler: Callable[[Dict[str, Any]], None]):
        """
        Subscribe to events of a specific type.
        
        Args:
            event_type: Event type to subscribe to. Can be:
                - Specific: "file_created", "file_updated", "file_deleted", "action_completed"
                - Wildcard: "*" (receives all events)
            handler: Callback function that receives the parsed JSON payload as a dict
        """
        with self._lock:
            self.subscribers[event_type].append(handler)
    
    def unsubscribe(self, event_type: str, handler: Callable[[Dict[str, Any]], None]):
        """
        Unsubscribe a handler from an event type.
        
        Args:
            event_type: Event type to unsubscribe from
            handler: Handler function to remove
        """
        with self._lock:
            if event_type in self.subscribers:
                try:
                    self.subscribers[event_type].remove(handler)
                except ValueError:
                    pass  # Handler not in list
    
    async def start(self):
        """Start the UDP listener in a background thread."""
        if self.running:
            raise RuntimeError("UDPDispatcher is already running")
        
        # Create and bind socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind((self.host, self.port))
        except OSError as e:
            self.sock.close()
            self.sock = None
            raise RuntimeError(f"Failed to bind UDP socket to {self.host}:{self.port}: {e}")
        
        self.sock.settimeout(0.5)  # Non-blocking with timeout
        self.running = True
        
        # Start listener thread
        self.listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.listener_thread.start()
        
        print(f"✅ UDPDispatcher started on {self.host}:{self.port}")
    
    def _listen_loop(self):
        """Background thread loop for receiving UDP packets."""
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65535)
                self._process_message(data, addr)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"❌ Error in UDP dispatcher listener: {e}")
    
    def _process_message(self, data: bytes, addr: tuple):
        """Parse and dispatch a UDP message to subscribers."""
        try:
            payload = json.loads(data.decode('utf-8'))
        except json.JSONDecodeError as e:
            print(f"⚠️  Failed to decode UDP JSON from {addr}: {e}")
            return
        except Exception as e:
            print(f"❌ Error processing UDP message from {addr}: {e}")
            return
        
        # Determine event type
        event_type = payload.get('event_type')
        
        # Route to subscribers
        handlers_to_call = []
        
        with self._lock:
            # Get handlers for specific event type
            if event_type:
                handlers_to_call.extend(self.subscribers.get(event_type, []))
            
            # Get wildcard handlers (subscribe to all events)
            handlers_to_call.extend(self.subscribers.get("*", []))
        
        # Call handlers (outside lock to avoid deadlocks)
        for handler in handlers_to_call:
            try:
                handler(payload)
            except Exception as e:
                print(f"⚠️  Error in UDP subscriber handler: {e}")
    
    async def stop(self):
        """Stop the UDP listener."""
        self.running = False
        
        if self.listener_thread:
            self.listener_thread.join(timeout=2)
        
        if self.sock:
            self.sock.close()
            self.sock = None
        
        with self._lock:
            self.subscribers.clear()
        
        print("✅ UDPDispatcher stopped")
    
    def is_running(self) -> bool:
        """Check if the dispatcher is running."""
        return self.running


# Global dispatcher instance (singleton pattern)
_global_dispatcher: Optional[UDPDispatcher] = None


def get_udp_dispatcher(host: str = "127.0.0.1", port: int = 34202) -> UDPDispatcher:
    """
    Get or create the global UDP dispatcher instance.
    
    This ensures only one dispatcher exists per process, preventing
    port conflicts. The dispatcher is created on first call.
    
    Args:
        host: Host to bind to (only used on first call)
        port: Port to bind to (only used on first call)
    
    Returns:
        The global UDPDispatcher instance
    """
    global _global_dispatcher
    if _global_dispatcher is None:
        _global_dispatcher = UDPDispatcher(host, port)
    return _global_dispatcher


def reset_global_dispatcher():
    """Reset the global dispatcher (useful for testing)."""
    global _global_dispatcher
    _global_dispatcher = None

