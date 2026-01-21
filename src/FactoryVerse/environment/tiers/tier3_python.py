"""Tier 3: Python Infrastructure.

Orchestrates RCON connection and UDP listeners for Python<->Factorio communication.
"""

import logging
from typing import Optional, Any, TYPE_CHECKING

from ..config import PythonConfig
from ..status import Tier3Status, TierState, PrerequisiteResult
from .base import TierBase, Tier, TierInitializationError

if TYPE_CHECKING:
    from ..environment import Environment
    from factorio_rcon import RCONClient

logger = logging.getLogger(__name__)


class Tier3Python(TierBase):
    """Tier 3: Python Infrastructure.

    Establishes the communication bridge between Python and Factorio:
    - RCON client for command/control
    - UDP dispatcher for async notifications
    - AsyncActionListener for action completion events

    This tier connects to an already-running Factorio instance
    (started by Tier 1/2 coordination).
    """

    tier_level = Tier.PYTHON_INFRA

    def __init__(self, environment: "Environment"):
        super().__init__(environment)
        self._rcon: Optional[Any] = None
        self._rcon_helper: Optional[Any] = None
        self._udp_dispatcher: Optional[Any] = None
        self._action_listener: Optional[Any] = None
        self._instance: Optional[str] = None
        self._agent_registry: Optional[Any] = None

    @property
    def config(self) -> PythonConfig:
        """Get tier 3 configuration."""
        return self._env.config.tier3

    @property
    def rcon(self) -> Optional["RCONClient"]:
        """Get RCON client."""
        return self._rcon

    @property
    def rcon_helper(self) -> Optional[Any]:
        """Get RconHelper with async action support."""
        return self._rcon_helper

    @property
    def instance(self) -> Optional[str]:
        """Get current instance name (client/server_N)."""
        return self._instance

    @property
    def agent_registry(self) -> Optional[Any]:
        """Get agent registry service."""
        return self._agent_registry

    async def verify_prerequisites(self) -> PrerequisiteResult:
        """Verify Tier 2 (Settings) is ready."""
        tier2 = self._env.tier2

        if tier2 is None or not tier2.is_ready:
            return PrerequisiteResult.failed(
                missing=["tier2_settings"],
                message="Factorio settings must be configured first",
            )

        return PrerequisiteResult.ok()

    async def initialize(self) -> None:
        """Initialize RCON connection and UDP listeners."""
        self._set_state(TierState.INITIALIZING)

        try:
            infra_config = self._env.config.infra_config

            # Determine instance to connect to
            self._instance = self._determine_instance()

            # Get connection parameters
            rcon_port = infra_config.get_rcon_port(self._instance)
            rcon_host = infra_config.rcon_host
            rcon_password = infra_config.rcon_password

            # Initialize RCON client
            await self._init_rcon(rcon_host, rcon_port, rcon_password)

            # Initialize UDP dispatcher if enabled
            if self.config.udp_enabled:
                await self._init_udp()

            # Initialize RconHelper with action listener
            await self._init_rcon_helper()

            # Verify connection with ping
            await self._verify_connection()

            # Initialize Agent Registry
            await self._init_agent_registry()

            self._set_state(TierState.READY)

        except Exception as e:
            self._set_state(TierState.ERROR, str(e))
            raise TierInitializationError(self.tier_level, str(e)) from e

    async def _wait_for_port(self, host: str, port: int, timeout: float = 60.0) -> None:
        """Wait for a TCP port to accept connections.

        This checks if the server is accepting connections at the socket level,
        before attempting RCON authentication. Useful when waiting for Docker
        containers to fully start.

        Args:
            host: Host to connect to
            port: Port to check
            timeout: Maximum seconds to wait (default 60)

        Raises:
            TimeoutError: If port doesn't become available within timeout
        """
        import asyncio
        import socket

        start_time = asyncio.get_event_loop().time()
        attempt = 0

        while True:
            attempt += 1
            elapsed = asyncio.get_event_loop().time() - start_time

            if elapsed >= timeout:
                raise TimeoutError(
                    f"Port {host}:{port} not available after {timeout}s"
                )

            try:
                # Try to open a TCP connection
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2.0)
                result = sock.connect_ex((host, port))
                sock.close()

                if result == 0:
                    logger.info(
                        f"Tier 3: Port {host}:{port} is ready (attempt {attempt}, {elapsed:.1f}s)"
                    )
                    return
                else:
                    logger.debug(
                        f"Tier 3: Port {host}:{port} not ready (attempt {attempt}), waiting..."
                    )
            except (socket.error, OSError) as e:
                logger.debug(
                    f"Tier 3: Port check failed ({e}), waiting..."
                )

            await asyncio.sleep(1.0)

    async def _init_rcon(self, host: str, port: int, password: str) -> None:
        """Initialize RCON client connection with port readiness check and retry logic.

        First waits for the port to accept TCP connections, then attempts RCON
        authentication with retries.
        """
        from factorio_rcon import RCONClient, RCONConnectError
        import asyncio

        # Phase 1: Wait for port to be accepting connections
        logger.info(f"Tier 3: Waiting for RCON port {host}:{port} to be ready...")
        await self._wait_for_port(host, port, timeout=60.0)

        # Phase 2: Attempt RCON authentication with retries
        # Server may accept connections but not be ready for RCON yet
        max_retries = 30
        for i in range(max_retries):
            try:
                self._rcon = RCONClient(host, port, password)
                logger.info(f"Tier 3: RCON client connected to {host}:{port}")
                return
            except RCONConnectError as e:
                if i < max_retries - 1:
                    logger.debug(
                        f"Tier 3: RCON auth failed ({e}), retrying ({i + 1}/{max_retries})..."
                    )
                    await asyncio.sleep(1.0)
                else:
                    raise

    async def _init_udp(self) -> None:
        """Initialize UDP dispatcher for agent action notifications.

        The UDP port must match what Tier 4 tells the Lua mod, otherwise
        async action notifications (walking, mining, crafting) will be lost.

        Port calculation:
        - If udp_port is explicitly set: use that port
        - Otherwise: calculate from agent_id using infra_config.get_agent_port()
        """
        from FactoryVerse.infra.udp_dispatcher import UDPDispatcher

        udp_port = self.config.udp_port

        if udp_port is None:
            # Calculate agent-specific port from agent_id
            # This ensures the Python listener matches the Lua agent's notification target
            agent_id = self.config.agent_id  # e.g., "agent_1"
            infra_config = self._env.config.infra_config

            try:
                agent_index = int(agent_id.split("_")[1]) - 1  # agent_1 → 0
            except (ValueError, IndexError):
                agent_index = 0

            # Get server_index from instance name
            server_index = None
            if self._instance and self._instance.startswith("server_"):
                try:
                    server_index = int(self._instance.split("_")[1])
                except (ValueError, IndexError):
                    pass

            udp_port = infra_config.get_agent_port(agent_index, server_index)
            logger.info(
                f"Tier 3: Calculated agent UDP port {udp_port} from agent_id='{agent_id}'"
            )

        self._udp_dispatcher = UDPDispatcher(port=udp_port)
        await self._udp_dispatcher.start()
        logger.info(
            f"Tier 3: UDP dispatcher started on port {self._udp_dispatcher.port}"
        )

    async def _init_rcon_helper(self) -> None:
        """Initialize RconHelper with async action support."""
        from FactoryVerse.infra.rcon_helper import RconHelper
        from FactoryVerse.agent.infra.async_listener import AsyncActionListener

        # Create action listener if UDP is enabled
        # Using the one from agent.infra.async_listener which has await_action()
        if self._udp_dispatcher:
            self._action_listener = AsyncActionListener(
                udp_dispatcher=self._udp_dispatcher
            )
            await self._action_listener.start()

        # Create RconHelper
        udp_port = self._udp_dispatcher.port if self._udp_dispatcher else None
        self._rcon_helper = RconHelper(
            rcon_client=self._rcon,
            udp_listener=self._action_listener,
            auto_create_agent=False,  # Tier 4 handles agent creation
            udp_port=udp_port,
        )

        logger.info("Tier 3: RconHelper initialized")

    async def _init_agent_registry(self) -> None:
        """Initialize Agent Registry service."""
        from FactoryVerse.agent.core.registry import AgentRegistry

        infra_config = self._env.config.infra_config

        # Use a central directory for agent profiles registry
        # We use .fv-output/agents/
        registry_dir = infra_config.fv_output_dir / "agents"

        self._agent_registry = AgentRegistry(storage_dir=registry_dir)
        logger.info(f"Tier 3: Agent Registry initialized at {registry_dir}")

    async def _verify_connection(self) -> None:
        """Verify RCON connection is working."""
        try:
            if self._rcon is None:
                raise RuntimeError("RCON not connected")

            result = self._rcon.send_command("/time")
            if result:
                # Clean result string if needed
                pass

            # Optimization: Cache tick
            if self._env.tier2:
                self._env.tier2.mark_game_loaded()
            # Parse tick from response (format: "daytime: N")
            if "daytime" in result.lower():
                # Update tier 2 with game state
                if self._env.tier2:
                    self._env.tier2.mark_game_loaded()
                logger.info("Tier 3: RCON connection verified")
            else:
                logger.warning(f"Tier 3: Unexpected RCON response: {result}")
        except Exception as e:
            raise RuntimeError(f"RCON connection failed: {e}") from e

    async def verify_ready(self) -> Tier3Status:
        """Verify Python infrastructure is operational."""
        if self._state != TierState.READY:
            return Tier3Status(
                state=self._state,
                error=self._error,
            )

        # Check connection status
        rcon_connected = self._rcon is not None
        rcon_responsive = False

        if rcon_connected:
            try:
                if self._rcon:
                    self._rcon.send_command("/time")
                rcon_responsive = True
            except Exception:
                pass

        return Tier3Status(
            state=self._state,
            rcon_connected=rcon_connected,
            rcon_responsive=rcon_responsive,
            udp_listening=self._udp_dispatcher is not None,
            instance_type=self._instance,
        )

    async def reset(self) -> None:
        """Reset by reconnecting RCON and UDP."""
        await self.shutdown()
        await self.initialize()

    async def shutdown(self) -> None:
        """Shutdown RCON and UDP connections."""
        self._set_state(TierState.SHUTTING_DOWN)

        # Stop action listener
        if self._action_listener:
            await self._action_listener.stop()
            self._action_listener = None

        # Stop UDP dispatcher
        if self._udp_dispatcher:
            await self._udp_dispatcher.stop()
            self._udp_dispatcher = None

        # Close RCON
        if self._rcon:
            try:
                self._rcon.close()
            except Exception:
                pass
            self._rcon = None

        self._rcon_helper = None
        self._instance = None

        self._set_state(TierState.SHUTDOWN)

    # =========================================================================
    # Lua Execution Methods
    # =========================================================================

    def execute_lua(self, code: str) -> str:
        """Execute raw Lua code via RCON.

        Args:
            code: Lua code to execute

        Returns:
            Result string from RCON
        """
        if not self._rcon:
            raise RuntimeError("RCON not connected")

        return self._rcon.send_command(f"/c {code}")

    def execute_silent(self, code: str) -> str:
        """Execute Lua code without output via RCON.

        Uses /silent-command for cleaner execution.
        """
        if not self._rcon:
            raise RuntimeError("RCON not connected")

        return self._rcon.send_command(f"/silent-command {code}")

    # =========================================================================
    # Lua State Query Methods (Single Source of Truth)
    # =========================================================================

    def list_game_agents(self) -> list[dict]:
        """Query agents currently existing in Factorio.

        Returns:
            List of agent dicts with keys:
            - id: Numeric agent ID
            - interface_name: Agent interface name (e.g., 'agent_1')
            - force: Force name (e.g., 'player')
            - udp_port: UDP port for notifications
            - entity_valid: Whether agent entity is valid
            - position: {x, y} position
        """
        import json

        if not self._rcon:
            raise RuntimeError("RCON not connected")

        result = self._rcon.send_command(
            "/c local res = remote.call('agent', 'list_agents'); "
            "rcon.print(helpers.table_to_json(res))"
        )
        return json.loads(result) if result else []

    def get_snapshot_status(self) -> dict:
        """Query snapshot system status from Factorio.

        Returns:
            Dict with keys:
            - phase: Current phase
            - system_phase: System phase
            - pending_chunks: Number of pending chunks
            - completed_chunks: Number of completed chunks
            - bootstrap_wait: Bootstrap wait status
            - config: Snapshot configuration
        """
        import json

        if not self._rcon:
            raise RuntimeError("RCON not connected")

        result = self._rcon.send_command(
            "/c local res = remote.call('map', 'get_snapshot_status'); "
            "rcon.print(helpers.table_to_json(res))"
        )
        return json.loads(result) if result else {}

    def get_game_tick(self) -> int:
        """Get current game tick from Factorio.

        Returns:
            Current game tick number
        """
        if not self._rcon:
            raise RuntimeError("RCON not connected")

        result = self._rcon.send_command("/c rcon.print(game.tick)")
        return int(result.strip()) if result else 0

    def destroy_game_agents(
        self, agent_ids: list[int], remove_forces: bool = False
    ) -> dict:
        """Destroy agents in Factorio.

        Args:
            agent_ids: List of numeric agent IDs to destroy
            remove_forces: Whether to also remove agent forces

        Returns:
            Dict with: destroyed (list), errors (list)
        """
        import json

        if not self._rcon:
            raise RuntimeError("RCON not connected")

        # Format agent IDs as Lua table
        ids_lua = "{" + ", ".join(str(id) for id in agent_ids) + "}"
        remove_str = "true" if remove_forces else "false"

        result = self._rcon.send_command(
            f"/c local res = remote.call('agent', 'destroy_agents', {ids_lua}, {remove_str}); "
            "rcon.print(helpers.table_to_json(res))"
        )
        return json.loads(result) if result else {"destroyed": [], "errors": []}

    def create_game_agent(
        self,
        udp_port: int,
        set_unique_forces: bool = False,
        default_common_force: str = "player",
        initial_inventory: dict[str, int] | None = None,
    ) -> dict:
        """Create a new agent in Factorio with correct parameter mapping.

        This matches the Lua API signature:
        remote.call('agent', 'create_agent', udp_port, set_unique_forces, default_common_force, initial_inventory)

        Args:
            udp_port: UDP port for agent notifications
            set_unique_forces: If True, create unique force per agent; if False, use default_common_force
            default_common_force: Force name when set_unique_forces=False (default: 'player')
            initial_inventory: Optional dict of item_name -> count

        Returns:
            Dict with: agent_id, force_name, interface_name, udp_port
        """
        import json

        if not self._rcon:
            raise RuntimeError("RCON not connected")

        # Build Lua command with correct parameter order
        # Args: udp_port, set_unique_forces, default_common_force, initial_inventory
        set_unique_str = "true" if set_unique_forces else "false"

        if initial_inventory:
            inv_lua = (
                "{"
                + ", ".join(f'["{k}"] = {v}' for k, v in initial_inventory.items())
                + "}"
            )
            cmd = (
                f"/c local res = remote.call('agent', 'create_agent', "
                f"{udp_port}, {set_unique_str}, \"{default_common_force}\", {inv_lua}); "
                "rcon.print(helpers.table_to_json(res))"
            )
        else:
            cmd = (
                f"/c local res = remote.call('agent', 'create_agent', "
                f"{udp_port}, {set_unique_str}, \"{default_common_force}\"); "
                "rcon.print(helpers.table_to_json(res))"
            )

        result = self._rcon.send_command(cmd)

        if result and result.strip():
            parsed = json.loads(result)
            logger.info(f"Tier 3: Created agent: {parsed}")
            return parsed
        else:
            logger.warning("Tier 3: Agent creation returned empty result")
            return {}

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _determine_instance(self) -> str:
        """Determine which Factorio instance to connect to.

        Priority:
        1. Explicit config.instance
        2. Auto-detect based on tier1 mode
        """
        if self.config.instance:
            return self.config.instance

        # Auto-detect from tier 1 mode
        tier1_config = self._env.config.tier1
        from ..config import InfraMode

        if tier1_config.mode == InfraMode.SERVER:
            return "server_0"
        else:
            return "client"
