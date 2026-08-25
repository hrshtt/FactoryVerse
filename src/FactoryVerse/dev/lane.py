"""Bounded Git worktree lanes for visible, interactive Codex workers."""

from __future__ import annotations

import fcntl
import json
import os
import re
import shlex
import shutil
import subprocess
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from dotenv import dotenv_values


LANE_SCHEMA_VERSION = 1
MAX_RESOURCE_SLOT = 30
_LANE_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class LaneError(RuntimeError):
    """A lane could not be created, validated, or entered safely."""


@dataclass(frozen=True)
class GitRepository:
    """Canonical paths shared by every worktree of one Git repository."""

    current_worktree: Path
    primary_worktree: Path
    common_git_dir: Path

    @property
    def registry_dir(self) -> Path:
        return self.common_git_dir / "factoryverse-lanes"

    @classmethod
    def discover(cls, start: Path | str = ".") -> "GitRepository":
        cwd = Path(start).expanduser().resolve()
        current = Path(_git(cwd, "rev-parse", "--show-toplevel")).resolve()
        common = Path(
            _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
        ).resolve()
        listing = _git(cwd, "worktree", "list", "--porcelain")
        primary_line = next(
            (line for line in listing.splitlines() if line.startswith("worktree ")),
            None,
        )
        if primary_line is None:
            raise LaneError("git worktree list returned no primary worktree")
        primary = Path(primary_line.removeprefix("worktree ")).resolve()
        return cls(
            current_worktree=current,
            primary_worktree=primary,
            common_git_dir=common,
        )


@dataclass(frozen=True)
class LaneManifest:
    """Durable host-local identity for one interactive experiment lane."""

    schema_version: int
    kind: str
    name: str
    repository_root: str
    git_common_dir: str
    worktree_path: str
    branch: str
    base_ref: str
    base_commit: str
    development_slot: int
    output_dir: str
    objective: str
    env_file: str | None
    codex_executable: str
    codex_model: str | None
    sandbox: str
    approval_policy: str
    no_alt_screen: bool
    strict_config: bool
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LaneManifest":
        try:
            manifest = cls(**dict(value))
        except TypeError as exc:
            raise LaneError(f"invalid lane manifest fields: {exc}") from exc
        manifest.validate()
        return manifest

    def validate(self) -> None:
        validate_lane_name(self.name)
        if self.schema_version != LANE_SCHEMA_VERSION:
            raise LaneError(
                f"unsupported lane schema {self.schema_version}; "
                f"expected {LANE_SCHEMA_VERSION}"
            )
        if self.kind != "factoryverse-codex-lane":
            raise LaneError(f"unexpected lane manifest kind: {self.kind!r}")
        if not 0 <= self.development_slot <= MAX_RESOURCE_SLOT:
            raise LaneError(
                f"development slot must be between 0 and {MAX_RESOURCE_SLOT}"
            )
        worktree = Path(self.worktree_path)
        output = Path(self.output_dir)
        if not worktree.is_absolute() or not output.is_absolute():
            raise LaneError("lane worktree and output paths must be absolute")
        if not output.is_relative_to(worktree):
            raise LaneError("lane output directory must remain inside its worktree")
        if self.sandbox not in {"read-only", "workspace-write"}:
            raise LaneError(
                "lane sandbox must be read-only or workspace-write; "
                "danger-full-access is intentionally unsupported"
            )
        if self.approval_policy not in {"untrusted", "on-request"}:
            raise LaneError(
                "lane approval policy must be untrusted or on-request; "
                "never is intentionally unsupported"
            )


def validate_lane_name(name: str) -> str:
    if not _LANE_NAME.fullmatch(name):
        raise LaneError(
            "lane name must start with a lowercase letter or digit and contain "
            "only lowercase letters, digits, '.', '_', or '-'"
        )
    return name


