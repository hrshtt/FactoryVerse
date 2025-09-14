local Snapshot = require "core.Snapshot"
local utils = require "utils"

-- Module-level constants for better maintainability
-- Enable debug metadata generation (set to true for debugging)
-- When enabled, generates comprehensive entity property mapping for debugging
local ENABLE_DEBUG_METADATA = false

-- All entity types that should be processed by the snapshot system
local ALLOWED_ENTITY_TYPES = {
    "assembling-machine", "furnace", "mining-drill", "inserter", "lab", "roboport", "beacon",
    "electric-pole", "radar", "pipe", "pipe-to-ground", "storage-tank", "offshore-pump",
    "chemical-plant", "oil-refinery", "boiler", "generator", "pump", "pumpjack", "rocket-silo",
    "container", "logistic-container", "arithmetic-combinator", "decider-combinator",
    "constant-combinator", "lamp", "reactor", "heat-pipe", "accumulator",
    "electric-energy-interface", "programmable-speaker", "train-stop", "rail-signal",
    "rail-chain-signal", "locomotive", "cargo-wagon", "fluid-wagon",
    "transport-belt", "underground-belt", "splitter", "loader", "loader-1x1", "linked-belt"
}

-- Lookup table for efficient belt type detection
local BELT_TYPES = {
    ["transport-belt"] = true,
    ["underground-belt"] = true,
    ["splitter"] = true,
    ["loader"] = true,
    ["loader-1x1"] = true,
    ["linked-belt"] = true
}

---@class EntitiesSnapshot : Snapshot
local EntitiesSnapshot = Snapshot:new()
EntitiesSnapshot.__index = EntitiesSnapshot

---@return EntitiesSnapshot
function EntitiesSnapshot:new()
    ---@class EntitiesSnapshot : Snapshot
    ---@field _cache table
    local instance = Snapshot:new()
    -- Per-run caches to avoid repeated prototype/method work
    instance._cache = {
        inv = {},   -- [entity_name] -> { {name, id}, ... } inventory indices that exist
        fluid = {}, -- [entity_name] -> { [index] = capacity }
        belt = {},  -- [entity_name] -> max transport line index
    }
    setmetatable(instance, self)
    ---@cast instance EntitiesSnapshot
    return instance
end

