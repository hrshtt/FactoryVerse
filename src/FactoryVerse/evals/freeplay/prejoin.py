"""Read-only client/server mod compatibility checks for campaign prejoin."""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any

from .provenance import canonical_json_sha256, sha256_file


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


@dataclass(frozen=True)
class _ModList:
    enabled: set[str]
    value: dict[str, Any]


class PrejoinStatus(str, Enum):
    """How conclusively the read-only evidence answers prejoin readiness."""

    MATCH = "match"
    MISMATCH = "mismatch"
    INDETERMINATE = "indeterminate"


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
    loaded_client_bytes_verified: bool = False

    @property
    def status(self) -> PrejoinStatus:
        if any(
            (
                self.missing_mods,
                self.extra_mods,
                self.missing_artifacts,
                self.version_mismatches,
                self.content_mismatches,
                self.server_bundle_errors,
                self.client_bundle_errors,
            )
        ):
            return PrejoinStatus.MISMATCH
        if self.unverified_builtin_versions or not self.loaded_client_bytes_verified:
            return PrejoinStatus.INDETERMINATE
        return PrejoinStatus.MATCH

    @property
    def compatible(self) -> bool:
        """Backward-compatible boolean that never promotes unknowns to success."""
        return self.status is PrejoinStatus.MATCH

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
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
            "loaded_client_bytes_verified": self.loaded_client_bytes_verified,
        }


