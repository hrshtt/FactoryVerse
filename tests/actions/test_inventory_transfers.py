"""Tests for inventory transfer operations.

This test suite validates the action issues reported:
1. create_item_stacks() returns empty list when it shouldn't
2. take_fuel() fails silently
3. Mining returns empty list but inventory updates
4. Placement validation issues
"""

import pytest
from FactoryVerse.game.factory.types import MapPosition


class TestCreateItemStacks:
    """Test create_item_stacks() behavior."""

    async def test_create_item_stacks_with_sufficient_items(
        self, dsl_context, admin, agent_id
    ):
        """create_item_stacks should return stacks when items are available."""
        agent_idx = int(agent_id.split("_")[1])
        admin.add_items(agent_idx, {"coal": 25})

        runtime = dsl_context.runtime
        stacks = runtime.inventory.create_item_stacks("coal", 10)

        assert len(stacks) > 0, "Should return at least one stack when items are available"
        assert all(s.name == "coal" for s in stacks), "All stacks should be coal"
        assert sum(s.count for s in stacks) <= 25, "Total count should not exceed available"

    async def test_create_item_stacks_returns_empty_when_none_available(
        self, dsl_context
    ):
        """create_item_stacks should return [] when no items available."""
        runtime = dsl_context.runtime
        stacks = runtime.inventory.create_item_stacks("coal", 10)
        assert stacks == [], "Should return empty list when no items available"

    async def test_create_item_stacks_with_exact_count(self, dsl_context, admin, agent_id):
        """create_item_stacks should work with exact count."""
        agent_idx = int(agent_id.split("_")[1])
        admin.add_items(agent_idx, {"coal": 25})

        runtime = dsl_context.runtime
        stacks = runtime.inventory.create_item_stacks("coal", 25, number_of_stacks=1)

        assert len(stacks) == 1, "Should return exactly one stack"
        assert stacks[0].count == 25, "Stack should have exact count"

    async def test_create_item_stacks_with_half_stack(self, dsl_context, admin, agent_id):
        """create_item_stacks should work with 'half' count."""
        agent_idx = int(agent_id.split("_")[1])
        admin.add_items(agent_idx, {"coal": 50})  # Coal stack size is 50

        runtime = dsl_context.runtime
        stacks = runtime.inventory.create_item_stacks("coal", "half", number_of_stacks=1)

        assert len(stacks) > 0, "Should return at least one stack"
        # Half of 50 is 25
        assert stacks[0].count == 25, f"Half stack should be 25, got {stacks[0].count}"

    async def test_create_item_stacks_with_full_stack(self, dsl_context, admin, agent_id):
        """create_item_stacks should work with 'full' count."""
        agent_idx = int(agent_id.split("_")[1])
        admin.add_items(agent_idx, {"coal": 50})

        runtime = dsl_context.runtime
        stacks = runtime.inventory.create_item_stacks("coal", "full", number_of_stacks=1)

        assert len(stacks) == 1, "Should return exactly one stack"
        assert stacks[0].count == 50, f"Full stack should be 50, got {stacks[0].count}"


class TestTakeFuel:
    """Test take_fuel() operations."""

    async def test_take_fuel_from_furnace(
        self, dsl_context, admin, agent_id, test_ground
    ):
        """take_fuel should extract fuel from burner entity."""
        # Setup: Place furnace, add fuel, agent nearby
        test_ground.place_entity("stone-furnace", 10, 10)
        agent_idx = int(agent_id.split("_")[1])
        admin.add_items(agent_idx, {"coal": 10})

        runtime = dsl_context.runtime
        await runtime.walking.walk_to(MapPosition(10, 10))

        furnace = runtime.reachable.get_entity("stone-furnace")
        assert furnace is not None, "Furnace should be reachable"

        # Add fuel to furnace
        coal_stacks = runtime.inventory.create_item_stacks("coal", 5)
        assert len(coal_stacks) > 0, "Should have coal stacks to add"
        furnace.add_fuel(coal_stacks[0])

        # Verify fuel was added (check inventory count decreased)
        initial_coal = runtime.inventory.check_total("coal")
        assert initial_coal < 10, "Some coal should have been used"

        # Take fuel back
        result = furnace.take_fuel("coal", count=2)
        assert len(result) > 0, "take_fuel should return item stacks"
        assert all(item.name == "coal" for item in result), "All items should be coal"

        # Verify coal is back in agent inventory
        final_coal = runtime.inventory.check_total("coal")
        assert final_coal > initial_coal, "Coal should be back in agent inventory"

    async def test_take_fuel_handles_errors_gracefully(
        self, dsl_context, test_ground
    ):
        """take_fuel should not fail silently - should raise or return empty."""
        test_ground.place_entity("stone-furnace", 10, 10)

        runtime = dsl_context.runtime
        await runtime.walking.walk_to(MapPosition(10, 10))

        furnace = runtime.reachable.get_entity("stone-furnace")
        assert furnace is not None

        # Try to take fuel from empty furnace
        # Should either return empty list or raise exception, not fail silently
        result = furnace.take_fuel("coal", count=1)
        # If no fuel, should return empty list (not None, not error silently)
        assert isinstance(result, list), "Should return a list (even if empty)"


