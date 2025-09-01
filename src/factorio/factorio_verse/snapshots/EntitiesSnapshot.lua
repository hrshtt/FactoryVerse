local Snapshot = require "core.Snapshot"
local utils = require "utils"

---
--- EntitiesSnapshot (Scaffold)
---
--- Purpose: orchestrate a snapshot that exports SQL-friendly JSON tables for
---   - entities (machines worth reasoning about)
---   - power_domains (electric islands & burner/self domains)
---   - production_flows (aggregate outputs/inputs for selected products over windows)
---   - tags & entity_tags (LLM/user-defined spatial groupings)
---
--- This file intentionally contains **no heavy implementation**. It's a design/spec with
--- method decomposition, input/output contracts, and TODOs. We will wire real logic later.
---
--- Schema version for the JSON produced by this snapshotter
local SCHEMA_VERSION = "entities.snapshot.v0"

---@class EntitiesSnapshot: Snapshot
local EntitiesSnapshot = Snapshot:new()
EntitiesSnapshot.__index = EntitiesSnapshot

--\\ Public API /////////////////////////////////////////////////////////////////

--- Create a new snapshot instance.
---@return EntitiesSnapshot
function EntitiesSnapshot:new()
    local instance = Snapshot:new()
    setmetatable(instance, self)
    return instance
end

--- High-level orchestrator. Collects, aggregates, and emits JSON.
--- **No real work yet** — just contracts and call sequence.
---
---@param opts EntitiesSnapshotOptions
---@return EntitiesSnapshotResult result  -- paths, totals, debug info
function EntitiesSnapshot:take(opts)
    opts = self:_normalize_opts(opts)

    -- 1) Resolve surface/force, time, and build meta
    local meta = self:_build_meta(opts)

    -- 2) Collect base tables (stubs for now)
    local tags, entity_tags = self:_resolve_tags(opts)
    local entities = self:_collect_entities(opts)
    local power_domains = self:_derive_power_domains(opts, entities)
    local production_flows = self:_compute_production_flows(opts, entities, tags)

    -- 3) Assemble snapshot payload
    local payload = self:_assemble_payload(meta, entities, power_domains, production_flows, tags, entity_tags)

    -- 4) Validate shape (lightweight schema checks)
    self:_validate(payload)

    -- 5) Emit JSON (delegates to Snapshot base when we wire it)
    local file_path = self:_emit(opts, payload)

    -- 6) Optional debug overlays (no-op for now)
    self:_debug_render(opts, payload)

    return {
        snapshot_id = meta.snapshot_id,
        schema_version = SCHEMA_VERSION,
        file_path = file_path,
        totals = {
            entities = #payload.entities,
            power_domains = #payload.power_domains,
            production_flows = #payload.production_flows,
            tags = #payload.tags,
            entity_tags = #payload.entity_tags,
        }
    }
end

--\\ Contracts & Types //////////////////////////////////////////////////////////

---@class EntitiesSnapshotOptions
---@field surface LuaSurface|string|nil        -- default: current player surface or "nauvis"
---@field force LuaForce|string|nil           -- default: "player"
---@field scope "charted"|"visible"|"both"  -- default: "charted"
---@field area BoundingBox|nil                -- optional limit
---@field include_types string[]|nil          -- entity types to include
---@field include_names string[]|nil          -- entity names to include
---@field windows ("5s"|"1m"|"10m"|"1h")[]|nil  -- flow windows, default {"10m"}
---@field products_of_interest string[]|nil   -- item/fluids to report in production_flows
---@field tags TagSpec[]|nil                  -- user/LLM supplied spatial tags (see TagSpec)
---@field output_dir string|nil               -- where JSON is written; base class may provide default
---@field snapshot_id string|nil              -- override id; else auto
---@field compression "none"|"gzip"|nil     -- default: none

---@class EntitiesSnapshotResult
---@field snapshot_id string
---@field schema_version string
---@field file_path string|nil
---@field totals {entities:integer, power_domains:integer, production_flows:integer, tags:integer, entity_tags:integer}

---@class SnapshotMeta
---@field schema_version string
---@field factorio_version string
---@field force string
---@field tick integer
---@field created_at_utc string
---@field scope string
---@field area BoundingBox|nil
---@field windows string[]

---@class EntityRow
---@field snapshot_id string
---@field entity_id integer            -- unit_number
---@field name string
---@field type string
---@field position {x:integer, y:integer}
---@field force string
---@field power_kind "electric"|"burner"|"none"
---@field power_domain_id string|nil   -- "elec:<id>" or "burner:<entity_id>"
---@field status string|nil            -- defines.entity_status textual name
---@field recipe string|nil
---@field modules {name:string, count:integer}[]|nil
---@field beacons integer|nil
---@field crafting_progress number|nil
---@field energy_buffer integer|nil

