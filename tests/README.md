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
├── conftest.py                 # Root fixtures (Environment-based)
├── README.md                   # This file
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
│   ├── conftest.py            # Infrastructure-specific fixtures
│   ├── test_server.py         # Server startup, health checks
│   ├── test_rcon.py           # RCON connection, commands
│   └── test_docker.py         # Docker compose, containers
│
├── unit/                       # Unit tests for Environment module
│   └── test_environment_tiers.py # Environment tier initialization tests
│
└── mod/                        # Lua mod tests (run inside Factorio)
    ├── test_remote_interfaces.py # Remote interface availability
    └── test_events.py         # Event handlers, custom events
```

---

## Configuration Discovery

The fixture system distinguishes between **runtime-discovered** and **static** configurations:

### Runtime-Discovered (Dynamic)
- **Scenarios**: Discovered from filesystem at test collection time
  - Scans `src/factorio/scenarios/` for directories with `control.lua`
  - Only repo scenarios are included (not local Factorio scenarios)
  - Automatically included in `environment_scenario` parametrization

### Static (Enum-Based)
- **Runtime Variants**: `MINIMAL`, `FULL` (hardcoded enum values)
- **Infra Modes**: `CLIENT`, `SERVER`, `CLIENT_AND_SERVER` (hardcoded enum values)

**Why this matters:**
- Scenarios change as you add/remove scenario directories → discovered automatically
- Variants are fixed enum values → can be hardcoded in fixtures
- Tests automatically adapt to available scenarios without code changes

**Accessing discovered scenarios:**
```python
async def test_with_scenario_list(available_scenarios):
    """Access the list of discovered scenarios."""
    assert "test-ground" in available_scenarios
    assert "freeplay" in available_scenarios
    # ... use for custom parametrization
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
uv run pytest tests/infra/  # Infrastructure tests

# Run multiple domains
uv run pytest tests/actions/ tests/entities/

# Run specific test file
uv run pytest tests/entities/test_furnaces.py -v

# Run with marker
uv run pytest -m "not slow"
uv run pytest -m "integration"
```

**Key test files for verifying the test harness:**
- `tests/unit/test_environment_tiers.py`: Unit tests for Environment tier initialization
- `tests/test_infrastructure.py`: Smoke tests for the testing infrastructure using Environment
- `tests/test_parametrized_fixtures.py`: Tests verifying parametrized fixtures work correctly

---

## Fixture Hierarchy

The test fixtures are organized around the `Environment` architecture, which provides a tiered initialization system:

```
environment (function)              # Minimal Environment (default: test-ground, MINIMAL)
    ├── tier4                       # Access to Tier 4 Runtime
    │   ├── agent                   # Access to embodied actions (acting as 'agent')
    │   └── reachable_view          # Entity querying
    ├── rcon                        # Tier 3 RconHelper
    │
    ├── full_environment            # Full Environment (adds DuckDB + RemoteView)
    │   └── remote_view             # SQL-based querying
    │
    ├── environment_variant         # Parametrized: MINIMAL and FULL variants
    ├── environment_scenario        # Parametrized: All discovered scenarios
    ├── environment_factory         # Factory for custom configurations
    │
    └── Named scenario fixtures:
        ├── freeplay_environment    # Freeplay scenario
        └── lab_environment         # Lab scenario
