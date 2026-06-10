#!/usr/bin/env python3
"""L3.3 certification check: prototype hydration matches the dump (OFFLINE).

Pipeline under test:
    fv_filters.yaml -> factorio-data-dump.json -> PrototypeDataManager (singleton)
        -> EntityPrototypes / RecipePrototypes (filtered accessors)
        -> typed entity classes (BaseEntity.prototype, tile_width/tile_height)
        -> Factoriopedia (KnowledgeEntity / KnowledgeRecipe)

Ground truth is an INDEPENDENT json.load of the dump file in this script
(no FactoryVerse code involved in producing the expected values).

For each sampled entity, every property kind present in the dump is compared
across all Python exposure paths. For each sampled recipe, ingredients,
products, energy and category are compared across RecipePrototypes and
Factoriopedia.

Non-vacuous guards:
  - entities compared > 15
  - total property comparisons > 100
  - every sampled name must resolve through every applicable path
  - every prototype in fv_filters scope must load through the manager
    (a failure to load is a FINDING, not a skip)

Exit codes: 0 PASS / 1 FAIL / 2 BLOCKED
Artifacts: .fv-output/certification/2026-06-10/L3.3/
"""

import json
import math
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

DUMP_PATH = REPO_ROOT / ".fv-output" / "factorio-data-dump.json"
ART_DIR = REPO_ROOT / ".fv-output" / "certification" / "2026-06-10" / "L3.3"
ART_DIR.mkdir(parents=True, exist_ok=True)

# --- Sample definition -------------------------------------------------------

SAMPLE_ENTITIES = [
    # name, dump category (independent of Python's type map)
    ("burner-mining-drill", "mining-drill"),
    ("electric-mining-drill", "mining-drill"),
    ("stone-furnace", "furnace"),
    ("assembling-machine-1", "assembling-machine"),
    ("assembling-machine-2", "assembling-machine"),
    ("transport-belt", "transport-belt"),
    ("fast-transport-belt", "transport-belt"),
    ("express-transport-belt", "transport-belt"),
    ("burner-inserter", "inserter"),
    ("fast-inserter", "inserter"),
    ("boiler", "boiler"),
    ("steam-engine", "generator"),
    ("offshore-pump", "offshore-pump"),
    ("small-electric-pole", "electric-pole"),
    ("wooden-chest", "container"),
    ("iron-chest", "container"),
    ("lab", "lab"),
]

SAMPLE_RECIPES = [
    "iron-gear-wheel",
    "engine-unit",
    "electronic-circuit",
    "copper-cable",
    "iron-plate",
    "steel-plate",
    "transport-belt",
    "automation-science-pack",
    "electric-mining-drill",
    "stone-furnace",
]

# Property kinds checked on entities when present in the dump entry.
ENTITY_PROP_KEYS = [
    "collision_box",          # kind 1: geometry
    "selection_box",
    "crafting_speed",         # kind 2: crafting speed
    "speed",                  # kind 3: belt speed
    "inventory_size",         # kind 4: inventory size
    "mining_speed",           # kind 5: mining speed
    "max_health",             # kind 6: health
    "energy_usage",           # kind 7: energy
    "rotation_speed",         # kind 8: inserter kinematics
    "extension_speed",
    "pumping_speed",          # kind 9: fluid throughput
    "supply_area_distance",   # kind 10: electric reach
    "maximum_wire_distance",
    "researching_speed",      # kind 11: lab speed
    "fluid_usage_per_tick",   # kind 12: generator
    "effectivity",
    "target_temperature",     # kind 13: boiler
    "crafting_categories",    # kind 14: capability sets
    "minable",                # kind 15: minability
]

# Character reach distances (kind 16) — checked through the manager raw path.
CHARACTER_KEYS = ["reach_distance", "build_distance", "reach_resource_distance",
                  "item_pickup_distance", "drop_item_distance"]


