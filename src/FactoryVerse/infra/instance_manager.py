"""Factorio instance detection and management.

Provides a centralized way to detect and configure connections to Factorio instances
(local client or Docker servers), ensuring consistent configuration across tests,
agents, and scripts.
"""

import os
import logging
from pathlib import Path
from typing import Optional, Literal, List
from dataclasses import dataclass

from factorio_rcon import RCONClient

from FactoryVerse.config import FactoryVerseConfig, get_config


logger = logging.getLogger(__name__)


class NoInstanceError(RuntimeError):
    """Raised when no Factorio instance is detected."""

    pass


class MultipleInstancesError(RuntimeError):
    """Raised when multiple Factorio instances are active and disambiguation is required."""

    pass


@dataclass
class FactorioInstance:
    """Represents a Factorio instance (client or server) with its configuration."""

    type: Literal["client", "server"]
    """Instance type: 'client' for local Factorio, 'server' for Docker server"""

    server_id: Optional[int]
    """Server ID (0, 1, 2, ...) if type is 'server', None for client"""

    script_output_dir: Path
    """Path to script-output directory for this instance"""

    rcon_host: str
    """RCON host address"""

    rcon_port: int
    """RCON port"""

    rcon_password: str
    """RCON password"""

    @property
    def name(self) -> str:
        """Human-readable instance name."""
        if self.type == "client":
            return "client"
        return f"server_{self.server_id}"

    @property
    def snapshot_dir(self) -> Path:
        """Snapshot directory for this instance."""
        return self.script_output_dir / "factoryverse" / "snapshots"

    def test_connection(self) -> bool:
        """Test if RCON connection is responsive."""
        try:
            client = RCONClient(self.rcon_host, self.rcon_port, self.rcon_password)
            client.connect()
            client.send_command("/c rcon.print('ping')")
            client.close()
            return True
        except Exception as e:
            logger.debug(f"Connection test failed for {self.name}: {e}")
            return False


