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
    """Test Tier 4 agent reconciliation logic (New vs Resume)."""
    # Mock mocks
    mock_env = MagicMock(spec=Environment)
    mock_env.config.tier4.agent_id = "test_agent"
    mock_env.config.tier4.variant = RuntimeVariant.MINIMAL
    # Mock Tier 6 so model capture works
    mock_env.tier6 = None
    mock_env.config.tier6 = MagicMock()
    mock_env.config.tier6.model = "test-model"

    # Mock Tier 3 with Registry
    mock_registry = MagicMock()
    mock_tier3 = MagicMock()
    mock_tier3.agent_registry = mock_registry
    mock_tier3.rcon_helper = MagicMock()
    mock_tier3.rcon_helper._create_agent = MagicMock()
    mock_tier3._udp_dispatcher.port = 1234
    mock_tier3.instance = "server_0"
    mock_env.tier3 = mock_tier3

    from FactoryVerse.environment.tiers.tier4_runtime import Tier4Runtime
    from FactoryVerse.agent.core.profile import AgentProfile, AgentStatus

    # Case 1: New Agent (Registry returns None)
    mock_registry.get_by_name.return_value = None

    tier4_new = Tier4Runtime(mock_env)
    # Patch internal methods we don't want to run
    tier4_new._setup_session_dir = AsyncMock(return_value=Path("/tmp"))
    tier4_new._load_embodied_actions = AsyncMock()
    tier4_new._load_reachable_view = AsyncMock()

    await tier4_new.initialize()

    # Check registration happened
    mock_registry.register.assert_called_once()
    registered_profile = mock_registry.register.call_args[0][0]
    assert registered_profile.name == "test_agent"
    assert registered_profile.status == AgentStatus.ACTIVE

    # Check creation with destroy_existing=True
    mock_tier3.rcon_helper._create_agent.assert_called_with(
        udp_port=1234, destroy_existing=True
    )

    # Case 2: Resume Agent (Registry returns Profile)
    mock_registry.reset_mock()
    mock_tier3.rcon_helper._create_agent.reset_mock()

    existing_profile = AgentProfile(
        name="test_agent",
        instance_id="server_0",
        model="old-model",  # Should not be overridden by current config model
        description="Existing agent",
        status=AgentStatus.PAUSED,
    )
    mock_registry.get_by_name.return_value = existing_profile

    tier4_resume = Tier4Runtime(mock_env)
    tier4_resume._setup_session_dir = AsyncMock(return_value=Path("/tmp"))
    tier4_resume._load_embodied_actions = AsyncMock()
    tier4_resume._load_reachable_view = AsyncMock()

    await tier4_resume.initialize()

    # Check status update
    mock_registry.save.assert_called_once()
    assert existing_profile.status == AgentStatus.ACTIVE

    # Check creation with destroy_existing=False (Binding)
    mock_tier3.rcon_helper._create_agent.assert_called_with(
        udp_port=1234, destroy_existing=False
    )
