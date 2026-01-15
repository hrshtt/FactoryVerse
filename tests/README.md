# FactoryVerse Tests

Test suite for FactoryVerse Factory (Factorio Objects) and mod.

## Test Organization

Tests are organized by **domain** to enable targeted test runs and encourage reuse. When adding new tests:

1. **Find a fitting domain** - Check if an existing directory matches your test's functionality
2. **Reuse if close enough** - If your test is similar to an existing domain, add it there
3. **Create a new domain** - Only create a new directory if the domain is truly distinct

---

## Domain Structure

```
tests/
├── conftest.py                 # Root fixtures (server, RCON, agent, etc.)
├── README.md                   # This file
├── helpers/                    # Shared test utilities
│   ├── server.py              # FactorioServer, RconConnection
│   └── test_ground.py         # TestGround helper
│
├── actions/                    # Agent action tests
│   ├── test_walking.py        # walk_to, stop_walking
│   ├── test_mining.py         # mine_resource, stop_mining
│   ├── test_crafting.py       # craft_enqueue, craft_dequeue
│   ├── test_placement.py      # place_entity, pickup_entity
│   ├── test_inventory.py      # inventory transfers, items
│   └── test_research.py       # research actions
│
├── entities/                   # Entity-specific behavior tests
│   ├── test_furnaces.py       # Furnace inspection, fueling, smelting
│   ├── test_drills.py         # Mining drill output, resource targeting
│   ├── test_assemblers.py     # Recipe setting, crafting progress
│   ├── test_inserters.py      # Pickup/drop positions, filters
│   ├── test_containers.py     # Chests, inventory operations
│   ├── test_power.py          # Poles, boilers, steam engines
│   └── test_belts.py          # Transport belts, splitters, loaders
│
├── connect/                    # Connection/wiring tests
│   ├── test_belts.py          # Belt-to-belt connections
│   ├── test_pipes.py          # Fluid pipe connections
│   ├── test_poles.py          # Electric pole networks
│   └── test_inserters.py      # Inserter placement relative to machines
│
├── factory/                   # Python Factory (Factorio Objects) layer tests
│   ├── conftest.py            # Factory (Factorio Objects)-specific fixtures (PlayingFactory, etc.)
│   ├── test_playing_factory.py # Context manager, session state
│   ├── test_reachable.py      # Reachable entity queries
│   ├── test_map_db.py         # DuckDB map queries
│   ├── test_entity_views.py   # Reachable, Remote, Ghost views
│   └── test_prototypes.py     # Prototype loading, caching
│
├── sync/                       # Data synchronization tests
│   ├── conftest.py            # Sync-specific fixtures (UDPCapture, GhostTestContext)
│   ├── test_udp_sync.py       # SyncService UDP handling, ghost operations
│   ├── test_snapshot_loader.py # SnapshotLoader file parsing, replay
│   └── test_ghost_snapshot.py # Ghost placement, conversion, label tracking (integration)
│
├── functional/                 # Multi-step workflow tests
│   ├── test_iron_smelting.py  # Drill → Furnace → Plate production
│   ├── test_automated_mining.py # Inserter-fed mining setup
│   ├── test_power_setup.py    # Boiler → Engine → Pole network
│   └── test_factory_unit.py   # Complete factory unit setups
│
├── multiagent/                 # Multi-agent coordination tests
│   ├── test_agent_creation.py # Multiple agent lifecycle
│   ├── test_shared_resources.py # Agents sharing entities
│   └── test_forces.py         # Force-based agent separation
│
├── eval/                       # Evaluation & benchmarking
│   ├── test_scenarios.py      # Scenario loading, validation
│   ├── test_objectives.py     # Goal completion tracking
│   └── test_metrics.py        # Performance/progress metrics
│
├── infra/                      # Infrastructure tests
│   ├── conftest.py            # Infrastructure-specific fixtures (Jupyter runtime, etc.)
│   ├── test_boilerplate_integration.py # LLM boilerplate E2E integration tests
│   ├── test_server.py         # Server startup, health checks
│   ├── test_rcon.py           # RCON connection, commands
│   └── test_docker.py         # Docker compose, containers
│
└── mod/                        # Lua mod tests (run inside Factorio)
    ├── test_remote_interfaces.py # Remote interface availability
    └── test_events.py         # Event handlers, custom events
```

---

## Running Tests by Domain

```bash
# Run all tests
uv run pytest

# Run specific domain
uv run pytest tests/actions/
uv run pytest tests/entities/
uv run pytest tests/factory/
uv run pytest tests/functional/
uv run pytest tests/infra/  # Infrastructure tests (boilerplate, Jupyter runtime)

# Run multiple domains
uv run pytest tests/actions/ tests/entities/

# Run specific test file
uv run pytest tests/entities/test_furnaces.py -v

# Run with marker
uv run pytest -m "not slow"
uv run pytest -m "integration"
```

