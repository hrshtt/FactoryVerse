# Scenario boot contract — deferred plan

**Status: DEFERRED.** Nothing here has been executed. Principles live in `docs/CONSTITUTION.md`.

> **Amendment 2026-08-29.** The §5 gate is decided: the observer policy is owned by `fv_embodied_agent`, `Spectator.lua` is revived, and it is exposed as a **mod setting** (settings stage), default enabled, so it can be disabled at boot and toggled later. Scenario copies drop their god-controller logic. All ten code claims in §1–§6 were re-verified against the tree on 2026-08-28 with no drift. Stage 0 also absorbs the snapshot-boot defect from `TRANSPORT_CONNECTIVITY_PLAN.md` §13, as that plan requests.

Every engine claim in this document was produced by running it against
`factoriotools/factorio:2.0.76` on 2026-08-25, not by reading code or docs. The
probes are reproduced verbatim in §7 so any reader can re-run them and void this
document's certification (§13). Where a published Factorio source contradicts a
measured result, the measured result is what is written down, and the
contradiction is named.

---

## Summary

**The freeplay campaign has never loaded a FactoryVerse freeplay scenario, and
no code path is capable of loading one.** `_build_service_config` branches on
`scenario == "freeplay"` into `--create` + `--start-server`, and `--create`
bakes base Factorio's freeplay into the save. This is not a resolution bug that
a search-path fix would repair; the scenario name is discarded before any
lookup happens.

**The observer policy exists four times and is live zero times.** A scenario
that makes joining humans non-embodied exists on a research branch, in the
developer's local Factorio directory, and inside a stale save — and a *second*,
independent implementation of the same policy sits in `fv_embodied_agent` fully
commented out. Nothing enables either.

**The mechanism underneath is underdesigned, not merely drifted.** Scenario
resolution has four different orders across three files, one of them consulting
the developer's *desktop Factorio install* to approve a *container* boot; and no
path anywhere asserts, after boot, which script actually loaded. Silence renders
identically to success (§15).

**The `--create` detour is not needed.** Its stated justification — that base's
freeplay is not below write-data and Factorio rejects an absolute path — is
accurate, and both available fixes were nonetheless missed:
`--start-server-load-scenario freeplay` against the mounted repo scenarios
directory works, and so does the documented `MOD/NAME` form `base/freeplay`.
Both were run; both booted; `--map-gen-settings`, `--map-settings` and
`--map-gen-seed` were all honoured.

**Peaceful is not the property we want, and the property we want is not the one
the docs suggest.** Measured on one seed over one identical generated area:
`peaceful_mode` alone leaves 37 enemy entities; `no_enemies_mode` — whose API
description promises no spawning "from spawners, map gen, or trigger effects" —
still leaves 11 spawners standing; only zeroing the `enemy-base` autoplace
control yields a world with zero enemy entities.

---

## 1. What actually runs today

Three entry points say "freeplay" and produce three different worlds.

| Entry point | Command it builds | Script that loads | World |
|---|---|---|---|
| `fv campaign` → `FreeplaySupervisor.start` | `--create /factorio/saves/factoryverse-initial.zip` once, then `--start-server` that save | **base freeplay** | Crash site, cutscene, intro dialog and starter items all armed but dormant; `always_day` unset; enemy autoplace zeroed by the campaign's own copied settings |
| `fv server start -s freeplay` | same branch, repo `map-gen-settings.json` | **base freeplay** | Same, but `enemy-base` at `1/1` — 37 enemy entities within 256 tiles of origin |
| `fv run` with no live instance → `_launch_client` | client `--load-scenario freeplay` | **whatever sits in the developer's `~/Library/Application Support/factorio/scenarios/freeplay`** | A stale August 8 copy of the FactoryVerse scenario, with a warning printed and the launch continuing |

The first two are proved by the artifact on disk. `.fv-output/server_0/saves/factoryverse-initial.zip` contains a 48-byte `control.lua`:

```lua
require('__base__/script/freeplay/control.lua')
```

That is base freeplay, embedded by `--create`, alongside base's full `locale/*/freeplay.cfg` set. The scenario name `"freeplay"` in `get_services(scenario=...)` never reaches a scenario lookup.

The third is proved by `factorio_client_setup.setup_client`: when the project scenarios directory has no `freeplay`, it prints `⚠️  Scenario 'freeplay' not found in project` and returns — it does not fail, and it does not remove what is already in the client's scenarios directory. The subsequent `--load-scenario freeplay` then resolves against write-data, where the August 8 copy still lives. `fv run` and `fv campaign` are therefore not running the same experiment, and neither of them is running the intended one.

