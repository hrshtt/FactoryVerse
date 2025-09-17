local Snapshot = require "core.Snapshot"

local utils = require "utils"

-- Normalize Factorio item identifiers to a plain string name.
-- Handles: string, LuaItemPrototype, and 2.0 ItemIDAndQualityIDPair (read form).
local function _item_id_to_name(obj)
    if obj == nil then return nil end
    if type(obj) == "string" then return obj end
    local t = type(obj)
    if t == "userdata" or t == "table" then
        -- Direct prototype
        if obj.object_name == "LuaItemPrototype" and obj.name then
            return obj.name
        end
        -- ItemIDAndQualityIDPair: .name may be string or LuaItemPrototype
        local n = rawget(obj, "name")
        if type(n) == "string" then
            return n
        end
        if (type(n) == "userdata" or type(n) == "table") and n.object_name == "LuaItemPrototype" and n.name then
            return n.name
        end
    end
    return nil
end

--- EntitiesSnapshot: Dumps raw entities and associated data chunk-wise
--- Includes inventories, fluidboxes, energy/burner info, and basic metadata
--- @class EntitiesSnapshot : Snapshot
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

--- Dump all entities chunk-wise with rich per-entity data
--- Dump all entities as flat rows (no chunk grouping). Each row includes its chunk coords
--- Dump all entities as componentized flat rows (no chunk grouping)
function EntitiesSnapshot:take()
    log("Taking entities snapshot")

    local charted_chunks = self.game_state:get_charted_chunks()

    -- Engine-side allowlist to avoid creating wrappers for belts/naturals
    local allowed_types = {
        "assembling-machine", "furnace", "mining-drill", "inserter", "lab", "roboport", "beacon",
        "electric-pole", "radar", "pipe", "pipe-to-ground", "storage-tank", "offshore-pump",
        "chemical-plant", "oil-refinery", "boiler", "generator", "pump", "pumpjack", "rocket-silo",
        "container", "logistic-container", "arithmetic-combinator", "decider-combinator",
        "constant-combinator", "lamp", "reactor", "heat-pipe", "accumulator",
        "electric-energy-interface", "programmable-speaker", "train-stop", "rail-signal",
        "rail-chain-signal", "locomotive", "cargo-wagon", "fluid-wagon"
    }

    -- Componentized outputs
    local entity_rows = {}
    local electric_rows = {}
    local crafting_rows = {}
    local burner_rows = {}
    local inventory_rows = {}
    local fluids_rows = {}
    local inserter_rows = {}

    local surface = self.game_state:get_surface()
    if not surface then
        local empty = self:create_output("snapshot.entities", "v3", {
            entity_rows = {},
            electric_rows = {},
            crafting_rows = {},
            burner_rows = {},
            inventory_rows = {},
            fluids_rows = {},
            inserter_rows = {},
        })
        return empty
    end

    for _, chunk in ipairs(charted_chunks) do
        -- Use engine filter for force and allowed types only
        local filter = { area = chunk.area, force = "player", type = allowed_types }
        local entities = surface.find_entities_filtered(filter)
        if #entities ~= 0 then
            local chunk_field = { x = chunk.x, y = chunk.y }
            for i = 1, #entities do
                local e = entities[i]
                if e and e.valid then
                    -- Filter common rock variants (type "simple-entity") if any
                    if e.type == "simple-entity" then
                        local n = e.name
                        if n == "rock-huge" or n == "rock-big" or n == "sand-rock-big" then
                            goto continue_entity
                        end
                    end

                    local row = self:_serialize_entity(e)
                    if row then
                        local chunk = chunk_field

                        -- Base entity row (no component payloads)
                        local base = {
                            unit_number = row.unit_number,
                            name = row.name,
                            type = row.type,
                            force = row.force,
                            position = row.position,
                            direction = row.direction,
                            direction_name = row.direction_name,
                            orientation = row.orientation,
                            orientation_name = row.orientation_name,
                            chunk = chunk,
                        }
                        if row.health ~= nil then base.health = row.health end
                        if row.status ~= nil then base.status = row.status end
                        if row.status_name ~= nil then base.status_name = row.status_name end
                        if row.bounding_box ~= nil then base.bounding_box = row.bounding_box end
                        if row.selection_box ~= nil then base.selection_box = row.selection_box end
                        if row.train ~= nil then base.train = row.train end
                        entity_rows[#entity_rows + 1] = base

                        -- Electric component
                        if row.electric_network_id ~= nil or row.electric_buffer_size ~= nil or row.energy ~= nil then
                            electric_rows[#electric_rows + 1] = {
                                unit_number = row.unit_number,
                                electric_network_id = row.electric_network_id,
                                electric_buffer_size = row.electric_buffer_size,
                                energy = row.energy,
                                chunk = chunk,
                            }
                        end

                        -- Crafting component
                        if row.recipe ~= nil or row.crafting_progress ~= nil then
                            crafting_rows[#crafting_rows + 1] = {
                                unit_number = row.unit_number,
                                recipe = row.recipe,
                                crafting_progress = row.crafting_progress,
                                chunk = chunk,
                            }
                        end

                        -- Burner component
                        if row.burner ~= nil then
                            burner_rows[#burner_rows + 1] = {
                                unit_number = row.unit_number,
                                burner = row.burner,
                                chunk = chunk,
                            }
                        end

                        -- Inventory component
                        if row.inventories ~= nil then
                            -- Filter out empty mining_drill_modules
                            local filtered_inventories = {}
                            for inv_name, inv_data in pairs(row.inventories) do
                                if inv_name ~= "mining_drill_modules" or (inv_data and next(inv_data) ~= nil) then
                                    filtered_inventories[inv_name] = inv_data
                                end
                            end
                            -- Only add if there are non-empty inventories
                            if next(filtered_inventories) ~= nil then
                                inventory_rows[#inventory_rows + 1] = {
                                    unit_number = row.unit_number,
                                    inventories = filtered_inventories,
                                    chunk = chunk,
                                }
                            end
                        end

                        -- Fluids component
                        if row.fluids ~= nil then
                            fluids_rows[#fluids_rows + 1] = {
                                unit_number = row.unit_number,
                                fluids = row.fluids,
                                chunk = chunk,
                            }
                        end

                        -- Inserter component
                        if row.inserter ~= nil then
                            inserter_rows[#inserter_rows + 1] = {
                                unit_number = row.unit_number,
                                inserter = row.inserter,
                                chunk = chunk,
                            }
                        end
                    end
                end
                ::continue_entity::
            end
        end
    end

    local output = self:create_output("snapshot.entities", "v3", {
        entity_rows = entity_rows,
        electric_rows = electric_rows,
        crafting_rows = crafting_rows,
        burner_rows = burner_rows,
        inventory_rows = inventory_rows,
        fluids_rows = fluids_rows,
        inserter_rows = inserter_rows,
    })

    -- Group entities by chunk for chunk-wise CSV emission
    local entities_by_chunk = {}
    local electric_by_chunk = {}
    local crafting_by_chunk = {}
    local burner_by_chunk = {}
    local inventory_by_chunk = {}
    local fluids_by_chunk = {}
    local inserter_by_chunk = {}

    -- Group all entity data by chunk
    for _, entity in ipairs(entity_rows) do
        local chunk_key = string.format("%d_%d", entity.chunk.x, entity.chunk.y)
        if not entities_by_chunk[chunk_key] then
            entities_by_chunk[chunk_key] = { chunk_x = entity.chunk.x, chunk_y = entity.chunk.y, entities = {} }
        end
        table.insert(entities_by_chunk[chunk_key].entities, entity)
    end

    for _, electric in ipairs(electric_rows) do
        local chunk_key = string.format("%d_%d", electric.chunk.x, electric.chunk.y)
        if not electric_by_chunk[chunk_key] then
            electric_by_chunk[chunk_key] = { chunk_x = electric.chunk.x, chunk_y = electric.chunk.y, entities = {} }
        end
        table.insert(electric_by_chunk[chunk_key].entities, electric)
    end

    for _, crafting in ipairs(crafting_rows) do
        local chunk_key = string.format("%d_%d", crafting.chunk.x, crafting.chunk.y)
        if not crafting_by_chunk[chunk_key] then
            crafting_by_chunk[chunk_key] = { chunk_x = crafting.chunk.x, chunk_y = crafting.chunk.y, entities = {} }
        end
        table.insert(crafting_by_chunk[chunk_key].entities, crafting)
    end

    for _, burner in ipairs(burner_rows) do
        local chunk_key = string.format("%d_%d", burner.chunk.x, burner.chunk.y)
        if not burner_by_chunk[chunk_key] then
            burner_by_chunk[chunk_key] = { chunk_x = burner.chunk.x, chunk_y = burner.chunk.y, entities = {} }
        end
        table.insert(burner_by_chunk[chunk_key].entities, burner)
    end

    for _, inventory in ipairs(inventory_rows) do
        local chunk_key = string.format("%d_%d", inventory.chunk.x, inventory.chunk.y)
        if not inventory_by_chunk[chunk_key] then
            inventory_by_chunk[chunk_key] = { chunk_x = inventory.chunk.x, chunk_y = inventory.chunk.y, entities = {} }
        end
        table.insert(inventory_by_chunk[chunk_key].entities, inventory)
    end

    for _, fluids in ipairs(fluids_rows) do
        local chunk_key = string.format("%d_%d", fluids.chunk.x, fluids.chunk.y)
        if not fluids_by_chunk[chunk_key] then
            fluids_by_chunk[chunk_key] = { chunk_x = fluids.chunk.x, chunk_y = fluids.chunk.y, entities = {} }
        end
        table.insert(fluids_by_chunk[chunk_key].entities, fluids)
    end

    for _, inserter in ipairs(inserter_rows) do
        local chunk_key = string.format("%d_%d", inserter.chunk.x, inserter.chunk.y)
        if not inserter_by_chunk[chunk_key] then
            inserter_by_chunk[chunk_key] = { chunk_x = inserter.chunk.x, chunk_y = inserter.chunk.y, entities = {} }
        end
        table.insert(inserter_by_chunk[chunk_key].entities, inserter)
    end

    -- Emit CSV files for each chunk and component type
    local base_opts = {
        output_dir = "script-output/factoryverse",
        tick = output.timestamp,
        metadata = {
            schema_version = "snapshot.entities.v3",
            surface = output.surface,
        }
    }

    -- Emit entities by chunk
    local entity_headers = self:get_headers("entity")
    for chunk_key, chunk_data in pairs(entities_by_chunk) do
        local flattened_entities = {}
        for _, entity in ipairs(chunk_data.entities) do
            table.insert(flattened_entities, self:flatten_data("entity", entity))
        end
        local opts = {
            output_dir = base_opts.output_dir,
            chunk_x = chunk_data.chunk_x,
            chunk_y = chunk_data.chunk_y,
            tick = base_opts.tick,
            metadata = base_opts.metadata
        }
        self:emit_csv(opts, "entities", self:_array_to_csv(flattened_entities, entity_headers),
            { headers = entity_headers })
    end

    -- Emit electric by chunk
    local electric_headers = self:get_headers("electric")
    for chunk_key, chunk_data in pairs(electric_by_chunk) do
        local flattened_electric = {}
        for _, electric in ipairs(chunk_data.entities) do
            table.insert(flattened_electric, self:flatten_data("electric", electric))
        end
        local opts = {
            output_dir = base_opts.output_dir,
            chunk_x = chunk_data.chunk_x,
            chunk_y = chunk_data.chunk_y,
            tick = base_opts.tick,
            metadata = base_opts.metadata
        }
        self:emit_csv(opts, "entities_electric", self:_array_to_csv(flattened_electric, electric_headers),
            { headers = electric_headers })
    end

    -- Emit crafting by chunk
    local crafting_headers = self:get_headers("crafting")
    for chunk_key, chunk_data in pairs(crafting_by_chunk) do
        local flattened_crafting = {}
        for _, crafting in ipairs(chunk_data.entities) do
            table.insert(flattened_crafting, self:flatten_data("crafting", crafting))
        end
        local opts = {
            output_dir = base_opts.output_dir,
            chunk_x = chunk_data.chunk_x,
            chunk_y = chunk_data.chunk_y,
            tick = base_opts.tick,
            metadata = base_opts.metadata
        }
        self:emit_csv(opts, "entities_crafting", self:_array_to_csv(flattened_crafting, crafting_headers),
            { headers = crafting_headers })
    end

    -- Emit burner by chunk
    local burner_headers = self:get_headers("burner")
    for chunk_key, chunk_data in pairs(burner_by_chunk) do
        local flattened_burner = {}
        for _, burner in ipairs(chunk_data.entities) do
            table.insert(flattened_burner, self:flatten_data("burner", burner))
        end
        local opts = {
            output_dir = base_opts.output_dir,
            chunk_x = chunk_data.chunk_x,
            chunk_y = chunk_data.chunk_y,
            tick = base_opts.tick,
            metadata = base_opts.metadata
        }
        self:emit_csv(opts, "entities_burner", self:_array_to_csv(flattened_burner, burner_headers),
            { headers = burner_headers })
    end

    -- Emit inventory by chunk
    local inventory_headers = self:get_headers("inventory")
    for chunk_key, chunk_data in pairs(inventory_by_chunk) do
        local flattened_inventory = {}
        for _, inventory in ipairs(chunk_data.entities) do
            table.insert(flattened_inventory, self:flatten_data("inventory", inventory))
        end
        local opts = {
            output_dir = base_opts.output_dir,
            chunk_x = chunk_data.chunk_x,
            chunk_y = chunk_data.chunk_y,
            tick = base_opts.tick,
            metadata = base_opts.metadata
        }
        self:emit_csv(opts, "entities_inventory", self:_array_to_csv(flattened_inventory, inventory_headers),
            { headers = inventory_headers })
    end

    -- Emit fluids by chunk
    local fluids_headers = self:get_headers("fluids")
    for chunk_key, chunk_data in pairs(fluids_by_chunk) do
        local flattened_fluids = {}
        for _, fluids in ipairs(chunk_data.entities) do
            table.insert(flattened_fluids, self:flatten_data("fluids", fluids))
        end
        local opts = {
            output_dir = base_opts.output_dir,
            chunk_x = chunk_data.chunk_x,
            chunk_y = chunk_data.chunk_y,
            tick = base_opts.tick,
            metadata = base_opts.metadata
        }
        self:emit_csv(opts, "entities_fluids", self:_array_to_csv(flattened_fluids, fluids_headers),
            { headers = fluids_headers })
    end

    -- Emit inserter by chunk
    local inserter_headers = self:get_headers("inserter")
    for chunk_key, chunk_data in pairs(inserter_by_chunk) do
        local flattened_inserter = {}
        for _, inserter in ipairs(chunk_data.entities) do
            table.insert(flattened_inserter, self:flatten_data("inserter", inserter))
        end
        local opts = {
            output_dir = base_opts.output_dir,
            chunk_x = chunk_data.chunk_x,
            chunk_y = chunk_data.chunk_y,
            tick = base_opts.tick,
            metadata = base_opts.metadata
        }
        self:emit_csv(opts, "entities_inserter", self:_array_to_csv(flattened_inserter, inserter_headers),
            { headers = inserter_headers })
    end

    self:print_summary(output, function(out)
        local d = out and out.data or {}
        local c = function(t) return (t and #t) or 0 end
        return {
            surface = out.surface,
            tick = out.timestamp,
            entities = {
                entity_rows = c(d.entity_rows),
                electric_rows = c(d.electric_rows),
                crafting_rows = c(d.crafting_rows),
                burner_rows = c(d.burner_rows),
                inventory_rows = c(d.inventory_rows),
                fluids_rows = c(d.fluids_rows),
                inserter_rows = c(d.inserter_rows),
            },
        }
    end)

    return output
end

--- Dump only belt-like entities with transport line contents
--- Dump only belt-like entities with transport line contents as flat rows
--- Dump only belt-like entities with transport line contents as flat component rows
function EntitiesSnapshot:take_belts()
    log("Taking belts snapshot")

    local charted_chunks = self.game_state:get_charted_chunks()
    local belt_rows = {}

    local surface = self.game_state:get_surface()
    if not surface then
        local empty = self:create_output("snapshot.belts", "v3", { belt_rows = {} })
        return empty
    end

    local belt_types = {
        "transport-belt", "underground-belt", "splitter",
        "loader", "loader-1x1", "linked-belt"
    }

    for _, chunk in ipairs(charted_chunks) do
        local filter = { area = chunk.area, force = "player", type = belt_types }
        local belts = surface.find_entities_filtered(filter)
        if #belts ~= 0 then
            local chunk_field = { x = chunk.x, y = chunk.y }
            for i = 1, #belts do
                local e = belts[i]
                if e and e.valid then
                    local item_lines = {}
                    local max_index = 0
                    do
                        local name = e.name
                        local cache = self._cache and self._cache.belt or nil
                        if cache and cache[name] ~= nil then
                            max_index = cache[name]
                        else
                            local v = (e.get_max_transport_line_index and e.get_max_transport_line_index()) or 0
                            max_index = (type(v) == "number" and v > 0) and v or 0
                            if cache then cache[name] = max_index end
                        end
                    end

                    for li = 1, max_index do
                        local tl = e.get_transport_line and e.get_transport_line(li) or nil
                        if tl then
                            local contents = tl.get_contents and tl.get_contents() or nil
                            if contents and next(contents) ~= nil then
                                item_lines[#item_lines + 1] = { index = li, items = contents }
                            end
                        end
                    end

                    -- Belt neighbours (inputs/outputs) and underground pairing
                    local inputs_ids, outputs_ids = {}, {}
                    local bn = e.belt_neighbours
                    if bn then
                        if bn.inputs then
                            for _, n in ipairs(bn.inputs) do
                                if n and n.valid and n.unit_number then inputs_ids[#inputs_ids + 1] = n.unit_number end
                            end
                        end
                        if bn.outputs then
                            for _, n in ipairs(bn.outputs) do
                                if n and n.valid and n.unit_number then outputs_ids[#outputs_ids + 1] = n.unit_number end
                            end
                        end
                    end
                    local underground_other = nil
                    local belt_to_ground_type = nil
                    if e.type == "underground-belt" then
                        belt_to_ground_type = e.belt_to_ground_type
                        local un = e.neighbours -- for underground belts this is the other end (or nil)
                        if un and un.valid and un.unit_number then underground_other = un.unit_number end
                    end

                    belt_rows[#belt_rows + 1] = {
                        unit_number = e.unit_number,
                        name = e.name,
                        type = e.type,
                        position = e.position,
                        direction = e.direction,
                        direction_name = utils.direction_to_name(e.direction and tonumber(tostring(e.direction)) or nil),
                        item_lines = item_lines,
                        belt_neighbours = ((#inputs_ids > 0 or #outputs_ids > 0) and { inputs = inputs_ids, outputs = outputs_ids }) or
                        nil,
                        belt_to_ground_type = belt_to_ground_type,
                        underground_neighbour_unit = underground_other,
                        chunk = chunk_field,
                    }
                end
            end
        end
    end

    local output = self:create_output("snapshot.belts", "v3", { belt_rows = belt_rows })

    -- Group belts by chunk for chunk-wise CSV emission
    local belts_by_chunk = {}
    for _, belt in ipairs(belt_rows) do
        local chunk_key = string.format("%d_%d", belt.chunk.x, belt.chunk.y)
        if not belts_by_chunk[chunk_key] then
            belts_by_chunk[chunk_key] = { chunk_x = belt.chunk.x, chunk_y = belt.chunk.y, belts = {} }
        end
        table.insert(belts_by_chunk[chunk_key].belts, belt)
    end

    -- Emit CSV for belts by chunk
    local base_opts = {
        output_dir = "script-output/factoryverse",
        tick = output.timestamp,
        metadata = {
            schema_version = "snapshot.belts.v3",
            surface = output.surface,
        }
    }

    local belt_headers = self:get_headers("belt")
    for chunk_key, chunk_data in pairs(belts_by_chunk) do
        local flattened_belts = {}
        for _, belt in ipairs(chunk_data.belts) do
            table.insert(flattened_belts, self:flatten_data("belt", belt))
        end
        local opts = {
            output_dir = base_opts.output_dir,
            chunk_x = chunk_data.chunk_x,
            chunk_y = chunk_data.chunk_y,
            tick = base_opts.tick,
            metadata = base_opts.metadata
        }
        self:emit_csv(opts, "belts", self:_array_to_csv(flattened_belts, belt_headers), { headers = belt_headers })
    end

    self:print_summary(output, function(out)
        local total = 0
        if out and out.data and out.data.belt_rows then total = #out.data.belt_rows end
        return { surface = out.surface, belts = { total = total }, tick = out.timestamp }
    end)

    return output
end

-- Internal helpers -----------------------------------------------------------

--- Convert table to CSV row, handling nested structures
--- @param data table - data to convert
--- @param headers table - column headers
--- @return string - CSV row
function EntitiesSnapshot:_table_to_csv_row(data, headers)
    local values = {}
    for _, header in ipairs(headers) do
        local value = data[header]
        if value == nil then
            table.insert(values, "")
        elseif type(value) == "table" then
            -- Convert table to JSON string for complex nested data
            local json_str = helpers.table_to_json(value)
            table.insert(values, '"' .. json_str:gsub('"', '""') .. '"')
        elseif type(value) == "string" then
            -- Regular string, escape quotes and wrap in quotes
            table.insert(values, '"' .. value:gsub('"', '""') .. '"')
        else
            table.insert(values, tostring(value))
        end
    end
    return table.concat(values, ",")
end

--- Convert array of tables to CSV
--- @param data table - array of data rows
--- @param headers table - column headers
--- @return string - CSV content
function EntitiesSnapshot:_array_to_csv(data, headers)
    if #data == 0 then
        return table.concat(headers, ",") .. "\n"
    end

    local csv_lines = { table.concat(headers, ",") }
    for _, row in ipairs(data) do
        table.insert(csv_lines, self:_table_to_csv_row(row, headers))
    end
    return table.concat(csv_lines, "\n") .. "\n"
end

--- @param e LuaEntity
--- @return table|nil
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

    -- Energy buffers
    if e.energy ~= nil then out.energy = e.energy end
    if e.electric_buffer_size ~= nil then out.electric_buffer_size = e.electric_buffer_size end

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
                do
                    local cb = burner.currently_burning
                    if cb then
                        local item_name = _item_id_to_name(rawget(cb, "name")) or _item_id_to_name(cb)
                        if item_name then b.currently_burning = item_name end
                    end
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
