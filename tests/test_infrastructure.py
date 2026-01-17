"""
Smoke tests for the testing infrastructure using the Environment module.

These tests verify that the Environment allows access to:
- RCON (Tier 3)
- Agent Runtime (Tier 4)
"""

import pytest
from FactoryVerse.environment.environment import Environment


@pytest.mark.asyncio
class TestEnvironmentBasics:
    """Test environment access."""

    async def test_rcon_connection(self, environment: Environment):
        """Verify RCON connection works via Tier 3."""
        assert environment.tier3 is not None
        assert environment.tier3.rcon_helper is not None
        # Send a simple command to verify connection
        # Use rcon_client directly as ping() is not available
        response = environment.tier3.rcon_helper.rcon_client.send_command("/h")
        assert response is not None
        # Allow checking against common help outputs or error if command invalid
        assert (
            "Help" in response or "Unknown subcommand" in response or len(response) > 0
        )

    async def test_list_interfaces(self, environment: Environment):
        """Verify remote interfaces are available."""
        # interfaces is a property returning a dict/list
        interfaces = environment.tier3.rcon_helper.interfaces
        assert interfaces is not None
        assert "agent" in interfaces
        assert "admin" in interfaces
        print(f"\nℹ️ Admin Interface Methods: {interfaces['admin']}")
        print(f"ℹ️ Agent Interface Methods: {interfaces['agent']}")


@pytest.mark.asyncio
class TestRuntimeBasics:
    """Test runtime and agent functionality."""

    async def test_agent_created(self, environment: Environment):
        """Verify agent is created in Tier 4."""
        assert environment.tier4 is not None
        assert environment.tier4.agent_id is not None

        # Verify we can get position via RCON directly using agent_interface
        # Note: Tier4 defaults agent_id="agent_1" which IS the interface name
        agent_interface = environment.tier4.agent_id

        pos = environment.tier3.rcon_helper.run(agent_interface, "get_position", {})
        assert pos is not None
        assert "x" in pos
        assert "y" in pos

    async def test_embodied_actions_loaded(self, environment_variant: Environment):
        """Verify embodied actions are loaded in both variants."""
        assert environment_variant.tier4.embodied_actions is not None
        assert "movement" in environment_variant.tier4.embodied_actions
        assert "placement" in environment_variant.tier4.embodied_actions

    async def test_agent_inspect(self, environment: Environment):
        """Verify agent inspect works."""
        agent_interface = environment.tier4.agent_id
        # Use RCON helper directly, 'inspect' usually returns the agent state dict
        state = environment.tier3.rcon_helper.run(agent_interface, "inspect", {})
        assert state is not None
        # Depending on inspect impl, check keys
        assert "position" in state
        assert (
            "state" in state
        )  # Inspect returns internal state including walking, mining, etc.

    async def test_agent_teleport(self, environment: Environment):
        """Verify agent can teleport."""
        agent_interface = environment.tier4.agent_id

        # Teleport
        target_pos = {"x": 10, "y": 10}
        result = environment.tier3.rcon_helper.run(
            agent_interface, "teleport", target_pos
        )
        # Teleport usually returns nothing or success
        # Check result if needed, but important is the effect

        # Check position
        pos = environment.tier3.rcon_helper.run(agent_interface, "get_position", {})
        assert abs(pos["x"] - 10) < 1
        assert abs(pos["y"] - 10) < 1
