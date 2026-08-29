--- stream.lua — the notification stream unit (NOTIFICATIONS_PRIMITIVE_DEFERRED.md, "The unit").
---
--- Side-effect-free at load: nothing here touches `storage`, `script.*` or
--- `remote.*` at module level. Each owner mod hands a stream a slot in its
--- own `storage`; tracking state (epoch, seq) lives in that slot, and the
--- per-tick buffer lives in a module-local table keyed by the slot, so it
--- never enters the save.
---
--- The unit owns tracking only: port, epoch, sequence, tick, event_type.
--- `data` passes through untouched; payload construction stays beside the
--- handler that knows its fields.
---
--- Envelope on the wire and on disk (same bytes, stamped once):
---   {"epoch":1,"seq":4382,"tick":36480,"event_type":"crafting_finished","data":{…}}
---
--- Rules the unit enforces:
---   * send-after-write: the file line is appended before the datagram leaves
---   * one flush order per stream, one blocking write per stream per tick
---   * a sequence never exists without an epoch
---   * an event_type outside the stream's vocabulary is refused at emit

local M = {}

--- Largest JSON envelope that is sent as a datagram. Anything larger goes
--- out envelope-only with `in_file = true`; the file has the record.
---
--- Gate 1, measured 2026-08-29 on factoriotools/factorio:2.0.76 (arm64, box64)
--- through the alpine/socat forwarder to the host, by
--- tests/live/test_turn_stream.py::test_gate_1_datagram_ceiling_measured:
--- a research_moved envelope with 8,080 filler bytes (~8,205 JSON bytes)
--- arrives intact; 8,100 filler bytes (~8,225 JSON bytes) never arrives.
--- helpers.send_udp therefore drops anything past ~8 KiB silently. 8000 is
--- ~200 bytes under the measured edge. Direct-to-client (no socat) was not
--- measured separately.
M.MAX_DATAGRAM_BYTES = 8000

-- Per-tick buffers, keyed by slot table identity. Weak keys so a destroyed
-- agent's slot does not pin its buffer.
local buffers = setmetatable({}, { __mode = "k" })

--- Bind a stream handle to its slot.
--- @param slot table The owner's storage sub-table for this stream (persisted).
--- @param port_source number|string A port number (per-agent streams) or a
---        mod setting name (mod-wide streams) resolved at send time.
--- @param vocabulary table Set of legal event_type names {name = true, ...}.
--- @param file string script-output path for the stream's JSONL file.
--- @return table stream handle (not persisted; rebuild with open after load)
function M.open(slot, port_source, vocabulary, file)
    assert(type(slot) == "table", "stream.open: slot must be a table")
    assert(type(vocabulary) == "table", "stream.open: vocabulary must be a table")
    assert(type(file) == "string" and #file > 0, "stream.open: file must be a path")
    if slot.epoch == nil then slot.epoch = 0 end
    if slot.seq == nil then slot.seq = 0 end
    return {
        slot = slot,
        port_source = port_source,
        vocabulary = vocabulary,
        file = file,
    }
end

--- Resolve the port for a stream at send time.
--- @param stream table
--- @return number|nil
function M.port(stream)
    local src = stream.port_source
    if type(src) == "number" then
        return src
    end
    if type(src) == "string" and settings and settings.global and settings.global[src] then
        return tonumber(settings.global[src].value)
    end
    return nil
end

--- Queue an event for this tick's flush. Never sends.
--- @param stream table
--- @param event_type string Must be in the stream's vocabulary.
--- @param data table|nil
--- @return boolean accepted
function M.emit(stream, event_type, data)
    if not stream.vocabulary[event_type] then
        log(string.format("[stream] refused event_type %q (not in vocabulary for %s)",
            tostring(event_type), stream.file))
        return false
    end
    local buf = buffers[stream.slot]
    if not buf then
        buf = {}
        buffers[stream.slot] = buf
    end
    buf[#buf + 1] = { event_type = event_type, data = data or {} }
    return true
end

--- Number of items waiting for flush (for tests and probes).
function M.pending(stream)
    local buf = buffers[stream.slot]
    return buf and #buf or 0
end

--- Stamp, write, then send everything emitted since the last flush.
--- Call once per tick from the owner's on_tick.
--- @param stream table
--- @return number items flushed
function M.flush(stream)
    local buf = buffers[stream.slot]
    if not buf or #buf == 0 then
        return 0
    end
    buffers[stream.slot] = nil

    local slot = stream.slot
    local tick = game.tick
    local port = M.port(stream)
    local lines = {}
    local datagrams = {}

    for i = 1, #buf do
        local item = buf[i]
        slot.seq = slot.seq + 1
        local envelope = {
            epoch = slot.epoch,
            seq = slot.seq,
            tick = tick,
            event_type = item.event_type,
            data = item.data,
        }
        local json = helpers.table_to_json(envelope)
        lines[#lines + 1] = json
        if #json > M.MAX_DATAGRAM_BYTES then
            datagrams[#datagrams + 1] = helpers.table_to_json({
                epoch = slot.epoch,
                seq = slot.seq,
                tick = tick,
                event_type = item.event_type,
                in_file = true,
            })
        else
            datagrams[#datagrams + 1] = json
        end
    end

    -- One blocking write per stream per tick, before any datagram.
    helpers.write_file(stream.file, table.concat(lines, "\n") .. "\n", true)

    if port then
        for i = 1, #datagrams do
            helpers.send_udp(port, datagrams[i])
        end
    else
        log(string.format("[stream] no port for %s; %d items written to file only",
            stream.file, #datagrams))
    end

    return #buf
end

--- Start a new epoch: counter and file reset together.
--- Only from on_init / on_configuration_changed — never on_load.
--- @param stream table
function M.new_epoch(stream)
    local slot = stream.slot
    slot.epoch = (slot.epoch or 0) + 1
    slot.seq = 0
    buffers[slot] = nil
    helpers.write_file(stream.file, "", false)
end

--- What Python asks for at attach and after any gap.
--- @param stream table
--- @return table {port, epoch, seq, tick}
function M.state(stream)
    return {
        port = M.port(stream),
        epoch = stream.slot.epoch,
        seq = stream.slot.seq,
        tick = game.tick,
    }
end

return M
