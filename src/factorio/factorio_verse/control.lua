-- control.lua: registers action run methods on a remote interface and hooks events

local action_registry = require("core.action.ActionRegistry")

local ok, mod = pcall(require, "actions.agent.walk.action")
if ok then
  log("Yeah even the action was loaded")
else
  log("Wait, what? The action was not loaded?")
  log(mod)
end

-- Load admin api
local admin_api = require("core.admin_api")
admin_api.load_helpers()

-- Register remote interface containing all actions' run methods
local function register_remote_interface()
  action_registry:register_remote_interface()
end

-- Hook any events exposed by actions (e.g., on_tick runners)
local function register_events()
  local events = action_registry:get_events()
  for event_id, handler in pairs(events) do
    -- Register one aggregated handler per event id
    script.on_event(event_id, handler)
  end
end

register_remote_interface()
register_events()

-- Perform registrations at different lifecycle points to be safe on reloads
script.on_init(function()
  log("hello from on_init")
end)

script.on_load(function()
  log("hello from on_load")
end)

script.on_configuration_changed(function()
  log("hello from on_configuration_changed")
end)