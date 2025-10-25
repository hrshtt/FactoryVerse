--- TestAPI.lua: Remote interface for test execution and management
--- Provides test_runner remote interface for scenarios to call test functions

local TestRunner = require("__factorio_verse__.core.test.TestRunner")
local TestReporter = require("__factorio_verse__.core.test.TestReporter")

local M = {}
M.test_helpers = {}

-- Store test suite provided by scenario
if not storage.test_api_state then
    storage.test_api_state = {
        test_suite = nil
    }
end

-- Direct registration function that scenario can call without serialization
-- This is called directly by scenario, not via remote.call
M.register_test_suite_direct = function(test_suite_table)
    if test_suite_table and type(test_suite_table) == "table" then
        storage.test_api_state.test_suite = test_suite_table
        local category_count = 0
        for _ in pairs(test_suite_table) do
            category_count = category_count + 1
        end
        log("Test suite registered directly with " .. tostring(category_count) .. " categories")
        return true
    end
    return false
end

-- Get registered test suite (internal helper)
local function get_test_suite()
    if not storage.test_api_state.test_suite then
        error("No test suite registered. Scenario must call test_api.register_test_suite_direct(test_suite)")
    end
    return storage.test_api_state.test_suite
end

-- Spawn test agents
M.test_helpers.spawn_agent = function(count, destroy_existing)
    local GameState = require("__factorio_verse__.core.game_state.GameState")
    return GameState:new():agent_state():create_agent_characters(count or 1, destroy_existing or false)
end

-- Get agent info
M.test_helpers.get_agent = function(agent_id)
    local GameState = require("__factorio_verse__.core.game_state.GameState")
    local agent = GameState:new():agent_state():get_agent(agent_id)
    if agent and agent.valid then
        return {
            valid = true,
            position = agent.position
        }
    end
    return { valid = false }
end

-- Clear all agents
M.test_helpers.clear_agents = function()
    local GameState = require("__factorio_verse__.core.game_state.GameState")
    return GameState:new():agent_state():force_destroy_agents()
end

-- Run all tests
M.test_helpers.run_all_tests = function()
    local test_suite = get_test_suite()
    
    if not storage.mod_test_runner then
        storage.mod_test_runner = TestRunner.create_test_runner()
    end
    
    local results = TestRunner.run_suite(storage.mod_test_runner, test_suite)
    TestReporter.log_results(results, true)
    return TestReporter.format_json(results, true)
end

-- Run a specific test
M.test_helpers.run_test = function(test_name)
    local test_suite = get_test_suite()
    
    if not storage.mod_test_runner then
        storage.mod_test_runner = TestRunner.create_test_runner()
    end
    
    local result = TestRunner.run_test(storage.mod_test_runner, test_name, test_suite)
    if result then
        local results = {
            total = 1,
            passed = result.passed and 1 or 0,
            failed = result.passed and 0 or 1,
            duration = result.duration,
            success_rate = result.passed and 100 or 0,
            results = {result},
            failures = result.passed and {} or {result}
        }
        TestReporter.log_results(results, true)
        return TestReporter.format_json(results, true)
    else
        return TestReporter.format_json({
            total = 0,
            passed = 0,
            failed = 1,
            duration = 0,
            results = {},
            failures = {{test_name = test_name, error = "Test not found"}}
        }, true)
    end
end

-- Run all tests in a category
M.test_helpers.run_category = function(category)
    local test_suite = get_test_suite()
    
    if not storage.mod_test_runner then
        storage.mod_test_runner = TestRunner.create_test_runner()
    end
    
    local results = TestRunner.run_category(storage.mod_test_runner, category, test_suite)
    TestReporter.log_results(results, true)
    return TestReporter.format_json(results, true)
end

-- List all tests
M.test_helpers.list_tests = function()
    local test_suite = get_test_suite()
    local tests = {}
    for category_name, category_tests in pairs(test_suite) do
        if type(category_tests) == "table" then
            for test_name, test_module in pairs(category_tests) do
                -- Only add the test name, don't try to serialize the module
                if type(test_module) == "table" and test_module.tests then
                    table.insert(tests, category_name .. "." .. test_name)
                end
            end
        end
    end
    -- Only serialize the string list, not the test functions
    return helpers.table_to_json(tests)
end

-- List all test categories
M.test_helpers.list_categories = function()
    local test_suite = get_test_suite()
    local categories = {}
    for category_name, _ in pairs(test_suite) do
        table.insert(categories, category_name)
    end
    -- Only serialize the string list, not the test modules
    return helpers.table_to_json(categories)
end

-- Register test_runner remote interface
M.load_test_helpers = function()
    if remote.interfaces["test_runner"] then
        remote.remove_interface("test_runner")
    end
    remote.add_interface("test_runner", M.test_helpers)
    log("Loaded: test_runner remote interface")
end

return M
