from FactoryVerse.game.agent.placement_hints import PlacementHints
from FactoryVerse.game.factory.types import Direction, MapPosition


class _Client:
    def __init__(self):
        self.call = None

    def get_water_placements(self, entity_name, area, max_results):
        self.call = (entity_name, area, max_results)
        return {
            "positions": [
                {
                    "position": {"x": -18, "y": 34},
                    "direction": Direction.SOUTH.value,
                    "valid": True,
                }
            ]
        }


def test_find_offshore_pump_sites_surfaces_validated_anchor_and_direction():
    hints = object.__new__(PlacementHints)
    hints._client = _Client()

    sites = hints.find_offshore_pump_sites(
        near=MapPosition(x=-14, y=34), radius=10, max_results=4
    )

    assert sites[0].position == MapPosition(x=-18, y=34)
    assert sites[0].direction is Direction.SOUTH
    assert hints._client.call == (
        "offshore-pump",
        {
            "left_top": {"x": -24, "y": 24},
            "right_bottom": {"x": -4, "y": 44},
        },
        4,
    )