-- COMPONENT DEFINITIONS: Schema-driven with declarative flattening configuration
local COMPONENTS = {
    entity = {
        name = "entities",
        flatten_config = {
            position = "coordinates",      -- position -> position_x, position_y
            chunk = "coordinates",         -- chunk -> chunk_x, chunk_y
            bounding_box = "bounds",       -- bounding_box -> bounding_box_min_x, etc.
            selection_box = "bounds",      -- selection_box -> selection_box_min_x, etc.
            train = "train_fields",        -- train -> train_id, train_state
            -- Keep complex fields as JSON
            inventories = false,           -- Keep as JSON
            fluids = false,               -- Keep as JSON
        },
        extract = function(row)
            -- Always present - base entity data (filtered in flatten)
            return {
                unit_number = row.unit_number,
                name = row.name,
                type = row.type,
                position = row.position,
                direction = row.direction,
                direction_name = row.direction_name,
                orientation = row.orientation,
                orientation_name = row.orientation_name,
                chunk = row.chunk,
                health = row.health,
                status = row.status,
                status_name = row.status_name,
                bounding_box = row.bounding_box,
                selection_box = row.selection_box,
                train = row.train,
                electric_network_id = row.electric_network_id
            }
        end,
        should_include = function(row) return true end -- Always include base entity
    },


    crafting = {
        name = "entities_crafting",
        flatten_config = {
            chunk = "coordinates",  -- chunk -> chunk_x, chunk_y
        },
        extract = function(row)
            return {
                unit_number = row.unit_number,
                recipe = row.recipe,
                crafting_progress = row.crafting_progress,
                chunk = row.chunk
            }
        end,
        should_include = function(row)
            return row.recipe ~= nil or row.crafting_progress ~= nil
        end
    },

    burner = {
        name = "entities_burner",
        flatten_config = {
            burner = "burner_fields",  -- burner -> remaining_burning_fuel, currently_burning, inventories
            chunk = "coordinates",     -- chunk -> chunk_x, chunk_y
        },
        extract = function(row)
            return {
                unit_number = row.unit_number,
                burner = row.burner,
                chunk = row.chunk
            }
        end,
        should_include = function(row)
            return row.burner ~= nil
        end
    },

    inventory = {
        name = "entities_inventory",
        flatten_config = {
            chunk = "coordinates",  -- chunk -> chunk_x, chunk_y
            inventories = false,    -- Keep as JSON
        },
        extract = function(row)
            -- Filter out empty mining_drill_modules
            local filtered_inventories = {}
            if row.inventories then
                for inv_name, inv_data in pairs(row.inventories) do
                    if inv_name ~= "mining_drill_modules" or (inv_data and next(inv_data) ~= nil) then
                        filtered_inventories[inv_name] = inv_data
                    end
                end
            end
            return {
                unit_number = row.unit_number,
                inventories = next(filtered_inventories) and filtered_inventories or nil,
                chunk = row.chunk
            }
        end,
        should_include = function(row)
            if not row.inventories then return false end
            -- Check if there are non-empty inventories after filtering
            for inv_name, inv_data in pairs(row.inventories) do
                if inv_name ~= "mining_drill_modules" or (inv_data and next(inv_data) ~= nil) then
                    return true
                end
            end
            return false
        end
    },

    fluids = {
        name = "entities_fluids",
        flatten_config = {
            chunk = "coordinates",  -- chunk -> chunk_x, chunk_y
            fluids = false,         -- Keep as JSON
        },
        extract = function(row)
            return {
                unit_number = row.unit_number,
                fluids = row.fluids,
                chunk = row.chunk
            }
        end,
        should_include = function(row)
            return row.fluids ~= nil
        end
    },

    inserter = {
        name = "entities_inserter",
        flatten_config = {
            inserter = "inserter_positions",  -- inserter -> pickup_position_x, drop_position_x, etc.
            chunk = "coordinates",            -- chunk -> chunk_x, chunk_y
        },
        extract = function(row)
            return {
                unit_number = row.unit_number,
                inserter = row.inserter,
                chunk = row.chunk
            }
        end,
        should_include = function(row)
            return row.inserter ~= nil
        end
    },

    belts = {
        name = "entities_belts",
        flatten_config = {
            position = "coordinates",  -- position -> position_x, position_y
            chunk = "coordinates",     -- chunk -> chunk_x, chunk_y
            item_lines = false,        -- Keep as JSON
            belt_neighbours = false,   -- Keep as JSON
        },
        extract = function(row)
            return {
                unit_number = row.unit_number,
                name = row.name,
                type = row.type,
                position = row.position,
                direction = row.direction,
                direction_name = row.direction_name,
                item_lines = row.item_lines,
                belt_neighbours = row.belt_neighbours,
                belt_to_ground_type = row.belt_to_ground_type,
                underground_neighbour_unit = row.underground_neighbour_unit,
                chunk = row.chunk
            }
        end,
        should_include = function(row)
            return BELT_TYPES[row.type] == true
        end
    }
}

--- Main snapshot method - processes entities once and outputs all components
function EntitiesSnapshot:take()
    log("Taking entities snapshot")

    local surface = self.game_state:get_surface()

    if not surface then
        return self:_create_empty_output()
    end

    -- Process all entities once using parent class chunk processing
    local all_entity_data = self:process_charted_chunks(function(chunk)
        return self:_extract_entities_from_chunk(surface, chunk)
    end)
    
    -- Flatten the nested array structure
    local flattened_entities = {}
    for _, chunk_entities in ipairs(all_entity_data) do
        for _, entity in ipairs(chunk_entities) do
            table.insert(flattened_entities, entity)
        end
    end

    -- Generate debug metadata only if enabled
    local debug_metadata = nil
    if ENABLE_DEBUG_METADATA then
        debug_metadata = self:_generate_debug_metadata(flattened_entities)
        self._debug_metadata = debug_metadata
    end

    -- Generate component data and emit CSVs using schema-driven approach
    local component_counts = {}
    for comp_key, comp_def in pairs(COMPONENTS) do
        local result = self:process_component_schema_driven(flattened_entities, comp_def)
        component_counts[comp_key .. "_rows"] = #result.data
        self:_emit_component_csv_schema_driven(result, comp_def)
    end

    -- Add debug metadata to component counts only if enabled
    if ENABLE_DEBUG_METADATA then
        component_counts.debug = debug_metadata
    end

    local output = self:create_output("snapshot.entities", "v3", component_counts)
    self:print_summary(output, function(out)
        return {
            surface = out.surface,
            tick = out.timestamp,
            entities = out.data
        }
    end)

    return output
end

-- PRIVATE METHODS --------------------------------------------------------

