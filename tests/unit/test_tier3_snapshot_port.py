from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from FactoryVerse.environment.tiers.tier3_python import Tier3Python


def test_configures_allocated_snapshot_port_and_verifies_it():
    infra = MagicMock()
    infra.get_snapshot_port.return_value = 55800
    environment = SimpleNamespace(
        config=SimpleNamespace(infra_config=infra),
    )
    tier3 = Tier3Python(environment)
    tier3._instance = "server_0"
    tier3._map_api = MagicMock()
    tier3._map_api.set_udp_port.return_value = {"success": True, "port": 55800}
    tier3._map_api.get_udp_port.return_value = 55800

    tier3._configure_snapshot_udp_port()

    infra.get_snapshot_port.assert_called_once_with("server_0")
    tier3._map_api.set_udp_port.assert_called_once_with(55800)
    tier3._map_api.get_udp_port.assert_called_once_with()


def test_initialize_configures_snapshot_before_starting_udp(monkeypatch):
    calls: list[str] = []
    infra = SimpleNamespace(
        get_rcon_port=lambda instance: 55500,
        rcon_host="localhost",
        rcon_password="factorio",
    )
    environment = SimpleNamespace(
        config=SimpleNamespace(
            infra_config=infra,
            tier3=SimpleNamespace(udp_enabled=True),
        )
    )
    tier3 = Tier3Python(environment)

    monkeypatch.setattr(tier3, "_determine_instance", lambda: "server_0")

    async def init_rcon(*args):
        calls.append("rcon")

    async def init_udp():
        calls.append("udp")

    async def init_rcon_helper():
        calls.append("rcon_helper")

    async def verify_connection():
        calls.append("verify")

    async def init_agent_registry():
        calls.append("registry")

    monkeypatch.setattr(tier3, "_init_rcon", init_rcon)
    monkeypatch.setattr(
        tier3,
        "_configure_snapshot_udp_port",
        lambda: calls.append("snapshot_port"),
    )
    monkeypatch.setattr(tier3, "_init_udp", init_udp)
    monkeypatch.setattr(tier3, "_init_rcon_helper", init_rcon_helper)
    monkeypatch.setattr(tier3, "_verify_connection", verify_connection)
    monkeypatch.setattr(tier3, "_init_agent_registry", init_agent_registry)

    import asyncio

    asyncio.run(tier3.initialize())

    assert calls == [
        "rcon",
        "snapshot_port",
        "udp",
        "rcon_helper",
        "verify",
        "registry",
    ]


def test_retries_once_when_fresh_save_consumes_first_console_mutation():
    infra = MagicMock()
    infra.get_snapshot_port.return_value = 55800
    environment = SimpleNamespace(config=SimpleNamespace(infra_config=infra))
    tier3 = Tier3Python(environment)
    tier3._instance = "server_0"
    tier3._map_api = MagicMock()
    tier3._map_api.set_udp_port.return_value = {"success": True, "port": 55800}
    tier3._map_api.get_udp_port.side_effect = [34400, 55800]

    tier3._configure_snapshot_udp_port()

    assert tier3._map_api.set_udp_port.call_count == 2
    assert tier3._map_api.get_udp_port.call_count == 2