### 1.1 What base freeplay does when a human joins a running campaign

The agent is a script-created character entity, not a `LuaPlayer` — the supervisor says so in `_freeplay_runtime_config`, and it is why the starter kit is injected by Tier 4 instead. So base freeplay's `on_player_created` never fires during an agent run, and `storage.init_ran` stays false.

It fires the moment a human joins to observe. At that point base freeplay, mid-run, on a world with a factory already in it:

- charts a 200-tile square around spawn,
- sets `surface.daytime = 0.7`,
- **creates a crash site at `(-5,-6)`** with debris and a wreck,
- sets `player.character.destructible = false`,
- starts a cutscene, and
- inserts the starter kit into the observer.

An observer is supposed to leave no trace. Today, watching a campaign mutates it. That is precisely the failure the FactoryVerse freeplay scenario was written to prevent.

---

## 2. Four implementations of one policy

| # | Location | Controller | Extras | Live? |
|---|---|---|---|---|
| 1 | `src/factorio/scenarios/freeplay/control.lua` on `research/s0-freeplay-20260808` (commit `236cba9`) — and the same god-controller `on_player_joined_game` block, with a log line that calls it "(spectator)", in `src/factorio/scenarios/lab-grid/control.lua:692-701` on this branch | `defines.controllers.god` | `always_day` on every surface; `factoryverse_freeplay` remote interface exposing `get_contract` v1 | **No** — the branch is not an ancestor of `HEAD`; `src/factorio/scenarios/` on this line of development holds only `lab-grid`, `lab_play`, `test-ground` |
| 2 | `~/Library/Application Support/factorio/scenarios/freeplay/control.lua` | `god` | identical bytes to #1, plus a 365 KB `blueprint.zip` and `info.json` containing `{}` | **Only for `fv run`'s client fallback**, by accident |
| 3 | `.fv-output/server_0/saves/freeplay.zip` → `freeplay/control.lua` (1344 bytes) | `god` | `always_day`; **no** remote interface — an earlier revision of #1 | **No** — nothing loads this save |
| 4 | `src/fv_embodied_agent/game_state/Spectator.lua` (322 lines) | **`defines.controllers.spectator`** | opt-in via `storage.spectator.enabled` (default `false`), plus camera-follow of an agent | **No** — every reference in `control.lua` is commented out with `-- DISABLED: Spectator logic disabled`, and no Python calls it |

Note the split: the scenario copies use the **god** controller, the mod uses the **spectator** controller, and these are materially different guarantees (§5). Four artifacts, two contradictory answers, zero of them running. There is no record of which was intended to win.

---

## 3. Why `--create` was chosen, and why it should go

The branch carries its own justification:

> The Docker image's built-in freeplay scenario is not present below write-data (`/factorio/scenarios`), and Factorio rejects an absolute scenario path as an invalid level name.

Both halves are true. Neither implies `--create`.

**Where write-data actually points, verified in the image.** `entrypoint: []` bypasses `docker-entrypoint.sh`, so the entrypoint's `sed -i '/write-data=/c\write-data=/factorio/'` never runs and write-data stays at the baked `__PATH__executable__/../..` = `/opt/factorio`. But the image ships `/opt/factorio/scenarios` as a **symlink to `/factorio/scenarios`**, which is exactly where `_build_service_config` mounts the repo scenarios directory. A bare scenario name therefore already resolves to repo scenarios today — which is why `lab-grid` and `test-ground` boot correctly and only `freeplay` does not.

**Verified: a repo scenario named `freeplay` loads.** Booting `--start-server-load-scenario freeplay` with the FactoryVerse scenario mounted produced `Checksum for script __level__/control.lua: 2100318968`, `remote.interfaces["factoryverse_freeplay"]` present, `remote.interfaces["freeplay"]` absent, `always_day = true`.

**Verified: the `MOD/NAME` form loads too.** `--start-server-load-scenario base/freeplay` booted with `remote.interfaces["freeplay"]` present and `always_day = false`.

**Verified: settings are honoured on a scenario start.** `seed = 44340`, `peaceful_mode = true`, `enemy-base = 0/0/0` all read back from `game.surfaces[1].map_gen_settings` after a scenario boot. This contradicts the still-circulating 0.17-era forum guidance that these flags only work with `--create`; that was a real bug, fixed in **0.17.48**, and the wiki's current text names `--start-server-load-scenario` for all three flags.