--- Generate comprehensive debug metadata for entity mapping
function EntitiesSnapshot:_generate_debug_metadata(all_entity_data)
    local debug = {
        entities = {},      -- {entity_name: {properties: set}}
        entity_types = {}   -- {entity_type: {properties: set}}
    }

    -- Analyze properties for each entity name and type
    for _, entity_data in ipairs(all_entity_data) do
        local entity_name = entity_data.name
        local entity_type = entity_data.type

        -- Get all non-nil properties for this entity
        local properties = {}
        for key, value in pairs(entity_data) do
            if value ~= nil then
                properties[key] = true
            end
        end

        -- Track properties by entity name
        if entity_name then
            if not debug.entities[entity_name] then
                debug.entities[entity_name] = {}
            end
            for prop, _ in pairs(properties) do
                debug.entities[entity_name][prop] = true
            end
        end

        -- Track properties by entity type
        if entity_type then
            if not debug.entity_types[entity_type] then
                debug.entity_types[entity_type] = {}
            end
            for prop, _ in pairs(properties) do
                debug.entity_types[entity_type][prop] = true
            end
        end
    end

    -- Convert sets to sorted arrays for better readability
    local entities_with_props = {}
    for name, props in pairs(debug.entities) do
        local prop_list = {}
        for prop, _ in pairs(props) do
            table.insert(prop_list, prop)
        end
        table.sort(prop_list)
        table.insert(entities_with_props, {name = name, properties = prop_list})
    end
    table.sort(entities_with_props, function(a, b) return a.name < b.name end)

    local types_with_props = {}
    for type_name, props in pairs(debug.entity_types) do
        local prop_list = {}
        for prop, _ in pairs(props) do
            table.insert(prop_list, prop)
        end
        table.sort(prop_list)
        table.insert(types_with_props, {type = type_name, properties = prop_list})
    end
    table.sort(types_with_props, function(a, b) return a.type < b.type end)

    return {
        entities = entities_with_props,
        entity_types = types_with_props,
        total_entities = #all_entity_data,
        unique_entity_names = #entities_with_props,
        unique_entity_types = #types_with_props
    }
end

--- Create empty output structure
function EntitiesSnapshot:_create_empty_output()
    local empty_data = {}
    for comp_key, _ in pairs(COMPONENTS) do
        empty_data[comp_key .. "_rows"] = {}
    end
    
    -- Add debug metadata only if enabled
    if ENABLE_DEBUG_METADATA then
        empty_data.debug = {
            entities = {},
            entity_types = {},
            total_entities = 0,
            unique_entity_names = 0,
            unique_entity_types = 0
        }
        self._debug_metadata = empty_data.debug
    end
    
    return self:create_output("snapshot.entities", "v3", empty_data)
end

--- Extract entity data from a single chunk
--- @param surface table - game surface
--- @param chunk table - chunk with x, y, area properties
--- @return table - array of serialized entities from this chunk
function EntitiesSnapshot:_extract_entities_from_chunk(surface, chunk)
    local chunk_entities = {}
    local filter = { area = chunk.area, force = "player", type = ALLOWED_ENTITY_TYPES }
    local entities = surface.find_entities_filtered(filter)

    if #entities ~= 0 then
        local chunk_field = { x = chunk.x, y = chunk.y }
        for i = 1, #entities do
            local e = entities[i]
            if e and e.valid and not self:_should_skip_entity(e) then
                local serialized = nil
                -- Use belt serialization for belt types, regular serialization for others
                if BELT_TYPES[e.type] then
                    serialized = self:_serialize_belt(e)
                else
                    serialized = self:_serialize_entity(e)
                end

                if serialized then
                    serialized.chunk = chunk_field
                    table.insert(chunk_entities, serialized)
                end
            end
        end
    end

    return chunk_entities
end

--- Check if entity should be skipped
function EntitiesSnapshot:_should_skip_entity(e)
    if e.type == "simple-entity" then
        local n = e.name
        return n == "rock-huge" or n == "rock-big" or n == "sand-rock-big"
    end
    return false
end


--- Emit CSV for a specific component using schema-driven approach
function EntitiesSnapshot:_emit_component_csv_schema_driven(result, component_def)
    local schema_version = component_def.name == "entities_belts" and "snapshot.belts.v3" or "snapshot.entities.v3"
    
    -- Create custom flatten function that includes debug metadata
    local flatten_fn = function(row)
        local flattened = row  -- Data is already flattened by schema-driven processing
        
        -- Add debug metadata if enabled and available (only for the main entities component)
        if ENABLE_DEBUG_METADATA and component_def.name == "entities" and self._debug_metadata then
            flattened._debug_metadata = self._debug_metadata
        end
        
        return flattened
    end
    
    self:emit_csv_by_chunks(result.data, component_def.name, result.headers, schema_version, flatten_fn)
