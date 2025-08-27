local Action = require("factorio_verse.core.action.Action")
local ParamSpec = require("factorio_verse.core.action.ParamSpec")
local validator_registry = require("factorio_verse.actions.start_research.validator")

local validators = validator_registry:get_validations("start_research")
local game_state = require("factorio_verse.core.game_state.GameState")

--- @class StartResearchParams : ParamSpec
--- @field agent_id number
--- @field technology_name string
local StartResearchParams = ParamSpec:new({
    agent_id = {
        type = "number",
        required = true
    },
    technology_name = {
        type = "string",
        required = true
    }
})

--- @class StartResearchAction : Action
local StartResearchAction = Action:new("start_research", StartResearchParams, validators)

--- @param params StartResearchParams
--- @return boolean
function StartResearchAction:run(params)
    local technology_name = params.technology_name
    local agent = game_state.agent:get_agent(params.agent_id)
    local force = agent.force

    if force.current_research then
        force.set_saved_technology_progress(force.current_research.name, force.research_progress)
    end
    -- Cancel current research if any
    --force.cancel_current_research()

    -- Set new research using add_research
    local success = force.add_research(technology_name)
    if not success then
        error(string.format("\"Failed to start research for %s\"", technology_name))
    end

    -- Collect and return the research ingredients
    local ingredients = {}
    local tech = force.technologies[technology_name]

    -- Get the count of research units needed
    local units_required = tech.research_unit_count

    -- Collect all ingredients and their counts
    for _, ingredient in pairs(tech.research_unit_ingredients) do
        table.insert(ingredients, {
            name = "\""..ingredient.name.."\"",
            count = ingredient.amount * units_required,
            type = ingredient.type
        })
    end

    return ingredients
end