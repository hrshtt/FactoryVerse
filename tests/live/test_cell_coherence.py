"""Live pytest wrapper for the L0.4 agent+cell coherence harness.

Ledger row: L0.4 (proposed) — agent+cell instance coherence. The harness
itself, its claim, pass criteria, audit-gate answers, and OPEN-QUESTIONS live
in scripts/certification/check_cell_coherence.py (single source of truth);
this wrapper exists so the same invariants can run in a CI-style pytest lane
once a live instance is available.

Skip semantics (anti-vacuity): when no RCON listener is on localhost:27000
(server_0), the test SKIPs at collection with a clear message. It only PROBES
the TCP port to decide — it never logs in, sends commands, or touches game
state while deciding. A skipped run shows as SKIPPED, never as a pass.

Failure semantics: any harness verdict other than PASS fails the test with
the harness's failure list; BLOCKED inside a live run (e.g. interfaces
missing) is a test failure too — if the port answered, the stack claimed to
be up, and a half-up stack must not look green.
"""

from __future__ import annotations

import importlib.util
import os
import socket
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HARNESS = REPO / "scripts" / "certification" / "check_cell_coherence.py"

RCON_HOST = "localhost"
# server_0 (playbook §1: 27000 + N). Overridable so the skip path can be
# exercised deliberately (point at a closed port) and so a runner can target
# another instance. NOTE: this is a LIVE, MUTATING check — when the port is
# open it WILL allocate agents and write snapshots on that instance (it
# cleans up after itself, verified). Do not run it against an instance
# someone is examining forensically.
RCON_PORT = int(os.environ.get("FV_CELL_COHERENCE_RCON_PORT", "27000"))


def _instance_for_port(port: int) -> str:
    if port == 27100:
        return "client"
    if 27000 <= port < 27100:
        return f"server_{port - 27000}"
    return "server_0"


INSTANCE = _instance_for_port(RCON_PORT)


def _rcon_port_open(host: str = RCON_HOST, port: int = RCON_PORT,
                    timeout: float = 1.0) -> bool:
    """TCP probe only — no RCON auth, no commands, no game contact."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# MUTATION GUARD: port detection alone is NOT consent. During this harness's
# own first validation, a plain `pytest -q` found a forensic server's port
# open and ran the full mutating battery against it (2026-06-11 incident,
# evidence in cell-coherence-harness/). Live mutating tests require BOTH an
# open port AND the explicit opt-in below.
_OPTED_IN = os.environ.get("FV_LIVE_TESTS") == "1"
_LIVE = _OPTED_IN and _rcon_port_open()

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not _OPTED_IN,
        reason=(
            "live MUTATING test: set FV_LIVE_TESTS=1 to opt in explicitly "
            "(an open port is not consent — it may be someone's forensic "
            "or in-use instance)"
        ),
    ),
    pytest.mark.skipif(
        _OPTED_IN and not _rcon_port_open(),
        reason=(
            f"no RCON listener on {RCON_HOST}:{RCON_PORT} ({INSTANCE}) — "
            "live cell-coherence check needs a running lab-grid instance "
            "(`uv run fv server start --num 1 --scenario lab-grid`)"
        ),
    ),
]


def _load_harness():
    """Import the harness by path (scripts/ is not a package). Deferred to
    call time so offline collection never imports duckdb/FactoryVerse."""
    spec = importlib.util.spec_from_file_location("check_cell_coherence", HARNESS)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_cell_coherence"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def harness():
    return _load_harness()


def test_cell_coherence_scenario_path(harness, tmp_path_factory):
    """Run the full seven-invariant check over the scenario allocation path
    (lab_grid.create_agent_in_cell), N=2 agents, cells chosen by the
    scenario's own allocation."""
    art = tmp_path_factory.mktemp("cell-coherence")
    verdict = harness.run_check(
        instance=INSTANCE,
        agents=2,
        path="scenario",
        artifacts_dir=str(art),
    )
    assert verdict["status"] == "PASS", (
        f"L0.4 verdict {verdict['status']}: "
        f"blocked_reason={verdict.get('blocked_reason')!r} "
        f"failures={verdict.get('failures')} "
        f"counters={verdict.get('counters')} (artifacts: {art})"
    )
    # Anti-vacuity re-check at the wrapper level: a PASS with no comparison
    # volume is not a pass (audit-gate Q1, independent of the harness's own
    # floors).
    counters = verdict.get("counters") or {}
    assert counters.get("agents_created", 0) >= 2, counters
    assert counters.get("spot_checks", 0) >= 20, counters
    assert counters.get("markers_placed", 0) >= 3, counters


def test_orchestrator_path_is_explicitly_unimplemented(harness):
    """Guard the loud-failure contract: --path orchestrator must return
    BLOCKED with an explanation, not silently run the scenario path (the
    orchestrator path is the one the CELL-1 field run used). When someone
    implements it, this test forces them to flip the wrapper deliberately."""
    verdict = harness.run_check(instance=INSTANCE, agents=2,
                                path="orchestrator")
    assert verdict["status"] == "BLOCKED", verdict
    assert "not implemented" in (verdict.get("blocked_reason") or "").lower(), verdict
