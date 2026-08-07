"""Codex CLI adapter for supervised FactoryVerse freeplay campaigns.

Codex owns planning and files in its workspace. The trusted freeplay supervisor
owns the embodied actor, runtime lifecycle, checkpoints, budgets, and teardown.
The adapter communicates with Codex over ordinary subprocess pipes; it does not
use a pseudo-terminal and never exposes supervisor operations as actor tools.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from FactoryVerse.integrations.codex import CodexAppServer, CodexAppServerError
from .actor_session import ActorRuntimeSession
from .codex_context import (
    FREEPLAY_DEVELOPER_INSTRUCTIONS,
    INTERACTABLE_STATE_FILENAME,
    InteractableStateFile,
)
from .models import utc_now
from .provenance import canonical_json_sha256, sha256_file
from FactoryVerse.utils.docs.bundle import write_reference_bundle


ACTION_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "state_summary": {"type": "string"},
        "action": {"type": "string", "enum": ["execute", "report_complete"]},
        "code": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["state_summary", "action", "code", "reason"],
    "additionalProperties": False,
}


RUN_BRIEF = """# FactoryVerse Codex Freeplay Brief

You are the sole embodied actor in one enemy-free Factorio freeplay campaign.
Make open-ended factory progress: gather resources, automate production,
research, expand capacity, and work toward launching a rocket.

Each turn, return exactly one structured action:

- `execute`: submit one complete Python block to the persistent live runtime.
- `report_complete`: tell the supervisor that you believe this bounded run
  should stop. This is advisory; the supervisor owns finalization.

For `execute`, put the complete Python block in `code`. Top-level `await` is
supported. Variables and functions persist within a runtime session. Across a
campaign resume, files persist but Python object references do not; rediscover
game objects from stable names, types, and positions.

You cannot checkpoint, reset, spawn actors, close the runtime, call Docker,
RCON, Lua, or administrative interfaces. The supervisor checkpoints on its own
cadence, enforces budgets, and owns cleanup. Do not try to operate campaign
lifecycle through shell commands or by editing harness artifacts.

Read `references/INDEX.md`, `EARLY_GAME_MECHANICS.md`, `CAMPAIGN_START.json`,
and `last-observation.json`. Follow the index to load only the API/schema files
needed for the current task; the complete monolithic references remain
available as fallbacks. If `MISSION.md` exists, treat it as the bounded goal
for this campaign. `CAMPAIGN_START.json` is an immutable launch snapshot, not
current state after actions. Use DuckDB/RemoteView for map-scale perception and the
embodied Python interfaces for actions. Learn from runtime errors and inspect
before acting. Do not claim an action occurred unless runtime output confirms
it. Successful runtime `execute` and `status` responses include `game_events`;
treat a `research_finished` event as an authoritative capability change and
add its recipes and effects to the available option set. Do not abandon a sound
in-progress build merely because a technology unlocked. You may create plans,
reusable Python helpers, and other memory files in this workspace.

Use `BUGS.md` as the durable bug ledger. Record suspected runtime or harness
defects with expected behavior, actual behavior, exact evidence, reproduction,
and status. Do not attempt to edit FactoryVerse product source: diagnose and
record the issue, then continue safely when possible. Files in this isolated
workspace are plans, evidence, and reusable agent helpers—not product patches.

Keep `state_summary` concise but durable. Put why this particular action is the
best next step in `reason`. For `report_complete`, `code` must be an empty
string.

One response contains one complete Python program; it is not limited to one
game operation. Batch causally safe queries, crafting, validation, movement,
placement, and verification in the same program. Use bounded loops for
candidate searches. Do not spend separate turns guessing individual
coordinates or acquiring individual recipe ingredients when the complete
batch can be planned safely.
"""


INITIAL_PROMPT = """Begin this FactoryVerse freeplay run.

Read MISSION.md when present, EARLY_GAME_MECHANICS.md, CAMPAIGN_START.json,
BUGS.md, last-observation.json, and references/INDEX.md. Read the current
harness-owned interactable state at
`../harness-control/current-interactable-state.json` before proposing a local
interaction.
Do not re-query facts already established by the campaign-start snapshot;
perform only reconnaissance needed to choose or validate a concrete build.
Use your files for plans and reusable skills if useful. Return one structured
response containing the next complete Python program, which may perform
multiple related game operations. Do not attempt to control the campaign
lifecycle yourself.
"""


def initial_prompt(task_objective: str) -> str:
    """Supply the immutable task once while keeping Codex Goals disabled."""
    return (
        "Campaign objective:\n\n"
        f"{task_objective.strip()}\n\n"
        f"{INITIAL_PROMPT}"
    )


EARLY_GAME_MECHANICS = """# Early-Game Mechanics and Harness Events

These are authoritative mechanics for this campaign.

## Triggered research

Early technologies complete from production triggers; do not queue them in a
laboratory:

- Producing 50 iron plates completes `steam-power`.
- Producing 10 copper plates completes `electronics`.
- Crafting one lab completes `automation-science-pack` after `steam-power` and
  `electronics` are complete.

When a trigger completes, the harness delivers one `research_finished` event
either in the current execution's `runtime_response.game_events` or as an
inter-turn `game_events` observation. The payload names the technology,
unlocked recipes, and effects. Treat it as an authoritative capability change
and record the new options. Continue a sound in-progress build unless an unlock
materially improves it or removes its blocker; an unlock is an option, not an
instruction to pivot.

If a trigger is confirmed but its event is absent, query technology and recipe
state once, record exact evidence in `BUGS.md`, and continue from observed
capability state. Do not repeatedly recreate the threshold.

## Placement and inventory mechanics

