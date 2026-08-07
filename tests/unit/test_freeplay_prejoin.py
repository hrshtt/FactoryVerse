"""Temp-directory tests for read-only campaign/client mod prejoin checks."""

from __future__ import annotations

import json
import stat
import warnings
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from FactoryVerse.cli import cmd_freeplay_eval_prejoin
from FactoryVerse.evals.freeplay.prejoin import (
    PrejoinModCompatibility,
    compare_campaign_client_mods,
    format_prejoin_mod_compatibility,
)
from FactoryVerse.evals.freeplay.provenance import canonical_json_sha256, sha256_tree


def _write_mod_list(path: Path, enabled: list[str]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "mod-list.json").write_text(
        json.dumps(
            {
                "mods": [{"name": name, "enabled": True} for name in enabled]
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


def _manifest(server: Path, **mods: str) -> dict:
    mod_list = json.loads((server / "mod-list.json").read_text(encoding="utf-8"))
    hashes = {"server_mod_list": canonical_json_sha256(mod_list)}
    hash_keys = {
        "fv_embodied_agent": "embodied_mod",
        "fv_snapshot": "snapshot_mod",
        "fv_placement_hints": "placement_hints_mod",
    }
    for name, version in mods.items():
        path = server / f"{name}_{version}"
        if name in hash_keys and path.is_dir():
            hashes[hash_keys[name]] = sha256_tree(path)
    return {
        "expected_active_mods": {"base": "2.0.76", **mods},
        "hashes": hashes,
    }


def _matching_bundle(tmp_path: Path) -> tuple[Path, Path, dict, Path]:
    server = tmp_path / "server"
    client = tmp_path / "client"
    _write_mod_list(server, ["base", "fv_embodied_agent"])
    _write_mod_list(client, ["base", "fv_embodied_agent"])
    _write_directory_mod(
        server, "fv_embodied_agent", "1.0.0", {"control.lua": "same\n"}
    )
    client_mod = _write_directory_mod(
        client, "fv_embodied_agent", "1.0.0", {"control.lua": "same\n"}
    )
    return (
        server,
        client,
        _manifest(server, fv_embodied_agent="1.0.0"),
        client_mod,
    )


def test_matching_on_disk_bundles_are_indeterminate_and_read_only(tmp_path):
    server = tmp_path / "server"
    client = tmp_path / "client"
    _write_mod_list(server, ["base", "fv_embodied_agent"])
    _write_mod_list(client, ["base", "fv_embodied_agent"])
    _write_directory_mod(
        server, "fv_embodied_agent", "1.0.0", {"control.lua": "same\n"}
    )
    client_mod = _write_directory_mod(
        client, "fv_embodied_agent", "1.0.0", {"control.lua": "same\n"}
    )
    before = (client_mod / "control.lua").read_bytes()

    result = compare_campaign_client_mods(
        server_mod_dir=server,
        client_mod_dir=client,
        campaign_manifest=_manifest(server, fv_embodied_agent="1.0.0"),
    )

    assert result.status.value == "indeterminate"
    assert result.compatible is False
    assert result.unverified_builtin_versions == ["base"]
    assert (client_mod / "control.lua").read_bytes() == before
    assert result.to_dict()["client_files_modified"] is False
    assert result.to_dict()["loaded_client_bytes_verified"] is False
    assert result.to_dict()["status"] == "indeterminate"
    rendered = format_prejoin_mod_compatibility(result)
    assert "On-disk custom mod artifacts match" in rendered
    assert "full join readiness is indeterminate" in rendered
    assert "Compatible client/server mod bundles" not in rendered


def test_three_state_result_only_matches_with_all_evidence_verified():
    result = PrejoinModCompatibility(
        server_mod_dir="/server",
        client_mod_dir="/client",
        loaded_client_bytes_verified=True,
    )
    assert result.status.value == "match"
    assert result.compatible is True

    result.loaded_client_bytes_verified = False
    assert result.status.value == "indeterminate"

    result.client_bundle_errors.append("bad bundle")
    assert result.status.value == "mismatch"


def test_same_name_and_version_reports_exact_content_difference(tmp_path):
    server = tmp_path / "server"
    client = tmp_path / "client"
    _write_mod_list(server, ["base", "fv_embodied_agent"])
    _write_mod_list(client, ["base", "fv_embodied_agent"])
    _write_directory_mod(
        server,
        "fv_embodied_agent",
        "1.0.0",
        {"connections/init.lua": "server\n", "server-only.lua": "x\n"},
    )
    _write_directory_mod(
        client,
        "fv_embodied_agent",
        "1.0.0",
        {"connections/init.lua": "client\n", "client-only.lua": "y\n"},
    )

    result = compare_campaign_client_mods(
        server_mod_dir=server,
        client_mod_dir=client,
        campaign_manifest=_manifest(server, fv_embodied_agent="1.0.0"),
    )

    assert result.compatible is False
    assert result.content_mismatches == [
        {
            "name": "fv_embodied_agent",
            "version": "1.0.0",
            "server_artifact": str(server / "fv_embodied_agent_1.0.0"),
            "client_artifact": str(client / "fv_embodied_agent_1.0.0"),
            "server_sha256": result.content_mismatches[0]["server_sha256"],
            "client_sha256": result.content_mismatches[0]["client_sha256"],
            "missing_client_files": ["server-only.lua"],
            "extra_client_files": ["client-only.lua"],
            "changed_files": ["connections/init.lua"],
            "changed_file_sha256": {
                "connections/init.lua": {
                    "server": result.content_mismatches[0]["changed_file_sha256"][
                        "connections/init.lua"
                    ]["server"],
                    "client": result.content_mismatches[0]["changed_file_sha256"][
                        "connections/init.lua"
                    ]["client"],
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
    _write_mod_list(server, ["base", "fv_embodied_agent", "fv_snapshot"])
    _write_mod_list(client, ["base", "fv_snapshot", "extra"])
    _write_directory_mod(server, "fv_embodied_agent", "1.0.0", {"control.lua": "a"})
    _write_directory_mod(server, "fv_snapshot", "2.0.0", {"control.lua": "b"})
    _write_directory_mod(client, "fv_snapshot", "1.0.0", {"control.lua": "b"})
    _write_directory_mod(client, "extra", "1.0.0", {"control.lua": "e"})

    result = compare_campaign_client_mods(
        server_mod_dir=server,
        client_mod_dir=client,
        campaign_manifest=_manifest(
            server, fv_embodied_agent="1.0.0", fv_snapshot="2.0.0"
        ),
    )

    assert result.missing_mods == ["fv_embodied_agent"]
    assert result.extra_mods == ["extra"]
    assert result.version_mismatches == [
        {
            "name": "fv_snapshot",
            "expected_version": "2.0.0",
            "installed_versions": ["1.0.0"],
            "installed_artifacts": [str(client / "fv_snapshot_1.0.0")],
        }
    ]


def test_zip_and_directory_with_same_logical_files_match(tmp_path):
    server = tmp_path / "server"
    client = tmp_path / "client"
    _write_mod_list(server, ["base", "fv_embodied_agent"])
    _write_mod_list(client, ["base", "fv_embodied_agent"])
    server_mod = _write_directory_mod(
        server, "fv_embodied_agent", "1.0.0", {"control.lua": "same\n"}
    )
    archive_path = client / "fv_embodied_agent_1.0.0.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for path in sorted(server_mod.rglob("*")):
            if path.is_file():
                archive.write(
                    path, f"fv_embodied_agent_1.0.0/{path.relative_to(server_mod)}"
                )

    result = compare_campaign_client_mods(
        server_mod_dir=server,
        client_mod_dir=client,
        campaign_manifest=_manifest(server, fv_embodied_agent="1.0.0"),
    )

    assert result.status.value == "indeterminate"


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
    manifest = _manifest(server, fv_embodied_agent="1.0.0")
    manifest["hashes"]["embodied_mod"] = immutable_hash

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
    _write_mod_list(server, ["base", "fv_embodied_agent"])
    _write_mod_list(client, ["base", "fv_embodied_agent"])
    _write_directory_mod(
        server, "fv_embodied_agent", "1.0.0", {"control.lua": "server"}
    )
    client_mod = _write_directory_mod(
        client, "fv_embodied_agent", "1.0.0", {"control.lua": "client"}
    )
    store = SimpleNamespace(
        paths=SimpleNamespace(server_mods=server),
        manifest=lambda: _manifest(server, fv_embodied_agent="1.0.0"),
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
    assert "Content mismatch: fv_embodied_agent 1.0.0" in capsys.readouterr().out
    assert (client_mod / "control.lua").read_bytes() == before


@pytest.mark.parametrize(
    "mods",
    [
        [
            {"name": "base", "enabled": True},
            {"name": "base", "enabled": False},
        ],
        [{"name": "base", "enabled": "yes"}],
        [{"enabled": True}],
        ["base"],
    ],
    ids=["duplicate-name", "non-boolean-enabled", "missing-name", "non-object"],
)
@pytest.mark.parametrize("side", ["server", "client"])
def test_malformed_mod_list_entries_are_bundle_errors(tmp_path, mods, side):
    server, client, manifest, client_mod = _matching_bundle(tmp_path)
    target = server if side == "server" else client
    (target / "mod-list.json").write_text(json.dumps({"mods": mods}), encoding="utf-8")
    before = (client_mod / "control.lua").read_bytes()

    result = compare_campaign_client_mods(
        server_mod_dir=server,
        client_mod_dir=client,
        campaign_manifest=manifest,
    )

    assert result.status.value == "mismatch"
    assert getattr(result, f"{side}_bundle_errors")
    assert (client_mod / "control.lua").read_bytes() == before


@pytest.mark.parametrize("kind", ["directory", "zip"])
def test_malformed_artifact_shaped_entries_are_bundle_errors(tmp_path, kind):
    server, client, manifest, client_mod = _matching_bundle(tmp_path)
    if kind == "directory":
        malformed = client / "broken_1.0.0"
        malformed.mkdir()
        (malformed / "info.json").write_text("{", encoding="utf-8")
    else:
        (client / "broken_1.0.0.zip").write_bytes(b"not a zip")
    before = (client_mod / "control.lua").read_bytes()

    result = compare_campaign_client_mods(
        server_mod_dir=server,
        client_mod_dir=client,
        campaign_manifest=manifest,
    )

    assert result.status.value == "mismatch"
    assert result.client_bundle_errors
    assert (client_mod / "control.lua").read_bytes() == before


def test_zip_with_multiple_info_roots_is_rejected(tmp_path):
    server, client, manifest, _ = _matching_bundle(tmp_path)
    archive_path = client / "ambiguous_1.0.0.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("one/info.json", '{"name":"one","version":"1"}')
        archive.writestr("two/info.json", '{"name":"two","version":"1"}')

    result = compare_campaign_client_mods(
        server_mod_dir=server,
        client_mod_dir=client,
        campaign_manifest=manifest,
    )

    assert any(
        "exactly one info.json root; found 2" in error
        for error in result.client_bundle_errors
    )


def test_zip_with_duplicate_logical_member_is_rejected(tmp_path):
    server, client, manifest, _ = _matching_bundle(tmp_path)
    archive_path = client / "duplicate_1.0.0.zip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr(
                "duplicate_1.0.0/info.json",
                '{"name":"duplicate","version":"1.0.0"}',
            )
            archive.writestr("duplicate_1.0.0/control.lua", "first")
            archive.writestr("duplicate_1.0.0/control.lua", "second")

    result = compare_campaign_client_mods(
        server_mod_dir=server,
        client_mod_dir=client,
        campaign_manifest=manifest,
    )

    assert any(
        "duplicate logical member" in error for error in result.client_bundle_errors
    )


@pytest.mark.parametrize(
    "unsafe_path",
    ["/absolute.lua", "unsafe_1.0.0/../escape.lua", "unsafe_1.0.0\\escape.lua"],
    ids=["absolute", "parent-traversal", "backslash"],
)
def test_zip_with_unsafe_path_is_rejected(tmp_path, unsafe_path):
    server, client, manifest, _ = _matching_bundle(tmp_path)
    archive_path = client / "unsafe_1.0.0.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "unsafe_1.0.0/info.json",
            '{"name":"unsafe","version":"1.0.0"}',
        )
        archive.writestr(unsafe_path, "escape")

    result = compare_campaign_client_mods(
        server_mod_dir=server,
        client_mod_dir=client,
        campaign_manifest=manifest,
    )

    assert any("unsafe member path" in error for error in result.client_bundle_errors)


def test_directory_artifact_symlink_cannot_read_external_file(tmp_path):
    server, client, manifest, client_mod = _matching_bundle(tmp_path)
    external = tmp_path / "outside.lua"
    external.write_text("secret", encoding="utf-8")
    (client_mod / "external.lua").symlink_to(external)

    result = compare_campaign_client_mods(
        server_mod_dir=server,
        client_mod_dir=client,
        campaign_manifest=manifest,
    )

    assert any(
        "contains a symbolic link" in error for error in result.client_bundle_errors
    )


def test_directory_artifact_rejects_external_info_symlink_before_reading(tmp_path):
    server, client, manifest, _ = _matching_bundle(tmp_path)
    external_info = tmp_path / "external-info.json"
    external_info.write_text('{"name":"linked","version":"1.0.0"}', encoding="utf-8")
    linked_mod = client / "linked_1.0.0"
    linked_mod.mkdir()
    (linked_mod / "info.json").symlink_to(external_info)

    result = compare_campaign_client_mods(
        server_mod_dir=server,
        client_mod_dir=client,
        campaign_manifest=manifest,
    )

    assert any(
        "artifact info.json is a symbolic link" in error
        for error in result.client_bundle_errors
    )


def test_zip_symlink_member_is_rejected(tmp_path):
    server, client, manifest, _ = _matching_bundle(tmp_path)
    archive_path = client / "linked_1.0.0.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "linked_1.0.0/info.json",
            '{"name":"linked","version":"1.0.0"}',
        )
        member = zipfile.ZipInfo("linked_1.0.0/external.lua")
        member.create_system = 3
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(member, "../../outside.lua")

    result = compare_campaign_client_mods(
        server_mod_dir=server,
        client_mod_dir=client,
        campaign_manifest=manifest,
    )

    assert any("symbolic-link member" in error for error in result.client_bundle_errors)


def test_multiple_server_artifact_versions_are_ambiguous(tmp_path):
    server, client, manifest, _ = _matching_bundle(tmp_path)
    _write_directory_mod(
        server, "fv_embodied_agent", "0.9.0", {"control.lua": "stale\n"}
    )

    result = compare_campaign_client_mods(
        server_mod_dir=server,
        client_mod_dir=client,
        campaign_manifest=manifest,
    )

    assert any(
        "campaign server has ambiguous artifacts for fv_embodied_agent" in error
        for error in result.server_bundle_errors
    )


@pytest.mark.parametrize(
    ("missing_hash", "message"),
    [
        ("server_mod_list", "no immutable server_mod_list hash"),
        ("embodied_mod", "no immutable embodied_mod hash"),
    ],
)
def test_immutable_manifest_proof_is_required(tmp_path, missing_hash, message):
    server, client, manifest, _ = _matching_bundle(tmp_path)
    del manifest["hashes"][missing_hash]

    result = compare_campaign_client_mods(
        server_mod_dir=server,
        client_mod_dir=client,
        campaign_manifest=manifest,
    )

    assert result.status.value == "mismatch"
    assert any(message in error for error in result.server_bundle_errors)


def test_every_custom_mod_requires_a_named_immutable_hash(tmp_path):
    server = tmp_path / "server"
    client = tmp_path / "client"
    _write_mod_list(server, ["base", "unknown_custom"])
    _write_mod_list(client, ["base", "unknown_custom"])
    _write_directory_mod(server, "unknown_custom", "1.0.0", {"control.lua": "same"})
    _write_directory_mod(client, "unknown_custom", "1.0.0", {"control.lua": "same"})
    manifest = _manifest(server, unknown_custom="1.0.0")

    result = compare_campaign_client_mods(
        server_mod_dir=server,
        client_mod_dir=client,
        campaign_manifest=manifest,
    )

    assert result.server_bundle_errors == [
        "campaign manifest defines no immutable hash key for custom mod: unknown_custom"
    ]


def test_server_mod_list_must_match_immutable_manifest_hash(tmp_path):
    server, client, manifest, _ = _matching_bundle(tmp_path)
    manifest["hashes"]["server_mod_list"] = "0" * 64

    result = compare_campaign_client_mods(
        server_mod_dir=server,
        client_mod_dir=client,
        campaign_manifest=manifest,
    )

    assert result.server_bundle_errors == [
        "campaign server mod-list differs from immutable manifest"
    ]


def test_cli_prejoin_exits_two_when_join_readiness_is_indeterminate(
    tmp_path, monkeypatch, capsys
):
    server, client, manifest, client_mod = _matching_bundle(tmp_path)
    store = SimpleNamespace(
        paths=SimpleNamespace(server_mods=server),
        manifest=lambda: manifest,
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

    assert exc_info.value.code == 2
    assert "Status: indeterminate" in capsys.readouterr().out
    assert (client_mod / "control.lua").read_bytes() == before


def test_cli_prejoin_returns_zero_for_verified_match(tmp_path, monkeypatch, capsys):
    server = tmp_path / "server"
    client = tmp_path / "client"
    store = SimpleNamespace(
        paths=SimpleNamespace(server_mods=server),
        manifest=lambda: {},
    )
    result = PrejoinModCompatibility(
        server_mod_dir=str(server),
        client_mod_dir=str(client),
        loaded_client_bytes_verified=True,
    )
    monkeypatch.setattr(
        "FactoryVerse.cli._freeplay_campaign_store", lambda campaign: store
    )
    monkeypatch.setattr(
        "FactoryVerse.evals.freeplay.prejoin.compare_campaign_client_mods",
        lambda **kwargs: result,
    )
    args = SimpleNamespace(
        campaign="campaign-1", client_mod_dir=str(client), json=False
    )

    cmd_freeplay_eval_prejoin(args)

    assert "Status: match" in capsys.readouterr().out
