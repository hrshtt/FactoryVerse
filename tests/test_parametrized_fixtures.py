"""
Test the parametrized fixtures to verify they work correctly.
"""

import pytest
from FactoryVerse.environment.environment import Environment
from FactoryVerse.environment.config import RuntimeVariant


@pytest.mark.asyncio
class TestParametrizedFixtures:
    """Test that parametrized fixtures work correctly."""

    async def test_environment_variant_parametrization(self, environment_variant: Environment):
        """Test that environment_variant runs for both variants."""
        # This test will run twice (once for MINIMAL, once for FULL)
        assert environment_variant.tier4 is not None
        variant = environment_variant.tier4.config.variant
        assert variant in [RuntimeVariant.MINIMAL, RuntimeVariant.FULL]
        
        # FULL variant should have remote_view, MINIMAL should not
        if variant == RuntimeVariant.FULL:
            assert environment_variant.tier4.remote_view is not None
        else:
            assert environment_variant.tier4.remote_view is None

    async def test_environment_scenario_parametrization(self, environment_scenario: Environment):
        """Test that environment_scenario runs for each discovered scenario."""
        # This test will run once per discovered scenario
        assert environment_scenario.tier2 is not None
        scenario = environment_scenario.tier2.current_scenario
        assert scenario is not None
        assert scenario in ["test-ground", "freeplay", "default_lab_scenario", "lab_play", "wipwip"]

    async def test_embodied_actions_work_all_variants(self, environment_variant: Environment):
        """Verify embodied actions work in both MINIMAL and FULL variants."""
        actions = environment_variant.tier4.embodied_actions
        assert actions is not None
        assert "movement" in actions or "walking" in actions
        assert "placement" in actions
        assert "crafting" in actions


@pytest.mark.asyncio
class TestFactoryFixture:
    """Test the environment_factory fixture."""

    async def test_factory_with_custom_scenario(self, environment_factory, available_scenarios):
        """Test factory with custom scenario."""
        # Use first available scenario (or test-ground if available)
        scenario = "test-ground" if "test-ground" in available_scenarios else available_scenarios[0]
        
        env = await environment_factory(tier2={"scenario": scenario})
        try:
            assert env.tier2.current_scenario == scenario
            assert env.tier4 is not None
        finally:
            await env.shutdown()

    async def test_factory_with_full_variant(self, environment_factory):
        """Test factory with FULL variant."""
        env = await environment_factory(tier4={"variant": RuntimeVariant.FULL})
        try:
            assert env.tier4.config.variant == RuntimeVariant.FULL
            assert env.tier4.remote_view is not None
        finally:
            await env.shutdown()

    async def test_factory_combines_configs(self, environment_factory, available_scenarios):
        """Test factory can combine multiple config overrides."""
        scenario = "test-ground" if "test-ground" in available_scenarios else available_scenarios[0]
        
        env = await environment_factory(
            tier2={"scenario": scenario},
            tier4={"variant": RuntimeVariant.FULL},
        )
        try:
            assert env.tier2.current_scenario == scenario
            assert env.tier4.config.variant == RuntimeVariant.FULL
            assert env.tier4.remote_view is not None
        finally:
            await env.shutdown()
