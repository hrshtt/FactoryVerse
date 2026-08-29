"""The turn report — the observation at the start of every turn.

TURN_CONTRACT §4: a diff over the previous turn's horizon, attributed, and
delivered *in the agent's input* by the harness before the agent is asked for
anything. Nothing here is new machinery: it is one assembly over reads the
mods already provide, done once per turn.

The assembler is dependency-injected: every read it needs is a plain callable
or value handed in by the runtime adapter, so the report can be assembled from
fixtures in a unit test and from the live engine in a run with the same code.

Context cost is the report's design problem (TURN §4): groups are thresholded
so a large base yields a small report — at most ``MAX_POSITIONS`` positions
per group, with a ``+n more`` marker, and drill-down through the normal reads.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from FactoryVerse.game.agent.status_dump import StatusChange, StatusDumpReader

MAX_POSITIONS = 5
MAX_ITEMS = 20


# --------------------------------------------------------------------------
# Inputs a turn captures at its start and reads at its end
# --------------------------------------------------------------------------


@dataclass
class TurnSnapshot:
    """Everything the report diffs against, captured at turn start."""

    tick: int
    production: Dict[str, Dict[str, int]]  # {"input": {...}, "output": {...}}
    inventory: Dict[str, int]
    map_rows: Dict[Tuple[str, float, float], Dict[str, Any]]  # entity rows by key
    ghost_rows: Dict[Tuple[str, float, float], Dict[str, Any]]
    research: Dict[str, Any]
    crafting_queue: List[Dict[str, Any]]
    researched_count: int


@dataclass
class ClockLedger:
    turn_start_tick: int
    end_turn_tick: int  # tick when end_turn (or the cap) fired
    advanced: int  # ticks fast-forwarded
    final_tick: int  # tick after the fast-forward
    execution_ticks: int  # sum of tool-call spans
    horizon: int  # T for the turn that just ended

    @property
    def used(self) -> int:
        return self.end_turn_tick - self.turn_start_tick

    @property
    def thinking_ticks(self) -> int:
        return max(0, self.used - self.execution_ticks)

    @property
    def total(self) -> int:
        return self.final_tick - self.turn_start_tick

    def reconciles(self) -> bool:
        """The ledger's own check: used + advanced == tick delta."""
        return self.used + self.advanced == self.total


# One class for the prediction, defined where it is made (§7.1): the crafting
# action stores it at enqueue, the report verifies it. Re-exported here so the
# report's callers need not know where it lives.
from FactoryVerse.game.agent.embodied_actions.crafting import CraftPrediction  # noqa: E402


@dataclass
class TurnReport:
    turn: int
    mode: str  # "planning" | "gameplay"
    clock: Dict[str, Any]
    horizon: Dict[str, Any]
    production: Dict[str, Any]
    map: Dict[str, Any]
    status: Dict[str, Any]
    research: Dict[str, Any]
    crafting: Dict[str, Any]
    inventory: Dict[str, Any]
    events: Dict[str, Any]
    plan: Optional[Dict[str, Any]] = None
    ended_by: str = "end_turn"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------
# The plan helper (planning-turn namespace)
# --------------------------------------------------------------------------


class PlanStore:
    """A free-text plan and a list of sub-goals, persisted per session.

    The planning turn's only write surface. Echoed at the top of every report
    so the plan is the thing the agent reads first, every turn.
    """

    def __init__(self, path: Optional[Path]):
        self._path = Path(path) if path else None
        self._data: Dict[str, Any] = {"plan": "", "goals": [], "updated_turn": None}
        if self._path and self._path.is_file():
            try:
                self._data.update(json.loads(self._path.read_text()))
            except (OSError, json.JSONDecodeError):
                pass
        self._turn: Optional[int] = None

    def _save(self) -> None:
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data, indent=2))

    def bind_turn(self, turn: int) -> None:
        self._turn = turn

    def set(self, text: str) -> str:
        """Replace the plan text."""
        self._data["plan"] = str(text)
        self._data["updated_turn"] = self._turn
        self._save()
        return "plan recorded"

    def set_goals(self, goals: Sequence[str]) -> str:
        """Replace the ordered sub-goal list."""
        self._data["goals"] = [str(g) for g in goals]
        self._data["updated_turn"] = self._turn
        self._save()
        return f"{len(self._data['goals'])} goals recorded"

    def read(self) -> Dict[str, Any]:
        return dict(self._data)

    def __repr__(self) -> str:
        return f"PlanStore(plan={self._data['plan'][:40]!r}, goals={len(self._data['goals'])})"


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------


