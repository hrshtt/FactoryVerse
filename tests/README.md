# FactoryVerse Tests

Test suite for FactoryVerse DSL and mod.

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
├── dsl/                        # Python DSL layer tests
│   ├── conftest.py            # DSL-specific fixtures (PlayingFactory, etc.)
│   ├── test_playing_factory.py # Context manager, session state
│   ├── test_reachable.py      # Reachable entity queries
│   ├── test_map_db.py         # DuckDB map queries
│   ├── test_entity_views.py   # Reachable, Remote, Ghost views
│   └── test_prototypes.py     # Prototype loading, caching
│
├── sync/                       # Data synchronization tests
│   ├── test_udp.py            # UDP notification handling
│   ├── test_snapshot.py       # Snapshot file parsing
│   └── test_duckdb_sync.py    # DuckDB entity sync
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
uv run pytest tests/dsl/
uv run pytest tests/functional/

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

## Domain-Specific Fixtures

Each domain can define its own `conftest.py` for specialized fixtures:

### `tests/dsl/conftest.py`

```python
import pytest
from FactoryVerse.factory.agent import PlayingFactory

@pytest.fixture(scope="function")
def playing_factory(rcon, agent_id):
    """PlayingFactory context for DSL tests."""
    return PlayingFactory(rcon=rcon, agent_id=agent_id)

@pytest.fixture(scope="function")
def dsl_context(playing_factory, test_ground, admin):
    """Complete DSL context with test helpers."""
    return DSLTestContext(playing_factory, test_ground, admin)
```

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

---

## Adding New Tests

### 1. Find the Right Domain

| If your test is about... | Add it to... |
|--------------------------|--------------|
| Agent commands (walk, mine, craft) | `actions/` |
| Specific entity types (furnace, drill) | `entities/` |
| Entity connections (belts, pipes) | `connect/` |
| Python DSL classes/methods | `dsl/` |
| UDP/snapshot/sync | `sync/` |
| Multi-step workflows | `functional/` |
| Multiple agents | `multiagent/` |
| Scenarios/benchmarks | `eval/` |
| Server/Docker/RCON | `infra/` |
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
