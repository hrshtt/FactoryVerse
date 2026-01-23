"""AsyncActionListener - UDP listener for async action completion events.

Handles agent-specific UDP port for async action completions (walking, mining, crafting).
"""

from __future__ import annotations
import json
import asyncio
import time
import logging
import socket
import threading
import queue
from typing import Any, Dict, Optional, Callable, List

from FactoryVerse.infra.udp_dispatcher import UDPDispatcher, get_udp_dispatcher
from FactoryVerse.game.agent.models import AsyncActionResponse

logger = logging.getLogger(__name__)


class AsyncActionListener:
    """UDP listener for async action completion events.

    Can operate in two modes:
    1. Direct UDP listening on agent-specific port (agent_port specified)
    2. Through UDPDispatcher for shared port (udp_dispatcher specified)
    """

    def __init__(
        self,
        udp_dispatcher: Optional[UDPDispatcher] = None,
        agent_port: Optional[int] = None,
        host: str = "0.0.0.0",
        timeout: int = 30,
    ):
        """
        Initialize the UDP listener.

        Args:
            udp_dispatcher: Optional UDPDispatcher instance. If None and agent_port is None, uses global dispatcher.
            agent_port: Optional direct UDP port for agent-specific messages. If provided, listens directly on this port.
            host: Host to bind to (only used if agent_port is provided)
            timeout: Default timeout in seconds for waiting on actions
        """
        self.udp_dispatcher = udp_dispatcher
        self.agent_port = agent_port
        self.host = host
        self.timeout = timeout
        self.pending_actions: Dict[str, asyncio.Event] = {}
        self.action_results: Dict[str, Dict[str, Any]] = {}
        self.event_loops: Dict[str, asyncio.AbstractEventLoop] = {}
        self.action_timeouts: Dict[
            str, float
        ] = {}  # Track timeout deadlines for progress extension
        self.action_progress: Dict[
            str, Dict[str, Any]
        ] = {}  # Track progress for actions
        self.notification_queue: queue.Queue = (
            queue.Queue()
        )  # Thread-safe queue for notifications
        self.notification_callbacks: Dict[
            str, Callable
        ] = {}  # Callbacks for specific notification types
        self.running = False
        self.sock: Optional[socket.socket] = None
        self.listener_thread: Optional[threading.Thread] = None

    async def start(self):
        """Start listening for UDP messages.

        If agent_port is set, listens directly on that port.
        Otherwise, subscribes to UDP dispatcher.
        """
        if self.agent_port is not None:
            # Direct UDP listening mode (agent-specific port)
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                self.sock.bind((self.host, self.agent_port))
            except OSError as e:
                self.sock.close()
                self.sock = None
                raise RuntimeError(
                    f"Failed to bind UDP socket to {self.host}:{self.agent_port}: {e}"
                )

            self.sock.settimeout(0.5)  # Non-blocking with timeout
            self.running = True

            # Start listener thread
            self.listener_thread = threading.Thread(
                target=self._direct_listen_loop, daemon=True
            )
            self.listener_thread.start()

            logger.info(
                f"✅ AsyncActionListener started on direct port {self.host}:{self.agent_port}"
            )
        else:
            # Dispatcher mode (shared port)
            if self.udp_dispatcher is None:
                self.udp_dispatcher = get_udp_dispatcher()

            if not self.udp_dispatcher.is_running():
                await self.udp_dispatcher.start()

            self.udp_dispatcher.subscribe("*", self._route_udp_message)
            self.running = True
            logger.info("✅ AsyncActionListener started via UDPDispatcher")

    def _route_udp_message(self, payload: Dict[str, Any]):
        """Route incoming UDP message to appropriate handler based on event_type.

        This is the dispatcher callback that mirrors the routing logic in _direct_listen_loop.
        """
        event_type = payload.get("event_type")

        if event_type == "action":
            self._handle_udp_message(payload)
        elif event_type == "notification":
            self._handle_notification(payload)
        else:
            logger.warning(f"Unknown event_type in UDP message: {event_type}")

    def _direct_listen_loop(self):
        """Background thread loop for receiving UDP packets directly."""
        while self.running and self.sock:
            try:
                data, addr = self.sock.recvfrom(65535)
                try:
                    payload = json.loads(data.decode("utf-8"))
                    event_type = payload.get("event_type")

                    if event_type == "action":
                        self._handle_udp_message(payload)
                    elif event_type == "notification":
                        self._handle_notification(payload)
                    else:
                        logger.warning(f"Unknown event_type: {event_type}")

                except json.JSONDecodeError as e:
                    logger.warning(f"⚠️  Failed to decode UDP JSON from {addr}: {e}")
                except Exception as e:
                    logger.error(f"❌ Error processing UDP message from {addr}: {e}")
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    logger.error(f"❌ Error in direct UDP listener: {e}")

    def _handle_notification(self, payload: Dict[str, Any]):
        """Process received UDP notification message."""
        logger.info(f"UDP Notification RX: {payload}")
        self.notification_queue.put(payload)
        notification_type = payload.get("notification_type")
        if notification_type and notification_type in self.notification_callbacks:
            try:
                self.notification_callbacks[notification_type](payload)
            except Exception as e:
                logger.error(
                    f"Error in notification callback for type '{notification_type}': {e}"
                )

    def _handle_udp_message(self, payload: Dict[str, Any]):
        """Process received UDP message from dispatcher (called by dispatcher thread).

        Implements state machine contract:
        - status: "queued" -> ignore (logging only)
        - status: "progress" -> track progress, extend timeout for walking
        - status: "completed" -> finish await
        - status: "cancelled" -> finish await with cancellation
        """
        logger.info(f"UDP RX: {payload}")
        try:
            action_id = payload.get("action_id")
            # TODO: make this categorically associated with the action type
            if not action_id:
                return

            # Require status field (no backwards compatibility)
            status = payload.get("status")
            if not status:
                return

            if action_id not in self.pending_actions:
                return

            # State machine routing
            if status == "queued":
                # Ignore - logging only, redundant with RCON response
                return

            if status == "progress":
                # Track progress
                self.action_progress[action_id] = payload.get("result", {})

                # Extend timeout for walking only
                action_type = payload.get("action_type")
                if action_type == "walk_to" and action_id in self.action_timeouts:
                    # Extend timeout by default timeout duration when progress is received
                    self.action_timeouts[action_id] = time.time() + self.timeout
                    logger.debug(f"Extended timeout for {action_id} due to progress")

                return

            if status in ("completed", "cancelled", "failed"):
                # Finish await - completed, cancelled, or failed are all terminal states
                self.action_results[action_id] = payload
                event = self.pending_actions[action_id]

                loop = self.event_loops.get(action_id)
                if loop and loop.is_running():
                    loop.call_soon_threadsafe(event.set)
                else:
                    event.set()
                return

            # Unknown status
            logger.warning(f"Unknown status '{status}' for action {action_id}")
        except Exception as e:
            print(f"❌ Error processing UDP message: {e}")

    async def stop(self):
        """Stop listening for UDP messages."""
        was_running = self.running
        self.running = False

        if self.agent_port is not None and self.sock:
            # Direct UDP listening mode - close socket
            if self.listener_thread:
                self.listener_thread.join(timeout=2)
            if self.sock:
                self.sock.close()
                self.sock = None
            logger.info(f"AsyncActionListener stopped (direct port {self.agent_port})")
        elif self.udp_dispatcher is not None and was_running:
            # Dispatcher mode - unsubscribe
            self.udp_dispatcher.unsubscribe("*", self._route_udp_message)
            logger.info("AsyncActionListener stopped (dispatcher mode)")

    def register_action(
        self, action_id: str, initial_timeout_deadline: Optional[float] = None
    ):
        """Register an action to wait for completion via UDP.

        Args:
            action_id: The action ID to register
            initial_timeout_deadline: Optional initial timeout deadline in seconds since epoch (for progress-based extension)
        """
        event = asyncio.Event()
        self.pending_actions[action_id] = event
        self.action_results[action_id] = None
        self.action_progress[action_id] = {}
        if initial_timeout_deadline:
            self.action_timeouts[action_id] = initial_timeout_deadline
        try:
            self.event_loops[action_id] = asyncio.get_running_loop()
        except RuntimeError:
            self.event_loops[action_id] = None

    async def wait_for_action(
        self, action_id: str, timeout: Optional[float] = None
    ) -> Dict[str, Any]:
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

        # Initialize timeout deadline for progress-based extension (walking only)
        if action_id not in self.action_timeouts:
            self.action_timeouts[action_id] = time.time() + timeout_secs

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout_secs)
            return self.action_results[action_id]
        except asyncio.TimeoutError:
            raise
        finally:
            self.pending_actions.pop(action_id, None)
            self.action_results.pop(action_id, None)
            self.action_timeouts.pop(action_id, None)
            self.action_progress.pop(action_id, None)
            self.event_loops.pop(action_id, None)

    async def await_action(
        self, response: AsyncActionResponse, timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """Wait for an async action to complete.

        Public method for actions to use. Handles starting listener if needed
        and calculating timeouts based on estimated_ticks.

        Args:
            response: AsyncActionResponse from async action (should have action_id)
            timeout: Optional timeout in seconds (overrides calculated timeout)

        Returns:
            Completion payload from UDP
        """
        if not response.queued:
            return {"success": response.success, "reason": response.reason}

        action_id = response.action_id
        if not action_id:
            return {"success": response.success, "reason": response.reason}

        # Ensure listener is running
        if not self.running:
            await self.start()

        # Calculate timeout with buffer based on estimated_ticks
        calculated_timeout = timeout
        if timeout is None:
            estimated_ticks = response.estimated_ticks
            if estimated_ticks:
                # Convert ticks to seconds: 1 tick = 1/60 seconds at game.speed = 1.0
                # Add 1.5x buffer for safety (total 2.5x)
                base_seconds = estimated_ticks / 60.0
                calculated_timeout = max(5.0, base_seconds * 2.5)
                logger.debug(
                    f"Calculated timeout for {action_id}: {calculated_timeout:.3f}s (from {estimated_ticks} ticks)"
                )
            else:
                calculated_timeout = self.timeout

        self.register_action(action_id)
        return await self.wait_for_action(action_id, timeout=calculated_timeout)

    # ========================================================================
    # NOTIFICATIONS
    # ========================================================================

    async def get_notifications(
        self, timeout: Optional[float] = 0.1
    ) -> List[Dict[str, Any]]:
        """Get all pending notifications (non-blocking).

        Retrieves notifications from the UDP notification queue. This includes
        research events, crafting completions, and other asynchronous game events.

        Args:
            timeout: Max time to wait for first notification (seconds).
                    Use 0 for immediate return, None to wait indefinitely.

        Returns:
            List of notification payloads. Each notification has:
                - event_type: "notification"
                - notification_type: Type of notification (e.g., "research_finished")
                - agent_id: Agent ID
                - tick: Game tick
                - data: Notification-specific data

        Example:
            >>> notifications = await listener.get_notifications(timeout=0.1)
            >>> for notif in notifications:
            ...     if notif['notification_type'] == 'research_finished':
            ...         print(f"Research complete: {notif['data']['technology']}")
        """
        # Ensure listener is running
        if not self.running:
            await self.start()

        notifications = []

        try:
            # Wait for first notification with timeout
            if timeout is not None and timeout > 0:
                start_time = time.time()
                while time.time() - start_time < timeout:
                    try:
                        notif = self.notification_queue.get_nowait()
                        notifications.append(notif)
                        break
                    except queue.Empty:
                        await asyncio.sleep(0.01)

            # Drain remaining notifications (non-blocking)
            while True:
                try:
                    notif = self.notification_queue.get_nowait()
                    notifications.append(notif)
                except queue.Empty:
                    break

        except Exception as e:
            logger.error(f"Error getting notifications: {e}")

        return notifications

    def register_notification_callback(
        self, notification_type: str, callback: Callable[[Dict[str, Any]], None]
    ):
        """Register callback for specific notification type.

        The callback will be called immediately when a notification of the specified
        type is received, from the UDP listener thread. Keep callbacks lightweight.

        Args:
            notification_type: Type of notification (e.g., "research_finished")
            callback: Function to call with notification payload

        Example:
            >>> def on_research_done(notif):
            ...     print(f"Research complete: {notif['data']['technology']}")
            >>> listener.register_notification_callback("research_finished", on_research_done)
        """
        self.notification_callbacks[notification_type] = callback
