# WalkHelper Usage Guide

The `WalkHelper` utility provides a clean, reusable way to handle `walk_if_unreachable` functionality across all actions.

## Features

- **Consistent reach checking** with customizable reach distance
- **Automatic walking** when targets are unreachable
- **Clean integration** with existing actions
- **Configurable parameters** for different use cases
- **Built into Action base class** for easy access

## Basic Usage

### 1. Add walk_if_unreachable to your ParamSpec

```lua
local MyActionParams = ParamSpec:new({
    agent_id = { type = "number", required = true },
    target_position = { type = "table", required = true },
    walk_if_unreachable = { type = "boolean", required = false, default = false }
})
```

### 2. Use WalkHelper in your action

```lua
function MyAction:run(params)
    local p = self:_pre_run(game_state, params)
    
    -- Check if target is reachable and walk if needed
    if p.walk_if_unreachable then
        local reachable = self.walk_helper:ensure_reachable_or_walk({
            agent_id = p.agent_id,
            target_position = p.target_position,
            walk_if_unreachable = true,
            arrive_radius = 1.0 -- optional, defaults to 1.2
        })
        
        if not reachable then
            error("Agent is walking to target. Try again when closer.")
        end
    end
    
    -- Your action logic here...
    return self:_post_run(result, p)
end
```

## Advanced Usage

### Custom Reach Checker

```lua
-- Custom reach checker for specific entity types
local function custom_reach_checker(control, target_pos)
    -- Your custom logic here
    local distance = math.sqrt((control.position.x - target_pos.x)^2 + (control.position.y - target_pos.y)^2)
    return distance <= 3.0 -- Custom reach distance
end

local reachable = self.walk_helper:is_reachable(control, target_pos, custom_reach_checker)
```

### Manual Walking Control

```lua
-- Start walking manually
local walk_success = self.walk_helper:start_walk_to({
    agent_id = agent_id,
    target_position = {x = 10, y = 20},
    arrive_radius = 0.5,
    prefer_cardinal = true,
    max_replans = 3
})

-- Cancel walking
self.walk_helper:cancel_walk(agent_id)
```

## Configuration Options

### WalkIfUnreachableOptions

- `agent_id` (required): The agent to move
- `target_position` (required): Target position {x, y}
- `walk_if_unreachable` (optional): Whether to start walking if unreachable
- `arrive_radius` (optional): How close to get to target (default: 1.2)
- `replan_on_stuck` (optional): Whether to replan path if stuck (default: true)
- `max_replans` (optional): Maximum replanning attempts (default: 2)
- `prefer_cardinal` (optional): Prefer cardinal directions (default: true)
- `reach_checker` (optional): Custom function to check reachability

## Examples from Existing Actions

### Place Entity Action
```lua
-- Handle walk_if_unreachable logic
if p.walk_if_unreachable then
    local placement_reachable = self.walk_helper:is_reachable(agent, p.position)
    if not placement_reachable then
        local walk_success = self.walk_helper:start_walk_to({
            agent_id = p.agent_id,
            target_position = p.position,
            walk_if_unreachable = true,
            arrive_radius = 1.0,
            prefer_cardinal = true
        })
        if walk_success then
            error("Agent is walking to position. Try placing again when closer.")
        end
    end
end
```

### Mine Resource Action (Ongoing Walking)
```lua
-- For actions that need ongoing walking behavior
local function _ensure_walking_towards(job)
    if job.walking_started then return end
    local ok = walk_helper:start_walk_to({
        agent_id = job.agent_id,
        target_position = job.target,
        walk_if_unreachable = true,
        arrive_radius = 1.2,
        replan_on_stuck = true,
        max_replans = 2,
        prefer_cardinal = true
    })
    if ok then
        job.walking_started = true
    end
end
```

## Benefits

1. **DRY**: No more duplicated walking logic across actions
2. **Consistent**: Same walking behavior everywhere
3. **Maintainable**: Changes to walking logic happen in one place
4. **Flexible**: Configurable for different use cases
5. **Clean**: Actions focus on their core logic, not walking details
