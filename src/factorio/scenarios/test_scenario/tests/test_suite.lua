-- Test suite registration for FactoryVerse actions
-- Aggregates all test modules for execution

return {
    entity = {
        rotate = require("tests.entity.test_entity_rotate"),
        pickup = require("tests.entity.test_entity_pickup"),
        set_recipe = require("tests.entity.test_entity_set_recipe")
    },
    inventory = {
        set_item = require("tests.inventory.test_inventory_set_item"),
        get_item = require("tests.inventory.test_inventory_get_item"),
        set_limit = require("tests.inventory.test_inventory_set_limit")
    },
    integration = {
        full_workflow = require("tests.integration.test_full_workflow")
    }
}
