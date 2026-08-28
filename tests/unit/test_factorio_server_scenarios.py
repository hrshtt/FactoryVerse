"""A boot is a scenario start; there is no cached-world third case.

SCENARIO_BOOT_CONTRACT Stage 2. Before this, ``scenario == "freeplay"`` was
special-cased into ``--create`` + ``--start-server``, which baked *base*
freeplay into a save the volume then served forever, so later changes to
seed or enemy settings were silently ignored. Every scenario now boots the
same way, from the mounted repo scenarios directory.
"""

import json

from FactoryVerse.environment.config import FactoryVerseConfig
from FactoryVerse.infra.docker.factorio_server_manager import FactorioServerManager


def test_freeplay_boots_as_a_scenario_start_not_a_cached_save(tmp_path):
    config = FactoryVerseConfig(output_dir=tmp_path / "output")
    manager = FactorioServerManager(work_dir=config.project_root, config=config)

    service = manager._build_service_config(0, "freeplay")

    command = service["command"][0] if service.get("entrypoint") else service["command"]
    text = command if isinstance(command, str) else " ".join(command)
    assert "--start-server-load-scenario freeplay" in text
    assert "--create" not in text
    assert "factoryverse-initial" not in text
    assert "--map-gen-seed 44340" in text
    assert "--map-gen-settings /factorio/config/map-gen-settings.json" in text
    assert any(volume.endswith(":/factorio/scenarios") for volume in service["volumes"])


def test_every_scenario_uses_the_same_boot_shape(tmp_path):
    config = FactoryVerseConfig(output_dir=tmp_path / "output")
    manager = FactorioServerManager(work_dir=config.project_root, config=config)
    shapes = set()
    for scenario in ("freeplay", "lab-grid", "test-ground"):
        service = manager._build_service_config(0, scenario)
        cmd = service["command"]
        text = cmd if isinstance(cmd, str) else " ".join(cmd)
        assert f"--start-server-load-scenario {scenario}" in text
        shapes.add(text.replace(scenario, "<scenario>"))
    assert len(shapes) == 1, "scenarios must not boot differently from one another"


def test_resume_is_an_explicit_save_and_never_restarts_automatically(tmp_path):
    config = FactoryVerseConfig(output_dir=tmp_path / "output")
    manager = FactorioServerManager(work_dir=config.project_root, config=config)

    fresh = manager._build_service_config(0, "freeplay")
    resumed = manager._build_service_config(0, "freeplay", save="checkpoint-3")

    assert "--start-server /factorio/saves/checkpoint-3.zip" in " ".join(
        resumed["command"] if isinstance(resumed["command"], list) else [resumed["command"]]
    )
    # A restarted container would come back at tick 0 on a freshly generated
    # world while looking like the old one. Lifecycle is owned explicitly.
    assert fresh["restart"] == "no"
    assert resumed["restart"] == "no"
    manager.effective_max_agents = 1
    assert manager._build_udp_forwarder_config(0)["restart"] == "no"


def test_isolated_freeplay_restores_private_mod_list_once(tmp_path):
    config = FactoryVerseConfig(output_dir=tmp_path / "output")
    manager = FactorioServerManager(work_dir=config.project_root, config=config)
    manager.mod_path = tmp_path / "campaign" / "server-mods"
    manager.config_dir = tmp_path / "campaign" / "server-config"
    manager.config_dir.mkdir(parents=True)
    manager.isolated_mods = True

    manager.prepare_mods("freeplay")
    service = manager._build_service_config(0, "freeplay")

    mod_list = json.loads((manager.mod_path / "mod-list.json").read_text())
    assert mod_list == json.loads(
        (manager.config_dir / "server-mod-list.json").read_text()
    )
    assert {entry["name"] for entry in mod_list["mods"] if entry["enabled"]} == {
        "base",
        "fv_embodied_agent",
        "fv_snapshot",
        "fv_placement_hints",
    }
    assert service["restart"] == "no"
    assert service["entrypoint"] == ["/bin/sh", "-c"]
    command = service["command"][0]
    restore = (
        "cp /factorio/config/server-mod-list.json "
        "/opt/factorio/mods/mod-list.json"
    )
    # One startup phase now, so the private mod list is restored exactly once.
    assert command.count(restore) == 1
    assert command.startswith(restore)
    assert f"{manager.mod_path.resolve()}:/opt/factorio/mods" in service["volumes"]
