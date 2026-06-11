#!/usr/bin/env python
"""Comprehension battery v0 — fixture capture (docs/INFORMATION_SURFACES.md §5).

Runs against the loaded `attempt3-base-specimen` save. Renders each probe's
PAYLOAD through the real agent surfaces (entity.inspect(), remote_view.query)
so the model sees exactly what an agent session would see, and captures the
ENGINE TRUTH for scoring via independent raw RCON (no shared code with the
payload path).

Output: scripts/battery/fixtures/v0.json — one record per probe:
  {id, concept, question, payload, truth, scoring}

Read-only: creates/destroys nothing. Safe to re-run.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURES.mkdir(exist_ok=True)

from factorio_rcon import RCONClient  # noqa: E402

rcon = RCONClient("localhost", 27000, "factorio")


def lua(body: str) -> Any:
    out = rcon.send_command(
        "/c local ok,res=xpcall(function() " + body + " end,debug.traceback) "
        "if ok then rcon.print(helpers.table_to_json({__v=res})) "
        "else rcon.print(helpers.table_to_json({__lua_error=tostring(res)})) end"
    )
    d = json.loads(out)
    if isinstance(d, dict) and "__lua_error" in d:
        raise RuntimeError(d["__lua_error"][:500])
    return d.get("__v", d) if isinstance(d, dict) else d


def inspect_payload(env, name: str, x: float, y: float) -> str:
    """Render an entity's inspect() exactly as an agent print() would show it."""
    e = env.tier4.remote_view.get_entity(
        f"SELECT * FROM map_entity WHERE entity_name = '{name}' "
        f"AND ABS(position_x - {x}) < 0.8 AND ABS(position_y - {y}) < 0.8 LIMIT 1"
    )
    if e is None:
        raise RuntimeError(f"payload entity not found: {name} @ ({x},{y})")
    insp = e.inspect()
    # the agent-visible rendering: repr of the typed inspection
    return repr(insp)


def engine_entity(name: str, x: float, y: float, fields: str) -> Dict:
    return lua(f"""
        local s = game.surfaces[1]
        local e = s.find_entities_filtered{{name='{name}',
            area={{{{{x}-0.8,{y}-0.8}},{{{x}+0.8,{y}+0.8}}}}}}[1]
        if not e then return {{missing=true}} end
        return {fields}
    """)


