-- control.lua: registers action run methods on a remote interface and hooks events

local action_registry = require("factorio_verse.core.action.ActionRegistry")

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

-- Perform registrations at different lifecycle points to be safe on reloads
script.on_init(function()
  register_remote_interface()
  register_events()
end)

script.on_load(function()
  register_remote_interface()
  register_events()
end)

script.on_configuration_changed(function()
  register_remote_interface()
  register_events()
end)