**What `--create` was silently buying, and why it is a defect.** The generated command guards creation with `if [ ! -s /factorio/saves/factoryverse-initial.zip ]`, and the saves volume persists across `compose down`. So the world is created once and then frozen: **any later change to seed, peaceful mode, ore richness or enemy autoplace is silently ignored.** `be1db2d` added a check that the settings *file* matches the request, which is a check on a file, not on a world (§14). Worse, `tier1_factorio.start_server` clears snapshot directories whenever `save is None` — true on this branch — so it announces a fresh boot while serving a cached world.

A scenario start has no cache: the map is generated at every boot from the mounted settings, so the settings are load-bearing by construction rather than by assertion.

**The cost of dropping `--create`.** A crash-restart of a compose service currently comes back to the same world; under a scenario start it would come back to tick 0. That is the correct trade only because the two lifecycles are already distinct: fresh boot is `--start-server-load-scenario`, and resume is `--start-server <checkpoint>.zip`, which the campaign already implements and which is unaffected. What must not survive is the middle case — a "fresh" boot that resumes a cached world nobody named. Campaign services already set `restart: "no"`; the non-campaign default `unless-stopped` needs the same treatment or an explicit statement that a restart discards the world.

---

## 4. Launching a peaceful run programmatically

### 4.1 The measurement

Same seed (`44340`), same scenario, same generated area — `request_to_generate_chunks({0,0}, 8)` then `force_generate_chunk_requests()`, i.e. a 17×17-chunk square around origin, roughly ±256 tiles — varying only `map-gen-settings.json`.

| Configuration | `no_enemies_mode` | `enemy-base` autoplace | enemy entities | spawners | worms | units |
|---|---|---|---|---|---|---|
| Repo default (`src/factorio/config/map-gen-settings.json`) | `false` | `1/1` | **37** | 11 | 8 | 18 |
| `no_enemies_mode: true` only | `true` | `1/1` | **11** | 11 | 0 | 0 |
| `enemy-base: {0,0,0}` (what the campaign supervisor writes) | `false` | `0/0` | **0** | 0 | 0 | 0 |

`peaceful_mode: true` was set in all three.

### 4.2 What the measurement means

- **`peaceful_mode` is not "no enemies."** It is "enemies do not attack unless attacked." Nests, worms and units all still generate; they still block placement and still retaliate. The system prompt's `**Peaceful Mode**: No enemies attack. Focus entirely on building.` describes the first clause and is read as the second — and the 2026-08-25 run forensics record an agent treating a nest-blocked build as a law of the world.
- **`no_enemies_mode` does not do what its API description says.** The 2.0 `MapGenSettings` field reads "Whether enemy creatures will not naturally spawn from spawners, map gen, or trigger effects." Measured, it suppressed every unit and worm and left **11 spawners standing**. Spawners collide with placement, so a world with `no_enemies_mode` alone is not a clear build site. This discrepancy is recorded here rather than resolved; if a future engine version changes it, the probe in §7 is how that is found out.
- **Zeroing the `enemy-base` autoplace control is the only setting measured to produce an empty world**, and it is what the campaign supervisor already writes in `_freeplay_map_settings`. It just never reached the world that `fv run` and `fv server start` boot, because those read the repo file, which still carries `"enemy-base": {"frequency": 1, "size": 1}`.

### 4.3 The recipe

At map generation, in the `map-gen-settings.json` that is passed to `--map-gen-settings`:

```json
"peaceful_mode": true,
"no_enemies_mode": true,
"autoplace_controls": { "enemy-base": { "frequency": 0, "size": 0, "richness": 0 } }
```

All three, deliberately. Zeroed autoplace is what empties the world; `no_enemies_mode` closes trigger-effect and spawner-driven spawning for anything that later reintroduces a spawner; `peaceful_mode` is the backstop if either is ever overridden. Each is independently checkable, which is the point.

In `map-settings.json` (passed to `--map-settings`), the repo currently ships `enemy_expansion.enabled: true` and `enemy_evolution.enabled: true`. With zero spawners both are inert, so this is belt-and-braces rather than a fix — but a run that claims "no enemies" should not leave expansion armed, and disabling them makes the claim self-evident from the config rather than derived.

**Runtime is a check, not a setting.** `LuaSurface::peaceful_mode` is read-write in 2.0, so a boot could assert-and-correct. It should assert only. A run whose world had to be corrected after generation is a run whose seed no longer describes it, and reproducibility is the whole reason the seed is pinned.