`CAMPAIGN_START.json`'s `nearest_water_tile.position` and every row returned by
`remote_view.find_water()` are water-tile search hints only. Water tiles are not
walkable destinations and are not validated offshore-pump anchors. Never pass a
water-tile position to `walking.walk_to()` and never place a pump at that raw
position.

Before travelling to build power, call
`placement_hints.find_offshore_pump_sites(near=water_hint, ...)`. Each returned
site supplies the exact live-validated pump placement position and required
direction plus an engine-derived standable `approach_position` within build
reach. Walk to `site.approach_position`, then place at `site.position` with
`site.direction` unchanged. Never walk directly to `site.position`. If no site
is returned, expand the search or choose another water cluster instead of
probing placements. If one supplied approach point is not path-reachable from
your current region, try the next returned site before changing clusters.

For other entities, use placement hints or the validator instead of spending
one turn per guessed coordinate.

Furnaces select their smelting recipe automatically from inserted ore. Do not
call `set_recipe` on a furnace; insert ore and fuel, then verify its live state.

`inventory.create_item_stacks(name, count, number_of_stacks=...)` uses `count`
per stack. When transferring an exact quantity, request one stack explicitly;
use `number_of_stacks="max"` only when intentionally consuming as many complete
stacks as possible.
"""


BUG_LEDGER_TEMPLATE = """# FactoryVerse Bug Ledger

This file is mutable, agent-owned diagnostic memory. Do not edit FactoryVerse
product source. For each suspected defect, add an entry using this shape:

## BUG-NNN: Short title

- Status: open | investigating | resolved-by-observation | blocked
- First observed: turn and game tick
- Expected:
- Actual:
- Evidence: exact runtime output, event payload, or query result
- Reproduction:
- Impact:
- Next safe check:

## Entries

"""


NOTIFICATION_DEBUG_MISSION = """# Notification Debug Mission

This is a bounded harness-debugging run, not an open-ended rocket run.

Using only the supplied raw ores, coal, stone, and normal starter equipment:

1. Smelt at least 50 iron plates and confirm whether a `research_finished`
   event for `steam-power` appears in `last-observation.json`/`game_events`.
2. Smelt at least 50 copper plates. The vanilla electronics threshold is 10;
   confirm whether its single `research_finished` event appears.
3. Craft one lab from intermediates you produce, then confirm whether the
   `automation-science-pack` research event appears and its recipe is enabled.

Track every expected event as seen, missing, or ambiguous in
`notification-report.md`. Put any discrepancy in `BUGS.md` with exact evidence.
Do not modify FactoryVerse source code or lifecycle state. Report complete only
after all three trigger outcomes have been checked.
"""


OFFSHORE_PUMP_DEBUG_MISSION = """# Offshore Pump and Water Affordance Debug Mission

This is a bounded harness-debugging run, not a factory progression run.

Use only the documented public embodied interfaces and the supplied finite test
items. Exercise the intended water and offshore-pump workflow without manually
guessing shoreline offsets or probing placements:

1. Read the campaign-start nearest-water entry and confirm that it is only a
   search hint—not a walking target or validated pump anchor.
2. Call `remote_view.find_water()` and use a returned water tile only as the
   search center for `placement_hints.find_offshore_pump_sites()`.
3. Inspect multiple returned sites. Confirm that each includes a canonical
   half-tile `position`, required `direction`, and standable
   `approach_position`, and that results are nearest-first.
4. Walk to a supplied `approach_position`, never the water hint or
   `site.position`. If that approach is unreachable, try the next returned site.
5. Place the supplied offshore pump at `site.position` with `site.direction`
   unchanged. Confirm the persisted entity position matches the returned site
   and live inspection reports water as its fluid source.
6. Use connection hints to attach at least one supplied pipe and inspect the
   resulting pump/pipe fluid state. Do not hand-compute the connection.

Record exact calls, returned coordinates, walking result, placed entity state,
and connection evidence in `offshore-pump-report.md`. Put any discrepancy in
`BUGS.md` with exact evidence. Do not modify FactoryVerse source or lifecycle
state. Report complete only after the public path has either succeeded or
produced a precise reproducible failure.
"""


FACTORY_DEBUG_MISSION = """# Factory Bootstrap and Scaling Debug Mission

This is an open-ended long-horizon factory run. Your objective is to discover a
reliable bootstrap strategy from the live game, execute it, and continually
scale the factory toward a rocket. Do not stop merely because an early
milestone is complete.

## How to think

Begin from `CAMPAIGN_START.json`; do not repeat its launch reconnaissance.
Inspect only volatile or missing facts needed to validate a concrete build.
Use the supplied routed API/schema references and confirmed runtime output as
evidence. Record durable conclusions so later turns compound rather than
rediscover them.

The character's attention is the scarcest early resource. Spend manual work to
install, start, extend, or restore production that will continue while the
character moves and builds elsewhere. Judge progress by useful production rate,
time to the next required intervention, and construction surplus—not by the
mere existence of one machine, one recipe, or one completed technology.

Treat the factory as a portfolio of simultaneous productive flows. Mining,
smelting, construction materials, intermediates, and science should keep doing
useful work in parallel whenever their inputs and outputs permit. A flow is not
meaningfully autonomous unless it has all of:

- a replenishing input and fuel path,
- operating production machines,
- an output escape path into consumption, a belt, or a buffer, and
- enough input and output capacity to remain useful while attention is away.

Estimate this autonomy horizon qualitatively: what will stop next, why, and how
soon? Belts and machine inventories are buffers too. Use buffers to decouple
producers from intermittent consumers, but do not confuse stored stock with
replenishment rate or force a healthy flow through a needless chest bottleneck.

Use this repeated operating loop:

1. Maintain a compact factory balance sheet in `PROGRESS.md`: industrial stage,
   installed and active productive capacity, starved or blocked machines,
   fuel/output autonomy, material and construction reserves, and useful work
   currently in flight.
