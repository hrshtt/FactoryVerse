"""Filesystem-backed campaign state with atomic writes and exclusive leases."""

from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from .models import (
    SCHEMA_VERSION,
    CampaignStatus,
    CheckpointRecord,
    RuntimeSessionRecord,
    utc_now,
)


CAMPAIGN_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$")


class CampaignNotFoundError(FileNotFoundError):
    pass


class CampaignStateError(RuntimeError):
    pass


class CampaignLeaseError(RuntimeError):
    pass


@dataclass(frozen=True)
class CampaignPaths:
    root: Path

    @property
    def manifest(self) -> Path:
        return self.root / "manifest.json"

    @property
    def state(self) -> Path:
        return self.root / "state.json"

    @property
    def sessions(self) -> Path:
        return self.root / "sessions"

    @property
    def checkpoints(self) -> Path:
        return self.root / "checkpoints"

    @property
    def checkpoint_index(self) -> Path:
        return self.checkpoints / "index.json"

    @property
    def protocol_log(self) -> Path:
        return self.root / "transcript" / "runtime-protocol.jsonl"

    @property
    def scores(self) -> Path:
        return self.root / "scores.jsonl"

    @property
    def result(self) -> Path:
        return self.root / "result.json"

    @property
    def server_output(self) -> Path:
        return self.root / "server-output"

    @property
    def server_config(self) -> Path:
        return self.root / "server-config"

    @property
    def server_mods(self) -> Path:
        """Campaign-private Factorio mod directory.

        The dedicated server must never share the desktop client's mutable
        mod directory. Factorio's client synchronization and data-dump flows
        both rewrite ``mod-list.json``.
        """
        return self.root / "server-mods"

    @property
    def compose(self) -> Path:
        return self.root / "server-compose.yml"

    @property
    def lease(self) -> Path:
        return self.root / ".runtime.lease"


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class CampaignLease:
    """Process-held, non-blocking exclusive lease for one campaign runtime."""

    def __init__(self, path: Path, session_id: str):
        self.path = Path(path)
        self.session_id = session_id
        self._handle = None

    def acquire(self) -> "CampaignLease":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.seek(0)
            owner = handle.read().strip() or "unknown owner"
            handle.close()
            raise CampaignLeaseError(
                f"Campaign runtime is already leased ({owner})"
            ) from exc

        handle.seek(0)
        handle.truncate()
        json.dump(
            {
                "pid": os.getpid(),
                "session_id": self.session_id,
                "acquired_at": utc_now(),
            },
            handle,
        )
        handle.flush()
        os.fsync(handle.fileno())
        self._handle = handle
        return self

    def release(self) -> None:
        if self._handle is None:
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None

    def __enter__(self) -> "CampaignLease":
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class FreeplayCampaignStore:
    """Owns durable, actor-independent state for one freeplay campaign."""

    def __init__(self, campaigns_root: Path, campaign_id: str):
        if not CAMPAIGN_ID_RE.fullmatch(campaign_id):
            raise ValueError(
                "campaign_id must be 1-80 letters, numbers, '.', '_' or '-', "
                "and must start with a letter or number"
            )
        self.campaign_id = campaign_id
        self.paths = CampaignPaths(Path(campaigns_root) / campaign_id)

    @property
    def exists(self) -> bool:
        return self.paths.manifest.exists()

    def create(self, manifest: Dict[str, Any]) -> Dict[str, Any]:
        if self.paths.root.exists() and any(self.paths.root.iterdir()):
            raise FileExistsError(f"Campaign already exists: {self.campaign_id}")

        for directory in (
            self.paths.sessions,
            self.paths.checkpoints,
            self.paths.protocol_log.parent,
            self.paths.server_output,
            self.paths.server_config,
            self.paths.server_mods,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        document = {
            "schema_version": SCHEMA_VERSION,
            "campaign_id": self.campaign_id,
            "created_at": utc_now(),
            **manifest,
        }
        _atomic_json(self.paths.manifest, document)
        _atomic_json(
            self.paths.state,
            {
                "schema_version": SCHEMA_VERSION,
                "campaign_id": self.campaign_id,
                "status": CampaignStatus.DEFINED.value,
                "active_session_id": None,
                "latest_checkpoint_id": None,
                "updated_at": utc_now(),
                "invalid_reason": None,
            },
        )
        _atomic_json(
            self.paths.checkpoint_index,
            {"schema_version": SCHEMA_VERSION, "checkpoints": []},
        )
        return document

    def require(self) -> None:
        if not self.exists:
            raise CampaignNotFoundError(
                f"Freeplay campaign does not exist: {self.campaign_id}"
            )

    def manifest(self) -> Dict[str, Any]:
        self.require()
        return _load_json(self.paths.manifest)

    def state(self) -> Dict[str, Any]:
        self.require()
        return _load_json(self.paths.state)

    def transition(
        self,
        status: CampaignStatus,
        *,
        expected: Optional[set[CampaignStatus]] = None,
        **updates: Any,
    ) -> Dict[str, Any]:
        state = self.state()
        current = CampaignStatus(state["status"])
        if expected is not None and current not in expected:
            expected_values = ", ".join(sorted(item.value for item in expected))
            raise CampaignStateError(
                f"Cannot transition campaign from {current.value} to {status.value}; "
                f"expected one of: {expected_values}"
            )
        state.update(updates)
        state["status"] = status.value
        state["updated_at"] = utc_now()
        _atomic_json(self.paths.state, state)
        return state

    def start_session(self, record: RuntimeSessionRecord) -> Path:
        path = self.paths.sessions / record.session_id / "session.json"
        _atomic_json(path, record.to_dict())
        return path

    def update_session(self, session_id: str, **updates: Any) -> Dict[str, Any]:
        path = self.paths.sessions / session_id / "session.json"
        if not path.exists():
            raise CampaignStateError(f"Unknown runtime session: {session_id}")
        data = _load_json(path)
        data.update(updates)
        _atomic_json(path, data)
        return data

    def checkpoint_records(self) -> list[Dict[str, Any]]:
        self.require()
        return _load_json(self.paths.checkpoint_index)["checkpoints"]

    def resolve_checkpoint(self, checkpoint_id: str) -> Dict[str, Any]:
        records = self.checkpoint_records()
        if checkpoint_id == "latest":
            if not records:
                raise CampaignStateError("Campaign has no checkpoints to resume")
            return records[-1]
        for record in records:
            if record["checkpoint_id"] == checkpoint_id:
                return record
        raise CampaignStateError(f"Unknown checkpoint: {checkpoint_id}")

    def add_checkpoint(self, record: CheckpointRecord) -> None:
        index = _load_json(self.paths.checkpoint_index)
        existing = {item["checkpoint_id"] for item in index["checkpoints"]}
        if record.checkpoint_id in existing:
            raise CampaignStateError(
                f"Checkpoint already exists: {record.checkpoint_id}"
            )
        index["checkpoints"].append(record.to_dict())
        _atomic_json(self.paths.checkpoint_index, index)

        state = self.state()
        state["latest_checkpoint_id"] = record.checkpoint_id
        state["updated_at"] = utc_now()
        _atomic_json(self.paths.state, state)

    def append_protocol(self, event: Dict[str, Any]) -> None:
        self.paths.protocol_log.parent.mkdir(parents=True, exist_ok=True)
        with self.paths.protocol_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, default=str) + "\n")

    def append_score(self, score: Dict[str, Any]) -> None:
        with self.paths.scores.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(score, sort_keys=True, default=str) + "\n")

    def write_result(self, result: Dict[str, Any]) -> None:
        _atomic_json(self.paths.result, result)

    def lease(self, session_id: str) -> CampaignLease:
        return CampaignLease(self.paths.lease, session_id)

    def iter_sessions(self) -> Iterator[Dict[str, Any]]:
        for path in sorted(self.paths.sessions.glob("*/session.json")):
            yield _load_json(path)