async def main() -> None:
    from FactoryVerse.environment.environment import Environment, Tier
    from FactoryVerse.environment.config import (
        EnvironmentConfig, ExecutionMode, InfraConfig, InfraMode,
        PythonConfig, RuntimeConfig, RuntimeVariant, SettingsConfig)

    env = Environment(config=EnvironmentConfig(
        tier1=InfraConfig(mode=InfraMode.EXTERNAL),
        tier2=SettingsConfig(scenario="lab-grid"),
        tier3=PythonConfig(instance="server_0"),
        tier4=RuntimeConfig(variant=RuntimeVariant.FULL, agent_id="agent_1",
                            execution_mode=ExecutionMode.INPROCESS),
    ))
    probes = []
    try:
        await env.initialize(up_to=Tier.RUNTIME)
        # mirror the specimen into the session DB (save loads keep their
        # in-game state; host snapshot files belong to whichever boot wrote
        # them last — re-snapshot then reload)
        lua("remote.call('map','re_snapshot_area',"
            "{left_top={x=0,y=0}, right_bottom={x=128,y=128}}, 50) "
            "return {ok=true}")
        # honest wait: write queue drained
        import time
        for _ in range(120):
            st = lua("return remote.call('map','get_snapshot_status')")
            if st.get("phase") == "IDLE" and st.get("write_queue_size") == 0:
                break
            time.sleep(1)
        env.tier4.reload_snapshot_data()
        rv = env.tier4.remote_view

        # ---- locate specimen anchors (engine truth) ----
        anchors = lua("""
            local s = game.surfaces[1]
            local function first(name)
                local e = s.find_entities_filtered{name=name, area={{0,0},{128,128}}}[1]
                if e then return {x=e.position.x, y=e.position.y, dir=e.direction} end
                return nil
            end
            local function all(name)
                local out = {}
                for _, e in ipairs(s.find_entities_filtered{name=name, area={{0,0},{128,128}}}) do
                    table.insert(out, {x=e.position.x, y=e.position.y, dir=e.direction})
                end
                return out
            end
            return {
                boilers = all('boiler'),
                pumps = all('offshore-pump'),
                engine = first('steam-engine'),
                drill_burner = first('burner-mining-drill'),
                drills = all('electric-mining-drill'),
                inserters = all('long-handed-inserter'),
                inserter_burner = first('burner-inserter'),
                furnaces = all('electric-furnace'),
                poles = all('medium-electric-pole'),
                belts_n = #all('transport-belt'),
            }
        """)
        (FIXTURES / "anchors.json").write_text(json.dumps(anchors, indent=1))

        def add(pid, concept, question, payload, truth, scoring):
            probes.append({"id": pid, "concept": concept, "question": question,
                           "payload": payload, "truth": truth,
                           "scoring": scoring})
            print(f"  captured {pid}")

        # ---- V1/V2: inserter direction semantics ----
        for pid, ins in (("V1", anchors["inserters"][0]),
                         ("V2", None)):  # V2 filled below if a north one exists
            if ins is None:
                continue
            payload = inspect_payload(env, "long-handed-inserter",
                                      ins["x"], ins["y"])
            truth = engine_entity(
                "long-handed-inserter", ins["x"], ins["y"],
                "{pickup={x=e.pickup_position.x,y=e.pickup_position.y},"
                "drop={x=e.drop_position.x,y=e.drop_position.y},dir=e.direction}")
            add(pid, "direction",
                "Based ONLY on this inspection data, which map cell does this "
                "inserter PICK UP from, and which cell does it DROP to? Answer "
                'as JSON: {"pickup": {"x":..,"y":..}, "drop": {"x":..,"y":..}}',
                payload, truth, "positions match engine pickup/drop within 0.5")
        # V2: burner-inserter (whatever its rotation — tests the same decode)
        bi = anchors.get("inserter_burner")
        if bi:
            payload = inspect_payload(env, "burner-inserter", bi["x"], bi["y"])
            truth = engine_entity(
                "burner-inserter", bi["x"], bi["y"],
                "{pickup={x=e.pickup_position.x,y=e.pickup_position.y},"
                "drop={x=e.drop_position.x,y=e.drop_position.y},dir=e.direction}")
            add("V2", "direction",
                "Same question for this inserter: which cell does it PICK UP "
                'from and which does it DROP to? JSON: {"pickup": {...}, "drop": {...}}',
                payload, truth, "positions match engine within 0.5")

        # ---- V5: status root-cause from real inspections ----
        b = anchors["boilers"][0]
        f = anchors["furnaces"][0]
        payload = (
            "Boiler inspection:\n" + inspect_payload(env, "boiler", b["x"], b["y"])
            + "\n\nElectric furnace inspection:\n"
            + inspect_payload(env, "electric-furnace", f["x"], f["y"]))
        truth = {"boiler": engine_entity("boiler", b["x"], b["y"],
                                         "{status=e.status, fuel=e.get_fuel_inventory().get_item_count('coal')}"),
                 "furnace": engine_entity("electric-furnace", f["x"], f["y"],
                                          "{status=e.status}")}
        add("V5", "status",
            "The furnaces in this factory are not working. Based ONLY on these "
            "two inspections, what is the root cause, and what single action "
            "fixes it? Answer as JSON: "
            '{"root_cause": "...", "fix": "..."}',
            payload, truth,
            "root_cause names boiler fuel (no_fuel/out of coal); fix = add/automate coal")

        # ---- V6/V7: reservation — pole safety near a working inserter ----
        ins0 = anchors["inserters"][0]
        payload = inspect_payload(env, "long-handed-inserter", ins0["x"], ins0["y"])
        t = engine_entity(
            "long-handed-inserter", ins0["x"], ins0["y"],
            "{pickup={x=e.pickup_position.x,y=e.pickup_position.y},"
            "drop={x=e.drop_position.x,y=e.drop_position.y}}")
        add("V6", "reservation",
            "You want to place a small-electric-pole (1x1) somewhere in the 8 "
            "cells surrounding this inserter. Based ONLY on this inspection, "
            "list the cell(s) you must NOT place it on, as JSON: "
            '{"forbidden": [{"x":..,"y":..}, ...]}',
            payload, t,
            "forbidden includes BOTH the pickup and drop cells (floor coords)")

        # ---- V8/V9: fluid ports ----
        b0 = anchors["boilers"][0]
        payload = inspect_payload(env, "boiler", b0["x"], b0["y"])
        add("V8", "fluid-ports",
            "Where can a steam-engine connect to THIS boiler, and how many "
            "distinct placements exist? Answer as JSON: "
            '{"n_placements": N, "side": "<which side of the boiler and why>"}',
            payload, {"n": 1, "note": "single steam output port, inline mate"},
            "n_placements == 1 AND side mentions steam output/facing side (not water sides)")

        pump_used = None
        pumps = anchors["pumps"]
        # find the pump that IS connected to a boiler (engine truth)
        for p in pumps:
            linked = lua(f"""
                local s = game.surfaces[1]
                local pu = s.find_entities_filtered{{name='offshore-pump',
                    area={{{{{p['x']}-0.6,{p['y']}-0.6}},{{{p['x']}+0.6,{p['y']}+0.6}}}}}}[1]
                if not pu then return {{missing=true}} end
                for i = 1, #pu.fluidbox do
                    for _, pc in ipairs(pu.fluidbox.get_pipe_connections(i)) do
                        if pc.target and pc.target.owner.name == 'boiler' then
                            return {{linked=true}}
                        end
                    end
                end
                return {{linked=false}}
            """)
            if linked.get("linked"):
                pump_used = p
                break
        if pump_used:
            payload = inspect_payload(env, "offshore-pump",
                                      pump_used["x"], pump_used["y"])
            add("V9", "fluid-ports",
                "This pump is already connected to a boiler. Can a SECOND "
                "boiler also connect directly to this same pump? Answer as "
                'JSON: {"possible": true/false, "why": "..."}',
                payload, {"possible": False, "note": "single output port, already occupied"},
                "possible == false AND why mentions the single/occupied output")

        # ---- V11: lazy drop_target ----
        d = anchors["drill_burner"]
        if d:
            payload = inspect_payload(env, "burner-mining-drill", d["x"], d["y"])
            truth = engine_entity(
                "burner-mining-drill", d["x"], d["y"],
                "{status=e.status, drop_target=(e.drop_target and e.drop_target.name or 'nil'),"
                "fuel=e.get_fuel_inventory().get_item_count('coal')}")
            add("V11", "item-drop",
                "This drill's drop_target shows None/nil even though a "
                "container sits on its drop cell. Is the drill->container "
                "connection physically broken? Answer JSON: "
                '{"broken": true/false, "explanation": "..."}',
                payload, truth,
                "broken == false; explanation mentions fuel/working state (lazy resolution)")

        # ---- V12/V13: belt flow over real specimen belts ----
        belt_pair = lua("""
            local s = game.surfaces[1]
            local belts = s.find_entities_filtered{name='transport-belt', area={{0,0},{128,128}}}
            -- find one belt WITH an output neighbour and one WITHOUT
            local with_out, without_out = nil, nil
            for _, b in ipairs(belts) do
                local n = b.belt_neighbours
                local outs = n and n.outputs or {}
                if #outs > 0 and not with_out then
                    with_out = {x=b.position.x, y=b.position.y,
                                out_x=outs[1].position.x, out_y=outs[1].position.y}
                end
                if #outs == 0 and not without_out then
                    without_out = {x=b.position.x, y=b.position.y}
                end
                if with_out and without_out then break end
            end
            return {with_out = with_out, without_out = without_out}
        """)
        if belt_pair.get("without_out"):
            wo = belt_pair["without_out"]
            payload = inspect_payload(env, "transport-belt", wo["x"], wo["y"])
            add("V12", "belt-flow",
                "Items are flowing on this belt tile. Based ONLY on this "
                "inspection, do items leave this tile onto a NEXT belt, or is "
                "this the end of the line? Answer JSON: "
                '{"continues": true/false, "evidence_field": "<which field told you>"}',
                payload, {"continues": False},
                "continues == false AND evidence cites belt_outputs (empty)")
        if belt_pair.get("with_out"):
            w = belt_pair["with_out"]
            payload = inspect_payload(env, "transport-belt", w["x"], w["y"])
            add("V13", "belt-flow",
                "Same question for this belt tile: do items continue to a "
                'next belt? JSON: {"continues": true/false, '
                '"next_cell": {"x":..,"y":..} or null}',
                payload, {"continues": True, "next": {"x": w["out_x"], "y": w["out_y"]}},
                "continues == true AND next_cell matches engine output neighbour within 0.5")

        # ---- V14: power flow sufficiency ----
        eng = anchors["engine"]
        payload = (
            "Steam engine inspection:\n"
            + inspect_payload(env, "steam-engine", eng["x"], eng["y"])
            + f"\n\nFactory machines on this network: "
            f"{len(anchors['furnaces'])} electric furnaces (180 kW each), "
            f"{len(anchors['drills'])} electric mining drills (90 kW each), "
            "8 assembling-machine-2 (150 kW each).")
        add("V14", "power-flow",
            "One steam engine produces at most 900 kW. Is generation "
            "sufficient for this load when everything runs? What does the "
            "boiler CONSUME while generating, and what happens when that "
            "runs out? Answer JSON: "
            '{"sufficient": true/false, "consumes": "...", "when_out": "..."}',
            payload, {"load_kw": len(anchors["furnaces"]) * 180
                      + len(anchors["drills"]) * 90 + 8 * 150},
            "sufficient == false; consumes mentions coal/fuel; when_out mentions everything stops/no power")

        # ---- V17/V18: wire/network ----
        nets = lua("""
            local s = game.surfaces[1]
            local by = {}
            for _, p in ipairs(s.find_entities_filtered{name='medium-electric-pole', area={{0,0},{128,128}}}) do
                local id = tostring(p.electric_network_id)
                by[id] = (by[id] or 0) + 1
            end
            return by
        """)
        pole_rows = rv.query(
            "SELECT entity_name, position_x, position_y, electric_network_id "
            "FROM map_entity WHERE entity_name = 'medium-electric-pole' "
            "ORDER BY position_x LIMIT 40")
        add("V18", "wire-network",
            "Here are all medium power poles with their electric_network_id. "
            "Is this ONE power network or MORE? If more, what does that mean "
            "for machines near the smaller group? Answer JSON: "
            '{"networks": N, "consequence": "..."}',
            json.dumps(pole_rows, default=str),
            {"engine_networks": nets},
            "networks matches count of distinct ids in payload; consequence: smaller group unpowered/no generator")

        # ---- V21: ghosts ----
        ghost_rows = rv.query(
            "SELECT ghost_name, position_x, position_y FROM ghost LIMIT 25")
        add("V21", "ghosts",
            "What ARE these rows — do these entities physically function "
            "(move items) right now? What must happen for them to function? "
            'Answer JSON: {"functional_now": true/false, "what_needed": "..."}',
            json.dumps(ghost_rows, default=str),
            {"n_ghosts": len(ghost_rows)},
            "functional_now == false; what_needed mentions building/reviving with real items")

        # ---- V23: occupancy footprint ----
        payload = inspect_payload(env, "boiler", b0["x"], b0["y"])
        truth = engine_entity("boiler", b0["x"], b0["y"],
                              "{bb=e.bounding_box, dir=e.direction}")
        add("V23", "occupancy",
            "List every integer tile this boiler blocks (tiles where nothing "
            'else can be built). JSON: {"tiles": [{"x":..,"y":..}, ...]}',
            payload, truth, "tiles match engine bounding box tile cover")

        # ---- prompt-only probes (no live payload) ----
        add("V3", "direction",
            "You received a placement cue: position=(10.5, 20.0), "
            "direction=SOUTH for a steam-engine that must connect to a "
            "boiler. You call place(position) WITHOUT passing direction. "
            'What happens? JSON: {"connects": true/false, "why": "..."}',
            "(no game state — answer from your knowledge of this API)",
            {"connects": False},
            "connects == false; why mentions default NORTH rotation / ports misaligned")
        add("V4", "status",
            'An electric furnace reports status 54. What does 54 mean, and '
            'what do you check NEXT to find the root cause? JSON: '
            '{"meaning": "...", "next_check": "..."}',
            "(no game state)",
            {"meaning": "no_power"},
            "meaning == no_power/no electricity; next_check walks generator side (engine/boiler/fuel or network)")
        add("V10", "fluid-ports",
            "You called get_connection_positions(pump, 'boiler', FLUID_PIPE) "
            "and got an EMPTY list []. List ALL distinct reasons this can "
            'happen, and what you would do next. JSON: {"reasons": [...], '
            '"next_action": "..."}',
            "(no game state)",
            {"key": "blocked space / occupied port / no geometric mate"},
            "reasons include blocked-by-something (space) AND occupied/absent port; next NOT hand-placing")
        add("V15", "power-flow",
            "Your machines all report no_power. List, IN ORDER, the exact "
            "queries/inspections you would run to find the root cause. "
            'JSON: {"steps": ["...", ...]}',
            "(no game state)",
            {"chain": "machine -> network/pole -> generator -> boiler -> fuel"},
            "steps walk to the GENERATOR side and include boiler fuel before re-wiring poles")
        add("V16", "power-flow",
            "Is fueling a boiler a one-time setup or a recurring need? What "
            "specific build makes boiler fuel permanent? JSON: "
            '{"recurring": true/false, "build": "..."}',
            "(no game state)",
            {"recurring": True},
            "recurring == true; build = coal drill/belt/inserter INTO the boiler fuel slot")
        add("V19", "staleness",
            "Five consecutive Task Progress reports all show: 'Snapshot tick: "
            "404340' while your actions keep succeeding and the game "
            "continues. Production shows 0. Do you trust the 0? What do you "
            'check? JSON: {"trust": true/false, "check": "..."}',
            "(the meter text is the only data)",
            {"trust": False},
            "trust == false (frozen tick); check mentions tick not advancing / query DB or game tick directly")
        add("V20", "staleness",
            "Write the SQL you would run to determine whether your map "
            "database is up to date with the live game. "
            'JSON: {"sql": "...", "how_to_interpret": "..."}',
            "(no game state)",
            {"table": "chunk_snapshot_meta"},
            "sql touches chunk_snapshot_meta MAX(tick); interpret vs current game tick")
        add("V22", "mirage",
            "Write the SQL to list all inserters with their pickup and drop "
            'positions. JSON: {"sql": "..."}',
            "(no game state — use the documented schema)",
            {"trap": "inserter table is empty; truth lives in map_entity.raw_data"},
            "RECORD ONLY: does the SQL use the dead `inserter` table (as the docs teach)?")
        add("V24", "reach",
            "You are at (50.0, 50.0). You want to place a chest at "
            '(61.5, 50.0). Can you do it from here? JSON: {"can_place": '
            'true/false, "first_action": "..."}',
            "(no game state)",
            {"distance": 11.5, "build_distance": 10},
            "can_place == false; first_action = walk closer")
        add("V25", "capability-baseline",
            "You are laying a row of furnaces fed by one belt with inserters, "
            "and you expect to add an OUTPUT belt later. How many empty tiles "
            "do you leave between the furnace row and anything else, and "
            'why? JSON: {"gap_tiles": N, "why": "..."}',
            "(design question)",
            {"min_gap": 2},
            "gap >= 2 with reasoning about inserter + belt lanes (judged)")

    finally:
        await env.shutdown()

    out = FIXTURES / "v0.json"
    out.write_text(json.dumps(probes, indent=1, default=str))
    print(f"\n{len(probes)} probes captured -> {out}")


if __name__ == "__main__":
    asyncio.run(main())
