"""
Pytest configuration for FactoryVerse tests with test-ground scenario.

This configuration provides:
- Session-scoped Factorio instance connection
- Test-ground scenario helpers
- Auto-reset between tests
- Snapshot control
- Resource/entity placement fixtures
"""

import pytest
from pathlib import Path
from typing import Generator
import subprocess
import time

from FactoryVerse.dsl.agent import PlayingFactory
from helpers.test_ground import TestGround


# ============================================================================
# Path Fixtures
# ============================================================================

@pytest.fixture
def project_root() -> Path:
    """Return the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture
def mod_dir(project_root: Path) -> Path:
    """Return the Factorio Verse mod directory."""
    return project_root / "src" / "factorio_verse"


@pytest.fixture
def scenarios_dir(project_root: Path) -> Path:
    """Return the scenarios directory."""
    return project_root / "src" / "factorio" / "scenarios"


@pytest.fixture
def config_dir(project_root: Path) -> Path:
    """Return the config directory."""
    return project_root / "src" / "factorio" / "config"


@pytest.fixture
def output_dir(project_root: Path) -> Path:
    """Return the output directory."""
    return project_root / ".fv-output"


# ============================================================================
# Docker & Server Fixtures
# ============================================================================

@pytest.fixture(scope="module")
def docker_available() -> bool:
    """Check if Docker is available."""
    try:
        subprocess.run(["docker", "version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


@pytest.fixture
def docker_manager():
    """Provide a ClusterManager instance for testing."""
    from FactoryVerse.infra.docker import ClusterManager
    return ClusterManager()


@pytest.fixture
def wait_for_server():
    """Helper to wait for a server to be ready."""
    def _wait(port: int, timeout: int = 30):
        import socket
        start = time.time()
        while time.time() - start < timeout:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex(('localhost', port))
                sock.close()
                if result == 0:
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        return False
    return _wait


# ============================================================================
# Factory & Test Ground Fixtures
# ============================================================================

@pytest.fixture(scope="session")
def factory_instance() -> Generator[PlayingFactory, None, None]:
    """
    Session-scoped factory instance connected to test-ground scenario.
    
    This fixture:
    - Connects to Factorio running test-ground scenario
    - Creates an agent for testing
    - Provides DSL access for tests
    - Persists across all tests in session
    - Cleans up on session end
    
    Yields:
        PlayingFactory: Connected factory instance
    """
    from factorio_rcon import RCONClient
    from FactoryVerse import dsl
    import json
    
    # TODO: Make these configurable via environment variables
    rcon_client = RCONClient("localhost", 27100, "factorio")
    
    # Warm up RCON
    rcon_client.send_command("/c rcon.print('hello world')")
    rcon_client.send_command("/c rcon.print('hello world')")
    
    # Create an agent for testing with specific UDP port
    agent_udp_port = 24389
    agent_result = rcon_client.send_command(
        f'/c rcon.print(helpers.table_to_json(remote.call("agent", "create_agent", {agent_udp_port}, true, false, "player", {{}})))'
    )
    
    # Enable all recipes and research all technologies for testing
    rcon_client.send_command("/c for _, tech in pairs(game.forces.player.technologies) do tech.researched = true end")
    rcon_client.send_command("/c for _, recipe in pairs(game.forces.player.recipes) do recipe.enabled = true end")
    
    agent_info = json.loads(agent_result)
    agent_id = agent_info["agent_id"]
    agent_interface_name = agent_info["interface_name"]
    
    # Configure DSL with the created agent
    dsl.configure(
        rcon_client=rcon_client,
        agent_id=agent_interface_name,
        snapshot_dir=None,  # Will be set per-test if needed
        db_path=None,  # In-memory database
        agent_udp_port=agent_udp_port  # Enable async actions in tests
    )
    
    # Enter playing context
    with dsl.playing_factorio() as factory:
        # Store numeric agent_id for admin commands
        factory._numeric_agent_id = agent_id
        yield factory
    
    # Cleanup: destroy agent
    rcon_client.send_command('/c remote.call("agent", "destroy_agents")')



@pytest.fixture(scope="session")
def test_ground(factory_instance: PlayingFactory) -> TestGround:
    """
    Session-scoped test ground helper.
    
    Provides high-level helpers for:
    - Resource placement
    - Entity placement
    - Area management
    - Snapshot control
    
    Returns:
        TestGround: Test ground helper instance
    """
    return TestGround(factory_instance._rcon)


# ============================================================================
# Auto-Reset Fixture
# ============================================================================

@pytest.fixture(autouse=False)  # Disabled for now - tests handle their own cleanup
def reset_between_tests(test_ground: TestGround, factory_instance: PlayingFactory):
    """
    Automatically reset game state between tests.
    
    NOTE: Currently disabled because it clears state before tests can validate.
    Tests should handle their own cleanup for now.
    """
    # Pre-test setup
    # test_ground.reset_test_area()
    
    # Reset player position (TODO: implement sync position reset)
    # factory_instance.walking.to(0, 0)  # This is async, skip for now
    
    # TODO: Reset inventory to default state
    # factory_instance._reset_inventory(factory_instance._test_default_inventory)
    
    # Force re-snapshot after reset
    # test_ground.force_resnapshot()
    
    # Wait for snapshot to complete
    # TODO: Poll snapshot status until complete
    # time.sleep(2)
    
    yield  # Test runs here
    
    # Post-test cleanup (if needed)
    pass


# ============================================================================
# Resource Location Fixtures
# ============================================================================

@pytest.fixture
def iron_ore_patch(test_ground: TestGround):
    """
    Provide a known iron ore patch.
    
    Places a 32x32 iron ore patch at (64, -64) with 10000 per tile.
    
    Returns:
        dict: Patch metadata including position, size, amount
    """
    result = test_ground.place_iron_patch(x=64, y=-64, size=32, amount=10000)
    # Force re-snapshot
    test_ground.force_resnapshot()
    time.sleep(1)
    return result


@pytest.fixture
def copper_ore_patch(test_ground: TestGround):
    """
    Provide a known copper ore patch.
    
    Places a 32x32 copper ore patch at (-64, -64) with 10000 per tile.
    
    Returns:
        dict: Patch metadata including position, size, amount
    """
    result = test_ground.place_copper_patch(x=-64, y=-64, size=32, amount=10000)
    test_ground.force_resnapshot()
    time.sleep(1)
    return result


@pytest.fixture
def coal_patch(test_ground: TestGround):
    """
    Provide a known coal patch.
    
    Places a 32x32 coal patch at (64, 64) with 10000 per tile.
    
    Returns:
        dict: Patch metadata including position, size, amount
    """
    result = test_ground.place_coal_patch(x=64, y=64, size=32, amount=10000)
    test_ground.force_resnapshot()
    time.sleep(1)
    return result


@pytest.fixture
def stone_patch(test_ground: TestGround):
    """
    Provide a known stone patch.
    
    Places a 32x32 stone patch at (-64, 64) with 10000 per tile.
    
    Returns:
        dict: Patch metadata including position, size, amount
    """
    result = test_ground.place_stone_patch(x=-64, y=64, size=32, amount=10000)
    test_ground.force_resnapshot()
    time.sleep(1)
    return result


@pytest.fixture
def all_resource_patches(iron_ore_patch, copper_ore_patch, coal_patch, stone_patch):
    """
    Provide all basic resource patches.
    
    Returns:
        dict: All patch metadata
    """
    return {
        "iron": iron_ore_patch,
        "copper": copper_ore_patch,
        "coal": coal_patch,
        "stone": stone_patch
    }


# ============================================================================
# Empty Area Fixtures
# ============================================================================

@pytest.fixture
def empty_test_area(test_ground: TestGround):
    """
    Provide coordinates for a guaranteed empty area.
    
    Returns:
        tuple: (x, y, width, height) of empty area
    """
    # Area at (100, 100) with 20x20 size
    # This is away from resource patches
    return (100, 100, 20, 20)


# ============================================================================
# Pytest Configuration
# ============================================================================

def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "requires_scenario: marks tests that require test-ground scenario"
    )
    config.addinivalue_line(
        "markers", "snapshot: marks tests that validate snapshot accuracy"
    )
    config.addinivalue_line(
        "markers", "dsl: marks tests that validate DSL operations"
    )
    config.addinivalue_line(
        "markers", "mod: marks tests that validate mod behavior"
    )