def create_lane(
    name: str,
    *,
    start: Path | str = ".",
    base_ref: str = "HEAD",
    branch: str | None = None,
    lanes_root: Path | str | None = None,
    worktree_path: Path | str | None = None,
    development_slot: int | None = None,
    output_dir: Path | str = ".fv-output",
    objective: str = "Investigate one bounded FactoryVerse harness question.",
    env_file: Path | str | None = None,
    codex_executable: str = "codex",
    codex_model: str | None = None,
    sandbox: str = "workspace-write",
    approval_policy: str = "on-request",
    no_alt_screen: bool = True,
    strict_config: bool = False,
) -> LaneManifest:
    """Create one worktree and register its immutable lane boundary."""

    validate_lane_name(name)
    _validate_codex_settings(
        objective=objective,
        codex_executable=codex_executable,
        sandbox=sandbox,
        approval_policy=approval_policy,
    )
    invocation_dir = Path(start).expanduser().resolve()
    repo = GitRepository.discover(invocation_dir)
    with _registry_lock(repo):
        return _create_lane_locked(
            name,
            invocation_dir=invocation_dir,
            repo=repo,
            base_ref=base_ref,
            branch=branch,
            lanes_root=lanes_root,
            worktree_path=worktree_path,
            development_slot=development_slot,
            output_dir=output_dir,
            objective=objective,
            env_file=env_file,
            codex_executable=codex_executable,
            codex_model=codex_model,
            sandbox=sandbox,
            approval_policy=approval_policy,
            no_alt_screen=no_alt_screen,
            strict_config=strict_config,
        )


def _create_lane_locked(
    name: str,
    *,
    invocation_dir: Path,
    repo: GitRepository,
    base_ref: str,
    branch: str | None,
    lanes_root: Path | str | None,
    worktree_path: Path | str | None,
    development_slot: int | None,
    output_dir: Path | str,
    objective: str,
    env_file: Path | str | None,
    codex_executable: str,
    codex_model: str | None,
    sandbox: str,
    approval_policy: str,
    no_alt_screen: bool,
    strict_config: bool,
) -> LaneManifest:
    """Create a lane while holding the repository-wide registry lock."""

    manifest_path = _manifest_path(repo, name)
    if manifest_path.exists():
        raise LaneError(f"lane {name!r} already exists; use 'fv lane status {name}'")

    existing = list_lanes(start=invocation_dir)
    used_slots = {lane.development_slot for lane in existing}
    slot = _select_slot(development_slot, used_slots)

    selected_branch = branch or f"research/lane-{name}"
    _validate_branch(repo.current_worktree, selected_branch)
    if _git_ok(
        repo.current_worktree,
        "show-ref",
        "--verify",
        "--quiet",
        f"refs/heads/{selected_branch}",
    ):
        raise LaneError(
            f"branch {selected_branch!r} already exists; choose another --branch"
        )

    base_commit = _git(
        repo.current_worktree, "rev-parse", "--verify", f"{base_ref}^{{commit}}"
    )
    if worktree_path is not None and lanes_root is not None:
        raise LaneError("pass either --path or --root, not both")
    if worktree_path is not None:
        selected_worktree = _resolve_path(invocation_dir, worktree_path)
    else:
        root = (
            _resolve_path(invocation_dir, lanes_root)
            if lanes_root is not None
            else repo.primary_worktree.parent / f"{repo.primary_worktree.name}-lanes"
        )
        selected_worktree = (root / name).resolve()
    for registered in _registered_worktrees(repo.current_worktree):
        if selected_worktree == registered:
            raise LaneError(f"worktree path is already registered: {selected_worktree}")
        if selected_worktree.is_relative_to(registered):
            raise LaneError(
                "lane worktrees may not be nested inside another Git worktree: "
                f"{selected_worktree}"
            )
    if selected_worktree.exists():
        raise LaneError(f"lane worktree path already exists: {selected_worktree}")

    selected_output = _resolve_path(selected_worktree, output_dir)
    if not selected_output.is_relative_to(selected_worktree):
        raise LaneError("--output-dir must resolve inside the lane worktree")
    selected_env = (
        _resolve_path(invocation_dir, env_file) if env_file is not None else None
    )
    if selected_env is not None and not selected_env.is_file():
        raise LaneError(f"lane env file does not exist: {selected_env}")

    selected_worktree.parent.mkdir(parents=True, exist_ok=True)
    _git(
        repo.current_worktree,
        "worktree",
        "add",
        "-b",
        selected_branch,
        str(selected_worktree),
        base_commit,
    )

    manifest = LaneManifest(
        schema_version=LANE_SCHEMA_VERSION,
        kind="factoryverse-codex-lane",
        name=name,
        repository_root=str(repo.primary_worktree),
        git_common_dir=str(repo.common_git_dir),
        worktree_path=str(selected_worktree),
        branch=selected_branch,
        base_ref=base_ref,
        base_commit=base_commit,
        development_slot=slot,
        output_dir=str(selected_output),
        objective=objective.strip(),
        env_file=str(selected_env) if selected_env is not None else None,
        codex_executable=codex_executable,
        codex_model=codex_model,
        sandbox=sandbox,
        approval_policy=approval_policy,
        no_alt_screen=no_alt_screen,
        strict_config=strict_config,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    manifest.validate()
    _write_json_atomic(manifest_path, manifest.to_dict())
    return manifest


def list_lanes(*, start: Path | str = ".") -> list[LaneManifest]:
    repo = GitRepository.discover(start)
    if not repo.registry_dir.exists():
        return []
    lanes: list[LaneManifest] = []
    for path in sorted(repo.registry_dir.glob("*.json")):
        try:
            lanes.append(
                LaneManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))
            )
        except (json.JSONDecodeError, OSError, LaneError) as exc:
            raise LaneError(f"cannot read lane manifest {path}: {exc}") from exc
    return lanes


