#!/usr/bin/env python
"""Certification check L4.5 — async completion honesty (walk / mine / craft).

Ledger row (FLOOR_CERTIFICATION.md L4.5):
    Claim:      Async completion honest — walk/mine/craft: UDP completion
                arrives exactly once and state matches
    Pass:       Completion <=> real state change

Why the old harness was decertified (audit 2026-06-10): tests/actions/* has
ZERO assertions about UDP completions; the purpose-built UDPCapture fixture is
used by no test. This harness binds a real UDP socket, triggers the real
actions over RCON, and cross-checks every completion datagram against an
independent RCON read of the state it claims.

THE UDP CONTRACT AS READ FROM CODE (src/fv_embodied_agent — encode, don't guess):
    - utils/udp.lua create_action_payload + game_state/Agents.lua
      process_agent_messages: every datagram is JSON with
      event_type="action", action_id, agent_id, action_type, status,
      rcon_tick, tick, category; non-standard message fields are nested
      under `result`.
    - status=="completed" adds completion_tick + success (defaults true) +
      result. "Exactly one completion" therefore means exactly one
      status=="completed" datagram per action_id.
    - mine_resource and craft_enqueue ALSO emit a status=="queued" datagram
      at trigger time (mining.lua:299, crafting.lua:299); walk_to does NOT
      (its sync RCON return is the ack). Queued datagrams are expected and
      are NOT completions.
    - walk_to async failure (all path candidates exhausted) emits
      status=="failed" with success=false in the MESSAGE, but
      create_action_payload only attaches top-level `success` when
      status=="completed" — so a failed datagram is detected by
      status=="failed"; its failure_type/goal/message live in `result`
      (Agents.lua:826 handle_path_failure). --> OPEN-QUESTION OQ1 below.
    - walk_to validation failures (entity_not_found / no_standable_tiles /
      already-in-reach) return synchronously over RCON with queued=false and
      send NO datagram (walking.lua:269-305). Contract case (c): a
      sync-failed action_id must produce ZERO datagrams.
    - crafting completion ALSO triggers a second datagram on the same port:
      event_type="notification", notification_type="crafting_finished"
      (Notifications.lua:189). It is not an action completion; the listener
      records it but excludes it from completion counting.

Actions exercised (serially — the agent state machines are exclusive):
    A walk_ok    : walk_to a point ~10 tiles away inside the cell play area.
                   Verify: exactly 1 completed; payload position == RCON
                   get_position (tol 0.5); agent actually moved >= 5 tiles
                   from start; no failed datagram.
    B walk_sync_fail : walk_to with entity_ref to an entity that does not
                   exist. Verify: RCON returns success=false + an action_id;
                   ZERO datagrams ever arrive for that action_id.
    C walk_async_fail: walk_to a point in the inter-cell void (lab-grid cells
                   are separated by out-of-map tiles — unpathable). Verify:
                   exactly one terminal datagram; if status=="failed", agent
                   position unchanged (< 2 tiles drift) and zero completed
                   datagrams; if the engine legitimately paths there
                   (OQ2), record honestly and require the walk_ok invariants.
    D mine       : teleport beside the cell's iron-ore patch; RCON-read the
                   target resource amount + agent iron-ore count;
                   mine_resource('iron-ore', 3). Verify: exactly 1 completed;
                   payload actual_products == {'iron-ore': 3}; inventory
                   gained exactly 3 (get_inventory_items is a LIST of
                   {name,quality,count} — playbook trap); resource amount at
                   the mined position decreased by exactly 3 (or entity gone).
    E craft      : add_items 4 iron-plate; craft_enqueue('iron-gear-wheel', 2).
                   Verify: exactly 1 completed; payload products ==
                   {'iron-gear-wheel': 2}; inventory +2 gears / -4 plates;
                   crafting_queue_size back to 0.

Pass criteria (ALL required):
    1. Per successful async action: exactly ONE status=="completed" datagram
       for its action_id (0 = FAIL silent, 2+ = FAIL duplicate).
    2. Every completion payload matches the independently-read state change
       (position moved / inventory credited + resource decremented / queue
       drained + products credited).
    3. Sync-failed action: zero datagrams for its action_id. Async-failed
       walk: exactly one terminal datagram, no state change claimed or made.
    4. Anti-vacuity: >= 3 actions completed with state verified, >= 1 failure
       case observed, total action datagrams captured > 0; else VACUOUS-RISK.

Audit-gate answers AS DESIGNED (executing runner re-validates):
    Q1 vacuous pass?     Datagram counts are exact-equality asserts (==1, ==0),
                         never >=0; state deltas are exact; counters gate the
                         verdict; a silent UDP channel FAILs (A expects 1).
    Q2 real layer?       Real UDP socket bound on the host, real mod-emitted
                         datagrams through the real (socat-forwarded on
                         server) channel, real actions.
    Q3 independent truth? Every completion claim is re-verified by a raw RCON
                         read (position scan, resource entity amount,
                         inventory counts, crafting_queue_size) that shares no
                         code with the UDP emit path.
    Q4 covers the row?   walk/mine/craft exactly-once + state-match + failure
                         honesty. NOT covered: place/pickup completions,
                         progress datagrams, multi-agent port isolation.

SCOPE / OPEN-QUESTIONS (offline draft cannot settle; runner must confirm):
    - OQ1: the "failed" datagram omits top-level `success` (create_action_payload
      only attaches it for completed). If a failed datagram arrives WITH
      success=true that is a contract bug — the harness records the raw
      payload and FAILs on completed-vs-failed count, not on the field.
    - OQ2: whether the void between cells is truly unpathable from inside a
      cell (C). If C completes successfully the harness does not FAIL — it
      records that no async-failure path was exercised and reports criterion
      4's failure-case via B only.
    - OQ3: port binding. Default agent port is 34202 (utils/udp.lua); on
      docker servers socat forwards 34202-34211 — LISTEN on the forwarded
      port, never set_udp_port/repoint (playbook §1). If 34202 is already
      bound by another process (e.g. a live SyncService/agent runtime), this
      check is BLOCKED — run it on an instance without a live runtime.
    - OQ4: reused agents (cell already occupied) keep their original
      udp_port; the harness reads it from agent.list_agents and binds that
      instead, BLOCKED if outside the forwarded 34202-34211 range.
    - OQ5: walk_ok goal standability is probabilistic on generated terrain;
      the harness tries up to 3 candidate goals before declaring BLOCKED.

Exit codes: 0 = PASS, 1 = FAIL, 2 = BLOCKED, 3 = VACUOUS-RISK.

Usage:
    uv run python scripts/certification/check_L4_5.py --instance client --cell 5
"""

