local Snapshot = require "core.Snapshot"
local utils = require "utils"

--- EntitiesSnapshot: Dumps raw entities and associated data chunk-wise
--- Includes inventories, fluidboxes, energy/burner info, and basic metadata
local EntitiesSnapshot = Snapshot:new()
EntitiesSnapshot.__index = EntitiesSnapshot

function EntitiesSnapshot:new()
    local instance = Snapshot:new()
    setmetatable(instance, self)
    return instance
end

--- Dump all entities chunk-wise with rich per-entity data
function EntitiesSnapshot:take()
    log("Taking entities snapshot")

    local charted_chunks = self.game_state:get_charted_chunks()
    local chunks_out = {}

    local surface = self.game_state:get_surface()
    if not surface then
        local empty = self:create_output("snapshot.entities", "v1", { chunks = {} })
        return empty
    end

    for _, chunk in ipairs(charted_chunks) do
        local entities = surface.find_entities_filtered { area = chunk.area }

        local out_entities = {}
        for i = 1, #entities do
            local e = entities[i]
            -- Filter out trees and resources (ores, oil, etc.)
            if e and e.valid and e.type ~= "tree" and e.type ~= "resource" then
                local serialized = self:_serialize_entity(e)
                if serialized then
                    out_entities[#out_entities + 1] = serialized
                end
            end
        end

        if #out_entities > 0 then
            chunks_out[#chunks_out + 1] = {
                cx = chunk.x,
                cy = chunk.y,
                count = #out_entities,
                entities = out_entities
            }
        end
    end

    local output = self:create_output("snapshot.entities", "v1", { chunks = chunks_out })

    -- Emit JSON for SQL ingestion
    self:emit_json({ output_dir = "script-output/factoryverse" }, "entities", {
        meta = {
            schema_version = "snapshot.entities.v1",
            surface = output.surface,
            tick = output.timestamp,
        },
        data = output.data,
    })

    self:print_summary(output, function(out)
        local chunk_count = #out.data.chunks
        local total_entities = 0
        for _, c in ipairs(out.data.chunks) do total_entities = total_entities + (c.count or 0) end
        return {
            surface = out.surface,
            entities = { chunk_count = chunk_count, total = total_entities },
            tick = out.timestamp
        }
    end)

    return output
end

--- Dump only belt-like entities with transport line contents
function EntitiesSnapshot:take_belts()
    log("Taking belts snapshot")

    local charted_chunks = self.game_state:get_charted_chunks()
    local chunks_out = {}

    local surface = self.game_state:get_surface()
    if not surface then
        local empty = self:create_output("snapshot.belts", "v1", { chunks = {} })
        return empty
    end

    local belt_types = {
        "transport-belt", "underground-belt", "splitter",
        "loader", "loader-1x1", "linked-belt"
    }

    for _, chunk in ipairs(charted_chunks) do
        local belts = surface.find_entities_filtered { area = chunk.area, type = belt_types }
        local out_entities = {}

        for i = 1, #belts do
            local e = belts[i]
            if e and e.valid then
                local item_lines = {}
                local max_index = 0
                local ok, v = pcall(function() return e.get_max_transport_line_index and e:get_max_transport_line_index() or 0 end)
                if ok and type(v) == "number" and v > 0 then max_index = v end

                for li = 1, max_index do
                    local tl = e.get_transport_line and e:get_transport_line(li) or nil
                    if tl then
                        local contents = tl.get_contents and tl.get_contents() or nil
                        if contents and next(contents) ~= nil then
                            item_lines[#item_lines + 1] = { index = li, items = contents }
                        end
                    end
                end

                out_entities[#out_entities + 1] = {
                    unit_number = e.unit_number,
                    name = e.name,
                    type = e.type,
                    position = e.position,
                    direction = e.direction,
                    item_lines = item_lines
                }
            end
        end

        if #out_entities > 0 then
            chunks_out[#chunks_out + 1] = {
                cx = chunk.x,
                cy = chunk.y,
                count = #out_entities,
                entities = out_entities
            }
        end
    end

    local output = self:create_output("snapshot.belts", "v1", { chunks = chunks_out })

    self:emit_json({ output_dir = "script-output/factoryverse" }, "belts", {
        meta = {
            schema_version = "snapshot.belts.v1",
            surface = output.surface,
            tick = output.timestamp,
        },
        data = output.data,
    })

    self:print_summary(output, function(out)
        local chunk_count = #out.data.chunks
        local total = 0
        for _, c in ipairs(out.data.chunks) do total = total + (c.count or 0) end
        return { surface = out.surface, belts = { chunk_count = chunk_count, total = total }, tick = out.timestamp }
    end)

    return output
end

-- Internal helpers -----------------------------------------------------------

function EntitiesSnapshot:_serialize_entity(e)
    if not (e and e.valid) then return nil end

    local out = {
        unit_number = e.unit_number,
        name = e.name,
        type = e.type,
        force = (e.force and e.force.name) or nil,
        position = e.position,
        direction = e.direction,
        direction_name = utils.direction_to_name(e.direction),
        orientation = e.orientation,
        orientation_name = utils.orientation_to_name(e.orientation),
    }

    -- Health & status
    if e.health ~= nil then out.health = e.health end
    local ok_status, status_val = pcall(function() return e.status end)
    if ok_status and status_val ~= nil then
        out.status = status_val
        out.status_name = utils.entity_status_to_name(status_val)
    end

    -- Electric network id
    local ok_enid, enid = pcall(function() return e.electric_network_id end)
    if ok_enid and enid then out.electric_network_id = enid end

    -- Energy buffers
    if e.energy ~= nil then out.energy = e.energy end
    local ok_buf, buf = pcall(function() return e.electric_buffer_size end)
    if ok_buf and buf then out.electric_buffer_size = buf end

    -- Crafting / recipe
    do
        local recipe_name = nil
        local ok_r, recipe = pcall(function() return e.get_recipe and e.get_recipe() or nil end)
        if ok_r and recipe then recipe_name = recipe.name end
        if not recipe_name then
            local ok_cr, cr = pcall(function() return e.get_recipe and e:get_recipe() end) -- alt call styles
            if ok_cr and cr then recipe_name = cr.name end
        end
        if not recipe_name then
            local ok_sel, sel = pcall(function() return e.get_selected_recipe and e:get_selected_recipe() end)
            if ok_sel and sel then recipe_name = sel.name end
        end
        if recipe_name then out.recipe = recipe_name end

        local ok_prog, prog = pcall(function() return e.crafting_progress end)
        if ok_prog and prog then out.crafting_progress = prog end
    end

    -- Burner info
    do
        local ok_b, burner = pcall(function() return e.burner end)
        if ok_b and burner then
            local b = {}
            local ok_rem, rem = pcall(function() return burner.remaining_burning_fuel end)
            if ok_rem and rem then b.remaining_burning_fuel = rem end
            local ok_curr, cur = pcall(function() return burner.currently_burning and burner.currently_burning.name end)
            if ok_curr and cur then b.currently_burning = cur end
            local inv = {}
            local ok_fi, fi = pcall(function() return burner.inventory end)
            if ok_fi and fi and fi.valid and not fi.is_empty() then inv.fuel = fi.get_contents() end
            local ok_bri, bri = pcall(function() return burner.burnt_result_inventory end)
            if ok_bri and bri and bri.valid and not bri.is_empty() then inv.burnt = bri.get_contents() end
            if next(inv) ~= nil then b.inventories = inv end
            if next(b) ~= nil then out.burner = b end
        end
    end

    -- Inventories (scan all defines.inventory entries safely)
    do
        local inventories = {}
        for inv_name, inv_id in pairs(defines.inventory) do
            if type(inv_id) == "number" then
                local ok_inv, inv = pcall(function() return e.get_inventory and e:get_inventory(inv_id) or nil end)
                if ok_inv and inv and inv.valid and not inv.is_empty() then
                    inventories[inv_name] = inv.get_contents()
                end
            end
        end
        if next(inventories) ~= nil then out.inventories = inventories end
    end

    -- Fluidboxes
    do
        local ok_fb, fb = pcall(function() return e.fluidbox end)
        if ok_fb and fb then
            local fluids = {}
            local count = 0
            local ok_len, len = pcall(function() return #fb end)
            if ok_len and type(len) == "number" then
                for i = 1, len do
                    local f = fb[i]
                    if f then
                        count = count + 1
                        local cap = nil
                        local ok_cap, cval = pcall(function() return fb.get_capacity and fb.get_capacity(i) or nil end)
                        if ok_cap then cap = cval end
                        fluids[#fluids + 1] = {
                            index = i,
                            name = f.name,
                            amount = f.amount,
                            temperature = f.temperature,
                            capacity = cap,
                        }
                    end
                end
            end
            if #fluids > 0 then out.fluids = fluids end
        end
    end

    -- Train info (for rolling stock)
    do
        local ok_train, train = pcall(function() return e.train end)
        if ok_train and train then
            out.train = { id = train.id, state = train.state }
        end
    end

    return out
end

return EntitiesSnapshot


