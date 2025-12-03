--[[
Test Scenario for FactoryVerse

Provides a test framework for verifying mod functionality via RCON.
Supports both synchronous tests (immediate verification) and asynchronous tests
(multi-tick actions like walking, mining, crafting).

Test execution:
  /c remote.call("test_runner", "run_all_tests")
  /c remote.call("test_runner", "run_category", "agent")
  /c remote.call("test_runner", "run_test", "agent.test_create")

Architecture:
- Sync tests: Execute action, verify result immediately
- Async tests: Execute action, register on_nth_tick poller, verify completion
- All state queries via remote.call (no direct storage access in scenarios)
--]]

-- Load factorio_verse mod
require("__factorio_verse__.control")

-- Load test grid coordinates
local TestGrid = require("test_grid")

-- Load test suite
local test_suite = require("tests.test_suite")

-- ============================================================================
-- TEST RUNNER STATE
-- ============================================================================

local runner_state = {
    -- Async test tracking
    pending_async_tests = {},  -- {test_id -> {test_module, context, start_tick, timeout_ticks, poll_fn}}
    async_results = {},        -- {test_id -> result}
    next_test_id = 1,
}

-- ============================================================================
-- ASSERTION HELPERS
-- ============================================================================

local function assert_equals(expected, actual, message)
    if expected ~= actual then
        error(string.format("%s: expected %s, got %s", 
            message or "Assertion failed", 
            tostring(expected), 
            tostring(actual)))
    end
end

local function assert_true(condition, message)
    if not condition then
        error(message or "Assertion failed: expected true")
    end
end

local function assert_not_nil(value, message)
    if value == nil then
        error(message or "Assertion failed: expected non-nil value")
    end
end

local function assert_table_has_key(tbl, key, message)
    if type(tbl) ~= "table" or tbl[key] == nil then
        error(message or string.format("Assertion failed: table missing key '%s'", tostring(key)))
    end
end

-- Export assertion helpers for tests
local Assertions = {
    equals = assert_equals,
    is_true = assert_true,
    not_nil = assert_not_nil,
    has_key = assert_table_has_key,
}

-- ============================================================================
-- TEST CONTEXT HELPERS
-- ============================================================================

--- Create a test context with common utilities
--- @param test_name string
--- @return table context
local function create_test_context(test_name)
    return {
        test_name = test_name,
        surface = game.surfaces[1],
        assert = Assertions,
        grid = TestGrid,
        agent_id = nil,  -- Will be set if agent is created
        
        -- Helper to create an agent for the test
        create_agent = function(self)
            local result = remote.call("agent", "create_agents", 1, true)
            if result and result[1] then
                self.agent_id = result[1].agent_id
                return self.agent_id
            end
            error("Failed to create test agent")
        end,
        
        -- Helper to destroy test agent
        destroy_agent = function(self)
            if self.agent_id then
                pcall(function()
                    remote.call("agent", "destroy_agents", {self.agent_id}, false)
                end)
                self.agent_id = nil
            end
        end,
        
        -- Helper to call agent remote interface
        agent_call = function(self, method, ...)
            if not self.agent_id then
                error("No agent created for test")
            end
            return remote.call("agent_" .. self.agent_id, method, ...)
        end,
        
        -- Helper to place an entity on the surface
        place_entity = function(self, name, position, force)
            return self.surface.create_entity({
                name = name,
                position = position,
                force = force or "player",
            })
        end,
        
        -- Helper to find entity at position
        find_entity = function(self, name, position)
            return self.surface.find_entity(name, position)
        end,
        
        -- Helper to clear area around position
        clear_area = function(self, position, radius)
            radius = radius or 5
            local entities = self.surface.find_entities_filtered({
                position = position,
                radius = radius,
            })
            for _, entity in ipairs(entities) do
                if entity.valid and entity.type ~= "character" then
                    entity.destroy()
                end
            end
        end,
    }
end

-- ============================================================================
-- SYNC TEST RUNNER
-- ============================================================================

--- Run a synchronous test
--- @param test_name string Full test name (category.test)
--- @param test_module table Test module with setup/tests/teardown
--- @return table Result {test_name, passed, error, duration}
local function run_sync_test(test_name, test_module)
    local start_tick = game.tick
    local result = {
        test_name = test_name,
        passed = false,
        error = nil,
        duration = 0,
    }
    
    local context = create_test_context(test_name)
    
    -- Setup
    if test_module.setup then
        local ok, err = pcall(test_module.setup, context)
        if not ok then
            result.error = "Setup failed: " .. tostring(err)
            result.duration = game.tick - start_tick
            return result
        end
    end
    
    -- Run test function
    if test_module.test then
        local ok, err = pcall(test_module.test, context)
        if not ok then
            result.error = tostring(err)
            result.duration = game.tick - start_tick
            -- Teardown even on failure
            if test_module.teardown then
                pcall(test_module.teardown, context)
            end
            return result
        end
    end
    
    -- Teardown
    if test_module.teardown then
        local ok, err = pcall(test_module.teardown, context)
        if not ok then
            result.error = "Teardown failed: " .. tostring(err)
            result.duration = game.tick - start_tick
            return result
        end
    end
    
    -- Success
    result.passed = true
    result.duration = game.tick - start_tick
    return result
