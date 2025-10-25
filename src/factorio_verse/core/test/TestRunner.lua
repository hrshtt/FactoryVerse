--- @class TestRunner
--- Test execution engine for FactoryVerse actions
local TestRunner = {}
TestRunner.__index = TestRunner

--- @class TestResult
--- @field test_name string
--- @field passed boolean
--- @field error string|nil
--- @field duration number
--- @field assertions number

--- @class TestSuite
--- @field total number
--- @field passed number
--- @field failed number
--- @field duration number
--- @field results table<TestResult>
--- @field failures table<TestResult>

--- Create a new TestRunner instance
--- @return TestRunner
function TestRunner:new()
    local instance = {
        results = {},
        current_test = nil,
        current_context = nil
    }
    setmetatable(instance, self)
    return instance
end

--- Run a complete test suite
--- @param test_suite table Test suite structure
--- @return TestSuite
function TestRunner:run_suite(test_suite)
    local start_time = game.tick
    local suite_result = {
        total = 0,
        passed = 0,
        failed = 0,
        duration = 0,
        results = {},
        failures = {}
    }
    
    self.results = {}
    
    -- Run tests by category
    for category_name, category_tests in pairs(test_suite) do
        if type(category_tests) == "table" then
            for test_name, test_module in pairs(category_tests) do
                if type(test_module) == "table" and test_module.tests then
                    local full_test_name = category_name .. "." .. test_name
                    local result = self:run_test_module(full_test_name, test_module)
                    
                    suite_result.total = suite_result.total + 1
                    table.insert(suite_result.results, result)
                    
                    if result.passed then
                        suite_result.passed = suite_result.passed + 1
                    else
                        suite_result.failed = suite_result.failed + 1
                        table.insert(suite_result.failures, result)
                    end
                end
            end
        end
    end
    
    suite_result.duration = game.tick - start_time
    return suite_result
end

--- Run a single test module
--- @param test_name string Full test name (category.test)
--- @param test_module table Test module with setup, tests, teardown
--- @return TestResult
function TestRunner:run_test_module(test_name, test_module)
    local start_time = game.tick
    local result = {
        test_name = test_name,
        passed = false,
        error = nil,
        duration = 0,
        assertions = 0
    }
    
    self.current_test = test_name
    self.current_context = {}
    
    -- Setup
    if test_module.setup then
        local ok, err = pcall(test_module.setup, self.current_context)
        if not ok then
            result.error = "Setup failed: " .. tostring(err)
            result.duration = game.tick - start_time
            return result
        end
    end
    
    -- Run individual test cases
    local test_cases_passed = 0
    local total_test_cases = 0
    
    for case_name, test_function in pairs(test_module.tests) do
        if type(test_function) == "function" then
            total_test_cases = total_test_cases + 1
            
            local case_ok, case_err = pcall(test_function, self.current_context)
            if case_ok then
                test_cases_passed = test_cases_passed + 1
            else
                result.error = "Test case '" .. case_name .. "' failed: " .. tostring(case_err)
                break
            end
        end
    end
    
    -- Teardown
    if test_module.teardown then
        local ok, err = pcall(test_module.teardown, self.current_context)
        if not ok and not result.error then
            result.error = "Teardown failed: " .. tostring(err)
        end
    end
    
    result.passed = (test_cases_passed == total_test_cases) and (result.error == nil)
    result.duration = game.tick - start_time
    
    return result
end

--- Run a specific test by name
--- @param test_name string Test name (category.test)
--- @param test_suite table Test suite structure
--- @return TestResult|nil
function TestRunner:run_test(test_name, test_suite)
    local parts = {}
    for part in string.gmatch(test_name, "[^%.]+") do
        table.insert(parts, part)
    end
    
    if #parts ~= 2 then
        return {
            test_name = test_name,
            passed = false,
            error = "Invalid test name format. Expected 'category.test'",
            duration = 0,
            assertions = 0
        }
    end
    
    local category = parts[1]
    local test = parts[2]
    
    if test_suite[category] and test_suite[category][test] then
        return self:run_test_module(test_name, test_suite[category][test])
    else
        return {
            test_name = test_name,
            passed = false,
            error = "Test not found: " .. test_name,
            duration = 0,
            assertions = 0
        }
    end
end

--- Run all tests in a category
--- @param category string Category name
--- @param test_suite table Test suite structure
--- @return TestSuite
function TestRunner:run_category(category, test_suite)
    local start_time = game.tick
    local suite_result = {
        total = 0,
        passed = 0,
        failed = 0,
        duration = 0,
        results = {},
        failures = {}
    }
    
    if test_suite[category] then
        for test_name, test_module in pairs(test_suite[category]) do
            if type(test_module) == "table" and test_module.tests then
                local full_test_name = category .. "." .. test_name
                local result = self:run_test_module(full_test_name, test_module)
                
                suite_result.total = suite_result.total + 1
                table.insert(suite_result.results, result)
                
                if result.passed then
                    suite_result.passed = suite_result.passed + 1
                else
                    suite_result.failed = suite_result.failed + 1
                    table.insert(suite_result.failures, result)
                end
            end
        end
    end
    
    suite_result.duration = game.tick - start_time
    return suite_result
end

--- Get current test results
--- @return table
function TestRunner:get_results()
    return self.results
end

--- Get current test context (for assertions)
--- @return table|nil
function TestRunner:get_current_context()
    return self.current_context
end

--- Increment assertion count for current test
function TestRunner:increment_assertions()
    if self.current_test then
        for _, result in ipairs(self.results) do
            if result.test_name == self.current_test then
                result.assertions = result.assertions + 1
                break
            end
        end
    end
end

return TestRunner:new()
