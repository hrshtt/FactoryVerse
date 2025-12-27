# FactoryVerse Tests

Test suite for FactoryVerse DSL and mod.

## Quick Start

```bash
# Run all tests (server auto-starts if needed)
uv run pytest tests/

# Run specific test file
uv run pytest tests/test_infrastructure.py -v

# Run with specific marker
uv run pytest -m "not slow" tests/
```

## Fixture Hierarchy

```
factorio_server (session)     # Auto-starts Docker, manages RCON
    └── rcon (function)       # RCON connection with xpcall error handling
        ├── agent (function)  # Fresh agent per test
        ├── test_ground       # Test area setup helpers
        ├── admin             # Admin commands (add items, unlock, etc.)
        └── game_world        # Combined access to all of the above
```

## Example Test

```python
class TestMyFeature:
    def test_place_and_mine(self, game_world):
        # Setup: place a resource patch
        patch = game_world.test_ground.place_iron_patch(100, 100, size=4)
        
        # Act: teleport agent and mine
        game_world.agent.teleport(100, 100)
        result = game_world.agent.mine_resource("iron-ore", 10)
        
        # Assert
        assert result["queued"]
```

## Available Fixtures

### `rcon` (function scope)
Raw RCON connection with xpcall wrapper. All Lua errors include tracebacks.

```python
def test_raw_rcon(rcon):
    result = rcon.call("test_ground", "get_test_metadata")
    assert result["entity_count"] >= 0
```

### `agent` (function scope)
Fresh agent created per test. Destroyed after test completes.

```python
def test_agent(agent):
    pos = agent.get_position()
    agent.teleport(10, 10)
    agent.walk_to(20, 20)  # Async - returns immediately
```

### `test_ground` (function scope)
Test area setup helpers.

```python
def test_setup(test_ground):
    test_ground.place_iron_patch(50, 50, size=32)
    test_ground.place_entity("stone-furnace", 60, 60)
    test_ground.clear_area((0, 0), (100, 100))
```

### `clean_area` (function scope)
Same as `test_ground` but resets the 512x512 area before the test.

```python
def test_clean_slate(clean_area):
    # Area is guaranteed empty
    metadata = clean_area.get_metadata()
    assert metadata["entity_count"] == 0
```

### `admin` (function scope)
Admin operations for test setup.

```python
def test_with_items(admin, agent):
    admin.add_items(1, {"iron-plate": 100, "coal": 50})
    admin.unlock_all_technologies()
```

### `game_world` (function scope)
Combined access to agent, test_ground, and admin.

```python
def test_full_workflow(game_world):
    game_world.test_ground.place_coal_patch(80, 80, size=8)
    game_world.agent.teleport(80, 80)
    game_world.admin.add_items(1, {"burner-mining-drill": 1})
```

## Server Lifecycle

The `factorio_server` fixture (session scope) handles Docker:

1. **Startup**: If container not running, starts `factorio_0`
2. **Health check**: Waits for RCON to respond
3. **Teardown**: Stops container if we started it

Override config via `server_config` fixture:

```python
@pytest.fixture(scope="session")
def server_config():
    return ServerConfig(
        rcon_port=27000,
        startup_timeout=60
    )
```

## Markers

- `@pytest.mark.slow` - Tests that take >5 seconds
- `@pytest.mark.requires_restart` - Tests that require server restart

## Files

```
tests/
├── conftest.py           # All fixtures
├── helpers/
│   ├── server.py        # FactorioServer, RconConnection
│   └── test_ground.py   # TestGround helper
├── test_infrastructure.py  # Smoke tests for fixtures
└── ...                   # Your tests
```