def _read_mod_list(mod_dir: Path) -> _ModList:
    mod_list_path = mod_dir / "mod-list.json"
    if not mod_list_path.is_file():
        raise ValueError(f"mod-list.json is missing: {mod_list_path}")
    try:
        value = json.loads(mod_list_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read mod-list.json: {mod_list_path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"mod-list.json root is not an object: {mod_list_path}")
    mods = value.get("mods")
    if not isinstance(mods, list):
        raise ValueError(f"mod-list.json has no mods array: {mod_list_path}")
    enabled: set[str] = set()
    seen: set[str] = set()
    for index, item in enumerate(mods):
        if not isinstance(item, dict):
            raise ValueError(
                f"mod-list.json entry {index} is not an object: {mod_list_path}"
            )
        name = item.get("name")
        if not isinstance(name, str) or not name or name.strip() != name:
            raise ValueError(
                f"mod-list.json entry {index} has an invalid name: {mod_list_path}"
            )
        if name in seen:
            raise ValueError(
                f"mod-list.json has duplicate mod name {name!r}: {mod_list_path}"
            )
        seen.add(name)
        if not isinstance(item.get("enabled"), bool):
            raise ValueError(
                f"mod-list.json entry {index} has a non-boolean enabled value: "
                f"{mod_list_path}"
            )
        if item["enabled"]:
            enabled.add(name)
    return _ModList(enabled=enabled, value=value)


def _manifest_sha256(files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for relative_path, file_hash in sorted(files.items()):
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(file_hash))
    return digest.hexdigest()


def _artifact_identity(info: Any, path: Path) -> tuple[str, str]:
    if not isinstance(info, dict):
        raise ValueError(f"info.json root is not an object: {path}")
    name = info.get("name")
    version = info.get("version")
    if not isinstance(name, str) or not name or name.strip() != name:
        raise ValueError(f"info.json has an invalid name: {path}")
    if not isinstance(version, str) or not version or version.strip() != version:
        raise ValueError(f"info.json has an invalid version: {path}")
    return name, version


def _directory_artifact(path: Path) -> _ModArtifact:
    if path.is_symlink():
        raise ValueError(f"artifact directory is a symbolic link: {path}")
    info_path = path / "info.json"
    if info_path.is_symlink():
        raise ValueError(f"artifact info.json is a symbolic link: {info_path}")
    if not info_path.is_file():
        raise ValueError(f"artifact directory has no info.json: {path}")
    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read artifact info.json: {info_path}: {exc}") from exc
    name, version = _artifact_identity(info, info_path)
    files: dict[str, str] = {}
    for item in sorted(path.rglob("*")):
        if item.is_symlink():
            raise ValueError(f"artifact contains a symbolic link: {item}")
        if item.is_dir():
            continue
        if not item.is_file():
            raise ValueError(f"artifact contains a non-regular entry: {item}")
        try:
            item.relative_to(path)
        except ValueError as exc:
            raise ValueError(f"artifact entry escapes its directory: {item}") from exc
        files[item.relative_to(path).as_posix()] = sha256_file(item)
    return _ModArtifact(
        name=name,
        version=version,
        path=path,
        files=files,
        sha256=_manifest_sha256(files),
    )


def _safe_zip_member_path(name: str, archive_path: Path) -> PurePosixPath:
    if not name or "\\" in name or name.startswith("/"):
        raise ValueError(f"ZIP has an unsafe member path {name!r}: {archive_path}")
    components = name.split("/")
    if components[-1] == "":
        components = components[:-1]
    if not components or any(item in {"", ".", ".."} for item in components):
        raise ValueError(f"ZIP has an unsafe member path {name!r}: {archive_path}")
    member_path = PurePosixPath(*components)
    if member_path.is_absolute():
        raise ValueError(f"ZIP has an unsafe member path {name!r}: {archive_path}")
    return member_path


def _zip_artifact(path: Path) -> _ModArtifact:
    if path.is_symlink():
        raise ValueError(f"artifact ZIP is a symbolic link: {path}")
    try:
        with zipfile.ZipFile(path) as archive:
            members: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
            seen_members: set[str] = set()
            for member in archive.infolist():
                member_path = _safe_zip_member_path(member.filename, path)
                logical_path = member_path.as_posix()
                if logical_path in seen_members:
                    raise ValueError(
                        f"ZIP has duplicate logical member {logical_path!r}: {path}"
                    )
                seen_members.add(logical_path)
                file_type = (member.external_attr >> 16) & 0o170000
                if file_type == stat.S_IFLNK:
                    raise ValueError(
                        f"ZIP contains a symbolic-link member {logical_path!r}: {path}"
                    )
                if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
                    raise ValueError(
                        f"ZIP contains a non-regular member {logical_path!r}: {path}"
                    )
                members.append((member, member_path))
            info_entries = [
                member_path
                for member, member_path in members
                if not member.is_dir()
                and member_path.name == "info.json"
                and "__MACOSX" not in member_path.parts
            ]
            if len(info_entries) != 1:
                raise ValueError(
                    f"ZIP must contain exactly one info.json root; found "
                    f"{len(info_entries)}: {path}"
                )
            info_entry = info_entries[0]
            info = json.loads(archive.read(info_entry.as_posix()).decode("utf-8"))
            name, version = _artifact_identity(info, path)
            root = info_entry.parent
            files: dict[str, str] = {}
            for member, member_path in members:
                if "__MACOSX" in member_path.parts:
                    continue
                if member_path != root and root not in member_path.parents:
                    raise ValueError(
                        f"ZIP member is outside the artifact root {root}: "
                        f"{member_path} in {path}"
                    )
                if member.is_dir():
                    continue
                relative = member_path.relative_to(root).as_posix()
                files[relative] = hashlib.sha256(archive.read(member)).hexdigest()
    except (
        OSError,
        UnicodeDecodeError,
        zipfile.BadZipFile,
        json.JSONDecodeError,
        KeyError,
        RuntimeError,
    ) as exc:
        raise ValueError(f"cannot read artifact ZIP {path}: {exc}") from exc
    return _ModArtifact(
        name=name,
        version=version,
        path=path,
        files=files,
        sha256=_manifest_sha256(files),
    )


def _artifact_shaped_directory(path: Path) -> bool:
    if (path / "info.json").exists():
        return True
    stem, separator, version = path.name.rpartition("_")
    return bool(separator and stem and version and version[0].isdigit())


def _discover_artifacts(
    mod_dir: Path,
) -> tuple[dict[str, list[_ModArtifact]], list[str]]:
    artifacts: dict[str, list[_ModArtifact]] = {}
    errors: list[str] = []
    if not mod_dir.is_dir():
        return artifacts, [f"mod directory is missing or not a directory: {mod_dir}"]
    for path in sorted(mod_dir.iterdir()):
        if path.is_symlink():
            errors.append(f"mod directory contains a symbolic link: {path}")
            continue
        is_zip = path.suffix.lower() == ".zip"
        is_directory_artifact = path.is_dir() and _artifact_shaped_directory(path)
        if not (is_zip or is_directory_artifact):
            continue
        try:
            artifact = _zip_artifact(path) if is_zip else _directory_artifact(path)
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
        else:
            artifacts.setdefault(artifact.name, []).append(artifact)
    return artifacts, errors


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

    Existing immutable campaign hashes retain ``sha256_tree``'s native path
    spelling. A campaign created on Windows can therefore conservatively report a
    hash mismatch when checked on POSIX; changing that would invalidate existing
    campaign hashes and requires a versioned provenance migration.
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
    expected: dict[str, str] = {}
    for name, version in expected_value.items():
        if not isinstance(name, str) or not name or name.strip() != name:
            result.server_bundle_errors.append(
                "campaign manifest has an invalid expected mod name"
            )
            continue
        if not isinstance(version, str) or not version or version.strip() != version:
            result.server_bundle_errors.append(
                f"campaign manifest has an invalid version for {name}"
            )
            continue
        expected[name] = version

    try:
        server_mod_list = _read_mod_list(server_mod_dir)
        server_enabled = server_mod_list.enabled
    except ValueError as exc:
        result.server_bundle_errors.append(str(exc))
        server_mod_list = None
        server_enabled = set()
    try:
        client_enabled = _read_mod_list(client_mod_dir).enabled
    except ValueError as exc:
        result.client_bundle_errors.append(str(exc))
        client_enabled = set()

    expected_names = set(expected)
    manifest_hashes = campaign_manifest.get("hashes")
    if not isinstance(manifest_hashes, dict):
        result.server_bundle_errors.append("campaign manifest has no hashes map")
        manifest_hashes = {}
    expected_mod_list_hash = manifest_hashes.get("server_mod_list")
    if not isinstance(expected_mod_list_hash, str) or not expected_mod_list_hash:
        result.server_bundle_errors.append(
            "campaign manifest has no immutable server_mod_list hash"
        )
    elif (
        server_mod_list is not None
        and canonical_json_sha256(server_mod_list.value) != expected_mod_list_hash
    ):
        result.server_bundle_errors.append(
            "campaign server mod-list differs from immutable manifest"
        )

    expected_custom_hashes: dict[str, str] = {}
    for name in sorted(expected_names - BUILTIN_MODS):
        hash_key = CAMPAIGN_MOD_HASH_KEYS.get(name)
        if hash_key is None:
            result.server_bundle_errors.append(
                f"campaign manifest defines no immutable hash key for custom mod: {name}"
            )
            continue
        expected_hash = manifest_hashes.get(hash_key)
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            result.server_bundle_errors.append(
                f"campaign manifest has no immutable {hash_key} hash for custom mod: "
                f"{name}"
            )
            continue
        try:
            bytes.fromhex(expected_hash)
        except ValueError:
            result.server_bundle_errors.append(
                f"campaign manifest has an invalid {hash_key} hash for custom mod: "
                f"{name}"
            )
            continue
        expected_custom_hashes[name] = expected_hash

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
    server_artifacts, server_artifact_errors = _discover_artifacts(server_mod_dir)
    client_artifacts, client_artifact_errors = _discover_artifacts(client_mod_dir)
    result.server_bundle_errors.extend(server_artifact_errors)
    result.client_bundle_errors.extend(client_artifact_errors)

    server_exact: dict[str, _ModArtifact] = {}
    for name in sorted(expected_names):
        expected_version = expected[name]
        server_candidates = server_artifacts.get(name, [])
        if not server_candidates and name in BUILTIN_MODS:
            continue
        if not server_candidates:
            result.missing_artifacts.append(
                {"side": "server", "name": name, "version": expected_version}
            )
            continue
        if len(server_candidates) != 1:
            result.server_bundle_errors.append(
                f"campaign server has ambiguous artifacts for {name}: "
                + ", ".join(str(item.path) for item in server_candidates)
            )
            continue
        candidate = server_candidates[0]
        if candidate.version != expected_version:
            result.server_bundle_errors.append(
                f"campaign server artifact version differs from manifest: {name} "
                f"expected {expected_version}, found {candidate.version}"
            )
            continue
        server_exact[name] = candidate
        expected_hash = expected_custom_hashes.get(name)
        if expected_hash and candidate.sha256 != expected_hash:
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
        exact = [
            artifact for artifact in installed if artifact.version == expected_version
        ]
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
    if result.status is PrejoinStatus.MATCH:
        headline = "Verified prejoin evidence matches the campaign."
    elif result.status is PrejoinStatus.INDETERMINATE:
        headline = (
            "On-disk custom mod artifacts match the campaign; full join readiness "
            "is indeterminate."
        )
    else:
        headline = "On-disk mod evidence does not match the campaign."
    lines = [
        headline,
        f"Status: {result.status.value}",
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
    if result.status is PrejoinStatus.MISMATCH:
        lines.append(
            "After syncing the client bundle, restart Factorio before connecting."
        )
    lines.append(
        "An already-running client's loaded mod bytes cannot be proven from its "
        "on-disk bundle; restart after any mod change."
    )
    return "\n".join(lines)
