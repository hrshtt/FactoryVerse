--- Entity Inspection Module
--- Provides categorized inspection functions for different entity types
--- Based on docs/entity_inspection_properties.md
---
--- Each category function returns a structured payload matching the documented schema.
--- The main inspect_entity() function dispatches to the appropriate category inspector.

local M = {}

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

--- Get inventory contents as a simple table
--- @param entity LuaEntity
--- @param inventory_type defines.inventory
--- @return table|nil Contents as {item_name: count, ...}
local function get_inventory_contents(entity, inventory_type)
    local inv = entity.get_inventory(inventory_type)
    if not inv then
        return nil
    end
    local contents = inv.get_contents()
    if not contents or next(contents) == nil then
        return nil
    end
    return contents
end

--- Format inventory data with proper structure for inspection response
--- @param entity LuaEntity
--- @param inventory_type defines.inventory
--- @param inventory_name string Name of the inventory (e.g., "crafter_input", "fuel")
--- @return table|nil Formatted inventory data with contents array
local function format_inventory_data(entity, inventory_type, inventory_name)
    local inv = entity.get_inventory(inventory_type)
    if not inv then
        return nil
    end
    
    -- Safely get inventory size (not all inventories have bars)
    local inv_size = nil
    local success, bar = pcall(function() return inv.get_bar() end)
    if success and bar then
        inv_size = bar
    else
        -- Fallback to inventory length (works for most inventories)
        success, inv_size = pcall(function() return #inv end)
        if not success then
            -- Last resort: use a default size
            inv_size = 1
        end
    end
    
    local contents_raw = inv.get_contents()
    if not contents_raw or next(contents_raw) == nil then
        return {
            name = inventory_name,
            size = inv_size,
            is_empty = true,
            contents = {}
        }
    end
    
    -- Convert contents to array format
    local contents = {}
    local slot = 1
    for _, item in pairs(contents_raw) do
        local item_name = item.name or item[1]
        local count = item.count or item[2]
        local quality = item.quality or "normal"
        if item_name and count then
            table.insert(contents, {
                slot = slot,
                name = item_name,
                count = count,
                quality = quality
            })
            slot = slot + 1
        end
    end
    
    return {
        name = inventory_name,
        size = inv_size,
        is_empty = false,
        contents = contents
    }
end

--- Inspect burner component
--- @param burner LuaBurner
--- @return table|nil BurnerData
local function inspect_burner(burner, entity)
    if not (burner and burner.valid) then
        return nil
    end
    
    local data = {}
    
    if burner.heat then
        data.heat = burner.heat
    end
    if burner.heat_capacity then
        data.heat_capacity = burner.heat_capacity
    end
    if burner.remaining_burning_fuel then
        data.remaining_burning_fuel = burner.remaining_burning_fuel
    end
    
    local currently_burning = burner.currently_burning
    if currently_burning then
        data.currently_burning = currently_burning.name
        
        -- Calculate burning progress
        -- Note: We can't calculate progress without fuel_value, so we skip it
        -- The remaining_burning_fuel is already provided which gives relative progress info
    else
        -- If currently_burning is nil but there's remaining_burning_fuel, check fuel inventory
        if data.remaining_burning_fuel and data.remaining_burning_fuel > 0 then
            local fuel_inv = entity.get_inventory(defines.inventory.fuel)
            if fuel_inv then
                for i = 1, #fuel_inv do
                    local stack = fuel_inv[i]
                    if stack and stack.valid_for_read and stack.count > 0 then
                        data.currently_burning = stack.name
                        -- Note: We can't calculate progress without fuel_value, so we skip it
                        -- The remaining_burning_fuel is already provided which gives relative progress info
                        break
                    end
                end
            end
        end
    end
    
    -- Populate fuel_inventory (required by Python BurnerMixin)
    local fuel_inv = entity.get_inventory(defines.inventory.fuel)
    if fuel_inv then
        local fuel_contents = fuel_inv.get_contents()
        if fuel_contents and next(fuel_contents) ~= nil then
            -- Convert to array format matching format_inventory_data structure
            local contents = {}
            local slot = 1
            for item_name, count in pairs(fuel_contents) do
                table.insert(contents, {
                    slot = slot,
                    name = item_name,
                    count = count,
                    quality = "normal"  -- Default quality
                })
                slot = slot + 1
            end
            data.fuel_inventory = {
                contents = contents
            }
        else
            -- Empty fuel inventory
            data.fuel_inventory = {
                contents = {}
            }
        end
    else
        -- No fuel inventory (shouldn't happen for burner entities, but handle gracefully)
        data.fuel_inventory = {
            contents = {}
        }
    end
    
    if next(data) == nil then
        return nil
    end
    return data
end

--- Create entity reference
--- @param entity LuaEntity
--- @return table|nil EntityRef
local function make_entity_ref(entity)
    if not (entity and entity.valid) then
        return nil
    end
    return {
        name = entity.name,
        position = {x = entity.position.x, y = entity.position.y}
    }
end

--- Create bounding box reference
--- @param box BoundingBox
--- @return table|nil BoundingBox
local function make_bounding_box(box)
    if not box then
        return nil
    end
    return {
        left_top = {x = box.left_top.x, y = box.left_top.y},
        right_bottom = {x = box.right_bottom.x, y = box.right_bottom.y}
    }
end

-- ============================================================================
-- CATEGORY INSPECTORS
-- ============================================================================

--- Inspect CraftingMachine entities
--- Entities: assembling-machine, furnace, chemical-plant, oil-refinery, centrifuge, rocket-silo
--- @param entity LuaEntity
--- @return table Category-specific data
local function inspect_crafting_machine(entity)
    local data = {}
    
    -- Recipe and progress
    local recipe, quality = entity.get_recipe()
    if recipe then
        data.recipe = recipe.name
        if entity.crafting_progress then
            data.crafting_progress = entity.crafting_progress
        end
        if entity.bonus_progress then
            data.bonus_progress = entity.bonus_progress
        end
        if entity.is_crafting then
            data.is_crafting = entity.is_crafting()
        end
    end
    
    -- Inventories (type-specific)
    -- Factorio 2.0+: Use crafter_input/crafter_output for all crafting machines
    -- Structure inventories properly for Python parsing
    data.inventories = {}
    
    if entity.type == "assembling-machine" then
        local input_inv = format_inventory_data(entity, defines.inventory.crafter_input, "crafter_input")
        if input_inv then
            data.inventories.crafter_input = input_inv
        end
        local output_inv = format_inventory_data(entity, defines.inventory.crafter_output, "crafter_output")
        if output_inv then
            data.inventories.crafter_output = output_inv
        end
        local modules_inv = format_inventory_data(entity, defines.inventory.assembling_machine_modules, "crafter_modules")
        if modules_inv then
            data.inventories.crafter_modules = modules_inv
        end
    elseif entity.type == "furnace" then
        local input_inv = format_inventory_data(entity, defines.inventory.crafter_input, "crafter_input")
        if input_inv then
            data.inventories.crafter_input = input_inv
        end
        local output_inv = format_inventory_data(entity, defines.inventory.crafter_output, "crafter_output")
        if output_inv then
            data.inventories.crafter_output = output_inv
        end
        local fuel_inv = format_inventory_data(entity, defines.inventory.fuel, "fuel")
        if fuel_inv then
            data.inventories.fuel = fuel_inv
        end
    elseif entity.type == "chemical-plant" or entity.type == "oil-refinery" then
        local input_inv = format_inventory_data(entity, defines.inventory.crafter_input, "crafter_input")
        if input_inv then
            data.inventories.crafter_input = input_inv
        end
        local output_inv = format_inventory_data(entity, defines.inventory.crafter_output, "crafter_output")
        if output_inv then
            data.inventories.crafter_output = output_inv
        end
        local modules_inv = format_inventory_data(entity, defines.inventory.assembling_machine_modules, "crafter_modules")
        if modules_inv then
            data.inventories.crafter_modules = modules_inv
        end
    end
    
    -- Energy
    if entity.energy then
        data.energy = {
            current = entity.energy,
            capacity = entity.electric_buffer_size or 0
        }
    end
    
    -- Beacons
    if entity.beacons_count then
        data.beacons_count = entity.beacons_count
    end
    
    -- Furnace-specific
    if entity.type == "furnace" then
        data.burner = inspect_burner(entity.burner, entity)
        if entity.previous_recipe then
            data.previous_recipe = entity.previous_recipe.name
        end
    end
    
    -- Rocket silo-specific
    if entity.type == "rocket-silo" then
        if entity.rocket_parts then
            data.rocket_parts = entity.rocket_parts
        end
        if entity.rocket_silo_status then
            data.rocket_silo_status = entity.rocket_silo_status
        end
    end
    
    return data
end

--- Inspect MiningDrill entities
--- Entities: mining-drill
--- @param entity LuaEntity
--- @return table Category-specific data
local function inspect_mining_drill(entity)
    local data = {}
    
    -- Mining target and progress
    local target = entity.mining_target
    if target and target.valid then
        data.mining_target = {
            name = target.name,
            type = target.type,
            position = {x = target.position.x, y = target.position.y},
            amount = target.amount
        }
        if entity.mining_progress then
            data.mining_progress = entity.mining_progress
        end
        if entity.bonus_mining_progress then
            data.bonus_mining_progress = entity.bonus_mining_progress
        end
    end
    
    -- Output inventory
    local output_inv = entity.get_output_inventory()
    if output_inv then
        local contents = output_inv.get_contents()
        if contents and next(contents) ~= nil then
            data.output = contents
        end
    end
    
    -- Drop position and target
    data.drop_position = {x = entity.drop_position.x, y = entity.drop_position.y}
    local drop_target = entity.drop_target
    if drop_target and drop_target.valid then
        data.drop_target = make_entity_ref(drop_target)
    end
    
    -- Mining area
    if entity.mining_area then
        data.mining_area = make_bounding_box(entity.mining_area)
    end
    
    -- Energy (electric drills)
    if entity.energy then
        data.energy = {
            current = entity.energy,
            capacity = entity.electric_buffer_size or 0
        }
    end
    
    -- Burner (burner mining drills)
    data.burner = inspect_burner(entity.burner, entity)
    
    -- Filter mode
    if entity.mining_drill_filter_mode then
        data.mining_drill_filter_mode = entity.mining_drill_filter_mode
    end
    
    return data
end

--- Inspect Inserter entities
--- Entities: inserter, fast-inserter, long-handed-inserter, filter-inserter, stack-inserter, stack-filter-inserter, burner-inserter
--- @param entity LuaEntity
--- @return table Category-specific data
local function inspect_inserter(entity)
    local data = {}
    
    -- Held item
    local held = entity.held_stack
    if held and held.valid_for_read then
        data.held_item = {
            name = held.name,
            count = held.count
        }
        if entity.held_stack_position then
            data.held_stack_position = {
                x = entity.held_stack_position.x,
                y = entity.held_stack_position.y
            }
        end
    end
    
    -- Positions
    data.pickup_position = {x = entity.pickup_position.x, y = entity.pickup_position.y}
    data.drop_position = {x = entity.drop_position.x, y = entity.drop_position.y}
    
    -- Targets
    local pickup_target = entity.pickup_target
    if pickup_target and pickup_target.valid then
        data.pickup_target = make_entity_ref(pickup_target)
    end
    local drop_target = entity.drop_target
    if drop_target and drop_target.valid then
        data.drop_target = make_entity_ref(drop_target)
    end
    
    -- Configuration
    if entity.inserter_filter_mode then
        data.inserter_filter_mode = entity.inserter_filter_mode
    end
    if entity.filter_slot_count then
        data.filter_slot_count = entity.filter_slot_count
        
        -- Get filters
        if data.filter_slot_count > 0 then
            local filters = {}
            for i = 1, data.filter_slot_count do
                local filter = entity.get_filter(i)
                if filter then
                    filters[i] = filter
                end
            end
            if next(filters) ~= nil then
                data.filters = filters
            end
        end
    end
    if entity.inserter_stack_size_override then
        data.inserter_stack_size_override = entity.inserter_stack_size_override
    end
    if entity.inserter_target_pickup_count then
        data.inserter_target_pickup_count = entity.inserter_target_pickup_count
    end
    if entity.pickup_from_left_lane ~= nil then
        data.pickup_from_left_lane = entity.pickup_from_left_lane
    end
    if entity.pickup_from_right_lane ~= nil then
        data.pickup_from_right_lane = entity.pickup_from_right_lane
    end
    if entity.inserter_spoil_priority then
        data.inserter_spoil_priority = entity.inserter_spoil_priority
    end
    if entity.use_filters ~= nil then
        data.use_filters = entity.use_filters
    end
    
    return data
end

--- Inspect Container entities
--- Entities: container, logistic-container, cargo-wagon
--- @param entity LuaEntity
--- @return table Category-specific data
local function inspect_container(entity)
    local data = {}
    
    -- Contents
    local inv = entity.get_inventory(defines.inventory.chest)
    if not inv then
        inv = entity.get_inventory(defines.inventory.cargo_wagon)
    end
    if inv then
        local contents = inv.get_contents()
        if contents and next(contents) ~= nil then
            data.contents = contents
        end
        local bar = inv.get_bar()
        if bar then
            data.inventory_bar = bar
        end
        local size_override = entity.get_inventory_size_override(defines.inventory.chest)
        if size_override then
            data.inventory_size_override = size_override
        end
    end
    
    -- Logistic container-specific
    if entity.type == "logistic-container" then
        if entity.storage_filter then
            data.storage_filter = entity.storage_filter
        end
        if entity.filter_slot_count then
            data.filter_slot_count = entity.filter_slot_count
            
            -- Get filters
            if data.filter_slot_count > 0 then
                local filters = {}
                for i = 1, data.filter_slot_count do
                    local filter = entity.get_filter(i)
                    if filter then
                        filters[i] = filter
                    end
                end
                if next(filters) ~= nil then
                    data.filters = filters
                end
            end
        end
        if entity.request_from_buffers ~= nil then
            data.request_from_buffers = entity.request_from_buffers
        end
    end
    
    return data
end

--- Inspect TransportBelt entities
--- Entities: transport-belt, fast-transport-belt, express-transport-belt, underground-belt, splitter, lane-splitter
--- @param entity LuaEntity
--- @return table Category-specific data
local function inspect_transport_belt(entity)
    local data = {}
    
    -- Belt shape (only available on TransportBelt, not underground-belt or splitter)
    if entity.type == "transport-belt" or entity.type == "fast-transport-belt" or entity.type == "express-transport-belt" then
        local success, belt_shape = pcall(function() return entity.belt_shape end)
        if success and belt_shape ~= nil then
            data.belt_shape = belt_shape
        end
    end
    
    -- Belt neighbours (safely access - may not exist on all belt types)
    local success, belt_neighbours = pcall(function() return entity.belt_neighbours end)
    if success and belt_neighbours ~= nil then
        local neighbours = {}
        for _, neighbour in pairs(belt_neighbours) do
            if neighbour and neighbour.valid then
                table.insert(neighbours, make_entity_ref(neighbour))
            end
        end
        if next(neighbours) ~= nil then
            data.belt_neighbours = neighbours
        end
    end
    
    -- Linked belt (safely access - may not exist on all belt types)
    local success2, linked_neighbour = pcall(function() return entity.linked_belt_neighbour end)
    if success2 and linked_neighbour and linked_neighbour.valid then
        data.linked_belt_neighbour = make_entity_ref(linked_neighbour)
        local success3, linked_type = pcall(function() return entity.linked_belt_type end)
        if success3 and linked_type ~= nil then
            data.linked_belt_type = linked_type
        end
    end
    
    -- Underground-specific
    if entity.type == "underground-belt" then
        local success, belt_to_ground_type = pcall(function() return entity.belt_to_ground_type end)
        if success and belt_to_ground_type ~= nil then
            data.belt_to_ground_type = belt_to_ground_type
        end
    end
    
    -- Splitter-specific
    if entity.type == "splitter" or entity.type == "lane-splitter" then
        local success, splitter_filter = pcall(function() return entity.splitter_filter end)
        if success and splitter_filter ~= nil then
            data.splitter_filter = splitter_filter
        end
        local success2, input_priority = pcall(function() return entity.splitter_input_priority end)
        if success2 and input_priority ~= nil then
            data.splitter_input_priority = input_priority
        end
        local success3, output_priority = pcall(function() return entity.splitter_output_priority end)
        if success3 and output_priority ~= nil then
            data.splitter_output_priority = output_priority
        end
    end
    
    -- Transport lines (simplified - full implementation would need to iterate line contents)
    -- Note: TransportLine doesn't have a simple get_contents() method
    -- This would require more complex iteration which is left for future implementation
    -- if entity.get_max_transport_line_index then
    --     local max_index = entity.get_max_transport_line_index()
    --     if max_index and max_index > 0 then
    --         -- Would need to iterate through line items here
    --     end
    -- end
    
    return data
end

--- Inspect Lab entities
--- Entities: lab
--- @param entity LuaEntity
--- @return table Category-specific data
local function inspect_lab(entity)
    local data = {}
    
    -- Inventories
    data.input = get_inventory_contents(entity, defines.inventory.lab_input)
    data.modules = get_inventory_contents(entity, defines.inventory.lab_modules)
    
    -- Current research
    local force = entity.force
    if force and force.research_queue then
        local current_research = force.research_queue[1]
        if current_research then
            data.current_research = current_research.name
        end
    end
    
    -- Bonuses and effects
    if entity.productivity_bonus then
        data.productivity_bonus = entity.productivity_bonus
    end
    if entity.speed_bonus then
        data.speed_bonus = entity.speed_bonus
    end
    if entity.beacons_count then
        data.beacons_count = entity.beacons_count
    end
    if entity.effects then
        data.effects = entity.effects
    end
    
    -- Energy
    if entity.energy then
        data.energy = {
            current = entity.energy,
            capacity = entity.electric_buffer_size or 0
        }
    end
    
    return data
end

--- Inspect EnergyProducer entities
--- Entities: boiler, steam-engine, steam-turbine, solar-panel, nuclear-reactor
--- @param entity LuaEntity
--- @return table Category-specific data
local function inspect_energy_producer(entity)
    local data = {}
    local entity_type = entity.type
    
    -- Energy generation (only on Generator types: steam-engine, steam-turbine)
    -- energy_generated_last_tick: Restriction: Can only be used if this is: Generator
    if entity_type == "steam-engine" or entity_type == "steam-turbine" then
        local success, energy_generated = pcall(function() return entity.energy_generated_last_tick end)
        if success then
            -- Property exists on this entity type - include it even if nil or 0
            data.energy_generated_last_tick = energy_generated
        end
    end
    
    -- Power production (only on ElectricEnergyInterface types)
    -- power_production: Restriction: Can only be used if this is: ElectricEnergyInterface
    -- Note: solar-panel and boiler are NOT ElectricEnergyInterface, so skip this
    if entity_type == "steam-engine" or entity_type == "steam-turbine" or entity_type == "nuclear-reactor" then
        local success, power_prod = pcall(function() return entity.power_production end)
        if success then
            -- Property exists on this entity type - include it even if nil or 0
            data.power_production = power_prod
        end
    end
    
    -- Burner (boilers only)
    if entity_type == "boiler" then
        data.burner = inspect_burner(entity.burner, entity)
    end
    
    -- Temperature (reactors, heat pipes)
    if entity_type == "nuclear-reactor" then
        local success, temp = pcall(function() return entity.temperature end)
        if success and temp ~= nil then
            data.temperature = temp
        end
    end
    
    -- Heat neighbours (reactors)
    if entity_type == "nuclear-reactor" then
        local success, heat_neighbours = pcall(function() return entity.heat_neighbours end)
        if success and heat_neighbours then
            local neighbours = {}
            for _, neighbour in pairs(heat_neighbours) do
                if neighbour and neighbour.valid then
                    table.insert(neighbours, make_entity_ref(neighbour))
                end
            end
            if next(neighbours) ~= nil then
                data.heat_neighbours = neighbours
            end
        end
    end
    
    -- Neighbour bonus (reactors only)
    if entity_type == "nuclear-reactor" then
        local success, neighbour_bonus = pcall(function() return entity.neighbour_bonus end)
        if success and neighbour_bonus ~= nil then
            data.neighbour_bonus = neighbour_bonus
        end
    end
    
    -- Energy buffer (available on electric entities)
    -- solar-panel, steam-engine, steam-turbine, nuclear-reactor have energy buffers
    if entity_type == "solar-panel" or entity_type == "steam-engine" or entity_type == "steam-turbine" or entity_type == "nuclear-reactor" then
        local success, energy = pcall(function() return entity.energy end)
        if success and energy ~= nil then
            local success2, capacity = pcall(function() return entity.electric_buffer_size end)
            data.energy = {
                current = energy,
                capacity = (success2 and capacity) or 0
            }
        end
    end
    
    return data
end

--- Inspect ElectricPole entities
--- Entities: small-electric-pole, medium-electric-pole, big-electric-pole, substation
--- @param entity LuaEntity
--- @return table Category-specific data
local function inspect_electric_pole(entity)
    local data = {}
    
    -- Network connection
    if entity.electric_network_id then
        data.electric_network_id = entity.electric_network_id
    end
    data.is_connected = entity.is_connected_to_electric_network()
    
    -- Statistics
    -- Note: electric_network_statistics structure may vary
    -- We skip extracting specific fields to avoid linter errors
    -- The statistics object can be accessed directly if needed
    
    -- Energy buffer
    if entity.energy then
        data.energy = {
            current = entity.energy,
            capacity = entity.electric_buffer_size or 0
        }
    end
    
    return data
end

--- Inspect Beacon entities
--- Entities: beacon
--- @param entity LuaEntity
--- @return table Category-specific data
local function inspect_beacon(entity)
    local data = {}
    
    -- Modules
    data.modules = get_inventory_contents(entity, defines.inventory.beacon_modules)
    
    -- Effects
    if entity.effects then
        data.effects = entity.effects
    end
    
    -- Energy
    if entity.energy then
        data.energy = {
            current = entity.energy,
            capacity = entity.electric_buffer_size or 0
        }
    end
    
    -- Effect receivers
    local receivers = entity.get_beacon_effect_receivers()
    if receivers and next(receivers) ~= nil then
        local receiver_refs = {}
        for _, receiver in pairs(receivers) do
            if receiver and receiver.valid then
                table.insert(receiver_refs, make_entity_ref(receiver))
            end
        end
        if next(receiver_refs) ~= nil then
            data.get_beacon_effect_receivers = receiver_refs
        end
    end
    
    return data
end

--- Inspect Pump entities
--- Entities: pump, offshore-pump
--- @param entity LuaEntity
--- @return table Category-specific data
local function inspect_pump(entity)
    local data = {}
    
    -- Pumped last tick
    if entity.pumped_last_tick then
        data.pumped_last_tick = entity.pumped_last_tick
    end
    
    -- Rail target (pumps only)
    if entity.type == "pump" then
        local rail_target = entity.pump_rail_target
        if rail_target and rail_target.valid then
            data.pump_rail_target = make_entity_ref(rail_target)
        end
    end
    
    -- Fluidbox
    if entity.fluids_count and entity.fluids_count > 0 then
        local fluidboxes = {}
        for i = 1, entity.fluids_count do
            local fluid = entity.get_fluid(i)
            if fluid and fluid.name then
                table.insert(fluidboxes, {
                    name = fluid.name,
                    amount = fluid.amount or 0,
                    temperature = fluid.temperature or 0
                })
            end
        end
        if next(fluidboxes) ~= nil then
            data.fluidbox = fluidboxes
        end
    end
    
    -- Offshore pump-specific
    if entity.type == "offshore-pump" then
        local source_fluid = entity.get_fluid_source_fluid()
        if source_fluid then
            data.get_fluid_source_fluid = source_fluid
        end
        local source_tile = entity.get_fluid_source_tile()
        if source_tile then
            data.get_fluid_source_tile = {x = source_tile.x, y = source_tile.y}
        end
    end
    
    return data
end

--- Inspect Radar entities
--- Entities: radar
--- @param entity LuaEntity
--- @return table Category-specific data
local function inspect_radar(entity)
    local data = {}
    
    -- Scan progress
    if entity.radar_scan_progress then
        data.radar_scan_progress = entity.radar_scan_progress
    end
    
    -- Energy
    if entity.energy then
        data.energy = {
            current = entity.energy,
            capacity = entity.electric_buffer_size or 0
        }
    end
    
    return data
end

--- Inspect Accumulator entities
--- Entities: accumulator
--- @param entity LuaEntity
--- @return table Category-specific data
local function inspect_accumulator(entity)
    local data = {}
    
    -- Energy
    if entity.energy then
        data.energy = {
            current = entity.energy,
            capacity = entity.electric_buffer_size or 0
        }
    end
    
    -- Network ID
    if entity.electric_network_id then
        data.electric_network_id = entity.electric_network_id
    end
    
    return data
end

--- Inspect Pipe entities
--- Entities: pipe, pipe-to-ground, storage-tank
--- @param entity LuaEntity
--- @return table Category-specific data
local function inspect_pipe(entity)
    local data = {}

    -- Fluidbox contents
    if entity.fluidbox and #entity.fluidbox > 0 then
        local fluidboxes = {}
        for i = 1, #entity.fluidbox do
            local fluid = entity.fluidbox[i]
            if fluid then
                table.insert(fluidboxes, {
                    index = i,
                    name = fluid.name,
                    amount = fluid.amount or 0,
                    temperature = fluid.temperature or 15
                })
            end
        end
        if next(fluidboxes) ~= nil then
            data.fluidbox = fluidboxes
        end
    end

    -- Pipe-to-ground specific: linked underground neighbour
    if entity.type == "pipe-to-ground" then
        local success, neighbour = pcall(function() return entity.neighbours end)
        if success and neighbour then
            -- For pipe-to-ground, neighbours is a single entity (the paired underground)
            if neighbour.valid then
                data.underground_neighbour = make_entity_ref(neighbour)
            end
        end
    end

    -- Storage tank specific: capacity info
    if entity.type == "storage-tank" then
        -- Get fluidbox capacity
        if entity.fluidbox and #entity.fluidbox > 0 then
            local fb = entity.fluidbox
            local capacity = fb.get_capacity(1)
            if capacity then
                data.capacity = capacity
            end
        end
    end

    return data
end

--- Inspect ResourceEntity entities
--- Entities: resource (iron-ore, copper-ore, stone, coal, etc.)
--- @param entity LuaEntity
--- @return table Category-specific data
local function inspect_resource_entity(entity)
    local data = {}
    
    -- Amount
    if entity.amount then
        data.amount = entity.amount
    end
    
    -- Initial amount (infinite resources)
    if entity.initial_amount then
        data.initial_amount = entity.initial_amount
    end
    
    return data
end

-- ============================================================================
-- MAIN INSPECTION FUNCTION
-- ============================================================================

--- Main inspection function - dispatches to category-specific inspectors
--- @param entity LuaEntity Entity to inspect
--- @return table Complete inspection data with base + category-specific fields
function M.inspect_entity(entity)
    if not (entity and entity.valid) then
        error("Inspection: Entity is invalid")
    end
    
    -- Base data (always present)
    local base_data = {
        entity_name = entity.name,
        entity_type = entity.type,
        position = {x = entity.position.x, y = entity.position.y},
        direction = entity.direction,
        tick = game.tick or 0
    }
    
    -- Health (if applicable)
    if entity.health then
        base_data.health = entity.health
        if entity.max_health then
            base_data.max_health = entity.max_health
        end
    end
    
    -- Status (send back as enum, not string)
    if entity.status then
        base_data.status = entity.status  -- Keep as enum
    end
    
    -- Dispatch to category-specific inspector
    local category_data = {}
    local entity_type = entity.type
    
    if entity_type == "assembling-machine" or 
       entity_type == "furnace" or 
       entity_type == "chemical-plant" or
       entity_type == "oil-refinery" or
       entity_type == "centrifuge" or
       entity_type == "rocket-silo" then
        category_data = inspect_crafting_machine(entity)
        
    elseif entity_type == "mining-drill" then
        category_data = inspect_mining_drill(entity)
        
    elseif entity_type == "inserter" or
           entity_type == "fast-inserter" or
           entity_type == "long-handed-inserter" or
           entity_type == "filter-inserter" or
           entity_type == "stack-inserter" or
           entity_type == "stack-filter-inserter" or
           entity_type == "burner-inserter" then
        category_data = inspect_inserter(entity)
        
    elseif entity_type == "container" or
           entity_type == "logistic-container" or
           entity_type == "cargo-wagon" then
        category_data = inspect_container(entity)
        
    elseif entity_type == "transport-belt" or
           entity_type == "fast-transport-belt" or
           entity_type == "express-transport-belt" or
           entity_type == "underground-belt" or
           entity_type == "splitter" or
           entity_type == "lane-splitter" then
        category_data = inspect_transport_belt(entity)
        
    elseif entity_type == "lab" then
        category_data = inspect_lab(entity)
        
    elseif entity_type == "boiler" or
           entity_type == "steam-engine" or
           entity_type == "steam-turbine" or
           entity_type == "solar-panel" or
           entity_type == "nuclear-reactor" then
        category_data = inspect_energy_producer(entity)
        
    elseif entity_type == "small-electric-pole" or
           entity_type == "medium-electric-pole" or
           entity_type == "big-electric-pole" or
           entity_type == "substation" then
        category_data = inspect_electric_pole(entity)
        
    elseif entity_type == "beacon" then
        category_data = inspect_beacon(entity)
        
    elseif entity_type == "pump" or
           entity_type == "offshore-pump" then
        category_data = inspect_pump(entity)
        
    elseif entity_type == "radar" then
        category_data = inspect_radar(entity)
        
    elseif entity_type == "accumulator" then
        category_data = inspect_accumulator(entity)

    elseif entity_type == "pipe" or
           entity_type == "pipe-to-ground" or
           entity_type == "storage-tank" then
        category_data = inspect_pipe(entity)

    elseif entity_type == "resource" then
        category_data = inspect_resource_entity(entity)
    end
    
    -- Merge base and category data
    local result = {}
    for k, v in pairs(base_data) do
        result[k] = v
    end
    for k, v in pairs(category_data) do
        result[k] = v
    end
    
    return result
end

return M