```

**Key fixtures:**
- `environment`: Basic setup for most tests (minimal runtime, no DuckDB, test-ground scenario)
- `full_environment`: For tests needing DuckDB/RemoteView
- `environment_variant`: **Parametrized** - runs tests for both MINIMAL and FULL variants
- `environment_scenario`: **Parametrized** - runs tests for all discovered scenarios
- `environment_factory`: Factory for creating custom environment configurations
- `tier4`: Direct access to the `Tier4Runtime` instance
- `agent`: Provides the `embodied_actions` dictionary (walking, crafting, etc.)
- `rcon`: Access to the RCON client via `Tier3Python`
- `reachable_view`: Lua-based entity querying (always available)
- `remote_view`: SQL-based querying (requires `full_environment`)
- `available_scenarios`: List of discovered scenarios (session-scoped)

---

## Agent Lifecycle

The `Environment` fixture automatically handles agent lifecycle management. You no longer need to manually create or destroy agents.

### Automatic Lifecycle Management

When you use the `environment` fixture, the following happens automatically:

1. **Initialization**: `Tier4Runtime` initializes the session during `await env.initialize()`
2. **Agent Creation**: `_create_agent()` is called automatically, which:
   - Creates the agent entity in Factorio via RCON
   - Sets up the UDP port for action feedback
   - Registers the agent interface
3. **Cleanup**: The `environment` fixture teardown automatically:
   - Shuts down the runtime
   - Cleans up the session directory
   - Stops the Factorio server

### Using the Agent in Tests

Simply request the `agent` fixture to access embodied actions:

```python
async def test_walking(agent, rcon):
    """Test agent walking capability."""
    # 'agent' provides embodied actions directly
    result = await agent["walking"].walk_to(x=10, y=10)
    assert result["success"]
    
    # Access other actions
    await agent["crafting"].enqueue("iron-plate", count=10)
    await agent["placement"].place_entity("iron-chest", x=5, y=5)
```

### Accessing Agent State

You can access the agent ID and other runtime properties via the `tier4` fixture:

```python
async def test_agent_state(tier4, rcon):
    """Access agent state via RCON."""
    agent_id = tier4.agent_id  # e.g., "agent_1"
    
    # Get position via RCON
    pos = rcon.run(agent_id, "get_position", {})
    assert "x" in pos
    assert "y" in pos
```

### Agent Remote Interface Methods

The agent is accessible via RCON using the interface name (same as `agent_id`):

| Method | Description |
|--------|-------------|
| `teleport({x, y})` | Teleport agent to position |
| `place_entity(name, pos, dir, ghost, label)` | Place entity/ghost |
| `walk_to({x, y}, strict, options)` | Start walking (async) |
| `get_position()` | Get current position |
| `get_inventory_items()` | Get inventory contents |
| `get_reachable(attach_ghosts)` | Get nearby entities |
| `inspect()` | Get agent internal state |

## Core Fixtures from `tests/conftest.py`

The root `conftest.py` provides the following core fixtures:

### `environment` (function-scoped)

Basic setup for most tests. Provides:
- Factorio server (Docker)
- Settings configuration
- RCON connection (Tier 3)
- Runtime with embodied actions (Tier 4, minimal variant)

```python
async def test_basic_setup(environment: Environment):
    """Test basic environment access."""
    assert environment.tier3 is not None
    assert environment.tier4 is not None
    assert environment.tier4.embodied_actions is not None
```

### `full_environment` (function-scoped)

Full environment with DuckDB and RemoteView. Use when you need SQL-based queries:

```python
async def test_remote_view(full_environment: Environment):
    """Test RemoteView SQL queries."""
    remote_view = full_environment.tier4.remote_view
    entities = await remote_view.query("SELECT * FROM entities WHERE name = 'iron-chest'")
    assert len(entities) > 0
```

### `tier4` (function-scoped)

Direct access to the `Tier4Runtime` instance:

```python
async def test_runtime_access(tier4):
    """Access runtime properties."""
    assert tier4.agent_id is not None
    assert tier4.session_dir is not None
    assert tier4.embodied_actions is not None
```

### `agent` (function-scoped)

Provides the `embodied_actions` dictionary for direct action access:

```python
async def test_walking(agent):
    """Test walking action."""
    result = await agent["walking"].walk_to(x=10, y=10)
    assert result["success"]
```

### `rcon` (function-scoped)

Access to the RCON client via `Tier3Python`:

```python
async def test_rcon_commands(rcon):
    """Test RCON commands."""
    response = rcon.rcon_client.send_command("/h")
    assert response is not None
```

### `reachable_view` (function-scoped)

Lua-based entity querying (always available):

```python
async def test_reachable_entities(reachable_view):
    """Test reachable entity queries."""
    entities = reachable_view.get_entities()
    assert entities is not None
