import json

from FactoryVerse.environment.config import FactoryVerseConfig
from FactoryVerse.infra.docker.factorio_server_manager import FactorioServerManager


def test_freeplay_creates_native_save_and_uses_correct_custom_mount(tmp_path):
    config = FactoryVerseConfig(output_dir=tmp_path / "output")
    manager = FactorioServerManager(work_dir=config.project_root, config=config)

    service = manager._build_service_config(0, "freeplay")

    command = service["command"][0]
    assert service["entrypoint"] == ["/bin/sh", "-c"]
    assert "--create /factorio/saves/factoryverse-initial.zip" in command
    assert "--start-server /factorio/saves/factoryverse-initial.zip" in command
    assert "--map-gen-seed 44340" in command
    assert any(volume.endswith(":/factorio/scenarios") for volume in service["volumes"])


def test_isolated_freeplay_restores_private_mod_list_between_startup_phases(tmp_path):
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
    assert command.count(restore) == 2
    assert f"{manager.mod_path.resolve()}:/opt/factorio/mods" in service["volumes"]
