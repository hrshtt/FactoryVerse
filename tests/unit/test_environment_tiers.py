import pytest
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from FactoryVerse.environment.environment import Environment, Tier
from FactoryVerse.environment.config import (
    EnvironmentConfig,
    RuntimeVariant,
    InteractionMode,
)


@pytest.mark.asyncio
async def test_environment_initialization_defaults():
    """Test environment initialization with default config."""
    env = Environment()
    assert env.config is not None
    assert env.tier1 is None
    assert env._initialized_up_to is None


@pytest.mark.asyncio
async def test_environment_convenience_constructors():
    """Test convenience constructors create correct configs."""
    # For testing
    env_test = Environment.for_testing(variant="minimal")
    assert env_test.config.tier4.variant == RuntimeVariant.MINIMAL

    # For agent
    env_agent = Environment.for_agent(mode="autonomous", provider="openai")
    assert env_agent.config.tier6.mode == InteractionMode.AUTONOMOUS
    assert env_agent.config.tier6.llm_provider == "openai"


@pytest.mark.asyncio
async def test_environment_lifecycle_flow():
    """Test the initialization flow through tiers."""
    # Mock tier classes to avoid actual side effects
    with (
        patch("FactoryVerse.environment.environment.Tier1Factorio") as MockTier1,
        patch("FactoryVerse.environment.environment.Tier2Settings") as MockTier2,
        patch("FactoryVerse.environment.environment.Tier3Python") as MockTier3,
        patch("FactoryVerse.environment.environment.Tier4Runtime") as MockTier4,
    ):
        # Setup mocks
        for MockClass in [MockTier1, MockTier2, MockTier3, MockTier4]:
            instance = MockClass.return_value
            instance.verify_prerequisites = AsyncMock(
                return_value=MagicMock(satisfied=True)
            )
            instance.initialize = AsyncMock()
            instance.verify_ready = AsyncMock(return_value=MagicMock(is_ready=True))
            # Set is_ready property to initially False, then True after init (simulated)
            type(instance).is_ready = unittest.mock.PropertyMock(
                side_effect=[False, True]
            )

        env = Environment()

        # Initialize up to Tier 2
        await env.initialize(up_to=Tier.SETTINGS)

        assert env.tier1 is not None
        assert env.tier2 is not None
        assert env.tier3 is None

        env.tier1.initialize.assert_called_once()
        env.tier2.initialize.assert_called_once()

        # Initialize up to Tier 4
        await env.initialize(up_to=Tier.RUNTIME)

        assert env.tier3 is not None
        assert env.tier4 is not None

        env.tier3.initialize.assert_called_once()
        env.tier4.initialize.assert_called_once()


@pytest.mark.asyncio
async def test_environment_reset_logic():
    """Test that reset only affects specified tier and above."""
    env = Environment()

    # Mock initialized tiers
    env._tier1 = AsyncMock()
    env._tier2 = AsyncMock()
    env._tier3 = AsyncMock()
    env._tier4 = AsyncMock()

    # Reset from Tier 3
    await env.reset(from_tier=Tier.PYTHON_INFRA)

    # Check calls
    env._tier4.reset.assert_called_once()
    env._tier3.reset.assert_called_once()
    env._tier2.reset.assert_not_called()
    env._tier1.reset.assert_not_called()


