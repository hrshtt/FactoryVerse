# Runtime Access Playbook

How an external process (a check-runner sub-agent, a script, Claude) talks to a running Factorio instance. **Read this before touching RCON.** Facts here were extracted from code on 2026-06-10; the smoke ritual (§0) re-proves the load-bearing ones every session — if §0 fails, fix the playbook before anything else.

## 0. Smoke ritual (run first, every session)

```python
from factorio_rcon import RCONClient
import json

rcon = RCONClient("localhost", 27100, "factorio")   # client; servers: 27000+N
rcon.send_command("/c rcon.print('ping')")           # first command may emit a warning — send twice
assert "ping" in rcon.send_command("/c rcon.print('ping')")
ifaces = json.loads(rcon.send_command(
    "/c rcon.print(helpers.table_to_json(remote.interfaces))"))
print(sorted(ifaces.keys()))
# Verified live 2026-06-10 (lab-grid): admin, agent, custom_events, entities,
# factorio_verse_docs, lab_grid, map, placement_hints, research, snapshot.
# test-ground scenario: expect 'test_ground' instead of 'lab_grid'.
# Plus 'agent_<id>' per live agent.
```

Three mods load, not two: `fv_embodied_agent`, `fv_snapshot`, **`fv_placement_hints`** (absent from CLAUDE.md's mental model). Confirm versions from scenario runtime with `script.active_mods` — it works over RCON; `game.active_mods` does NOT exist in Factorio 2.0.x.

If `remote.interfaces` is missing `agent`/`snapshot`, the mods didn't load → stop, check `factorio-current.log`.

## 1. Connection facts

| Fact | Value |
|------|-------|
| Host | `localhost` |
| Client RCON port | `27100` |
| Docker server N RCON port | `27000 + N` (container 27015 mapped out) |
| Password | `factorio` (from `.env`, `FV_RCON_PASSWORD`) |
| Detection helper | `FactorioInstanceManager.detect_active()` — tries servers 0–2 then client |
| Launch client | `uv run fv client start --scenario <test-ground\|lab-grid>` (~10–30 s to RCON-ready) |
| Launch server | `uv run fv server start --num 1 --scenario <name>` (docker compose, ~15–45 s) |
| Readiness | poll RCON connect + `/c rcon.print('ping')` every 2 s |

NOTE: CLAUDE.md says `fv client launch` — that's stale; the subcommand is `start`.

**Docker server specifics (verified live 2026-06-10):**
- Host `.fv-output/server_N` IS the container's script-output (compose volume) — snapshots at `.fv-output/server_N/factoryverse/snapshots`.
- UDP leaves the container ONLY via the socat sidecar, which forwards a fixed port list: **34202–34211 (agent) and 34400 (snapshot)** to `host.docker.internal`. `snapshot.set_udp_port` to any other port silently blackholes every sync packet inside the container — listen on the forwarded port instead of repointing. A `127.0.0.1`-bound host listener receives forwarded traffic fine.
- Headless server has **no player character** (client world has one) — don't assume a character exists.
- All certification scripts take `--instance server_N` (default `client`).

## 2. Executing Lua over RCON

- Prefix: `/c <lua>`. RCON executes in the **scenario** runtime: no `require`, no mod-local state; mod functionality only via `remote.call`.
- Return values: serialize with `rcon.print(helpers.table_to_json(expr))`, parse the response as JSON.
- Always wrap in xpcall or errors come back as raw tracebacks:

```python
LUA = """
local ok, res = xpcall(function()
  return {tick = game.tick, entity_count = #game.surfaces[1].find_entities_filtered{force='player'}}
end, debug.traceback)
if ok then rcon.print(helpers.table_to_json(res))
else rcon.print(helpers.table_to_json({error = tostring(res)})) end
"""
out = json.loads(rcon.send_command("/c " + LUA.strip()))
```

- **Big payloads**: RCON responses have buffer limits. For bulk dumps (census!), write inside Lua via `helpers.write_file("factoryverse/dumps/<name>.jsonl", ...)` and read the file from script-output instead of returning over RCON. Chunk the Lua-side iteration (the census dump should write per-chunk lines, not one giant table_to_json).

## 3. Remote interfaces

| Interface | Provider | Key methods |
|-----------|----------|-------------|
| `agent` | fv_embodied_agent mod | `create_agent`, `destroy_agents`, `list_agents` |
| `agent_<id>` | per-agent | `walk_to`, `mine_resource`, `craft_enqueue`, `place_entity`, `inspect_entity`, `get_reachable`, `get_position`, `get_inventory_items` |
| `snapshot` | fv_snapshot mod | `get_snapshot_status`, `set_udp_port` |
| `entities`, `map`, `research` | fv_snapshot mod | snapshot domain interfaces (enumerate methods via `remote.interfaces` dump) |
| `placement_hints` | fv_placement_hints mod | placement reasoning (enumerate via dump) |
| `admin`, `custom_events`, `factorio_verse_docs` | mods | admin/util surfaces (enumerate via dump) |
| `test_ground` | test-ground scenario only | `place_entity`, `place_entity_grid`, `place_resource_patch`, `place_resource_patch_circle`, `clear_area`, `reset_test_area`, `validate_entity_at`, `validate_resource_at`, `get_test_bounds`, `get_test_metadata`, ~~`force_resnapshot`~~ |

⚠️ **`test_ground.force_resnapshot` is a no-op** (verified live 2026-06-10, twice): it enqueues chunks without clearing `snapshot_tick`, so every chunk is skipped as already-snapshotted and zero files are written. Use `remote.call('map','re_snapshot_area', bounds, priority)` instead — delivers in seconds. Also: `place_entity` cannot express underground-belt `type`; place the output end via raw `create_entity{..., type='output'}`.
| `lab_grid` | lab-grid scenario only | `get_config`, `allocate_cell`, `release_cell`, `create_agent_in_cell`, `get_cell_status` |

Python wrappers: `TestGroundHelper(rcon)` in `src/FactoryVerse/game/scenarios/test_ground.py`; `LabGridAdapter(rcon)` in `lab_grid.py`. Generic call shape:

```python
cmd = f"/c local res = remote.call('test_ground','place_entity','iron-chest',{{x=10,y=10}},0,'player'); rcon.print(helpers.table_to_json(res))"
```

## 4. Reading state back — the three channels

1. **RCON inspect (fresh, per-entity)**: `remote.call('agent_<id>','inspect_entity', name, position)` or `get_reachable`. Needs an agent to exist.
2. **Raw surface scan (ground truth, no agent needed)**: `find_entities_filtered` via `/c` — the independent-truth source for census parity. Use script-output files for anything > a few hundred entities.
3. **Snapshot files / DuckDB**: snapshot JSONL lands under `<script-output>/factoryverse/snapshots/{chunk_x}/{chunk_y}/*.jsonl`; agent stats under `<script-output>/factoryverse/agent-snapshots/<agent_id>/*.jsonl`. Session DB at `.fv-output/runs/<model>/<ts>/map.duckdb` — open with `duckdb.connect(path, read_only=True)` from a second process; never read-write while a primary holds it. The ONE DB stack (after the 2026-06-10 Stack-B deletion): `SnapshotDatabase` + `SnapshotLoader` + `SyncService` (`game/infra/duckdb/{database,loader,sync}.py`). Relational entity data lives in `map_entity.raw_data` JSON; component tables exist but are unpopulated (ledger L1.5 ❌). The mod's default snapshot UDP port is **34400** (not 34500 as the port table suggests) — always `get_udp_port` before `set_udp_port`, and restore on exit.

Script-output locations: macOS Steam client → `~/Library/Application Support/factorio/script-output`; docker server N → `.fv-output/server_N/`.

## 5. Concurrency rules for check-runners

- **One writer per game area.** Live checks that mutate state must either run serially or in separate lab-grid cells (64 force-isolated 128×128 cells; allocate via `lab_grid.allocate_cell`). test-ground has no cells → strictly serial.
- Read-only probes (census scans, inspects, DB reads) may run concurrently with anything.
- DuckDB: secondary processes read-only, always.
- Don't leave state behind: `clear_area`/`release_cell` when done, or the next check's census inherits your junk.

## 6. Verdict protocol (what a check-runner returns)

Full evidence goes to files; the orchestrator gets a verdict. Write everything bulky to `.fv-output/certification/<YYYY-MM-DD>/<check-id>/` (raw dumps, diffs, logs, scripts used). Final message = exactly this shape, nothing else:

```
CHECK: L1.2
STATUS: PASS | FAIL | BLOCKED | VACUOUS-RISK
GAME: client @ lab-grid, tick 123456, commit <hash>
DID: <1-3 lines: rig built, action taken, layers compared>
EVIDENCE: <1-3 lines: the decisive numbers/diffs>
ARTIFACTS: .fv-output/certification/2026-06-10/L1.2/
AUDIT: <first run of a new harness only: answers to the 4 audit-gate questions>
LEDGER-EDIT: <the exact status-cell text to put in FLOOR_CERTIFICATION.md>
```

BLOCKED = couldn't run (no instance, missing affordance) — say what's missing. Never pad the verdict with narration; the orchestrator reads dozens of these.

**Heartbeats (mandatory for mutating checks):** before and after every phase that touches the game, append one line to `.fv-output/certification/<date>/<check-id>/progress.log`:
`<ISO-time> <phase>: <one-line, e.g. "placing rig: 3 belts + inserter at (10,10)" / "rig placed, 9 entities verified present">`.
This is the orchestrator's and the user's live lens into what you're doing — a runner that mutates silently is indistinguishable from a stuck one.

## 7. Observer lens (for the orchestrator and the user)

`uv run python scripts/certification/observe.py [--watch 5]` — read-only, safe anytime, shows: game tick, entity census by name, test-ground bounds, freshest snapshot file age, and the last heartbeat lines of recent runners. This is the standing answer to "is anything actually happening?" — run it instead of inferring from agent status. If census says the world didn't change and heartbeats are stale, the runner is stuck or still reading code; the game never lies.
