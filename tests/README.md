# FactoryVerse Tests

Comprehensive test suite for FactoryVerse DSL, mods, and snapshot system.

## Quick Start

### Prerequisites

1. **Factorio running with test-ground scenario**
   - Load the `test-ground` scenario from `src/factorio/scenarios/test-ground`
   - Ensure RCON is enabled (default port 27015, password "factorio")

2. **Install test dependencies**
   ```bash
   pip install pytest pytest-xdist
   ```

### Running Tests

```bash
# Run all tests
pytest tests/

# Run with verbose output
pytest -v tests/

# Run specific test file
pytest tests/test_ground_examples.py

# Run tests matching a pattern
pytest -k "snapshot" tests/
```

## Test Structure

```
tests/
├── conftest.py                    # pytest configuration and fixtures
├── helpers/                       # Test helper modules
│   ├── __init__.py
│   └── test_ground.py            # TestGround helper class
├── test_ground_examples.py        # Example tests demonstrating infrastructure
├── dsl/                           # DSL operation tests (TODO)
│   ├── actions/                   # Walking, mining, crafting, etc.
│   └── entities/                  # Furnaces, drills, inserters, etc.
├── snapshot/                      # Snapshot accuracy tests (TODO)
└── workflows/                     # End-to-end workflow tests (TODO)
```

## Key Concepts

### test-ground Scenario

- **512x512 lab tile map** - clean, obstacle-free testing environment
- **Programmatic resource/entity placement** - deterministic test setup
- **Force re-snapshot** - on-demand snapshot triggering for validation
- **Metadata tracking** - all placed resources/entities tracked

### TestGround Helper

Python class providing high-level API for:
- Resource placement (`place_iron_patch()`, `place_copper_patch()`, etc.)
- Entity placement (`place_entity()`, `place_entity_grid()`)
- Area management (`clear_area()`, `reset_test_area()`)
- Snapshot control (`force_resnapshot()`)
- Validation (`validate_resource_at()`, `validate_entity_at()`)

### pytest Fixtures

- `factory_instance` - Session-scoped DSL access
- `test_ground` - Session-scoped TestGround helper
- `iron_ore_patch`, `copper_ore_patch`, etc. - Pre-placed resource patches
- `reset_between_tests` (autouse) - Automatic test isolation

## Example Test

```python
def test_mine_from_known_patch(factory_instance, iron_ore_patch):
    """Test mining from a known iron ore patch."""
    # Walk to patch
    patch_x = iron_ore_patch["center"]["x"]
    patch_y = iron_ore_patch["center"]["y"]
    factory_instance.walking.to(patch_x, patch_y)
    
    # Get initial inventory
    initial_iron = factory_instance.inventory.get_total("iron-ore")
    
    # Mine
    factory_instance.mining.resource("iron-ore", quantity=10)
    
    # Verify
    final_iron = factory_instance.inventory.get_total("iron-ore")
    assert final_iron == initial_iron + 10
```

## Documentation

See [testing_infrastructure.md](../.gemini/antigravity/brain/42d2e351-8b2b-4afb-87af-cb2f2a49bb50/testing_infrastructure.md) for comprehensive documentation including:
- Architecture overview
- test-ground scenario API
- TestGround helper API
- Writing tests guide
- Best practices
- Troubleshooting

## Contributing Tests

When adding new tests:

1. **Use existing fixtures** when possible
2. **Follow naming conventions**: `test_<feature>_<scenario>`
3. **Add docstrings** explaining what the test validates
4. **Use markers** for categorization:
   - `@pytest.mark.slow` - Tests that take >5 seconds
   - `@pytest.mark.snapshot` - Tests validating snapshot accuracy
   - `@pytest.mark.dsl` - Tests validating DSL operations
   - `@pytest.mark.mod` - Tests validating mod behavior

5. **Ensure test isolation** - tests should not depend on each other

## Troubleshooting

### "test-ground scenario not loaded"

Ensure Factorio is running with the test-ground scenario and RCON is accessible.

### "No resources found in snapshot"

Increase wait time after `force_resnapshot()` or implement snapshot status polling.

### Tests interfere with each other

Verify `reset_between_tests` fixture is working. Check `conftest.py` is in `tests/` directory.

## Next Steps

1. Run `pytest tests/test_ground_examples.py` to verify infrastructure
2. Write DSL operation tests in `tests/dsl/actions/`
3. Write entity behavior tests in `tests/dsl/entities/`
4. Write snapshot validation tests in `tests/snapshot/`