class FactorioInstanceManager:
    """Manages detection and configuration of Factorio instances.

    Uses live detection to find running instances. Provides collision
    detection when multiple instances are active.
    """

    # Environment variable to override instance selection
    ENV_INSTANCE = "FV_INSTANCE"

    @classmethod
    def from_env(cls, config: Optional[FactoryVerseConfig] = None) -> FactorioInstance:
        """Load instance from FV_INSTANCE env var or auto-detect.

        FV_INSTANCE format: 'client' or 'server_N' (e.g., 'server_0')

        Returns:
            Detected or configured FactorioInstance

        Raises:
            NoInstanceError: If no instance can be detected or configured
            ValueError: If FV_INSTANCE has invalid format
        """
        cfg = config or get_config()
        instance_name = os.getenv(cls.ENV_INSTANCE)

        if instance_name:
            logger.info(f"Using instance from {cls.ENV_INSTANCE}: {instance_name}")
            if instance_name == "client":
                return cls.get_client(cfg)
            elif instance_name.startswith("server_"):
                server_id = int(instance_name.split("_")[1])
                return cls.get_server(server_id, cfg)
            else:
                raise ValueError(
                    f"Invalid {cls.ENV_INSTANCE} value: {instance_name}. "
                    f"Expected 'client' or 'server_N'"
                )

        # Auto-detect
        logger.info("No FV_INSTANCE set, attempting auto-detection...")
        instance = cls.detect_active(cfg)
        if instance:
            logger.info(f"Auto-detected instance: {instance.name}")
            return instance

        raise NoInstanceError(
            "Could not detect active Factorio instance. "
            f"Set {cls.ENV_INSTANCE}=client or {cls.ENV_INSTANCE}=server_0"
        )

    @classmethod
    def get_active(
        cls,
        require_single: bool = False,
        config: Optional[FactoryVerseConfig] = None,
    ) -> FactorioInstance:
        """Get active instance with collision handling.

        Args:
            require_single: If True, raise error when multiple instances active
            config: Optional config override

        Returns:
            Active FactorioInstance

        Raises:
            NoInstanceError: No instances detected
            MultipleInstancesError: Multiple active and require_single=True
        """
        cfg = config or get_config()

        # Check for explicit override first
        instance_name = os.getenv(cls.ENV_INSTANCE)
        if instance_name:
            return cls.from_env(cfg)

        # Live detection
        active = cls.list_active(cfg)

        if len(active) == 0:
            raise NoInstanceError(
                "No Factorio instances detected. "
                "Start a client with 'fv client launch' or servers with 'fv server start'."
            )

        if len(active) > 1:
            names = [i.name for i in active]
            if require_single:
                raise MultipleInstancesError(
                    f"Multiple instances active: {names}. "
                    f"Set FV_INSTANCE environment variable to choose one "
                    f"(e.g., FV_INSTANCE=server_0)"
                )

            # Multiple instances: warn and return first server (or client if no servers)
            servers = [i for i in active if i.type == "server"]
            if servers:
                logger.warning(
                    f"Multiple instances active ({names}), using {servers[0].name}. "
                    f"Set FV_INSTANCE to choose explicitly."
                )
                return servers[0]
            else:
                logger.warning(
                    f"Multiple instances active ({names}), using {active[0].name}."
                )
                return active[0]

        return active[0]

    @classmethod
    def detect_active(
        cls, config: Optional[FactoryVerseConfig] = None
    ) -> Optional[FactorioInstance]:
        """Auto-detect which Factorio instance is running.

        Tries to connect to known RCON ports in order:
        1. Server 0 (localhost:27000)
        2. Server 1 (localhost:27001)
        3. Server 2 (localhost:27002)
        4. Client (localhost:27100)

        Note: Servers are checked first since they're more commonly used for
        automated testing and agent runs.

        Returns:
            First responsive instance, or None if none found
        """
        cfg = config or get_config()

        # Try servers 0-2 first
        for server_id in range(3):
            server_instance = cls.get_server(server_id, cfg)
            if server_instance.test_connection():
                return server_instance

        # Try client
        client_instance = cls.get_client(cfg)
        if client_instance.test_connection():
            return client_instance

        return None

    @classmethod
    def get_client(
        cls, config: Optional[FactoryVerseConfig] = None
    ) -> FactorioInstance:
        """Get client instance configuration.

        Returns:
            FactorioInstance configured for local Factorio client
        """
        cfg = config or get_config()

        return FactorioInstance(
            type="client",
            server_id=None,
            script_output_dir=cfg.get_script_output_dir("client"),
            rcon_host=cfg.rcon_host,
            rcon_port=cfg.rcon_client_port,
            rcon_password=cfg.rcon_password,
        )

    @classmethod
    def get_server(
        cls, server_id: int, config: Optional[FactoryVerseConfig] = None
    ) -> FactorioInstance:
        """Get server instance configuration.

        Args:
            server_id: Server ID (0, 1, 2, ...)
            config: Optional config override

        Returns:
            FactorioInstance configured for Docker server
        """
        cfg = config or get_config()

        return FactorioInstance(
            type="server",
            server_id=server_id,
            script_output_dir=cfg.get_server_output_dir(server_id),
            rcon_host=cfg.rcon_host,
            rcon_port=cfg.get_rcon_port(f"server_{server_id}"),
            rcon_password=cfg.rcon_password,
        )

    @classmethod
    def list_available(
        cls, config: Optional[FactoryVerseConfig] = None
    ) -> List[FactorioInstance]:
        """List all potentially available instances (client + servers 0-2).

        Returns:
            List of FactorioInstance objects (may not all be running)
        """
        cfg = config or get_config()
        instances = [cls.get_client(cfg)]
        instances.extend([cls.get_server(i, cfg) for i in range(3)])
        return instances

    @classmethod
    def list_active(
        cls, config: Optional[FactoryVerseConfig] = None
    ) -> List[FactorioInstance]:
        """List all currently active (responsive) instances.

        Returns:
            List of FactorioInstance objects that respond to RCON
        """
        cfg = config or get_config()
        return [inst for inst in cls.list_available(cfg) if inst.test_connection()]

    @classmethod
    def set_active(cls, instance: FactorioInstance) -> None:
        """Set an instance as active via environment variable.

        Args:
            instance: Instance to set as active
        """
        os.environ[cls.ENV_INSTANCE] = instance.name
        logger.info(f"Set active instance: {instance.name}")
