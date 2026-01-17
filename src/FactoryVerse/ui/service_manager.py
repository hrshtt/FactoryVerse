"""Unified service management using Environment module."""

import asyncio
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

from FactoryVerse.config import get_config
from FactoryVerse.environment import (
    Environment,
    EnvironmentConfig,
    InfraConfig,
    SettingsConfig,
    InfraMode,
    Tier,
)
from FactoryVerse.infra.instance_manager import FactorioInstanceManager

logger = logging.getLogger(__name__)


@dataclass
class ServiceStatus:
    name: str
    id: str
    running: bool
    status_text: str
    details: Dict
    actions: List[str]


class ServiceManager:
    """Centralized manager for all FactoryVerse services via Environment."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ServiceManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.config = get_config()
        self.work_dir = self.config.project_root
        self._initialized = True

    async def get_all_statuses(self) -> List[ServiceStatus]:
        """Fetch status for all services using Environment."""
        statuses = []

        # 1. Factorio Client Status
        try:
            # Ephemeral environment for client check
            env_client = Environment(
                config=EnvironmentConfig(tier1=InfraConfig(mode=InfraMode.CLIENT))
            )
            await env_client.initialize(up_to=Tier.FACTORIO_INFRA)

            if env_client.tier1:
                client_stat = await env_client.tier1.verify_ready()
                client_running = bool(client_stat.details.get("client_running"))

                statuses.append(
                    ServiceStatus(
                        name="Factorio Client",
                        id="client",
                        running=client_running,
                        status_text="Running" if client_running else "Stopped",
                        details={
                            "factorio_installed": client_stat.details.get(
                                "factorio_installed"
                            ),
                            "mods_installed": client_stat.details.get("mods_installed"),
                        },
                        actions=["stop", "restart"] if client_running else ["start"],
                    )
                )
        except Exception as e:
            logger.error(f"Error checking client status: {e}")
            statuses.append(
                ServiceStatus(
                    name="Factorio Client",
                    id="client",
                    running=False,
                    status_text="Error checking status",
                    details={"error": str(e)},
                    actions=[],
                )
            )

        # 2. Docker Infrastructure Status
        try:
            # Ephemeral environment for server/docker check
            env_server = Environment(
                config=EnvironmentConfig(tier1=InfraConfig(mode=InfraMode.SERVER))
            )
            # We initialize to get the server manager and compose manager
            await env_server.initialize(up_to=Tier.FACTORIO_INFRA)

            if env_server.tier1:
                server_stat = await env_server.tier1.verify_ready()
                docker_active = bool(server_stat.details.get("server_running"))

                # Note: Tier1Status doesn't give container count natively yet,
                # but we can infer active state.

                statuses.append(
                    ServiceStatus(
                        name="Docker Infrastructure",
                        id="docker",
                        running=docker_active,
                        status_text="Active" if docker_active else "Inactive",
                        details={
                            "ports_available": server_stat.details.get(
                                "ports_available"
                            )
                        },
                        actions=["stop", "restart"] if docker_active else ["start"],
                    )
                )
        except Exception as e:
            logger.error(f"Error checking docker status: {e}")
            statuses.append(
                ServiceStatus(
                    name="Docker Infrastructure",
                    id="docker",
                    running=False,
                    status_text="Error checking status",
                    details={"error": str(e)},
                    actions=[],
                )
            )

        # 3. Individual Instances (Active Connections)
        # Used by Tier 3/4 but managed independently for now
        try:
            instances = FactorioInstanceManager.list_available()
            for inst in instances:
                active = inst.test_connection()
                statuses.append(
                    ServiceStatus(
                        name=f"Instance: {inst.name}",
                        id=f"inst_{inst.name}",
                        running=active,
                        status_text="Connected" if active else "Disconnected",
                        details={
                            "type": inst.type,
                            "rcon": f"{inst.rcon_host}:{inst.rcon_port}",
                            "script_output": str(inst.script_output_dir),
                        },
                        actions=[],  # Connection status is passive
                    )
                )
        except Exception as e:
            logger.error(f"Error checking instances: {e}")

        return statuses

    async def start_client(self, scenario: Optional[str] = None):
        """Start the Factorio client."""
        scenario = scenario or "test-ground"

        # Helper to run in async context properly
        async def _start():
            config = EnvironmentConfig(
                tier1=InfraConfig(mode=InfraMode.CLIENT),
                tier2=SettingsConfig(scenario=scenario, peaceful=True),
            )
            env = Environment(config=config)

            try:
                await env.initialize(up_to=Tier.SETTINGS)
                if env.tier1 and env.tier2:
                    launch_args = env.tier2.get_launch_args()
                    await env.tier1.start_client(**launch_args)
            except Exception as e:
                logger.error(f"Failed to start client: {e}")
                raise

        await _start()

    async def stop_client(self):
        """Stop the Factorio client."""

        async def _stop():
            env = Environment(
                config=EnvironmentConfig(tier1=InfraConfig(mode=InfraMode.CLIENT))
            )
            await env.initialize(up_to=Tier.FACTORIO_INFRA)
            if env.tier1:
                await env.tier1.stop_client()

        await _stop()

    async def start_docker(self, num_servers: int = 1, scenario: str = "test-ground"):
        """Start Docker services."""

        async def _start():
            config = EnvironmentConfig(
                tier1=InfraConfig(mode=InfraMode.SERVER, server_count=num_servers),
                tier2=SettingsConfig(scenario=scenario, peaceful=True),
            )
            env = Environment(config=config)

            try:
                await env.initialize(up_to=Tier.SETTINGS)
                if env.tier1:
                    await env.tier1.start_server(
                        scenario=scenario, num_instances=num_servers
                    )
            except Exception as e:
                logger.error(f"Failed to start docker: {e}")
                raise

        await _start()

    async def stop_docker(self):
        """Stop Docker services."""

        async def _stop():
            env = Environment(
                config=EnvironmentConfig(tier1=InfraConfig(mode=InfraMode.SERVER))
            )
            await env.initialize(up_to=Tier.FACTORIO_INFRA)
            if env.tier1:
                await env.tier1.stop_server()

        await _stop()
