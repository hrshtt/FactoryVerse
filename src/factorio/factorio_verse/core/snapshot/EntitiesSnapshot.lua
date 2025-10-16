local Snapshot = require "core.snapshot.Snapshot"
local utils = require "utils"

--- Component Schema Definition for EntitiesSnapshot
local ComponentSchema = {
    -- Base entity component
    entity = {
        fields = {
            unit_number = "number",
            -- permanent fields
            name = "string",
            type = "string",
            force = "string",
            -- rarely changing fields
            direction = "number",
            direction_name = "string",
            orientation = "number",
            orientation_name = "string",
            electric_network_id = "number",
            recipe = "string",
            -- spatial fields
            position_x = "number",
            position_y = "number",
            tile_width = "number",
            tile_height = "number",
            bounding_box_min_x = "number",
            bounding_box_min_y = "number",
            bounding_box_max_x = "number",
            bounding_box_max_y = "number",
            chunk_x = "number",
            chunk_y = "number",
        },
        flatten_rules = {
            position = { x = "position_x", y = "position_y" },
            chunk = { x = "chunk_x", y = "chunk_y" },
            bounding_box = {
                bbox_min_x = "bounding_box_min_x",
                bbox_min_y = "bounding_box_min_y",
                bbox_max_x = "bounding_box_max_x",
                bbox_max_y = "bounding_box_max_y"
            }
        }
    },

    -- Inserter component
    inserter = {
        fields = {
            unit_number = "number",
            pickup_target_unit = "number",
            drop_target_unit = "number",
            pickup_position_x = "number",
            pickup_position_y = "number",
            drop_position_x = "number",
            drop_position_y = "number",
            chunk_x = "number",
            chunk_y = "number",
        },
        flatten_rules = {
            chunk = { x = "chunk_x", y = "chunk_y" },
            pickup_position = { x = "pickup_position_x", y = "pickup_position_y" },
            drop_position = { x = "drop_position_x", y = "drop_position_y" }
        }
    },

    -- Belt component
    belt = {
        fields = {
            unit_number = "number",
            name = "string",
            type = "string",
            direction = "number",
            direction_name = "string",
            belt_neighbours_json = "json", -- Complex nested data
            belt_to_ground_type = "string",
            underground_neighbour_unit = "number",
            -- spatial fields
            position_x = "number",
            position_y = "number",
            chunk_x = "number",
            chunk_y = "number"
        },
        flatten_rules = {
            position = { x = "position_x", y = "position_y" },
            chunk = { x = "chunk_x", y = "chunk_y" },
            belt_neighbours = "belt_neighbours_json" -- Map to _json suffixed field
        }
    },

    -- Pipe component
    pipe = {
        fields = {
            unit_number = "number",
            name = "string",
            type = "string",
            direction = "number",
            direction_name = "string",
            pipe_neighbours_json = "json", -- Input/output connections like belts
            position_x = "number",
            position_y = "number",
            chunk_x = "number",
            chunk_y = "number",
        },
        flatten_rules = {
            position = { x = "pos_x", y = "pos_y" },
            chunk = { x = "chunk_x", y = "chunk_y" },
            pipe_neighbours = "pipe_neighbours_json" -- Map to _json suffixed field
        }
    },

    -- Entity status for recurring snapshots
    entity_status = {
        fields = {
            unit_number = "number",
            status = "number",
            status_name = "string",
            health = "number",
            tick = "number"
        },
        flatten_rules = {}
    }
}

--- EntitiesSnapshot: Dumps raw entities and associated data chunk-wise
--- Includes basic metadata
--- @class EntitiesSnapshot : Snapshot
local EntitiesSnapshot = Snapshot:new()
EntitiesSnapshot.__index = EntitiesSnapshot

---@return EntitiesSnapshot
function EntitiesSnapshot:new()
    ---@class EntitiesSnapshot : Snapshot
    ---@field _cache table
    local instance = Snapshot:new()
    -- Per-run caches to avoid repeated prototype/method work
    setmetatable(instance, self)
    ---@cast instance EntitiesSnapshot
    return instance
end

--- Get headers for a component type
--- @param component_type string - component type name
--- @return table - array of header names
function EntitiesSnapshot:_get_headers(component_type)
    local schema = ComponentSchema[component_type]
    if not schema then
        error("Unknown component type: " .. tostring(component_type))
    end

    local headers = {}
    for field_name, _ in pairs(schema.fields) do
        table.insert(headers, field_name)
    end

    -- Sort for consistent ordering
    table.sort(headers)
    return headers
end