@pytest.mark.asyncio
async def test_tier4_agent_reconciliation():
    """Test Tier 4 agent reconciliation logic with query-first pattern.

    The new implementation queries Lua first (SSOT), then decides:
    - BIND: If agent exists with correct port and valid entity
    - DESTROY+CREATE: If agent exists but port mismatch or invalid entity
    - CREATE: If no existing agent
    """
    # Mock environment
    mock_env = MagicMock(spec=Environment)
    mock_env.config.tier4.agent_id = "test_agent"
    mock_env.config.tier4.variant = RuntimeVariant.MINIMAL
    # Mock Tier 6 so model capture works
    mock_env.tier6 = None
    mock_env.config.tier6 = MagicMock()
    mock_env.config.tier6.model = "test-model"

    # Mock infra_config with get_agent_port for deterministic port allocation
    mock_env.config.infra_config = MagicMock()
    expected_udp_port = 34202  # Expected port from get_agent_port(0, 0) for server_0
    mock_env.config.infra_config.get_agent_port = MagicMock(return_value=expected_udp_port)

    # Mock Tier 3 with new Lua query methods (SSOT pattern)
    mock_registry = MagicMock()
    mock_tier3 = MagicMock()
    mock_tier3.agent_registry = mock_registry
    mock_tier3.rcon_helper = MagicMock()
    mock_tier3._udp_dispatcher.port = 1234  # This should NOT be used anymore
    mock_tier3.instance = "server_0"
    # New query-first pattern methods
    mock_tier3.list_game_agents = MagicMock(return_value=[])  # No agents initially
    mock_tier3.create_game_agent = MagicMock(return_value={"agent_id": "test_agent"})
    mock_tier3.destroy_game_agents = MagicMock(return_value={"destroyed": [], "errors": []})
    mock_env.tier3 = mock_tier3

    from FactoryVerse.environment.tiers.tier4_runtime import Tier4Runtime
    from FactoryVerse.agent.core.profile import AgentProfile, AgentStatus

    # Case 1: New Agent (No agent in Lua, registry returns None)
    mock_registry.get_by_name.return_value = None
    mock_tier3.list_game_agents.return_value = []  # No agents in Factorio

    tier4_new = Tier4Runtime(mock_env)
    # Patch internal methods we don't want to run
    tier4_new._setup_session_dir = AsyncMock(return_value=Path("/tmp"))
    tier4_new._setup_executor = AsyncMock()
    tier4_new._load_embodied_actions = AsyncMock()
    tier4_new._load_ghost_builder = AsyncMock()
    tier4_new._load_reachable_view = AsyncMock()
    tier4_new._load_placement_hints = AsyncMock()

    await tier4_new.initialize()

    # Verify query-first pattern: list_game_agents called first
    mock_tier3.list_game_agents.assert_called_once()

    # Check agent created with correct parameters
    mock_tier3.create_game_agent.assert_called_once_with(
        udp_port=expected_udp_port,
        set_unique_forces=False,
        default_common_force="player",
    )

    # Check registration happened in Python registry
    mock_registry.register.assert_called_once()
    registered_profile = mock_registry.register.call_args[0][0]
    assert registered_profile.name == "test_agent"
    assert registered_profile.status == AgentStatus.ACTIVE

    # Verify get_agent_port was called with correct arguments
    # "test_agent" parses as agent_index=0 (fallback), server_0 gives server_index=0
    mock_env.config.infra_config.get_agent_port.assert_called_with(0, 0)

    # Case 2: Bind to existing agent (agent exists with correct port)
    mock_registry.reset_mock()
    mock_tier3.list_game_agents.reset_mock()
    mock_tier3.create_game_agent.reset_mock()
    mock_tier3.destroy_game_agents.reset_mock()
    mock_env.config.infra_config.get_agent_port.reset_mock()

    # Agent exists in Lua with correct port
    mock_tier3.list_game_agents.return_value = [
        {
            "id": 1,
            "interface_name": "test_agent",
            "udp_port": expected_udp_port,
            "entity_valid": True,
            "position": {"x": 0, "y": 0},
        }
    ]

    existing_profile = AgentProfile(
        name="test_agent",
        instance_id="server_0",
        model="old-model",
        description="Existing agent",
        status=AgentStatus.PAUSED,
    )
    mock_registry.get_by_name.return_value = existing_profile

    tier4_bind = Tier4Runtime(mock_env)
    tier4_bind._setup_session_dir = AsyncMock(return_value=Path("/tmp"))
    tier4_bind._setup_executor = AsyncMock()
    tier4_bind._load_embodied_actions = AsyncMock()
    tier4_bind._load_ghost_builder = AsyncMock()
    tier4_bind._load_reachable_view = AsyncMock()
    tier4_bind._load_placement_hints = AsyncMock()

    await tier4_bind.initialize()

    # Should query and then BIND (no create, no destroy)
    mock_tier3.list_game_agents.assert_called_once()
    mock_tier3.create_game_agent.assert_not_called()  # BIND, not CREATE
    mock_tier3.destroy_game_agents.assert_not_called()

    # Check status update in Python registry
    mock_registry.save.assert_called_once()
    assert existing_profile.status == AgentStatus.ACTIVE

    # Case 3: Recreate agent (port mismatch)
    mock_registry.reset_mock()
    mock_tier3.list_game_agents.reset_mock()
    mock_tier3.create_game_agent.reset_mock()
    mock_tier3.destroy_game_agents.reset_mock()

    # Agent exists but with wrong port
    wrong_port = 99999
    mock_tier3.list_game_agents.return_value = [
        {
            "id": 42,
            "interface_name": "test_agent",
            "udp_port": wrong_port,  # Wrong port!
            "entity_valid": True,
            "position": {"x": 0, "y": 0},
        }
    ]
    mock_registry.get_by_name.return_value = existing_profile

    tier4_recreate = Tier4Runtime(mock_env)
    tier4_recreate._setup_session_dir = AsyncMock(return_value=Path("/tmp"))
    tier4_recreate._setup_executor = AsyncMock()
    tier4_recreate._load_embodied_actions = AsyncMock()
    tier4_recreate._load_ghost_builder = AsyncMock()
    tier4_recreate._load_reachable_view = AsyncMock()
    tier4_recreate._load_placement_hints = AsyncMock()

    await tier4_recreate.initialize()

    # Should DESTROY then CREATE
    mock_tier3.list_game_agents.assert_called_once()
    mock_tier3.destroy_game_agents.assert_called_once_with([42])  # Destroy by numeric ID
    mock_tier3.create_game_agent.assert_called_once_with(
        udp_port=expected_udp_port,
        set_unique_forces=False,
        default_common_force="player",
    )