end

-- ============================================================================
-- ASYNC TEST RUNNER
-- ============================================================================

--- Start an asynchronous test
--- @param test_name string Full test name
--- @param test_module table Test module with setup/start/poll/verify/teardown
--- @return string test_id
local function start_async_test(test_name, test_module)
    local test_id = "async_" .. runner_state.next_test_id
    runner_state.next_test_id = runner_state.next_test_id + 1
    
    local context = create_test_context(test_name)
    context.test_id = test_id
    
    -- Setup
    if test_module.setup then
        local ok, err = pcall(test_module.setup, context)
        if not ok then
            runner_state.async_results[test_id] = {
                test_name = test_name,
                passed = false,
                error = "Setup failed: " .. tostring(err),
                duration = 0,
            }
            return test_id
        end
    end
    
    -- Start the async action
    if test_module.start then
        local ok, err = pcall(test_module.start, context)
        if not ok then
            runner_state.async_results[test_id] = {
                test_name = test_name,
                passed = false,
                error = "Start failed: " .. tostring(err),
                duration = 0,
            }
            if test_module.teardown then
                pcall(test_module.teardown, context)
            end
            return test_id
        end
    end
    
    -- Register for polling
    runner_state.pending_async_tests[test_id] = {
        test_name = test_name,
        test_module = test_module,
        context = context,
        start_tick = game.tick,
        timeout_ticks = test_module.timeout_ticks or 600,  -- Default 10 second timeout
    }
    
    return test_id
end

--- Poll pending async tests (called by on_nth_tick)
local function poll_async_tests()
    for test_id, test_data in pairs(runner_state.pending_async_tests) do
        local test_module = test_data.test_module
        local context = test_data.context
        local elapsed = game.tick - test_data.start_tick
        
        -- Check timeout
        if elapsed > test_data.timeout_ticks then
            runner_state.async_results[test_id] = {
                test_name = test_data.test_name,
                passed = false,
                error = "Timeout after " .. elapsed .. " ticks",
                duration = elapsed,
            }
            if test_module.teardown then
                pcall(test_module.teardown, context)
            end
            runner_state.pending_async_tests[test_id] = nil
            goto continue
        end
        
        -- Poll for completion
        if test_module.poll then
            local ok, is_complete = pcall(test_module.poll, context)
            if not ok then
                runner_state.async_results[test_id] = {
                    test_name = test_data.test_name,
                    passed = false,
                    error = "Poll failed: " .. tostring(is_complete),
                    duration = elapsed,
                }
                if test_module.teardown then
                    pcall(test_module.teardown, context)
                end
                runner_state.pending_async_tests[test_id] = nil
                goto continue
            end
            
            if is_complete then
                -- Verify results
                local verify_ok, verify_err = true, nil
                if test_module.verify then
                    verify_ok, verify_err = pcall(test_module.verify, context)
                end
                
                runner_state.async_results[test_id] = {
                    test_name = test_data.test_name,
                    passed = verify_ok,
                    error = verify_ok and nil or tostring(verify_err),
                    duration = elapsed,
                }
                
                if test_module.teardown then
                    pcall(test_module.teardown, context)
                end
                runner_state.pending_async_tests[test_id] = nil
            end
        end
        
        ::continue::
    end
end

-- ============================================================================
-- TEST SUITE EXECUTION
-- ============================================================================

--- Run all tests in a category
--- @param category string Category name
--- @return table Results {total, passed, failed, results, failures}
local function run_category(category)
    local results = {
        total = 0,
        passed = 0,
        failed = 0,
        duration = 0,
        results = {},
        failures = {},
    }
    
    local category_tests = test_suite[category]
    if not category_tests then
        results.error = "Category not found: " .. tostring(category)
        return results
    end
    
    local start_tick = game.tick
    
    for test_name, test_module in pairs(category_tests) do
        if type(test_module) == "table" then
            local full_name = category .. "." .. test_name
            local result
            
            -- Check if async test (has start and poll functions)
            if test_module.start and test_module.poll then
                -- For async tests, we start them but can't wait for completion
                -- in a single RCON call. Return pending status.
                local test_id = start_async_test(full_name, test_module)
                result = {
                    test_name = full_name,
                    passed = false,
                    pending = true,
                    test_id = test_id,
                    duration = 0,
                }
            else
                result = run_sync_test(full_name, test_module)
            end
            
            results.total = results.total + 1
            table.insert(results.results, result)
            
            if result.pending then
                -- Async test, don't count as passed/failed yet
            elseif result.passed then
                results.passed = results.passed + 1
            else
                results.failed = results.failed + 1
                table.insert(results.failures, result)
            end
        end
    end
    
    results.duration = game.tick - start_tick
    results.success_rate = results.total > 0 and (results.passed / results.total * 100) or 0
    return results
