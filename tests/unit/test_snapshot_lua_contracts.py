"""Phase 0B (2026-08-29): the snapshot pipeline stops shipping fabrications and
volatile state, and subscribes to every geometry-changing engine event.

These are text-level contracts over the Lua sources (no engine needed). Each one
pins a defect that was verified in the tree on 2026-08-28 and repaired here:

- TRANSPORT_CONNECTIVITY_PLAN §8.6: five geometry-changing events were never
  registered, so a derived view over the map model was a floor that lies.
- §8.1: pipe flow direction was fabricated from ``dx > 0``.
- §8.2 / API §4.6: items on belts and stored belt adjacency rode in ``raw_data``.
- NOTIFICATIONS census: a cross-mod ``require`` of EntityInterface minted a dead
  pair of event IDs in fv_snapshot's Lua state; ``Error.lua`` had no ``return``;
  four ``send_*`` functions and five ``action_*`` constructors had no caller.

Every assertion first proves the thing it inspects was found (non-vacuous).
What these cannot prove: that the handlers behave in-engine. That needs a live
instance and belongs in tests/live.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SNAPSHOT = REPO / "src" / "fv_snapshot"
AGENT = REPO / "src" / "fv_embodied_agent"
ENTITIES = SNAPSHOT / "game_state" / "Entities.lua"
SERIALIZE = AGENT / "utils" / "serialize.lua"
ENTITY_INTERFACE = AGENT / "game_state" / "EntityInterface.lua"


def _events_block() -> str:
    text = ENTITIES.read_text()
    fn = text.index("function M._build_disk_write_snapshot")
    start = text.index("local events = {", fn)
    end = text.index("\n    }", start)
    return text[start:end]


def test_geometry_changing_engine_events_are_registered():
    block = _events_block()
    registered = re.findall(r"\[defines\.events\.(\w+)\]", block)
    assert len(registered) >= 8, registered
    for name in (
        "on_player_flipped_entity",
        "script_raised_revive",
        "on_robot_built_entity",
        "on_entity_cloned",
        "script_raised_teleported",
    ):
        assert name in registered, f"{name} not subscribed"


def test_cloned_and_teleported_use_the_spec_fields():
    text = ENTITIES.read_text()
    cloned = text[text.index("local function _on_entity_cloned"):]
    cloned = cloned[: cloned.index("\nend")]
    assert "event.destination" in cloned
    tele = text[text.index("local function _on_entity_teleported"):]
    tele = tele[: tele.index("\nend")]
    assert "event.old_position" in tele
    assert "make_remove_operation" in tele and "write_entity_snapshot" in tele


def test_snapshot_never_subscribes_to_entity_interface_event_ids():
    text = ENTITIES.read_text()
    assert "EntityInterface:new(" in text  # the admin facade still needs the require
    assert not re.search(r"events\[EntityInterface\.on_", text)
    ei = ENTITY_INTERFACE.read_text()
    guard = ei.index('if script.mod_name == "fv_embodied_agent" then')
    gen = [m.start() for m in re.finditer(r"script\.generate_event_name\(\)", ei)]
    assert len(gen) == 2 and all(g > guard for g in gen)


def _strip_lua_comments(text: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines())


def test_serializer_emits_no_volatile_or_fabricated_keys():
    text = _strip_lua_comments(SERIALIZE.read_text())
    assert "_serialize_belt_data" in text and "_serialize_pipe_data" in text
    for key in ("item_lines", "belt_neighbours", "pipe_neighbours", "get_transport_line("):
        assert key not in text, key
    assert "dx > 0 or dy > 0" not in text
    assert "get_pipe_connections" in text
    assert "belt_to_ground_type" in text  # TRANSPORT §2.2 stays


def test_error_lua_is_gone_from_both_mods():
    assert not (SNAPSHOT / "utils" / "Error.lua").exists()
    assert not (AGENT / "utils" / "Error.lua").exists()
    lua_files = list(SNAPSHOT.rglob("*.lua"))
    assert lua_files
    for f in lua_files:
        assert 'require("utils.Error")' not in f.read_text(), f


def test_dead_senders_are_gone():
    snap = (SNAPSHOT / "utils" / "snapshot.lua").read_text()
    payloads = (SNAPSHOT / "utils" / "udp_payloads.lua").read_text()
    assert "function M.send_udp_notification" in snap  # the live sender survives
    for fn in (
        "send_action_completion_udp",
        "send_entity_operation_udp",
        "send_chunk_init_complete_udp",
        "send_file_event_udp",
    ):
        assert fn not in snap, fn
    for fn in (
        "action_start",
        "action_progress",
        "action_completed",
        "action_cancelled",
        "action_queued",
        "M.send_action(",
    ):
        assert fn not in payloads, fn
    assert "function M.send_entity_operation" in payloads


# ---------------------------------------------------------------------------
# Phase 1B (2026-08-29): the snapshot boot contract — TRANSPORT §13.
# A world charted before the mod existed must be ingested at boot, and the
# phase machine must not report a healthy MAINTENANCE over a world it never
# looked at. Text contracts here; the numbers live in
# tests/live/test_snapshot_boot_contract.py.
# ---------------------------------------------------------------------------

MAP = SNAPSHOT / "game_state" / "Map.lua"
CONTROL = SNAPSHOT / "control.lua"


def test_boot_is_the_single_storage_writable_lifecycle_entry():
    control = CONTROL.read_text()
    on_init = control[control.index("script.on_init("):control.index("script.on_load(")]
    on_conf = control[control.index("script.on_configuration_changed("):]
    assert 'Map.boot("on_init")' in on_init
    assert 'Map.boot("on_configuration_changed")' in on_conf
    # The old two-step (init_storage + init) must not survive beside boot().
    assert "Map.init_storage()" not in on_init and "Map.init_storage()" not in on_conf
    m = MAP.read_text()
    boot = m[m.index("function M.boot(reason)"):]
    boot = boot[:boot.index("\nend")]
    assert "M.init_storage()" in boot and "M.boot_reconcile_charted_chunks(reason)" in boot


def test_boot_pass_walks_generated_chunks_and_filters_by_charted_force():
    m = MAP.read_text()
    fn = m[m.index("function M.boot_reconcile_charted_chunks"):m.index("function M.get_boot_report")]
    assert "surface.get_chunks()" in fn
    assert "is_chunk_charted(surface" in fn
    assert "forces.get_tracked_forces()" in fn
    assert 'register_charted_chunk(chunk.x, chunk.y, "boot"' in fn


def test_chart_handlers_and_boot_share_one_registration_path():
    m = MAP.read_text()
    calls = re.findall(r"register_charted_chunk\(([^)]*)\)", m)
    origins = {re.search(r'"(player|agent|boot)"', c).group(1) for c in calls if re.search(r'"(player|agent|boot)"', c)}
    assert origins == {"player", "agent", "boot"}, origins


def test_has_tracked_entities_has_exactly_one_writer():
    m = MAP.read_text()
    writers = [ln for ln in m.splitlines() if re.search(r"\.has_tracked_entities\s*=", ln)]
    assert len(writers) == 1, writers
    # ...and that writer is called from the snapshot-complete path too, so a
    # forced or boot-time snapshot flags the chunk.
    complete = m[m.index("local function phase_complete"):m.index("function M._on_tick_snapshot_chunks")]
    assert "M.refresh_chunk_entity_flag(chunk_x, chunk_y)" in complete


def test_phase_machine_distinguishes_empty_from_maintenance():
    m = MAP.read_text()
    assert 'EMPTY = "EMPTY"' in m
    trans = m[m.index("local function transition_to_maintenance"):m.index("enqueue_chunk_for_snapshot = function")]
    assert "chunks_considered" in trans and "SystemPhase.EMPTY" in trans
    # Nothing may still gate on MAINTENANCE alone where EMPTY is also quiescent.
    assert "== SystemPhase.MAINTENANCE then" not in m
    assert "get_boot_report = M.get_boot_report" in m


def test_dead_status_walk_is_gone():
    e = ENTITIES.read_text()
    for name in ("track_all_charted_chunk_entity_status", "track_chunk_entity_status", "track_entity_status"):
        assert name not in e, name
    assert "function M.dump_status_to_disk()" in e
    assert "function M.collect_all_statuses_for_dump()" in e
    control = CONTROL.read_text()
    assert "Entities.dump_status_to_disk()" in control
    assert 'get_system_phase() ~= "INITIAL_SNAPSHOTTING"' in control
