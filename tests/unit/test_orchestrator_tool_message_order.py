"""TOOLMSG-1 — every tool_call_id is answered before anything else is said.

Providers reject a history where a non-tool message sits between an assistant
message carrying tool_calls and the tool messages answering them:

    assistant(tool_calls=[A, B]) -> tool(A) -> user("Game Events...") -> tool(B)

    400: An assistant message with 'tool_calls' must be followed by tool
         messages responding to each 'tool_call_id'.

Game-event notifications enter the history as a *user* message, and the drain
used to run inside the per-tool-call loop, so any turn where the model emitted
two tool calls and an event landed between them killed the run. Observed live:
a freeplay run died on its second turn, 14 seconds in.

Under the turn contract (2026-08-29) the drain runs once per turn, at the
boundary, into the turn report — so inside a turn nothing is injected at all
(tests/unit/test_turn_contract.py pins that). The helper below is what the
boundary uses, and this file keeps pinning the provider's ordering rule on it.

These tests exercise the ordering rule directly against the message list the
orchestrator builds, so the invariant is pinned without needing a provider.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from FactoryVerse.infra.llm.orchestrator import AgentOrchestrator


def assert_tool_calls_are_answered_contiguously(messages: List[Dict[str, Any]]) -> None:
    """The provider's rule, stated once: after an assistant message with N tool
    calls, the next N messages must be the tool replies, in any order but with
    nothing else in between."""
    for index, message in enumerate(messages):
        tool_calls = message.get("tool_calls") or []
        if message.get("role") != "assistant" or not tool_calls:
            continue
        expected_ids = {call["id"] for call in tool_calls}
        replies = messages[index + 1 : index + 1 + len(expected_ids)]
        roles = [reply.get("role") for reply in replies]
        assert roles == ["tool"] * len(expected_ids), (
            f"messages {index + 1}..{index + len(expected_ids)} must all be tool "
            f"replies, got {roles}"
        )
        assert {reply.get("tool_call_id") for reply in replies} == expected_ids


def _orchestrator() -> AgentOrchestrator:
    orch = AgentOrchestrator.__new__(AgentOrchestrator)
    orch.messages = []
    orch.trajectory = None
    orch.turn_number = 0
    return orch


def test_the_broken_interleaving_is_detected():
    """Guard the guard: the assertion must actually catch the bad shape."""
    orch = _orchestrator()
    orch.messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "call_a", "function": {"name": "execute_dsl"}},
                {"id": "call_b", "function": {"name": "execute_duckdb"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call_a", "content": "ok"},
        {"role": "user", "content": "**Game Events:**\n\nResearch complete"},
        {"role": "tool", "tool_call_id": "call_b", "content": "ok"},
    ]

    with pytest.raises(AssertionError):
        assert_tool_calls_are_answered_contiguously(orch.messages)


def test_notifications_after_all_tool_replies_is_accepted():
    """The shape the fixed drain produces."""
    orch = _orchestrator()
    orch.messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "call_a", "function": {"name": "execute_dsl"}},
                {"id": "call_b", "function": {"name": "execute_duckdb"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call_a", "content": "ok"},
        {"role": "tool", "tool_call_id": "call_b", "content": "ok"},
        {"role": "user", "content": "**Game Events:**\n\nResearch complete"},
    ]

    assert_tool_calls_are_answered_contiguously(orch.messages)


@pytest.mark.asyncio
async def test_notification_drain_appends_after_the_tool_replies():
    """The real drain, against a stub event stream, must land last."""

    class _Events:
        async def drain(self, timeout=0.05):
            return [{"category": "research", "text": "automation complete"}]

        def format_events(self, events):
            return "Research complete: automation"

    class _Runtime:
        events = _Events()

    orch = _orchestrator()
    orch.runtime = _Runtime()
    orch.console = type("_C", (), {"system_notification": staticmethod(lambda _m: None)})()
    orch.chat_log_path = None
    orch._log_to_chat = lambda _text: None
    orch.messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "call_a", "function": {"name": "execute_dsl"}},
                {"id": "call_b", "function": {"name": "execute_duckdb"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call_a", "content": "ok"},
        {"role": "tool", "tool_call_id": "call_b", "content": "ok"},
    ]

    await orch._add_notifications_to_messages()

    assert orch.messages[-1]["role"] == "user"
    assert "Research complete" in orch.messages[-1]["content"]
    assert_tool_calls_are_answered_contiguously(orch.messages)
