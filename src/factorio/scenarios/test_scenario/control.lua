-- Test scenario for FactoryVerse actions
-- Loads the main mod and provides test execution interface

-- Load factorio_verse mod
require("__factorio_verse__.control")

-- Load test framework
local TestRunner = require("__factorio_verse__.core.test.TestRunner")
local TestReporter = require("__factorio_verse__.core.test.TestReporter")
local test_suite = require("__factorio_verse__.tests.test_suite")

-- Initialize test runner on script load
script.on_init(function()
    if not storage.test_runner then
        storage.test_runner = TestRunner.create_test_runner()
        log("Created new test_runner instance in on_init")
    end
end)

script.on_load(function()
    if not storage.test_runner then
        storage.test_runner = TestRunner.create_test_runner()
        log("Created test_runner instance on load")
    end
end)

-- Register remote interface for test execution
remote.add_interface("test_runner", {
    run_all_tests = function()
        log("Running all tests...")
        local results = TestRunner.run_suite(storage.test_runner, test_suite)
        TestReporter.log_results(results, true)
        return TestReporter.format_json(results, true)
    end,
    
    run_test = function(test_name)
        log("Running test: " .. test_name)
        local result = TestRunner.run_test(storage.test_runner, test_name, test_suite)
        if result then
            local results = {
                total = 1,
                passed = result.passed and 1 or 0,
                failed = result.passed and 0 or 1,
                duration = result.duration,
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
    end,
    
    run_category = function(category)
        log("Running category: " .. category)
        local results = TestRunner.run_category(storage.test_runner, category, test_suite)
        TestReporter.log_results(results, true)
        return TestReporter.format_json(results, true)
    end,
    
    get_results = function()
        return TestReporter.format_json(TestRunner.get_results(storage.test_runner), true)
    end,
    
    -- Additional test management functions
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
    
    -- Test execution with custom options
    run_tests_verbose = function()
        log("Running all tests (verbose mode)...")
        local results = TestRunner.run_suite(storage.test_runner, test_suite)
        TestReporter.log_results(results, true)
        return TestReporter.format_text(results, true)
    end,
    
    run_tests_quiet = function()
        log("Running all tests (quiet mode)...")
        local results = TestRunner.run_suite(storage.test_runner, test_suite)
        return TestReporter.format_console(results)
    end
})

log("Test scenario loaded. Use remote.call('test_runner', 'run_all_tests') to run tests.")
