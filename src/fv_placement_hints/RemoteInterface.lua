--- Placement Hints Remote Interface
--- Provides spatial reasoning queries for AI agents
---
--- All methods are read-only queries that replicate what human players see:
--- - Green/red tiles for valid/invalid placement
--- - Valid directions for directional entities
--- - Connection points for entity relationships
---
--- Entity references always use (entity_name, position) pairs, never unit_number.

local M = {}

-- Require implementation modules
local scanning = require("scanning.area")
local connections = require("connections.init")
local entity_lookup = require("utils.entity_lookup")
local geometry = require("utils.geometry")

-- ============================================================================
-- INTERFACE METHOD DEFINITIONS
-- ============================================================================

local INTERFACE_METHODS = {
    -- ========================================================================
    -- AREA SCANNING
    -- ========================================================================

    --- Validate if a single position is valid for placement
    --- @param entity_name string Entity prototype name
    --- @param position table {x, y}
    --- @param direction number|nil Direction (0=N, 4=E, 8=S, 12=W)
    --- @param ghost boolean|nil Use ghost build check (default: false)
    --- @return table {valid: bool, reason: string|nil}
    validate_placement = {
        category = "validation",
        doc = [[Validate if a single position is valid for entity placement.
Returns validity and optional reason for failure.]],
        paramspec = {
            _param_order = {"entity_name", "position", "direction", "ghost"},
            entity_name = {type = "string", required = true, doc = "Entity prototype name"},
            position = {type = "position", required = true, doc = "Position {x, y}"},
            direction = {type = "number", default = nil, doc = "Direction (0=N, 4=E, 8=S, 12=W)"},
            ghost = {type = "boolean", default = false, doc = "Use ghost build check"},
        },
        func = function(entity_name, position, direction, ghost)
            return scanning.validate_placement(entity_name, position, direction, ghost)
        end,
    },

    --- Batch validate multiple positions
    --- @param entity_name string Entity prototype name
    --- @param positions table Array of {x, y} positions
    --- @param directions table|nil Array of directions (parallel to positions) or nil
    --- @param ghost boolean|nil Use ghost build check (default: false)
    --- @return table Array of booleans (parallel to positions)
    validate_positions = {
        category = "validation",
        doc = [[Batch validate multiple positions for entity placement.
More efficient than multiple validate_placement calls.]],
        paramspec = {
            _param_order = {"entity_name", "positions", "directions", "ghost"},
            entity_name = {type = "string", required = true, doc = "Entity prototype name"},
            positions = {type = "array", required = true, doc = "Array of positions [{x,y}, ...]"},
            directions = {type = "array", default = nil, doc = "Array of directions (parallel to positions)"},
            ghost = {type = "boolean", default = false, doc = "Use ghost build check"},
        },
        func = function(entity_name, positions, directions, ghost)
            return scanning.validate_positions(entity_name, positions, directions, ghost)
        end,
    },

    --- Get valid placements in an area
    --- @param entity_name string Entity prototype name
    --- @param area table {left_top: {x,y}, right_bottom: {x,y}}
    --- @param options table|nil {include_directions: bool, ghost: bool, max_results: number}
    --- @return table Array of {position, direction, valid}
    get_valid_placements = {
        category = "scanning",
        doc = [[Scan an area and return all valid placement positions.
For directional entities, returns the first valid direction per position.
Use for belt lines, pipe runs, or general placement queries.]],
        paramspec = {
            _param_order = {"entity_name", "area", "options"},
            entity_name = {type = "string", required = true, doc = "Entity prototype name"},
            area = {type = "area", required = true, doc = "Area {left_top: {x,y}, right_bottom: {x,y}}"},
            options = {type = "table", default = {}, doc = "Options: {include_directions, ghost, max_results}"},
        },
        func = function(entity_name, area, options)
            return scanning.get_valid_placements(entity_name, area, options or {})
        end,
    },

    --- Get valid placements on resource tiles (for mining drills, pumpjacks)
    --- @param entity_name string Entity prototype name (mining drill or pumpjack)
    --- @param area table {left_top: {x,y}, right_bottom: {x,y}}
    --- @param options table|nil {max_results: number}
    --- @return table Array of {position, direction, resource_name, resource_amount}
    get_resource_placements = {
        category = "scanning",
        doc = [[Scan for valid mining drill/pumpjack placements on resources.
Only returns positions where the entity can be placed on a resource patch.
Optimized to only check tiles with resources.]],
        paramspec = {
            _param_order = {"entity_name", "area", "options"},
            entity_name = {type = "string", required = true, doc = "Mining drill or pumpjack prototype name"},
            area = {type = "area", required = true, doc = "Area to scan"},
            options = {type = "table", default = {}, doc = "Options: {max_results}"},
        },
        func = function(entity_name, area, options)
            return scanning.get_resource_placements(entity_name, area, options or {})
        end,
    },

    --- Get valid placements for water-requiring entities (offshore pumps)
    --- @param entity_name string Entity prototype name (offshore-pump)
    --- @param area table {left_top: {x,y}, right_bottom: {x,y}}
    --- @param options table|nil {max_results: number}
    --- @return table Array of {position, direction, approach_position}
    get_water_placements = {
        category = "scanning",
        doc = [[Scan for valid offshore pump placements along water edges.
Tests all cardinal directions per coastal tile. Each result contains Factorio's
canonical entity-center position plus a standable approach_position within
build reach.
Optimized to only check tiles near water.]],
        paramspec = {
            _param_order = {"entity_name", "area", "options"},
            entity_name = {type = "string", required = true, doc = "Offshore pump prototype name"},
            area = {type = "area", required = true, doc = "Area to scan"},
            options = {type = "table", default = {}, doc = "Options: {max_results}"},
        },
        func = function(entity_name, area, options)
            return scanning.get_water_placements(entity_name, area, options or {})
        end,
    },

    --- Get detailed placement cue for a specific position
    --- @param entity_name string Entity prototype name
    --- @param position table {x, y}
    --- @param direction number|nil Direction to check
    --- @return table Rich placement info with reasons, collisions, valid directions
    get_placement_cue = {
        category = "scanning",
        doc = [[Get detailed placement information for a specific position.
Returns rich feedback including why placement fails (collision, terrain, etc.),
what entities are colliding, and which directions are valid.]],
        paramspec = {
            _param_order = {"entity_name", "position", "direction"},
            entity_name = {type = "string", required = true, doc = "Entity prototype name"},
            position = {type = "position", required = true, doc = "Position to check"},
            direction = {type = "number", default = nil, doc = "Specific direction to check"},
        },
        func = function(entity_name, position, direction)
            return scanning.get_placement_cue(entity_name, position, direction)
        end,
    },

    -- ========================================================================
    -- CONNECTION SOLVING
    -- ========================================================================

    --- Get valid positions to connect item output (drill → chest/belt)
    --- @param source_name string Source entity name (e.g., "electric-mining-drill")
    --- @param source_position table Source entity position {x, y}
    --- @param target_name string Target entity name to place (e.g., "iron-chest")
    --- @param options table|nil {max_results: number, ghost: bool}
    --- @return table Array of {position, direction, perpendicular_offset}
    get_item_drop_connections = {
        category = "connections",
        doc = [[Find valid positions to place an entity that receives items from a source.
Uses the source entity's drop_position to find where targets can be placed.
Results sorted by perpendicular_offset (0.0 = perfect alignment).]],
        paramspec = {
            _param_order = {"source_name", "source_position", "target_name", "options"},
            source_name = {type = "string", required = true, doc = "Source entity name (drill, etc.)"},
            source_position = {type = "position", required = true, doc = "Source entity position"},
            target_name = {type = "string", required = true, doc = "Target entity name to place"},
            options = {type = "table", default = {}, doc = "Options: {max_results, ghost}"},
        },
        func = function(source_name, source_position, target_name, options)
            return connections.get_item_drop_connections(source_name, source_position, target_name, options or {})
        end,
    },

    --- Get valid positions to connect fluid pipes to a machine
    --- @param source_name string Source entity name with fluidbox
    --- @param source_position table Source entity position {x, y}
    --- @param target_name string Target entity name (pipe, pump, etc.)
    --- @param options table|nil {max_results: number, ghost: bool}
    --- @return table Array of {position, direction, connection_index, connection_type}
    get_fluid_connections = {
        category = "connections",
        doc = [[Find valid positions to connect pipes to a machine's fluidbox.
Returns positions adjacent to each fluid connection point.
connection_type indicates "input" or "output" flow direction.]],
        paramspec = {
            _param_order = {"source_name", "source_position", "target_name", "options"},
            source_name = {type = "string", required = true, doc = "Source entity name with fluidbox"},
            source_position = {type = "position", required = true, doc = "Source entity position"},
            target_name = {type = "string", required = true, doc = "Target entity name (pipe, pump, etc.)"},
            options = {type = "table", default = {}, doc = "Options: {max_results, ghost}"},
        },
        func = function(source_name, source_position, target_name, options)
            return connections.get_fluid_connections(source_name, source_position, target_name, options or {})
        end,
    },

    --- Get valid inserter placements between two entities
    --- @param pickup_name string Entity to pick up from
    --- @param pickup_position table Pickup entity position {x, y}
    --- @param drop_name string Entity to drop into
    --- @param drop_position table Drop entity position {x, y}
    --- @param inserter_name string|nil Inserter type (default: "inserter")
    --- @return table Array of {position, direction}
    get_inserter_placements = {
        category = "connections",
        doc = [[Find valid inserter positions to transfer items between two entities.
Tests all cardinal directions and validates that inserter can reach both
pickup and drop positions.]],
        paramspec = {
            _param_order = {"pickup_name", "pickup_position", "drop_name", "drop_position", "inserter_name"},
            pickup_name = {type = "string", required = true, doc = "Entity to pick up from"},
            pickup_position = {type = "position", required = true, doc = "Pickup entity position"},
            drop_name = {type = "string", required = true, doc = "Entity to drop into"},
            drop_position = {type = "position", required = true, doc = "Drop entity position"},
            inserter_name = {type = "string", default = "inserter", doc = "Inserter prototype name"},
        },
        func = function(pickup_name, pickup_position, drop_name, drop_position, inserter_name)
            return connections.get_inserter_placements(
                pickup_name, pickup_position,
                drop_name, drop_position,
                inserter_name or "inserter"
            )
        end,
    },

    --- Get valid pole positions to connect to an existing pole
    --- @param source_name string Source pole entity name
    --- @param source_position table Source pole position {x, y}
    --- @param pole_name string Pole type to place
    --- @param search_area table Area to search {left_top, right_bottom}
    --- @param options table|nil {max_results: number}
    --- @return table Array of {position, wire_distance, entities_in_supply_area}
    get_pole_connections = {
        category = "connections",
        doc = [[Find valid pole positions that can connect to an existing pole.
Returns positions within wire distance, sorted by distance.
Includes count of entities that would be powered by the new pole.]],
        paramspec = {
            _param_order = {"source_name", "source_position", "pole_name", "search_area", "options"},
            source_name = {type = "string", required = true, doc = "Source pole entity name"},
            source_position = {type = "position", required = true, doc = "Source pole position"},
            pole_name = {type = "string", required = true, doc = "Pole type to place"},
            search_area = {type = "area", required = true, doc = "Area to search"},
            options = {type = "table", default = {}, doc = "Options: {max_results}"},
        },
        func = function(source_name, source_position, pole_name, search_area, options)
            return connections.get_pole_connections(
                source_name, source_position,
                pole_name, search_area,
                options or {}
            )
        end,
    },

    -- ========================================================================
    -- ENTITY INFORMATION
    -- ========================================================================

    --- Get output/drop information for an entity
    --- @param entity_name string Entity prototype name
    --- @param position table Entity position {x, y}
    --- @return table {drop_position, direction, bounding_box}
    get_entity_output_info = {
        category = "info",
        doc = [[Get the output/drop position and bounding box for an entity.
Uses engine-provided values (entity.drop_position) rather than prototype calculations.
Essential for connection solving without prototype reimplementation in Python.]],
        paramspec = {
            _param_order = {"entity_name", "position"},
            entity_name = {type = "string", required = true, doc = "Entity prototype name"},
            position = {type = "position", required = true, doc = "Entity position"},
        },
        func = function(entity_name, position)
            return entity_lookup.get_entity_output_info(entity_name, position)
        end,
    },

    --- Get fluid connection points for an entity
    --- @param entity_name string Entity prototype name
    --- @param position table Entity position {x, y}
    --- @return table Array of {position, type, connection_index}
    get_fluid_connection_points = {
        category = "info",
        doc = [[Get the fluid connection points for an entity with a fluidbox.
Returns absolute map positions for each connection, accounting for entity direction.
type indicates "input", "output", or "input-output".]],
        paramspec = {
            _param_order = {"entity_name", "position"},
            entity_name = {type = "string", required = true, doc = "Entity prototype name"},
            position = {type = "position", required = true, doc = "Entity position"},
        },
        func = function(entity_name, position)
            return entity_lookup.get_fluid_connection_points(entity_name, position)
        end,
    },

    --- Get entity footprint (tiles covered)
    --- @param entity_name string Entity prototype name
    --- @param position table Entity position {x, y}
    --- @param direction number|nil Entity direction
    --- @return table {tiles: array, bounding_box: table, center: position}
    get_entity_footprint = {
        category = "info",
        doc = [[Get the tiles covered by an entity's footprint.
Returns array of tile positions and the bounding box.
Accounts for entity direction for asymmetric entities.]],
        paramspec = {
            _param_order = {"entity_name", "position", "direction"},
            entity_name = {type = "string", required = true, doc = "Entity prototype name"},
            position = {type = "position", required = true, doc = "Entity center position"},
            direction = {type = "number", default = nil, doc = "Entity direction"},
        },
        func = function(entity_name, position, direction)
            return geometry.get_entity_footprint(entity_name, position, direction)
        end,
    },
}

