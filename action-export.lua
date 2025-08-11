---Action Export for Lua Language Server
---Custom documentation script that extracts Factorio action specifications
---Implements the required lua-language-server export API

-- Import required modules from lua-language-server
local ws       = require 'workspace'
local vm       = require 'vm'
local guide    = require 'parser.guide'
local getDesc  = require 'core.hover.description'
local getLabel = require 'core.hover.label'
local jsonb    = require 'json-beautify'
local util     = require 'utility'
local markdown = require 'provider.markdown'
local fs       = require 'bee.filesystem'
local furi     = require 'file-uri'

local export = {}

-- Configuration for action detection
local ACTION_MARKER = "---@action:"
local ACTIONS_PATH_PATTERN = "actions/"

-- Debug logging helper
local function debug_log(message)
    print("[ACTION-EXPORT] " .. message)
end

debug_log("Custom action export script loaded!")

-- Helper function to check if a source represents an action
local function is_action_source(source)
    if not source then return false end
    
    -- Get file URI and check if it's in actions directory
    local uri = guide.getUri(source)
    if uri then
        local file_path = export.getLocalPath(uri)
        if file_path and string.find(file_path, ACTIONS_PATH_PATTERN) then
            return true
        end
    end
    
    return false
end

-- Helper function to extract action name from file path
local function get_action_name_from_path(file_path)
    if not file_path then return nil end
    local name = string.match(file_path, "actions/([^/]+)%.lua$")
    return name
end

---Required API: Get local path relative to documentation root
function export.getLocalPath(uri)
    local file_canonical = fs.canonical(furi.decode(uri)):string()
    
    -- DOC should be set by the language server, but fallback to workspace root
    local doc_path = DOC or ws.rootUri or ""
    if doc_path == "" then
        -- If no DOC is available, just return the decoded URI path
        return furi.decode(uri):string()
    end
    
    local doc_canonical = fs.canonical(fs.path(doc_path)):string()
    local relativePath = fs.relative(file_canonical, doc_canonical):string()
    if relativePath == "" or relativePath:sub(1, 2) == '..' then
        -- not under project directory
        return '[FOREIGN] ' .. file_canonical
    end
    return relativePath
end

---Required API: Position wrapper
function export.positionOf(rowcol)
    return type(rowcol) == 'table' and guide.positionOf(rowcol[1], rowcol[2]) or -1
end

---Required API: Sort documentation entries (focusing on actions first)
function export.sortDoc(a, b)
    -- Prioritize actions over non-actions
    local a_is_action = a.file and string.find(a.file, ACTIONS_PATH_PATTERN)
    local b_is_action = b.file and string.find(b.file, ACTIONS_PATH_PATTERN)
    
    if a_is_action and not b_is_action then
        return true
    elseif not a_is_action and b_is_action then
        return false
    end
    
    -- For actions, sort by action name
    if a_is_action and b_is_action then
        local a_action = get_action_name_from_path(a.file)
        local b_action = get_action_name_from_path(b.file)
        if a_action and b_action then
            return a_action < b_action
        end
    end
    
    -- Default sorting
    if a.name ~= b.name then
        return a.name < b.name
    end
    
    if a.file ~= b.file then
        return a.file < b.file
    end
    
    return export.positionOf(a.start) < export.positionOf(b.start)
end