end

--- Run all tests
--- @return table Results
local function run_all_tests()
    local results = {
        total = 0,
        passed = 0,
        failed = 0,
        pending = 0,
        duration = 0,
        results = {},
        failures = {},
    }
    
    local start_tick = game.tick
    
    for category_name, category_tests in pairs(test_suite) do
        if type(category_tests) == "table" then
            local category_results = run_category(category_name)
            
            results.total = results.total + category_results.total
            results.passed = results.passed + category_results.passed
            results.failed = results.failed + category_results.failed
            
            for _, r in ipairs(category_results.results) do
                table.insert(results.results, r)
                if r.pending then
                    results.pending = (results.pending or 0) + 1
                end
            end
            for _, f in ipairs(category_results.failures) do
                table.insert(results.failures, f)
            end
        end
    end
    
    results.duration = game.tick - start_tick
    results.success_rate = results.total > 0 and (results.passed / results.total * 100) or 0
    return results
end

--- Run a single test by name
--- @param test_name string Full test name (category.test)
--- @return table Result
local function run_test(test_name)
    local category, test = test_name:match("(.+)%.(.+)")
    if not category or not test then
        return {
            error = "Invalid test name format. Expected 'category.test'"
        }
    end
    
    local test_module = test_suite[category] and test_suite[category][test]
    if not test_module then
        return {
            error = "Test not found: " .. test_name
        }
    end
    
    -- Check if async test
    if test_module.start and test_module.poll then
        local test_id = start_async_test(test_name, test_module)
        return {
            test_name = test_name,
            pending = true,
            test_id = test_id,
            message = "Async test started. Poll with get_async_result('" .. test_id .. "')"
        }
    end
    
    return run_sync_test(test_name, test_module)
end

-- ============================================================================
-- SCENARIO INITIALIZATION
-- ============================================================================

script.on_init(function()
    local surface = game.surfaces[1]
    
    -- Disable dynamic systems for deterministic testing
    game.map_settings.enemy_expansion.enabled = false
    game.map_settings.pollution.enabled = false
    
    log("================================================")
    log("Test Scenario Initialized")
    log("================================================")
    log("Map size: " .. TestGrid.MAP_SIZE .. "x" .. TestGrid.MAP_SIZE)
    log("Test block: " .. TestGrid.BLOCK_SIZE .. "x" .. TestGrid.BLOCK_SIZE .. " centered at (0,0)")
    log("")
    log("Test Categories:")
    for name, area in pairs(TestGrid.AREAS) do
        if area.category ~= "reserved" then
            log("  " .. name .. ": " .. area.description)
        end
    end
    log("================================================")
end)

-- Register on_nth_tick for async test polling (every 10 ticks)
script.on_nth_tick(10, function(event)
    poll_async_tests()
end)

-- ============================================================================
-- REMOTE INTERFACE
-- ============================================================================

remote.add_interface("test_runner", {
    -- Run all tests
    run_all_tests = function()
        local results = run_all_tests()
        return helpers.table_to_json(results)
    end,
    
    -- Run tests in a category
    run_category = function(category)
        local results = run_category(category)
        return helpers.table_to_json(results)
    end,
    
    -- Run a single test
    run_test = function(test_name)
        local result = run_test(test_name)
        return helpers.table_to_json(result)
    end,
    
    -- List all tests
    list_tests = function()
        local tests = {}
        for category_name, category_tests in pairs(test_suite) do
            if type(category_tests) == "table" then
                for test_name, _ in pairs(category_tests) do
                    table.insert(tests, category_name .. "." .. test_name)
                end
            end
        end
        return helpers.table_to_json(tests)
    end,
    
    -- List categories
    list_categories = function()
        local categories = {}
        for category_name, _ in pairs(test_suite) do
            table.insert(categories, category_name)
        end
        return helpers.table_to_json(categories)
    end,
    
    -- Get async test result
    get_async_result = function(test_id)
        local result = runner_state.async_results[test_id]
        if result then
            return helpers.table_to_json(result)
        end
        
        local pending = runner_state.pending_async_tests[test_id]
        if pending then
            return helpers.table_to_json({
                test_id = test_id,
                pending = true,
                elapsed_ticks = game.tick - pending.start_tick,
            })
        end
        
        return helpers.table_to_json({
            error = "Test ID not found: " .. tostring(test_id)
        })
    end,
    
    -- Get all pending async tests
    get_pending_tests = function()
        local pending = {}
        for test_id, data in pairs(runner_state.pending_async_tests) do
            table.insert(pending, {
                test_id = test_id,
                test_name = data.test_name,
                elapsed_ticks = game.tick - data.start_tick,
            })
        end
        return helpers.table_to_json(pending)
    end,
})

log("Test scenario loaded. test_runner remote interface ready.")
