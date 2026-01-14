"""
Pytest configuration for FactoryVerse tests.

Auto-manages Factorio server lifecycle:
- Starts Docker container if not running (session scope)
- Creates fresh agent per test (function scope)
- Cleans up on session end

Server Fixture Hierarchy:
    factorio_server (session) -> rcon (function) -> agent (function)
"""

import pytest
import sys
from pathlib import Path
from typing import Generator, Any, Optional

# Add tests directory to path for helper imports
tests_dir = Path(__file__).parent
if str(tests_dir) not in sys.path:
    sys.path.insert(0, str(tests_dir))

from helpers.server import FactorioServer, RconConnection, ServerConfig
from helpers.test_ground import TestGround


# ============================================================================
# SERVER FIXTURES (Session Scope)
# ============================================================================


@pytest.fixture(scope="session")
def server_config() -> ServerConfig:
    """Server configuration. Override in conftest.py or via environment."""
    return ServerConfig()


@pytest.fixture(scope="session")
def factorio_server(
    server_config: ServerConfig,
) -> Generator[Optional[FactorioServer], None, None]:
    """
    Session-scoped Factorio server.

    Starts Docker container if not running.
    Stops on session end if we started it.
    
    Returns None if FV_INSTANCE=client (uses local client instead).
    """
    import os
    
    # Skip Docker if using client
    if os.getenv("FV_INSTANCE") == "client":
        # Return None - rcon fixture will handle client connection
        yield None
        return
    
    server = FactorioServer(server_config)
    server.ensure_running()

    yield server

    server.stop()


# ============================================================================
# RCON FIXTURES (Function Scope)
# ============================================================================


@pytest.fixture(scope="function")
def rcon(factorio_server) -> RconConnection:
    """
    Function-scoped RCON connection.

    Uses FV_INSTANCE env var to determine connection:
    - If FV_INSTANCE=client: Connects to local Factorio client (no Docker)
    - Otherwise: Uses Docker server (factorio_server fixture)
    """
    import os
    from FactoryVerse.config import get_config
    from FactoryVerse.infra.instance_manager import FactorioInstanceManager
    from factorio_rcon import RCONClient
    
    instance_name = os.getenv("FV_INSTANCE")
    
    # If client is explicitly requested, connect to client (skip Docker)
    if instance_name == "client":
        config = get_config()
        instance = FactorioInstanceManager.get_client(config)
        client = RCONClient(
            instance.rcon_host,
            instance.rcon_port,
            instance.rcon_password,
        )
        client.connect()
        return RconConnection(client)
    
    # Otherwise use Docker server
    if factorio_server is None:
        raise RuntimeError("factorio_server fixture returned None but FV_INSTANCE is not 'client'")
    return factorio_server.rcon


# ============================================================================
# TEST GROUND FIXTURES
# ============================================================================


@pytest.fixture(scope="function")
def test_ground(rcon: RconConnection) -> TestGround:
    """
    TestGround helper for test setup.

    Provides:
    - Resource placement (place_iron_patch, etc.)
    - Entity placement (place_entity, etc.)
    - Area management (clear_area, reset_test_area)
    - Snapshot control (force_resnapshot)
    """
    return TestGround(rcon)


@pytest.fixture(scope="function")
def clean_area(test_ground: TestGround) -> Generator[TestGround, None, None]:
    """
    TestGround with clean test area.

    Resets the 512x512 test area before test runs.
    Use when you need a completely empty map.
    """
    test_ground.reset_test_area()
    yield test_ground


# ============================================================================
# AGENT FIXTURES
# ============================================================================


@pytest.fixture(scope="function")
def agent_id(rcon: RconConnection) -> Generator[str, None, None]:
    """
    Create a fresh agent for testing.

    Agent is destroyed after test completes.
    Returns the agent interface name (e.g., "agent_1").
    """
    # Create agent
    result = rcon.call("agent", "create_agent", 34202, True, False, "player", {})
    interface_name = result["interface_name"]

    yield interface_name

    # Cleanup: destroy all agents
    rcon.call("agent", "destroy_agents", 0)


@pytest.fixture(scope="function")
def agent(rcon: RconConnection, agent_id: str) -> "AgentInterface":
    """
    Agent interface for testing.

    Provides methods to interact with the agent:
    - walk_to, mine_resource, craft_enqueue (async)
    - place_entity, pickup_entity, teleport (sync)
    - inspect, get_inventory, get_position (queries)
    """
    return AgentInterface(rcon, agent_id)


