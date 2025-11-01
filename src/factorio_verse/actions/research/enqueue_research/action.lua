local Action = require("core.Action")
local game_state = require("core.game_state.GameState")

--- @class EnqueueResearchParams : ParamSpec
--- @field agent_id number
--- @field technology_name string
--- @field cancel_current_research boolean
local EnqueueResearchParams = Action.ParamSpec:new({
    agent_id = {
        type = "number",
        required = true
    },
    technology_name = {
        type = "string",
        required = true
    },
    cancel_current_research = {
        type = "boolean",
        required = false,
        default = false
    }
})

--- @class EnqueueResearchAction : Action
local EnqueueResearchAction = Action:new("enqueue_research", EnqueueResearchParams)

--- @param params EnqueueResearchParams
--- @return table
function EnqueueResearchAction:run(params)
    ---@type EnqueueResearchParams
    local p = self:_pre_run(game_state, params)
    local technology_name = p.technology_name
    local agent = game_state:agent():get_agent(p.agent_id)
    local force = agent.force

    if force.current_research then
        -- agent.force.research_progress()
        table.insert(storage.agent_context[params.agent_id].research_progress, {
            name = force.current_research.name,
            progress = force.research_progress
        })
    end

    -- Cancel current research if any
    if p.cancel_current_research then
        force.cancel_current_research()
    end

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
            name = ingredient.name,
            count = ingredient.amount * units_required,
        })
    end

    return self:_post_run(ingredients, p)
end

return { action = EnqueueResearchAction, params = EnqueueResearchParams }
