local ValidatorRegistry = require("core.action.ValidatorRegistry")

local validator_registry = ValidatorRegistry:new()

--- @param game_state GameState
--- @param params StartResearchParams
--- @return boolean
local function can_research_technology(game_state, params)
    local agent = game_state:agent_state():get_agent(params.agent_id)
    local force = agent.force
    local tech_name = params.technology_name
    local tech = force.technologies[tech_name]

    if not tech then
        error("Technology doesn't exist: " .. tech_name)
    end

    if tech.researched then
        error("Technology is already researched: " .. tech_name)
    end

    if force.current_research and force.current_research.name == tech_name then
        error("Technology is already being researched: " .. tech_name)
    end

    if not tech.enabled then
        error("Technology is not enabled: " .. tech_name)
    end

    -- Check prerequisites
    for _, prerequisite in pairs(tech.prerequisites) do
        if not prerequisite.researched then
            error("Missing prerequisite: " .. prerequisite.name)
        end
    end

    -- Check if we have the required research ingredients
    for _, ingredient in pairs(tech.research_unit_ingredients) do
        if not force.recipes[ingredient.name].enabled then
            error("Missing required science pack recipe: " .. ingredient.name)
        end
    end

    return true
end

validator_registry:register("start_research", can_research_technology)

return validator_registry