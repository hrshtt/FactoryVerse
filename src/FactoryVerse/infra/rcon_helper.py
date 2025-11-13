"""Enhanced RCON helper with async/sync action support and UDP completion handling."""

import json
import asyncio
import time
from typing import Optional, Dict, Any

from FactoryVerse.infra.udp_dispatcher import UDPDispatcher, get_udp_dispatcher


class AsyncActionListener:
    """UDP listener for async action completion events."""
    
    def __init__(self, udp_dispatcher: Optional[UDPDispatcher] = None, timeout: int = 30):
        """
        Initialize the UDP listener.
        
        Args:
            udp_dispatcher: Optional UDPDispatcher instance. If None, uses global dispatcher.
            timeout: Default timeout in seconds for waiting on actions
        """
        self.udp_dispatcher = udp_dispatcher
        self.timeout = timeout
        self.pending_actions: Dict[str, asyncio.Event] = {}
        self.action_results: Dict[str, Dict[str, Any]] = {}
        self.event_loops: Dict[str, asyncio.AbstractEventLoop] = {}  # Store event loop for each action
        self.running = False
        
    async def start(self):
        """Subscribe to UDP dispatcher for action completion events."""
        # Get dispatcher (use provided one or global)
        if self.udp_dispatcher is None:
            self.udp_dispatcher = get_udp_dispatcher()
        
        # Ensure dispatcher is running
        if not self.udp_dispatcher.is_running():
            await self.udp_dispatcher.start()
        
        # Subscribe to action completion events (messages with action_id)
        # We use "*" to receive all events and filter by action_id in handler
        self.udp_dispatcher.subscribe("*", self._handle_udp_message)
        
        self.running = True
        print(f"✅ AsyncActionListener subscribed to UDP dispatcher")
    
    def _handle_udp_message(self, payload: Dict[str, Any]):
        """Process received UDP message from dispatcher (called by dispatcher thread)."""
        process_start = time.time()
        
        try:
            action_id = payload.get('action_id')
            
            # Only process action completion events (have action_id)
            if not action_id:
                return  # Not an action completion event, ignore
            
            # Direct lookup by action_id
            if action_id not in self.pending_actions:
                print(f"⚠️  Received completion for unregistered action: {action_id}")
                return
            
            # Store result and signal completion (thread-safe)
            self.action_results[action_id] = payload
            event = self.pending_actions[action_id]
            
            # Use the stored event loop to safely signal from background thread
            loop = self.event_loops.get(action_id)
            if loop and loop.is_running():
                loop.call_soon_threadsafe(event.set)
            else:
                # Fallback if no loop or loop not running
                event.set()
            
            rcon_tick = payload.get('rcon_tick')
            completion_tick = payload.get('completion_tick')
            elapsed_ticks = (completion_tick - rcon_tick) if (rcon_tick and completion_tick) else None
            
            # Measure processing time
            process_time_ms = (time.time() - process_start) * 1000
            
            elapsed_str = f" ({elapsed_ticks} ticks)" if elapsed_ticks else ""
            print(f"✅ {payload.get('action_type', 'action')} completed{elapsed_str}: {action_id} [processed in {process_time_ms:.2f}ms]")
            
        except Exception as e:
            process_time_ms = (time.time() - process_start) * 1000
            print(f"❌ Error processing UDP message: {e} [{process_time_ms:.2f}ms]")
    
    async def stop(self):
        """Unsubscribe from UDP dispatcher."""
        if self.udp_dispatcher and self.running:
            self.udp_dispatcher.unsubscribe("*", self._handle_udp_message)
        
        self.running = False
        print("✅ AsyncActionListener stopped")
    
    def register_action(self, action_id: str):
        """Register an action to wait for completion via UDP."""
        event = asyncio.Event()
        self.pending_actions[action_id] = event
        self.action_results[action_id] = None
        # Capture the running event loop (important for Jupyter and other async contexts)
        try:
            self.event_loops[action_id] = asyncio.get_running_loop()
        except RuntimeError:
            self.event_loops[action_id] = None
    
    async def wait_for_action(self, action_id: str, timeout: Optional[int] = None) -> Dict[str, Any]:
        """
        Wait for an action to complete via UDP.
        
        Args:
            action_id: The action ID to wait for
            timeout: Optional timeout override in seconds
            
        Returns:
            The action completion payload
            
        Raises:
            TimeoutError: If action doesn't complete within timeout
            ValueError: If action_id not registered
        """
        if action_id not in self.pending_actions:
            raise ValueError(f"Action not registered: {action_id}")
        
        event = self.pending_actions[action_id]
        timeout_secs = timeout or self.timeout
        wait_start = time.time()
        
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout_secs)
            wait_time_ms = (time.time() - wait_start) * 1000
            result = self.action_results[action_id]
            print(f"   → Waited {wait_time_ms:.1f}ms for UDP")
            return result
        except asyncio.TimeoutError:
            print(f"❌ Action timeout: {action_id} (waited {timeout_secs}s)")
            raise
        finally:
            # Cleanup
            self.pending_actions.pop(action_id, None)
            self.action_results.pop(action_id, None)
            self.event_loops.pop(action_id, None)


