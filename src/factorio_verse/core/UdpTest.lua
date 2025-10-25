-- UdpTest.lua: Proof-of-concept module to test UDP blocking behavior
-- This module is designed to be completely self-contained and removable

local M = {}

-- Configuration
local UDP_TEST_ENABLED = true
local TARGET_HOST = "127.0.0.1"
local TARGET_PORT = 34198
local PAYLOAD_SIZE_KB = 1
local FREQUENCY_TICKS = 1

-- Test state
local test_state = {
    enabled = false,
    packets_sent = 0,
    packets_failed = 0,
    total_bytes_sent = 0,
    tick_times = {},
    sequence_number = 0,
    start_tick = 0
}

-- Initialize storage namespace
if not storage.udp_test then
    storage.udp_test = {}
end

-- Payload generators for different sizes
local function generate_small_payload(sequence)
    return {
        type = "small_test",
        sequence = sequence,
        tick = game.tick,
        timestamp = game.tick / 60.0,
        data = string.rep("A", 1000) -- 1KB
    }
end

local function generate_medium_payload(sequence)
    return {
        type = "medium_test", 
        sequence = sequence,
        tick = game.tick,
        timestamp = game.tick / 60.0,
        entities = {},
        data = string.rep("B", 10000) -- 10KB
    }
end

local function generate_large_payload(sequence)
    local entities = {}
    for i = 1, 100 do
        table.insert(entities, {
            id = i,
            name = "test-entity-" .. i,
            position = { x = i * 10, y = i * 10 },
            health = 100,
            energy = 50,
            status = "working"
        })
    end
    
    return {
        type = "large_test",
        sequence = sequence,
        tick = game.tick,
        timestamp = game.tick / 60.0,
        entities = entities,
        resources = {
            iron_ore = 1000,
            copper_ore = 2000,
            coal = 500
        },
        data = string.rep("C", 100000) -- 100KB
    }
end

local function generate_huge_payload(sequence)
    local entities = {}
    for i = 1, 1000 do
        table.insert(entities, {
            id = i,
            name = "test-entity-" .. i,
            position = { x = i * 10, y = i * 10 },
            health = 100,
            energy = 50,
            status = "working",
            inventory = {
                iron_plate = 10,
                copper_plate = 15,
                steel_plate = 5
            }
        })
    end
    
    return {
        type = "huge_test",
        sequence = sequence,
        tick = game.tick,
        timestamp = game.tick / 60.0,
        entities = entities,
        resources = {
            iron_ore = 10000,
            copper_ore = 20000,
            coal = 5000,
            stone = 3000
        },
        data = string.rep("D", 200000) -- 200KB
    }
end

-- Get payload generator based on size
local function get_payload_generator(size_kb)
    if size_kb <= 1 then
        return generate_small_payload
    elseif size_kb <= 10 then
        return generate_medium_payload
    elseif size_kb <= 100 then
        return generate_large_payload
    else
        return generate_huge_payload
    end
end

-- Measure tick timing
local function measure_tick_time()
    local start_time = game.tick
    return function()
        local end_time = game.tick
        local duration = end_time - start_time
        table.insert(test_state.tick_times, duration)
        
        -- Keep only last 100 measurements
        if #test_state.tick_times > 100 then
            table.remove(test_state.tick_times, 1)
        end
        return duration
    end
end

-- Send UDP packet with timing measurement
local function send_udp_packet(payload)
    local measure = measure_tick_time()
    
    local success, error_msg = pcall(function()
        local json_data = helpers.table_to_json(payload)
        helpers.send_udp(TARGET_PORT, json_data)
        
        test_state.packets_sent = test_state.packets_sent + 1
        test_state.total_bytes_sent = test_state.total_bytes_sent + #json_data
        test_state.sequence_number = test_state.sequence_number + 1
        
        return #json_data
    end)
    
    local tick_duration = measure()
    
    if not success then
        test_state.packets_failed = test_state.packets_failed + 1
        log("UDP send failed: " .. tostring(error_msg))
    end
    
    return success, tick_duration
end

-- Main test handler
local function run_udp_test()
    if not test_state.enabled then
        return
    end
    
    local payload_generator = get_payload_generator(PAYLOAD_SIZE_KB)
    local payload = payload_generator(test_state.sequence_number)
    
    local success, tick_duration = send_udp_packet(payload)
    
    -- Log every 10 packets for testing
    if test_state.packets_sent % 10 == 0 then
        local avg_tick_time = 0
        if #test_state.tick_times > 0 then
            local sum = 0
            for _, time in ipairs(test_state.tick_times) do
                sum = sum + time
            end
            avg_tick_time = sum / #test_state.tick_times
        end
        
        log(string.format("UDP Test: %d packets sent, %d failed, avg tick time: %.4fs", 
            test_state.packets_sent, test_state.packets_failed, avg_tick_time))
    end
end

-- Auto-start test for demonstration
local function auto_start_test()
    if UDP_TEST_ENABLED then
        test_state.enabled = true
        test_state.packets_sent = 0
        test_state.packets_failed = 0
        test_state.total_bytes_sent = 0
        test_state.tick_times = {}
        test_state.sequence_number = 0
        test_state.start_tick = game.tick
        
        log("UDP Test auto-started: sending 1KB packets every tick to 127.0.0.1:34198")
    end
end

-- Public API
function M.start_test(host, port, size_kb, frequency_ticks)
    TARGET_HOST = host or "127.0.0.1"
    TARGET_PORT = port or 34198
    PAYLOAD_SIZE_KB = size_kb or 1
    FREQUENCY_TICKS = frequency_ticks or 1
    
    test_state.enabled = true
    test_state.packets_sent = 0
    test_state.packets_failed = 0
    test_state.total_bytes_sent = 0
    test_state.tick_times = {}
    test_state.sequence_number = 0
    test_state.start_tick = game.tick
    
    log(string.format("UDP Test started: %s:%d, %dKB payload, every %d ticks", 
        TARGET_HOST, TARGET_PORT, PAYLOAD_SIZE_KB, FREQUENCY_TICKS))
end

function M.stop_test()
    test_state.enabled = false
    log("UDP Test stopped")
end

function M.get_stats()
    local avg_tick_time = 0
    if #test_state.tick_times > 0 then
        local sum = 0
        for _, time in ipairs(test_state.tick_times) do
            sum = sum + time
        end
        avg_tick_time = sum / #test_state.tick_times
    end
    
    return {
        enabled = test_state.enabled,
        packets_sent = test_state.packets_sent,
        packets_failed = test_state.packets_failed,
        total_bytes_sent = test_state.total_bytes_sent,
        avg_tick_time = avg_tick_time,
        max_tick_time = #test_state.tick_times > 0 and math.max(table.unpack(test_state.tick_times)) or 0,
        min_tick_time = #test_state.tick_times > 0 and math.min(table.unpack(test_state.tick_times)) or 0,
        test_duration_ticks = game.tick - test_state.start_tick,
        target_host = TARGET_HOST,
        target_port = TARGET_PORT,
        payload_size_kb = PAYLOAD_SIZE_KB,
        frequency_ticks = FREQUENCY_TICKS
    }
end

function M.get_events()
    if not UDP_TEST_ENABLED then
        return nil
    end
    
    return {
        [FREQUENCY_TICKS] = run_udp_test
    }
end

-- Enable/disable the test module
function M.set_enabled(enabled)
    UDP_TEST_ENABLED = enabled
    if not enabled then
        test_state.enabled = false
    end
end

return M
