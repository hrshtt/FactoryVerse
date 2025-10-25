--- factorio_verse/core/WalkHelper.lua
--- Utility for handling walk_if_unreachable logic across actions

local action_registry = require("core.action.ActionRegistry")

--- @class WalkHelper
local WalkHelper = {}
WalkHelper.__index = WalkHelper

--- @class WalkIfUnreachableOptions
--- @field agent_id number
--- @field target_position {x:number,y:number}
--- @field walk_if_unreachable boolean|nil
--- @field arrive_radius number|nil
--- @field replan_on_stuck boolean|nil
--- @field max_replans number|nil
--- @field prefer_cardinal boolean|nil
--- @field reach_checker function|nil Custom function to check if target is reachable: function(control, target_pos) -> boolean

--- Create a new WalkHelper instance
--- @return WalkHelper
function WalkHelper:new()
    return setmetatable({}, self)
end

--- Get the control (character entity) for an agent
--- @param agent_id number
--- @return LuaEntity|nil
function WalkHelper:_get_control_for_agent(agent_id)
    local agent = storage.agent_characters and storage.agent_characters[agent_id] or nil
    if agent and agent.valid then return agent end
    return nil
end

--- Default reach checker using distance-based logic
--- @param control LuaEntity
--- @param target_pos {x:number,y:number}
--- @param reach_distance number|nil
--- @return boolean
function WalkHelper:_default_reach_checker(control, target_pos, reach_distance)
    if not (control and control.valid and target_pos) then return false end
    
    -- Use provided reach distance or calculate from control
    local reach = reach_distance
    if not reach then
        local proto = control.prototype
        reach = (proto and (proto.reach_resource_distance or proto.reach_distance)) or control.reach_distance or 2.5
        reach = reach + 0.1 -- small buffer
    end
    
    local dx, dy = target_pos.x - control.position.x, target_pos.y - control.position.y
    local dist = math.sqrt(dx*dx + dy*dy)
    return dist <= reach
end

--- Check if target is reachable, with optional custom reach checker
--- @param control LuaEntity
--- @param target_pos {x:number,y:number}
--- @param reach_checker function|nil
--- @param reach_distance number|nil
--- @return boolean
function WalkHelper:is_reachable(control, target_pos, reach_checker, reach_distance)
    if reach_checker then
        return reach_checker(control, target_pos)
    else
        return self:_default_reach_checker(control, target_pos, reach_distance)
    end
end

--- Start walking towards a target if unreachable
--- @param options WalkIfUnreachableOptions
--- @return boolean success True if walking was started or target is already reachable
function WalkHelper:ensure_reachable_or_walk(options)
    if not options or not options.agent_id or not options.target_position then
        return false
    end
    
    local control = self:_get_control_for_agent(options.agent_id)
    if not control then
        return false
    end
    
    -- Check if already reachable
    local reachable = self:is_reachable(control, options.target_position, options.reach_checker)
    if reachable then
        return true
    end
    
    -- If not reachable and walk_if_unreachable is enabled, start walking
    if options.walk_if_unreachable then
        return self:start_walk_to(options)
    end
    
    return false
end

--- Start a walk_to action with the given options
--- @param options WalkIfUnreachableOptions
--- @return boolean success
function WalkHelper:start_walk_to(options)
    local walk_to = action_registry:get("agent.walk_to")
    if not walk_to then
        return false
    end
    
    local walk_params = {
        agent_id = options.agent_id,
        goal = options.target_position,
        arrive_radius = options.arrive_radius or 1.2,
        replan_on_stuck = options.replan_on_stuck ~= false, -- default true
        max_replans = options.max_replans or 2,
        prefer_cardinal = options.prefer_cardinal ~= false -- default true
    }
    
    local ok, result = pcall(function()
        return walk_to:run(walk_params)
    end)
    
    return ok and result
end

--- Cancel walking for an agent
--- @param agent_id number
--- @return boolean success
function WalkHelper:cancel_walk(agent_id)
    local cancel = action_registry:get("agent.walk_cancel")
    if not cancel then
        return false
    end
    
    local ok = pcall(function()
        cancel:run({ agent_id = agent_id })
    end)
    
    return ok
end

--- Utility to add walk_if_unreachable parameter to any ParamSpec
--- @param param_spec ParamSpec
--- @return ParamSpec The same param_spec with walk_if_unreachable added
function WalkHelper:add_walk_param(param_spec)
    -- This would need to be implemented based on ParamSpec's internal structure
    -- For now, actions should manually add walk_if_unreachable to their param specs
    return param_spec
end

return WalkHelper
