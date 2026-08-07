import pytest

from FactoryVerse.game.agent.placement_hints import ConnectionQueryError, PlacementHints
from FactoryVerse.game.factory.types import Direction, MapPosition


class _Client:
    def __init__(self):
        self.call = None

    def get_water_placements(self, entity_name, area, max_results):
        self.call = (entity_name, area, max_results)
        return {
            "positions": [
                {
                    "position": {"x": -17.5, "y": 34.5},
                    "direction": Direction.SOUTH.value,
                    "approach_position": {"x": -18.5, "y": 30.5},
                    "valid": True,
                }
            ]
        }


def test_find_offshore_pump_sites_surfaces_anchor_direction_and_approach():
    hints = object.__new__(PlacementHints)
    hints._client = _Client()

    sites = hints.find_offshore_pump_sites(
        near=MapPosition(x=-14, y=34), radius=10, max_results=4
    )

    assert sites[0].position == MapPosition(x=-17.5, y=34.5)
    assert sites[0].direction is Direction.SOUTH
    assert sites[0].approach_position == MapPosition(x=-18.5, y=30.5)
    assert hints._client.call == (
        "offshore-pump",
        {
            "left_top": {"x": -24, "y": 24},
            "right_bottom": {"x": -4, "y": 44},
        },
        4,
    )


def test_find_offshore_pump_sites_rejects_stale_mod_payload():
    hints = object.__new__(PlacementHints)

    class _StaleClient:
        def get_water_placements(self, entity_name, area, max_results):
            return {
                "positions": [
                    {
                        "position": {"x": -17.5, "y": 34.5},
                        "direction": Direction.SOUTH.value,
                        "valid": True,
                    }
                ]
            }

    hints._client = _StaleClient()

    with pytest.raises(ConnectionQueryError, match="omitted approach_position"):
        hints.find_offshore_pump_sites(near=MapPosition(x=-14, y=34))


def test_find_offshore_pump_sites_orders_results_nearest_anchor_first():
    hints = object.__new__(PlacementHints)

    class _UnsortedClient:
        def get_water_placements(self, entity_name, area, max_results):
            return {
                "positions": [
                    {
                        "position": {"x": 12, "y": 0},
                        "direction": Direction.NORTH.value,
                        "approach_position": {"x": 12, "y": 4},
                    },
                    {
                        "position": {"x": 3, "y": 0},
                        "direction": Direction.NORTH.value,
                        "approach_position": {"x": 3, "y": 4},
                    },
                ]
            }

    hints._client = _UnsortedClient()

    sites = hints.find_offshore_pump_sites(near=MapPosition(x=0, y=0), radius=20)

    assert [site.position.x for site in sites] == [3.0, 12.0]


def test_generated_docs_forbid_walking_to_water_hints_or_pump_anchors():
    from FactoryVerse.utils.docs.generator import generate_api_reference
    from FactoryVerse.utils.docs.registry import reset_registry

    reset_registry()
    markdown = generate_api_reference()

    assert "Find water tiles on the map (offshore-pump sites)" not in markdown
    assert "not walkable destinations" in markdown
    assert "Never pass a returned water-tile position to walking.walk_to()" in markdown
    assert "walking.walk_to(site.approach_position" in markdown
    assert "walking.walk_to(site.position" not in markdown
    assert "pump.place(site.position, site.direction)" in markdown
    assert "await pump.place(site.position, site.direction)" not in markdown
