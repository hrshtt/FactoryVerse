--- Signals framework
--- Runtime-only (no prototypes): register signal schemas, subscribe per-namespace,
--- sample on tick, and publish via pluggable sinks (file / UDP). Designed to be
--- driven from control.lua by calling Signals.register_events() or by manually
--- forwarding on_tick to Signals.on_tick().
---@class SignalSchema
---@field id string              -- unique id, e.g. "player.position"
---@field version integer|nil    -- optional schema version
---@field extract fun(ctx: table): table  -- extractor returns the data payload
---@field describe fun(): table|nil       -- optional human/machine readable field spec
local Signals = {}

-- use the shared helpers table if present (project-specific); fall back to Factorio APIs
local helpers = _G.helpers or {}
helpers.table_to_json = helpers.table_to_json or function(tbl) return game.table_to_json(tbl) end
helpers.json_to_table = helpers.json_to_table or function(str) return game.json_to_table(str) end
helpers.write_file = helpers.write_file or function(path, data, append)
    game.write_file(path, data, append)
end

-- optional UDP helpers (require running with --enable-lua-udp and a forwarder)
-- if unavailable, UDP sink will no-op with a log line
local has_udp = type(helpers.send_udp) == "function"

-- internal -------------------------------------------------------------------
local function _ensure_global()
    global.signals = global.signals or {
        enabled = true,
        seq = 0,
        -- schemas: [schema_id] = schema
        schemas = {},
        -- subs: [namespace] = { [sub_id] = subscription }
        subs = {},
        -- sinks: [sink_name] = function(namespace, schema_id, json_line, opts)
        sinks = {},
    }
end

local function _next_seq()
    global.signals.seq = (global.signals.seq or 0) + 1
    return global.signals.seq
end

local function _now()
    return game and game.tick or 0
end

local function _get_sink(name)
    _ensure_global()
    return global.signals.sinks[name]
end

local function _log(msg)
    if log then log(msg) end
end

-- sinks ----------------------------------------------------------------------
-- file sink: writes JSONL per-namespace under script-output
local function _sink_file(namespace, schema_id, json_line, opts)
    local dir = (opts and opts.dir) or "script-output/factoryverse/signals"
    local file = dir .. "/" .. namespace .. ".jsonl"
    helpers.write_file(file, json_line .. "\n", true)
end

-- udp sink: sends each JSON line as a datagram to a local forwarder
local function _sink_udp(namespace, schema_id, json_line, opts)
    if not has_udp then
        _log("[signals] UDP sink requested but helpers.send_udp is unavailable; skipping")
        return
    end
    local host = (opts and opts.host) or "127.0.0.1"
    local port = (opts and opts.port) or 49555
    local ok, err = pcall(function()
        helpers.send_udp(host, port, json_line)
    end)
    if not ok then _log("[signals] UDP send failed: " .. tostring(err)) end
end

-- rcon sink: useful for quick debugging in headless
local function _sink_rcon(namespace, schema_id, json_line, _)
    if rcon and rcon.print then
        pcall(function() rcon.print(json_line) end)
    else
        _log("[signals] rcon sink unavailable in this runtime")
    end
end

-- public API: lifecycle ------------------------------------------------------
function Signals.init()
    _ensure_global()
    -- register built-in sinks (can be overridden)
    global.signals.sinks["file"] = _sink_file
    global.signals.sinks["udp"]  = _sink_udp
    global.signals.sinks["rcon"] = _sink_rcon
end

function Signals.on_load()
    -- nothing special; state lives in global
end

function Signals.register_events()
    -- Install a lightweight on_tick scheduler. If your mod already centralizes
    -- on_tick, you can instead call Signals.on_tick() from your own handler and
    -- avoid registering here.
    script.on_event(defines.events.on_tick, Signals.on_tick)
end

-- public API: schemas --------------------------------------------------------
---Register a signal schema
---@param schema SignalSchema
function Signals.register_schema(schema)
    _ensure_global()
    assert(type(schema) == "table", "schema must be a table")
    assert(type(schema.id) == "string" and schema.id ~= "", "schema.id must be a non-empty string")
    assert(type(schema.extract) == "function", "schema.extract(ctx) function required")
    global.signals.schemas[schema.id] = schema
end

function Signals.has_schema(id)
    _ensure_global()
    return global.signals.schemas[id] ~= nil
end

function Signals.schemas()
    _ensure_global()
    return global.signals.schemas
end

-- public API: subscriptions --------------------------------------------------
-- A subscription samples one schema on a cadence and publishes to a sink.
-- sub fields: { id, namespace, schema_id, every, offset, sink, sink_opts, last }

local function _ns_bucket(namespace)
    _ensure_global()
    global.signals.subs[namespace] = global.signals.subs[namespace] or {}
    return global.signals.subs[namespace]
end

