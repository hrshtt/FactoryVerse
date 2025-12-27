"""
Smoke tests for the testing infrastructure.

These tests verify that the core fixtures work correctly:
- Server starts and RCON connects
- Agent can be created and destroyed
- TestGround can place and clear entities
"""


class TestServerFixtures:
    """Test server and RCON fixtures."""

    def test_rcon_connection(self, rcon):
        """Verify RCON connection works."""
        assert rcon.ping()

    def test_list_interfaces(self, rcon):
        """Verify remote interfaces are available."""
        interfaces = rcon.list_interfaces()
        assert "agent" in interfaces
        assert "test_ground" in interfaces
        assert "admin" in interfaces


class TestAgentFixtures:
    """Test agent creation and destruction."""

    def test_agent_created(self, agent):
        """Verify agent is created."""
        position = agent.get_position()
        assert "x" in position
        assert "y" in position

    def test_agent_inspect(self, agent):
        """Verify agent inspect works."""
        state = agent.inspect(attach_state=True)
        assert "agent_id" in state
        assert "position" in state
        assert "state" in state

    def test_agent_teleport(self, agent):
        """Verify agent can teleport."""
        result = agent.teleport(10, 10)
        # Teleport returns True on success
        assert result is True

        pos = agent.get_position()
        assert abs(pos["x"] - 10) < 1
        assert abs(pos["y"] - 10) < 1


class TestTestGroundFixtures:
    """Test TestGround fixture."""

    def test_place_resource(self, test_ground):
        """Verify resource placement works."""
        patch = test_ground.place_iron_patch(50, 50, size=4, amount=1000)

        assert patch.resource_name == "iron-ore"
        assert patch.total_tiles == 16  # 4x4
        assert patch.total_amount == 16000  # 16 * 1000

    def test_place_entity(self, test_ground):
        """Verify entity placement works."""
        entity = test_ground.place_entity("stone-furnace", 30, 30)

        assert entity.name == "stone-furnace"
        assert abs(entity.position[0] - 30) < 1
        assert abs(entity.position[1] - 30) < 1

    def test_clear_area(self, test_ground):
        """Verify area clearing works."""
        # Place some entities
        test_ground.place_entity("stone-furnace", 40, 40)
        test_ground.place_entity("stone-furnace", 42, 40)

        # Clear area
        cleared = test_ground.clear_area((35, 35), (50, 50))

        assert cleared >= 2

    def test_validate_entity(self, test_ground):
        """Verify entity validation works."""
        # Place entity
        test_ground.place_entity("iron-chest", 60, 60)

        # Validate
        assert test_ground.validate_entity_at("iron-chest", 60, 60)
        assert not test_ground.validate_entity_at("iron-chest", 100, 100)


class TestAdminFixtures:
    """Test admin fixture."""

    def test_admin_available(self, admin, rcon):
        """Verify admin interface is available."""
        interfaces = rcon.list_interfaces()
        assert "admin" in interfaces


class TestGameWorldFixture:
    """Test combined game_world fixture."""

    def test_game_world_components(self, game_world):
        """Verify game_world has all components."""
        assert game_world.agent is not None
        assert game_world.test_ground is not None
        assert game_world.admin is not None

    def test_game_world_workflow(self, game_world):
        """Test a simple workflow using game_world."""
        # Place a resource
        patch = game_world.test_ground.place_coal_patch(70, 70, size=4)
        assert patch.resource_name == "coal"

        # Teleport agent nearby
        game_world.agent.teleport(70, 70)

        # Check position
        pos = game_world.agent.get_position()
        assert abs(pos["x"] - 70) < 1
        assert abs(pos["y"] - 70) < 1


class TestCleanAreaFixture:
    """Test the clean_area fixture."""

    def test_clean_area_is_empty(self, clean_area):
        """Verify clean_area resets the test area."""
        metadata = clean_area.get_metadata()
        # After reset, should have no tracked entities
        assert metadata.get("entity_count", 0) == 0