def load_lane(name: str, *, start: Path | str = ".") -> LaneManifest:
    validate_lane_name(name)
    repo = GitRepository.discover(start)
    path = _manifest_path(repo, name)
    if not path.is_file():
        raise LaneError(f"unknown lane {name!r}; use 'fv lane list'")
    try:
        return LaneManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError) as exc:
        raise LaneError(f"cannot read lane manifest {path}: {exc}") from exc


def lane_status(lane: LaneManifest, *, start: Path | str = ".") -> dict[str, Any]:
    """Return verified Git and campaign state without mutating the lane."""

    repo = GitRepository.discover(start)
    worktree = Path(lane.worktree_path)
    registered = worktree in _registered_worktrees(repo.current_worktree)
    errors: list[str] = []
    branch: str | None = None
    head: str | None = None
    dirty: bool | None = None
    if not worktree.is_dir():
        errors.append("worktree path is missing")
    elif not registered:
        errors.append("path is not a registered worktree of this repository")
    else:
        branch = _git_optional(worktree, "branch", "--show-current") or None
        head = _git_optional(worktree, "rev-parse", "HEAD") or None
        dirty = bool(_git_optional(worktree, "status", "--porcelain=v1"))
        if branch != lane.branch:
            errors.append(
                f"branch mismatch: manifest={lane.branch!r}, current={branch!r}"
            )
        if head and not _git_ok(
            worktree, "merge-base", "--is-ancestor", lane.base_commit, head
        ):
            errors.append("lane HEAD does not descend from its pinned base commit")

    campaigns = _campaign_summaries(Path(lane.output_dir))
    return {
        "manifest": lane.to_dict(),
        "healthy": not errors,
        "errors": errors,
        "worktree_exists": worktree.is_dir(),
        "registered_worktree": registered,
        "current_branch": branch,
        "head": head,
        "dirty": dirty,
        "codex_executable_available": _executable_available(lane.codex_executable),
        "campaigns": campaigns,
    }