```

### `remote_view` (function-scoped)

SQL-based querying (requires `full_environment`):

```python
async def test_remote_queries(remote_view):
    """Test SQL queries."""
    entities = await remote_view.query("SELECT * FROM entities")
    assert entities is not None
```

### `environment_variant` (function-scoped, parametrized)

**Parametrized fixture** that runs tests for both MINIMAL and FULL runtime variants. This ensures features work in both configurations.

```python
async def test_embodied_actions_work_all_variants(environment_variant: Environment):
    """Test runs twice: once for MINIMAL, once for FULL."""
    # This test automatically runs for both variants
    actions = environment_variant.tier4.embodied_actions
    assert actions is not None
    assert "walking" in actions
    
    # FULL variant has remote_view, MINIMAL does not
    if environment_variant.tier4.config.variant == RuntimeVariant.FULL:
        assert environment_variant.tier4.remote_view is not None
    else:
        assert environment_variant.tier4.remote_view is None
```

**When to use:**
- Testing features that should work in both variants
- Ensuring core functionality doesn't depend on DuckDB/RemoteView
- Systematic coverage of variant differences

### `environment_scenario` (function-scoped, parametrized)

**Parametrized fixture** that runs tests for all discovered scenarios. Scenarios are discovered from the filesystem at test collection time.

```python
async def test_scenario_behavior(environment_scenario: Environment):
    """Test runs once per discovered scenario."""
    # Automatically runs for: test-ground, freeplay, lab, etc.
    scenario = environment_scenario.tier2.current_scenario
    assert scenario is not None
    
    # Test scenario-specific behavior
    reachable = environment_scenario.tier4.reachable_view
    entities = reachable.get_entities()
    assert entities is not None
```

**When to use:**
- Testing features that should work across all scenarios
- Verifying scenario-specific behavior
- Systematic coverage of scenario differences

**Note:** Scenarios are discovered at test collection time by scanning for directories with `control.lua` files. Only repo scenarios (not local Factorio scenarios) are included for test reproducibility.

### `environment_factory` (function-scoped)

Factory fixture for creating environments with custom configurations:

```python
async def test_custom_config(environment_factory):
    """Test with custom scenario and variant."""
    env = await environment_factory(
        tier2={"scenario": "freeplay"},
        tier4={"variant": RuntimeVariant.FULL},
    )
    try:
        assert env.tier2.current_scenario == "freeplay"
        assert env.tier4.config.variant == RuntimeVariant.FULL
        assert env.tier4.remote_view is not None
    finally:
        await env.shutdown()
```

**When to use:**
- Custom configurations not covered by parametrized fixtures
- Testing specific scenario × variant combinations
- One-off tests with unique requirements

### `available_scenarios` (session-scoped)

Provides the list of discovered scenarios for manual parametrization:

```python
async def test_custom_parametrization(environment_factory, available_scenarios):
    """Manually parametrize over scenarios."""
    for scenario in available_scenarios:
        env = await environment_factory(tier2={"scenario": scenario})
        try:
            # Test logic
            assert env.tier2.current_scenario == scenario
        finally:
            await env.shutdown()
```

### Named Scenario Fixtures

Convenience fixtures for common scenarios:

- `freeplay_environment`: Environment with freeplay scenario
- `lab_environment`: Environment with lab scenario

```python
async def test_freeplay_specific(freeplay_environment: Environment):
    """Test specific to freeplay scenario."""
    assert freeplay_environment.tier2.current_scenario == "freeplay"
```

## Domain-Specific Fixtures

Each domain can define its own `conftest.py` for specialized fixtures that build on the core fixtures:

### `tests/entities/conftest.py`

```python
@pytest.fixture(scope="function")
def furnace_setup(environment, agent, rcon):
    """Pre-placed furnace with coal for entity tests."""
    # Use RCON to place entity
    agent_id = environment.tier4.agent_id
    rcon.run(agent_id, "place_entity", {
        "name": "stone-furnace",
        "position": {"x": 10, "y": 10}
    })
    
    # Add items via admin
    agent_index = int(agent_id.split("_")[-1])
    cmd = f"/c remote.call('admin', 'add_items', {agent_index}, {{['coal'] = 50, ['iron-ore'] = 50}})"
    rcon.rcon_client.send_command(cmd)
    
    return {"position": (10, 10), "entity": "stone-furnace"}
