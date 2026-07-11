"""FROZEN spec for the accessor_liveness family. Sub-agents MUST NOT edit.

THE CLAIM (ledger row L1.12, pending): every public WRITE accessor on the
agent-facing typed layer actually mutates the ENGINE state it promises, and —
where a DB surface promises to reflect that mutation — the config-sync spine
carries it to DuckDB. An accessor that returns success while the engine is
unchanged is a LYING AFFORDANCE (the write-side mirage class) and must show up
here as a RED-FINDING until the surface is reconciled.

This is the write-side twin of db_column_liveness (L1.11). Same three-verdict
protocol, same strict-xfail register, same reconciliation forcing function.

TRUTH CHANNELS (frozen):
- ENGINE: raw RCON Lua via runtime.lua_strict, reading LuaEntity attributes
  directly (direction, get_recipe().name, get_filter(i), inventory contents,
  inventory get_bar). Shares no code with the mod's inspection path, the
  Python client state, or the loader. NEVER assert on the accessor's return
  value or the typed object's post-call attributes — client state is exactly
  what ROT-1 shows can lie.
- DB (spine cases only): after the mutation, wait_ops_flushed() then
  runtime.load_db and read the entity row. Deliberately NOT the re_snapshot
  ritual — a full re-gather would mask the event-driven config-upsert path
  (and squashes provenance, PROV-1). The spine IS the surface under test.

CASE MATRIX: enumerated at import from the typed layer's own classes (the
same classes ENTITY_CLASS_MAP instantiates) plus the two action classes that
carry write primitives with no typed accessor. Adding a public method to any
enumerated class creates an unclassified accessor, which fails the
completeness gate below until the orchestrator classifies it.

Expectations encode today's KNOWN state (code-audit 2026-07-09, live plants
confirmed in-source: rotatable.py:44 TODO no-op; inserter.py:104
"inserter_filter" key absent from EntityInterface.lua:135-145):
- MUTATOR + engine LIVE: assert engine reflects the mutation (+ floors).
- MUTATOR + engine DEAD: same assertions, strict-xfail with tracker id.
- db LIVE/DEAD: a DB surface promises the value; assert/xfail accordingly.
- db NOT_APPLICABLE: adjudicated boundary rule (Harshit 2026-07-09): the DB
  is a spatial reference + durable contracts; volatile state (inventories,
  fuel, fluids) is ephemeral-bridge-only and MUST NOT gain a DB assertion.
- READ_PROBE / COVERED / DEFERRED: enumerated but excluded from this family,
  each with a rationale + pointer. Exclusion without a pointer is a spec bug.
"""

from __future__ import annotations

import enum
import inspect
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

