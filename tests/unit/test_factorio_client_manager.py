import json

from FactoryVerse.infra.factorio_client_manager import FactorioClientManager


def test_record_checkpoint_preserves_scenario_and_selects_save_for_restart(tmp_path):
    manager = FactorioClientManager(tmp_path)
    manager.state_file.write_text(json.dumps({"scenario": "freeplay"}))
    checkpoint = tmp_path / "checkpoint.zip"
    checkpoint.write_bytes(b"save")

    manager.record_checkpoint(checkpoint)

    assert json.loads(manager.state_file.read_text()) == {
        "scenario": "freeplay",
        "save_file": str(checkpoint.resolve()),
        "new_map": False,
    }
