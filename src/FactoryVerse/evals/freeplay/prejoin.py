"""Read-only client/server mod compatibility checks for campaign prejoin."""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .provenance import sha256_file


BUILTIN_MODS = {"base", "elevated-rails", "quality", "space-age"}
CAMPAIGN_MOD_HASH_KEYS = {
    "fv_embodied_agent": "embodied_mod",
    "fv_snapshot": "snapshot_mod",
    "fv_placement_hints": "placement_hints_mod",
}


@dataclass(frozen=True)
class _ModArtifact:
    name: str
    version: str
    path: Path
    files: dict[str, str]
    sha256: str


@dataclass
class PrejoinModCompatibility:
    """Exact filesystem comparison between a campaign and desktop client."""

    server_mod_dir: str
    client_mod_dir: str
    missing_mods: list[str] = field(default_factory=list)
    extra_mods: list[str] = field(default_factory=list)
    missing_artifacts: list[dict[str, str]] = field(default_factory=list)
    version_mismatches: list[dict[str, Any]] = field(default_factory=list)
    content_mismatches: list[dict[str, Any]] = field(default_factory=list)
    server_bundle_errors: list[str] = field(default_factory=list)
    client_bundle_errors: list[str] = field(default_factory=list)
    unverified_builtin_versions: list[str] = field(default_factory=list)

    @property
    def compatible(self) -> bool:
        return not any(
            (
                self.missing_mods,
                self.extra_mods,
                self.missing_artifacts,
                self.version_mismatches,
                self.content_mismatches,
                self.server_bundle_errors,
                self.client_bundle_errors,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "compatible": self.compatible,
            "server_mod_dir": self.server_mod_dir,
            "client_mod_dir": self.client_mod_dir,
            "missing_mods": self.missing_mods,
            "extra_mods": self.extra_mods,
            "missing_artifacts": self.missing_artifacts,
            "version_mismatches": self.version_mismatches,
            "content_mismatches": self.content_mismatches,
            "server_bundle_errors": self.server_bundle_errors,
            "client_bundle_errors": self.client_bundle_errors,
            "unverified_builtin_versions": self.unverified_builtin_versions,
            "client_files_modified": False,
            "restart_required_after_sync": True,
            "loaded_client_bytes_verified": False,
        }


def _enabled_mods(mod_dir: Path) -> set[str]:
    mod_list_path = mod_dir / "mod-list.json"
    if not mod_list_path.is_file():
        raise ValueError(f"mod-list.json is missing: {mod_list_path}")
    try:
        value = json.loads(mod_list_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read mod-list.json: {mod_list_path}: {exc}") from exc
    mods = value.get("mods")
    if not isinstance(mods, list):
        raise ValueError(f"mod-list.json has no mods array: {mod_list_path}")
    return {
        str(item["name"])
        for item in mods
        if isinstance(item, dict) and item.get("enabled") is True and item.get("name")
    }


def _manifest_sha256(files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for relative_path, file_hash in sorted(files.items()):
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(file_hash))
    return digest.hexdigest()


def _directory_artifact(path: Path) -> _ModArtifact | None:
    info_path = path / "info.json"
    if not info_path.is_file():
        return None
    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not info.get("name") or not info.get("version"):
        return None
    files = {
        item.relative_to(path).as_posix(): sha256_file(item)
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }
    return _ModArtifact(
        name=str(info["name"]),
        version=str(info["version"]),
        path=path,
        files=files,
        sha256=_manifest_sha256(files),
    )


def _zip_artifact(path: Path) -> _ModArtifact | None:
    try:
        with zipfile.ZipFile(path) as archive:
            info_entries = sorted(
                (
                    PurePosixPath(name)
                    for name in archive.namelist()
                    if PurePosixPath(name).name == "info.json"
                    and "__MACOSX" not in PurePosixPath(name).parts
                ),
                key=lambda item: (len(item.parts), item.as_posix()),
            )
            if not info_entries:
                return None
            info_entry = info_entries[0]
            info = json.loads(archive.read(info_entry.as_posix()).decode("utf-8"))
            if not info.get("name") or not info.get("version"):
                return None
            root = info_entry.parent
            files: dict[str, str] = {}
            for member in archive.infolist():
                member_path = PurePosixPath(member.filename)
                if member.is_dir() or root not in member_path.parents:
                    continue
                relative = member_path.relative_to(root).as_posix()
                files[relative] = hashlib.sha256(archive.read(member)).hexdigest()
    except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError, KeyError):
        return None
    return _ModArtifact(
        name=str(info["name"]),
        version=str(info["version"]),
        path=path,
        files=files,
        sha256=_manifest_sha256(files),
    )


def _discover_artifacts(mod_dir: Path) -> dict[str, list[_ModArtifact]]:
    artifacts: dict[str, list[_ModArtifact]] = {}
    if not mod_dir.is_dir():
        return artifacts
    for path in sorted(mod_dir.iterdir()):
        artifact = None
        if path.is_dir():
            artifact = _directory_artifact(path)
        elif path.is_file() and path.suffix.lower() == ".zip":
            artifact = _zip_artifact(path)
        if artifact is not None:
            artifacts.setdefault(artifact.name, []).append(artifact)
    return artifacts


def _content_difference(
    server: _ModArtifact, client: _ModArtifact
) -> dict[str, Any] | None:
    if server.sha256 == client.sha256:
        return None
    server_files = set(server.files)
    client_files = set(client.files)
    return {
        "name": server.name,
        "version": server.version,
        "server_artifact": str(server.path),
        "client_artifact": str(client.path),
        "server_sha256": server.sha256,
        "client_sha256": client.sha256,
        "missing_client_files": sorted(server_files - client_files),
        "extra_client_files": sorted(client_files - server_files),
        "changed_files": sorted(
            path
            for path in server_files & client_files
            if server.files[path] != client.files[path]
        ),
        "changed_file_sha256": {
            path: {"server": server.files[path], "client": client.files[path]}
            for path in sorted(server_files & client_files)
            if server.files[path] != client.files[path]
        },
    }


def compare_campaign_client_mods(
    *,
    server_mod_dir: Path,
    client_mod_dir: Path,
    campaign_manifest: dict[str, Any],
) -> PrejoinModCompatibility:
    """Compare campaign-private server mods with installed client mods.

    The comparison is read-only and does not trust client-side cache/hash files.
    Directory and ZIP artifacts are normalized to relative file paths and content
    hashes so archive packaging metadata cannot hide or invent a mismatch.
    """
    server_mod_dir = Path(server_mod_dir)
    client_mod_dir = Path(client_mod_dir)
    result = PrejoinModCompatibility(
        server_mod_dir=str(server_mod_dir.resolve()),
        client_mod_dir=str(client_mod_dir.resolve()),
    )
    expected_value = campaign_manifest.get("expected_active_mods")
    if not isinstance(expected_value, dict):
        result.server_bundle_errors.append(
            "campaign manifest has no expected_active_mods map"
        )
        return result
    expected = {str(name): str(version) for name, version in expected_value.items()}

    try:
        server_enabled = _enabled_mods(server_mod_dir)
    except ValueError as exc:
        result.server_bundle_errors.append(str(exc))
        server_enabled = set()
    try:
        client_enabled = _enabled_mods(client_mod_dir)
    except ValueError as exc:
        result.client_bundle_errors.append(str(exc))
        client_enabled = set()

    expected_names = set(expected)
    manifest_hashes = campaign_manifest.get("hashes")
    if server_enabled != expected_names:
        missing = sorted(expected_names - server_enabled)
        extra = sorted(server_enabled - expected_names)
        if missing:
            result.server_bundle_errors.append(
                "campaign server mod-list missing enabled mods: " + ", ".join(missing)
            )
        if extra:
            result.server_bundle_errors.append(
                "campaign server mod-list has unexpected enabled mods: "
                + ", ".join(extra)
            )

    result.missing_mods = sorted(expected_names - client_enabled)
    result.extra_mods = sorted(client_enabled - expected_names)
    server_artifacts = _discover_artifacts(server_mod_dir)
    client_artifacts = _discover_artifacts(client_mod_dir)

    server_exact: dict[str, _ModArtifact] = {}
    for name in sorted(expected_names):
        expected_version = expected[name]
        server_candidates = [
            artifact
            for artifact in server_artifacts.get(name, [])
            if artifact.version == expected_version
        ]
        if not server_candidates and name in BUILTIN_MODS:
            continue
        if not server_candidates:
            result.missing_artifacts.append(
                {"side": "server", "name": name, "version": expected_version}
            )
            continue
        if len(server_candidates) != 1:
            result.server_bundle_errors.append(
                f"campaign server has {len(server_candidates)} artifacts for "
                f"{name} {expected_version}"
            )
            continue
        server_exact[name] = server_candidates[0]
        hash_key = CAMPAIGN_MOD_HASH_KEYS.get(name)
        if (
            hash_key
            and isinstance(manifest_hashes, dict)
            and manifest_hashes.get(hash_key)
            and server_candidates[0].sha256 != manifest_hashes[hash_key]
        ):
            result.server_bundle_errors.append(
                f"campaign server mod bytes differ from immutable manifest: {name}"
            )

    for name in sorted(expected_names & client_enabled):
        expected_version = expected[name]
        if name in BUILTIN_MODS:
            result.unverified_builtin_versions.append(name)
            continue
        server_artifact = server_exact.get(name)
        if server_artifact is None:
            continue

        installed = client_artifacts.get(name, [])
        installed_versions = sorted({artifact.version for artifact in installed})
        if not installed:
            result.missing_artifacts.append(
                {"side": "client", "name": name, "version": expected_version}
            )
            continue
        exact = [artifact for artifact in installed if artifact.version == expected_version]
        if installed_versions != [expected_version] or len(exact) != 1:
            result.version_mismatches.append(
                {
                    "name": name,
                    "expected_version": expected_version,
                    "installed_versions": installed_versions,
                    "installed_artifacts": [str(item.path) for item in installed],
                }
            )
            continue
        difference = _content_difference(server_artifact, exact[0])
        if difference is not None:
            result.content_mismatches.append(difference)

    return result


def format_prejoin_mod_compatibility(result: PrejoinModCompatibility) -> str:
    """Render an actionable human report without changing either bundle."""
    lines = [
        (
            "Compatible client/server mod bundles."
            if result.compatible
            else "Client/server mod bundles are incompatible."
        ),
        f"Server bundle: {result.server_mod_dir}",
        f"Client bundle: {result.client_mod_dir}",
    ]
    if result.missing_mods:
        lines.append("Missing enabled client mods: " + ", ".join(result.missing_mods))
    if result.extra_mods:
        lines.append("Unexpected enabled client mods: " + ", ".join(result.extra_mods))
    for item in result.missing_artifacts:
        lines.append(
            f"Missing {item['side']} artifact: {item['name']} {item['version']}"
        )
    for item in result.version_mismatches:
        versions = ", ".join(item["installed_versions"]) or "none"
        lines.append(
            f"Version mismatch: {item['name']} expected {item['expected_version']}; "
            f"installed {versions}"
        )
    for item in result.content_mismatches:
        lines.append(
            f"Content mismatch: {item['name']} {item['version']} "
            f"server={item['server_sha256']} client={item['client_sha256']}"
        )
        for key in ("missing_client_files", "extra_client_files", "changed_files"):
            if item[key]:
                lines.append(f"  {key}: " + ", ".join(item[key]))
    for error in result.server_bundle_errors:
        lines.append("Server bundle error: " + error)
    for error in result.client_bundle_errors:
        lines.append("Client bundle error: " + error)
    if result.unverified_builtin_versions:
        lines.append(
            "Built-in client versions not verifiable from mods directory: "
            + ", ".join(result.unverified_builtin_versions)
        )
    lines.append("This check did not modify client files.")
    if not result.compatible:
        lines.append(
            "After syncing the client bundle, restart Factorio before connecting."
        )
    lines.append(
        "An already-running client's loaded mod bytes cannot be proven from its "
        "on-disk bundle; restart after any mod change."
    )
    return "\n".join(lines)