class AgentInterface:
    """
    Wrapper around agent remote interface.

    Provides typed access to agent methods with proper error handling.
    """

    def __init__(self, rcon: RconConnection, interface_name: str):
        self.rcon = rcon
        self.interface_name = interface_name

    def call(self, method: str, *args) -> Any:
        """Call an agent method."""
        return self.rcon.call(self.interface_name, method, *args)

    # Queries
    def inspect(self, attach_state: bool = False) -> dict:
        """Get agent position and optionally activity state."""
        return self.call("inspect", attach_state)

    def get_position(self) -> dict:
        """Get agent position."""
        return self.call("get_position")

    def get_inventory(self) -> dict:
        """Get agent inventory contents."""
        return self.call("get_inventory_items")

    def get_reachable(self, attach_ghosts: bool = True) -> dict:
        """Get reachable entities, resources, and ghosts."""
        return self.call("get_reachable", attach_ghosts)

    # Sync actions
    def teleport(self, x: float, y: float) -> dict:
        """Teleport agent to position."""
        return self.call("teleport", {"x": x, "y": y})

    def place_entity(
        self,
        entity_name: str,
        x: float,
        y: float,
        direction: int = None,
        ghost: bool = False,
    ) -> dict:
        """Place entity from inventory."""
        return self.call(
            "place_entity", entity_name, {"x": x, "y": y}, direction, ghost
        )

    def pickup_entity(self, entity_name: str, x: float = None, y: float = None) -> dict:
        """Pick up entity into inventory."""
        pos = {"x": x, "y": y} if x is not None else None
        return self.call("pickup_entity", entity_name, pos)

    def set_entity_recipe(
        self, entity_name: str, x: float, y: float, recipe_name: str
    ) -> dict:
        """Set recipe on a machine."""
        return self.call(
            "set_entity_recipe", entity_name, {"x": x, "y": y}, recipe_name
        )

    def take_inventory_item(
        self,
        entity_name: str,
        x: float,
        y: float,
        inventory_type: str,
        item_name: str,
        count: int = None,
    ) -> dict:
        """Take items from entity inventory."""
        return self.call(
            "take_inventory_item",
            entity_name,
            {"x": x, "y": y},
            inventory_type,
            item_name,
            count,
        )

    def put_inventory_item(
        self,
        entity_name: str,
        x: float,
        y: float,
        inventory_type: str,
        item_name: str,
        count: int,
    ) -> dict:
        """Put items into entity inventory."""
        return self.call(
            "put_inventory_item",
            entity_name,
            {"x": x, "y": y},
            inventory_type,
            item_name,
            count,
        )

    def reset(self, reset_force: bool = False) -> dict:
        """Reset agent (double-call pattern - call twice to confirm)."""
        return self.call("reset", reset_force)

    # Async actions (these need UDP handling for completion - just queue for now)
    def walk_to(self, x: float, y: float, strict: bool = False) -> dict:
        """Start walking to position. Returns immediately, action completes async."""
        return self.call("walk_to", {"x": x, "y": y}, strict, {})

    def stop_walking(self) -> dict:
        """Stop current walking action."""
        return self.call("stop_walking")

    def mine_resource(self, resource_name: str, max_count: int = None) -> dict:
        """Start mining resource. Returns immediately, action completes async."""
        return self.call("mine_resource", resource_name, max_count)

    def stop_mining(self) -> dict:
        """Stop current mining action."""
        return self.call("stop_mining")

    def craft_enqueue(self, recipe_name: str, count: int = 1) -> dict:
        """Queue crafting. Returns immediately, action completes async."""
        return self.call("craft_enqueue", recipe_name, count)

    def craft_dequeue(self, recipe_name: str, count: int = None) -> dict:
        """Cancel queued crafting."""
        return self.call("craft_dequeue", recipe_name, count)


# ============================================================================
# ADMIN FIXTURES
# ============================================================================


@pytest.fixture(scope="function")
def admin(rcon: RconConnection) -> "AdminInterface":
    """
    Admin interface for test setup.

    Provides:
    - add_items: Add items to agent inventory
    - clear_inventory: Clear agent inventory
    - unlock_technology: Unlock a technology
    """
    return AdminInterface(rcon)


class AdminInterface:
    """Wrapper around admin remote interface."""

    def __init__(self, rcon: RconConnection):
        self.rcon = rcon

    def add_items(self, agent_id: int, items: dict) -> None:
        """Add items to agent inventory."""
        self.rcon.call("admin", "add_items", agent_id, items)

    def clear_inventory(self, agent_id: int) -> None:
        """Clear agent inventory."""
        self.rcon.call("admin", "clear_inventory", agent_id)

    def unlock_technology(self, tech_name: str) -> None:
        """Unlock a technology."""
        self.rcon.call("admin", "unlock_technology", tech_name)

    def unlock_all_technologies(self) -> None:
        """Unlock all technologies."""
        self.rcon.execute(
            "for _, tech in pairs(game.forces.player.technologies) do tech.researched = true end"
        )

    def enable_all_recipes(self) -> None:
        """Enable all recipes."""
        self.rcon.execute(
            "for _, recipe in pairs(game.forces.player.recipes) do recipe.enabled = true end"
        )


# ============================================================================
# CONVENIENCE FIXTURES
# ============================================================================


@pytest.fixture(scope="function")
def game_world(agent: AgentInterface, test_ground: TestGround, admin: AdminInterface):
    """
    Complete game world fixture.

    Provides:
    - agent: Agent interface for actions
    - test_ground: Test setup helpers
    - admin: Admin commands
    """
    return GameWorld(agent, test_ground, admin)


class GameWorld:
    """Aggregate fixture providing complete game access."""

    def __init__(
        self, agent: AgentInterface, test_ground: TestGround, admin: AdminInterface
    ):
        self.agent = agent
        self.test_ground = test_ground
        self.admin = admin


# ============================================================================
# PYTEST CONFIGURATION
# ============================================================================


def pytest_configure(config):
    """Register pytest markers."""
    config.addinivalue_line("markers", "slow: marks tests as slow")
    config.addinivalue_line(
        "markers", "requires_restart: marks tests that require server restart"
    )