def retire_lane(lane: LaneManifest, *, start: Path | str = ".") -> dict[str, str]:
    """Retire an empty, clean lane while preserving its Git branch."""

    repo = GitRepository.discover(start)
    worktree = Path(lane.worktree_path)
    if repo.current_worktree == worktree:
        raise LaneError(
            "run lane retirement from another worktree, not from inside the lane"
        )

    with _registry_lock(repo):
        current = load_lane(lane.name, start=repo.current_worktree)
        if current != lane:
            raise LaneError("lane manifest changed while retirement was requested")
        status = lane_status(current, start=repo.current_worktree)
        if not status["healthy"]:
            raise LaneError(
                "lane is not safely retireable: " + "; ".join(status["errors"])
            )
        if status["dirty"]:
            raise LaneError(
                "lane worktree is dirty; review or preserve its changes before retirement"
            )
        active = [
            campaign["campaign_id"]
            for campaign in status["campaigns"]
            if campaign["active_session_id"] is not None
            or campaign["status"] in {"provisioning", "running"}
        ]
        if active:
            raise LaneError(
                "lane has active campaigns and cannot be retired: " + ", ".join(active)
            )
        output = Path(current.output_dir)
        if output.exists() and any(output.iterdir()):
            raise LaneError(
                "lane output contains artifacts; preserve or relocate them before "
                f"retirement: {output}"
            )

        _git(repo.current_worktree, "worktree", "remove", str(worktree))
        manifest_path = _manifest_path(repo, current.name)
        try:
            manifest_path.unlink()
        except OSError as exc:
            raise LaneError(
                "worktree was retired but its lane manifest could not be removed: "
                f"{manifest_path}: {exc}"
            ) from exc
        return {
            "name": current.name,
            "worktree_path": current.worktree_path,
            "preserved_branch": current.branch,
        }


def build_codex_command(
    lane: LaneManifest,
    *,
    additional_prompt: str | None = None,
    search: bool = False,
) -> list[str]:
    """Build the visible interactive Codex command for a registered lane."""

    command = [
        lane.codex_executable,
        "-C",
        lane.worktree_path,
        "--sandbox",
        lane.sandbox,
        "--ask-for-approval",
        lane.approval_policy,
    ]
    if lane.no_alt_screen:
        command.append("--no-alt-screen")
    if lane.strict_config:
        command.append("--strict-config")
    if lane.codex_model:
        command.extend(["--model", lane.codex_model])
    if search:
        command.append("--search")
    command.append(_lane_prompt(lane, additional_prompt=additional_prompt))
    return command