---

## 5. The observer policy: god, spectator, or neither

The user-facing requirement is: *a human who joins has no character and cannot alter the world.* The four implementations answer it two ways.

- **`defines.controllers.god`** — "the controller isn't tied to a character. This is the default controller in sandbox." No body, no reach limit, and **full ability to build, mine and modify**. It satisfies "no character." It does not satisfy "cannot alter the world."
- **`defines.controllers.spectator`** — "can't change anything in the world but can view anything." It satisfies both.

**Spectator is the correct controller**, and the FactoryVerse scenario's use of `god` should be treated as the drift, not the mod's `spectator`. The reason is not preference: under §13 a campaign is certified by what was run against what state of the world, and an observer who can build is a hole in that pair that no artifact would record. Under §15, a world silently modified by a watcher is exactly the dishonest sensor the Constitution names as worse than a missing capability.

Three details the implementation must get right, all of them visible in the existing code:

1. **Destroy the character explicitly.** `set_controller` detaches; it does not destroy. Both existing implementations capture `player.character` before the switch and destroy it after, which is correct and must be preserved — otherwise an orphaned body stands in the world, minable and collidable.
2. **`type` accepts any `defines.controllers` value.** The 2.0 runtime API declares `set_controller`'s `type` parameter as `defines.controllers` with the other parameters conditional on `character` / `cutscene` / `remote` / `editor`. `spectator` needs no additional parameters. (Only `editor` carries a restriction: it auto-promotes to admin and requires the caller be an admin.)
3. **Do not touch the agent.** The agent is a character entity with no `LuaPlayer`, so `on_player_joined_game` cannot fire for it — but the scenario version already guards on `player.connected`, and that guard should stay as the explicit statement of intent rather than an incidental truth.

**Where the policy should live is a real question, not a formality.** Both candidate homes work:

- **In the scenario.** Matches how `lab-grid` and `test-ground` already configure their worlds, and keeps the policy attached to the world it governs.
- **In `fv_embodied_agent`.** Applies to *every* world the mod loads — including save-resumed campaigns, which is the case a scenario `on_init` cannot reach — and makes the policy a property of the harness rather than of one scenario.

The mod is the better home for that second reason alone: a campaign resumed from a checkpoint boots via `--start-server <save>.zip`, where the scenario's `control.lua` is whatever was baked in at creation. If the observer policy lives only in the scenario, then fixing it does not fix already-created campaigns, and the fix is not auditable from the running world. ~~This plan proposes the mod as the owner … the choice is a gate, not a conclusion~~ **Decided 2026-08-29: the mod owns it.** `Spectator.lua` is revived; a mod setting (settings stage, default enabled) switches it on so a boot can disable it and an operator can toggle it; the scenarios become thin world-shapers (`always_day`, and nothing else) and lose their controller blocks — including `lab-grid`'s, which uses `god` while logging "spectator".

---

## 6. The actual design gap

The bug is downstream of a missing contract. Three symptoms, one cause.

**Scenario resolution has four orders and no owner.**

| Consumer | Search order | Consequence |
|---|---|---|
| `FactoryVerseConfig.validate_scenario` / `get_scenario_source` / `list_scenarios` | repo → **the host's Factorio install** → the host's user scenarios | Approves a container boot on the strength of the developer's desktop install |
| `FactorioServerManager._build_service_config` | `freeplay` → `--create`; anything else → bare name, resolved by the engine inside the container against `/opt/factorio/scenarios` → `/factorio/scenarios` | The name is discarded for exactly one value |
| `setup_client` | repo only, hash-gated; missing → **warn and continue** | Client silently runs whatever stale copy is already installed |
| The engine | write-data `scenarios/NAME`, or `MOD/NAME` | The only order that is actually authoritative, and the only one no Python consults |

`Tier2Settings._check_prerequisites` calls the first of these. So `SettingsConfig(scenario="freeplay")` passes its prerequisite check today **because the developer has Factorio installed on this Mac**, and would fail on a CI machine that has everything the container needs and nothing else.

**No boot asserts what loaded.** The campaign preflight is genuinely good — it probes the live surface for `enemy_base_frequency`, `hostile_combat_entity_count`, tick, speed and mods, and fails loudly. It does not ask which scenario script is running. It cannot, because nothing publishes that: the `factoryverse_freeplay` remote interface with its `get_contract`/`CONTRACT_VERSION` was written for exactly this purpose on the research branch and never had a caller. So the one campaign in the repo that checks its world carefully has run for months against a scenario nobody chose, and reported valid every time (§15).