class RconHelper:
    """Enhanced RCON helper with async/sync action support."""
    
    def __init__(self, rcon_client, udp_listener: Optional[AsyncActionListener] = None):
        """
        Initialize the RCON helper.
        
        Args:
            rcon_client: factorio_rcon.RCONClient instance
            udp_listener: Optional AsyncActionListener for handling async action completions
                         (default: AsyncActionListener on port 34202)
        """
        self.rcon_client = rcon_client
        self.udp_listener = udp_listener
        self.interfaces = None
        self.action_metadata = None
        self._fetch_metadata()
    
    def _fetch_metadata(self):
        """Fetch interfaces and action metadata from Lua."""
        try:
            # Fetch remote interfaces to validate connection
            interfaces_cmd = "/c rcon.print(helpers.table_to_json(remote.interfaces))"
            interfaces_json = self.rcon_client.send_command(interfaces_cmd)
            self.interfaces = json.loads(interfaces_json)
            print(f"✅ Loaded remote interfaces: {list(self.interfaces.keys())}")
            
            # Fetch action metadata (sync vs async classification)
            metadata_cmd = "/c rcon.print(helpers.table_to_json(remote.call('metadata', 'get_action_metadata')))"
            metadata_json = self.rcon_client.send_command(metadata_cmd)
            self.action_metadata = json.loads(metadata_json)
            print(f"✅ Loaded action metadata: {len(self.action_metadata)} actions classified")
        except Exception as e:
            print(f"❌ Error fetching metadata: {e}")
            raise
    
    def get_cmd(self, category: str, method: str, args: Dict[str, Any]) -> str:
        """
        Generate unsafe RCON command (no error handling).
        
        Args:
            category: Remote interface category
            method: Method name
            args: Arguments dict
            
        Returns:
            RCON command string
        """
        assert category in self.interfaces, f"Unknown category: {category}"
        assert method in self.interfaces[category], f"Unknown method: {category}.{method}"
        assert isinstance(args, dict), "Args must be a dict"
        
        remote_call = f"remote.call('{category}', '{method}', '{json.dumps(args)}')"
        return f"/c rcon.print(helpers.table_to_json({remote_call}))"
    
    def get_safe_cmd(self, category: str, method: str, args: Dict[str, Any]) -> str:
        """
        Generate safe RCON command with error handling.
        
        Args:
            category: Remote interface category
            method: Method name
            args: Arguments dict
            
        Returns:
            RCON command string
        """
        assert category in self.interfaces, f"Unknown category: {category}"
        assert method in self.interfaces[category], f"Unknown method: {category}.{method}"
        assert isinstance(args, dict), "Args must be a dict"
        
        remote_call = f"remote.call('{category}', '{method}', '{json.dumps(args)}')"
        xpcall = f"local success, result = xpcall(function() return {remote_call} end, debug.traceback)"
        handler = "if success then rcon.print(helpers.table_to_json({success = true, result = result})) else rcon.print(helpers.table_to_json({success = false, error = result})) end"
        return f"/c {xpcall} {handler}"
    
    def run(self, category: str, method: str, args: Dict[str, Any], safe: bool = True, verbose: bool = True) -> Dict[str, Any]:
        """
        Execute a synchronous action and return result.
        
        NOTE: For async actions, use run_async() instead to properly await completion.
        
        Args:
            category: Remote interface category
            method: Method name
            args: Arguments dict
            safe: Whether to use error handling
            verbose: Whether to print the command
            
        Returns:
            Response dict
            
        Raises:
            Exception: If remote call fails (when safe=True)
        """
        cmd = self.get_safe_cmd(category, method, args) if safe else self.get_cmd(category, method, args)
        
        if verbose:
            print(f"→ {cmd}")
        
        response = self.rcon_client.send_command(cmd)
        result = json.loads(response)
        
        # Handle structured response from safe mode
        if safe and isinstance(result, dict):
            if result.get('success') == False:
                raise Exception(f"Remote call failed: {result.get('error')}")
            return result.get('result')
        
        return result
    
    async def run_async(self, category: str, method: str, args: Dict[str, Any], 
                       safe: bool = True, verbose: bool = True, timeout: Optional[int] = None) -> Dict[str, Any]:
        """
        Execute an action and await completion for async actions.
        
        This method checks action_metadata to determine if the action is async.
        - If sync: completes in same RCON call, returns result immediately
        - If async: queues in Lua, registers with UDP listener, waits for UDP completion
        
        Args:
            category: Remote interface category
            method: Method name
            args: Arguments dict
            safe: Whether to use error handling
            verbose: Whether to print the command
            timeout: Optional timeout override in seconds
            
        Returns:
            Final action result/payload
            
        Raises:
            ValueError: If action metadata not found
            TimeoutError: If async action times out
        """
        # Get metadata for this action
        # action_key = f"{category}_{method}"
        action_key = method
        metadata = self.action_metadata.get(action_key)
        
        if not metadata:
            raise ValueError(f"Action metadata not found: {action_key}")
        
        is_async = metadata.get('is_async', False)
        
        if not is_async:
            # Sync action: execute and return immediately
            if verbose:
                print(f"→ [SYNC] {action_key}")
            return self.run(category, method, args, safe=safe, verbose=verbose)
        
        # Async action: execute and wait for UDP completion
        if not self.udp_listener:
            raise RuntimeError("UDP listener not configured for async actions")
        
        if verbose:
            print(f"→ [ASYNC] {action_key}")
        
        # Execute action (returns queued response)
        response = self.run(category, method, args, safe=safe, verbose=verbose)
        
        # Check for validation/execution errors first
        if isinstance(response, dict) and response.get('success') == False:
            error_msg = response.get('error', 'Unknown error')
            raise Exception(f"Action failed: {error_msg}")
        
        # Check if it was actually queued
        if not response.get('queued'):
            if verbose:
                print(f"⚠️  Action was not queued: {action_key}")
            return response
        
        # Register and wait for completion
        action_id = response.get('action_id')
        if not action_id:
            raise ValueError("Async action response missing action_id")
        
        self.udp_listener.register_action(action_id)
        if verbose:
            print(f"⏳ Waiting for action: {action_id}")
        
        result = await self.udp_listener.wait_for_action(action_id, timeout=timeout)
        return result
    
    def pause(self):
        """Pause the game."""
        res = self.rcon_client.send_command("/c rcon.print(game.tick_paused); game.tick_paused=true; rcon.print(game.tick_paused)")
        print(res)
    
    def resume(self):
        """Resume the game."""
        res = self.rcon_client.send_command("/c rcon.print(game.tick_paused); game.tick_paused=false; rcon.print(game.tick_paused)")
        print(res)

