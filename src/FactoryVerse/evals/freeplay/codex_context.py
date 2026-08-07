"""Codex-specific prompting and live context for the freeplay harness."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from .models import utc_now


INTERACTABLE_STATE_FILENAME = "current-interactable-state.json"

FREEPLAY_DEVELOPER_INSTRUCTIONS = """\
You operate one embodied actor in a supervised FactoryVerse Factorio campaign.
Use the persistent Python runtime as the only gameplay action surface. One
response proposes one complete Python program; it may batch multiple causally
safe operations. Top-level await is supported and Python state persists within
a runtime session. On campaign resume, files persist but Python object
references do not.

The trusted harness owns the actor lease, runtime lifecycle, action budget,
checkpoints, finalization, and teardown. Never attempt to checkpoint, reset,
spawn actors, close the runtime, invoke Docker, RCON, Lua, or administrative
interfaces. Do not edit FactoryVerse product source. Workspace files are for
plans, evidence, and reusable Python helpers.

The harness atomically replaces
`../harness-control/current-interactable-state.json` with the latest immediate
actor state and the complete interactable entities, resources, and ghosts at
its sampled tick. Read it before any action whose validity depends on local
interaction. If you are looking for a specific entity or resource not present
there, query `remote_view` or DuckDB. Never edit or treat this harness-owned file
as durable memory. A remote observation establishes knowledge but does not by
itself grant interaction capability.

Use `references/INDEX.md` to load only the focused API or schema documentation
needed for the current operation. `CAMPAIGN_START.json` contains immutable
launch facts, not current state. `last-observation.json` contains the trusted
result of the previous submitted program. Learn from exact runtime evidence and
never claim an action happened unless output confirms it. Record suspected
harness defects, with exact evidence, in `BUGS.md` and continue safely where
possible.

Return exactly the requested structured action. For `execute`, provide a
non-empty complete Python program. For `report_complete`, provide empty code;
completion remains advisory to the supervisor. Keep the state summary concise
and durable, and explain why the proposed action is the best next investment.
"""


def freeplay_goal(
    *,
    notification_debug: bool = False,
    offshore_pump_debug: bool = False,
    factory_debug: bool = False,
) -> str:
    """Return the campaign objective for Codex Goal, separate from instructions."""
    if notification_debug:
        return (
            "Complete the bounded research-notification validation mission in "
            "MISSION.md. Produce the required trigger items, verify each emitted "
            "event from trusted runtime observations, record exact evidence, and "
            "stop only when every outcome is confirmed or precisely blocked."
        )
    if offshore_pump_debug:
        return (
            "Complete the bounded offshore-pump affordance mission in MISSION.md. "
            "Exercise the documented water-search, validated placement, approach, "
            "and connection path; record exact evidence and stop only after success "
            "or a precise reproducible failure."
        )
    if factory_debug:
        return (
            "Within the supervisor's turn budget, build the largest sustainably "
            "productive factory possible and progress toward a rocket. Maximize "
            "durable replenishing throughput, concurrent useful production, and "
            "construction optionality rather than entity count or temporary "
            "hand-fed output. Preserve working flows, verify sustained operation, "
            "and continue scaling until the budget ends or no safe progress remains."
        )
    return (
        "Make the greatest verified Factorio freeplay progress possible within the "
        "supervisor's turn budget: build durable replenishing production, research, "
        "expand useful capacity, and work toward launching a rocket."
    )


class InteractableStateFile:
    """Atomically replace one harness-owned, model-readable context artifact."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def refresh(self, supervisor: Any, *, reason: str) -> Dict[str, Any]:
        environment = supervisor.environment
        tier3 = environment.tier3 if environment is not None else None
        if tier3 is None:
            raise RuntimeError("Tier 3 is unavailable for interactable state capture")
        interface_name = str(supervisor.store.manifest()["agent_id"])
        quoted_interface = json.dumps(interface_name)
        sampled = tier3.run_lua(
            """
            local interface_name = __INTERFACE_NAME__
            local actor = remote.call(interface_name, "inspect", true)
            local inventory = remote.call(interface_name, "get_inventory_items")
            local interactable = remote.call(interface_name, "get_reachable", true)
            return {
                tick = game.tick,
                actor = actor,
                inventory = inventory,
                interactable = interactable
            }
            """.replace("__INTERFACE_NAME__", quoted_interface)
        )
        payload = {
            "schema_version": 1,
            "ownership": "harness",
            "replacement_semantics": "supersedes_all_previous_snapshots",
            "captured_at": utc_now(),
            "capture_reason": reason,
            "available": True,
            "tick": sampled.get("tick"),
            "actor": sampled.get("actor") or {},
            "inventory": sampled.get("inventory") or {},
            "interactable": sampled.get("interactable")
            or {
                "entities": [],
                "resources": [],
                "ghosts": [],
            },
            "pointer": (
                "If you are looking for a specific entity or resource not present "
                "here, query remote_view or DuckDB."
            ),
        }
        self._replace(payload)
        return payload

    def mark_unavailable(self, *, reason: str, error: str) -> None:
        """Replace stale state with an explicit unavailable marker."""
        self._replace(
            {
                "schema_version": 1,
                "ownership": "harness",
                "replacement_semantics": "supersedes_all_previous_snapshots",
                "captured_at": utc_now(),
                "capture_reason": reason,
                "available": False,
                "error": error,
                "pointer": (
                    "Current local interaction state is unavailable. Do not infer "
                    "interaction capability from an older observation."
                ),
            }
        )

    def _replace(self, payload: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp-{os.getpid()}")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