**"Peaceful" means four things.** `SettingsConfig.peaceful` verifies a file; `_freeplay_map_settings` writes a different file for campaigns only; `lab-grid/control.lua` sets `map_gen_settings.peaceful_mode` and `always_day` in Lua at `on_init`; and the campaign preflight probes the live surface. Only the last is evidence.

---

## 7. Probes

Run against `factoriotools/factorio:2.0.76`, `linux/arm64`, box64, 2026-08-25. These are the certification pair for every measured claim above; re-run them before trusting this document.

```bash
# Boot with a repo scenario mounted at /factorio/scenarios (→ /opt/factorio/scenarios)
docker run -d --name fptest --platform linux/arm64 --entrypoint /bin/sh -p 27055:27015/tcp \
  -v "$S/scenarios:/factorio/scenarios" -v "$S/config:/factorio/config" \
  -v "$S/saves:/factorio/saves" -v "$S/mods:/opt/factorio/mods" \
  factoriotools/factorio:2.0.76 -c '/bin/box64 /opt/factorio/bin/x64/factorio \
    --start-server-load-scenario freeplay --port 34197 \
    --rcon-port 27015 --rcon-password test \
    --server-settings /factorio/config/server-settings.json \
    --map-gen-settings /factorio/config/map-gen-settings.json \
    --map-settings /factorio/config/map-settings.json --map-gen-seed 44340'
```

```lua
-- which script loaded
/c rcon.print(tostring(remote.interfaces["factoryverse_freeplay"] ~= nil)
           .. " " .. tostring(remote.interfaces["freeplay"] ~= nil))

-- world settings actually in force
/c local m = game.surfaces[1].map_gen_settings
   rcon.print(m.seed .. " peaceful=" .. tostring(m.peaceful_mode)
           .. " no_enemies=" .. tostring(m.no_enemies_mode))

-- enemies over a fixed, comparable area
/c local s = game.surfaces[1]
   s.request_to_generate_chunks({0,0}, 8) s.force_generate_chunk_requests()
   rcon.print(s.count_entities_filtered{force="enemy"} .. " total, "
           .. s.count_entities_filtered{force="enemy", type="unit-spawner"} .. " spawners, "
           .. s.count_entities_filtered{force="enemy", type="turret"} .. " worms, "
           .. s.count_entities_filtered{force="enemy", type="unit"} .. " units")
```

```bash
# what --create actually bakes in
unzip -p .fv-output/server_0/saves/factoryverse-initial.zip \
  factoryverse-initial/control.lua
# → require('__base__/script/freeplay/control.lua')   (48 bytes)
```

Also verified in-image, no game boot required:

```bash
docker run --rm --entrypoint /bin/sh factoriotools/factorio:2.0.76 -c \
  'ls -l /opt/factorio/scenarios; cat /opt/factorio/config-path.cfg'
# → scenarios -> /factorio/scenarios ; config-path=__PATH__executable__/../../config
```

---

## 8. The plan

Ordered so that each stage is independently checkable, and so that the honesty
fixes land before the behaviour changes they are meant to police.

**Stage 0 — make the current state legible.** No behaviour change. Add a
post-boot probe that reports which scenario script is loaded, and surface it in
campaign preflight output *without* failing on it yet. This is the check that
should have existed; running it against today's code is what turns §1 from an
argument into a record. *(Added 2026-08-29, from `TRANSPORT_CONNECTIVITY_PLAN.md`
§13:)* the same probe reports whether the world was **ingested** — charted chunks
versus chunks the snapshot mod tracks — because a world charted before the mods
were added yields 0 chunks and 0 entities while the phase machine reports
healthy. Two silences, one probe.

**Stage 1 — one resolver.** Collapse the four search orders into a single
resolution function with an explicit, stated precedence, and remove the host
Factorio install from any path that decides a *container* boot. A scenario the
container cannot see must not pass a prerequisite check. `setup_client`'s
missing-scenario warning becomes a failure: a client that silently runs a stale
scenario is the same class of defect as a server that silently runs a cached
world.

