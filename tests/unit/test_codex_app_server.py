import asyncio
import json
from pathlib import Path

import pytest

from FactoryVerse.integrations.codex import CodexAppServer


@pytest.mark.asyncio
async def test_thread_instructions_goal_and_turn_are_separate(tmp_path):
    client = CodexAppServer()
    requests = []
    notifications = asyncio.Queue()

    async def request(method, params):
        requests.append((method, params))
        if method == "thread/start":
            return {"thread": {"id": "thread-1"}}
        if method == "thread/goal/set":
            return {"goal": {"objective": params["objective"], "status": "active"}}
        if method == "turn/start":
            return {"turn": {"id": "turn-1"}}
        raise AssertionError(method)

    async def wait_notification(method, *, timeout=None):
        assert method == "turn/completed"
        return await notifications.get()

    client.request = request
    client.wait_notification = wait_notification

    thread_id = await client.start_thread(
        cwd=tmp_path,
        model="gpt-test",
        developer_instructions="stable harness contract",
    )
    await client.set_goal(thread_id, "campaign objective")
    await notifications.put(
        {
            "threadId": thread_id,
            "turn": {
                "id": "turn-1",
                "status": "completed",
                "items": [{"type": "agentMessage", "text": '{"ok":true}'}],
            },
        }
    )
    result = await client.run_turn(
        thread_id=thread_id,
        prompt="begin",
        output_schema={"type": "object"},
        timeout_seconds=1,
    )

    start_params = requests[0][1]
    assert start_params["developerInstructions"] == "stable harness contract"
    assert "baseInstructions" not in start_params
    assert requests[1] == (
        "thread/goal/set",
        {
            "threadId": "thread-1",
            "objective": "campaign objective",
            "status": "active",
        },
    )
    assert requests[2][0] == "turn/start"
    assert requests[2][1]["input"] == [{"type": "text", "text": "begin"}]
    assert result.text == '{"ok":true}'


def test_goal_rejects_empty_and_oversized_objectives():
    client = CodexAppServer()

    with pytest.raises(ValueError, match="must not be empty"):
        asyncio.run(client.set_goal("thread-1", "  "))
    with pytest.raises(ValueError, match="exceeds 4000"):
        asyncio.run(client.set_goal("thread-1", "x" * 4001))


def test_app_server_records_protocol_without_harness_knowledge(tmp_path: Path):
    log = tmp_path / "events.jsonl"
    client = CodexAppServer(event_log_path=log)

    client._record("client", {"method": "thread/start"})

    value = json.loads(log.read_text())
    assert value == {
        "direction": "client",
        "message": {"method": "thread/start"},
    }