---

## Fixture Hierarchy

```
factorio_server (session)     # Auto-starts Docker, manages RCON
    └── rcon (function)       # RCON connection with xpcall error handling
        ├── agent (function)  # Fresh agent per test
        ├── test_ground       # Test area setup helpers
        ├── admin             # Admin commands (add items, unlock, etc.)
        └── game_world        # Combined access to all of the above
```

---

## Agent Lifecycle

Agents must be properly created and destroyed to avoid resource leaks and test interference.

### Creating an Agent

```python
# Via RCON - returns agent interface name (e.g., "agent_4")
cmd = '/c local result = remote.call("agent", "create_agent", 34210, true, false, "player", {}); rcon.print(result.interface_name)'
result = rcon_client.send_command(cmd)
interface_name = result.strip()  # e.g., "agent_4"

# Extract agent index from name
agent_idx = int(interface_name.split("_")[1])  # e.g., 4
```

### Using the Agent

```python
# Teleport agent
rcon_client.send_command(f'/c rcon.print(helpers.table_to_json(remote.call("{interface_name}", "teleport", {{x=100, y=100}})))')

# Give agent items via admin
rcon_client.send_command(f'/c remote.call("admin", "add_items", {agent_idx}, {{["iron-plate"]=50, ["transport-belt"]=20}})')

# Place entity (ghost or real)
rcon_client.send_command(f'/c rcon.print(helpers.table_to_json(remote.call("{interface_name}", "place_entity", "iron-chest", {{x=100, y=100}}, nil, false, nil)))')
```

### Destroying an Agent

**Important**: Always destroy agents after tests to prevent resource leaks.

```python
# Destroy a specific agent by ID (preferred)
rcon_client.send_command(f'/c remote.call("agent", "destroy_agents", {{{agent_idx}}})')

# Destroy multiple agents
rcon_client.send_command('/c remote.call("agent", "destroy_agents", {1, 2, 3})')
```

### Fixture Pattern

Use pytest fixtures to ensure proper cleanup:

```python
@pytest.fixture(scope="function")
def agent_name(rcon_client):
    """Create a fresh agent for each test."""
    # Create agent
    cmd = '/c local result = remote.call("agent", "create_agent", 34210, true, false, "player", {}); rcon.print(result.interface_name)'
    result = rcon_client.send_command(cmd)
    interface_name = result.strip()
    agent_idx = int(interface_name.split("_")[1])

    yield interface_name

    # Cleanup - destroy this specific agent
    rcon_client.send_command(f'/c remote.call("agent", "destroy_agents", {{{agent_idx}}})')
```

### Agent Remote Interface Methods

| Method | Description |
|--------|-------------|
| `teleport({x, y})` | Teleport agent to position |
| `place_entity(name, pos, dir, ghost, label)` | Place entity/ghost |
| `walk_to({x, y}, strict, options)` | Start walking (async) |
| `get_position()` | Get current position |
| `get_inventory_items()` | Get inventory contents |
| `get_reachable(attach_ghosts)` | Get nearby entities |

## Domain-Specific Fixtures

Each domain can define its own `conftest.py` for specialized fixtures:

### `tests/factory/conftest.py`

```python
import pytest
from FactoryVerse.runtime import create_runtime
from FactoryVerse.config import get_config
from FactoryVerse.infra.instance_manager import FactorioInstanceManager

@pytest.fixture(scope="function")
async def agent_runtime(rcon: RconConnection, agent_id: str):
    """Create and start an AgentRuntime for tests.
    
    Auto-detects Docker server's script-output directory for snapshots.
    Provides same affordances as boilerplate without Jupyter kernel.
    """
    # Detect the Docker server's script-output directory
    config = get_config()
    instance = FactorioInstanceManager.from_env(config)
    snapshot_dir = instance.script_output_dir
    
    # Create runtime with auto-allocated UDP port
    runtime = create_runtime(
        rcon_client=rcon.client,
        agent_id=agent_id,
        udp_port=None,  # Auto-allocate
        snapshot_dir=snapshot_dir,  # Use Docker's script-output directory
    )
    
    await runtime.start()
    
    try:
        yield runtime
    finally:
        await runtime.stop()

@pytest.fixture(scope="function")
def dsl_context(agent_runtime, test_ground, admin):
    """Complete DSL context with AgentRuntime.
    
    Provides:
    - runtime: AgentRuntime with all affordances
    - test_ground: TestGround helper for entity/resource placement
    - admin: AdminInterface for inventory/tech management
    """
    return DSLTestContext(agent_runtime, test_ground, admin)
```

