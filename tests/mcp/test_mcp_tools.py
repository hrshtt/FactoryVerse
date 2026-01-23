"""Tests for MCP server tools and underlying infrastructure.

These tests verify that MCP tool handlers work correctly by:
1. Testing underlying infrastructure functions directly
2. Testing MCP tool handlers (bypassing MCP protocol layer)
3. Measuring timing to identify performance bottlenecks
"""

import asyncio
import time
import pytest
from unittest.mock import Mock, patch, MagicMock

from FactoryVerse.infra.mcp.server import FactoryVerseMCPServer
from FactoryVerse.infra.instance_manager import (
    FactorioInstanceManager,
    FactorioInstance,
)
from FactoryVerse.environment.config import get_config


class TestInstanceManagerDirect:
    """Test FactorioInstanceManager functions directly (no MCP layer)."""

    def test_list_available_returns_4_instances(self):
        """list_available should return 4 instances (client + 3 servers)."""
        config = get_config()
        instances = FactorioInstanceManager.list_available(config)

        assert len(instances) == 4
        names = [inst.name for inst in instances]
        assert "client" in names
        assert "server_0" in names
        assert "server_1" in names
        assert "server_2" in names

    def test_get_client_returns_valid_instance(self):
        """get_client should return a valid FactorioInstance."""
        config = get_config()
        client = FactorioInstanceManager.get_client(config)

        assert client.type == "client"
        assert client.server_id is None
        assert client.name == "client"
        assert client.rcon_port == config.rcon_client_port

    def test_get_server_returns_valid_instance(self):
        """get_server should return a valid FactorioInstance."""
        config = get_config()
        server = FactorioInstanceManager.get_server(0, config)

        assert server.type == "server"
        assert server.server_id == 0
        assert server.name == "server_0"

    def test_instance_creation_is_fast(self):
        """Creating instances (without connection test) should be fast."""
        config = get_config()

        start = time.time()
        instances = FactorioInstanceManager.list_available(config)
        elapsed = time.time() - start

        # Should take less than 100ms to create 4 instances
        assert elapsed < 0.1, f"Instance creation took {elapsed:.2f}s, expected < 0.1s"


class TestConnectionTimeout:
    """Test connection timeout behavior."""

    def test_connection_test_with_no_server_times_out(self):
        """test_connection should timeout reasonably when no server running."""
        config = get_config()
        # Use a high port that's unlikely to have anything running
        instance = FactorioInstance(
            type="server",
            server_id=99,
            script_output_dir=config.project_root / "test_output",
            rcon_host="127.0.0.1",
            rcon_port=59999,  # Unlikely to be in use
            rcon_password="test",
        )

        start = time.time()
        result = instance.test_connection()
        elapsed = time.time() - start

        assert result is False
        # This test documents current behavior - may be slow!
        # If this takes > 5s, that's the problem we need to fix
        print(f"Connection test to non-existent server took {elapsed:.2f}s")

    def test_connection_refused_is_fast(self):
        """Connection to localhost with refused port should be fast."""
        config = get_config()
        # Use localhost with a port that will quickly refuse
        instance = FactorioInstance(
            type="server",
            server_id=99,
            script_output_dir=config.project_root / "test_output",
            rcon_host="127.0.0.1",
            rcon_port=1,  # Should get connection refused quickly
            rcon_password="test",
        )

        start = time.time()
        result = instance.test_connection()
        elapsed = time.time() - start

        assert result is False
        # Connection refused should be fast (< 1s)
        assert elapsed < 1.0, f"Connection refused took {elapsed:.2f}s, expected < 1s"


