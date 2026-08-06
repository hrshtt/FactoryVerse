"""DIGEST-1 regression: the power digest must render THROUGH the runtime
adapters the orchestrator actually receives — not only against tier4 directly.

Found live 2026-07-12 (terra-pro attempt 5): tier6's _RuntimeAdapter did not
expose `remote_view`, so `getattr(runtime, 'remote_view', None)` was None and
the digest silently omitted itself on every turn of the run, while the
sampler data existed on disk. Same adapter-missing-attribute class as the
PROMPT-3 `scenario` skip.
"""

from types import SimpleNamespace

from FactoryVerse.environment.tiers.tier6_interaction import _RuntimeAdapter
from FactoryVerse.infra.llm.orchestrator import AgentOrchestrator
from FactoryVerse.game.agent.remote_view import (
    PowerNetworkCensus,
    PowerNetworksReport,
)


def _report_one_net() -> PowerNetworksReport:
    net = PowerNetworkCensus(
        network_id=1,
        anchor_pole_name="small-electric-pole",
        anchor_pole_position={"x": 971.5, "y": 971.5},
        pole_count=1,
        member_count=3,
        production_w=77500.0,
        consumption_w=77500.0,
        storage_j=0.0,
        headroom_ratio=1.0,
        production_by_prototype={"electric-energy-interface": 77500.0},
        consumption_by_prototype={"assembling-machine-1": 77500.0},
        low_power_count=0,
        no_power_count=2,
        sample_tick=600,
    )
    return PowerNetworksReport(networks=[net], sample_tick=600, freshness_note="")


class _FakeRemoteView:
    is_loaded = True

    def get_power_networks(self):
        return _report_one_net()


def _orchestrator_with(runtime) -> AgentOrchestrator:
    orch = AgentOrchestrator.__new__(AgentOrchestrator)
    orch.runtime = runtime
    return orch


def test_digest_renders_through_tier6_runtime_adapter():
    tier4 = SimpleNamespace(remote_view=_FakeRemoteView())
    adapter = _RuntimeAdapter(tier3=None, tier4=tier4)
    # the adapter must pass remote_view through (the DIGEST-1 gap)
    assert adapter.remote_view is tier4.remote_view
    line = _orchestrator_with(adapter)._render_power_digest_line()
    assert line is not None, "digest omitted through the eval-path adapter"
    assert line.startswith("power: 1 nets")
    assert "77.5kW/77.5kW" in line
    assert "2 no_power" in line


def test_digest_omits_and_warns_once_without_tier4(caplog):
    adapter = _RuntimeAdapter(tier3=None, tier4=None)
    orch = _orchestrator_with(adapter)
    with caplog.at_level("WARNING"):
        assert orch._render_power_digest_line() is None
        assert orch._render_power_digest_line() is None
    warnings = [r for r in caplog.records if "power digest disabled" in r.message]
    assert len(warnings) == 1, "omission must be loud exactly once"


def test_digest_renders_orphan_term():
    # DIGEST-2: dark machines on NO network must appear as their own term.
    report = _report_one_net()
    report.unattributed_no_power = 5
    rv = _FakeRemoteView()
    rv.get_power_networks = lambda: report
    tier4 = SimpleNamespace(remote_view=rv)
    line = _orchestrator_with(_RuntimeAdapter(tier3=None, tier4=tier4))._render_power_digest_line()
    assert line.endswith("| 5 unpowered (no net)"), line


def test_digest_orphan_term_with_zero_networks():
    # Early game: machines placed, no poles at all — the digest must still shout.
    report = PowerNetworksReport(
        networks=[], sample_tick=600, freshness_note="", unattributed_no_power=3
    )
    rv = _FakeRemoteView()
    rv.get_power_networks = lambda: report
    tier4 = SimpleNamespace(remote_view=rv)
    line = _orchestrator_with(_RuntimeAdapter(tier3=None, tier4=tier4))._render_power_digest_line()
    assert line == "power: no networks | 3 unpowered (no net)"


def test_session_adapter_exposes_remote_view():
    from FactoryVerse.infra.services.agent_service import SessionRuntimeAdapter

    rv = _FakeRemoteView()
    session = SimpleNamespace(_env=SimpleNamespace(tier4=SimpleNamespace(remote_view=rv)))
    adapter = SessionRuntimeAdapter.__new__(SessionRuntimeAdapter)
    adapter._session = session
    assert adapter.remote_view is rv
