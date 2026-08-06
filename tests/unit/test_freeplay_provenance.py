import asyncio
import json
import subprocess

import pytest

from FactoryVerse.evals.freeplay.provenance import (
    canonical_json_sha256,
    repository_provenance,
    sha256_tree,
)
from FactoryVerse.evals.freeplay.supervisor import (
    FreeplayLaunchError,
    FreeplaySupervisor,
    _freeplay_map_settings,
)


def test_freeplay_map_settings_disable_enemies_and_pin_seed(tmp_path):
    source = tmp_path / "map-gen-settings.json"
    source.write_text(
        json.dumps(
            {
                "seed": None,
                "peaceful_mode": False,
                "autoplace_controls": {
                    "iron-ore": {"frequency": 1, "size": 1, "richness": 1},
                    "enemy-base": {"frequency": 1, "size": 1},
                },
            }
        )
    )

    settings = _freeplay_map_settings(source, 12345)

    assert settings["seed"] == 12345
    assert settings["peaceful_mode"] is True
    assert settings["autoplace_controls"]["enemy-base"] == {
        "frequency": 0,
        "size": 0,
        "richness": 0,
    }
    assert canonical_json_sha256(settings) == canonical_json_sha256(
        json.loads(json.dumps(settings))
    )


def test_tree_hash_changes_with_file_content(tmp_path):
    (tmp_path / "a.txt").write_text("one")
    first = sha256_tree(tmp_path)
    (tmp_path / "a.txt").write_text("two")
    assert sha256_tree(tmp_path) != first


def test_repository_provenance_hashes_untracked_file_contents(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "freeplay@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Freeplay Test"], cwd=tmp_path, check=True
    )
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("tracked\n")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=tmp_path, check=True)

    untracked = tmp_path / "runner.py"
    untracked.write_text("print('one')\n")
    first = repository_provenance(tmp_path)
    untracked.write_text("print('two')\n")
    second = repository_provenance(tmp_path)

    assert first["status_sha256"] == second["status_sha256"]
    assert first["untracked_file_count"] == 1
    assert second["untracked_file_count"] == 1
    assert first["untracked_files_sha256"] != second["untracked_files_sha256"]


def test_supervisor_refuses_repository_drift_before_launch(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    class Store:
        def manifest(self):
            return {
                "harness": "codex-cli/1.0",
                "model": "test-model",
                "repository": {"commit": "a different tree"},
            }

    supervisor = FreeplaySupervisor(
        Store(),
        repo_root=tmp_path,
        harness="codex-cli/1.0",
        model="test-model",
    )

    with pytest.raises(FreeplayLaunchError, match="Repository provenance differs"):
        asyncio.run(supervisor.start())