class TestMCPToolHandlers:
    """Test MCP tool handler methods directly (bypassing protocol)."""

    @pytest.fixture
    def mcp_server(self):
        """Create MCP server instance for testing."""
        return FactoryVerseMCPServer()

    @pytest.mark.asyncio
    async def test_list_scenarios_is_fast(self, mcp_server):
        """_list_scenarios should complete quickly."""
        start = time.time()
        result = await mcp_server._list_scenarios({})
        elapsed = time.time() - start

        assert len(result) == 1  # Should return TextContent
        assert "scenarios" in result[0].text or "error" in result[0].text.lower()

        # Should complete in under 1 second
        assert elapsed < 1.0, f"list_scenarios took {elapsed:.2f}s, expected < 1s"

    @pytest.mark.asyncio
    async def test_list_sessions_is_fast(self, mcp_server):
        """_list_sessions should complete quickly (no external connections)."""
        start = time.time()
        result = await mcp_server._list_sessions({})
        elapsed = time.time() - start

        assert len(result) == 1
        # Should complete in under 1 second
        assert elapsed < 1.0, f"list_sessions took {elapsed:.2f}s, expected < 1s"

    @pytest.mark.asyncio
    async def test_list_envs_is_fast(self, mcp_server):
        """_list_envs should complete quickly when no envs exist."""
        start = time.time()
        result = await mcp_server._list_envs({})
        elapsed = time.time() - start

        assert len(result) == 1
        assert '"count": 0' in result[0].text or '"environments": []' in result[0].text

        # Should complete in under 100ms
        assert elapsed < 0.1, f"list_envs took {elapsed:.2f}s, expected < 0.1s"


class TestMCPListInstancesTiming:
    """Specific tests for list_instances timing issues."""

    @pytest.fixture
    def mcp_server(self):
        """Create MCP server instance for testing."""
        return FactoryVerseMCPServer()

    @pytest.mark.asyncio
    async def test_list_instances_with_mocked_connections(self, mcp_server):
        """list_instances should be fast when connections are mocked."""
        # Mock test_connection to return immediately
        with patch.object(FactorioInstance, 'test_connection', return_value=False):
            start = time.time()
            result = await mcp_server._list_instances({})
            elapsed = time.time() - start

        assert len(result) == 1
        assert "instances" in result[0].text

        # With mocked connections, should be very fast
        assert elapsed < 0.5, f"list_instances (mocked) took {elapsed:.2f}s, expected < 0.5s"

    @pytest.mark.asyncio
    async def test_list_instances_real_timing(self, mcp_server):
        """
        Test real timing of list_instances WITHOUT mocking.

        This test documents the actual performance issue.
        It may be slow - that's the point of the test.
        """
        start = time.time()
        result = await mcp_server._list_instances({})
        elapsed = time.time() - start

        assert len(result) == 1

        # Document the actual timing
        print(f"\n=== TIMING: _list_instances took {elapsed:.2f}s ===")

        # If this takes > 5s, we have a timeout issue
        # (4 instances * ~1s each = 4s minimum with current implementation)
        if elapsed > 5:
            pytest.fail(
                f"list_instances took {elapsed:.2f}s - this indicates a timeout issue. "
                "Consider adding connection timeouts to test_connection()."
            )


class TestScenarioListing:
    """Test scenario listing functionality."""

    def test_list_scenarios_from_config(self):
        """Config should list scenarios quickly."""
        config = get_config()

        start = time.time()
        scenarios = config.list_scenarios(include_local=True)
        elapsed = time.time() - start

        assert isinstance(scenarios, list)
        # Should complete quickly (file system operation)
        assert elapsed < 0.5, f"Scenario listing took {elapsed:.2f}s"

        print(f"Found {len(scenarios)} scenarios: {scenarios}")


class TestMCPServerCreation:
    """Test MCP server instantiation."""

    def test_server_creation_is_fast(self):
        """Creating MCP server should be fast (no external connections)."""
        start = time.time()
        server = FactoryVerseMCPServer()
        elapsed = time.time() - start

        assert server is not None
        assert elapsed < 0.5, f"Server creation took {elapsed:.2f}s"

    def test_server_has_required_attributes(self):
        """MCP server should have required attributes."""
        server = FactoryVerseMCPServer()

        assert hasattr(server, 'server')
        assert hasattr(server, '_environments')
        assert isinstance(server._environments, dict)
