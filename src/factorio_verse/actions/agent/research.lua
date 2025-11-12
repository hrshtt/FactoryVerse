-- TODO: Migrate to AsyncAction pattern to support cancellation/dequeue
-- Research is a long-running operation that should be cancellable
-- When migrated, this will support async tracking and cancellation via dequeue_research
local Action = require("types.Action")
local GameContext = require("types.GameContext")

--- @class EnqueueResearchParams : ParamSpec
--- @field agent_id number
--- @field technology_name string Technology name (validated against agent's force)
--- @field cancel_current_research boolean
local EnqueueResearchParams = Action.ParamSpec:new({
    agent_id = {
        type = "number",
        required = true
    },
    technology_name = {
        type = "technology_name",
        required = true
    },
    cancel_current_research = {
        type = "boolean",
        required = false,
        default = false
    }
})

--- @class EnqueueResearchAction : Action
local EnqueueResearchAction = Action:new("research", EnqueueResearchParams)

--- @class EnqueueResearchContext
--- @field agent LuaEntity Agent character entity
--- @field technology LuaTechnology Technology object (force-specific)
--- @field technology_name string Technology name
--- @field cancel_current_research boolean Whether to cancel current research
--- @field params EnqueueResearchParams ParamSpec instance for _post_run

--- Override _pre_run to build context using GameContext
--- @param params EnqueueResearchParams|table|string
--- @return EnqueueResearchContext
function EnqueueResearchAction:_pre_run(params)
    -- Call parent to get validated ParamSpec
    local p = Action._pre_run(self, params)
    local params_table = p:get_values()
    
    -- Build context using GameContext
    local agent = GameContext.resolve_agent(params_table, self.game_state)
    
    -- Resolve technology (force-specific)
    local tech_params = { tech_name = params_table.technology_name }
    local technology = GameContext.resolve_technology(tech_params, agent)
    
    -- Return context for run()
    return {
        agent = agent,
        technology = technology,
        technology_name = params_table.technology_name,
        cancel_current_research = params_table.cancel_current_research or false,
        params = p
    }
end

--- @param params EnqueueResearchParams|table|string
--- @return table
function EnqueueResearchAction:run(params)
    --- @type EnqueueResearchContext
    local context = self:_pre_run(params)
    
    local force = context.agent.force

    local params_table = context.params:get_values()
    if force.current_research then
        -- agent.force.research_progress()
        table.insert(storage.agent_context[params_table.agent_id].research_progress, {
            name = force.current_research.name,
            progress = force.research_progress
        })
    end

    -- Cancel current research if any
    if context.cancel_current_research then
        force.cancel_current_research()
    end

    -- Set new research using add_research
    local success = force.add_research(context.technology_name)
    if not success then
        error(string.format("\"Failed to start research for %s\"", context.technology_name))
    end

    -- Collect and return the research ingredients
    local ingredients = {}
    local tech = context.technology

    -- Get the count of research units needed
    local units_required = tech.research_unit_count

    -- Collect all ingredients and their counts
    for _, ingredient in pairs(tech.research_unit_ingredients) do
        table.insert(ingredients, {
            name = ingredient.name,
            count = ingredient.amount * units_required,
        })
    end

    return self:_post_run(ingredients, context.params)
end

return { action = EnqueueResearchAction, params = EnqueueResearchParams }
