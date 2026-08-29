--- vocabulary.lua — the names that may appear on the UDP wire.
---
--- This file is data. It contains no code, no requires, and nothing that
--- runs at load. Python parses it with a regex
--- (tests/unit/test_vocabulary_parity.py); a section may nest one level.
---
--- Two blocks, deliberately separate so a reader cannot mistake one for
--- the other:
---
---   wire    What is on the wire TODAY, keyed by the field the string sits
---           in. Every name here is a literal in one of the two emitting
---           mods, and the parity test derives the same sets from the Lua
---           source and asserts equality. Nothing here is aspirational.
---
---   target  The stream/name layout NOTIFICATIONS_PRIMITIVE_DEFERRED.md
---           ("The design") intends. Names in target.not_on_wire exist on
---           no wire and in no Lua string today; the test asserts exactly
---           that, and asserts every other target name IS a wire literal.
---           When stream.lua lands for a stream, its names move from
---           not_on_wire into wire and the corresponding assertion flips.
---           The `turn` stream landed 2026-08-29: wire.turn == target.turn.
---
--- Gate 5 of the plan is the set of tests over this file. Python-side legs
--- that do not yet agree with `wire` are strict xfails naming the gap.

return {
    wire = {
        -- The top-level envelope field on the action port (`action`) and the
        -- snapshot port (the rest). The per-agent `turn` port carries
        -- stream.lua envelopes whose event_type ∈ wire.turn below.
        event_type = {
            action = true,               -- fv_embodied_agent/utils/udp.lua
            entity_operation = true,     -- fv_snapshot/utils/udp_payloads.lua
            file_io = true,
            snapshot_state = true,
            system_phase_changed = true,
            chunk_charted = true,
            chunk_init_complete = true,
        },

        -- event_type on the per-agent `turn` stream (utils/stream.lua
        -- envelope). Emitted from game_state/Notifications.lua; the stream
        -- refuses anything else. Python re-keys it as notification_type.
        turn = {
            research_queued = true,
            research_started = true,
            research_finished = true,
            research_cancelled = true,
            research_moved = true,
            research_reversed = true,
            crafting_finished = true,
        },

        -- `action` field on event_type == "action" (the body verb).
        action = {
            walk_to = true,
            mine_resource = true,
            craft_enqueue = true,
            craft_dequeue = true,
            place_entity = true,
            pickup_entity = true,
            rotate_entity = true,
            set_entity_recipe = true,
            set_entity_filter = true,
            set_inventory_limit = true,
            get_inventory_item = true,
            put_inventory_item = true,
        },

        -- `status` field on event_type == "action". udp.lua also defines a
        -- "progress" constant; nothing emits it, so it is not listed.
        status = {
            queued = true,
            completed = true,
            cancelled = true,
            failed = true,
        },

        -- `op` field on event_type == "entity_operation". Ghosts ride the
        -- same ops with `is_ghost = true`; there is no ghost_operation.
        op = {
            created = true,
            destroyed = true,
            rotated = true,
            configuration_changed = true,
        },

        -- `operation` field on event_type == "file_io".
        file_op = {
            written = true,
            appended = true,
        },

        -- `file_type` field on event_type == "file_io".
        file_type = {
            resource = true,
            water = true,
            trees_rocks = true,
            power_statistics = true,
            power_networks = true,
            entity_status = true,
            agent_production_statistics = true,
            agent_crafting_statistics = true,
            agent_mining_statistics = true,
        },
    },

    target = {
        -- Per-agent stream, read per call by the action listener.
        -- event_type becomes the verb; data.status ∈ wire.status.
        action = {
            walk_to = true,
            mine_resource = true,
            craft_enqueue = true,
            craft_dequeue = true,
            place_entity = true,
            pickup_entity = true,
            rotate_entity = true,
            set_entity_recipe = true,
            set_entity_filter = true,
            set_inventory_limit = true,
            get_inventory_item = true,
            put_inventory_item = true,
        },

        -- Per-agent stream, drained by the turn into the turn report.
        turn = {
            research_queued = true,
            research_started = true,
            research_finished = true,
            research_cancelled = true,
            research_moved = true,
            research_reversed = true,
            crafting_finished = true,
        },

        -- Mod-wide stream, read continuously by the sync service.
        -- entity_*/ghost_* replace entity_operation + op + is_ghost.
        entities = {
            entity_created = true,
            entity_destroyed = true,
            entity_rotated = true,
            entity_configuration_changed = true,
            ghost_created = true,
            ghost_destroyed = true,
            ghost_rotated = true,
            ghost_configuration_changed = true,
            resource_destroyed = true,
            chunk_init_complete = true,
            snapshot_state = true,
            system_phase_changed = true,
            chunk_charted = true,
        },

        -- Mod-wide stream: a hint that a file changed.
        -- Replaces file_io + operation. data.file_type ∈ wire.file_type.
        files = {
            file_written = true,
            file_appended = true,
        },

        -- Target names that exist on no wire and in no Lua string today.
        not_on_wire = {
            entity_created = true,
            entity_destroyed = true,
            entity_rotated = true,
            entity_configuration_changed = true,
            ghost_created = true,
            ghost_destroyed = true,
            ghost_rotated = true,
            ghost_configuration_changed = true,
            resource_destroyed = true,
            file_written = true,
            file_appended = true,
        },
    },
}
