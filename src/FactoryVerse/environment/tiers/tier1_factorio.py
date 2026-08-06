"""Tier 1: Factorio Infrastructure.

Orchestrates Factorio client and server lifecycle with mods.
Handles multi-port architecture: RCON (TCP), game UDP, snapshot UDP, per-agent UDP.
"""

import logging
from pathlib import Path
from typing import Optional, Dict, Any, TYPE_CHECKING

from ..config import InfraConfig, InfraMode
from ..status import Tier1Status, TierState, PrerequisiteResult
from .base import TierBase, Tier, TierInitializationError

if TYPE_CHECKING:
    from ..environment import Environment

logger = logging.getLogger(__name__)


class Tier1Factorio(TierBase):
    """Tier 1: Factorio Infrastructure.

    Orchestrates Factorio installations with our mods (fv_embodied_agent, fv_snapshot).
    Both mods are always expected - snapshot depends on embodied_agent.

    Multi-port architecture:
    - RCON port (TCP): Command/control interface
    - Game UDP port: Game multiplayer traffic
    - Snapshot UDP port: Snapshot mod sync notifications
    - Agent UDP ports: Per-agent async action notifications (one-to-one)
    """

    tier_level = Tier.FACTORIO_INFRA

    def __init__(self, environment: "Environment"):
        super().__init__(environment)
        self._client_manager: Optional[Any] = None
        self._server_manager: Optional[Any] = None
        self._docker_compose_manager: Optional[Any] = None
        # Track what WE started vs what was already running
        self._client_started_by_us: bool = False
        self._server_started_by_us: bool = False

    @property
    def config(self) -> InfraConfig:
        """Get tier 1 configuration."""
        return self._env.config.tier1

    @property
    def client_manager(self) -> Optional[Any]:
        """Get Factorio client manager (if initialized)."""
        return self._client_manager

    @property
    def server_manager(self) -> Optional[Any]:
        """Get Factorio server manager (if initialized)."""
        return self._server_manager

    async def verify_prerequisites(self) -> PrerequisiteResult:
        """Tier 1 has no prerequisites (it's the base tier).

        However, we verify system requirements are met.
        """
        # EXTERNAL mode: no prerequisites, just connect to existing
        if self.config.mode == InfraMode.EXTERNAL:
            return PrerequisiteResult.ok()

        missing = []

        # Check Factorio is installed (for client mode)
        if self.config.mode in (InfraMode.CLIENT, InfraMode.CLIENT_AND_SERVER):
            if not self._is_factorio_installed():
                missing.append("factorio_client")

        # Check Docker is available (for server mode)
        if self.config.mode in (InfraMode.SERVER, InfraMode.CLIENT_AND_SERVER):
            if not self._is_docker_available():
                missing.append("docker")

        if missing:
            return PrerequisiteResult.failed(
                missing=missing, message="Required components not available"
            )

        return PrerequisiteResult.ok()

    async def initialize(self) -> None:
        """Initialize Factorio infrastructure based on mode.

        - CLIENT: Initialize client manager (manages lifecycle)
        - SERVER: Initialize server manager + Docker (manages lifecycle)
        - CLIENT_AND_SERVER: Initialize both
        - EXTERNAL: No managers, just connect to existing instance
        """
        self._set_state(TierState.INITIALIZING)

        try:
            # EXTERNAL mode: no lifecycle management, skip manager initialization
            if self.config.mode == InfraMode.EXTERNAL:
                logger.info("Tier 1: EXTERNAL mode - no lifecycle management")
                self._set_state(TierState.READY)
                return

            infra_config = self._env.config.infra_config

            # Initialize based on mode
            if self.config.mode in (InfraMode.CLIENT, InfraMode.CLIENT_AND_SERVER):
                await self._initialize_client(infra_config)

            if self.config.mode in (InfraMode.SERVER, InfraMode.CLIENT_AND_SERVER):
                await self._initialize_server(infra_config)

            self._set_state(TierState.READY)

        except Exception as e:
            self._set_state(TierState.ERROR, str(e))
            raise TierInitializationError(self.tier_level, str(e)) from e

    async def _initialize_client(self, infra_config) -> None:
        """Initialize Factorio client manager."""
        from FactoryVerse.infra.factorio_client_manager import FactorioClientManager

        self._client_manager = FactorioClientManager(work_dir=infra_config.project_root)
        logger.info("Tier 1: Client manager initialized")

    async def _initialize_server(self, infra_config) -> None:
        """Initialize Factorio server manager with Docker."""
        from FactoryVerse.infra.docker.factorio_server_manager import (
            FactorioServerManager,
        )
        from FactoryVerse.infra.docker.docker_compose_manager import (
            DockerComposeManager,
        )

        self._server_manager = FactorioServerManager(
            work_dir=infra_config.project_root,
            config=infra_config,
        )

        self._docker_compose_manager = DockerComposeManager(
            work_dir=infra_config.project_root
        )
        logger.info("Tier 1: Server manager initialized")

    async def verify_ready(self) -> Tier1Status:
        """Verify Factorio infrastructure is ready."""
        if self._state != TierState.READY:
            return Tier1Status(
                state=self._state,
                error=self._error,
            )

        factorio_installed = self._is_factorio_installed()
        mods_installed = self._check_mods_installed()

        # Check port availability
        ports_available = await self._check_ports()

        # Check running state
        client_running = None
        server_running = None

        if self._client_manager:
            client_running = self._client_manager.is_running()

        if self._server_manager and self._docker_compose_manager:
            # Check if Docker containers are running
            server_running = self._docker_compose_manager.is_running()

        return Tier1Status(
            state=self._state,
            factorio_installed=factorio_installed,
            mods_installed=mods_installed,
            client_running=client_running,
            server_running=server_running,
            ports_available=ports_available,
        )

    async def reset(self) -> None:
        """Reset Tier 1 by stopping and restarting Factorio."""
        self._set_state(TierState.INITIALIZING)

        # Stop existing instances
        await self.shutdown()

        # Re-initialize
        await self.initialize()

    async def shutdown(self) -> None:
        """Shutdown Factorio infrastructure.

        Only stops instances that WE started. Pre-existing instances are left alone.
        """
        self._set_state(TierState.SHUTTING_DOWN)

        # Only stop client if WE started it
        if self._client_manager and self._client_started_by_us:
            try:
                self._client_manager.stop()
                logger.info("Tier 1: Stopped client (started by us)")
            except Exception as e:
                logger.warning(f"Error stopping client: {e}")

        # Only stop server if WE started it
        if self._docker_compose_manager and self._server_started_by_us:
            try:
                self._docker_compose_manager.down()
                logger.info("Tier 1: Stopped server (started by us)")
            except Exception as e:
                logger.warning(f"Error stopping server: {e}")

        self._client_manager = None
        self._server_manager = None
        self._docker_compose_manager = None
        self._client_started_by_us = False
        self._server_started_by_us = False

        self._set_state(TierState.SHUTDOWN)

    # =========================================================================
    # Runtime Control Methods
    # =========================================================================

    async def start_client(
        self,
        scenario: Optional[str] = None,
        save_path: Optional[Path] = None,
        **kwargs,
    ) -> None:
        """Start Factorio client with scenario or save.

        Args:
            scenario: Scenario name to load
            save_path: Save file path (overrides scenario)
            **kwargs: Additional arguments passed to client manager
        """
        if not self._client_manager:
            raise RuntimeError("Client manager not initialized")

        # Ownership guard: ClientManager.start() no-ops when a client is
        # already running, so marking started_by_us after the fact would make
        # shutdown() kill a client we never started (live-observed 2026-06-11:
        # the L0.4 orchestrator-path harness SIGTERMed a pre-existing client
        # on env.shutdown()).
        if self._client_manager.is_running():
            logger.info(
                "Tier 1: Client already running — not ours; shutdown leaves it alone"
            )
            return

        if save_path:
            self._client_manager.start(save_file=str(save_path), **kwargs)
        elif scenario:
            self._client_manager.start(scenario=scenario, **kwargs)
        else:
            # Use tier 2 config if available
            tier2_config = self._env.config.tier2
            self._client_manager.start(scenario=tier2_config.scenario, **kwargs)

        # Mark that WE started the client
        self._client_started_by_us = True

    async def stop_client(self, force: bool = False) -> None:
        """Stop Factorio client."""
        if self._client_manager:
            self._client_manager.stop(force=force)

    async def start_server(
        self,
        scenario: str,
        num_instances: int = 1,
        save: Optional[str] = None,
        prepare_mods: bool = True,
    ) -> None:
        """Start Factorio server container(s).

        Args:
            scenario: Scenario to load
            num_instances: Number of server instances
            save: Save name to load instead of a fresh scenario start
                (from the per-server saves volume, .fv-output/server_N/saves)
        """
        if not self._server_manager or not self._docker_compose_manager:
            raise RuntimeError("Server manager not initialized")

        # Ownership guard (mirrors start_client): if the compose stack is
        # already up, attach — do NOT clear the RUNNING boot's snapshot dirs
        # (the CELL-2b clear below is for fresh boots only) and do NOT claim
        # started_by_us (shutdown would compose-down a server we never
        # started; live-observed 2026-06-11: the LIVE-1 #3 eval session tore
        # down server_0 on exit and wiped its live snapshot dirs on entry).
        if self._docker_compose_manager.is_running():
            logger.info(
                "Tier 1: Server already running — attaching (not ours; "
                "snapshots untouched; shutdown leaves it alone)"
            )
            return

        # CELL-2b: a FRESH scenario boot must not inherit a previous boot's
        # snapshot files (host volume persists across container restarts;
        # stale cells/destroyed rigs would load into every new session DB).
        # Saves keep their snapshots — the on-disk state matches the save.
        if save is None:
            self._server_manager.clear_all_server_snapshot_dirs(num_instances)
        else:
            logger.info(
                "Tier 1: Loading save '%s' — keeping existing snapshot dirs", save
            )

        # Prepare mods. Evaluation supervisors can prepare and verify an
        # immutable campaign bundle before allowing Docker to start.
        if prepare_mods:
            self._server_manager.prepare_mods(scenario)

        # Generate and write Docker Compose config
        services = self._server_manager.get_services(
            num_instances=num_instances,
            scenario=scenario,
            save=save,
        )
        self._docker_compose_manager.add_services("factorio", services)
        self._docker_compose_manager.write_compose()

        # Start containers
        self._docker_compose_manager.up()

        # Mark that WE started the server
        self._server_started_by_us = True

    async def stop_server(self) -> None:
        """Stop Factorio server container(s)."""
        if self._docker_compose_manager:
            self._docker_compose_manager.down()

    # =========================================================================
    # Port Information Methods
    # =========================================================================

    def get_rcon_port(self, instance: str = "client") -> int:
        """Get RCON port for an instance."""
        return self._env.config.infra_config.get_rcon_port(instance)

    def get_snapshot_port(self, instance: str = "client") -> int:
        """Get snapshot UDP port for an instance."""
        return self._env.config.infra_config.get_snapshot_port(instance)

    def get_agent_port(
        self, agent_index: int, server_index: Optional[int] = None
    ) -> int:
        """Get UDP port for a specific agent."""
        return self._env.config.infra_config.get_agent_port(agent_index, server_index)

    # =========================================================================
    # Private Helper Methods
    # =========================================================================

    def _is_factorio_installed(self) -> bool:
        """Check if Factorio client is installed."""
        try:
            from FactoryVerse.infra.factorio_client_setup import (
                _find_factorio_executable,
            )

            return _find_factorio_executable() is not None
        except Exception:
            return False

    def _is_docker_available(self) -> bool:
        """Check if Docker is available."""
        import shutil

        return shutil.which("docker") is not None

    def _check_mods_installed(self) -> bool:
        """Check if FactoryVerse mods are available.

        We check for mod source directories, not installation.
        Installation happens during server/client setup.
        """
        infra_config = self._env.config.infra_config
        embodied_mod = infra_config.embodied_agent_mod_dir
        snapshot_mod = infra_config.snapshot_mod_dir

        return embodied_mod.exists() and snapshot_mod.exists()

    async def _check_ports(self) -> Dict[str, bool]:
        """Check if required ports are available."""
        from FactoryVerse.utils.port_utils import is_port_available

        infra_config = self._env.config.infra_config
        ports = {}

        # Check RCON port based on mode
        if self.config.mode in (InfraMode.CLIENT, InfraMode.CLIENT_AND_SERVER):
            rcon_port = infra_config.rcon_client_port
            ports["rcon_client"] = is_port_available(rcon_port)

        if self.config.mode in (InfraMode.SERVER, InfraMode.CLIENT_AND_SERVER):
            for i in range(self.config.server_count):
                rcon_port = infra_config.rcon_server_port_base + i
                ports[f"rcon_server_{i}"] = is_port_available(rcon_port)

        return ports