--- Flatten data according to component schema rules
--- @param component_type string - component type name
--- @param data table - data to flatten
--- @return table - flattened data
function EntitiesSnapshot:_flatten_data(component_type, data)
    local schema = ComponentSchema[component_type]
    if not schema then
        error("Unknown component type: " .. tostring(component_type))
    end

    local flattened = {}
    local rules = schema.flatten_rules or {}

    for k, v in pairs(data) do
        if rules[k] then
            if type(rules[k]) == "string" then
                -- Simple field mapping (e.g., inventories -> inventories_json)
                flattened[rules[k]] = v
            elseif type(rules[k]) == "table" then
                -- Apply flattening rules for nested structures
                for nested_key, flattened_key in pairs(rules[k]) do
                    if type(nested_key) == "string" and type(flattened_key) == "string" then
                        -- Simple field mapping
                        if v[nested_key] ~= nil then
                            flattened[flattened_key] = v[nested_key]
                        end
                    elseif type(nested_key) == "table" and type(flattened_key) == "string" then
                        -- Nested structure flattening (like position -> pos_x, pos_y)
                        for sub_key, sub_flattened_key in pairs(nested_key) do
                            if v[sub_key] ~= nil then
                                flattened[sub_flattened_key] = v[sub_key]
                            end
                        end
                    end
                end
            end
        else
            -- Direct field copy
            flattened[k] = v
        end
    end

    return flattened
end

