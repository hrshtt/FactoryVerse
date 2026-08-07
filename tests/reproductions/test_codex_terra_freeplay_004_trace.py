"""Forensic assertions over the preserved Codex Terra freeplay-004 trace.

This is not a causal live test. It prevents the retrospective from drifting
away from its raw artifacts and can be rerun wherever the campaign directory
has been preserved:

    FV_REPRO_RUN_004=.fv-output/freeplay/codex-terra-factory-debug-20260807-004 \
      uv run pytest -q tests/reproductions/test_codex_terra_freeplay_004_trace.py
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest


RUN_ROOT_TEXT = os.environ.get("FV_REPRO_RUN_004")
pytestmark = pytest.mark.skipif(
    not RUN_ROOT_TEXT,
    reason="set FV_REPRO_RUN_004 to the preserved campaign directory",
)


def _read_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


@pytest.fixture(scope="module")
def run_root() -> Path:
    root = Path(RUN_ROOT_TEXT).resolve()
    required = [
        root / "transcript" / "runtime-protocol.jsonl",
        root / "harness-control" / "codex-app-server.jsonl",
        root / "checkpoints" / "cp-000004-tick-1678482" / "checkpoint.json",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    assert missing == [], f"missing preserved run artifacts: {missing}"
    return root


def test_runtime_trace_reproduces_manual_service_without_logistics_placement(run_root):
    records = list(_read_jsonl(run_root / "transcript" / "runtime-protocol.jsonl"))
    programs = [
        record["request"]["source"]
        for record in records
        if record.get("direction") == "actor_request"
        and record.get("request", {}).get("op") == "execute"
    ]

    placement_patterns = {
        "transport-belt": re.compile(
            r"placement\.place(?:_entity)?\([^\n]*['\"]transport-belt['\"]"
        ),
        "electric-mining-drill": re.compile(
            r"placement\.place(?:_entity)?\([^\n]*['\"]electric-mining-drill['\"]"
        ),
    }

    assert len(programs) == 115
    assert sum("put_inventory_item" in source for source in programs) == 75
    assert sum(
        any(
            operation in source
            for operation in (
                "take_inventory_item",
                "take_all_inventory_items",
                "take_products",
                "take_fuel",
            )
        )
        for source in programs
    ) == 49
    assert {
        entity: sum(bool(pattern.search(source)) for source in programs)
        for entity, pattern in placement_patterns.items()
    } == {"transport-belt": 0, "electric-mining-drill": 0}


def test_codex_trace_reproduces_context_pressure_and_compactions(run_root):
    records = _read_jsonl(run_root / "harness-control" / "codex-app-server.jsonl")
    completed_items = [
        record["message"]["params"]["item"]
        for record in records
        if record.get("message", {}).get("method") == "item/completed"
    ]
    commands = [item for item in completed_items if item.get("type") == "commandExecution"]
    compactions = [item for item in completed_items if item.get("type") == "contextCompaction"]

    assert len(commands) == 138
    assert len(compactions) == 4
    assert sum(len(item.get("aggregatedOutput", "")) for item in commands) == 2_035_955
    assert sum("current-interactable-state" in item.get("command", "") for item in commands) == 98
    assert sum("last-observation" in item.get("command", "") for item in commands) == 96
    assert sum("PROGRESS.md" in item.get("command", "") for item in commands) == 64


def test_final_checkpoint_reproduces_score_inventory_and_deployment_gap(run_root):
    checkpoint = json.loads(
        (
            run_root
            / "checkpoints"
            / "cp-000004-tick-1678482"
            / "checkpoint.json"
        ).read_text(encoding="utf-8")
    )
    score = checkpoint["score"]

    assert checkpoint["reason"] == "operator_interrupt"
    assert score["automation_produced_total"] == 18_711
    assert score["automation_produced_items"]["iron-gear-wheel"] == 52
    assert score["manual_crafted_items"]["transport-belt"] == 72
    assert score["manual_crafted_items"]["electric-mining-drill"] == 2
    assert score["entity_counts"]["assembling-machine-1"] == 1
    assert "transport-belt" not in score["entity_counts"]
    assert "electric-mining-drill" not in score["entity_counts"]
    assert not any("inserter" in name for name in score["entity_counts"])