**Key improvement**: The `agent_runtime` fixture now auto-detects the correct snapshot directory:
- Uses `FactorioInstanceManager.from_env()` to detect Docker vs client
- Configures runtime with `instance.script_output_dir`
- RemoteView can now properly load snapshots from Docker server

### `tests/entities/conftest.py`

```python
@pytest.fixture(scope="function")
def furnace_setup(test_ground, admin, agent):
    """Pre-placed furnace with coal for entity tests."""
    test_ground.place_entity("stone-furnace", 10, 10)
    agent.teleport(10, 10)
    admin.add_items(1, {"coal": 50, "iron-ore": 50})
    return {"position": (10, 10), "entity": "stone-furnace"}
```

### `tests/functional/conftest.py`

```python
@pytest.fixture(scope="function") 
def resource_area(clean_area):
    """Area with iron and coal patches for workflow tests."""
    clean_area.place_iron_patch(50, 50, size=32)
    clean_area.place_coal_patch(50, 80, size=16)
    return clean_area
```

### `tests/infra/conftest.py`

```python
@pytest.fixture(scope="function")
def jupyter_runtime(temp_notebook_path, rcon, agent_id, temp_session_dir):
    """Create a FactoryVerseRuntime with boilerplate loaded.
    
    Simulates what run_agent.py does:
    1. Creates a Jupyter kernel
    2. Sets up environment variables for boilerplate
    3. Loads boilerplate.py into the kernel
    4. Loads map database
    
    Usage:
        def test_boilerplate_loaded(jupyter_runtime):
            result = jupyter_runtime.execute_code("print(runtime.agent_id)")
            assert agent_id in result
    """
    # Sets up environment and loads boilerplate
    runtime = FactoryVerseRuntime(notebook_path=str(temp_notebook_path))
    runtime.setup_boilerplate()
    runtime.load_map_database()
    yield runtime
    runtime.stop()
```

---

## Adding New Tests

### 1. Find the Right Domain

| If your test is about... | Add it to... |
|--------------------------|--------------|
| Agent commands (walk, mine, craft) | `actions/` |
| Specific entity types (furnace, drill) | `entities/` |
| Entity connections (belts, pipes) | `connect/` |
| Python Factory (Factorio Objects) classes/methods | `factory/` |
| UDP/snapshot/sync | `sync/` |
| Multi-step workflows | `functional/` |
| Multiple agents | `multiagent/` |
| Scenarios/benchmarks | `eval/` |
| Server/Docker/RCON | `infra/` |
| LLM boilerplate/Jupyter runtime | `infra/` |
| Lua mod behavior | `mod/` |

### 2. Use Domain Fixtures

Check the domain's `conftest.py` for existing fixtures before creating new ones.

### 3. Create New Domain (if needed)

Only create a new directory if:
- The domain is truly distinct from existing ones
- You expect multiple related test files
- The domain warrants its own fixtures

**New domain checklist:**
- [ ] Create `tests/<domain>/` directory
- [ ] Add `__init__.py`
- [ ] Add `conftest.py` with domain fixtures
- [ ] Add marker to `pytest.ini` if needed
- [ ] Update this README's domain table

---

## Markers

| Marker | Description |
|--------|-------------|
| `@pytest.mark.slow` | Tests that take >5 seconds |
| `@pytest.mark.requires_docker` | Tests that require Docker |
| `@pytest.mark.requires_restart` | Tests that require server restart |
| `@pytest.mark.integration` | Integration tests (require server) |
| `@pytest.mark.unit` | Unit tests (no server required) |

---

## Best Practices

### 1. Prefer reuse over new domains
If your test is "close enough" to an existing domain, add it there rather than creating a new one.

### 2. Use the fixture hierarchy
Leverage existing fixtures from `conftest.py` rather than setting up RCON/server yourself.

### 3. Keep tests isolated
Use `clean_area` fixture when tests need a fresh map state.

### 4. Document test requirements
Use docstrings to explain what server state/scenario the test expects.

### 5. Handle async properly
Async actions (walk_to, mine_resource) complete via UDP. Use wait helpers or poll for completion.

### 6. Testing boilerplate integration
The `tests/infra/test_boilerplate_integration.py` suite validates the complete LLM boilerplate system. It:
- Loads boilerplate.py into a Jupyter kernel (simulating `run_agent.py`)
- Validates all runtime affordances are available
- Tests all action types (walking, mining, crafting, etc.)
- Tests entity operations and ghost building
- Tests remote view DuckDB queries

This is the **final validation** that the system is ready for agent trajectories.

