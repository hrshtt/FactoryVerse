local Snapshot = require "core.Snapshot"
local utils = require "utils"

--- EntitiesSnapshot: Dumps raw entities and associated data chunk-wise
--- Includes inventories, fluidboxes, energy/burner info, and basic metadata
local EntitiesSnapshot = Snapshot:new()
EntitiesSnapshot.__index = EntitiesSnapshot

function EntitiesSnapshot:new()
    local instance = Snapshot:new()
    -- Per-run caches to avoid repeated prototype/method work
    instance._cache = {
        inv = {},          -- [entity_name] -> { {name, id}, ... } inventory indices that exist
        fluid = {},        -- [entity_name] -> { [index] = capacity }
        belt = {},         -- [entity_name] -> max transport line index
    }
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
        -- Use engine filter for force only; do type exclusions in Lua to avoid invert/force pitfalls
        local filter = { area = chunk.area, force = "player" }

        -- Fast skip chunks with zero matching entities for this force
        local cnt = surface.count_entities_filtered(filter)
        if cnt ~= 0 then
            local entities = surface.find_entities_filtered(filter)

            -- Excluded types (handled elsewhere or not needed)
            local skip_types = {
                resource = true, tree = true, fish = true,
                ["transport-belt"] = true, ["underground-belt"] = true, splitter = true,
                loader = true, ["loader-1x1"] = true, ["linked-belt"] = true,
            }

            local out_entities = {}
            for i = 1, #entities do
                local e = entities[i]
                if e and e.valid and not skip_types[e.type] then
                    -- Filter common rock variants (type "simple-entity") if any
                    if e.type == "simple-entity" then
                        local n = e.name
                        if n == "rock-huge" or n == "rock-big" or n == "sand-rock-big" then
                            goto continue_entity
                        end
                    end
                    local serialized = self:_serialize_entity(e)
                    if serialized then
                        out_entities[#out_entities + 1] = serialized
                    end
                end
                ::continue_entity::
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
        local filter = { area = chunk.area, force = "player", type = belt_types }
        local cnt = surface.count_entities_filtered(filter)
        if cnt ~= 0 then
            local belts = surface.find_entities_filtered(filter)
            local out_entities = {}

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

                    out_entities[#out_entities + 1] = {
                        unit_number = e.unit_number,
                        name = e.name,
                        type = e.type,
                        position = e.position,
                        direction = e.direction,
                        direction_name = utils.direction_to_name(e.direction),
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

    local proto = e.prototype
    local cache_inv  = self._cache and self._cache.inv or nil
    local cache_fluid = self._cache and self._cache.fluid or nil
    local ename = e.name

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

    -- Selection & bounding boxes (runtime first; fall back to prototype)
    do
        local bb_ok, bb = pcall(function() return e.bounding_box end)
        if bb_ok and bb and bb.left_top and bb.right_bottom then
            out.bounding_box = {
                min_x = bb.left_top.x, min_y = bb.left_top.y,
                max_x = bb.right_bottom.x, max_y = bb.right_bottom.y
            }
        end
        local sb_ok, sb = pcall(function() return e.selection_box end)
        if sb_ok and sb and sb.left_top and sb.right_bottom then
            out.selection_box = {
                min_x = sb.left_top.x, min_y = sb.left_top.y,
                max_x = sb.right_bottom.x, max_y = sb.right_bottom.y
            }
        elseif proto and proto.selection_box then
            local psb = proto.selection_box
            -- Prototype selection_box may be in array form {{x1,y1},{x2,y2}} or with left_top/right_bottom
            if psb.left_top and psb.right_bottom then
                out.selection_box = {
                    min_x = psb.left_top.x or psb.left_top[1],
                    min_y = psb.left_top.y or psb.left_top[2],
                    max_x = psb.right_bottom.x or psb.right_bottom[1],
                    max_y = psb.right_bottom.y or psb.right_bottom[2]
                }
            elseif type(psb) == "table" and psb[1] and psb[2] then
                out.selection_box = {
                    min_x = psb[1][1], min_y = psb[1][2],
                    max_x = psb[2][1], max_y = psb[2][2]
                }
            end
        end
    end

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
    local ok_buf, buf = pcall(function() return e.electric_buffer_size end)
    if ok_buf and buf then out.electric_buffer_size = buf end

    -- Electric pole copper neighbours (unit_numbers)
    do
        if e.type == "electric-pole" then
            local n_ok, ns = pcall(function() return e.neighbours end)
            if n_ok and ns then
                local list = ns.copper or ns
                local ids = {}
                if type(list) == "table" then
                    for _, p in pairs(list) do
                        if p and p.valid and p.unit_number then
                            ids[#ids+1] = p.unit_number
                        end
                    end
                end
                if #ids > 0 then
                    out.neighbours = { copper = ids }
                end
            end
        end
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
                        inv_defs[#inv_defs + 1] = {inv_name, idx}
                    end
                end
            end
            if cache_inv then cache_inv[ename] = inv_defs end
        end
        for i = 1, #inv_defs do
            local inv_name, idx = inv_defs[i][1], inv_defs[i][2]
            local inv = e.get_inventory and e.get_inventory(idx) or nil
            if inv and inv.valid then
                local contents = inv.get_contents and inv.get_contents() or nil
                inventories[inv_name] = contents or {}
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

    -- Inserter IO (pickup/drop positions and resolved targets)
    do
        if e.type == "inserter" then
            local ins = {
                pickup_position = e.pickup_position,
                drop_position = e.drop_position,
            }
            local ok_pt, pt = pcall(function() return e.pickup_target end)
            if ok_pt and pt and pt.valid and pt.unit_number then
                ins.pickup_target_unit = pt.unit_number
            end
            local ok_dt, dt = pcall(function() return e.drop_target end)
            if ok_dt and dt and dt.valid and dt.unit_number then
                ins.drop_target_unit = dt.unit_number
            end
            if next(ins) ~= nil then out.inserter = ins end
        end
    end

    -- Train info (for rolling stock)
    do
        if e.train then
            out.train = { id = e.train.id, state = e.train.state }
        end
    end

    return out
end

return EntitiesSnapshot