---Required API: Document object processor with action filtering
function export.documentObject(source, has_seen)
    --is this a primative type? then we dont need to process it.
    if type(source) ~= 'table' then return source end

    --set up/check recursion
    if not has_seen then has_seen = {} end
    if has_seen[source] then
        return nil
    end
    has_seen[source] = true

    --is this an array type? then process each array item and collect it
    if (#source > 0 and next(source, #source) == nil) then
        local objs = {} --make a pure numerical array
        for i, child in ipairs(source) do
            objs[i] = export.documentObject(child, has_seen)
        end
        return objs
    end

    --if neither, then this is a singular docUnion
    local obj = export.makeDocObject['INIT'](source, has_seen)

    --check if this source has a type (no type sources are usually autogen'd anon functions's return values that are not explicitly stated)
    if not obj.type then return obj end

    local res = export.makeDocObject[obj.type](source, obj, has_seen)
    if res == false then
        return nil
    end
    return res or obj
end

---Required API: Documentation object creation handlers
export.makeDocObject = setmetatable({}, {__index = function(t, k)
    return function()
        -- Default handler for unrecognized types
    end
end})

-- INIT handler - enhanced to detect actions
export.makeDocObject['INIT'] = function(source, has_seen)
    local ok, desc = pcall(getDesc, source)
    local rawok, rawdesc = pcall(getDesc, source, true)
    
    local obj = {
        type = source.cate or source.type,
        name = export.documentObject((source.getCodeName and source:getCodeName()) or source.name, has_seen),
        start = source.start and {guide.rowColOf(source.start)},
        finish = source.finish and {guide.rowColOf(source.finish)},
        types = export.documentObject(source.types, has_seen),
        view = vm.getInfer(source):view(ws.rootUri),
        desc = ok and desc or nil,
        rawdesc = rawok and rawdesc or nil,
        file = export.getLocalPath(guide.getUri(source))
    }
    
    -- Mark as action if in actions directory
    if obj.file and string.find(obj.file, ACTIONS_PATH_PATTERN) then
        obj.is_action = true
        obj.action_name = get_action_name_from_path(obj.file)
    end
    
    return obj
end

-- Function handler - enhanced for actions
export.makeDocObject['function'] = function(source, obj, has_seen)
    obj.args = export.documentObject(source.args, has_seen)
    obj.view = getLabel(source, source.parent.type == 'setmethod', 1)
    local _, _, max = vm.countReturnsOfFunction(source)
    if max > 0 then obj.returns = {} end
    for i = 1, max do
        obj.returns[i] = export.documentObject(vm.getReturnOfFunction(source, i), has_seen)
    end
end

-- Copy other handlers from the original export.lua as needed
export.makeDocObject['doc.alias'] = function(source, obj, has_seen) end
export.makeDocObject['doc.field'] = function(source, obj, has_seen)
    if source.field.type == 'doc.field.name' then
        obj.name = source.field[1]
    else
        obj.name = ('[%s]'):format(vm.getInfer(source.field):view(ws.rootUri))
    end
    obj.file = export.getLocalPath(guide.getUri(source))
    obj.extends = source.extends and export.documentObject(source.extends, has_seen)
    obj.async = vm.isAsync(source, true) and true or false
    obj.deprecated = vm.getDeprecated(source) and true or false
    obj.visible = vm.getVisibleType(source)
end

export.makeDocObject['doc.class'] = function(source, obj, has_seen)
    local extends = source.extends or source.value
    local field = source.field or source.method 
    obj.name = type(field) == 'table' and field[1] or nil
    obj.file = export.getLocalPath(guide.getUri(source))
    obj.extends = extends and export.documentObject(extends, has_seen)
    obj.async = vm.isAsync(source, true) and true or false
    obj.deprecated = vm.getDeprecated(source) and true or false
    obj.visible = vm.getVisibleType(source)
end

export.makeDocObject['local'] = function(source, obj, has_seen)
    obj.name = source[1]
end

export.makeDocObject['self'] = export.makeDocObject['local']
export.makeDocObject['setfield'] = export.makeDocObject['doc.class']
export.makeDocObject['setglobal'] = export.makeDocObject['doc.class']
export.makeDocObject['setindex'] = export.makeDocObject['doc.class']
export.makeDocObject['setmethod'] = export.makeDocObject['doc.class']

export.makeDocObject['tableindex'] = function(source, obj, has_seen)
    obj.name = source.index[1]
end

export.makeDocObject['type'] = function(source, obj, has_seen)
    if export.makeDocObject['variable'](source, obj, has_seen) == false then
        return false
    end
    obj.fields = {}
    vm.getClassFields(ws.rootUri, source, vm.ANY, function (next_source, mark)
        if next_source.type == 'doc.field'
        or next_source.type == 'setfield'
        or next_source.type == 'setmethod'
        or next_source.type == 'tableindex'
        then
            table.insert(obj.fields, export.documentObject(next_source, has_seen))
        end
    end)
    table.sort(obj.fields, export.sortDoc)
end

export.makeDocObject['variable'] = function(source, obj, has_seen)
    obj.defines = {}
    for _, set in ipairs(source:getSets(ws.rootUri)) do
        if set.type == 'setglobal'
        or set.type == 'setfield'
        or set.type == 'setmethod'
        or set.type == 'setindex'
        or set.type == 'doc.alias'
        or set.type == 'doc.class'
        then
            table.insert(obj.defines, export.documentObject(set, has_seen))
        end
    end
    if #obj.defines == 0 then return false end
    table.sort(obj.defines, export.sortDoc)
end

export.makeDocObject['doc.field.name'] = function(source, obj, has_seen)
    obj['[1]'] = export.documentObject(source[1], has_seen)
    obj.view = source[1]
end

export.makeDocObject['doc.type.arg.name'] = export.makeDocObject['doc.field.name']

export.makeDocObject['doc.type.function'] = function(source, obj, has_seen)
    obj.args = export.documentObject(source.args, has_seen)
    obj.returns = export.documentObject(source.returns, has_seen)
end

export.makeDocObject['doc.type.table'] = function(source, obj, has_seen)
    obj.fields = export.documentObject(source.fields, has_seen)
end

export.makeDocObject['funcargs'] = function(source, obj, has_seen)
    local objs = {} --make a pure numerical array
    for i, child in ipairs(source) do
        objs[i] = export.documentObject(child, has_seen)
    end
    return objs
end

export.makeDocObject['function.return'] = function(source, obj, has_seen)
    obj.desc = source.comment and getDesc(source.comment)
    obj.rawdesc = source.comment and getDesc(source.comment, true)
end

---Required API: Gather globals (filter to focus on actions)
function export.gatherGlobals()
    debug_log("gatherGlobals() called")
    local all_globals = vm.getAllGlobals()
    local globals = {}
    local action_count = 0
    
    -- Count total globals properly
    local total_count = 0
    for _ in pairs(all_globals) do
        total_count = total_count + 1
    end
    debug_log("Found " .. total_count .. " total globals")
    
    -- Include all globals but mark actions for later filtering
    for _, g in pairs(all_globals) do
        local is_action_related = false
        
        -- Check if this global is from an actions file
        if g:getSets() then
            for _, set in ipairs(g:getSets(ws.rootUri)) do
                local uri = guide.getUri(set)
                if uri then
                    local file_path = export.getLocalPath(uri)
                    if file_path and string.find(file_path, ACTIONS_PATH_PATTERN) then
                        is_action_related = true
                        action_count = action_count + 1
                        debug_log("Found action global in: " .. file_path)
                        break
                    end
                end
            end
        end
        
        -- Always include - we'll filter during documentation generation
        table.insert(globals, g)
    end
    
    debug_log("Found " .. action_count .. " action-related globals out of " .. #globals .. " total")
    return globals
end

---Required API: Create documentation from globals
function export.makeDocs(globals, callback)
    local docs = {}
    for i, global in ipairs(globals) do
        local doc = export.documentObject(global)
        if doc then
            table.insert(docs, doc)
        end
        callback(i, #globals)
    end
    
    -- Add configuration info
    local doc_path = DOC or ws.rootUri or ""
    docs[#docs+1] = {
        name = 'FactoryVerse Actions',
        type = 'factorio.actions',
        DOC = doc_path ~= "" and fs.canonical(fs.path(doc_path)):string() or "unknown",
        defines = {},
        fields = {}
    }
    
    table.sort(docs, export.sortDoc)
    return docs
end

---Required API: Serialize and export documentation
function export.serializeAndExport(docs, outputDir)
    debug_log("serializeAndExport() called with " .. #docs .. " docs, outputDir: " .. outputDir)
    
    -- Filter to only action-related docs for cleaner output
    local action_docs = {}
    for _, doc in ipairs(docs) do
        if doc.is_action or (doc.file and string.find(doc.file, ACTIONS_PATH_PATTERN)) then
            table.insert(action_docs, doc)
            debug_log("Including action doc: " .. (doc.name or "unnamed") .. " from " .. (doc.file or "unknown file"))
        end
    end
    
    debug_log("Filtered to " .. #action_docs .. " action-related docs")
    
    local jsonPath = outputDir .. '/doc.json'
    local mdPath = outputDir .. '/doc.md'

    -- Export filtered docs to JSON
    local old_jsonb_supportSparseArray = jsonb.supportSparseArray
    jsonb.supportSparseArray = true
    local jsonOk, jsonErr = util.saveFile(jsonPath, jsonb.beautify(action_docs))
    jsonb.supportSparseArray = old_jsonb_supportSparseArray

    -- Export to markdown (LLM-friendly format)
    local md = markdown()
    md:add('md', '# Factorio Actions Documentation')
    md:emptyLine()
    md:add('md', 'This document contains action specifications for LLM agents.')
    md:emptyLine()
    
    for _, doc in ipairs(action_docs) do
        if doc.action_name then
            md:add('md', '## Action: ' .. doc.action_name)
            md:emptyLine()
            
            if doc.desc then
                md:add('md', doc.desc)
                md:emptyLine()
            end
            
            if doc.view then
                md:add('lua', doc.view)
                md:emptyLine()
            end
            
            if doc.args then
                md:add('md', '### Parameters')
                for _, arg in ipairs(doc.args) do
                    if arg.name then
                        md:add('md', '- `' .. arg.name .. '`: ' .. (arg.view or 'unknown type'))
                        if arg.desc then
                            md:add('md', '  - ' .. arg.desc)
                        end
                    end
                end
                md:emptyLine()
            end
            
            if doc.returns then
                md:add('md', '### Returns')
                md:add('md', 'JSON response string')
                md:emptyLine()
            end
            
            md:splitLine()
        end
    end
    
    local mdOk, mdErr = util.saveFile(mdPath, md:string())

    --error checking save file
    if( not (jsonOk and mdOk) ) then
        return false, {jsonPath, mdPath}, {jsonErr, mdErr}
    end

    return true, {jsonPath, mdPath}
end

return export