```

### `tests/functional/conftest.py`

```python
@pytest.fixture(scope="function") 
def resource_area(environment, rcon):
    """Area with iron and coal patches for workflow tests."""
    # Use admin interface to place resource patches
    # Implementation depends on available helpers
    return {"iron_patch": (50, 50), "coal_patch": (50, 80)}
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
| Environment module/Infrastructure | `infra/`, `unit/` |
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

### 6. Testing Environment integration
The `tests/test_infrastructure.py` suite validates the Environment module integration. It:
- Tests RCON connection via Tier 3
- Validates agent creation in Tier 4
- Tests embodied actions loading
- Verifies agent state access

**Running infrastructure tests:**
```bash
# Run all infrastructure tests
uv run pytest tests/infra/

# Run environment smoke tests
uv run pytest tests/test_infrastructure.py -v

# Run unit tests for Environment tiers
uv run pytest tests/unit/test_environment_tiers.py -v
```

### 9. Parametrized Testing for Comprehensive Coverage

Use parametrized fixtures to test features across multiple configurations:

**Test across variants:**
```python
async def test_feature_works_all_variants(environment_variant: Environment):
    """Automatically tests both MINIMAL and FULL variants."""
    # Test runs twice (once per variant)
    assert environment_variant.tier4.embodied_actions is not None
```

**Test across scenarios:**
```python
async def test_feature_works_all_scenarios(environment_scenario: Environment):
    """Automatically tests all discovered scenarios."""
    # Test runs once per scenario (test-ground, freeplay, lab, etc.)
    scenario = environment_scenario.tier2.current_scenario
    assert scenario is not None
```

**Test all combinations:**
```python
from FactoryVerse.environment.config import RuntimeVariant
from tests.conftest import _AVAILABLE_SCENARIOS

@pytest.mark.parametrize("scenario", _AVAILABLE_SCENARIOS)
@pytest.mark.parametrize("variant", [RuntimeVariant.MINIMAL, RuntimeVariant.FULL])
async def test_all_combinations(environment_factory, scenario, variant):
    """Test all scenario × variant combinations."""
    env = await environment_factory(
        tier2={"scenario": scenario},
        tier4={"variant": variant},
    )
    try:
        # Test logic
        assert env.tier2.current_scenario == scenario
        assert env.tier4.config.variant == variant
    finally:
        await env.shutdown()
```

**Benefits:**
- ✅ Automatic coverage of all configurations
- ✅ Catches bugs in specific scenarios/variants
- ✅ Documents which configs are supported
- ✅ No manual test duplication

**When to parametrize:**
- Features that should work in both variants → use `environment_variant`
- Features that should work in all scenarios → use `environment_scenario`
- Testing configuration-specific behavior → use `environment_factory` with custom configs

### 7. Testing without Jupyter: Tier 4 Access

**Solution**: Use the `tier4` or `agent` fixtures to interact with the Python runtime directly.

This approach provides:
- ✅ Direct access to all runtime affordances (walking, crafting, reachable_view, remote_view)
- ✅ Normal Python scoping (no string execution)
- ✅ Proper async/await support
- ✅ Faster test execution
- ✅ No Jupyter kernel overhead

**Example:**
```python
async def test_example(agent, rcon):
    """Test using agent actions directly."""
    # 'agent' provides embodied actions directly
    result = await agent["walking"].walk_to(x=10, y=10)
    assert result["success"]
    
    # Access other actions
    await agent["crafting"].enqueue("iron-plate", count=10)
    await agent["placement"].place_entity("iron-chest", x=5, y=5)
```

**Accessing Tier 4 Runtime:**
```python
async def test_runtime_access(tier4, reachable_view):
    """Access runtime components directly."""
    # Access embodied actions
    walking = tier4.embodied_actions["walking"]
    
    # Access views
    entities = reachable_view.get_entities()
    
    # Access agent ID
    agent_id = tier4.agent_id
```

