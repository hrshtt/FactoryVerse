"""Temp-directory tests for read-only campaign/client mod prejoin checks."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from FactoryVerse.cli import cmd_freeplay_eval_prejoin
from FactoryVerse.evals.freeplay.prejoin import (
    compare_campaign_client_mods,
    format_prejoin_mod_compatibility,
)
from FactoryVerse.evals.freeplay.provenance import sha256_tree


def _write_mod_list(path: Path, enabled: list[str]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "mod-list.json").write_text(
        json.dumps(
            {
                "mods": [
                    {"name": name, "enabled": True} for name in enabled
                ]
                + [{"name": "quality", "enabled": False}]
            }
        ),
        encoding="utf-8",
    )


def _write_directory_mod(
    root: Path, name: str, version: str, files: dict[str, str]
) -> Path:
    mod = root / f"{name}_{version}"
    mod.mkdir(parents=True)
    (mod / "info.json").write_text(
        json.dumps({"name": name, "version": version}), encoding="utf-8"
    )
    for relative, content in files.items():
        target = mod / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return mod


def _manifest(**mods: str) -> dict:
    return {"expected_active_mods": {"base": "2.0.76", **mods}}


def test_matching_directory_bundles_are_compatible_and_read_only(tmp_path):
    server = tmp_path / "server"
    client = tmp_path / "client"
    _write_mod_list(server, ["base", "fv_test"])
    _write_mod_list(client, ["base", "fv_test"])
    _write_directory_mod(server, "fv_test", "1.0.0", {"control.lua": "same\n"})
    client_mod = _write_directory_mod(
        client, "fv_test", "1.0.0", {"control.lua": "same\n"}
    )
    before = (client_mod / "control.lua").read_bytes()

    result = compare_campaign_client_mods(
        server_mod_dir=server,
        client_mod_dir=client,
        campaign_manifest=_manifest(fv_test="1.0.0"),
    )

    assert result.compatible is True
    assert result.unverified_builtin_versions == ["base"]
    assert (client_mod / "control.lua").read_bytes() == before
    assert result.to_dict()["client_files_modified"] is False


def test_same_name_and_version_reports_exact_content_difference(tmp_path):
    server = tmp_path / "server"
    client = tmp_path / "client"
    _write_mod_list(server, ["base", "fv_test"])
    _write_mod_list(client, ["base", "fv_test"])
    _write_directory_mod(
        server,
        "fv_test",
        "1.0.0",
        {"connections/init.lua": "server\n", "server-only.lua": "x\n"},
    )
    _write_directory_mod(
        client,
        "fv_test",
        "1.0.0",
        {"connections/init.lua": "client\n", "client-only.lua": "y\n"},
    )

    result = compare_campaign_client_mods(
        server_mod_dir=server,
        client_mod_dir=client,
        campaign_manifest=_manifest(fv_test="1.0.0"),
    )

    assert result.compatible is False
    assert result.content_mismatches == [
        {
            "name": "fv_test",
            "version": "1.0.0",
            "server_artifact": str(server / "fv_test_1.0.0"),
            "client_artifact": str(client / "fv_test_1.0.0"),
            "server_sha256": result.content_mismatches[0]["server_sha256"],
            "client_sha256": result.content_mismatches[0]["client_sha256"],
            "missing_client_files": ["server-only.lua"],
            "extra_client_files": ["client-only.lua"],
            "changed_files": ["connections/init.lua"],
            "changed_file_sha256": {
                "connections/init.lua": {
                    "server": result.content_mismatches[0][
                        "changed_file_sha256"
                    ]["connections/init.lua"]["server"],
                    "client": result.content_mismatches[0][
                        "changed_file_sha256"
                    ]["connections/init.lua"]["client"],
                }
            },
        }
    ]
    rendered = format_prejoin_mod_compatibility(result)
    assert "connections/init.lua" in rendered
    assert "restart Factorio before connecting" in rendered


def test_missing_extra_and_version_mismatches_are_separate(tmp_path):
    server = tmp_path / "server"
    client = tmp_path / "client"
    _write_mod_list(server, ["base", "alpha", "beta"])
    _write_mod_list(client, ["base", "beta", "extra"])
    _write_directory_mod(server, "alpha", "1.0.0", {"control.lua": "a"})
    _write_directory_mod(server, "beta", "2.0.0", {"control.lua": "b"})
    _write_directory_mod(client, "beta", "1.0.0", {"control.lua": "b"})
    _write_directory_mod(client, "extra", "1.0.0", {"control.lua": "e"})

    result = compare_campaign_client_mods(
        server_mod_dir=server,
        client_mod_dir=client,
        campaign_manifest=_manifest(alpha="1.0.0", beta="2.0.0"),
    )

    assert result.missing_mods == ["alpha"]
    assert result.extra_mods == ["extra"]
    assert result.version_mismatches == [
        {
            "name": "beta",
            "expected_version": "2.0.0",
            "installed_versions": ["1.0.0"],
            "installed_artifacts": [str(client / "beta_1.0.0")],
        }
    ]


def test_zip_and_directory_with_same_logical_files_match(tmp_path):
    server = tmp_path / "server"
    client = tmp_path / "client"
    _write_mod_list(server, ["base", "fv_test"])
    _write_mod_list(client, ["base", "fv_test"])
    server_mod = _write_directory_mod(
        server, "fv_test", "1.0.0", {"control.lua": "same\n"}
    )
    archive_path = client / "fv_test_1.0.0.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for path in sorted(server_mod.rglob("*")):
            if path.is_file():
                archive.write(path, f"fv_test_1.0.0/{path.relative_to(server_mod)}")

    result = compare_campaign_client_mods(
        server_mod_dir=server,
        client_mod_dir=client,
        campaign_manifest=_manifest(fv_test="1.0.0"),
    )

    assert result.compatible is True


def test_campaign_manifest_hash_detects_mutated_server_bundle(tmp_path):
    server = tmp_path / "server"
    client = tmp_path / "client"
    _write_mod_list(server, ["base", "fv_embodied_agent"])
    _write_mod_list(client, ["base", "fv_embodied_agent"])
    server_mod = _write_directory_mod(
        server, "fv_embodied_agent", "1.0.0", {"control.lua": "original\n"}
    )
    client_mod = _write_directory_mod(
        client, "fv_embodied_agent", "1.0.0", {"control.lua": "changed\n"}
    )
    immutable_hash = sha256_tree(server_mod)
    (server_mod / "control.lua").write_text("changed\n", encoding="utf-8")
    assert sha256_tree(server_mod) == sha256_tree(client_mod)
    manifest = _manifest(fv_embodied_agent="1.0.0")
    manifest["hashes"] = {"embodied_mod": immutable_hash}

    result = compare_campaign_client_mods(
        server_mod_dir=server,
        client_mod_dir=client,
        campaign_manifest=manifest,
    )

    assert result.content_mismatches == []
    assert result.server_bundle_errors == [
        "campaign server mod bytes differ from immutable manifest: fv_embodied_agent"
    ]


def test_cli_prejoin_reports_mismatch_and_exits_without_syncing(
    tmp_path, monkeypatch, capsys
):
    server = tmp_path / "server"
    client = tmp_path / "client"
    _write_mod_list(server, ["base", "fv_test"])
    _write_mod_list(client, ["base", "fv_test"])
    _write_directory_mod(server, "fv_test", "1.0.0", {"control.lua": "server"})
    client_mod = _write_directory_mod(
        client, "fv_test", "1.0.0", {"control.lua": "client"}
    )
    store = SimpleNamespace(
        paths=SimpleNamespace(server_mods=server),
        manifest=lambda: _manifest(fv_test="1.0.0"),
    )
    monkeypatch.setattr(
        "FactoryVerse.cli._freeplay_campaign_store", lambda campaign: store
    )
    args = SimpleNamespace(
        campaign="campaign-1", client_mod_dir=str(client), json=False
    )
    before = (client_mod / "control.lua").read_bytes()

    with pytest.raises(SystemExit) as exc_info:
        cmd_freeplay_eval_prejoin(args)

    assert exc_info.value.code == 1
    assert "Content mismatch: fv_test 1.0.0" in capsys.readouterr().out
    assert (client_mod / "control.lua").read_bytes() == before