def lane_environment(
    lane: LaneManifest, *, base: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Build the child environment, importing only FV_* keys from an env file."""

    inherited = os.environ if base is None else base
    environment = {
        key: value for key, value in inherited.items() if not key.startswith("FV_")
    }
    if lane.env_file:
        for key, value in dotenv_values(lane.env_file).items():
            if key.startswith("FV_") and value is not None:
                environment[key] = value
    environment["FV_OUTPUT_DIR"] = lane.output_dir
    environment["FACTORYVERSE_LANE_NAME"] = lane.name
    environment["FACTORYVERSE_LANE_DEVELOPMENT_SLOT"] = str(lane.development_slot)
    return environment


def enter_lane(
    lane: LaneManifest,
    *,
    start: Path | str = ".",
    additional_prompt: str | None = None,
    search: bool = False,
    dry_run: bool = False,
) -> int:
    status = lane_status(lane, start=start)
    if not status["healthy"]:
        raise LaneError("lane is not enterable: " + "; ".join(status["errors"]))
    command = build_codex_command(
        lane, additional_prompt=additional_prompt, search=search
    )
    if dry_run:
        print(shlex.join(command))
        return 0
    try:
        completed = subprocess.run(
            command,
            cwd=lane.worktree_path,
            env=lane_environment(lane),
            check=False,
        )
    except OSError as exc:
        raise LaneError(
            f"cannot launch Codex executable {lane.codex_executable!r}: {exc}"
        ) from exc
    return completed.returncode


def _lane_prompt(lane: LaneManifest, *, additional_prompt: str | None) -> str:
    lines = [
        f"You are the visible interactive operator for FactoryVerse lane {lane.name!r}.",
        "",
        "Trusted lane boundary:",
        f"- Worktree: {lane.worktree_path}",
        f"- Branch: {lane.branch}",
        f"- Pinned base commit: {lane.base_commit}",
        f"- Default FactoryVerse development slot: {lane.development_slot}",
        "  (This is an operational default, not a scientific assignment or held lease.)",
        f"- Output root: {lane.output_dir}",
        f"- Objective: {lane.objective}",
        "",
        "Operating contract:",
        "1. Work only in this worktree and do not add other writable directories.",
        "2. Preserve unrelated changes. Do not commit, push, merge, or delete a worktree unless the user explicitly asks.",
        "3. Show the user the exact experiment command before launching a campaign.",
        f"4. For ad hoc development only, default to --slot {lane.development_slot} and a campaign id beginning with {lane.name}-.",
        "5. For an S2 experiment, use its frozen campaign id and assigned slot instead of the lane default.",
        "6. Use uv run fv freeplay-eval for campaign lifecycle operations. Do not invoke docker or docker compose directly.",
        "7. Keep development evidence separate from comparative evaluation claims.",
        "8. Start by reporting pwd, git branch, git status, pinned base ancestry, and the lane objective. Do not launch a campaign immediately.",
    ]
    if additional_prompt and additional_prompt.strip():
        lines.extend(["", "Additional user assignment:", additional_prompt.strip()])
    return "\n".join(lines)


def _campaign_summaries(output_dir: Path) -> list[dict[str, Any]]:
    root = output_dir / "freeplay"
    if not root.is_dir():
        return []
    summaries: list[dict[str, Any]] = []
    for state_path in sorted(root.glob("*/state.json")):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state = {"status": "unreadable"}
        summaries.append(
            {
                "campaign_id": state_path.parent.name,
                "status": state.get("status"),
                "active_session_id": state.get("active_session_id"),
            }
        )
    return summaries


def _select_slot(requested: int | None, used: set[int]) -> int:
    if requested is not None:
        if not 0 <= requested <= MAX_RESOURCE_SLOT:
            raise LaneError(
                f"development slot must be between 0 and {MAX_RESOURCE_SLOT}"
            )
        if requested in used:
            raise LaneError(
                f"development slot {requested} is already assigned to a lane"
            )
        return requested
    for slot in range(MAX_RESOURCE_SLOT + 1):
        if slot not in used:
            return slot
    raise LaneError("no unassigned FactoryVerse development slots remain")


def _validate_codex_settings(
    *,
    objective: str,
    codex_executable: str,
    sandbox: str,
    approval_policy: str,
) -> None:
    if not objective.strip():
        raise LaneError("lane objective must not be empty")
    if not codex_executable.strip():
        raise LaneError("Codex executable must not be empty")
    if sandbox not in {"read-only", "workspace-write"}:
        raise LaneError(
            "lane sandbox must be read-only or workspace-write; "
            "danger-full-access is intentionally unsupported"
        )
    if approval_policy not in {"untrusted", "on-request"}:
        raise LaneError(
            "lane approval policy must be untrusted or on-request; "
            "never is intentionally unsupported"
        )


@contextmanager
def _registry_lock(repo: GitRepository) -> Iterator[None]:
    """Serialize lane names, slot allocation, branches, and worktree creation."""

    repo.registry_dir.mkdir(parents=True, exist_ok=True)
    handle = (repo.registry_dir / ".registry.lock").open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _validate_branch(cwd: Path, branch: str) -> None:
    result = subprocess.run(
        ["git", "check-ref-format", "--branch", branch],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise LaneError(f"invalid lane branch {branch!r}: {result.stderr.strip()}")


def _executable_available(executable: str) -> bool:
    path = Path(executable).expanduser()
    if path.is_absolute() or len(path.parts) > 1:
        return path.is_file() and os.access(path, os.X_OK)
    return shutil.which(executable) is not None


def _registered_worktrees(cwd: Path) -> set[Path]:
    listing = _git(cwd, "worktree", "list", "--porcelain")
    return {
        Path(line.removeprefix("worktree ")).resolve()
        for line in listing.splitlines()
        if line.startswith("worktree ")
    }


def _manifest_path(repo: GitRepository, name: str) -> Path:
    return repo.registry_dir / f"{name}.json"


def _resolve_path(base: Path, value: Path | str) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise LaneError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout.strip()


def _git_optional(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _git_ok(cwd: Path, *args: str) -> bool:
    return (
        subprocess.run(
            ["git", *args],
            cwd=cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def command_text(command: Sequence[str]) -> str:
    """Return a shell-display form without changing execution semantics."""

    return shlex.join(command)