def _delta(before: Dict[str, int], after: Dict[str, int]) -> Dict[str, int]:
    keys = set(before) | set(after)
    out = {k: int(after.get(k, 0)) - int(before.get(k, 0)) for k in keys}
    return {k: v for k, v in out.items() if v}


def _top(d: Dict[str, int], n: int = MAX_ITEMS) -> Dict[str, int]:
    return dict(sorted(d.items(), key=lambda kv: (-abs(kv[1]), kv[0]))[:n])


def _positions(keys: Iterable[Tuple[str, float, float]]) -> Dict[str, Any]:
    keys = list(keys)
    shown = [f"{k[0]}@({k[1]:g},{k[2]:g})" for k in keys[:MAX_POSITIONS]]
    return {"count": len(keys), "shown": shown, "more": max(0, len(keys) - MAX_POSITIONS)}


def _row_key(row: Dict[str, Any], name_col: str) -> Tuple[str, float, float]:
    return (str(row[name_col]), float(row["position_x"]), float(row["position_y"]))


def index_rows(rows: Iterable[Dict[str, Any]], name_col: str) -> Dict[Tuple[str, float, float], Dict[str, Any]]:
    return {_row_key(r, name_col): r for r in rows}


def event_counts_by_item(events: Sequence[Any]) -> Dict[str, int]:
    """Hand-crafted item counts from drained crafting_finished events."""
    out: Dict[str, int] = {}
    for e in events:
        ntype = getattr(e, "notification_type", None) or (e.get("notification_type") if isinstance(e, dict) else None)
        if ntype != "crafting_finished":
            continue
        data = getattr(e, "data", None) or (e.get("data") if isinstance(e, dict) else {}) or {}
        # The Lua completion carries the recipe and count (crafting.lua); the
        # products of a recipe are the recipe's own name for every hand recipe
        # in scope, so recipe name stands in for item name here.
        recipe = data.get("recipe") or data.get("item")
        count = data.get("count") or data.get("count_completed") or 0
        if recipe:
            out[recipe] = out.get(recipe, 0) + int(count)
    return out


def derived_queue_ticks(queue: Sequence[Dict[str, Any]], energy_for: Callable[[str], Optional[float]]) -> Tuple[int, List[Dict[str, Any]]]:
    """Serial char-time of the queue at crafting speed 1 (§7.1 — arithmetic,
    not extrapolation). Returns (total_ticks, per-item list)."""
    total = 0
    items: List[Dict[str, Any]] = []
    for item in queue:
        recipe = item.get("recipe")
        count = int(item.get("count", 0) or 0)
        energy = energy_for(recipe) if recipe else None
        ticks = int(round((energy or 0.5) * 60 * count))
        total += ticks
        items.append({"recipe": recipe, "count": count, "ticks": ticks, "energy_known": energy is not None})
    return total, items


