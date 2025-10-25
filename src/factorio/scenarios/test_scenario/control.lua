-- Test scenario for FactoryVerse actions
-- Simple test framework that verifies mod API by calling it like agents would

-- Load factorio_verse mod
require("__factorio_verse__.control")

-- Load test suite from this scenario's tests
local test_suite = require("tests.test_suite")

-- ============================================================================
-- Simple Test Runner - runs tests in the scenario
-- ============================================================================

local function run_test(test_name, test_module)
    local start_tick = game.tick
    local result = {
        test_name = test_name,
        passed = false,
        error = nil,
        duration = 0,
        assertions = 0
    }
    
    local context = {}
    
    -- Setup
    if test_module.setup then
        local ok, err = pcall(test_module.setup, context)
        if not ok then
            result.error = "Setup failed: " .. tostring(err)
            result.duration = game.tick - start_tick
            return result
        end
    end
    
    -- Run tests (all functions in test_module.tests table)
    if test_module.tests then
        for test_func_name, test_func in pairs(test_module.tests) do
            local ok, err = pcall(test_func, context)
            if not ok then
                result.error = test_func_name .. ": " .. tostring(err)
                result.duration = game.tick - start_tick
                -- Teardown even on failure
                if test_module.teardown then
                    pcall(test_module.teardown, context)
                end
                return result
            end
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
    
    -- All passed
    result.passed = true
    result.duration = game.tick - start_tick
    return result
end

local function run_all_tests()
    local start_tick = game.tick
    local results = {
        total = 0,
        passed = 0,
        failed = 0,
        duration = 0,
        results = {},
        failures = {}
    }
    
    -- Run tests by category
    for category_name, category_tests in pairs(test_suite) do
        if type(category_tests) == "table" then
            for test_name, test_module in pairs(category_tests) do
                if type(test_module) == "table" and test_module.tests then
                    local full_name = category_name .. "." .. test_name
                    local result = run_test(full_name, test_module)
                    
                    results.total = results.total + 1
                    table.insert(results.results, result)
                    
                    if result.passed then
                        results.passed = results.passed + 1
                    else
                        results.failed = results.failed + 1
                        table.insert(results.failures, result)
                    end
                end
            end
        end
    end
    
    results.duration = game.tick - start_tick
    results.success_rate = results.total > 0 and (results.passed / results.total * 100) or 0
    return results
end

local function run_category(category)
    local start_tick = game.tick
    local results = {
        total = 0,
        passed = 0,
        failed = 0,
        duration = 0,
        results = {},
        failures = {}
    }
    
    local category_tests = test_suite[category]
    if not category_tests then
        results.error = "Category not found: " .. category
        return results
    end
    
    for test_name, test_module in pairs(category_tests) do
        if type(test_module) == "table" and test_module.tests then
            local full_name = category .. "." .. test_name
            local result = run_test(full_name, test_module)
            
            results.total = results.total + 1
            table.insert(results.results, result)
            
            if result.passed then
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

-- ============================================================================
-- Remote Interface
-- ============================================================================

remote.add_interface("test_runner", {
    -- Test execution
    run_all_tests = function()
        local results = run_all_tests()
        return helpers.table_to_json(results)
    end,
    
    run_test = function(test_name)
        -- Find the test in the suite
        local category, test = test_name:match("(.+)%.(.+)")
        if not category or not test then
            return helpers.table_to_json({
                error = "Invalid test name format. Expected 'category.test'"
            })
        end
        
        local test_module = test_suite[category] and test_suite[category][test]
        if not test_module then
            return helpers.table_to_json({
                error = "Test not found: " .. test_name
            })
        end
        
        local result = run_test(test_name, test_module)
        return helpers.table_to_json(result)
    end,
    
    run_category = function(category)
        local results = run_category(category)
        return helpers.table_to_json(results)
    end,
    
    list_tests = function()
        local tests = {}
        for category_name, category_tests in pairs(test_suite) do
            if type(category_tests) == "table" then
                for test_name, test_module in pairs(category_tests) do
                    if type(test_module) == "table" and test_module.tests then
                        table.insert(tests, category_name .. "." .. test_name)
                    end
                end
            end
        end
        return helpers.table_to_json(tests)
    end,
    
    list_categories = function()
        local categories = {}
        for category_name, _ in pairs(test_suite) do
            table.insert(categories, category_name)
        end
        return helpers.table_to_json(categories)
    end,
    
    -- Legacy variants for compatibility
    run_tests_verbose = function()
        local results = run_all_tests()
        return helpers.table_to_json(results)
    end,
    
    run_tests_quiet = function()
        local results = run_all_tests()
        return helpers.table_to_json(results)
    end
})

log("Test scenario loaded. test_runner remote interface ready.")