---Subscribe to a schema for a given namespace
---@param namespace string                     -- logical namespace (e.g. "force:player-1")
---@param schema_id string
---@param opts table|nil                -- { every=60, offset=0, sink="udp"|"file"|..., sink_opts={...}, meta={...} }
---@return integer sub_id
function Signals.subscribe(namespace, schema_id, opts)
    _ensure_global()
    assert(Signals.has_schema(schema_id), "unknown schema: " .. tostring(schema_id))
    opts = opts or {}
    local every = math.max(1, tonumber(opts.every or 60) or 60)
    local offset = tonumber(opts.offset or 0) or 0
    local sink = opts.sink or "file"
    assert(_get_sink(sink), "unknown sink: " .. tostring(sink))

    local bucket = _ns_bucket(namespace)
    local id = _next_seq()
    bucket[id] = {
        id = id,
        namespace = namespace,
        schema_id = schema_id,
        every = every,
        offset = offset % every,
        sink = sink,
        sink_opts = opts.sink_opts or {},
        meta = opts.meta or {},
        last = nil,
    }
    return id
end

---Unsubscribe by id
function Signals.unsubscribe(namespace, sub_id)
    local bucket = _ns_bucket(namespace)
    bucket[sub_id] = nil
end

function Signals.unsubscribe_all(namespace)
    if global.signals.subs[namespace] then
        global.signals.subs[namespace] = {}
    end
end

function Signals.subscriptions(namespace)
    return _ns_bucket(namespace)
end

-- sampling & publishing ------------------------------------------------------
local function _build_ctx(namespace)
    -- callers can encode the namespace however they like. Here we expose a
    -- convenient structured ctx inferred from common patterns: "force:<name>",
    -- "surface:<name>", or custom strings.
    local ctx = { namespace = namespace, tick = _now() }
    if namespace:sub(1, 6) == "force:" then
        local fname = namespace:sub(7)
        ctx.force = game.forces[fname]
    elseif namespace:sub(1, 8) == "surface:" then
        local sname = namespace:sub(9)
        ctx.surface = game.surfaces[sname]
    end
    return ctx
end

local function _publish(sub, payload)
    local envelope = {
        type = "signal",
        schema = sub.schema_id,
        namespace = sub.namespace,
        seq = _next_seq(),
        tick = _now(),
        meta = sub.meta,
        data = payload,
    }
    local line = helpers.table_to_json(envelope)
    local sink_fn = _get_sink(sub.sink)
    if sink_fn then
        sink_fn(sub.namespace, sub.schema_id, line, sub.sink_opts)
    end
end

local function _sample_once(sub)
    local schema = global.signals.schemas[sub.schema_id]
    if not schema then return end
    local ok, payload = pcall(schema.extract, _build_ctx(sub.namespace))
    if ok then
        _publish(sub, payload)
    else
        _log("[signals] extractor failed for " .. sub.schema_id .. ": " .. tostring(payload))
    end
end

function Signals.flush(namespace)
    -- Force sample all subs for a namespace immediately
    for _, sub in pairs(_ns_bucket(namespace)) do
        _sample_once(sub)
        sub.last = _now()
    end
end

-- tick scheduler: cheap; respects per-sub cadence and offset
function Signals.on_tick(event)
    if not global.signals or not global.signals.enabled then return end
    local tick = event and event.tick or _now()
    for namespace, subs in pairs(global.signals.subs) do
        for _, sub in pairs(subs) do
            if (tick + sub.offset) % sub.every == 0 then
                _sample_once(sub)
                sub.last = tick
            end
        end
    end
end

-- optional: built-in example schemas (not auto-registered) -------------------
-- Call Signals.register_builtin() if you want these.
local _builtin = {}

-- Minimal heartbeat useful for wiring pipelines end-to-end
_builtin["debug.heartbeat"] = {
    id = "debug.heartbeat",
    version = 1,
    extract = function(ctx)
        return {
            tick = ctx.tick,
            namespace = ctx.namespace,
            surface = ctx.surface and ctx.surface.name or nil,
            force = ctx.force and ctx.force.name or nil,
        }
    end,
    describe = function()
        return {
            fields = {
                { name = "tick",    type = "uint" },
                { name = "namespace",      type = "string" },
                { name = "surface", type = "string?" },
                { name = "force",   type = "string?" },
            }
        }
    end,
}

-- Example: simple force-wide production statistics snapshot (lightweight)
_builtin["force.production"] = {
    id = "force.production",
    version = 1,
    extract = function(ctx)
        if not ctx.force then return { error = "no_force" } end
        local p = ctx.force.item_production_statistics
        -- Return top-N recent items by input count; keep tiny to avoid perf issues
        local entries, out = p.input_counts, {}
        local n = 0
        for name, count in pairs(entries) do
            n = n + 1
            if n > 10 then break end
            out[#out + 1] = { item = name, produced = count }
        end
        return { force = ctx.force.name, top = out }
    end,
}

function Signals.register_builtin()
    for _, schema in pairs(_builtin) do
        Signals.register_schema(schema)
    end
end

return Signals