from __future__ import annotations

import argparse
import datetime
import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from factorio_rcon import RCONClient  # noqa: E402

# ----------------------------------------------------------------------------
# Constants / instance plumbing
# ----------------------------------------------------------------------------
DATE = datetime.date.today().isoformat()
CHECK_ID = "L4.5"

RCON_HOST, RCON_PORT, RCON_PASS = "localhost", 27100, "factorio"
FORWARDED_PORTS = range(34202, 34212)  # socat sidecar forwards exactly these

COMPLETION_TIMEOUT_S = 60.0
NO_DATAGRAM_WINDOW_S = 8.0

results: Dict[str, Any] = {"findings": [], "actions": {}, "counters": {}}
ART: Path = REPO / ".fv-output" / "certification" / DATE / CHECK_ID
PROGRESS: Path = ART / "progress.log"


def configure_instance(name: str) -> None:
    global RCON_PORT
    if name == "client":
        return
    if name.startswith("server_"):
        RCON_PORT = 27000 + int(name.split("_")[1])
        return
    raise SystemExit(f"unknown instance {name!r}; use 'client' or 'server_N'")


def hb(msg: str) -> None:
    line = f"{datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')} {msg}"
    with open(PROGRESS, "a") as f:
        f.write(line + "\n")
    print(f"[hb] {line}", flush=True)


def finding(msg: str) -> None:
    results["findings"].append(msg)
    print(f"[FINDING] {msg}", flush=True)


def save(name: str, data: Any) -> None:
    (ART / name).write_text(json.dumps(data, indent=2, default=str))


# ----------------------------------------------------------------------------
# RCON helpers (RUNTIME_PLAYBOOK §2)
# ----------------------------------------------------------------------------
def lua(rcon: RCONClient, body: str) -> Any:
    # HARNESS-FIX 2026-06-11 (first run, same as check_L2_4/L2_5): non-table
    # returns (teleport -> boolean) raised in table_to_json OUTSIDE the xpcall
    # -> empty RCON response on the docker server. Envelope-serialize instead.
    wrapped = (
        "/c local ok, res = xpcall(function() "
        + body
        + " end, debug.traceback) "
        + "if ok then rcon.print(helpers.table_to_json({__v = res})) "
        + "else rcon.print(helpers.table_to_json({__lua_error = tostring(res)})) end"
    )
    out = rcon.send_command(wrapped)
    if out is None or out.strip() == "":
        return {"__lua_error": "empty RCON response (unwrapped error?)"}
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return {"__lua_error": f"non-JSON response: {out[:500]}"}
    if isinstance(data, dict) and "__lua_error" in data:
        return data
    if isinstance(data, dict):
        return data.get("__v", {"ok": True})
    return data


