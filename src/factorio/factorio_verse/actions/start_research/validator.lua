local ValidatorRegistry = require("factorio_verse.core.action.ValidatorRegistry")

local validator_registry = ValidatorRegistry:new()

local function can_research_technology(force, tech_name)
    local tech = force.technologies[tech_name]

    if not tech then
        return false, "technology doesn't exist"
    end

    if tech.researched then
        return false, "technology is already researched"
    end

    if not tech.enabled then
        return false, "technology is not enabled"
    end

    -- Check prerequisites
    for _, prerequisite in pairs(tech.prerequisites) do
        if not prerequisite.researched then
            return false, "missing prerequisite - " .. prerequisite.name
        end
    end

    -- Check if we have the required research ingredients
    for _, ingredient in pairs(tech.research_unit_ingredients) do
        if not force.recipes[ingredient.name].enabled then
            return false, "missing required science pack recipe - " .. ingredient.name
        end
    end

    return true, tech
end

validator_registry:register("start_research", can_research_technology)