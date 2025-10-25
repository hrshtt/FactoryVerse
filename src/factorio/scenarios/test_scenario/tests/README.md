# FactoryVerse Testing Framework

This directory contains the comprehensive testing framework for FactoryVerse actions. The framework follows Factorio mod testing best practices using scenario-based testing with remote interfaces.

## Overview

The testing framework provides:
- **Scenario-based testing** using Factorio's built-in scenario system
- **Remote interface execution** via RCON for external test control
- **Comprehensive test coverage** for all 7 implemented entity actions
- **Integration tests** for complete workflows
- **Python test runner** for CI/CD integration

## Test Structure

```
tests/
├── entity/                    # Entity action tests
│   ├── test_entity_rotate.lua
│   ├── test_entity_pickup.lua
│   └── test_entity_set_recipe.lua
├── inventory/                 # Inventory action tests
│   ├── test_inventory_set_item.lua
│   ├── test_inventory_get_item.lua
│   └── test_inventory_set_limit.lua
├── integration/               # Integration tests
│   └── test_full_workflow.lua
├── test_suite.lua            # Test registry
└── README.md                 # This file
```

## Running Tests

### Prerequisites

1. **Factorio Server**: Start a Factorio server with the test scenario
2. **RCON Access**: Enable RCON with a known password
3. **Python Dependencies**: Install `factorio-rcon` package

```bash
pip install factorio-rcon
```

### Using the Python Test Runner

The `scripts/run_tests.py` script provides a comprehensive test runner:

```bash
# Run all tests
python scripts/run_tests.py

# Run specific test
python scripts/run_tests.py --test entity.rotate

# Run test category
python scripts/run_tests.py --category entity

# Verbose output
python scripts/run_tests.py --verbose

# JSON output
python scripts/run_tests.py --json

# List available tests
python scripts/run_tests.py --list

# Custom server settings
python scripts/run_tests.py --host localhost --port 27015 --password mypassword
```

### Using RCON Directly

You can also run tests directly via RCON:

```bash
# Run all tests
rcon -H localhost -P 27015 -p password "/c remote.call('test_runner', 'run_all_tests')"

# Run specific test
rcon -H localhost -P 27015 -p password "/c remote.call('test_runner', 'run_test', 'entity.rotate')"

# List available tests
rcon -H localhost -P 27015 -p password "/c remote.call('test_runner', 'list_tests')"
```

## Test Framework Components

### Core Testing Module (`core/test/`)

- **TestRunner.lua**: Test execution engine with setup/teardown support
- **TestHelpers.lua**: Common utilities for test operations
- **TestAssertions.lua**: Factorio-specific assertion library
- **TestReporter.lua**: Results formatting and reporting

### Test Helpers

Common utilities available in tests:

```lua
-- Agent management
local agent = TestHelpers.spawn_agent(surface, position)
TestHelpers.clear_agent_inventory(agent)
TestHelpers.give_agent_items(agent, {["iron-plate"] = 10})

-- Entity management
local entity = TestHelpers.spawn_entity(surface, "inserter", position)
local chest = TestHelpers.create_test_chest(surface, position, items)
local assembler = TestHelpers.create_test_assembler(surface, position, recipe)

-- Area management
TestHelpers.clear_test_area(surface, area)
local area = TestHelpers.create_test_area(center, radius)
```

### Test Assertions

Factorio-specific assertions for validation:

```lua
-- Basic assertions
TestAssertions.assert_equal(actual, expected)
TestAssertions.assert_not_nil(value)
TestAssertions.assert_true(value)
TestAssertions.assert_contains(string, substring)

-- Factorio-specific assertions
TestAssertions.assert_entity_exists(unit_number)
TestAssertions.assert_entity_direction(entity, direction)
TestAssertions.assert_inventory_contains(entity, inventory_type, item, count)
TestAssertions.assert_recipe_set(entity, recipe_name)
TestAssertions.assert_agent_has_items(agent, items)
TestAssertions.assert_entity_minable(entity)
TestAssertions.assert_entity_rotatable(entity)
```

## Writing New Tests

### Test Module Structure

Each test module should follow this structure:

```lua
local TestHelpers = require("core.test.TestHelpers")
local TestAssertions = require("core.test.TestAssertions")

return {
    name = "test.name",
    
    setup = function(context)
        -- Initialize test environment
        context.surface = game.surfaces[1]
        context.test_area = TestHelpers.create_test_area({x=0, y=0}, 20)
        context.agent = TestHelpers.spawn_agent(context.surface, {x=0, y=0})
    end,
    
    tests = {
        test_case_name = function(context)
            -- Test implementation
            local result = remote.call("actions", "action.name", params)
            TestAssertions.assert_not_nil(result)
        end,
        
        another_test_case = function(context)
            -- Another test case
        end
    },
    
    teardown = function(context)
        -- Clean up test artifacts
        TestHelpers.clear_test_area(context.surface, context.test_area)
    end
}
```