_SRC = str(Path(__file__).resolve().parents[3] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class Kind(enum.Enum):
    MUTATOR = "mutator"          # tested by this family
    READ_PROBE = "read_probe"    # read-only accessor; excluded with pointer
    COVERED = "covered"          # write path certified/covered elsewhere
    DEFERRED = "deferred"        # write path owned by a queued family


class Expect(enum.Enum):
    LIVE = "live"                # assert; must pass
    DEAD = "dead"                # assert; strict-xfail with tracker id
    NOT_APPLICABLE = "n/a"       # boundary rule: no DB assertion permitted
    NONE = "none"                # no DB surface promises this value today


@dataclass(frozen=True)
class AccessorCase:
    owner: str                   # class name
    method: str
    kind: Kind
    group: str = ""              # fan-out boundary; required for MUTATOR
    engine: Expect = Expect.NONE # engine-effect expectation (MUTATOR only)
    db: Expect = Expect.NONE     # DB-sync expectation (MUTATOR only)
    tracker: str = ""            # tracker/ledger anchor for DEAD/exclusions
    note: str = ""


# --- the frozen class registry (enumeration source) --------------------------
# Import paths are part of the spec: these are the classes the typed layer is
# built from. BaseEntity itself is deliberately NOT enumerated: its mutators
# (build/remove/pickup) are certified via L2.1/L4.6 and the offline battery;
# its read surface via L2.4. Enumerating it would fold that certified scope
# into this family and double-own it.

def _classes():
    from FactoryVerse.game.factory.entity.capabilities.rotatable import (
        RotatableMixin, Rotatable180Mixin)
    from FactoryVerse.game.factory.entity.capabilities.inserter import InserterMixin
    from FactoryVerse.game.factory.entity.capabilities.crafter import (
        CrafterMixin, SetRecipeMixin)
    from FactoryVerse.game.factory.entity.capabilities.burner import BurnerMixin
    from FactoryVerse.game.factory.entity.capabilities.miner import MinerMixin
    from FactoryVerse.game.factory.entity.capabilities.fluid import FluidMixin
    from FactoryVerse.game.factory.entity.capabilities.belt import BeltMixin
    from FactoryVerse.game.factory.entity.capabilities.electric import ElectricMixin
    from FactoryVerse.game.factory.entity.implementations.container import Container
    from FactoryVerse.game.factory.entity.implementations.electric_pole import ElectricPole
    from FactoryVerse.game.factory.entity.implementations.generator import GeneratorMixin
    from FactoryVerse.game.agent.embodied_actions.entity_operations import (
        EntityOperationsAction)
    from FactoryVerse.game.agent.embodied_actions.place_entity import PlacementAction
    return (RotatableMixin, Rotatable180Mixin, InserterMixin, SetRecipeMixin,
            CrafterMixin, BurnerMixin, MinerMixin, FluidMixin, BeltMixin,
            ElectricMixin, GeneratorMixin, Container, ElectricPole,
            EntityOperationsAction, PlacementAction)


# --- classification registry (every enumerated accessor MUST appear) ---------

CLASSIFICATION: Dict[Tuple[str, str], AccessorCase] = {}


def _c(owner: str, method: str, kind: Kind, group: str = "",
       engine: Expect = Expect.NONE, db: Expect = Expect.NONE,
       tracker: str = "", note: str = "") -> None:
    CLASSIFICATION[(owner, method)] = AccessorCase(
        owner, method, kind, group, engine, db, tracker, note)


# rotate: ROT-1 FIXED 2026-07-11 (this family's baseline reproduced it, the
# fix flipped all three xfails to strict-XPASS, reconciled here). The wire:
# mixins call EntityOperationsAction.rotate_entity -> remote rotate_entity ->
# event -> ops line -> DB. The fix also surfaced+closed a deeper break: typed
# entities never RECEIVED direction at all (BaseEntity **kwargs swallowed it;
# pre-fix rotate() died on AttributeError before its no-op) — mixins now own
# an __init__ that claims direction from the constructor chain.
_c("RotatableMixin", "rotate", Kind.MUTATOR, "rotate_direction",
   engine=Expect.LIVE, db=Expect.LIVE,
   note="ROT-1 fixed 2026-07-11; exact promised-value equality enforced")
_c("Rotatable180Mixin", "rotate_180", Kind.MUTATOR, "rotate_direction",
   engine=Expect.LIVE, db=Expect.LIVE,
   note="ROT-1 fixed 2026-07-11; exact promised-value equality enforced")

# inserter filter: FILT-1 FIXED 2026-07-11 (baseline reproduced both legs,
# fix flipped them, reconciled here). The fix: entity-level filter route in
# EntityInterface:set_filter (2.0 use_filters + entity.set_filter{name=...})
# + filter contract in serialize's inserter branch. DB shape (verified live):
# raw_data.inserter.{use_filters, filter_mode, filters:[{index,name}]}.
# CONF-1 remains OPEN for splitters (no write path, no serialization).
_c("InserterMixin", "set_filter", Kind.MUTATOR, "filters_and_limits",
   engine=Expect.LIVE, db=Expect.LIVE,
   note="FILT-1 fixed 2026-07-11; contracts ride the config-upsert spine")

# recipe: the LIVE spine exemplar. set_entity_recipe raises the config event
# (entity_ops.lua:123) -> full-entity upsert -> raw_data.recipe. Both legs
# expected green; the DB leg certifies the event-driven config-upsert spine.
_c("SetRecipeMixin", "set_recipe", Kind.MUTATOR, "recipe_and_spine",
   engine=Expect.LIVE, db=Expect.LIVE,
   note="DB leg reads raw_data.recipe from the ops-file replay (spine test)")

# inventory transfers: engine-effect only. DB leg barred by the boundary rule.
_c("BurnerMixin", "add_fuel", Kind.MUTATOR, "burner_crafter_io",
   engine=Expect.LIVE, db=Expect.NOT_APPLICABLE)
_c("BurnerMixin", "take_fuel", Kind.MUTATOR, "burner_crafter_io",
   engine=Expect.LIVE, db=Expect.NOT_APPLICABLE,
   note="zero prior coverage (TEST-0)")
_c("CrafterMixin", "add_ingredients", Kind.MUTATOR, "burner_crafter_io",
   engine=Expect.LIVE, db=Expect.NOT_APPLICABLE)
_c("CrafterMixin", "take_products", Kind.MUTATOR, "burner_crafter_io",
   engine=Expect.LIVE, db=Expect.NOT_APPLICABLE)
_c("Container", "store_item", Kind.MUTATOR, "container_io",
   engine=Expect.LIVE, db=Expect.NOT_APPLICABLE)
_c("Container", "take_item", Kind.MUTATOR, "container_io",
   engine=Expect.LIVE, db=Expect.NOT_APPLICABLE)

# action-layer write primitives with no typed accessor (DOC-GAP class):
_c("EntityOperationsAction", "set_inventory_limit", Kind.MUTATOR,
   "filters_and_limits", engine=Expect.LIVE, db=Expect.NONE,
   note="no typed accessor exists (audit DOC-GAP-1); zero prior coverage "
        "(TEST-0); engine truth = inventory.get_bar(); no DB surface "
        "promises the bar today")
_c("EntityOperationsAction", "take_inventory_item", Kind.MUTATOR,
   "container_io", engine=Expect.LIVE, db=Expect.NOT_APPLICABLE,
   note="zero prior direct coverage (TEST-0)")

# excluded-with-pointer (the gate still enumerates them):
_c("MinerMixin", "get_resource_search_area", Kind.READ_PROBE,
   tracker="L2.4", note="read-only; typed-transform scope")
_c("FluidMixin", "get_fluid", Kind.READ_PROBE, tracker="STUB-1",
   note="KNOWN lying read (always None, fluid.py:733); owned by the "
        "ephemeral-bridge track per 2026-07-09 adjudication, NOT this family")
_c("Container", "get_item_count", Kind.READ_PROBE,
   note="read; used BY this family as a convenience only, never as truth")
_c("ElectricPole", "get_supply_area", Kind.READ_PROBE,
   note="read; prototype-derived geometry")
_c("EntityOperationsAction", "rotate_entity", Kind.COVERED,
   tracker="rotate_direction",
   note="added 2026-07-11 by the ROT-1 fix; exercised transitively via "
        "RotatableMixin.rotate / Rotatable180Mixin.rotate_180")
_c("EntityOperationsAction", "set_entity_recipe", Kind.COVERED,
   tracker="recipe_and_spine",
   note="exercised transitively via SetRecipeMixin.set_recipe")
_c("EntityOperationsAction", "set_entity_filter", Kind.COVERED,
   tracker="filters_and_limits",
   note="exercised transitively via InserterMixin.set_filter")
_c("EntityOperationsAction", "put_inventory_item", Kind.COVERED,
   tracker="burner_crafter_io/container_io",
   note="exercised transitively via add_fuel/add_ingredients/store_item")
_c("EntityOperationsAction", "inspect_entity", Kind.COVERED, tracker="L2.4",
   note="read; certified as the typed-transform input")
_c("EntityOperationsAction", "pickup_entity", Kind.COVERED, tracker="L2.1/L4.6",
   note="place/pickup lifecycle certified there")
_c("PlacementAction", "place", Kind.COVERED, tracker="L2.1/L4.6")
_c("PlacementAction", "remove_ghost", Kind.DEFERRED, tracker="intent-provenance family",
   note="ghost lifecycle (place->label->build/remove) is that family's claim; "
        "zero coverage today is acknowledged, not ignored")


# --- completeness gate --------------------------------------------------------

def _build_matrix() -> Dict[Tuple[str, str], AccessorCase]:
    enumerated: List[Tuple[str, str]] = []
    for cls in _classes():
        for name, val in vars(cls).items():
            if inspect.isfunction(val) and not name.startswith("_"):
                enumerated.append((cls.__name__, name))

    missing = [k for k in enumerated if k not in CLASSIFICATION]
    if missing:
        raise AssertionError(
            f"UNCLASSIFIED accessors {missing} — the typed layer grew a public "
            "method; classify it in accessor_spec.py (orchestrator edit)")
    phantom = [k for k in CLASSIFICATION if k not in enumerated]
    if phantom:
        raise AssertionError(
            f"CLASSIFICATION references accessors absent from the code: {phantom}")

    for key, case in CLASSIFICATION.items():
        if case.kind is Kind.MUTATOR and not case.group:
            raise AssertionError(f"MUTATOR {key} has no group")
        if case.kind in (Kind.READ_PROBE, Kind.COVERED, Kind.DEFERRED):
            if not (case.note or case.tracker):
                raise AssertionError(f"exclusion {key} lacks a rationale/pointer")
    return dict(CLASSIFICATION)


MATRIX: Dict[Tuple[str, str], AccessorCase] = _build_matrix()

GROUPS: Tuple[str, ...] = ("rotate_direction", "filters_and_limits",
                           "recipe_and_spine", "burner_crafter_io",
                           "container_io")


def cases_for_group(group: str) -> Tuple[AccessorCase, ...]:
    return tuple(sorted((c for c in MATRIX.values()
                         if c.kind is Kind.MUTATOR and c.group == group),
                        key=lambda c: (c.owner, c.method)))


# --- extra frozen claims (no accessor of their own) ---------------------------

# 1. LABEL SURVIVAL (recipe_and_spine): a config-change upsert re-serializes
#    the whole entity and INSERT-OR-REPLACEs the whole row (sync/loader).
#    Claim: set_recipe on a LABELED entity (place(label=...)) preserves
#    map_entity.label + agent provenance through the spine. PROV-1-adjacent:
#    this is the EVENT-path leg (expected LIVE); the full-re-gather squash is
#    PROV-1 itself and is NOT this family's claim.
LABEL_SURVIVAL_GROUP = "recipe_and_spine"

# 2. SYNTHETIC PLANTS (one per named file): a deliberately mutated expectation
#    on a LIVE surface, must fail, marked strict-xfail SYNTHETIC-PLANT.
SYNTHETIC_PLANT_GROUPS = ("recipe_and_spine", "container_io")


# --- anti-vacuity floors -------------------------------------------------------

MIN_DISTINCT_TARGETS = 2   # config mutators must apply >=2 distinct values
                           # (two rotations, two recipes, two filter items,
                           # two bar values) and see EACH reflected — a single
                           # target can green on a stale read
REQUIRE_PRECONDITION_DELTA = True  # the engine pre-state MUST differ from the
                           # first target; asserting a value already present
                           # proves nothing
MIN_TRANSFER_ITEMS = 2     # inventory transfers must move >=2 items and the
                           # engine count delta must equal the accessor's
                           # reported moved count


# --- frozen engine truth-channel snippets --------------------------------------
# Sub-agents read engine state ONLY through these shapes (via runtime.lua_strict
# with a find_entity anchor). Uniformity is part of the audit surface.

ENGINE_READS: Dict[str, str] = {
    "direction":  "e.direction",                       # raw defines int
    "recipe":     "(e.get_recipe() and e.get_recipe().name) or ''",
    "filter":     "(e.get_filter(1) and (e.get_filter(1).name and "
                  "(e.get_filter(1).name.name or e.get_filter(1).name))) or ''",
    "use_filters": "e.use_filters",
    "bar":        "e.get_inventory(defines.inventory.chest).get_bar()",
    "fuel_count": "e.get_fuel_inventory() and "
                  "e.get_fuel_inventory().get_item_count('coal') or 0",
    "chest_count": "e.get_inventory(defines.inventory.chest)"
                   ".get_item_count(ITEM)",
    "input_count": "e.get_inventory(defines.inventory.assembling_machine_input)"
                   ".get_item_count(ITEM)",
    "output_count": "e.get_inventory(defines.inventory.assembling_machine_output)"
                    ".get_item_count(ITEM)",
    "furnace_source_count": "e.get_inventory(defines.inventory.furnace_source)"
                            ".get_item_count(ITEM)",
    "furnace_result_count": "e.get_inventory(defines.inventory.furnace_result)"
                            ".get_item_count(ITEM)",
}


# --- DB spine wait (frozen; deliberately NOT runtime.re_snapshot_and_wait) -----

def wait_ops_flushed(rcon, timeout_s: float = 60.0):
    """Block until the snapshot writer is IDLE with an empty write queue, so
    the config-upsert ops line for a just-raised event is on disk. Returns
    None; timeout RAISES SpecBug (lying-wait class). This does NOT trigger any
    re-gather — the event-driven spine is the surface under test."""
    import time as _t
    from _frozen import runtime as _rt
    deadline = _t.time() + timeout_s
    last = {}
    while _t.time() < deadline:
        st = _rt.lua(rcon, "return remote.call('map','get_snapshot_status')")
        last = {"phase": st.get("phase"), "write_queue": st.get("write_queue_size")}
        if last["phase"] == "IDLE" and last["write_queue"] == 0:
            return
        _t.sleep(0.5)
    raise _rt.SpecBug(f"ops flush wait timed out after {timeout_s:.0f}s (last={last})")
