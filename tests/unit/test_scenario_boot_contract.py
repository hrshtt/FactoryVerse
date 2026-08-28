"""SCENARIO_BOOT_CONTRACT_DEFERRED.md — the offline half of its owed checks.

Each test names the stage it certifies. The live half (which script actually
loaded, whether the world has enemies, whether a joining human has a body)
lives in tests/live/test_scenario_boot_contract.py.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from FactoryVerse.environment import boot_probe
from FactoryVerse.environment.config import FactoryVerseConfig
from FactoryVerse.environment.tiers.tier2_settings import _settings_match
from FactoryVerse.infra import factorio_client_setup

REPO = Path(__file__).resolve().parents[2]
SCENARIOS = REPO / "src" / "factorio" / "scenarios"
CONFIG = REPO / "src" / "factorio" / "config"
MOD = REPO / "src" / "fv_embodied_agent"


# ---------------------------------------------------------------------------
# Stage 1 — one resolver, repo only
# ---------------------------------------------------------------------------


@pytest.fixture
def scenario_tree(tmp_path, monkeypatch):
    repo = tmp_path / "scenarios"
    (repo / "alpha").mkdir(parents=True)
    (repo / "alpha" / "control.lua").write_text("-- alpha")
    (repo / "no-control").mkdir()
    config = FactoryVerseConfig(output_dir=tmp_path / "out")
    monkeypatch.setattr(FactoryVerseConfig, "scenarios_dir", property(lambda self: repo))

    # The host's Factorio install must never be consulted for a boot decision.
    def _forbidden(*_a, **_k):
        raise AssertionError("scenario resolution consulted the host Factorio install")

    monkeypatch.setattr("FactoryVerse.environment.config._detect_factorio_install_dir", _forbidden)
    monkeypatch.setattr("FactoryVerse.environment.config._detect_factorio_dir", _forbidden)
    return config, repo


def test_resolver_accepts_only_repo_scenarios_with_control_lua(scenario_tree):
    config, repo = scenario_tree
    assert config.resolve_scenario("alpha") == repo / "alpha"
    assert config.validate_scenario("alpha")
    assert config.is_repo_scenario("alpha")
    assert config.resolve_scenario("no-control") is None
    assert not config.validate_scenario("no-control")
    # Names that exist only on the developer's machine do not resolve.
    assert not config.validate_scenario("freeplay")
    assert config.list_scenarios() == ["alpha"]
    assert config.list_scenarios(include_local=True) == ["alpha"]


def test_engine_scenarios_pass_through_by_slash(scenario_tree):
    config, _ = scenario_tree
    assert config.is_engine_scenario("base/freeplay")
    assert config.validate_scenario("base/freeplay")
    assert config.resolve_scenario("base/freeplay") is None
    assert not config.is_repo_scenario("base/freeplay")


def test_setup_client_fails_on_a_missing_project_scenario(tmp_path, monkeypatch):
    client_mods = tmp_path / "client" / "mods"
    client_scenarios = tmp_path / "client" / "scenarios"
    client_mods.mkdir(parents=True)
    client_scenarios.mkdir(parents=True)
    # A stale copy in the client's directory must not rescue the launch.
    (client_scenarios / "ghost-town").mkdir()
    (client_scenarios / "ghost-town" / "control.lua").write_text("-- stale")
    monkeypatch.setattr(factorio_client_setup, "_get_mod_path", lambda: client_mods)
    monkeypatch.setattr(factorio_client_setup, "_get_scenario_path", lambda: client_scenarios)
    project_scenarios = tmp_path / "project" / "scenarios"
    project_scenarios.mkdir(parents=True)

    with pytest.raises(FileNotFoundError, match="ghost-town"):
        factorio_client_setup.setup_client(
            REPO, scenario="ghost-town", project_scenarios_dir=project_scenarios
        )


def test_setup_client_syncs_a_repo_scenario_into_the_client(tmp_path, monkeypatch):
    client_mods = tmp_path / "client" / "mods"
    client_scenarios = tmp_path / "client" / "scenarios"
    client_mods.mkdir(parents=True)
    client_scenarios.mkdir(parents=True)
    monkeypatch.setattr(factorio_client_setup, "_get_mod_path", lambda: client_mods)
    monkeypatch.setattr(factorio_client_setup, "_get_scenario_path", lambda: client_scenarios)
    project_scenarios = tmp_path / "project" / "scenarios"
    (project_scenarios / "alpha").mkdir(parents=True)
    (project_scenarios / "alpha" / "control.lua").write_text("-- alpha v1")

    factorio_client_setup.setup_client(
        REPO, scenario="alpha", project_scenarios_dir=project_scenarios
    )
    assert (client_scenarios / "alpha" / "control.lua").read_text() == "-- alpha v1"


# ---------------------------------------------------------------------------
# Stage 2 — the freeplay scenario is in the repo and is a thin world-shaper
# ---------------------------------------------------------------------------


def test_freeplay_scenario_exists_and_publishes_its_contract():
    control = (SCENARIOS / "freeplay" / "control.lua").read_text()
    assert 'remote.add_interface("factoryverse_freeplay"' in control
    assert "get_contract" in control
    assert "CONTRACT_VERSION" in control
    assert "always_day = true" in control
    # Replaces base freeplay: none of its machinery is pulled in.
    assert "__base__/script/freeplay" not in control
    assert "crash" not in control.lower().replace("crash site, no", "")
    assert "set_win_ending_info" not in control


def test_no_repo_scenario_sets_a_player_controller():
    """The observer policy is the mod's (Stage 4). A scenario that sets a
    controller is a second, divergent implementation of the same policy."""
    offenders = []
    for control in SCENARIOS.glob("*/control.lua"):
        if "set_controller" in control.read_text():
            offenders.append(control.parent.name)
    assert offenders == []


# ---------------------------------------------------------------------------
# Stage 3 — the settings the world is generated from
# ---------------------------------------------------------------------------


def test_map_gen_settings_carry_the_no_enemies_recipe():
    settings = json.loads((CONFIG / "map-gen-settings.json").read_text())
    assert settings["peaceful_mode"] is True
    assert settings["no_enemies_mode"] is True
    assert settings["autoplace_controls"]["enemy-base"] == {
        "frequency": 0, "size": 0, "richness": 0,
    }


def test_map_settings_do_not_arm_expansion_or_evolution():
    settings = json.loads((CONFIG / "map-settings.json").read_text())
    assert settings["enemy_expansion"]["enabled"] is False
    assert settings["enemy_evolution"]["enabled"] is False


def test_tier2_requested_settings_match_the_file():
    """Tier 2 compares its request against the mounted file; the request now
    carries the full recipe and dict values compare as subsets."""
    from FactoryVerse.environment.config import SettingsConfig
    from FactoryVerse.environment.tiers.tier2_settings import Tier2Settings

    from types import SimpleNamespace

    tier = Tier2Settings.__new__(Tier2Settings)
    tier._env = SimpleNamespace(
        config=SimpleNamespace(tier2=SettingsConfig(scenario="freeplay", peaceful=True))
    )
    requested = tier._build_map_gen_settings()
    mounted = json.loads((CONFIG / "map-gen-settings.json").read_text())
    for key, value in requested.items():
        assert _settings_match(mounted.get(key), value), key
    # And a world that still has enemy autoplace is a mismatch.
    mounted["autoplace_controls"]["enemy-base"] = {"frequency": 1, "size": 1}
    assert not _settings_match(mounted["autoplace_controls"], requested["autoplace_controls"])


def test_prompt_no_longer_promises_only_that_enemies_do_not_attack():
    template = (REPO / "docs" / "system-prompt" / "factoryverse-system-prompt-v3-template.md").read_text()
    assert "No enemies attack" not in template
    assert "No enemies" in template


# ---------------------------------------------------------------------------
# Stage 4 — the observer policy is the mod's, behind a setting
# ---------------------------------------------------------------------------


def test_observer_setting_is_declared_default_on():
    settings = (MOD / "settings.lua").read_text()
    block = settings[settings.index('name = "fv-observer-spectator"'):]
    assert 'setting_type = "runtime-global"' in block[:400]
    assert "default_value = true" in block[:400]


def test_spectator_module_is_wired_and_uses_the_spectator_controller():
    control = (MOD / "control.lua").read_text()
    assert 'local Spectator = require("game_state.Spectator")' in control
    assert re.search(r"local modules = \{[^}]*Spectator[^}]*\}", control)
    assert "DISABLED: Spectator" not in control
    spectator = (MOD / "game_state" / "Spectator.lua").read_text()
    assert "defines.controllers.spectator" in spectator
    assert "defines.controllers.god" not in spectator
    assert 'settings.global["fv-observer-spectator"]' in spectator or "settings.global[SETTING]" in spectator
    assert "player.connected" in spectator
    assert "character.destroy()" in spectator


@pytest.mark.skipif(shutil.which("luac") is None, reason="luac not on PATH")
def test_touched_lua_parses():
    for path in (
        MOD / "control.lua",
        MOD / "game_state" / "Spectator.lua",
        MOD / "settings.lua",
        SCENARIOS / "freeplay" / "control.lua",
        SCENARIOS / "lab-grid" / "control.lua",
    ):
        subprocess.run(["luac", "-p", str(path)], check=True)


# ---------------------------------------------------------------------------
# Stage 0 / 5 — the probe and its gate
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("luac") is None, reason="luac not on PATH")
def test_probe_lua_is_syntactically_valid(tmp_path):
    body = tmp_path / "probe.lua"
    body.write_text("local function probe()\n" + boot_probe._PROBE_LUA + "\nend\n")
    subprocess.run(["luac", "-p", str(body)], check=True)


def _probe(**overrides):
    base = {
        "interfaces": ["agent", "factoryverse_freeplay", "map", "spectator"],
        "contract": {"name": "freeplay", "version": 2},
        "world": {
            "seed": 44340, "peaceful_mode": True, "no_enemies_mode": True,
            "enemy_base": {"frequency": 0, "size": 0, "richness": 0},
        },
        "enemies": {"total": 0, "spawners": 0, "worms": 0, "units": 0},
        "observer": {"enabled": True},
        "ingestion": {"available": True, "charted_chunks": 10, "tracked_chunks": 10},
    }
    base.update(overrides)
    base["loaded_scenario"] = boot_probe.loaded_scenario(base)
    return base


def test_loaded_scenario_is_named_from_the_contract_interface():
    assert boot_probe.loaded_scenario({"interfaces": ["factoryverse_freeplay"]}) == "freeplay"
    assert boot_probe.loaded_scenario({"interfaces": ["freeplay"]}) == "base/freeplay"
    assert boot_probe.loaded_scenario({"interfaces": ["lab_grid"]}) == "lab-grid"
    assert boot_probe.loaded_scenario({"interfaces": ["agent"]}) is None


def test_boot_errors_name_each_way_a_boot_can_be_wrong():
    assert boot_probe.boot_errors(_probe(), expected_scenario="freeplay") == []
    wrong = boot_probe.boot_errors(
        _probe(interfaces=["freeplay", "spectator"]), expected_scenario="freeplay"
    )
    assert any("base/freeplay" in e for e in wrong)
    enemies = boot_probe.boot_errors(
        _probe(enemies={"total": 37, "spawners": 11, "worms": 8, "units": 18}),
        expected_scenario="freeplay",
    )
    assert any("enemy entities exist" in e for e in enemies)
    off = boot_probe.boot_errors(_probe(observer={"enabled": False}), expected_scenario="freeplay")
    assert any("disabled" in e for e in off)
    unreadable = boot_probe.boot_errors(_probe(observer=None), expected_scenario="freeplay")
    assert any("unreadable" in e for e in unreadable)


def test_probe_boot_adds_the_loaded_scenario():
    class _Runner:
        def run_lua(self, code, *, safe=True, silent=True):
            return {"interfaces": ["lab_grid"], "world": {}, "enemies": {}, "ingestion": {}}

    assert boot_probe.probe_boot(_Runner())["loaded_scenario"] == "lab-grid"


def test_campaign_manifest_hashes_the_scenario(tmp_path):
    from FactoryVerse.evals.freeplay.supervisor import build_campaign_manifest

    config = FactoryVerseConfig(output_dir=tmp_path / "out")
    if not (config.data_dump_path.exists() and config.prototype_api_path.exists()):
        pytest.skip("prototype dump not present; manifest cannot be built offline")
    manifest = build_campaign_manifest(
        repo_root=REPO, infra_config=config, seed=1, agent_id="a", harness="fv", model="m"
    )
    assert "scenario" in manifest["hashes"]
    assert len(manifest["hashes"]["scenario"]) == 64