---@class PowerDomainRow
---@field snapshot_id string
---@field power_domain_id string
---@field kind "electric"|"burner"
---@field electric_network_id integer|nil
---@field entity_id integer|nil          -- when kind==burner
---@field summary table|nil              -- optional {producers,consumers,accumulators,satisfaction,production_w}


---@class MiningSiteRow
---@field snapshot_id string
---@field patch_id string
---@field electric_network_id integer|nil
---@field entity_id integer|nil          -- when kind==burner
---@field summary table|nil              -- optional {producers,consumers,accumulators,satisfaction,production_w}

---@class ProductionFlowRow
---@field snapshot_id string
---@field flow_id string                 -- e.g., "pf:<product>:<window>:<scope>"
---@field product {item?:string, fluid?:string}
---@field window string
---@field scope {type:"surface"|"tag", surface?:string, tag_id?:string}
---@field output integer
---@field input integer
---@field net integer
---@field members integer[]              -- entity_ids believed involved
---@field notes string|nil

---@class TagSpec
---@field tag_id string
---@field label string
---@field parent_tag_id string|nil
---@field areas {min_cx:integer,min_cy:integer,max_cx:integer,max_cy:integer}[]
---@field notes string|nil

--\\ Private helpers (stubs) ///////////////////////////////////////////////////

---@param opts EntitiesSnapshotOptions
---@return EntitiesSnapshotOptions
function EntitiesSnapshot:_normalize_opts(opts)
    -- TODO: set sensible defaults; coerce surface/force to names
    return opts or {}
end

---@param opts EntitiesSnapshotOptions
---@return SnapshotMeta
function EntitiesSnapshot:_build_meta(opts)
    -- TODO: resolve factorio_version, surface name, force name, tick, created_at
    return {
        schema_version = SCHEMA_VERSION,
        factorio_version = "2.0.60",
        surface = "nauvis",
        force = "player",
        tick = 0,
        created_at_utc = "0000-00-00T00:00:00Z",
        scope = opts and opts.scope or "charted",
        area = opts and opts.area or nil,
        windows = (opts and opts.windows) or { "10m" }
    }
end

---@param opts EntitiesSnapshotOptions
---@return TagSpec[] tags, table entity_tags  -- entity_tags is a list of {tag_id, entity_id}
function EntitiesSnapshot:_resolve_tags(opts)
    -- TODO: project chunk-rectangles to world bbox, compute membership for entities (later)
    return opts and (opts.tags or {}) or {}, {}
end

---@param opts EntitiesSnapshotOptions
---@return EntityRow[]
function EntitiesSnapshot:_collect_entities(opts)
    -- TODO: walk charted/visible chunks; collect unit_number entities matching filters
    return {}
end

---@param opts EntitiesSnapshotOptions
---@param entities EntityRow[]
---@return PowerDomainRow[]
function EntitiesSnapshot:_derive_power_domains(opts, entities)
    -- TODO: group by electric_network_id; create burner:self domains; compute basic summaries
    return {}
end

---@param opts EntitiesSnapshotOptions
---@param entities EntityRow[]
---@param tags TagSpec[]
---@return ProductionFlowRow[]
function EntitiesSnapshot:_compute_production_flows(opts, entities, tags)
    -- TODO: query FlowStatistics for requested windows/products within scopes (surface or tag areas)
    return {}
end

---@param meta SnapshotMeta
---@param entities EntityRow[]
---@param power_domains PowerDomainRow[]
---@param production_flows ProductionFlowRow[]
---@param tags TagSpec[]
---@param entity_tags table
---@return table payload
function EntitiesSnapshot:_assemble_payload(meta, entities, power_domains, production_flows, tags, entity_tags)
    return {
        meta = meta,
        entities = entities or {},
        power_domains = power_domains or {},
        production_flows = production_flows or {},
        tags = tags or {},
        entity_tags = entity_tags or {}
    }
end

---@param payload table
function EntitiesSnapshot:_validate(payload)
    -- TODO: assert minimal keys and types; log warnings for big tables
    return true
end

---@param opts EntitiesSnapshotOptions
---@param payload table
---@return string|nil file_path
function EntitiesSnapshot:_emit(opts, payload)
    -- TODO: delegate to base Snapshot (e.g., self:write_json), respect compression/output_dir
    -- return absolute path (or nil in test mode)
    return nil
end

---@param opts EntitiesSnapshotOptions
---@param payload table
function EntitiesSnapshot:_debug_render(opts, payload)
    -- TODO: optional LuaRendering overlays (zones/tags/power islands)
end

return EntitiesSnapshot