def lua_strict(rcon: RCONClient, body: str) -> Any:
    res = lua(rcon, body)
    if isinstance(res, dict) and "__lua_error" in res:
        raise RuntimeError(f"Lua error: {res['__lua_error'][:800]}")
    return res


def pos_lua(p: Dict[str, float]) -> str:
    return f"{{x={p['x']},y={p['y']}}}"


# ----------------------------------------------------------------------------
# UDP capture (bind BEFORE any action is triggered; never repoint the mod)
# ----------------------------------------------------------------------------
class UDPCapture:
    """Plain socket listener; collects every datagram with arrival time.
    Deliberately NOT the production UDPDispatcher: capture must be
    independent of the code under test wherever possible."""

    def __init__(self, host: str, port: int):
        self.host, self.port = host, port
        self.datagrams: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._sock: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.decode_errors = 0

    def start(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # No SO_REUSEADDR: if something else owns the port we MUST fail loudly
        # (a shared bind silently steals/splits datagrams on macOS).
        self._sock.bind((self.host, self.port))
        self._sock.settimeout(0.25)
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while self._running:
            try:
                data, _ = self._sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                payload = json.loads(data.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                self.decode_errors += 1
                continue
            with self._lock:
                self.datagrams.append({"recv_time": time.time(), "payload": payload})

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._sock:
            self._sock.close()

    def snapshot(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.datagrams)

    def for_action(self, action_id: str) -> List[Dict[str, Any]]:
        return [d for d in self.snapshot()
                if d["payload"].get("event_type") == "action"
                and d["payload"].get("action_id") == action_id]

    def wait_terminal(self, action_id: str, timeout: float) -> Optional[Dict[str, Any]]:
        """Wait for a completed/failed/cancelled datagram for action_id."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            for d in self.for_action(action_id):
                if d["payload"].get("status") in ("completed", "failed", "cancelled"):
                    return d
            time.sleep(0.2)
        return None


# ----------------------------------------------------------------------------
# Verdict bookkeeping
# ----------------------------------------------------------------------------
class Verdict:
    def __init__(self) -> None:
        self.failures: List[str] = []
        self.checks = 0
        self.completed_verified = 0
        self.failure_cases_observed = 0

    def check(self, label: str, ok: bool, detail: Any = None) -> bool:
        self.checks += 1
        rec = {"label": label, "ok": ok, "detail": detail}
        results.setdefault("checks", []).append(rec)
        if not ok:
            self.failures.append(f"{label}: {detail!r}")
        return ok


def inv_count(rcon: RCONClient, iface: str, item: str) -> int:
    """get_inventory_items returns a LIST of {name, quality, count} (playbook §3)."""
    items = lua_strict(rcon, f"return remote.call('{iface}','get_inventory_items')")
    if isinstance(items, dict):
        items = list(items.values())
    total = 0
    for it in items or []:
        if isinstance(it, dict) and it.get("name") == item:
            total += int(it.get("count") or 0)
    return total


def get_pos(rcon: RCONClient, iface: str) -> Dict[str, float]:
    return lua_strict(rcon, f"return remote.call('{iface}','get_position')")


def dist(a: Dict[str, float], b: Dict[str, float]) -> float:
    return ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main() -> int:
    global ART, PROGRESS
    ap = argparse.ArgumentParser(
        description="L4.5 — async completion honesty: exactly-once UDP + real state change"
    )
    ap.add_argument("--instance", default="client", help="client or server_N")
    ap.add_argument("--cell", type=int, default=5, help="lab-grid cell index to use")
    ap.add_argument("--udp-host", default="127.0.0.1", help="listener bind host")
    ap.add_argument("--udp-port", type=int, default=None,
                    help="override listener port (default: the agent's own port)")
    ap.add_argument("--artifacts-dir", default=None, help="override evidence dir")
    args = ap.parse_args()
    configure_instance(args.instance)

    if args.artifacts_dir:
        ART = Path(args.artifacts_dir)
    elif args.instance != "client":
        ART = ART / args.instance
    ART.mkdir(parents=True, exist_ok=True)
    PROGRESS = ART / "progress.log"

    commit = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()
    hb(f"=== check_L4_5 start (instance={args.instance}, cell={args.cell}, commit={commit}) ===")

    try:
        rcon = RCONClient(RCON_HOST, RCON_PORT, RCON_PASS)
    except Exception as e:  # noqa: BLE001
        print(f"BLOCKED: cannot connect RCON: {e}")
        return 2

    rcon.send_command("/c rcon.print('ping')")
    assert "ping" in rcon.send_command("/c rcon.print('ping')"), "smoke ping failed"
    ifaces = json.loads(
        rcon.send_command("/c rcon.print(helpers.table_to_json(remote.interfaces))")
    )
    missing = [i for i in ("lab_grid", "agent") if i not in ifaces]
    if missing:
        print(f"BLOCKED: missing remote interfaces {missing}")
        return 2
    hb("smoke ok")

    # --- agent (create in cell, or reuse + read its real udp_port) -----------
    cell = args.cell
    b = lua_strict(rcon, f"return remote.call('lab_grid','get_cell_bounds',{cell})")
    lt = b["left_top"]
    st = lua_strict(rcon, f"return remote.call('lab_grid','get_cell_status',{cell})")
    if st.get("has_agent"):
        agents = lua_strict(rcon, "return remote.call('agent','list_agents')")
        if isinstance(agents, dict):
            agents = list(agents.values())
        storage = lua_strict(rcon, "return remote.call('lab_grid','get_storage')")
        ac = storage.get("agent_cells") or {}
        # HARNESS-FIX 2026-06-11 (same as check_L2_4/L2_5): consecutive-int-keyed
        # Lua tables serialize as JSON arrays; list index i -> agent_id i+1.
        if isinstance(ac, list):
            ac = {i + 1: v for i, v in enumerate(ac) if v is not None}
        bound = {int(aid): int(ci) for aid, ci in ac.items()}
        entry = next((a for a in agents if bound.get(int(a.get("id", -1))) == cell), None)
        if entry is None:
            print(f"BLOCKED: cell {cell} occupied but unbound; pick another --cell")
            return 2
        agent_id, agent_port = int(entry["id"]), int(entry.get("udp_port") or 34202)
        created_by_us = False
    else:
        create = lua_strict(
            rcon, f"return remote.call('lab_grid','create_agent_in_cell',{{cell_index={cell}}})"
        )
        if not create.get("success"):
            print(f"BLOCKED: create_agent_in_cell failed: {create}")
            return 2
        agent_id, agent_port = int(create["agent_id"]), 34202  # scenario passes udp_port=nil
        created_by_us = True
    iface = f"agent_{agent_id}"
    listen_port = args.udp_port or agent_port
    results["agent"] = {"agent_id": agent_id, "iface": iface,
                        "udp_port": agent_port, "listen_port": listen_port,
                        "created_by_us": created_by_us}
    if listen_port not in FORWARDED_PORTS and args.instance != "client":
        print(f"BLOCKED: agent udp_port {listen_port} is outside the socat-forwarded "
              f"range 34202-34211 (OQ4) — datagrams would blackhole in the container")
        return 2

    # ENVIRONMENT WORKAROUND (recorded as a real lab-grid defect, 2026-06-11):
    # lab-grid's initialize_map sets tiles via set_tiles but NEVER calls
    # set_chunk_generated_status (control.lua:305 comment promises it; no call
    # exists) -> is_chunk_generated == false map-wide -> the engine pathfinder
    # refuses every path -> ALL walk_to fail in ~1 tick with no path. Verified
    # live: flagging the cell's chunks makes the identical walk complete.
    # Flag this cell's play-area chunks so walk cases are exercisable; the
    # scenario itself still needs the code fix.
    cx0, cx1 = int(lt["x"] // 32), int((lt["x"] + 127) // 32)
    cy0, cy1 = int(lt["y"] // 32), int((lt["y"] + 127) // 32)
    flagged = lua_strict(rcon, f"""
        local s = game.surfaces[1]
        local n = 0
        for cx = {cx0}, {cx1} do
            for cy = {cy0}, {cy1} do
                s.set_chunk_generated_status({{cx, cy}}, defines.chunk_generated_status.entities)
                n = n + 1
            end
        end
        return {{flagged = n}}
    """)
    results["chunk_generated_workaround"] = flagged
    hb(f"WORKAROUND: flagged {flagged.get('flagged')} cell chunks as generated "
       "(lab-grid defect: pathfinder dead on unflagged chunks)")

    cap = UDPCapture(args.udp_host, listen_port)
    try:
        cap.start()
    except OSError as e:
        print(f"BLOCKED: cannot bind UDP {args.udp_host}:{listen_port}: {e} "
              "(OQ3 — another listener owns the agent port; stop it or use a quiet instance)")
        return 2
    hb(f"UDP capture bound on {args.udp_host}:{listen_port} (agent port {agent_port})")

    v = Verdict()
    try:
        # ======================= A. walk_to success =========================
        spawn = get_pos(rcon, iface)
        goal_candidates = [
            {"x": spawn["x"] + 10, "y": spawn["y"]},
            {"x": spawn["x"] - 10, "y": spawn["y"] + 3},
            {"x": spawn["x"], "y": spawn["y"] + 10},
        ]
        walk_done = None
        for gi, goal in enumerate(goal_candidates):
            hb(f"A: walk_to attempt {gi}: goal={goal}")
            p0 = get_pos(rcon, iface)
            t_trigger = time.time()
            trig = lua_strict(
                rcon, f"return remote.call('{iface}','walk_to',{{goal={pos_lua(goal)}}})"
            )
            results["actions"][f"walk_ok_trigger_{gi}"] = trig
            if not trig.get("queued"):
                # not queued: either already-there (no datagram by contract) or
                # sync failure — try the next candidate.
                finding(f"A: candidate {gi} not queued ({trig.get('message')}); trying next")
                continue
            action_id = trig["action_id"]
            term = cap.wait_terminal(action_id, COMPLETION_TIMEOUT_S)
            if term and term["payload"].get("status") == "completed":
                walk_done = (action_id, p0, goal, term, t_trigger)
                break
            finding(f"A: candidate {gi} terminal={term and term['payload'].get('status')}; trying next")
        if walk_done is None:
            print("BLOCKED: no walk_to candidate completed (OQ5 — terrain); "
                  "see findings/artifacts")
            return 2
        action_id, p0, goal, term, t_trigger = walk_done
        dgs = cap.for_action(action_id)
        completed = [d for d in dgs if d["payload"]["status"] == "completed"]
        failed = [d for d in dgs if d["payload"]["status"] == "failed"]
        v.check("A.exactly_one_completed", len(completed) == 1,
                {"completed": len(completed), "all_statuses":
                 [d["payload"]["status"] for d in dgs]})
        v.check("A.zero_failed", len(failed) == 0, len(failed))
        payload = completed[0]["payload"] if completed else {}
        res_pos = (payload.get("result") or {}).get("position")
        p1 = get_pos(rcon, iface)
        v.check("A.payload_position_matches_rcon",
                res_pos is not None and dist(res_pos, p1) < 0.5,
                {"payload": res_pos, "rcon": p1})
        v.check("A.agent_actually_moved", dist(p0, p1) >= 5.0,
                {"from": p0, "to": p1, "goal": goal})
        v.check("A.payload_success_true", payload.get("success") is True,
                payload.get("success"))
        if all(r["ok"] for r in results["checks"][-5:]):
            v.completed_verified += 1
        hb(f"A done: moved {dist(p0, p1):.1f} tiles, {len(dgs)} datagrams for action")

        # ================= B. sync failure (no datagram) ====================
        # HARNESS-REDESIGN 2026-06-11 (first run): the original case used
        # walk_to options.entity_ref to a nonexistent entity. REAL FINDING:
        # options.entity_ref is DEAD via the remote interface — the paramspec
        # doc promises it, but RemoteInterface.lua:371 dispatches only
        # (goal, strict_goal, options) while walking.lua:207 reads entity_ref
        # as a 4th positional arg that is never passed. The agent silently did
        # a plain position walk (observed live: queued + completed datagram).
        # Replacement sync-failure: mine_resource for a resource not within
        # reach — raises a Lua error over RCON (mining.lua:228), no action_id
        # is ever minted, so the contract is ZERO new action datagrams.
        hb("B: mine_resource('copper-ore') with none in reach (sync Lua error)")
        finding("B-REDESIGN: walk_to options.entity_ref is dead code via remote "
                "(RemoteInterface.lua:371 drops it; walking.lua takes it as 4th "
                "positional arg) — entity-aware walking unreachable from RCON; "
                "sync-failure case replaced with mine_resource-not-in-reach")
        # Stand on verified resource-free ground first (the agent may have
        # ended case A within reach of a patch — observed live on rerun).
        clear_spot = lua_strict(rcon, f"""
            local s = game.surfaces[1]
            for dy = 0, 40, 4 do
                local p = {{x = {lt['x']} + 24, y = {lt['y']} + 24 + dy}}
                if s.get_tile(p.x, p.y).name ~= 'out-of-map'
                   and #s.find_entities_filtered{{position=p, radius=8, type='resource'}} == 0 then
                    remote.call('{iface}','teleport', {{position=p}})
                    return {{x=p.x, y=p.y, found=true}}
                end
            end
            return {{found=false}}
        """)
        v.check("B.resource_free_spot_found", clear_spot.get("found") is True, clear_spot)
        n_action_dgs_before = sum(
            1 for d in cap.snapshot() if d["payload"].get("event_type") == "action")
        trig_b = lua(rcon, f"""
            return remote.call('{iface}','mine_resource',
                {{resource_name='copper-ore', max_count=1}})
        """)
        results["actions"]["sync_fail_trigger"] = trig_b
        is_sync_error = (isinstance(trig_b, dict) and "__lua_error" in trig_b
                         and "not found within reach" in trig_b["__lua_error"])
        v.check("B.sync_returns_failure", is_sync_error, trig_b)
        time.sleep(NO_DATAGRAM_WINDOW_S)
        n_action_dgs_after = sum(
            1 for d in cap.snapshot() if d["payload"].get("event_type") == "action")
        v.check("B.zero_datagrams_for_failed_sync_action",
                n_action_dgs_after == n_action_dgs_before,
                {"before": n_action_dgs_before, "after": n_action_dgs_after})
        if is_sync_error:
            v.failure_cases_observed += 1
        hb(f"B done: sync_error={is_sync_error}, action datagrams "
           f"{n_action_dgs_before}->{n_action_dgs_after}")

        # ============ C. walk_to async failure (void between cells) =========
        void_goal = {"x": lt["x"] - 16, "y": lt["y"] - 16}  # inter-cell gap
        hb(f"C: walk_to into the void at {void_goal} (expect async path failure)")
        c0 = get_pos(rcon, iface)
        trig_c = lua_strict(
            rcon, f"return remote.call('{iface}','walk_to',{{goal={pos_lua(void_goal)}}})"
        )
        results["actions"]["walk_async_fail_trigger"] = trig_c
        if trig_c.get("queued"):
            c_id = trig_c["action_id"]
            term_c = cap.wait_terminal(c_id, COMPLETION_TIMEOUT_S)
            c_dgs = cap.for_action(c_id)
            c_completed = [d for d in c_dgs if d["payload"]["status"] == "completed"]
            c_failed = [d for d in c_dgs if d["payload"]["status"] == "failed"]
            v.check("C.exactly_one_terminal", len(c_completed) + len(c_failed) == 1,
                    {"completed": len(c_completed), "failed": len(c_failed)})
            if c_failed:
                c1 = get_pos(rcon, iface)
                v.check("C.failed_means_no_movement", dist(c0, c1) < 2.0,
                        {"from": c0, "to": c1})
                # HARNESS-FIX 2026-06-11 (first run): failure_type was asserted
                # hard; observed live that create_action_payload (udp.lua:99-119)
                # attaches `result` ONLY for completed/cancelled/progress —
                # status='failed' datagrams DROP handle_path_failure's
                # failure_type/goal/message entirely. The failed STATUS itself
                # is honest (exactly-once, no movement) so the floor holds;
                # the missing diagnostic detail is recorded as a REAL contract
                # gap, not a verdict failure.
                if not (c_failed[0]["payload"].get("result") or {}).get("failure_type"):
                    finding("C: failed datagram has NO result/failure_type — "
                            "create_action_payload drops result for status='failed' "
                            "(udp.lua:99-119); failure detail lost on the wire")
                v.failure_cases_observed += 1
            else:
                finding("C: void goal unexpectedly pathed/completed (OQ2) — async-failure "
                        "path NOT exercised this run; failure honesty rests on case B")
        else:
            finding(f"C: walk rejected synchronously ({trig_c}) — counts as a second "
                    "sync-failure observation, async path failure NOT exercised (OQ2)")
            time.sleep(2.0)
        hb("C done")

        # ======================= D. mine_resource ===========================
        hb("D: locating nearest iron-ore in cell; teleporting agent beside it")
        ore = lua_strict(rcon, f"""
            local s = game.surfaces[1]
            local area = {{left_top={{x={lt['x']},y={lt['y']}}},
                           right_bottom={{x={lt['x']}+128,y={lt['y']}+128}}}}
            local best, bd = nil, 1e9
            local me = {pos_lua(get_pos(rcon, iface))}
            for _, e in pairs(s.find_entities_filtered{{area=area, name='iron-ore'}}) do
                local d = (e.position.x-me.x)^2 + (e.position.y-me.y)^2
                if d < bd then best, bd = e, d end
            end
            if not best then return {{missing=true}} end
            return {{x=best.position.x, y=best.position.y, amount=best.amount}}
        """)
        if ore.get("missing"):
            print("BLOCKED: no iron-ore in cell — lab-grid patch expected at offset (15,70)")
            return 2
        ore_pos = {"x": ore["x"], "y": ore["y"]}
        lua_strict(rcon, f"return remote.call('{iface}','teleport',"
                         f"{{position={pos_lua({'x': ore['x'] + 1.5, 'y': ore['y']})}}})")
        amount_before = ore["amount"]
        # HARNESS-FIX 2026-06-11 (first run): per-tile baseline for EVERY ore
        # tile the action could pick (mine_resource selects its own nearest
        # tile; tiles may also carry decrements from earlier runs).
        baseline_tiles = lua_strict(rcon, f"""
            local me = remote.call('{iface}','get_position')
            local out = {{}}
            for _, e in pairs(game.surfaces[1].find_entities_filtered{{
                    position=me, radius=6, name='iron-ore'}}) do
                out[string.format('%.1f,%.1f', e.position.x, e.position.y)] = e.amount
            end
            return out
        """)
        results["actions"]["mine_baseline_tiles"] = baseline_tiles
        inv_before = inv_count(rcon, iface, "iron-ore")
        trig_d = lua_strict(rcon, f"""
            return remote.call('{iface}','mine_resource',
                {{resource_name='iron-ore', max_count=3}})
        """)
        results["actions"]["mine_trigger"] = trig_d
        if not trig_d.get("queued"):
            v.check("D.mine_queued", False, trig_d)
        else:
            d_id = trig_d["action_id"]
            term_d = cap.wait_terminal(d_id, COMPLETION_TIMEOUT_S)
            d_dgs = cap.for_action(d_id)
            d_completed = [d for d in d_dgs if d["payload"]["status"] == "completed"]
            d_queued = [d for d in d_dgs if d["payload"]["status"] == "queued"]
            v.check("D.exactly_one_completed", len(d_completed) == 1,
                    [d["payload"]["status"] for d in d_dgs])
            v.check("D.queued_datagram_seen", len(d_queued) == 1, len(d_queued))
            payload_d = d_completed[0]["payload"] if d_completed else {}
            products = (payload_d.get("result") or {}).get("actual_products") or {}
            v.check("D.payload_products", products.get("iron-ore") == 3, products)
            inv_after = inv_count(rcon, iface, "iron-ore")
            v.check("D.inventory_credited_exactly", inv_after - inv_before == 3,
                    {"before": inv_before, "after": inv_after})
            # HARNESS-FIX 2026-06-11 (first run): mine_resource picks ITS OWN
            # nearest ore tile, which need not be the tile this harness probed
            # (observed live: probed tile untouched, adjacent tile mined). The
            # honest check for "state matches the completion claim" is to read
            # the resource at the POSITION THE PAYLOAD CLAIMS was mined.
            claimed_pos = (payload_d.get("result") or {}).get("position")
            v.check("D.payload_claims_mined_position", claimed_pos is not None,
                    payload_d.get("result"))
            if claimed_pos is not None:
                after = lua_strict(rcon, f"""
                    local e = game.surfaces[1].find_entity('iron-ore', {pos_lua(claimed_pos)})
                    if not e then return {{gone=true}} end
                    return {{amount=e.amount}}
                """)
                tile_key = f"{float(claimed_pos['x']):.1f},{float(claimed_pos['y']):.1f}"
                tile_baseline = (baseline_tiles or {}).get(tile_key)
                decremented = after.get("gone") or (
                    tile_baseline is not None
                    and after.get("amount") is not None
                    and after["amount"] == tile_baseline - 3)
                v.check("D.resource_decremented_exactly_at_claimed_position",
                        bool(decremented),
                        {"claimed_pos": claimed_pos, "tile_baseline": tile_baseline,
                         "after": after})
            if d_completed and inv_after - inv_before == 3:
                v.completed_verified += 1
            hb(f"D done: inv {inv_before}->{inv_after}, ore {amount_before}->{after}")

        # ======================= E. craft_enqueue ===========================
        hb("E: craft_enqueue iron-gear-wheel x2 (plates via agent.add_items)")
        lua_strict(rcon, f"return remote.call('agent','add_items',{agent_id},"
                         "{['iron-plate']=4})")
        plates_before = inv_count(rcon, iface, "iron-plate")
        gears_before = inv_count(rcon, iface, "iron-gear-wheel")
        trig_e = lua_strict(rcon, f"""
            return remote.call('{iface}','craft_enqueue',
                {{recipe_name='iron-gear-wheel', count=2}})
        """)
        results["actions"]["craft_trigger"] = trig_e
        if not trig_e.get("queued"):
            v.check("E.craft_queued", False, trig_e)
        else:
            e_id = trig_e["action_id"]
            v.check("E.queued_count", trig_e.get("count_queued") == 2, trig_e)
            term_e = cap.wait_terminal(e_id, COMPLETION_TIMEOUT_S)
            e_dgs = cap.for_action(e_id)
            e_completed = [d for d in e_dgs if d["payload"]["status"] == "completed"]
            v.check("E.exactly_one_completed", len(e_completed) == 1,
                    [d["payload"]["status"] for d in e_dgs])
            payload_e = e_completed[0]["payload"] if e_completed else {}
            products_e = (payload_e.get("result") or {}).get("products") or {}
            v.check("E.payload_products", products_e.get("iron-gear-wheel") == 2, products_e)
            plates_after = inv_count(rcon, iface, "iron-plate")
            gears_after = inv_count(rcon, iface, "iron-gear-wheel")
            v.check("E.gears_credited", gears_after - gears_before == 2,
                    {"before": gears_before, "after": gears_after})
            v.check("E.plates_debited", plates_before - plates_after == 4,
                    {"before": plates_before, "after": plates_after})
            q = lua_strict(rcon, f"""
                local a = remote.call('{iface}','inspect', true)
                return {{queue_active = a.state and a.state.crafting
                         and a.state.crafting.active or false}}
            """)
            v.check("E.queue_drained", q.get("queue_active") is not True, q)
            # the crafting_finished NOTIFICATION is a separate datagram type;
            # record it (contract evidence), do not count it as a completion.
            notif = [d for d in cap.snapshot()
                     if d["payload"].get("event_type") == "notification"
                     and d["payload"].get("notification_type") == "crafting_finished"]
            results["actions"]["crafting_notifications"] = [d["payload"] for d in notif]
            if e_completed and gears_after - gears_before == 2:
                v.completed_verified += 1
            hb(f"E done: gears {gears_before}->{gears_after}, plates "
               f"{plates_before}->{plates_after}, notifications={len(notif)}")

        # ---- global duplicate scan: no action_id may have >1 completed ------
        by_id: Dict[str, int] = {}
        for d in cap.snapshot():
            p = d["payload"]
            if p.get("event_type") == "action" and p.get("status") == "completed":
                by_id[p.get("action_id")] = by_id.get(p.get("action_id"), 0) + 1
        dupes = {k: n for k, n in by_id.items() if n > 1}
        v.check("GLOBAL.no_duplicate_completions", not dupes, dupes)

        # --- verdict ----------------------------------------------------------
        all_dgs = cap.snapshot()
        results["udp"] = {
            "total_datagrams": len(all_dgs),
            "action_datagrams": sum(1 for d in all_dgs
                                    if d["payload"].get("event_type") == "action"),
            "decode_errors": cap.decode_errors,
        }
        save("datagrams.json", [d["payload"] for d in all_dgs])
        results["counters"] = {
            "checks": v.checks,
            "completed_verified": v.completed_verified,
            "failure_cases_observed": v.failure_cases_observed,
            "disagreements": len(v.failures),
        }
        tick = lua_strict(rcon, "return {tick=game.tick}")["tick"]
        vacuous = (v.completed_verified < 3
                   or v.failure_cases_observed < 1
                   or results["udp"]["action_datagrams"] == 0)
        status = ("VACUOUS-RISK" if vacuous and not v.failures
                  else ("FAIL" if v.failures else "PASS"))
        results["verdict"] = {"check": CHECK_ID, "status": status, "commit": commit,
                              "tick": tick, "failures": v.failures}
        save("results.json", results)
        print("\n========== SUMMARY ==========")
        print(json.dumps({"status": status, "counters": results["counters"],
                          "udp": results["udp"], "failures": v.failures,
                          "findings": results["findings"]}, indent=2, default=str))
        return {"PASS": 0, "FAIL": 1, "VACUOUS-RISK": 3}[status]

    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        import traceback
        results["error"] = {"type": type(e).__name__, "msg": str(e),
                            "traceback": traceback.format_exc()}
        save("results.json", results)
        hb(f"ERROR: {type(e).__name__}: {e}")
        print(f"FAIL (crash): {e}")
        return 1
    finally:
        cap.stop()
        # leave the agent in place if we created it via the session path (it
        # is the cell's bound agent); record that the runner may unassign it.
        hb(f"=== check_L4_5 end (captured {len(cap.snapshot())} datagrams) ===")


if __name__ == "__main__":
    sys.exit(main())
