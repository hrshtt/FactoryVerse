"""
RCON Smoke Test for FactoryVerse

This test verifies basic RCON connectivity and agent operations work.
It requires a running Factorio server with the factorio_verse mod loaded.

Run with:
    uv run pytest tests/integration/test_rcon_smoke.py -v

Prerequisites:
    - Factorio server running with factorio_verse mod
    - RCON enabled on port 27015 (default)
    - RCON password configured (see conftest.py or environment)
"""

import json
import os
import pytest
from pathlib import Path


# Skip all tests if RCON is not available
pytestmark = pytest.mark.integration


def get_rcon_client():
    """Create an RCON client for testing.
    
    Tries to import factorio_rcon package, falls back to simple socket implementation.
    """
    try:
        import factorio_rcon
        
        host = os.environ.get("FACTORIO_RCON_HOST", "localhost")
        port = int(os.environ.get("FACTORIO_RCON_PORT", "27100"))
        password = os.environ.get("FACTORIO_RCON_PASSWORD", "")
        
        # Try to read password from config file if not in env
        if not password:
            config_path = Path(__file__).parent.parent.parent / "src" / "factorio" / "config" / "rconpw"
            if config_path.exists():
                password = config_path.read_text().strip()
        
        client = factorio_rcon.RCONClient(host, port, password)
        return client
    except ImportError:
        pytest.skip("factorio_rcon package not installed")
    except Exception as e:
        pytest.skip(f"Could not create RCON client: {e}")


@pytest.fixture
def rcon():
    """Provide an RCON client for tests."""
    client = get_rcon_client()
    try:
        # Test connection
        client.send_command("/c rcon.print('test')")
        yield client
    except Exception as e:
        pytest.skip(f"RCON connection failed: {e}")


class TestRconSmoke:
    """Basic RCON smoke tests."""
    
    def test_rcon_connection(self, rcon):
        """Test that RCON connection works."""
        result = rcon.send_command("/c rcon.print('hello')")
        assert result is not None
        assert "hello" in result
    
    def test_remote_interfaces_available(self, rcon):
        """Test that factorio_verse remote interfaces are registered."""
        result = rcon.send_command("/c rcon.print(helpers.table_to_json(remote.interfaces))")
        assert result is not None
        
        interfaces = json.loads(result)
        
        # Check core interfaces exist
        assert "agent" in interfaces, "agent interface should exist"
        assert "map" in interfaces, "map interface should exist"
        assert "entities" in interfaces, "entities interface should exist"
        
        # Check agent interface has expected methods
        assert "create_agents" in interfaces["agent"], "agent.create_agents should exist"
        assert "destroy_agents" in interfaces["agent"], "agent.destroy_agents should exist"
    
    def test_agent_creation(self, rcon):
        """Test that agents can be created via RCON."""
        # Destroy any existing agents first
        rcon.send_command("/c remote.call('agent', 'destroy_agents', {1, 2, 3}, false)")
        
        # Create an agent
        result = rcon.send_command(
            "/c rcon.print(helpers.table_to_json(remote.call('agent', 'create_agents', 1, true)))"
        )
        assert result is not None
        
        agents = json.loads(result)
        assert len(agents) >= 1, "Should create at least one agent"
        assert agents[0]["agent_id"] == 1, "First agent should have ID 1"
        
        # Verify agent interface was created
        interfaces_result = rcon.send_command("/c rcon.print(helpers.table_to_json(remote.interfaces))")
        interfaces = json.loads(interfaces_result)
        assert "agent_1" in interfaces, "agent_1 interface should exist after creation"
    
    def test_agent_inspect(self, rcon):
        """Test that agent state can be inspected."""
        # Ensure agent exists
        rcon.send_command("/c remote.call('agent', 'create_agents', 1, true)")
        
        # Inspect agent
        result = rcon.send_command(
            "/c rcon.print(helpers.table_to_json(remote.call('agent_1', 'inspect')))"
        )
        assert result is not None
        
        state = json.loads(result)
        
        # Verify expected fields
        assert "agent_id" in state, "Should have agent_id"
        assert state["agent_id"] == 1, "Agent ID should be 1"
        assert "tick" in state, "Should have tick"
        assert "position" in state, "Should have position"
        assert "x" in state["position"], "Position should have x"
        assert "y" in state["position"], "Position should have y"
    
    def test_agent_inspect_with_inventory(self, rcon):
        """Test that agent inventory can be inspected."""
        # Ensure agent exists
        rcon.send_command("/c remote.call('agent', 'create_agents', 1, true)")
        
        # Inspect with inventory
        result = rcon.send_command(
            "/c rcon.print(helpers.table_to_json(remote.call('agent_1', 'inspect', true, false)))"
        )
        assert result is not None
        
        state = json.loads(result)
        assert "inventory" in state, "Should have inventory when requested"
        assert isinstance(state["inventory"], (dict, list)), "Inventory should be dict or list"
    
    def test_agent_get_activity_state(self, rcon):
        """Test that agent activity state can be queried."""
        # Ensure agent exists
        rcon.send_command("/c remote.call('agent', 'create_agents', 1, true)")
        
        # Get activity state
        result = rcon.send_command(
            "/c rcon.print(helpers.table_to_json(remote.call('agent_1', 'get_activity_state')))"
        )
        assert result is not None
        
        state = json.loads(result)
        
        # Verify expected activity state structure
        assert "walking" in state, "Should have walking state"
        assert "mining" in state, "Should have mining state"
        assert "crafting" in state, "Should have crafting state"
        
        # Check walking state fields
        assert "active" in state["walking"], "Walking should have active field"
        
        # Check mining state fields
        assert "active" in state["mining"], "Mining should have active field"
        
        # Check crafting state fields
        assert "active" in state["crafting"], "Crafting should have active field"
    
    def test_agent_teleport(self, rcon):
        """Test that agent can be teleported."""
        # Ensure agent exists
        rcon.send_command("/c remote.call('agent', 'create_agents', 1, true)")
        
        # Teleport to a known position
        target = {"x": 25, "y": 25}
        result = rcon.send_command(
            f"/c rcon.print(helpers.table_to_json(remote.call('agent_1', 'teleport', {{x={target['x']}, y={target['y']}}})))"
        )
        
        # Verify position changed
        inspect_result = rcon.send_command(
            "/c rcon.print(helpers.table_to_json(remote.call('agent_1', 'inspect')))"
        )
        state = json.loads(inspect_result)
        
        # Allow some tolerance for position
        assert abs(state["position"]["x"] - target["x"]) < 2, "X should be near target"
        assert abs(state["position"]["y"] - target["y"]) < 2, "Y should be near target"
    
    def test_agent_destruction(self, rcon):
        """Test that agents can be destroyed."""
        # Create agent
        rcon.send_command("/c remote.call('agent', 'create_agents', 1, true)")
        
        # Verify it exists
        interfaces_before = json.loads(
            rcon.send_command("/c rcon.print(helpers.table_to_json(remote.interfaces))")
        )
        assert "agent_1" in interfaces_before, "agent_1 should exist before destroy"
        
        # Destroy agent
        result = rcon.send_command(
            "/c rcon.print(helpers.table_to_json(remote.call('agent', 'destroy_agents', {1}, false)))"
        )
        destroy_result = json.loads(result)
        assert 1 in destroy_result.get("destroyed", []), "Agent 1 should be destroyed"
        
        # Verify interface is removed
        interfaces_after = json.loads(
            rcon.send_command("/c rcon.print(helpers.table_to_json(remote.interfaces))")
        )
        assert "agent_1" not in interfaces_after, "agent_1 should not exist after destroy"


