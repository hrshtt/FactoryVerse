--[[
Test Suite Registration for FactoryVerse

Aggregates all test modules by category for execution by the test runner.

Categories:
- agent: Agent lifecycle (create, destroy, inspect, teleport)
- entity_ops: Entity operations (place, pickup, set_recipe)
- inventory: Inventory operations (get/set items, limits, filters)
- crafting: Crafting operations (enqueue, dequeue, completion)
- mining: Mining operations (mine resource, completion)
- walking: Walking operations (walk to, completion)
- charting: Charting operations (chart spawn, chart view)
--]]

return {
    -- Synchronous tests
    agent = {
        test_create = require("tests.agent.test_create"),
        test_destroy = require("tests.agent.test_destroy"),
        test_teleport = require("tests.agent.test_teleport"),
        test_inspect = require("tests.agent.test_inspect"),
    },
    
    entity_ops = {
        test_place_entity = require("tests.entity_ops.test_place_entity"),
        test_pickup_entity = require("tests.entity_ops.test_pickup_entity"),
        test_set_recipe = require("tests.entity_ops.test_set_recipe"),
    },
    
    inventory = {
        test_put_item = require("tests.inventory.test_put_item"),
        test_take_item = require("tests.inventory.test_take_item"),
        test_set_limit = require("tests.inventory.test_set_limit"),
        test_set_filter = require("tests.inventory.test_set_filter"),
    },
    
    -- Asynchronous tests (use start/poll/verify pattern)
    crafting = {
        test_enqueue = require("tests.crafting.test_enqueue"),
        test_dequeue = require("tests.crafting.test_dequeue"),
        test_completion = require("tests.crafting.test_completion"),
    },
    
    mining = {
        test_mine_resource = require("tests.mining.test_mine_resource"),
        test_mine_completion = require("tests.mining.test_mine_completion"),
        test_stop_mining = require("tests.mining.test_stop_mining"),
    },
    
    walking = {
        test_walk_to = require("tests.walking.test_walk_to"),
        test_walk_completion = require("tests.walking.test_walk_completion"),
        test_stop_walking = require("tests.walking.test_stop_walking"),
    },
    
    charting = {
        test_chart_spawn = require("tests.charting.test_chart_spawn"),
    },
}

