"""Typed research notifications retain every capability effect."""

from FactoryVerse.game.agent.event_stream import GameEvent, ResearchFinishedEvent


def test_research_finished_event_exposes_recipes_and_effects():
    event = GameEvent.from_payload(
        {
            "notification_type": "research_finished",
            "agent_id": 1,
            "tick": 420,
            "data": {
                "technology": "automation",
                "unlocked_recipes": ["assembling-machine-1", "long-handed-inserter"],
                "effects": [
                    {"type": "unlock-recipe", "recipe": "assembling-machine-1"},
                    {"type": "laboratory-speed", "modifier": 0.2},
                ],
                "level": 1,
            },
        }
    )

    assert isinstance(event, ResearchFinishedEvent)
    assert event.technology == "automation"
    assert event.unlocked_recipes == ["assembling-machine-1", "long-handed-inserter"]
    assert event.effects == [
        {"type": "unlock-recipe", "recipe": "assembling-machine-1"},
        {"type": "laboratory-speed", "modifier": 0.2},
    ]
    assert event.to_dict() == {
        "notification_type": "research_finished",
        "agent_id": 1,
        "tick": 420,
        "data": event.data,
        "critical": True,
    }