### Test Conventions

1. **Naming**: Use descriptive test names that explain the scenario
2. **Isolation**: Each test should be independent and clean up after itself
3. **Context**: Use the context table to share data between setup, tests, and teardown
4. **Assertions**: Use specific assertions for better error messages
5. **Error Handling**: Test both success and failure scenarios

### Example Test Cases

```lua
-- Test successful action execution
test_action_success = function(context)
    local result = remote.call("actions", "entity.rotate", {
        agent_id = context.agent.player_index,
        unit_number = context.entity.unit_number,
        direction = "north"
    })
    
    TestAssertions.assert_not_nil(result)
    TestAssertions.assert_entity_direction(context.entity, defines.direction.north)
end

-- Test error handling
test_action_error = function(context)
    local success, error = pcall(function()
        remote.call("actions", "entity.rotate", {
            agent_id = context.agent.player_index,
            unit_number = 99999, -- Non-existent entity
            direction = "north"
        })
    end)
    
    TestAssertions.assert_equal(success, false)
    TestAssertions.assert_contains(error, "Entity not found")
end

-- Test no-op behavior
test_action_no_op = function(context)
    context.entity.direction = defines.direction.north
    
    local result = remote.call("actions", "entity.rotate", {
        agent_id = context.agent.player_index,
        unit_number = context.entity.unit_number,
        direction = "north"
    })
    
    TestAssertions.assert_equal(result.no_op, true)
    TestAssertions.assert_contains(result.message, "already in requested direction")
end
```

## Test Categories

### Entity Actions (`entity/`)

- **test_entity_rotate.lua**: Tests entity rotation with direction support
- **test_entity_pickup.lua**: Tests entity pickup with inventory extraction
- **test_entity_set_recipe.lua**: Tests recipe setting with validation

### Inventory Actions (`inventory/`)

- **test_inventory_set_item.lua**: Tests item insertion with type validation
- **test_inventory_get_item.lua**: Tests item extraction with partial transfers
- **test_inventory_set_limit.lua**: Tests inventory limit setting

### Integration Tests (`integration/`)

- **test_full_workflow.lua**: Complete workflow from mining to production

## Test Results

### Output Formats

The test runner supports multiple output formats:

- **Console**: Human-readable summary
- **Verbose**: Detailed test results with timing
- **JSON**: Machine-readable format for CI/CD
- **Quiet**: Minimal output for automation

### Result Structure

```json
{
  "total": 15,
  "passed": 14,
  "failed": 1,
  "duration": 120,
  "success_rate": 93.3,
  "results": [...],
  "failures": [...]
}
```

## Troubleshooting

### Common Issues

1. **Connection Failed**: Check RCON settings and server status
2. **Test Not Found**: Verify test name format (category.test)
3. **Parse Error**: Check Factorio server logs for Lua errors
4. **Timeout**: Increase RCON timeout for long-running tests

### Debug Mode

Enable verbose logging in Factorio:

```lua
-- In Factorio console
/c game.print("Debug mode enabled")
/c log("Test execution started")
```

### Test Isolation

If tests are interfering with each other:

1. Use larger test areas
2. Ensure proper cleanup in teardown
3. Use unique entity positions
4. Clear agent inventory between tests

## CI/CD Integration

### GitHub Actions Example

```yaml
name: FactoryVerse Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Setup Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.8'
      - name: Install dependencies
        run: pip install factorio-rcon
      - name: Start Factorio server
        run: |
          # Start Factorio server with test scenario
          ./factorio --start-server test_scenario --rcon-port 27015 --rcon-password testpass
      - name: Run tests
        run: python scripts/run_tests.py --host localhost --port 27015 --password testpass
```

### Jenkins Pipeline Example

```groovy
pipeline {
    agent any
    stages {
        stage('Test') {
            steps {
                sh 'pip install factorio-rcon'
                sh './factorio --start-server test_scenario --rcon-port 27015 --rcon-password testpass &'
                sh 'sleep 30' // Wait for server startup
                sh 'python scripts/run_tests.py --host localhost --port 27015 --password testpass'
            }
        }
    }
}
```

## Performance Considerations

- **Test Duration**: Individual tests should complete within 1-2 seconds
- **Memory Usage**: Clean up test artifacts to prevent memory leaks
- **Parallel Execution**: Tests are currently sequential but can be parallelized
- **Resource Usage**: Use minimal test areas to reduce overhead

## Contributing

When adding new tests:

1. Follow the established naming conventions
2. Include both success and failure test cases
3. Use appropriate assertions for clear error messages
4. Ensure proper cleanup in teardown
5. Update this documentation if adding new test categories

## Support

For issues with the testing framework:

1. Check the Factorio server logs
2. Verify RCON connection settings
3. Test individual actions manually
4. Review test isolation and cleanup
5. Check for Factorio version compatibility