--- Get events for recurring snapshots
--- @return table - event configuration
function EntitiesSnapshot.get_events()
    return {
        tick_interval = 60,  -- Every second
        handler = function(event)
            EntitiesSnapshot:new():take_recurring()
        end
    }
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
        "electric-pole", "radar", "storage-tank", "offshore-pump", "chemical-plant", "oil-refinery",
        "boiler", "generator", "pump", "pumpjack", "rocket-silo", "container", "logistic-container",
        "arithmetic-combinator", "decider-combinator", "constant-combinator", "lamp", "reactor",
        "heat-pipe", "accumulator", "electric-energy-interface",
        -- "programmable-speaker", "train-stop", "rail-signal",
        -- "rail-chain-signal", "locomotive", "cargo-wagon", "fluid-wagon"
    }

    -- Componentized outputs
    local entity_rows = {}
    local inserter_rows = {}

    local surface = self.game_state:get_surface()
    if not surface then
        local empty = self:create_output("snapshot.entities", "v3", {
            entity_rows = {},
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

                        -- Base entity row (includes electric fields, no component payloads)
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
                        if row.bounding_box ~= nil then base.bounding_box = row.bounding_box end
                        -- Electric fields now part of main entity
                        if row.electric_network_id ~= nil then base.electric_network_id = row.electric_network_id end
                        -- Tile dimensions
                        if row.tile_width ~= nil then base.tile_width = row.tile_width end
                        if row.tile_height ~= nil then base.tile_height = row.tile_height end
                        if row.recipe ~= nil then base.recipe = row.recipe end
                        entity_rows[#entity_rows + 1] = base

                        -- Inserter component
                        if row.inserter ~= nil then
                            inserter_rows[#inserter_rows + 1] = {
                                unit_number = row.unit_number,
                                pickup_position = row.inserter.pickup_position,
                                drop_position = row.inserter.drop_position,
                                pickup_target_unit = row.inserter.pickup_target_unit,
                                drop_target_unit = row.inserter.drop_target_unit,
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
        inserter_rows = inserter_rows,
    })

    -- Group entities by chunk for chunk-wise CSV emission
    local entities_by_chunk = {}
    local inserter_by_chunk = {}

    -- Group all entity data by chunk
    for _, entity in ipairs(entity_rows) do
        local chunk_key = string.format("%d_%d", entity.chunk.x, entity.chunk.y)
        if not entities_by_chunk[chunk_key] then
            entities_by_chunk[chunk_key] = { chunk_x = entity.chunk.x, chunk_y = entity.chunk.y, entities = {} }
        end
        table.insert(entities_by_chunk[chunk_key].entities, entity)
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
    local entity_headers = self:_get_headers("entity")
    for chunk_key, chunk_data in pairs(entities_by_chunk) do
        local flattened_entities = {}
        for _, entity in ipairs(chunk_data.entities) do
            table.insert(flattened_entities, self:_flatten_data("entity", entity))
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


    local belt_output = self:_take_belts()

    -- Process pipes
    local pipe_output = self:_take_pipes()

    self:print_summary(output, function(out)
        local d = out and out.data or {}
        local c = function(t) return (t and #t) or 0 end
        local belt_count = 0
        if belt_output and belt_output.data and belt_output.data.belt_rows then
            belt_count = #belt_output.data.belt_rows
        end
        local pipe_count = 0
        if pipe_output and pipe_output.data and pipe_output.data.pipe_rows then
            pipe_count = #pipe_output.data.pipe_rows
        end
        return {
            surface = out.surface,
            tick = out.timestamp,
            entities = {
                entity_rows = c(d.entity_rows),
                inserter_rows = c(d.inserter_rows),
                belt_rows = belt_count,
                pipe_rows = pipe_count,
            },
        }
    end)

    return output
end

--- Take recurring snapshot of entity status and health
--- Overwrites single CSV file with current status of all entities
function EntitiesSnapshot:take_recurring()
    log("Taking recurring entities snapshot (status/health)")

    local charted_chunks = self.game_state:get_charted_chunks()
    local status_rows = {}

    local surface = self.game_state:get_surface()
    if not surface then
        local empty = self:create_output("snapshot.entities.recurring", "v1", { status_rows = {} })
        return empty
    end

    -- Engine-side allowlist to avoid creating wrappers for belts/naturals
    local allowed_types = {
        "assembling-machine", "furnace", "mining-drill", "inserter", "lab", "roboport", "beacon",
        "electric-pole", "radar", "storage-tank", "offshore-pump", "chemical-plant", "oil-refinery",
        "boiler", "generator", "pump", "pumpjack", "rocket-silo", "container", "logistic-container",
        "arithmetic-combinator", "decider-combinator", "constant-combinator", "lamp", "reactor",
        "heat-pipe", "accumulator", "electric-energy-interface",
    }

    for _, chunk in ipairs(charted_chunks) do
        local filter = { area = chunk.area, force = "player", type = allowed_types }
        local entities = surface.find_entities_filtered(filter)
        if #entities ~= 0 then
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

                    local status_data = {
                        unit_number = e.unit_number,
                        status = e.status or 0,
                        status_name = e.status and utils.status_to_name(e.status) or "unknown",
                        health = e.health or 0,
                        tick = game and game.tick or 0
                    }

                    table.insert(status_rows, status_data)
                end
                ::continue_entity::
            end
        end
    end

    local output = self:create_output("snapshot.entities.recurring", "v1", {
        status_rows = status_rows,
    })

    -- Emit single CSV file (overwrites each time)
    local headers = self:_get_headers("entity_status")
    local flattened_rows = {}
    for _, row in ipairs(status_rows) do
        table.insert(flattened_rows, self:_flatten_data("entity_status", row))
    end

    local csv_data = self:_array_to_csv(flattened_rows, headers)
    local opts = {
        output_dir = "script-output/factoryverse/recurring",
        tick = output.timestamp,
        metadata = {
            schema_version = "snapshot.entities.recurring.v1",
            surface = output.surface,
        }
    }
    self:emit_csv(opts, "entity_status", csv_data, { headers = headers })

    self:print_summary(output, function(out)
        local d = out and out.data or {}
        return {
            surface = out.surface,
            tick = out.timestamp,
            entities_status = #d.status_rows,
        }
    end)

    return output
end

--- Internal method to dump only belt-like entities with transport line contents
--- Dump only belt-like entities with transport line contents as flat rows
--- Dump only belt-like entities with transport line contents as flat component rows
function EntitiesSnapshot:_take_belts()
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

    local belt_headers = self:_get_headers("belt")
    for chunk_key, chunk_data in pairs(belts_by_chunk) do
        local flattened_belts = {}
        for _, belt in ipairs(chunk_data.belts) do
            table.insert(flattened_belts, self:_flatten_data("belt", belt))
        end
        local opts = {
            output_dir = base_opts.output_dir,
            chunk_x = chunk_data.chunk_x,
            chunk_y = chunk_data.chunk_y,
            tick = base_opts.tick,
            metadata = base_opts.metadata
        }
        self:emit_csv(opts, "entities_belts", self:_array_to_csv(flattened_belts, belt_headers), { headers = belt_headers })
    end

    return output
end

--- Internal method to dump only pipe-like entities
function EntitiesSnapshot:_take_pipes()
    log("Taking pipes snapshot")

    local charted_chunks = self.game_state:get_charted_chunks()
    local pipe_rows = {}

    local surface = self.game_state:get_surface()
    if not surface then
        local empty = self:create_output("snapshot.pipes", "v3", { pipe_rows = {} })
        return empty
    end

    local pipe_types = {
        "pipe", "pipe-to-ground"
    }

    for _, chunk in ipairs(charted_chunks) do
        local filter = { area = chunk.area, force = "player", type = pipe_types }
        local pipes = surface.find_entities_filtered(filter)
        if #pipes ~= 0 then
            local chunk_field = { x = chunk.x, y = chunk.y }
            for i = 1, #pipes do
                local e = pipes[i]
                if e and e.valid then
                    -- Pipe neighbours (similar to belt_neighbours) - categorize as inputs/outputs
                    local inputs_ids, outputs_ids = {}, {}

                    -- Get connected entities through fluidbox and categorize as inputs/outputs
                    local fb = e.fluidbox
                    if fb then
                        for k = 1, #fb do
                            local connections = fb.get_connections and fb.get_connections(k) or {}
                            for _, conn in ipairs(connections) do
                                if conn.owner and conn.owner.valid and conn.owner.unit_number then
                                    local conn_entity = conn.owner
                                    local conn_unit = conn_entity.unit_number
                                    
                                    -- Categorize connections based on entity type and relative position
                                    -- This is a simplified approach - in practice, you might want more sophisticated logic
                                    if conn_entity.type == "pipe" or conn_entity.type == "pipe-to-ground" then
                                        -- For pipe-to-pipe connections, use position to determine flow direction
                                        -- This is a heuristic - pipes generally flow from higher to lower pressure/position
                                        if conn_entity.position and e.position then
                                            local dx = conn_entity.position.x - e.position.x
                                            local dy = conn_entity.position.y - e.position.y
                                            -- Simple heuristic: if connected entity is "upstream" (higher x or y), it's input
                                            if dx > 0 or dy > 0 then
                                                inputs_ids[#inputs_ids + 1] = conn_unit
                                            else
                                                outputs_ids[#outputs_ids + 1] = conn_unit
                                            end
                                        else
                                            -- Fallback: treat as input
                                            inputs_ids[#inputs_ids + 1] = conn_unit
                                        end
                                    else
                                        -- For non-pipe entities (boilers, engines, etc.), treat as inputs
                                        inputs_ids[#inputs_ids + 1] = conn_unit
                                    end
                                end
                            end
                        end
                    end

                    pipe_rows[#pipe_rows + 1] = {
                        unit_number = e.unit_number,
                        name = e.name,
                        type = e.type,
                        position = e.position,
                        direction = e.direction,
                        direction_name = utils.direction_to_name(e.direction and tonumber(tostring(e.direction)) or nil),
                        pipe_neighbours = ((#inputs_ids > 0 or #outputs_ids > 0) and { inputs = inputs_ids, outputs = outputs_ids }) or nil,
                        chunk = chunk_field,
                    }
                end
            end
        end
    end

    local output = self:create_output("snapshot.pipes", "v3", { pipe_rows = pipe_rows })

    -- Group pipes by chunk for chunk-wise CSV emission
    local pipes_by_chunk = {}
    for _, pipe in ipairs(pipe_rows) do
        local chunk_key = string.format("%d_%d", pipe.chunk.x, pipe.chunk.y)
        if not pipes_by_chunk[chunk_key] then
            pipes_by_chunk[chunk_key] = { chunk_x = pipe.chunk.x, chunk_y = pipe.chunk.y, pipes = {} }
        end
        table.insert(pipes_by_chunk[chunk_key].pipes, pipe)
    end

    -- Emit CSV for pipes by chunk
    local base_opts = {
        output_dir = "script-output/factoryverse",
        tick = output.timestamp,
        metadata = {
            schema_version = "snapshot.pipes.v3",
            surface = output.surface,
        }
    }

    local pipe_headers = self:_get_headers("pipe")
    for chunk_key, chunk_data in pairs(pipes_by_chunk) do
        local flattened_pipes = {}
        for _, pipe in ipairs(chunk_data.pipes) do
            table.insert(flattened_pipes, self:_flatten_data("pipe", pipe))
        end
        local opts = {
            output_dir = base_opts.output_dir,
            chunk_x = chunk_data.chunk_x,
            chunk_y = chunk_data.chunk_y,
            tick = base_opts.tick,
            metadata = base_opts.metadata
        }
        self:emit_csv(opts, "entities_pipes", self:_array_to_csv(flattened_pipes, pipe_headers), { headers = pipe_headers })
    end

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

    -- Electric network id
    if e.electric_network_id ~= nil then
        out.electric_network_id = e.electric_network_id
    end

    -- Tile dimensions from prototype
    if proto then
        if proto.tile_width ~= nil then out.tile_width = proto.tile_width end
        if proto.tile_height ~= nil then out.tile_height = proto.tile_height end
    end

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
