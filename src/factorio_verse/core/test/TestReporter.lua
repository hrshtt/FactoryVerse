--- @class TestReporter
--- Test results formatting and reporting
local TestReporter = {}
TestReporter.__index = TestReporter

--- Create a new TestReporter instance
--- @return TestReporter
function TestReporter:new()
    local instance = {}
    setmetatable(instance, self)
    return instance
end

--- Format test results as JSON
--- @param suite_result table TestSuite result
--- @param verbose boolean|nil
--- @return string
function TestReporter.format_json(suite_result, verbose)
    verbose = verbose or false
    
    local result = {
        total = suite_result.total,
        passed = suite_result.passed,
        failed = suite_result.failed,
        duration = suite_result.duration,
        success_rate = suite_result.total > 0 and (suite_result.passed / suite_result.total) * 100 or 0
    }
    
    if verbose then
        result.results = {}
        for _, test_result in ipairs(suite_result.results) do
            table.insert(result.results, {
                test_name = test_result.test_name,
                passed = test_result.passed,
                duration = test_result.duration,
                assertions = test_result.assertions,
                error = test_result.error
            })
        end
    end
    
    if suite_result.failures and #suite_result.failures > 0 then
        result.failures = {}
        for _, failure in ipairs(suite_result.failures) do
            table.insert(result.failures, {
                test_name = failure.test_name,
                error = failure.error,
                duration = failure.duration
            })
        end
    end
    
    return helpers.table_to_json(result)
end

--- Format test results as human-readable text
--- @param suite_result table TestSuite result
--- @param verbose boolean|nil
--- @return string
function TestReporter.format_text(suite_result, verbose)
    verbose = verbose or false
    
    local lines = {}
    
    -- Header
    table.insert(lines, "=== Test Results ===")
    table.insert(lines, "")
    
    -- Summary
    table.insert(lines, "Summary:")
    table.insert(lines, "  Total: " .. suite_result.total)
    table.insert(lines, "  Passed: " .. suite_result.passed)
    table.insert(lines, "  Failed: " .. suite_result.failed)
    table.insert(lines, "  Success Rate: " .. string.format("%.1f%%", suite_result.success_rate))
    table.insert(lines, "  Duration: " .. suite_result.duration .. " ticks")
    table.insert(lines, "")
    
    -- Failures
    if suite_result.failures and #suite_result.failures > 0 then
        table.insert(lines, "Failures:")
        for _, failure in ipairs(suite_result.failures) do
            table.insert(lines, "  FAIL: " .. failure.test_name)
            table.insert(lines, "    " .. (failure.error or "Unknown error"))
            table.insert(lines, "    Duration: " .. failure.duration .. " ticks")
            table.insert(lines, "")
        end
    end
    
    -- Verbose results
    if verbose and suite_result.results then
        table.insert(lines, "All Results:")
        for _, test_result in ipairs(suite_result.results) do
            local status = test_result.passed and "PASS" or "FAIL"
            table.insert(lines, "  " .. status .. ": " .. test_result.test_name .. 
                         " (" .. test_result.duration .. " ticks, " .. test_result.assertions .. " assertions)")
            if test_result.error then
                table.insert(lines, "    " .. test_result.error)
            end
        end
    end
    
    return table.concat(lines, "\n")
end

--- Format test results for console output
--- @param suite_result table TestSuite result
--- @return string
function TestReporter.format_console(suite_result)
    local lines = {}
    
    -- Simple summary
    table.insert(lines, "Tests: " .. suite_result.passed .. "/" .. suite_result.total .. " passed")
    
    if suite_result.failed > 0 then
        table.insert(lines, "Failures: " .. suite_result.failed)
        for _, failure in ipairs(suite_result.failures) do
            table.insert(lines, "  " .. failure.test_name .. ": " .. (failure.error or "Unknown error"))
        end
    end
    
    return table.concat(lines, "\n")
end

--- Log test results to game console
--- @param suite_result table TestSuite result
--- @param verbose boolean|nil
function TestReporter.log_results(suite_result, verbose)
    verbose = verbose or false
    
    local text = TestReporter.format_text(suite_result, verbose)
    log(text)
    
    -- Also print to console for immediate visibility
    for line in string.gmatch(text, "[^\n]+") do
        print(line)
    end
end

--- Create a test summary for quick reference
--- @param suite_result table TestSuite result
--- @return table
function TestReporter.create_summary(suite_result)
    return {
        total = suite_result.total,
        passed = suite_result.passed,
        failed = suite_result.failed,
        success_rate = suite_result.total > 0 and (suite_result.passed / suite_result.total) * 100 or 0,
        duration = suite_result.duration,
        has_failures = suite_result.failed > 0,
        failure_count = suite_result.failures and #suite_result.failures or 0
    }
end

--- Export test results to file (if file system access is available)
--- @param suite_result table TestSuite result
--- @param filename string|nil
--- @param format string|nil
--- @return boolean
function TestReporter.export_results(suite_result, filename, format)
    filename = filename or "test_results.json"
    format = format or "json"
    
    local content
    if format == "json" then
        content = TestReporter.format_json(suite_result, true)
    else
        content = TestReporter.format_text(suite_result, true)
    end
    
    -- Note: In Factorio, we can't directly write to files
    -- This would need to be handled by external tools via RCON
    log("Test results exported to: " .. filename)
    log("Content length: " .. string.len(content) .. " characters")
    
    return true
end

--- Create a test report with timing analysis
--- @param suite_result table TestSuite result
--- @return table
function TestReporter.create_timing_report(suite_result)
    local report = {
        total_duration = suite_result.duration,
        average_duration = 0,
        slowest_test = nil,
        fastest_test = nil,
        timing_breakdown = {}
    }
    
    if suite_result.results and #suite_result.results > 0 then
        local total_time = 0
        local slowest_duration = 0
        local fastest_duration = math.huge
        
        for _, test_result in ipairs(suite_result.results) do
            total_time = total_time + test_result.duration
            
            if test_result.duration > slowest_duration then
                slowest_duration = test_result.duration
                report.slowest_test = {
                    name = test_result.test_name,
                    duration = test_result.duration
                }
            end
            
            if test_result.duration < fastest_duration then
                fastest_duration = test_result.duration
                report.fastest_test = {
                    name = test_result.test_name,
                    duration = test_result.duration
                }
            end
            
            table.insert(report.timing_breakdown, {
                test_name = test_result.test_name,
                duration = test_result.duration,
                passed = test_result.passed
            })
        end
        
        report.average_duration = total_time / #suite_result.results
    end
    
    return report
end

return TestReporter:new()