2. Preserve existing production. Service imminent fuel or output failures in a
   grouped round when practical, without draining self-fueling systems below
   their operating reserve.
3. Choose the investment that most improves future unattended production,
   construction optionality, or readiness for the next industrial stage.
   Prefer replicating a verified productive module over creating an isolated
   demonstration machine.
4. Execute the largest coherent expansion current knowledge and inventory make
   safe. Include its inputs, fuel, output handling, placement, startup, and
   verification where causally possible.
5. Verify sustained operation in the live engine, record the capacity delta,
   and decide whether to replicate, extend, connect, or transition. Do not infer
   production from successful placement alone.

Prefer reusable Python helpers and data-driven placement over long repetitive
blocks. Keep enough space and modularity for extensions, but favor a working
production loop over speculative perfect layouts. Preserve and extend useful
infrastructure instead of repeatedly rebuilding from scratch.

Maintain forward pressure. Do not let inspection, local diagnosis, or repeated
servicing become the whole turn when a safe repair and the next expansion can be
combined. While planning or travelling, keep useful construction hand-crafting
queued whenever ingredients and inventory space permit: prioritize the drills,
furnaces, belts, inserters, chests, assemblers, and power equipment needed by the
next coherent build. Do not consume scarce construction inputs on large manual
batches of science or intermediates merely to keep the handcrafting queue busy.
When practical, combine crafting, resource acquisition, construction, fueling,
startup, and verification in one causally ordered Python program so waiting and
travel overlap productive work.

Manual mining and hand-feeding are bootstrap and recovery tools, not steady
production plans. Use them when they are the fastest way to install or restore
productive capacity, when a required material has no working flow yet, or when
waiting for the automated flow would stall the whole expansion. Otherwise
collect from, service, and expand the installed factory instead.

## Early passive-fuel bootstrap

Burner mining drills placed on coal can form self-fueling loops: arrange drill
outputs so the drills feed one another and seed the loop with a small amount of
fuel. A closed loop that fills its drill inventories and stops is self-preserving
but is not yet a useful passive fuel supply. Verify orientation and operating
reserve, then give surplus coal an escape path into a belt, chest, downstream
consumer, or a safe grouped collection routine. Extend the escape path or output
capacity when it limits the autonomy horizon.

Use that coal to support several useful primitive flows as materials permit:
coal and stone extraction with output capacity, and iron/copper drill-and-
furnace cells or equivalent ore-to-plate flows with fuel and output handling.
Replicate working cells instead of treating one cell per material as adequate.
Do not impose a fixed ratio blindly; scale the flows that increase sustained
construction-material production and keep the whole burner economy operating.

## Industrial stages and transitions

Stages describe the factory's operating regime, not a rigid build order or a
checkbox satisfied by one machine. Keep useful capacity from the previous stage
running until its replacement is connected and verified.

1. **Embodied bootstrap:** obtain only the manual resources needed to start a
   self-preserving fuel source and the first productive cells.
2. **Distributed burner expansion:** multiply mining and smelting cells, add
   input/output capacity, and accumulate stone, coal, plates, and construction
   equipment while the character works elsewhere.
3. **Power and logistics readiness:** assemble enough materials and confirm a
   viable water, boiler, generator, and pole layout. Establish power without
   unnecessarily idling the burner economy.
4. **Hybrid transition:** add electric miners, belts, and centralized processing
   alongside working primitive cells. Expand and validate the new flow before
   retiring or neglecting the old one.
5. **Compounding automation:** automate construction intermediates and science;
   replicate production sections and keep research supplied when the upstream
   economy can do so without exhausting the construction reserve.
6. **Advanced expansion:** use the same operating doctrine for steel, improved
   mining and smelting, oil, chemical chains, higher science, and rocket
   infrastructure.

An unlocked technology changes what is possible; it does not prove that a
transition is affordable. Before adding a new consumer, confirm that its
upstream flows can support it while still accumulating the materials needed to
expand. Research may run continuously when supported by genuine surplus, but
research activity is not a substitute for economic growth.

Because enemies are disabled, do not spend capacity on defenses unless a live
observation proves they are required.

## Durable debugging

Use `BUGS.md` for every suspected runtime or harness defect. Include exact
turn/tick evidence, expected versus actual behavior, a safe reproduction, and
the impact on progress. Never edit FactoryVerse product source. Work around a
bug when safe and keep advancing. Update `PROGRESS.md` at least every ten
executed actions and after every major research or production milestone.

Only use `report_complete` after a rocket is confirmed launched, or when a
specific unrecoverable blocker is supported by evidence and recorded in
`BUGS.md`. Reaching an intermediate milestone is not completion.
"""


FACTORY_PLAN_TEMPLATE = """# Factory Plan

This is agent-owned planning memory. Revise it as live evidence changes.

## Operating objective

Compound useful unattended production and construction capacity toward the next
affordable industrial transition.

## Current industrial stage and readiness

- Stage: unknown until the first targeted validation
- Evidence supporting this stage:
- Missing conditions for the next stage:

## Confirmed constraints

- Add only facts confirmed by runtime output or workspace references.

## Productive flows to preserve

- Record each useful flow, what keeps it running, and what will require the next
  intervention.

## Next capacity investment

- Build: unknown until the first targeted validation
- Expected durable gain:
- Inputs and construction reserve required:
- Input, fuel, and output path:
- Verification of sustained operation:

## In-flight useful work

- Hand-crafting queue:
- Machines producing while the character moves or plans:

## Transition horizon

- Preserve or replicate before transitioning:
- Technology options worth using when affordable:
- Later objective after the next investment:
"""


PROGRESS_LOG_TEMPLATE = """# Factory Progress

Update this durable log at least every ten executed actions and after major
research or production milestones.

