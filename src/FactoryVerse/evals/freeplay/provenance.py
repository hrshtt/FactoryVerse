"""Reproducibility metadata for freeplay campaign manifests."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(path: Path) -> str:
    """Hash file names and contents below ``path`` deterministically."""
    digest = hashlib.sha256()
    root = Path(path)
    if not root.exists():
        return digest.hexdigest()
    for file_path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(str(file_path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(file_path)))
    return digest.hexdigest()


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _untracked_files_fingerprint(repo_root: Path) -> tuple[str, int]:
    """Hash paths and contents for every non-ignored untracked repository file.

    ``git status`` proves which paths are untracked, but its output is unchanged
    when the contents of one of those files changes. Comparative campaigns need
    the actual source bytes in their immutable provenance boundary as well.
    Symlinks are hashed by link target instead of following them outside the
    repository.
    """
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return "unknown", 0

    digest = hashlib.sha256()
    paths = [value for value in result.stdout.split(b"\0") if value]
    for raw_relative_path in sorted(paths):
        relative_path = os.fsdecode(raw_relative_path)
        file_path = repo_root / relative_path
        digest.update(raw_relative_path)
        digest.update(b"\0")
        if file_path.is_symlink():
            digest.update(b"symlink\0")
            digest.update(os.fsencode(os.readlink(file_path)))
        elif file_path.is_file():
            digest.update(b"file\0")
            digest.update(bytes.fromhex(sha256_file(file_path)))
        else:
            # Preserve a deterministic marker if the worktree changes while
            # provenance is being captured.
            digest.update(b"missing\0")
    return digest.hexdigest(), len(paths)


def repository_provenance(repo_root: Path) -> Dict[str, Any]:
    status = _git(repo_root, "status", "--porcelain=v1", "--untracked-files=all")
    tracked_diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        check=False,
    ).stdout
    status_digest = hashlib.sha256(status.encode("utf-8")).hexdigest()
    diff_digest = hashlib.sha256(tracked_diff).hexdigest()
    untracked_digest, untracked_count = _untracked_files_fingerprint(repo_root)
    return {
        "commit": _git(repo_root, "rev-parse", "HEAD"),
        "dirty": bool(status),
        "status_sha256": status_digest,
        "tracked_diff_sha256": diff_digest,
        "untracked_files_sha256": untracked_digest,
        "untracked_file_count": untracked_count,
        "fingerprint_method": (
            "sha256(git-status) + sha256(git-diff-binary-HEAD) + "
            "sha256(untracked-paths-and-contents)"
        ),
    }


def canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
