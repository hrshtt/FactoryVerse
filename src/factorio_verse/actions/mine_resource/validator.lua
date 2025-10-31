local ValidatorRegistry = require("core.action.ValidatorRegistry")

local validator_registry = ValidatorRegistry:new()
local GameState = require("core.game_state.GameState")

--- Validate that the given (x, y) is a resource tile of the correct type
--- @param params table
--- @return boolean
local function validate_resource_tile(params)
    local resource_name = params.resource_name
    -- if not resource_name then
    --     error("Missing required param: resource_name")
    -- end
    -- if not params.x or not params.y then
    --     error("Missing required params: x and y")
    -- end

    local surface = game.surfaces[1]

    local tile_entities = surface.find_entities_filtered{
        area = {{params.x, params.y}, {params.x + 1, params.y + 1}},
        type = "resource"
    }

    for _, ent in ipairs(tile_entities) do
        if ent.name == resource_name then
            return true
        end
    end

    error(string.format("No resource tile of type '%s' at (%d, %d)", resource_name, params.x, params.y))
end

validator_registry:register("mine_resource", validate_resource_tile)


return validator_registry