class TestMiningReturns:
    """Test mining operation return values."""

    async def test_mining_returns_item_stacks(self, dsl_context, test_ground):
        """mine() should return ItemStack list even if inventory updates."""
        test_ground.place_iron_patch(50, 50, size=16)

        runtime = dsl_context.runtime
        await runtime.walking.walk_to(MapPosition(50, 50))

        resources = runtime.reachable.get_resources("iron-ore")
        assert len(resources) > 0, "Should find iron ore resources"

        initial_count = runtime.inventory.check_total("iron-ore")
        items = await resources[0].mine(max_count=25)

        # Should return item stacks (not empty list)
        assert isinstance(items, list), "Should return a list"
        # Even if empty, should be a list
        # But ideally should have items
        if len(items) == 0:
            # If empty, verify inventory still updated (bug case)
            final_count = runtime.inventory.check_total("iron-ore")
            if final_count > initial_count:
                pytest.fail(
                    "Mining returned empty list but inventory updated - this is the bug!"
                )

    async def test_mining_inventory_consistency(self, dsl_context, test_ground):
        """Mining return value should match inventory update."""
        test_ground.place_iron_patch(50, 50, size=16)

        runtime = dsl_context.runtime
        await runtime.walking.walk_to(MapPosition(50, 50))

        resources = runtime.reachable.get_resources("iron-ore")
        initial_count = runtime.inventory.check_total("iron-ore")

        items = await resources[0].mine(max_count=25)
        final_count = runtime.inventory.check_total("iron-ore")

        # If items returned, count should match inventory increase
        if len(items) > 0:
            returned_count = sum(item.count for item in items)
            inventory_increase = final_count - initial_count
            assert (
                returned_count == inventory_increase
            ), f"Returned count ({returned_count}) should match inventory increase ({inventory_increase})"


class TestPlacementValidation:
    """Test placement validation issues."""

    async def test_placement_away_from_current_position(
        self, dsl_context, admin, agent_id, test_ground
    ):
        """Placing entities should work when not at current position."""
        agent_idx = int(agent_id.split("_")[1])
        admin.add_items(agent_idx, {"iron-chest": 1})

        runtime = dsl_context.runtime
        current_pos = runtime.walking.current_position

        # Place entity away from current position
        target_pos = MapPosition(current_pos.x + 5, current_pos.y + 5)
        chest_item = runtime.inventory.get_item("iron-chest")
        assert chest_item is not None, "Should have iron-chest in inventory"

        result = chest_item.place(target_pos)
        assert result is not None, "Placement should succeed away from agent"

    async def test_placement_validation_handles_occupied_tiles(
        self, dsl_context, admin, agent_id, test_ground
    ):
        """Placement should handle occupied tiles gracefully."""
        # Place first entity
        test_ground.place_entity("iron-chest", 10, 10)

        agent_idx = int(agent_id.split("_")[1])
        admin.add_items(agent_idx, {"iron-chest": 1})

        runtime = dsl_context.runtime
        await runtime.walking.walk_to(MapPosition(10, 10))

        # Try to place another chest at same position
        chest_item = runtime.inventory.get_item("iron-chest")
        if chest_item:
            # Should either fail with clear error or succeed (if it replaces)
            # But should not fail silently
            try:
                result = chest_item.place(MapPosition(10, 10))
                # If succeeds, that's fine (replacement)
            except Exception as e:
                # If fails, should have clear error message
                assert len(str(e)) > 0, "Error should have message"