-- ============================================================================
-- PUBLIC API
-- ============================================================================

--- Build the remote interface table from method definitions
--- @return table Interface with method functions
function M.get_interface()
    local interface = {}

    for method_name, meta in pairs(INTERFACE_METHODS) do
        interface[method_name] = function(...)
            local args = ...
            -- Check if called with single table argument (RCON pattern)
            if type(args) == "table" and select("#", ...) == 1 and meta.paramspec and meta.paramspec._param_order then
                local ordered_args = {}
                for _, key in ipairs(meta.paramspec._param_order) do
                    table.insert(ordered_args, args[key])
                end
                return meta.func(table.unpack(ordered_args))
            end
            -- Fallback to positional arguments
            return meta.func(...)
        end
    end

    return interface
end

--- Export interface schema for documentation/bindings
--- @return table Schema with methods, params, returns
function M.export_interface_schema()
    local schema = {
        version = "1.0.0",
        description = "FactoryVerse Placement Hints Remote Interface",
        methods = {},
    }

    for method_name, meta in pairs(INTERFACE_METHODS) do
        local params = {}
        for _, param_name in ipairs(meta.paramspec._param_order or {}) do
            local param_spec = meta.paramspec[param_name]
            if param_spec then
                params[param_name] = {
                    type = param_spec.type,
                    required = param_spec.required or false,
                    default = param_spec.default,
                    doc = param_spec.doc,
                }
            end
        end

        schema.methods[method_name] = {
            category = meta.category,
            doc = meta.doc,
            params = params,
            param_order = meta.paramspec._param_order,
        }
    end

    return schema
end

return M