def assemble(
    *,
    turn: int,
    mode: str,
    ended_by: str,
    clock: ClockLedger,
    before: TurnSnapshot,
    after: TurnSnapshot,
    events: Sequence[Any],
    status_change: Optional[StatusChange],
    next_horizon: int,
    next_inputs: Dict[str, Any],
    energy_for: Callable[[str], Optional[float]],
    predictions: Sequence[CraftPrediction] = (),
    plan: Optional[Dict[str, Any]] = None,
    seq_gaps: Sequence[Dict[str, Any]] = (),
) -> TurnReport:
    # Production — split automated vs hand-crafted.
    produced = _delta(before.production.get("output", {}), after.production.get("output", {}))
    consumed = _delta(before.production.get("input", {}), after.production.get("input", {}))
    hand = event_counts_by_item(events)
    automated = {k: v - hand.get(k, 0) for k, v in produced.items()}
    automated = {k: v for k, v in automated.items() if v > 0}
    turn_minutes = max(clock.total, 1) / 3600.0
    automated_rate = sum(automated.values()) / turn_minutes if turn_minutes > 0 else 0.0

    # Map — placed/removed by name + position; ghosts placed / built over.
    placed = sorted(set(after.map_rows) - set(before.map_rows))
    removed = sorted(set(before.map_rows) - set(after.map_rows))
    ghosts_placed = sorted(set(after.ghost_rows) - set(before.ghost_rows))
    ghosts_gone = sorted(set(before.ghost_rows) - set(after.ghost_rows))
    built_over = [g for g in ghosts_gone if g in after.map_rows]
    ghosts_removed = [g for g in ghosts_gone if g not in after.map_rows]

    # Status — transitions grouped by label.
    status_section: Dict[str, Any] = {"source": None, "groups": {}}
    if status_change is not None:
        status_section["source"] = status_change.source
        for label, ts in status_change.grouped().items():
            status_section["groups"][label] = _positions(t.entity for t in ts)

    # Research.
    finished = [
        (getattr(e, "data", None) or {}).get("technology")
        for e in events
        if getattr(e, "notification_type", None) == "research_finished"
    ]
    research_section = {
        "before": {k: before.research.get(k) for k in ("current_research", "progress", "queue_length")},
        "after": {k: after.research.get(k) for k in ("current_research", "progress", "queue_length")},
        "completed": [t for t in finished if t],
        "researched_count": after.researched_count,
    }

    # Crafting (§7.1).
    remaining_ticks, remaining_items = derived_queue_ticks(after.crafting_queue, energy_for)
    verified = []
    for p in predictions:
        actual = None
        for e in events:
            if getattr(e, "notification_type", None) == "crafting_finished":
                d = getattr(e, "data", None) or {}
                if d.get("recipe") == p.recipe:
                    actual = getattr(e, "tick", None)
        verified.append({"recipe": p.recipe, "count": p.count, "predicted_tick": p.predicted_completion_tick, "actual_tick": actual})
    crafting_section = {
        "completed": _top(hand),
        "remaining": remaining_items[:MAX_ITEMS],
        "remaining_ticks": remaining_ticks,
        "share_of_next_horizon": (remaining_ticks / next_horizon) if next_horizon else None,
        "stalled": "unknown",  # the queue read does not expose the stall reason today
        "predicted_vs_actual": verified,
    }

    # Events, in order, with epoch/seq when present.
    event_list = []
    for e in events:
        to_dict = getattr(e, "to_dict", None)
        event_list.append(to_dict() if callable(to_dict) else (e if isinstance(e, dict) else {"repr": repr(e)}))

    return TurnReport(
        turn=turn,
        mode=mode,
        ended_by=ended_by,
        clock={
            "used": clock.used,
            "execution": clock.execution_ticks,
            "thinking": clock.thinking_ticks,
            "advanced": clock.advanced,
            "total": clock.total,
            "horizon": clock.horizon,
            "tick": clock.final_tick,
            "reconciles": clock.reconciles(),
        },
        horizon={"next_ticks": next_horizon, "inputs": dict(next_inputs)},
        production={
            "produced": _top(produced),
            "consumed": _top(consumed),
            "automated": _top(automated),
            "hand_crafted": _top(hand),
            "automated_rate_per_min": round(automated_rate, 2),
            "source": "force production statistics (live), hand-crafted from crafting_finished events",
        },
        map={
            "placed": _positions(placed),
            "removed": _positions(removed),
            "ghosts_placed": _positions(ghosts_placed),
            "ghosts_built_over": _positions(built_over),
            "ghosts_removed": _positions(ghosts_removed),
            "source": "map_entity/ghost tables diffed between turn start and now",
        },
        status=status_section,
        research=research_section,
        crafting=crafting_section,
        inventory={"delta": _top(_delta(before.inventory, after.inventory)), "source": "agent inventory (live)"},
        events={"count": len(event_list), "items": event_list, "seq_gaps": list(seq_gaps)},
        plan=plan,
    )


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def _fmt_items(d: Dict[str, int]) -> str:
    if not d:
        return "none"
    return ", ".join(f"{k} ×{v}" if v >= 0 else f"{k} {v}" for k, v in d.items())


def _fmt_positions(p: Dict[str, Any]) -> str:
    if not p or p.get("count", 0) == 0:
        return "none"
    s = ", ".join(p["shown"])
    if p.get("more"):
        s += f" (+{p['more']} more)"
    return f"{p['count']}: {s}"