**When to use each approach:**

| Approach | Use When | Example Tests |
|----------|----------|---------------|
| **Tier 4 / Agent fixtures** | Testing actions, runtime components, API structure | `test_crafting_status.py`, `test_infrastructure.py` |
| **Full Environment** | Testing RemoteView SQL queries, DuckDB integration | Tests requiring `remote_view` fixture |
| **RCON directly** | Testing Lua mod behavior, low-level RCON commands | `test_remote_interfaces.py` |

### 8. Testing DI pipelines and structure

When testing dependency injection and API structure (rather than end-to-end behavior):

**Focus on contracts, not integration:**
```python
async def test_walking_action_injected(tier4):
    """Verify walking_action flows through DI pipeline."""
    # Check the pipeline
    assert tier4.embodied_actions["walking"] is not None
    
    # Access reachable view
    reachable = tier4.reachable_view
    # Verify injection if applicable
    # (Implementation depends on current architecture)
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

---

## Example Tests

### Basic Test with Default Environment

```python
# tests/actions/test_crafting_status.py
import pytest
from FactoryVerse.environment.environment import Environment

@pytest.mark.asyncio
class TestCraftingStatus:
    """Test crafting.status() returns proper queue information."""

    async def test_status_returns_typed_queue(self, environment_variant: Environment):
        """Test runs for both MINIMAL and FULL variants."""
        # Setup: Ensure agent has items
        agent_id_str = environment_variant.tier4.agent_id
        agent_index = int(agent_id_str.split("_")[-1]) if "_" in agent_id_str else 1

        # Add items via RCON admin interface
        cmd = f"/c rcon.print(helpers.table_to_json(remote.call('admin', 'add_items', {agent_index}, {{['iron-plate'] = 20}})))"
        res = environment_variant.tier3.rcon_helper.rcon_client.send_command(cmd)
        assert "success" in res

        # Access crafting action via embodied_actions
        crafting_action = environment_variant.tier4.embodied_actions["crafting"]

        # Get initial status (should be empty)
        status = crafting_action.status()

        # Verify type structure
        assert isinstance(status, dict), "Should return a dict"
        assert "queue" in status, "Should have 'queue' field"
        assert len(status["queue"]) == 0, "Queue should be empty initially"
```

### Using Parametrized Fixtures

```python
# tests/actions/test_walking.py
import pytest

@pytest.mark.asyncio
async def test_walk_to_all_variants(environment_variant):
    """Test walking works in both MINIMAL and FULL variants."""
    # Automatically runs twice (once per variant)
    result = await environment_variant.tier4.embodied_actions["walking"].walk_to(x=10, y=10)
    assert result["success"]

@pytest.mark.asyncio
async def test_walk_to_all_scenarios(environment_scenario):
    """Test walking works in all scenarios."""
    # Automatically runs for each discovered scenario
    walking = environment_scenario.tier4.embodied_actions["walking"]
    result = await walking.walk_to(x=10, y=10)
    assert result["success"]
```

### Using the Agent Fixture

```python
# tests/actions/test_walking.py
import pytest

@pytest.mark.asyncio
async def test_walk_to(agent, tier4):
    """Test walking action."""
    # Use agent fixture for direct action access
    result = await agent["walking"].walk_to(x=10, y=10)
    assert result["success"]
    
    # Access agent ID if needed
    agent_id = tier4.agent_id
```

### Using Factory for Custom Configurations

```python
# tests/actions/test_custom.py
import pytest
from FactoryVerse.environment.config import RuntimeVariant

@pytest.mark.asyncio
async def test_custom_config(environment_factory):
    """Test with custom scenario and variant."""
    env = await environment_factory(
        tier2={"scenario": "freeplay"},
        tier4={"variant": RuntimeVariant.FULL},
    )
    try:
        # Test logic
        assert env.tier2.current_scenario == "freeplay"
        assert env.tier4.remote_view is not None
    finally:
        await env.shutdown()
```