**Running boilerplate tests:**
```bash
# Run all infrastructure tests
uv run pytest tests/infra/

# Run just boilerplate integration tests
uv run pytest tests/infra/test_boilerplate_integration.py -v
```

**Interactive exploration:**
See `notebooks/test_boilerplate_exploration.py` for a comprehensive exploration script that can be run in Jupyter notebooks.

### 7. Testing without Jupyter: Direct Runtime Usage

**Problem**: Jupyter-based testing (via `FactoryVerseRuntime` and kernel execution) adds complexity:
- Kernel management overhead
- String-based code execution
- Async coordination between kernel and test process
- Snapshot timing issues

**Solution**: Use `AgentRuntime` directly in tests via the `agent_runtime` fixture.

This approach (used in `tests/factory/test_entity_walking_di.py`) provides:
- ✅ Direct access to all runtime affordances (walking, crafting, reachable, remote_view)
- ✅ Normal Python scoping (no string execution)
- ✅ Proper async/await support
- ✅ Same boilerplate initialization (just without Jupyter kernel)
- ✅ Faster test execution

**Example:**
```python
async def test_entity_has_walk_to(dsl_context):
    """Test entity walking capability."""
    # dsl_context.runtime is an AgentRuntime instance
    # Same as 'runtime' variable in boilerplate
    runtime = dsl_context.runtime
    
    # Place entity
    dsl_context.test_ground.place_entity("stone-furnace", 2, 2)
    
    # Get reachable entity (same API as boilerplate)
    furnace = runtime.reachable.get_entity("stone-furnace")
    
    # Access capabilities directly
    assert hasattr(furnace, "walk_to")
    assert furnace._walking_action is runtime.walking
```

**Key insight**: The boilerplate's affordances come from `AgentRuntime`, not from Jupyter. Tests can use `AgentRuntime` directly and get the same functionality without the kernel overhead.

**When to use each approach:**

| Approach | Use When | Example Tests |
|----------|----------|---------------|
| **Direct AgentRuntime** | Testing DI pipeline, method presence, API structure, unit tests | `test_entity_walking_di.py` |
| **Jupyter Runtime** | Testing boilerplate loading, code execution in kernel, full integration | `test_boilerplate_integration.py` |
| **Agent Interface (RCON)** | Testing Lua mod behavior, low-level RCON commands | `test_remote_interfaces.py` |

### 8. Testing DI pipelines and structure

When testing dependency injection and API structure (rather than end-to-end behavior):

**Focus on contracts, not integration:**
```python
async def test_walking_action_injected(dsl_context):
    """Verify walking_action flows through DI pipeline."""
    runtime = dsl_context.runtime
    
    # Check the pipeline
    assert runtime.walking is not None
    assert runtime.remote_view._walking_action is runtime.walking
    assert runtime.remote_view._query._walking_action is runtime.walking
    
    # Place entity and verify injection
    dsl_context.test_ground.place_entity("chest", 2, 2)
    entity = runtime.reachable.get_entity("chest")
    assert entity._walking_action is runtime.walking
```

**Why this approach?**
- ✅ Fast (no waiting for game state)
- ✅ Reliable (no async timing issues)
- ✅ Clear intent (testing the wiring, not behavior)
- ✅ Documents the architecture

**Reserve integration tests for:**
- Actual walking behavior (pathfinding, obstacles)
- Complex game state interactions
- Multi-step workflows
- Performance validation

See `tests/factory/test_entity_walking_di.py` for a complete example of this methodology.

---

## Example Test

```python
# tests/entities/test_furnaces.py
import pytest

class TestFurnaceInspection:
    """Tests for furnace entity inspection and status."""
    
    def test_furnace_shows_fuel_status(self, furnace_setup, agent, dsl_context):
        """Furnace inspection should show fuel and input/output contents."""
        # Arrange: furnace_setup provides placed furnace with coal
        with dsl_context.playing_factory as factory:
            furnace = factory.reachable.get_entity("stone-furnace")
            
            # Act
            info = furnace.inspect()
            
            # Assert
            assert "coal" in info.lower()
            assert "Status:" in info
    
    def test_furnace_smelts_ore(self, furnace_setup, agent, game_world):
        """Furnace should smelt iron ore into plates."""
        # Add ore to furnace input
        agent.put_inventory_item("stone-furnace", 10, 10, "fuel", "coal", 5)
        agent.put_inventory_item("stone-furnace", 10, 10, "input", "iron-ore", 10)
        
        # Wait for smelting (async)
        import time
        time.sleep(2)
        
        # Check output
        result = agent.take_inventory_item("stone-furnace", 10, 10, "output", "iron-plate", 10)
        assert result["success"]
```