def render(report: TurnReport) -> str:
    """The text the model sees. Grouped, thresholded, every section sourced."""
    c = report.clock
    h = report.horizon
    lines = [
        f"# Turn {report.turn + 1} — {report.mode.upper()} turn",
        "",
        f"clock      previous turn used {c['used']} ticks (execution {c['execution']}, thinking {c['thinking']}), "
        f"advanced {c['advanced']}, total {c['total']} of horizon {c['horizon']}; now tick {c['tick']}"
        + ("" if c.get("reconciles", True) else "  [ledger does not reconcile — reported, not hidden]"),
        f"horizon    next turn: {h['next_ticks']} ticks ({h['next_ticks'] / 3600:.1f} game-min); "
        f"set by research tier {h['inputs'].get('research_tier')} ({h['inputs'].get('researched_count')} techs) "
        f"and automated rate {h['inputs'].get('automated_rate_per_min')}/min",
    ]
    if report.mode == "planning":
        lines.append("           (a planning turn advances no world time)")
    if report.plan and (report.plan.get("plan") or report.plan.get("goals")):
        lines += ["", "plan       " + (report.plan.get("plan") or "(no text)")]
        for i, g in enumerate(report.plan.get("goals") or [], 1):
            lines.append(f"           {i}. {g}")
    p = report.production
    lines += [
        "",
        f"production automated {_fmt_items(p['automated'])}",
        f"           hand-crafted {_fmt_items(p['hand_crafted'])}",
        f"           consumed {_fmt_items(p['consumed'])}",
    ]
    m = report.map
    lines += [
        "",
        f"map        placed {_fmt_positions(m['placed'])}",
        f"           removed {_fmt_positions(m['removed'])}",
        f"           ghosts placed {_fmt_positions(m['ghosts_placed'])}; built over {_fmt_positions(m['ghosts_built_over'])}; removed {_fmt_positions(m['ghosts_removed'])}",
    ]
    s = report.status
    lines.append("")
    if s.get("groups"):
        lines.append(f"status     transitions ({s.get('source')}):")
        for label, pos in s["groups"].items():
            lines.append(f"           {label}: {_fmt_positions(pos)}")
    else:
        lines.append(f"status     no transitions ({s.get('source') or 'no status dump available'})")
    r = report.research
    lines += [
        "",
        f"research   completed {', '.join(r['completed']) or 'none'}; "
        f"current {r['after'].get('current_research') or 'none'} "
        f"({(r['after'].get('progress') or 0) * 100:.0f}%), queue {r['after'].get('queue_length') or 0}",
    ]
    cr = report.crafting
    share = cr.get("share_of_next_horizon")
    lines += [
        "",
        f"crafting   completed {_fmt_items(cr['completed'])}",
        "           remaining " + (", ".join(f"{i['recipe']} ×{i['count']}" for i in cr["remaining"]) or "none") + " — "
        f"{cr['remaining_ticks']} ticks"
        + (f" (≈{share * 100:.0f}% of next horizon)" if share is not None and cr["remaining_ticks"] else ""),
        f"           stalled {cr['stalled']}",
    ]
    for v in cr["predicted_vs_actual"]:
        lines.append(
            f"           predicted {v['recipe']} ×{v['count']} completion tick {v['predicted_tick']} → actual "
            f"{v['actual_tick'] if v['actual_tick'] is not None else 'not yet'}"
        )
    lines += ["", f"inventory  {_fmt_items(report.inventory['delta'])}"]
    ev = report.events
    lines.append("")
    if ev["seq_gaps"]:
        lines.append(f"events     GAP: {len(ev['seq_gaps'])} sequence gap(s) — {ev['seq_gaps']}")
    lines.append(f"events     {ev['count']} in order:")
    for e in ev["items"][:50]:
        seq = f" [{e.get('epoch')}:{e.get('seq')}]" if isinstance(e, dict) and e.get("seq") is not None else ""
        ntype = e.get("notification_type") if isinstance(e, dict) else None
        tick = e.get("tick") if isinstance(e, dict) else None
        data = e.get("data") if isinstance(e, dict) else None
        summary = ""
        if isinstance(data, dict):
            summary = data.get("technology") or data.get("recipe") or ""
            if data.get("count"):
                summary += f" ×{data['count']}"
        if ntype is None and isinstance(e, dict) and e.get("text"):
            # An untyped payload: show what it says rather than "None None".
            lines.append(f"           {e['text']}")
        elif ntype is None and isinstance(e, dict) and e.get("repr"):
            lines.append(f"           {e['repr']}")
        else:
            lines.append(f"           t={tick}{seq} {ntype} {summary}".rstrip())
    if ev["count"] > 50:
        lines.append(f"           (+{ev['count'] - 50} more on the record)")
    return "\n".join(lines)