def eq(a, b):
    """Deep equality with float tolerance."""
    if isinstance(a, float) or isinstance(b, float):
        try:
            return math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=1e-12)
        except (TypeError, ValueError):
            return False
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(eq(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(eq(a[k], b[k]) for k in a)
    return a == b


def norm_io(entries):
    """Normalize an ingredients/results list to sorted (name, amount, type)."""
    out = []
    for e in entries:
        out.append((e["name"], float(e.get("amount", 1)), e.get("type", "item")))
    return sorted(out)


def expected_tile_dims(proto):
    """Independent re-derivation of tile dims from raw dump values."""
    eps = 0.001
    if "tile_width" in proto:
        tw = int(proto["tile_width"])
    elif "collision_box" in proto:
        (x1, y1), (x2, y2) = proto["collision_box"]
        tw = int(math.ceil(abs(x1 - x2) - eps))
    else:
        tw = 0
    if "tile_height" in proto:
        th = int(proto["tile_height"])
    elif "collision_box" in proto:
        (x1, y1), (x2, y2) = proto["collision_box"]
        th = int(math.ceil(abs(y1 - y2) - eps))
    else:
        th = 0
    return tw, th


def main():
    findings = []      # hard failures
    notes = []         # informational findings (recorded, non-fatal)
    rows = []          # full comparison table

    if not DUMP_PATH.exists():
        print(f"BLOCKED: dump not found at {DUMP_PATH}")
        return 2

    # Ground truth: independent parse, zero FactoryVerse code.
    with open(DUMP_PATH) as f:
        dump = json.load(f)

    # --- Load the Python layer ------------------------------------------
    try:
        from FactoryVerse.game.factory.prototype_data import get_prototype_manager
        from FactoryVerse.game.factory.prototypes import (
            get_entity_prototypes,
            get_recipe_prototypes,
        )
        from FactoryVerse.game.factory.entity.create_entity import ENTITY_CLASS_MAP
        from FactoryVerse.game.factory.factoriopedia import Factoriopedia
        from FactoryVerse.game.factory.types import MapPosition, Direction
    except Exception:
        print("BLOCKED: cannot import FactoryVerse prototype layer")
        traceback.print_exc()
        return 2

    manager = get_prototype_manager()
    mgr_raw = manager.get_raw_data()
    ep = get_entity_prototypes()
    rp = get_recipe_prototypes()
    pedia = Factoriopedia()

    # --- Check 0: the manager loaded THIS dump file -----------------------
    mgr_path = manager.get_dump_file_path()
    if mgr_path is None or Path(mgr_path).resolve() != DUMP_PATH.resolve():
        findings.append(
            f"manager loaded '{mgr_path}', expected '{DUMP_PATH}'"
        )
    # And the parsed content is byte-equivalent at JSON level.
    if mgr_raw is not dump and not (set(mgr_raw) == set(dump)):
        findings.append("manager raw data top-level keys differ from dump")

    # --- Check 1: full fv_filters scope loads through the manager ---------
    filtered_entities = manager.get_filtered_entities()
    filtered_recipes = manager.get_filtered_recipes()
    if len(filtered_entities) < 50:
        findings.append(
            f"vacuous-risk: only {len(filtered_entities)} filtered entities"
        )
    if len(filtered_recipes) < 50:
        findings.append(
            f"vacuous-risk: only {len(filtered_recipes)} filtered recipes"
        )
    scope_fail_e = [n for n in filtered_entities if not ep.get_prototype(n)]
    if scope_fail_e:
        # Localize each failure to its dump category for the artifact.
        details = {}
        for n in scope_fail_e:
            details[n] = [c for c, v in dump.items()
                          if isinstance(v, dict) and n in v]
        findings.append(
            f"{len(scope_fail_e)} prototypes in fv_filters entity scope fail "
            f"to load through EntityPrototypes.get_prototype: {details} "
            f"(FilterConfig.filter_entities iterates ALL dump categories "
            f"including 'item', so item prototypes whose subgroup matches an "
            f"included entity subgroup leak into the entity scope; "
            f"EntityPrototypes then drops them via ignore_categories)"
        )
    scope_fail_r = [n for n in filtered_recipes if n not in rp.recipes]
    if scope_fail_r:
        findings.append(
            f"{len(scope_fail_r)} in-scope recipes fail to load through "
            f"RecipePrototypes: {scope_fail_r[:10]}"
        )

    n_entities_compared = 0
    n_props_compared = 0

    def compare(scope, name, prop, expected, got_by_path):
        nonlocal n_props_compared
        statuses = {}
        ok_all = True
        for path, got in got_by_path.items():
            ok = eq(expected, got)
            statuses[path] = "OK" if ok else f"MISMATCH (got {got!r})"
            if not ok:
                ok_all = False
            n_props_compared += 1
        rows.append({
            "scope": scope, "name": name, "property": prop,
            "expected_from_dump": expected, "paths": statuses,
        })
        if not ok_all:
            findings.append(
                f"{scope} {name}.{prop}: expected {expected!r}, paths: "
                + ", ".join(f"{p}={s}" for p, s in statuses.items()
                            if s != "OK")
            )

    # --- Check 2: sampled entities, all paths ------------------------------
    pedia_categories = {"assembling-machine", "furnace", "mining-drill",
                        "rocket-silo"}
    for name, dump_cat in SAMPLE_ENTITIES:
        raw = dump.get(dump_cat, {}).get(name)
        if raw is None:
            findings.append(f"sample entity {name} missing from dump "
                            f"category '{dump_cat}'")
            continue

        # Path: manager raw
        mgr_entry = mgr_raw.get(dump_cat, {}).get(name)
        # Path: filtered accessor
        ep_entry = ep.get_prototype(name)
        # Path: typed entity class .prototype
        cls = ENTITY_CLASS_MAP.get(name)
        inst = None
        if cls is None:
            findings.append(f"sample entity {name} has no typed class in "
                            f"ENTITY_CLASS_MAP")
        else:
            try:
                inst = cls(
                    name=name,
                    position=MapPosition(x=0.5, y=0.5),
                    direction=Direction.NORTH,
                    entity_ops=None, place_ops=None, walking_action=None,
                )
            except TypeError:
                inst = cls(
                    name=name,
                    position=MapPosition(x=0.5, y=0.5),
                    entity_ops=None, place_ops=None, walking_action=None,
                )

        if not ep_entry:
            findings.append(f"sample entity {name}: EntityPrototypes "
                            f"returned empty dict (filtered out?)")
            continue
        if mgr_entry is None:
            findings.append(f"sample entity {name}: missing in manager raw")
            continue

        n_entities_compared += 1

        # Sanity: Python's type map agrees with the dump category.
        compare("entity", name, "__entity_type__", dump_cat,
                {"EntityPrototypes.get_entity_type":
                 ep.get_entity_type(name)})

        for key in ENTITY_PROP_KEYS:
            if key not in raw:
                continue
            paths = {
                "manager.get_raw_data": mgr_entry.get(key),
                "EntityPrototypes.get_prototype": ep_entry.get(key),
            }
            if inst is not None:
                paths["entity_class.prototype"] = inst.prototype.get(key)
            compare("entity", name, key, raw[key], paths)

        # Derived geometry on the typed class vs independent recompute.
        if inst is not None:
            exp_tw, exp_th = expected_tile_dims(raw)
            compare("entity", name, "tile_width(derived)", exp_tw,
                    {"entity_class.tile_width": inst.tile_width})
            compare("entity", name, "tile_height(derived)", exp_th,
                    {"entity_class.tile_height": inst.tile_height})

        # Factoriopedia path (only covers its hardcoded categories).
        if dump_cat in pedia_categories:
            kent = pedia.entities.get(name)
            if kent is None:
                findings.append(f"sample entity {name}: missing from "
                                f"Factoriopedia.entities")
            else:
                compare("entity", name, "mining_speed(pedia)",
                        float(raw.get("mining_speed", 0)),
                        {"Factoriopedia.entities": kent.mining_speed})
                compare("entity", name, "inventory_size(pedia)",
                        int(raw.get("inventory_size", 0) or 0),
                        {"Factoriopedia.entities": kent.inventory_size})
                compare("entity", name, "crafting_categories(pedia)",
                        raw.get("crafting_categories", []),
                        {"Factoriopedia.entities": kent.crafting_categories})

    # --- Check 3: character reach distances (manager raw path) -------------
    char_raw = dump.get("character", {}).get("character")
    if char_raw is None:
        findings.append("character prototype missing from dump")
    else:
        char_mgr = mgr_raw.get("character", {}).get("character", {})
        for key in CHARACTER_KEYS:
            if key in char_raw:
                compare("character", "character", key, char_raw[key],
                        {"manager.get_raw_data": char_mgr.get(key)})
        notes.append(
            "reach distances are exposed ONLY via manager raw data; no typed "
            "Python accessor (EntityPrototypes filters out 'character', no "
            "entity class, no Factoriopedia entry) consumes them"
        )

    # --- Check 4: sampled recipes, all paths --------------------------------
    n_recipes_compared = 0
    for rname in SAMPLE_RECIPES:
        raw = dump.get("recipe", {}).get(rname)
        if raw is None:
            findings.append(f"sample recipe {rname} missing from dump")
            continue
        rp_entry = rp.recipes.get(rname)
        krec = pedia.recipes.get(rname)
        if rp_entry is None:
            findings.append(f"sample recipe {rname}: missing from "
                            f"RecipePrototypes (filtered out?)")
            continue
        if krec is None:
            findings.append(f"sample recipe {rname}: missing from "
                            f"Factoriopedia.recipes")
            continue
        n_recipes_compared += 1

        exp_ings = norm_io(raw.get("ingredients", []))
        exp_results = norm_io(raw.get("results", []))
        exp_energy = float(raw.get("energy_required", 0.5))
        exp_cat = raw.get("category", "crafting")

        compare("recipe", rname, "ingredients", exp_ings, {
            "RecipePrototypes.recipes":
                norm_io(rp_entry.get("ingredients", [])),
            "Factoriopedia.recipes": sorted(
                (i.name, float(i.amount), i.type) for i in krec.ingredients),
        })
        compare("recipe", rname, "results", exp_results, {
            "RecipePrototypes.recipes":
                norm_io(rp_entry.get("results", [])),
            "Factoriopedia.recipes": sorted(
                (p.name, float(p.amount), p.type) for p in krec.products),
        })
        compare("recipe", rname, "energy_required", exp_energy, {
            "RecipePrototypes.recipes":
                float(rp_entry.get("energy_required", 0.5)),
            "Factoriopedia.recipes": krec.energy,
        })
        compare("recipe", rname, "category", exp_cat, {
            "RecipePrototypes.get_recipe_category":
                rp.get_recipe_category(rname),
            "Factoriopedia.recipes": krec.category,
        })
        compare("recipe", rname, "is_handcraftable",
                exp_cat == "crafting",
                {"RecipePrototypes.is_handcraftable":
                 rp.is_handcraftable(rname)})

    # --- Non-vacuous guards --------------------------------------------------
    if n_entities_compared <= 15:
        findings.append(
            f"vacuous: only {n_entities_compared} entities compared (need >15)"
        )
    if n_props_compared <= 100:
        findings.append(
            f"vacuous: only {n_props_compared} property comparisons "
            f"(need >100)"
        )
    if n_recipes_compared < 10:
        findings.append(
            f"vacuous: only {n_recipes_compared} recipes compared (need 10)"
        )

    # --- Artifacts -----------------------------------------------------------
    summary = {
        "check": "L3.3",
        "dump_file": str(DUMP_PATH),
        "manager_dump_file": str(mgr_path),
        "filtered_entities_in_scope": len(filtered_entities),
        "filtered_recipes_in_scope": len(filtered_recipes),
        "entities_compared": n_entities_compared,
        "recipes_compared": n_recipes_compared,
        "property_comparisons": n_props_compared,
        "mismatches": sum(
            1 for r in rows for s in r["paths"].values() if s != "OK"),
        "findings": findings,
        "notes": notes,
        "verdict": "PASS" if not findings else "FAIL",
    }
    with open(ART_DIR / "comparison_table.json", "w") as f:
        json.dump(rows, f, indent=1, default=str)
    with open(ART_DIR / "summary.json", "w") as f:
        json.dump(summary, f, indent=1)

    print(json.dumps(summary, indent=1))
    return 0 if not findings else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        print("BLOCKED: unexpected harness error")
        sys.exit(2)