end


--- Serialize belt entity (extracted from original belt logic)
function EntitiesSnapshot:_serialize_belt(e)
    local item_lines = {}
    local max_index = 0

    -- Get max transport line index (with caching)
    local cache = self._cache and self._cache.belt or nil
    if cache and cache[e.name] ~= nil then
        max_index = cache[e.name]
    else
        local v = (e.get_max_transport_line_index and e.get_max_transport_line_index()) or 0
        max_index = (type(v) == "number" and v > 0) and v or 0
        if cache then cache[e.name] = max_index end
    end

    -- Extract transport line contents
    for li = 1, max_index do
        local tl = e.get_transport_line and e.get_transport_line(li) or nil
        if tl then
            local contents = tl.get_contents and tl.get_contents() or nil
            if contents and next(contents) ~= nil then
                table.insert(item_lines, { index = li, items = contents })
            end
        end
    end

    -- Belt neighbours and underground pairing
    local inputs_ids, outputs_ids = {}, {}
    local bn = e.belt_neighbours
    if bn then
        if bn.inputs then
            for _, n in ipairs(bn.inputs) do
                if n and n.valid and n.unit_number then
                    table.insert(inputs_ids, n.unit_number)
                end
            end
        end
        if bn.outputs then
            for _, n in ipairs(bn.outputs) do
                if n and n.valid and n.unit_number then
                    table.insert(outputs_ids, n.unit_number)
                end
            end
        end
    end

    local underground_other = nil
    local belt_to_ground_type = nil
    if e.type == "underground-belt" then
        belt_to_ground_type = e.belt_to_ground_type
        local un = e.neighbours
        if un and un.valid and un.unit_number then
            underground_other = un.unit_number
        end
    end

    return {
        unit_number = e.unit_number,
        name = e.name,
        type = e.type,
        position = e.position,
        direction = e.direction,
        direction_name = utils.direction_to_name(e.direction and tonumber(tostring(e.direction)) or nil),
        item_lines = item_lines,
        belt_neighbours = (#inputs_ids > 0 or #outputs_ids > 0) and { inputs = inputs_ids, outputs = outputs_ids } or nil,
        belt_to_ground_type = belt_to_ground_type,
        underground_neighbour_unit = underground_other
    }
end

function EntitiesSnapshot:_serialize_entity(e)
    if not (e and e.valid) then return nil end

    local proto       = e.prototype
    local cache_inv   = self._cache and self._cache.inv or nil
    local cache_fluid = self._cache and self._cache.fluid or nil
    local ename       = e.name

    local out         = {
        unit_number = e.unit_number,
        name = e.name,
        type = e.type,
        force = (e.force and e.force.name) or nil,
        position = e.position,
        direction = e.direction,
        direction_name = utils.direction_to_name(e.direction and tonumber(tostring(e.direction)) or nil),
        orientation = e.orientation,
        orientation_name = utils.orientation_to_name(e.orientation),
    }

    -- Health & status
    if e.health ~= nil then out.health = e.health end
    if e.status ~= nil then
        out.status = e.status
        out.status_name = utils.entity_status_to_name(e.status)
    end

    -- Electric network id
    local ok_enid, enid = pcall(function() return e.electric_network_id end)
    if ok_enid and enid then out.electric_network_id = enid end

    -- Crafting / recipe (gate to crafting machines only)
    do
        -- Treat only true crafting machines as crafters
        local is_crafter = (e.type == "assembling-machine" or e.type == "furnace")
        if not is_crafter and proto and proto.crafting_categories then
            is_crafter = true
        end

        if is_crafter then
            -- Per docs, LuaEntity::get_recipe() is the supported way to read the current recipe
            local r = e.get_recipe()
            if r then out.recipe = r.name end
            -- crafting_progress is valid on crafting machines
            if e.crafting_progress ~= nil then
                out.crafting_progress = e.crafting_progress
            end
        end
    end

    -- Burner info (gate by prototype)
    do
        if proto and proto.burner_prototype then
            local burner = e.burner
            if burner then
                local b = {}
                if burner.remaining_burning_fuel ~= nil then b.remaining_burning_fuel = burner.remaining_burning_fuel end
                if burner.currently_burning and burner.currently_burning.name then
                    b.currently_burning = burner.currently_burning.name
                end
                local inv = {}
                local fi = burner.inventory
                if fi and fi.valid and not fi.is_empty() then inv.fuel = fi.get_contents() end
                local bri = burner.burnt_result_inventory
                if bri and bri.valid and not bri.is_empty() then inv.burnt = bri.get_contents() end
                if next(inv) ~= nil then b.inventories = inv end
                if next(b) ~= nil then out.burner = b end
            end
        end
    end

    -- Inventories (enumerate 1..get_max_inventory_index; cache per entity name)
    do
        local inventories = {}
        local inv_defs = cache_inv and cache_inv[ename]
        if inv_defs == nil then
            inv_defs = {}
            local max_idx = (e.get_max_inventory_index and e.get_max_inventory_index()) or 0
            if max_idx and max_idx > 0 then
                for idx = 1, max_idx do
                    local inv = e.get_inventory and e.get_inventory(idx) or nil
                    if inv and inv.valid then
                        local inv_name = (e.get_inventory_name and e.get_inventory_name(idx)) or tostring(idx)
                        inv_defs[#inv_defs + 1] = { inv_name, idx }
                    end
                end
            end
            if cache_inv then cache_inv[ename] = inv_defs end
        end
        for i = 1, #inv_defs do
            local inv_name, idx = inv_defs[i][1], inv_defs[i][2]
            local inv = e.get_inventory and e.get_inventory(idx) or nil
            if inv and inv.valid then
                if inv.is_empty and inv.is_empty() then
                    inventories[inv_name] = {}
                else
                    local contents = inv.get_contents and inv.get_contents() or nil
                    inventories[inv_name] = contents or {}
                end
            end
        end
        if next(inventories) ~= nil then out.inventories = inventories end
    end

    -- Fluidboxes (use prototype volumes when available; cache per entity name)
    do
        local fb = e.fluidbox
        if fb then
            local fluids = {}
            local len = #fb
            local caps = cache_fluid and cache_fluid[ename]
            if caps == nil then
                caps = {}
                if proto and proto.fluidbox_prototypes then
                    for idx, fbp in pairs(proto.fluidbox_prototypes) do
                        if fbp and fbp.volume then caps[idx] = fbp.volume end
                    end
                end
                if cache_fluid then cache_fluid[ename] = caps end
            end
            for i = 1, len do
                local f = fb[i]
                if f then
                    local cap = caps[i]
                    if cap == nil and fb.get_capacity then
                        cap = fb.get_capacity(i)
                    end
                    fluids[#fluids + 1] = {
                        index = i,
                        name = f.name,
                        amount = f.amount,
                        temperature = f.temperature,
                        capacity = cap,
                    }
                end
            end
            if #fluids > 0 then out.fluids = fluids end
        end
    end

    -- Train info (for rolling stock)
    do
        if e.train then
            out.train = { id = e.train.id, state = e.train.state }
        end
    end

    -- Selection & bounding boxes (runtime first; fall back to prototype)
    do
        local bb = e.bounding_box
        if bb and bb.left_top and bb.right_bottom then
            out.bounding_box = {
                min_x = bb.left_top.x,
                min_y = bb.left_top.y,
                max_x = bb.right_bottom.x,
                max_y = bb.right_bottom.y
            }
        end
        local sb = e.selection_box
        if sb and sb.left_top and sb.right_bottom then
            out.selection_box = {
                min_x = sb.left_top.x,
                min_y = sb.left_top.y,
                max_x = sb.right_bottom.x,
                max_y = sb.right_bottom.y
            }
        elseif proto and proto.selection_box then
            local psb = proto.selection_box
            if psb.left_top and psb.right_bottom then
                out.selection_box = {
                    min_x = psb.left_top.x or psb.left_top[1],
                    min_y = psb.left_top.y or psb.left_top[2],
                    max_x = psb.right_bottom.x or psb.right_bottom[1],
                    max_y = psb.right_bottom.y or psb.right_bottom[2]
                }
            elseif type(psb) == "table" and psb[1] and psb[2] then
                out.selection_box = {
                    min_x = psb[1][1],
                    min_y = psb[1][2],
                    max_x = psb[2][1],
                    max_y = psb[2][2]
                }
            end
        end
    end

    -- Inserter IO (pickup/drop positions and resolved targets)
    do
        if e.type == "inserter" then
            local ins = {
                pickup_position = e.pickup_position,
                drop_position   = e.drop_position,
            }
            local pt = e.pickup_target
            if pt and pt.valid and pt.unit_number then ins.pickup_target_unit = pt.unit_number end
            local dt = e.drop_target
            if dt and dt.valid and dt.unit_number then ins.drop_target_unit = dt.unit_number end
            if next(ins) ~= nil then out.inserter = ins end
        end
    end

    return out
end

return EntitiesSnapshot