**Stage 2 — restore the scenario, delete the `--create` branch.** Bring the
freeplay scenario onto this line of development (recoverable from `236cba9`, or
authored fresh — see the Stage 4 gate on what it should contain). Replace the
`elif scenario == "freeplay"` branch with the same
`--start-server-load-scenario` path every other scenario uses. Delete the
cached-initial-save mechanism and the `if [ ! -s … ]` guard with it. Two
existing unit assertions change and must be rewritten rather than relaxed:
`test_freeplay_creates_native_save_and_uses_correct_custom_mount` asserts the
branch this stage removes, and
`test_isolated_freeplay_restores_private_mod_list_between_startup_phases`
asserts `command.count(restore) == 2` for the two-phase create/start startup,
which becomes one phase.

**Stage 3 — make the settings load-bearing.** Bring
`src/factorio/config/map-gen-settings.json` to §4.3, so `fv run` and
`fv server start` produce the world their prompt describes. Turn the campaign
preflight's existing `no_enemies_mode` read into an assertion alongside the
`enemy_base_frequency` and `hostile_combat_entity_count` checks it already
makes. Amend the system prompt line — `No enemies attack` is a claim about
behaviour that survives even in a world with nests; if the world has none, say
that instead, and if it has some, say what they block.

**Stage 4 — one observer policy.** *Decided 2026-08-29: the mod.* Revive
`Spectator.lua`; add a settings-stage setting (default enabled) that its
`on_player_joined_game` handler reads, so the policy is a property of the
harness and can be disabled or toggled; remove the god-controller blocks from
every scenario (`lab-grid` included); delete the other three artifacts rather
than leaving them as candidates. The stale local copy at
`~/Library/Application Support/factorio/scenarios/freeplay` and the baked copy
in `.fv-output/server_0/saves/freeplay.zip` stop being reachable by any launch
path.

**Stage 5 — turn Stage 0's probe into a gate.** Campaign preflight fails when
the loaded scenario is not the one the manifest names. The manifest already
hashes mods, map-gen settings, prototype data and the Tier 4 runtime; the
scenario contract is the missing entry, and it belongs in `hashes` next to
`server_mod_list`.

### Gates

- ~~**Which layer owns the observer policy** (§5).~~ Decided 2026-08-29: the mod,
  behind a setting. No longer a gate.
- **Whether a non-campaign server restart may discard its world** (§3). If not,
  the `unless-stopped` default needs replacing with supervisor-owned lifecycle,
  not a cached save. Blocks Stage 2's deletion of the cache.
- **Whether the FactoryVerse freeplay scenario replaces base freeplay entirely
  or wraps it.** Today's research-branch scenario replaces it: no crash site, no
  starter kit, no silo/victory script, no `freeplay` remote interface. The
  campaign already injects the starter kit through Tier 4 and does not want the
  crash site, so replacement looks right — but `game.set_win_ending_info` and
  the rocket-launch completion path go with it, and nothing in the repo has
  decided whether a freeplay campaign has a win condition. Blocks Stage 2's
  choice of scenario contents.

---

## 9. Checks this plan owes

Following §13: each claim below names the check that would certify it. None of
these exist yet.

| Claim | Check |
|---|---|
| The scenario the manifest names is the scenario that booted | Live: `remote.call` the scenario contract interface after boot, compare to manifest |
| A fresh campaign boot generates its map from the mounted settings | Live: change the seed, boot twice, assert the worlds differ |
| A joining human alters nothing | Live: fingerprint entities before and after a real client join |
| A joining human has no character | Live: assert `player.character == nil` and `controller_type == spectator`; and with the setting disabled, that neither holds |
| The world was ingested, not merely charted | Live: charted-chunk count versus tracked-chunk count after boot on a pre-built save (`TRANSPORT_CONNECTIVITY_PLAN.md` §13) |
| The world contains no enemies | Live: the §7 fixed-area count, asserted at zero — preflight already computes it |
| Every scenario the config approves is one the container can load | Unit: resolution against a fixture tree, with the host install absent |
| `setup_client` fails on a missing project scenario | Unit |

The live checks belong in `tests/live/`, which already skips offline. The two
unit checks replace the two assertions Stage 2 invalidates, so unit coverage of
this path does not go down while it is being changed.

---

## 10. What this plan does not do

- **It does not design the campaign lifecycle.** Checkpoint, resume and lease
  are out of scope; the only claim made about them is that
  `--start-server <save>.zip` is untouched by every stage here.
- **It does not decide the freeplay win condition.** Named as a gate, not
  answered.
- **It does not touch the agent's affordances.** Nothing here changes what the
  agent may do; it changes only what world it does it in, and who else can
  touch that world.
- **It does not reconstruct why the four implementations diverged.** The record
  was deliberately removed and is not being rebuilt from memory. What is written
  here is what the artifacts on disk say today.
