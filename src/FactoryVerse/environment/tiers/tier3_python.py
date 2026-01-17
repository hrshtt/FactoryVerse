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

            self._set_state(TierState.READY)

        except Exception as e:
            self._set_state(TierState.ERROR, str(e))
            raise TierInitializationError(self.tier_level, str(e)) from e

    async def _init_rcon(self, host: str, port: int, password: str) -> None:
        """Initialize RCON client connection with retry logic."""
        from factorio_rcon import RCONClient, RCONConnectError
        import asyncio

        max_retries = 30  # 30 seconds total
        for i in range(max_retries):
            try:
                self._rcon = RCONClient(host, port, password)
                logger.info(f"Tier 3: RCON client created for {host}:{port}")
                return
            except RCONConnectError:
                if i < max_retries - 1:
                    logger.debug(
                        f"Tier 3: RCON connection failed, retrying ({i + 1}/{max_retries})..."
                    )
                    await asyncio.sleep(1.0)
                else:
                    raise

    async def _init_udp(self) -> None:
        """Initialize UDP dispatcher for notifications."""
        from FactoryVerse.infra.udp_dispatcher import UDPDispatcher, get_udp_dispatcher

        udp_port = self.config.udp_port
        if udp_port is None:
            # Use global dispatcher with auto-allocated port
            self._udp_dispatcher = get_udp_dispatcher()
        else:
            self._udp_dispatcher = UDPDispatcher(port=udp_port)

        await self._udp_dispatcher.start()
        logger.info(
            f"Tier 3: UDP dispatcher started on port {self._udp_dispatcher.port}"
        )

    async def _init_rcon_helper(self) -> None:
        """Initialize RconHelper with async action support."""
        from FactoryVerse.infra.rcon_helper import RconHelper, AsyncActionListener

        # Create action listener if UDP is enabled
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
