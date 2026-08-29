"""Batched live reads and pure supply geometry — infrastructure, not an accessor.

What survived the ``verify`` accessor's deletion (API_AFFORDANCE_REDESIGN
§2.1, 2026-08-29): the *mechanism*. Per-entity inspection costs one RCON
roundtrip each, so a base-wide status read is one xpcall'd Lua loop over the
whole target set in a single tick. The methods that sat on ``verify`` were
absorbed — ``entity.status`` (live), ``entity_reference(pole).covers(...)``
and ``pole.covers(...)`` (box-vs-box geometry), network ids on the electric
mixin — and this module is what they stand on.

Freshness contract: positions, statuses and ``electric_network_id`` are LIVE
engine reads at call time; supply distances and collision boxes are
PROTOTYPE-derived (the offline dump). Mixing a live position with a
prototype box is sound because the box does not change at runtime.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union, TYPE_CHECKING

from FactoryVerse.game.agent.placement_hints import _pole_prototype_distances
from FactoryVerse.game.factory.prototypes import get_entity_prototypes

if TYPE_CHECKING:
    from FactoryVerse.game.agent.infra.rcon_handler import RconHandler

logger = logging.getLogger(__name__)

Target = Union[Tuple[str, Any], Dict[str, Any]]


@dataclass
class EntityCoverage:
    """Coverage verdict for one electric consumer against the pole set.

    Geometry is prototype-derived (supply distance, collision box); the pole and
    entity *positions* it is computed from are live. ``covered`` is True iff the
    entity's collision box intersects at least one pole's supply box (the engine
    rule). ``margin`` is a single honest number:
      * covered  -> the smallest overlap depth (tiles you could shift the entity
        before it falls out of coverage);
      * NOT covered -> the shortest distance needed to become covered, with the
        axis in ``margin_axis`` ('X', 'Y', or 'XY' when separated on both).
    ``by_pole_name``/``by_pole_position`` name the covering pole (when covered)
    or the nearest pole that would cover it with the least move (when not).
    ``detail`` is a human sentence, e.g. "0.15 short on Y toward y=64.5 pole line".
    """

    entity_name: str
    position: Dict[str, float]
    covered: bool
    margin: float
    margin_axis: str
    by_pole_name: Optional[str]
    by_pole_position: Optional[Dict[str, float]]
    detail: str


# =============================================================================
# Pure geometry (no RCON — unit-tested directly against the prototype dump)
# =============================================================================

Rect = Tuple[float, float, float, float]  # (min_x, min_y, max_x, max_y)


def _collision_box(prototypes, name: str, x: float, y: float) -> Rect:
    """Absolute collision box of ``name`` centred at (x, y), from the dump.

    The prototype ``collision_box`` is ``[[x1,y1],[x2,y2]]`` relative to the
    entity centre; add the position to get world coordinates. Falls back to a
    unit box if the prototype has no collision_box (loud-ish: still usable).
    """
    proto = prototypes.get_prototype(name)
    cb = proto.get("collision_box") if proto else None
    if not cb:
        return (x - 0.5, y - 0.5, x + 0.5, y + 0.5)
    (x1, y1), (x2, y2) = cb[0], cb[1]
    return (x + x1, y + y1, x + x2, y + y2)


def _supply_box(px: float, py: float, supply: float) -> Rect:
    """Continuous supply box of a pole: centre ± supply_area_distance."""
    return (px - supply, py - supply, px + supply, py + supply)


def _overlap(a: Rect, b: Rect) -> Tuple[float, float]:
    """Signed overlap depths (ox, oy). Positive == overlapping on that axis,
    negative == a gap of that magnitude."""
    ox = min(a[2], b[2]) - max(a[0], b[0])
    oy = min(a[3], b[3]) - max(a[1], b[1])
    return ox, oy


def _coverage_for_entity(
    entity_box: Rect,
    entity_center: Tuple[float, float],
    poles: List[Dict[str, Any]],
) -> Tuple[bool, float, str, Optional[Dict[str, Any]], str]:
    """Compute (covered, margin, margin_axis, by_pole, detail) for one entity.

    ``poles`` is a list of resolved pole dicts each with keys name, x, y, supply.
    Deterministic: poles are consumed in the (already sorted) order given.
    """
    ex, ey = entity_center
    best_cov: Optional[Tuple[float, Dict[str, Any]]] = None   # (depth, pole)
    best_gap: Optional[Tuple[float, float, float, Dict[str, Any]]] = None
    # (gap_dist, gap_x, gap_y, pole)

    for pole in poles:
        sbox = _supply_box(pole["x"], pole["y"], pole["supply"])
        ox, oy = _overlap(entity_box, sbox)
        if ox > 0 and oy > 0:
            depth = min(ox, oy)
            if best_cov is None or depth > best_cov[0]:
                best_cov = (depth, pole)
        else:
            gx = max(0.0, -ox)
            gy = max(0.0, -oy)
            gap = math.hypot(gx, gy)
            if best_gap is None or gap < best_gap[0]:
                best_gap = (gap, gx, gy, pole)

    if best_cov is not None:
        depth, pole = best_cov
        return (
            True,
            round(depth, 4),
            "",
            {"name": pole["name"], "position": {"x": pole["x"], "y": pole["y"]}},
            f"covered by {pole['name']}@({pole['x']},{pole['y']}); "
            f"overlap depth {depth:.2f} tiles",
        )

    if best_gap is None:
        return (False, float("inf"), "", None, "no poles in scene")

    gap, gx, gy, pole = best_gap
    if gx > 0 and gy <= 1e-9:
        axis = "X"
        toward = f"toward x={pole['x']} pole line"
        margin = gx
        detail = f"{gx:.2f} short on X {toward}"
    elif gy > 0 and gx <= 1e-9:
        axis = "Y"
        toward = f"toward y={pole['y']} pole line"
        margin = gy
        detail = f"{gy:.2f} short on Y {toward}"
    else:
        axis = "XY"
        margin = gap
        detail = (
            f"{gap:.2f} short (X {gx:.2f} toward x={pole['x']}, "
            f"Y {gy:.2f} toward y={pole['y']})"
        )
    return (
        False,
        round(margin, 4),
        axis,
        {"name": pole["name"], "position": {"x": pole["x"], "y": pole["y"]}},
        detail,
    )


def compute_supply_coverage(
    entities: List[Tuple[str, float, float]],
    poles: List[Dict[str, Any]],
    prototypes=None,
) -> List[EntityCoverage]:
    """Pure geometry core: coverage of ``entities`` by ``poles``.

    ``entities`` are (name, x, y); ``poles`` are dicts with name/x/y and either a
    resolved ``supply`` or a ``pole_name`` to resolve. ``prototypes`` defaults to
    the shared prototype accessor (offline dump). This function does NO RCON, so
    tests exercise the exact attempt-5 numbers without a live server.
    """
    prototypes = prototypes or get_entity_prototypes()
    resolved: List[Dict[str, Any]] = []
    for p in poles:
        supply = p.get("supply")
        if supply is None:
            _wire, supply = _pole_prototype_distances(p["pole_name"])
        resolved.append(
            {
                "name": p.get("name") or p.get("pole_name"),
                "x": p["x"],
                "y": p["y"],
                "supply": supply,
                "is_proposed": bool(p.get("is_proposed")),
            }
        )
    # Deterministic pole order (proposed last on ties → stable, and the live
    # spine is preferred as the covering reference when equal).
    resolved.sort(key=lambda q: (q["is_proposed"], q["x"], q["y"], q["name"]))

    out: List[EntityCoverage] = []
    for name, x, y in sorted(entities):
        ebox = _collision_box(prototypes, name, x, y)
        covered, margin, axis, by_pole, detail = _coverage_for_entity(
            ebox, (x, y), resolved
        )
        out.append(
            EntityCoverage(
                entity_name=name,
                position={"x": x, "y": y},
                covered=covered,
                margin=margin,
                margin_axis=axis,
                by_pole_name=by_pole["name"] if by_pole else None,
                by_pole_position=by_pole["position"] if by_pole else None,
                detail=detail,
            )
        )
    return out


# =============================================================================
# Target normalisation
# =============================================================================


def _pos_xy(position: Any) -> Tuple[float, float]:
    """Normalize a position arg to (x, y): MapPosition | {'x','y'} | (x, y)."""
    if hasattr(position, "x") and hasattr(position, "y"):
        return float(position.x), float(position.y)
    if isinstance(position, dict):
        return float(position["x"]), float(position["y"])
    if isinstance(position, (tuple, list)) and len(position) >= 2:
        return float(position[0]), float(position[1])
    raise TypeError(
        f"Unsupported position {position!r}; expected MapPosition, "
        f"{{'x','y'}} dict, or (x, y) tuple"
    )


def _normalize_target(t: Target) -> Tuple[str, float, float]:
    """(entity_name, x, y) from a (name, position) tuple or a dict."""
    if isinstance(t, dict):
        name = t.get("entity_name") or t.get("name")
        if name is None:
            raise ValueError(f"target dict missing entity_name/name: {t!r}")
        if "position" in t:
            x, y = _pos_xy(t["position"])
        else:
            x, y = float(t["x"]), float(t["y"])
        return name, x, y
    if isinstance(t, (tuple, list)) and len(t) == 2 and isinstance(t[0], str):
        x, y = _pos_xy(t[1])
        return t[0], x, y
    raise TypeError(
        f"Unsupported target {t!r}; expected (entity_name, position) or "
        f"{{'entity_name','position'}}"
    )


# =============================================================================
# The batched live read — one roundtrip for N entities
# =============================================================================


def to_lua(value: Any) -> str:
    """Python value → Lua literal (safe quoting)."""
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(float(value)) if isinstance(value, float) else str(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, dict):
        items = ", ".join(f"[{json.dumps(k)}] = {to_lua(v)}" for k, v in value.items())
        return "{" + items + "}"
    if isinstance(value, (list, tuple)):
        return "{" + ", ".join(to_lua(v) for v in value) + "}"
    raise TypeError(f"cannot convert {type(value)} to Lua")


def run_lua_batch(rcon: "RconHandler", body: str) -> Any:
    """Run a Lua body under xpcall over RCON; return the parsed JSON result.

    The body should ``return`` a table; errors come back as ``{"error": ...}``
    rather than raising, so a transport failure is distinguishable from an
    empty answer (Constitution §15).
    """
    cmd = (
        "local ok, res = xpcall(function() " + body + " end, debug.traceback) "
        "if ok then rcon.print(helpers.table_to_json("
        "res == nil and {ok=true} or res)) "
        "else rcon.print(helpers.table_to_json({error = tostring(res)})) end"
    )
    out = rcon.execute(cmd, silent=True)
    if out is None or out.strip() == "":
        return {"error": "empty RCON response"}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"error": f"non-JSON response: {out[:400]}"}


def live_status_batch(rcon: "RconHandler", targets: List[Target]) -> List[Dict[str, Any]]:
    """Status name and electric network id for many entities in one tick.

    Each row: ``{found, name, x, y, status_name, electric_network_id}`` in the
    order of ``targets``; ``found=False`` when nothing sits at the position.
    This is the transport under every base-wide live read; it is not an
    agent-facing method.
    """
    norm = [_normalize_target(t) for t in targets]
    lua_targets = [{"name": n, "x": x, "y": y} for n, x, y in norm]
    body = (
        "local s = game.surfaces[1] "
        "local names = {} "
        "for k, v in pairs(defines.entity_status) do names[v] = k end "
        f"local targets = {to_lua(lua_targets)} "
        "local out = {} "
        "for _, t in ipairs(targets) do "
        "  local e = s.find_entities_filtered{name=t.name, "
        "    position={x=t.x, y=t.y}, radius=0.6}[1] "
        "  if e and e.valid then "
        "    out[#out+1] = {found=true, name=t.name, x=t.x, y=t.y, "
        "      status_name=names[e.status], electric_network_id=e.electric_network_id} "
        "  else "
        "    out[#out+1] = {found=false, name=t.name, x=t.x, y=t.y} "
        "  end "
        "end "
        "return out"
    )
    raw = run_lua_batch(rcon, body)
    rows = raw if isinstance(raw, list) else []
    out: List[Dict[str, Any]] = []
    for (name, x, y), row in zip(norm, rows + [{}] * (len(norm) - len(rows))):
        if row.get("found"):
            out.append({"found": True, "name": name, "x": x, "y": y,
                        "status_name": row.get("status_name"),
                        "electric_network_id": row.get("electric_network_id")})
        else:
            out.append({"found": False, "name": name, "x": x, "y": y,
                        "status_name": None, "electric_network_id": None})
    return out


def live_poles_in_area(rcon: "RconHandler", area: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every electric pole in ``area`` with its live network id, one roundtrip."""
    lt, rb = area["left_top"], area["right_bottom"]
    body = (
        "local s = game.surfaces[1] "
        f"local poles = s.find_entities_filtered{{type='electric-pole', "
        f"area={{{{{lt['x']}, {lt['y']}}}, {{{rb['x']}, {rb['y']}}}}}}} "
        "local out = {} "
        "for _, p in ipairs(poles) do "
        "  out[#out+1] = {name=p.name, x=p.position.x, y=p.position.y, "
        "    electric_network_id=p.electric_network_id} "
        "end "
        "return out"
    )
    raw = run_lua_batch(rcon, body)
    return raw if isinstance(raw, list) else []


__all__ = [
    "EntityCoverage",
    "Rect",
    "compute_supply_coverage",
    "live_status_batch",
    "live_poles_in_area",
    "run_lua_batch",
    "to_lua",
]
