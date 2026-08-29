"""Documentation for the entity reference and the Phase 3B additions.

- ``entity_reference(name)``: planning-time answers about a thing on your
  cursor (Constitution §6) — footprint, buildability, supply overlay, the
  drop arrow, inserter placements, offshore pump sites. Read-only.
- ``inventory.await_item``: the one bounded in-turn wait (Constitution §9).
- ``crafting.list_recipes`` / ``research.list_technologies``: the catalogs,
  as the two HUD screens list them, read from Python.
- ``entity.status``, ``entity.can_place``, ``Container.set_limit``, and the
  pole's ``supply_area`` / ``covers`` / ``wire_reach``.
"""

from FactoryVerse.utils.docs.registry import get_registry
from FactoryVerse.utils.docs.models import Example, ErrorCase, ValidationLevel


def _register_entity_reference():
    registry = get_registry()

    from FactoryVerse.game.agent.entity_reference import EntityReferenceAccessor, EntityReference
    from FactoryVerse.game.agent.embodied_actions.inventory import AgentInventory
    from FactoryVerse.game.agent.embodied_actions.crafting import CraftingAction
    from FactoryVerse.game.agent.embodied_actions.research import ResearchAction
    from FactoryVerse.game.factory.entity.base_entity import BaseEntity
    from FactoryVerse.game.factory.entity.implementations.container import Container
    from FactoryVerse.game.factory.entity.implementations.electric_pole import ElectricPole

    # ------------------------------------------------------------------ accessor
    registry.register_class(
        cls=EntityReferenceAccessor,
        accessor_name="entity_reference",
        description="Hold an entity type on your cursor without placing it. "
        "entity_reference(\"small-electric-pole\") returns a read-only reference that answers "
        "what the placement preview would show: footprint, whether it can go here, the supply "
        "overlay a pole would project, a drill's drop arrow, where an inserter could sit between "
        "two machines, where an offshore pump could sit. It cannot place anything and holds no "
        "inventory — placing still goes through inventory.get_item(name).place().",
        decision_context="Use it while planning, before you own the item or have walked anywhere: "
        "the same questions you would answer by holding the item and looking at the preview. "
        "Every answer says where it came from: 'prototype' (static data) or 'live' (an engine "
        "check right now). Anything about a machine's contents, status or network needs the real "
        "entity, not a reference.",
        notes=[
            "Read-only: no method here changes the world",
            "Every method name also exists on the real entity class, so what you learn here transfers",
            "can_place() checks the engine's own placement rule live but not reach or inventory",
            "covers() uses the engine's box-against-box rule; a corner of a 3x3 machine inside the square counts",
        ],
        related_classes=["PlaceableItem", "ElectricPole", "Inserter"],
    )

    registry.register_class(
        cls=EntityReference,
        accessor_name="entity_reference(...)",
        description="The object entity_reference(name) returns. Read-only planning answers for one entity type.",
        decision_context="Ask it the preview questions; ask the real entity everything else.",
        notes=["Results are SourcedValue: the value plus .source ('prototype' or 'live')"],
    )

    registry.register_method(
        cls=EntityReference,
        method_name="footprint",
        description="Tiles this entity would occupy at a position and facing (source: prototype).",
        examples=[
            Example(
                code="""ref = entity_reference("stone-furnace")
tiles = ref.footprint(MapPosition(x=10, y=10))
print(len(tiles), tiles.source)  # 4 prototype""",
                decision_context="Checking how much room a machine takes before walking over",
                expected_outcome="A list of TilePosition, with .source == 'prototype'",
                validation_level=ValidationLevel.SYNTAX,
            )
        ],
    )
    registry.register_method(
        cls=EntityReference,
        method_name="can_place",
        description="Could this be placed here right now? The engine's red/green preview, read live. "
        "Reach and inventory are not checked — the reference holds nothing.",
        examples=[
            Example(
                code="""ref = entity_reference("burner-mining-drill")
ok = ref.can_place(MapPosition(x=34.5, y=-90.5), Direction.NORTH)
if ok:
    drill = inventory.get_item("burner-mining-drill").place(MapPosition(x=34.5, y=-90.5), Direction.NORTH)""",
                decision_context="Testing a spot before committing to walk there and place",
                expected_outcome="SourcedValue(True/False, source='live')",
                validation_level=ValidationLevel.SYNTAX,
            )
        ],
        error_cases=[
            ErrorCase(
                exception="RuntimeError",
                when="The reference was created without a live engine",
                resolution="Only happens offline; in a run every reference is live",
            )
        ],
    )
    registry.register_method(
        cls=EntityReference,
        method_name="supply_area",
        description="The supply box a pole would project from a position (source: prototype). Poles only.",
        examples=[
            Example(
                code="""pole = entity_reference("small-electric-pole")
box = pole.supply_area(MapPosition(x=0, y=0))
print(box)""",
                decision_context="Seeing the overlay before placing a pole",
                expected_outcome="A BoundingBox centre ± supply_area_distance",
                validation_level=ValidationLevel.SYNTAX,
            )
        ],
    )
    registry.register_method(
        cls=EntityReference,
        method_name="covers",
        description="Would a pole at this position power that entity? Box-against-box, the engine's rule. Poles only.",
        examples=[
            Example(
                code="""pole = entity_reference("small-electric-pole")
drill = reachable_view.get_entity("electric-mining-drill")
if drill and pole.covers(MapPosition(x=drill.position.x + 3, y=drill.position.y), drill):
    print("a pole 3 tiles east would power the drill")""",
                decision_context="Choosing where a pole goes so a machine is inside its area",
                expected_outcome="SourcedValue(True/False, source='prototype')",
                validation_level=ValidationLevel.SYNTAX,
            )
        ],
    )
    registry.register_method(
        cls=EntityReference,
        method_name="wire_reach",
        description="Would a pole here be within wire distance of that pole? A bound, not a promise of wiring. Poles only.",
    )
    registry.register_method(
        cls=EntityReference,
        method_name="drop_position",
        description="Where a drill at this position and facing drops its output — the arrow on the cursor. Drills only.",
        examples=[
            Example(
                code="""drill = entity_reference("burner-mining-drill")
drop = drill.drop_position(MapPosition(x=34.5, y=-90.5), Direction.NORTH)
print(drop)  # the tile a chest or belt must occupy""",
                decision_context="Deciding where the chest or belt goes before placing the drill",
                expected_outcome="SourcedValue(MapPosition, source='prototype')",
                validation_level=ValidationLevel.SYNTAX,
            )
        ],
    )
    registry.register_method(
        cls=EntityReference,
        method_name="placements_between",
        description="Positions and facings where this inserter would move items from one placed entity into another. "
        "Both entities must exist. Zero candidates come back with a reason, never as an error. Inserters only.",
        examples=[
            Example(
                code="""chest = reachable_view.get_entity("wooden-chest")
furnace = reachable_view.get_entity("stone-furnace")
answer = entity_reference("inserter").placements_between(chest, furnace)
for position, direction in answer["positions"]:
    print(position, direction)
if not answer["positions"]:
    print("why:", answer["reason"])""",
                decision_context="Linking two machines with an inserter",
                expected_outcome="SourcedValue({'positions': [(MapPosition, Direction), ...], 'reason': str|None}, source='live')",
                validation_level=ValidationLevel.SYNTAX,
            )
        ],
    )
    registry.register_method(
        cls=EntityReference,
        method_name="sites",
        description="Where an offshore pump could sit near a position, with its required facing and a standable approach position. Offshore pumps only.",
        examples=[
            Example(
                code="""sites = entity_reference("offshore-pump").sites(walking.position, radius=30)
for site in sites:
    print(site.position, site.direction, site.approach_position)""",
                decision_context="Finding water to start power",
                expected_outcome="SourcedValue(list of ConnectionPosition, source='live')",
                validation_level=ValidationLevel.SYNTAX,
            )
        ],
    )

    # ------------------------------------------------------------ inventory wait
    registry.register_method(
        cls=AgentInventory,
        method_name="await_item",
        description="Wait, bounded, for an item to be in your inventory. Returns at once if held; refuses at once "
        "if nothing in your crafting queue produces it; otherwise waits up to timeout_ticks and returns "
        "actuals — never raises. The wait spends the turn's clock like anything else.",
        examples=[
            Example(
                code="""crafting.enqueue("iron-gear-wheel", count=5)
got = await inventory.await_item("iron-gear-wheel", count=5, timeout_ticks=600)
if got:
    print("have", got.have)
else:
    print(got.reason, "have", got.have, "still queued", got.remaining_in_queue)""",
                decision_context="Needing crafted items in this same turn before placing them",
                expected_outcome="AwaitItemResult; truthy when satisfied",
                validation_level=ValidationLevel.SYNTAX,
            )
        ],
        decision_points=[
            "Prefer the state-join: check inventory.check_total() at the start of the block that needs the items",
            "Use await_item when the craft is short and you will place the items this turn",
            "A long craft outlasts the bound: end the turn and the items arrive while the world runs",
        ],
    )

    # ---------------------------------------------------------------- catalogs
    registry.register_method(
        cls=CraftingAction,
        method_name="list_recipes",
        description="The recipe catalog as the crafting screen lists it. A read — nothing is queued. "
        "hand_craftable tells you whether a character can make it (smelting is machine-only); "
        "craftable_now is an annotation, not a filter.",
        examples=[
            Example(
                code="""for r in crafting.list_recipes(name_filter="iron", hand_craftable=True):
    print(r["name"], r["ingredients"], "now" if r["craftable_now"] else "")""",
                decision_context="Finding what you can hand-craft from what you hold",
                expected_outcome="A list of dicts sorted by name",
                validation_level=ValidationLevel.SYNTAX,
            )
        ],
    )
    registry.register_method(
        cls=CraftingAction,
        method_name="predictions",
        description="The completion predictions recorded at enqueue (recipe energy at speed 1, summed serially) "
        "that no turn report has consumed yet.",
        examples=[
            Example(
                code="""crafting.enqueue("iron-gear-wheel", count=5)
for p in crafting.predictions:
    print(p.recipe, p.count, "done by tick", p.predicted_completion_tick)""",
                decision_context="Seeing when queued crafts will finish, in game ticks",
                expected_outcome="A list of CraftPrediction",
                validation_level=ValidationLevel.SYNTAX,
            )
        ],
    )
    registry.register_method(
        cls=CraftingAction,
        method_name="take_predictions",
        description="Hand the completion predictions recorded at enqueue to the turn report and clear them. "
        "The report calls this once per turn; you do not need to.",
        examples=[
            Example(
                code="""pending = crafting.take_predictions()
print(len(pending), "predictions handed to the report")""",
                decision_context="Harness use; the turn report does this for you",
                expected_outcome="The pending CraftPrediction list, now cleared",
                validation_level=ValidationLevel.SYNTAX,
            )
        ],
    )
    registry.register_method(
        cls=ResearchAction,
        method_name="list_technologies",
        description="The technology catalog as the research screen lists it. A read — nothing is queued. "
        "available means every prerequisite is researched and it can be queued now. Use this to discover "
        "names; never discover by enqueueing.",
        examples=[
            Example(
                code="""for t in research.list_technologies(available=True):
    print(t["name"], t["science_packs"], t["unit_count"], "unlocks", t["unlocks"])""",
                decision_context="Choosing the next research",
                expected_outcome="A list of dicts: available first, then locked, then researched",
                validation_level=ValidationLevel.SYNTAX,
            )
        ],
    )

    # -------------------------------------------------------------- entity side
    registry.register_method(
        cls=BaseEntity,
        method_name="status",
        description="The entity's status name, read live in one roundtrip: 'working', 'no_fuel', 'no_power', "
        "'full_output' … Never cached; .source says which tick it was read at. Ghosts have no status.",
        examples=[
            Example(
                code="""furnace = reachable_view.get_entity("stone-furnace")
if furnace and furnace.status == "no_fuel":
    furnace.add_fuel(inventory.create_item_stacks("coal", 10))""",
                decision_context="Reading a machine's problem before acting on it",
                expected_outcome="A LiveStatus string with .source like 'live:36480'",
                validation_level=ValidationLevel.SYNTAX,
            )
        ],
    )
    registry.register_method(
        cls=BaseEntity,
        method_name="can_place",
        description="Could an entity of this type be placed at a position right now? The engine's preview, read live.",
    )
    registry.register_method(
        cls=Container,
        method_name="set_limit",
        description="Set the inventory bar on a chest — how many slots accept items. None clears it. "
        "The red bar you drag in the chest window.",
        examples=[
            Example(
                code="""chest = reachable_view.get_entity("wooden-chest")
if chest:
    chest.set_limit(4)""",
                decision_context="Stopping a chest from swallowing a whole belt's output",
                expected_outcome="A dict from the engine with success and the new limit",
                validation_level=ValidationLevel.SYNTAX,
            )
        ],
    )
    registry.register_method(
        cls=ElectricPole,
        method_name="supply_area",
        description="The supply box this pole projects (or would project from a given position). Static geometry.",
    )
    registry.register_method(
        cls=ElectricPole,
        method_name="covers",
        description="Does this pole power that entity? Box-against-box, the engine's rule.",
    )
    registry.register_method(
        cls=ElectricPole,
        method_name="wire_reach",
        description="Is that pole within wire distance? A bound from the prototypes, not a statement of wiring.",
    )