## Factory balance sheet

- Turn: 0
- Game tick: unknown
- Industrial stage: not established
- Fuel flow and autonomy horizon: not inspected
- Raw extraction, installed/active/blocked: not inspected
- Smelting, installed/active/starved/blocked: not inspected
- Logistics and power: not inspected
- Construction reserves and replenishment: not inspected
- Intermediates and science: not inspected
- Research and newly available options: not inspected
- Useful hand-crafting or machine work in flight: none recorded
- Manual production debt: identify recurring manual work that should become a
  productive flow

## Next intervention risks

- What will stop first, why, and how soon: unknown
- Productive flows that must be preserved during the next build: unknown

## Latest verified capacity delta

- Added, activated, replicated, or connected:
- Sustained-operation evidence:
- Remaining starvation or output blockage:

## Growth history

"""


FOLLOWUP_PROMPT = """Continue the same FactoryVerse freeplay run.

Read last-observation.json for the trusted result of your previous action and
read `../harness-control/current-interactable-state.json` before any next action
whose validity depends on local interaction. The harness has replaced that file
with the current snapshot; do not edit it or rely on an older snapshot.
Return the next coherent batch of work, not merely the next primitive game
operation. Preserve useful flows, update the factory balance sheet, and prefer a
capacity investment that increases unattended production or construction
optionality. Treat technology unlocks as options, not automatic pivots. Update
workspace plans or reusable helpers when useful. If an execution failed,
diagnose it from the recorded output rather than assuming it succeeded, then
combine a safe repair with forward progress when practical. Campaign lifecycle
remains supervisor-owned.
"""


class CodexRunnerError(RuntimeError):
    """The coding harness failed before producing a valid actor action."""


@dataclass(frozen=True)
class CodexInvocation:
    action: Dict[str, str]
    thread_id: str
    returncode: int


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True, default=str) + "\n")


def _validate_action(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        raise CodexRunnerError("Codex final response is not a JSON object")
    expected = {"state_summary", "action", "code", "reason"}
    if set(value) != expected:
        raise CodexRunnerError(
            "Codex action fields differ from the required schema: "
            f"expected {sorted(expected)}, got {sorted(value)}"
        )
    if any(not isinstance(value[field], str) for field in expected):
        raise CodexRunnerError("Every Codex action field must be a string")
    if value["action"] not in {"execute", "report_complete"}:
        raise CodexRunnerError(f"Unsupported Codex action: {value['action']!r}")
    if value["action"] == "execute" and not value["code"].strip():
        raise CodexRunnerError("Codex execute action contains no Python source")
    if value["action"] == "report_complete" and value["code"].strip():
        raise CodexRunnerError("Codex report_complete action must have empty code")
    if not value["reason"].strip():
        raise CodexRunnerError("Codex action reason must not be empty")
    return {field: value[field] for field in expected}


class CodexCliClient:
    """Legacy ``codex exec`` adapter retained for old campaign compatibility."""

    def __init__(
        self,
        *,
        executable: str,
        model: str,
        workspace: Path,
        control_dir: Path,
        timeout_seconds: float,
    ):
        self.executable = executable
        self.model = model
        self.workspace = Path(workspace)
        self.control_dir = Path(control_dir)
        self.timeout_seconds = timeout_seconds

    async def version(self) -> str:
        try:
            process = await asyncio.create_subprocess_exec(
                self.executable,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise CodexRunnerError(
                f"Codex executable was not found: {self.executable}"
            ) from exc
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15.0)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise CodexRunnerError(
                "Timed out while checking Codex CLI version"
            ) from exc
        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            raise CodexRunnerError(f"Codex version check failed: {message}")
        return stdout.decode("utf-8", errors="replace").strip()

    async def invoke(
        self,
        *,
        turn: int,
        thread_id: Optional[str],
    ) -> CodexInvocation:
        response_path = self.control_dir / "responses" / f"turn-{turn:06d}.json"
        response_path.parent.mkdir(parents=True, exist_ok=True)
        response_path.unlink(missing_ok=True)
        schema_path = self.control_dir / "next-action.schema.json"

        common = [
            "--model",
            self.model,
            "--config",
            'sandbox_mode="workspace-write"',
            "--skip-git-repo-check",
            "--ignore-user-config",
            "--ignore-rules",
            "--output-schema",
            str(schema_path.resolve()),
            "--json",
            "--output-last-message",
            str(response_path.resolve()),
        ]
        if thread_id:
            command = [
                self.executable,
                "exec",
                "resume",
                *common,
                thread_id,
                FOLLOWUP_PROMPT,
            ]
        else:
            command = [
                self.executable,
                "exec",
                "--cd",
                str(self.workspace.resolve()),
                *common,
                INITIAL_PROMPT,
            ]

        _append_jsonl(
            self.control_dir / "runner-events.jsonl",
            {
                "event": "codex_invocation_started",
                "recorded_at": utc_now(),
                "turn": turn,
                "resuming_thread_id": thread_id,
                "command_shape": "resume" if thread_id else "initial",
            },
        )
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=self.workspace,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise CodexRunnerError(
                f"Codex executable was not found: {self.executable}"
            ) from exc

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
            raise CodexRunnerError(
                f"Codex turn {turn} exceeded {self.timeout_seconds:.1f}s"
            ) from exc

        self._append_bytes(self.control_dir / "codex-events.jsonl", stdout)
        self._append_bytes(self.control_dir / "codex-stderr.log", stderr)
        parsed_thread_id = thread_id
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "thread.started" and event.get("thread_id"):
                parsed_thread_id = str(event["thread_id"])

        _append_jsonl(
            self.control_dir / "runner-events.jsonl",
            {
                "event": "codex_invocation_finished",
                "recorded_at": utc_now(),
                "turn": turn,
                "returncode": process.returncode,
                "thread_id": parsed_thread_id,
                "stdout_bytes": len(stdout),
                "stderr_bytes": len(stderr),
            },
        )
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()[-2000:]
            raise CodexRunnerError(
                f"Codex turn {turn} exited with {process.returncode}: {detail}"
            )
        if not parsed_thread_id:
            raise CodexRunnerError("Codex emitted no thread.started identifier")
        if not response_path.exists():
            raise CodexRunnerError(
                f"Codex turn {turn} produced no final response artifact"
            )
        try:
            action = _validate_action(
                json.loads(response_path.read_text(encoding="utf-8"))
            )
        except json.JSONDecodeError as exc:
            raise CodexRunnerError(
                f"Codex turn {turn} final response is not valid JSON"
            ) from exc
        return CodexInvocation(
            action=action,
            thread_id=parsed_thread_id,
            returncode=int(process.returncode),
        )

    @staticmethod
    def _append_bytes(path: Path, payload: bytes) -> None:
        if not payload:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("ab") as handle:
            handle.write(payload)
            if not payload.endswith(b"\n"):
                handle.write(b"\n")


class CodexAppServerActionClient:
    """Freeplay action adapter over the reusable Codex app-server transport."""

    def __init__(
        self,
        *,
        executable: str,
        model: str,
        workspace: Path,
        control_dir: Path,
        timeout_seconds: float,
        task_objective: str,
        developer_instructions: str = FREEPLAY_DEVELOPER_INSTRUCTIONS,
    ):
        self.executable = executable
        self.model = model
        self.workspace = Path(workspace)
        self.control_dir = Path(control_dir)
        self.timeout_seconds = timeout_seconds
        self.task_objective = task_objective.strip()
        if not self.task_objective:
            raise ValueError("task_objective must not be empty")
        self.developer_instructions = developer_instructions
        self._thread_id: Optional[str] = None
        self._server = CodexAppServer(
            executable=executable,
            request_timeout_seconds=min(timeout_seconds, 30.0),
            event_log_path=self.control_dir / "codex-app-server.jsonl",
            stderr_path=self.control_dir / "codex-stderr.log",
            client_name="factoryverse-freeplay",
            disabled_features=("goals",),
        )

    async def version(self) -> str:
        return await self._server.version()

    async def start(self) -> Dict[str, Any]:
        return await self._server.start()

    async def close(self) -> None:
        await self._server.close()

    async def invoke(
        self,
        *,
        turn: int,
        thread_id: Optional[str],
    ) -> CodexInvocation:
        active_thread = await self._ensure_thread(thread_id)
        prompt = FOLLOWUP_PROMPT if thread_id else initial_prompt(self.task_objective)
        _append_jsonl(
            self.control_dir / "runner-events.jsonl",
            {
                "event": "codex_invocation_started",
                "recorded_at": utc_now(),
                "turn": turn,
                "resuming_thread_id": thread_id,
                "thread_id": active_thread,
                "command_shape": "app_server_turn",
            },
        )
        try:
            result = await self._server.run_turn(
                thread_id=active_thread,
                prompt=prompt,
                output_schema=ACTION_SCHEMA,
                timeout_seconds=self.timeout_seconds,
            )
            action = _validate_action(json.loads(result.text))
        except (asyncio.TimeoutError, json.JSONDecodeError, CodexAppServerError) as exc:
            raise CodexRunnerError(
                f"Codex app-server turn {turn} failed: {exc}"
            ) from exc
        _write_json(
            self.control_dir / "responses" / f"turn-{turn:06d}.json",
            action,
        )
        _append_jsonl(
            self.control_dir / "runner-events.jsonl",
            {
                "event": "codex_invocation_finished",
                "recorded_at": utc_now(),
                "turn": turn,
                "returncode": 0,
                "thread_id": result.thread_id,
                "turn_id": result.turn_id,
            },
        )
        return CodexInvocation(
            action=action,
            thread_id=result.thread_id,
            returncode=0,
        )

    async def _ensure_thread(self, thread_id: Optional[str]) -> str:
        if self._thread_id is not None:
            if thread_id not in (None, self._thread_id):
                raise CodexRunnerError(
                    "Stored Codex thread differs from the active app-server thread"
                )
            return self._thread_id
        if thread_id:
            active = await self._server.resume_thread(
                thread_id,
                cwd=self.workspace,
                developer_instructions=self.developer_instructions,
                model=self.model,
            )
        else:
            active = await self._server.start_thread(
                cwd=self.workspace,
                developer_instructions=self.developer_instructions,
                model=self.model,
            )
        self._thread_id = active
        return active


def codex_harness_configuration(
    *,
    codex_version: str,
    max_turns: int,
    checkpoint_every: int,
    codex_timeout: float,
    execution_timeout: float,
    maximum_execution_timeout: float,
    notification_debug: bool = False,
    offshore_pump_debug: bool = False,
    factory_debug: bool = False,
) -> Dict[str, Any]:
    """Return the immutable Codex-side configuration stored in the manifest."""
    return {
        "adapter": "FactoryVerse.evals.freeplay.codex_runner",
        "adapter_protocol_version": 4,
        "codex_version": codex_version,
        "transport": "codex-app-server-jsonrpc",
        "action_schema_sha256": canonical_json_sha256(ACTION_SCHEMA),
        "run_brief_sha256": hashlib.sha256(RUN_BRIEF.encode("utf-8")).hexdigest(),
        "developer_instructions_sha256": hashlib.sha256(
            FREEPLAY_DEVELOPER_INSTRUCTIONS.encode("utf-8")
        ).hexdigest(),
        "interactable_state": {
            "path": f"harness-control/{INTERACTABLE_STATE_FILENAME}",
            "ownership": "harness",
            "update": "atomic_replace",
        },
        "max_turns": max_turns,
        "checkpoint_every": checkpoint_every,
        "codex_timeout_seconds": codex_timeout,
        "execution_timeout_seconds": execution_timeout,
        "maximum_execution_timeout_seconds": maximum_execution_timeout,
        "notification_debug": notification_debug,
        "offshore_pump_debug": offshore_pump_debug,
        "factory_debug": factory_debug,
    }


def supervisor_owned_codex_configuration(
    configuration: Dict[str, Any], task_objective: str
) -> Dict[str, Any]:
    """Bind one task to a manually driven Codex adapter configuration."""
    task_objective = task_objective.strip()
    if not task_objective:
        raise ValueError("task_objective must not be empty")
    bound = dict(configuration)
    bound.update(
        {
            "adapter_protocol_version": 4,
            "goal_api": False,
            "codex_goals_feature": False,
            "turn_owner": "factoryverse-supervisor",
            "task_objective_sha256": hashlib.sha256(
                task_objective.encode("utf-8")
            ).hexdigest(),
        }
    )
    return bound


class CodexFreeplayRunner:
    """Drive one supervised actor from one resumable Codex thread."""

    def __init__(
        self,
        supervisor: Any,
        client: Any,
        *,
        max_turns: int,
        checkpoint_every: int,
        execution_timeout: float,
        maximum_execution_timeout: float,
        notification_debug: bool = False,
        offshore_pump_debug: bool = False,
        factory_debug: bool = False,
    ):
        if max_turns < 1:
            raise ValueError("max_turns must be at least 1")
        if checkpoint_every < 0:
            raise ValueError("checkpoint_every cannot be negative")
        self.supervisor = supervisor
        self.client = client
        self.max_turns = max_turns
        self.checkpoint_every = checkpoint_every
        self.notification_debug = notification_debug
        self.offshore_pump_debug = offshore_pump_debug
        self.factory_debug = factory_debug
        if sum((notification_debug, offshore_pump_debug, factory_debug)) > 1:
            raise ValueError("Codex debug profiles are mutually exclusive")
        self.actor = ActorRuntimeSession(
            supervisor,
            default_timeout=execution_timeout,
            maximum_timeout=maximum_execution_timeout,
        )
        self.workspace = client.workspace
        self.control_dir = client.control_dir
        self.interactable_state = InteractableStateFile(
            self.control_dir / INTERACTABLE_STATE_FILENAME
        )

    def prepare_workspace(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.control_dir.mkdir(parents=True, exist_ok=True)
        self._write_static(self.workspace / "RUN_BRIEF.md", RUN_BRIEF)
        self._write_static(
            self.workspace / "EARLY_GAME_MECHANICS.md", EARLY_GAME_MECHANICS
        )
        self._seed_mutable(self.workspace / "BUGS.md", BUG_LEDGER_TEMPLATE)
        if self.notification_debug:
            self._write_static(
                self.workspace / "MISSION.md", NOTIFICATION_DEBUG_MISSION
            )
        elif self.offshore_pump_debug:
            self._write_static(
                self.workspace / "MISSION.md", OFFSHORE_PUMP_DEBUG_MISSION
            )
        elif self.factory_debug:
            self._write_static(self.workspace / "MISSION.md", FACTORY_DEBUG_MISSION)
            self._seed_mutable(
                self.workspace / "FACTORY_PLAN.md", FACTORY_PLAN_TEMPLATE
            )
            self._seed_mutable(self.workspace / "PROGRESS.md", PROGRESS_LOG_TEMPLATE)
        references = self.workspace / "references"
        references.mkdir(parents=True, exist_ok=True)
        documentation = self.supervisor.store.manifest()["documentation"]
        manifest_hashes = self.supervisor.store.manifest().get("hashes", {})
        for key, target_name in (
            ("api_reference", "api_reference.md"),
            ("schema_reference", "schema_reference.md"),
        ):
            source = Path(documentation[key])
            expected_digest = manifest_hashes.get(key)
            if expected_digest and sha256_file(source) != expected_digest:
                raise CodexRunnerError(
                    f"Current {key} differs from the campaign manifest"
                )
            target = references / target_name
            if target.exists() and sha256_file(target) != sha256_file(source):
                raise CodexRunnerError(
                    f"Existing Codex workspace reference differs from manifest: {target}"
                )
            if not target.exists():
                shutil.copy2(source, target)
        staging = self.control_dir / "reference-bundle"
        generated = write_reference_bundle(
            Path(documentation["api_reference"]),
            Path(documentation["schema_reference"]),
            staging,
        )
        for relative, digest in generated.items():
            source = staging / relative
            target = references / relative
            if target.exists() and sha256_file(target) != digest:
                raise CodexRunnerError(
                    f"Existing routed Codex reference differs from its source: {target}"
                )
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        schema_text = json.dumps(ACTION_SCHEMA, indent=2, sort_keys=True) + "\n"
        self._write_static(self.control_dir / "next-action.schema.json", schema_text)

    async def run(self, preflight: Dict[str, Any]) -> Dict[str, Any]:
        self.prepare_workspace()
        self._validate_codex_context_identity()
        state_path = self.control_dir / "codex-state.json"
        state: Dict[str, Any]
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if state.get("model") != self.client.model:
                raise CodexRunnerError(
                    "Stored Codex thread model differs from this campaign model"
                )
        else:
            state = {
                "schema_version": 1,
                "model": self.client.model,
                "thread_id": None,
                "turns_completed": 0,
                "total_executions": 0,
                "state_summary": "",
                "phase": "runtime_ready",
                "updated_at": utc_now(),
            }
            _write_json(state_path, state)

        baseline = None
        if not self.supervisor.store.checkpoint_records():
            baseline = await self.supervisor.checkpoint(reason="codex_baseline")
        self._seed_campaign_start(preflight, baseline)

        recovered_pending = await self._recover_pending_action(state, state_path)
        if not recovered_pending:
            initial_observation = {
                "event": "runtime_ready",
                "recorded_at": utc_now(),
                "runtime": self.actor.describe(preflight),
                "preflight": preflight,
                "baseline_checkpoint": baseline,
                "campaign_turns_completed": int(state.get("turns_completed", 0)),
                "campaign_executions": int(state.get("total_executions", 0)),
                "previous_state_summary": state.get("state_summary", ""),
                "campaign_start": "CAMPAIGN_START.json",
                "reference_router": "references/INDEX.md",
            }
            self._write_observation(0, initial_observation)
            self._refresh_interactable_state(reason="runtime_ready")

        last_reason = "codex_turn_budget_exhausted"
        while int(state["turns_completed"]) < self.max_turns:
            turn = int(state["turns_completed"]) + 1
            await self._surface_interturn_events(turn)
            self._refresh_interactable_state(reason=f"before_codex_turn_{turn}")
            state["phase"] = "codex_inference"
            state["pending_codex_turn"] = turn
            state["updated_at"] = utc_now()
            _write_json(state_path, state)
            invocation = await self.client.invoke(
                turn=turn,
                thread_id=state.get("thread_id"),
            )
            action = invocation.action
            _write_json(self.control_dir / "actions" / f"turn-{turn:06d}.json", action)
            state["thread_id"] = invocation.thread_id
            state["state_summary"] = action["state_summary"]
            state.pop("pending_codex_turn", None)
            state["phase"] = "action_ready"
            state["updated_at"] = utc_now()

            if action["action"] == "report_complete":
                last_reason = f"codex_report_complete: {action['reason']}"
                state["turns_completed"] = turn
                state["phase"] = "terminal"
                _write_json(state_path, state)
                self._write_observation(
                    turn,
                    {
                        "event": "report_complete_acknowledged",
                        "recorded_at": utc_now(),
                        "turn": turn,
                        "reason": action["reason"],
                        "state_summary": action["state_summary"],
                    },
                )
                break

            state["pending_action_turn"] = turn
            state["phase"] = "actor_execution"
            _write_json(state_path, state)
            await self._execute_action(turn, action, state, state_path)

        if last_reason == "codex_turn_budget_exhausted":
            state["phase"] = "terminal"
            state["updated_at"] = utc_now()
            _write_json(state_path, state)
        return {
            "reason": last_reason,
            "thread_id": state.get("thread_id"),
            "turns_completed": int(state["turns_completed"]),
            "campaign_executions": int(state.get("total_executions", 0)),
            "session_executions": self.actor.execution_count,
            "state_summary": state.get("state_summary", ""),
        }

    def _seed_campaign_start(
        self,
        preflight: Dict[str, Any],
        baseline: Optional[Dict[str, Any]],
    ) -> None:
        """Write an immutable launch snapshot once; never relabel it as current."""
        target = self.workspace / "CAMPAIGN_START.json"
        if target.exists():
            return
        manifest = self.supervisor.store.manifest()
        actor_state = preflight.get("actor_state") or {}
        payload = {
            "schema_version": 1,
            "captured_game_tick": preflight.get("game_tick"),
            "campaign": {
                "scenario": manifest.get("scenario", "freeplay"),
                "seed": manifest.get("seed"),
                "game_speed": manifest.get("game_speed"),
                "clock_policy": manifest.get("clock_policy"),
                "enemies_enabled": manifest.get("enemies_enabled"),
            },
            "actor": {
                "id": manifest.get("agent_id"),
                "position": actor_state.get("position"),
                "inventory": actor_state.get(
                    "inventory", manifest.get("initial_inventory", {})
                ),
            },
            "factory": preflight.get(
                "factory_state",
                {
                    "entity_count": 0,
                    "power_network_count": 0,
                    "researched_technology_count": 0,
                },
            ),
            "perception": {
                "database_live": bool(
                    preflight.get("database_sync", {}).get("is_running")
                ),
                **preflight.get("database_perception", {}),
                "nearest_resources": preflight.get("nearest_resources", {}),
                "nearest_water_tile": preflight.get("nearest_water_tile"),
            },
            "baseline_checkpoint": baseline,
            "warning": (
                "Immutable campaign-start snapshot; it is not current state after "
                "actions. nearest_water_tile.position is an unwalkable search hint, "
                "not a pump anchor or walking target. Resolve a live anchor and "
                "direction with placement_hints.find_offshore_pump_sites, walk "
                "to site.approach_position, and never walk to site.position."
            ),
        }
        _write_json(target, payload)

    async def _recover_pending_action(
        self, state: Dict[str, Any], state_path: Path
    ) -> bool:
        """Recover a durably proposed action without risking duplicate mutation."""
        pending = state.get("pending_action_turn")
        if pending is None:
            return False
        turn = int(pending)
        action_path = self.control_dir / "actions" / f"turn-{turn:06d}.json"
        if not action_path.exists():
            raise CodexRunnerError(
                f"Pending Codex action {turn} has no canonical action artifact"
            )
        action = _validate_action(json.loads(action_path.read_text(encoding="utf-8")))
        request_id = f"codex-turn-{turn:06d}"
        request_seen = False
        recovered_response: Optional[Dict[str, Any]] = None
        protocol_path = self.supervisor.store.paths.protocol_log
        if protocol_path.exists():
            for line in protocol_path.read_text(encoding="utf-8").splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                request = event.get("request", {})
                response = event.get("response", {})
                if (
                    event.get("direction") == "actor_request"
                    and request.get("id") == request_id
                ):
                    request_seen = True
                if (
                    event.get("direction") == "actor_response"
                    and response.get("id") == request_id
                ):
                    recovered_response = response
        if recovered_response is not None:
            await self._complete_execution(
                turn, action, recovered_response, state, state_path
            )
            return True
        if request_seen:
            raise CodexRunnerError(
                f"Actor request {request_id} has no durable response; refusing to "
                "repeat a possibly mutating Python block"
            )
        await self._execute_action(turn, action, state, state_path)
        return True

    async def _surface_interturn_events(self, turn: int) -> None:
        """Put events received between executions into the next model context."""
        response = await self.actor.handle(
            {
                "id": f"codex-turn-{turn:06d}-status",
                "op": "status",
            }
        )
        if not response.get("ok"):
            raise CodexRunnerError(
                f"Actor status failed before Codex turn {turn}: {response.get('error')}"
            )
        game_events = response.get("game_events") or []
        if not game_events:
            return

        previous_path = self.workspace / "last-observation.json"
        previous_observation = (
            json.loads(previous_path.read_text(encoding="utf-8"))
            if previous_path.exists()
            else None
        )
        observation = {
            "event": "interturn_game_events",
            "recorded_at": utc_now(),
            "turn": turn,
            "game_events": game_events,
            "runtime_status": response,
            "previous_observation": previous_observation,
        }
        _write_json(
            self.control_dir / "turn-contexts" / f"turn-{turn:06d}.json",
            observation,
        )
        _write_json(previous_path, observation)

    async def _execute_action(
        self,
        turn: int,
        action: Dict[str, str],
        state: Dict[str, Any],
        state_path: Path,
    ) -> None:
        source = action["code"]
        response = await self.actor.handle(
            {
                "id": f"codex-turn-{turn:06d}",
                "op": "execute",
                "source": source,
                "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                "logical_path": f"codex/turn-{turn:06d}.py",
            }
        )
        await self._complete_execution(turn, action, response, state, state_path)

    async def _complete_execution(
        self,
        turn: int,
        action: Dict[str, str],
        response: Dict[str, Any],
        state: Dict[str, Any],
        state_path: Path,
    ) -> None:
        state["total_executions"] = int(state.get("total_executions", 0)) + 1
        checkpoint = None
        checkpoint_reason = f"codex_periodic_{state['total_executions']}"
        if (
            self.checkpoint_every
            and int(state["total_executions"]) % self.checkpoint_every == 0
        ):
            matching = [
                record
                for record in self.supervisor.store.checkpoint_records()
                if record.get("reason") == checkpoint_reason
            ]
            checkpoint = (
                matching[-1]
                if matching
                else await self.supervisor.checkpoint(reason=checkpoint_reason)
            )
        observation = {
            "event": "execution_result",
            "recorded_at": utc_now(),
            "turn": turn,
            "reason": action["reason"],
            "state_summary": action["state_summary"],
            "runtime_response": response,
            "periodic_checkpoint": checkpoint,
            "campaign_executions": state["total_executions"],
        }
        self._write_observation(turn, observation)
        self._refresh_interactable_state(reason=f"after_execution_{turn}")
        state["turns_completed"] = turn
        state.pop("pending_action_turn", None)
        state["phase"] = "idle"
        state["updated_at"] = utc_now()
        _write_json(state_path, state)

    def _write_observation(self, turn: int, observation: Dict[str, Any]) -> None:
        _write_json(
            self.control_dir / "observations" / f"turn-{turn:06d}.json",
            observation,
        )
        # This mirror is deliberately in the agent-owned workspace. The
        # canonical record above remains outside the model's writable root.
        _write_json(self.workspace / "last-observation.json", observation)

    def _refresh_interactable_state(self, *, reason: str) -> None:
        try:
            self.interactable_state.refresh(self.supervisor, reason=reason)
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            self.interactable_state.mark_unavailable(reason=reason, error=detail)
            raise CodexRunnerError(
                f"Failed to refresh harness-owned interactable state: {detail}"
            ) from exc

    def _validate_codex_context_identity(self) -> None:
        """Bind the active instructions and task to the immutable manifest."""
        configuration = self.supervisor.store.manifest().get(
            "harness_configuration", {}
        )
        if configuration.get("adapter_protocol_version") != 4:
            raise CodexRunnerError(
                "This runner requires a fresh Codex adapter protocol v4 campaign"
            )
        if configuration.get("codex_goals_feature") is not False:
            raise CodexRunnerError(
                "Codex Goals must be disabled for supervisor-owned campaigns"
            )
        if configuration.get("turn_owner") != "factoryverse-supervisor":
            raise CodexRunnerError("FactoryVerse supervisor must own Codex turns")
        expected_developer = configuration.get("developer_instructions_sha256")
        developer_instructions = getattr(self.client, "developer_instructions", None)
        if expected_developer and isinstance(developer_instructions, str):
            actual = hashlib.sha256(developer_instructions.encode("utf-8")).hexdigest()
            if actual != expected_developer:
                raise CodexRunnerError(
                    "Codex developer instructions differ from the campaign manifest"
                )
        expected_task = configuration.get("task_objective_sha256")
        task_objective = getattr(self.client, "task_objective", None)
        if expected_task and isinstance(task_objective, str):
            actual = hashlib.sha256(task_objective.encode("utf-8")).hexdigest()
            if actual != expected_task:
                raise CodexRunnerError(
                    "Codex task objective differs from the campaign manifest"
                )

    @staticmethod
    def _write_static(path: Path, content: str) -> None:
        if path.exists():
            if path.read_text(encoding="utf-8") != content:
                raise CodexRunnerError(
                    f"Existing immutable Codex harness artifact differs: {path}"
                )
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def _seed_mutable(path: Path, content: str) -> None:
        """Create an agent-owned artifact once and preserve later edits."""
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