class TestScenarioTestRunner:
    """Tests for the scenario-based test runner."""
    
    def test_test_runner_interface_exists(self, rcon):
        """Test that test_runner interface is available (if scenario is loaded)."""
        result = rcon.send_command("/c rcon.print(helpers.table_to_json(remote.interfaces))")
        interfaces = json.loads(result)
        
        # test_runner only exists if test_scenario is loaded
        if "test_runner" not in interfaces:
            pytest.skip("test_runner interface not available - test_scenario not loaded")
        
        # Verify expected methods
        assert "run_all_tests" in interfaces["test_runner"]
        assert "run_test" in interfaces["test_runner"]
        assert "list_tests" in interfaces["test_runner"]
    
    def test_list_tests(self, rcon):
        """Test listing available tests."""
        result = rcon.send_command("/c rcon.print(helpers.table_to_json(remote.interfaces))")
        interfaces = json.loads(result)
        
        if "test_runner" not in interfaces:
            pytest.skip("test_runner interface not available")
        
        tests_result = rcon.send_command(
            "/c rcon.print(remote.call('test_runner', 'list_tests'))"
        )
        tests = json.loads(tests_result)
        
        assert isinstance(tests, list), "list_tests should return a list"
        assert len(tests) > 0, "Should have some tests registered"
    
    def test_run_single_test(self, rcon):
        """Test running a single test."""
        result = rcon.send_command("/c rcon.print(helpers.table_to_json(remote.interfaces))")
        interfaces = json.loads(result)
        
        if "test_runner" not in interfaces:
            pytest.skip("test_runner interface not available")
        
        # Run a simple sync test
        test_result = rcon.send_command(
            "/c rcon.print(remote.call('test_runner', 'run_test', 'agent.test_create'))"
        )
        result = json.loads(test_result)
        
        # Should have test result structure
        assert "test_name" in result or "error" in result, "Should have test result or error"

