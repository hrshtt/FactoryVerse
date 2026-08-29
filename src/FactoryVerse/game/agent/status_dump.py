"""Raw reader over the entity-status dump files.

The snapshot mod writes a full, tickstamped status block to
``script-output/factoryverse/status/status-<tick>.jsonl`` on a fixed cadence
and keeps a rolling window of them (``fv_snapshot/game_state/Entities.lua``
``dump_status_to_disk``; ``utils/snapshot.lua`` ``MAX_STATUS_DUMP_FILES``).
Each file is one meta line ``{"meta": true, "tick": T, "count": N}`` followed
by one ``{"name", "status", "x", "y"}`` record per entity that has a status.

Entity status has no event backing — nothing fires when a machine runs short
of ingredients — so it does not belong in the map model (Constitution §10).
This reader is the lawful home: the dump layer is read on demand, and every
answer says which block it came from (``source``; Constitution §11).

Two reads fall out with no new machinery (API plan §4.3):

- ``current()``  — the newest block grouped by status: *what is wrong now*.
- ``changed(since_tick)`` — two blocks diffed: *what changed*. This is the
  read the turn report's Status section wants and the one the old database
  reducer computed away.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

_FILE_RE = re.compile(r"^status-(\d+)\.jsonl$")

EntityKey = Tuple[str, float, float]


@dataclass(frozen=True)
class StatusBlock:
    """One full dump: the engine's status truth at ``tick``."""

    tick: int
    records: Dict[EntityKey, str]  # (name, x, y) -> status name
    path: Optional[Path] = None

    @property
    def source(self) -> str:
        return f"status_dump:{self.tick}"

    def grouped(self) -> Dict[str, List[EntityKey]]:
        out: Dict[str, List[EntityKey]] = {}
        for key, status in self.records.items():
            out.setdefault(status, []).append(key)
        for keys in out.values():
            keys.sort()
        return out


@dataclass
class StatusTransition:
    entity: EntityKey
    before: Optional[str]  # None: the entity was not in the earlier block
    after: Optional[str]  # None: the entity is gone from the later block


@dataclass
class StatusChange:
    """The diff between two blocks, grouped for a small report."""

    from_tick: Optional[int]
    to_tick: Optional[int]
    transitions: List[StatusTransition] = field(default_factory=list)

    @property
    def source(self) -> str:
        return f"status_dump:{self.from_tick}->{self.to_tick}"

    def grouped(self) -> Dict[str, List[StatusTransition]]:
        """Group by ``before -> after`` label; appeared/vanished get their own."""
        out: Dict[str, List[StatusTransition]] = {}
        for t in self.transitions:
            if t.before is None:
                label = f"appeared as {t.after}"
            elif t.after is None:
                label = f"gone (was {t.before})"
            else:
                label = f"{t.before} -> {t.after}"
            out.setdefault(label, []).append(t)
        return out


def parse_block(lines: Iterable[str], path: Optional[Path] = None) -> Optional[StatusBlock]:
    """Parse one dump file's lines. Returns None if there is no meta line."""
    tick: Optional[int] = None
    records: Dict[EntityKey, str] = {}
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if obj.get("meta"):
            tick = int(obj.get("tick", 0))
            continue
        name = obj.get("name")
        status = obj.get("status")
        if name is None or status is None:
            continue
        try:
            key = (str(name), float(obj.get("x")), float(obj.get("y")))
        except (TypeError, ValueError):
            continue
        records[key] = str(status)
    if tick is None:
        return None
    return StatusBlock(tick=tick, records=records, path=path)


class StatusDumpReader:
    """Reads the rolling window of status dumps under one directory."""

    def __init__(self, status_dir: Path):
        self._dir = Path(status_dir)

    @property
    def directory(self) -> Path:
        return self._dir

    def available_ticks(self) -> List[int]:
        if not self._dir.is_dir():
            return []
        ticks = []
        for p in self._dir.iterdir():
            m = _FILE_RE.match(p.name)
            if m:
                ticks.append(int(m.group(1)))
        return sorted(ticks)

    def block(self, tick: int) -> Optional[StatusBlock]:
        path = self._dir / f"status-{tick}.jsonl"
        if not path.is_file():
            return None
        try:
            with open(path, "r") as f:
                return parse_block(f, path=path)
        except OSError:
            return None

    def newest(self) -> Optional[StatusBlock]:
        # Walk from the newest down: a file mid-write can be incomplete.
        for tick in reversed(self.available_ticks()):
            block = self.block(tick)
            if block is not None:
                return block
        return None

    def newest_at_or_before(self, tick: int) -> Optional[StatusBlock]:
        for t in reversed([t for t in self.available_ticks() if t <= tick]):
            block = self.block(t)
            if block is not None:
                return block
        return None

    def current(self) -> Optional[StatusBlock]:
        """What is wrong right now — the newest block."""
        return self.newest()

    def changed(self, since_tick: int, until: Optional[StatusBlock] = None) -> StatusChange:
        """Transitions between the newest block at-or-before ``since_tick`` and
        the newest block (or ``until``).

        If no block exists at or before ``since_tick`` the earliest block is
        used and the change says so through ``from_tick``; if there is no
        block at all the result is empty with both ticks None.
        """
        later = until or self.newest()
        if later is None:
            return StatusChange(from_tick=None, to_tick=None)
        earlier = self.newest_at_or_before(since_tick)
        if earlier is None:
            ticks = self.available_ticks()
            earlier = self.block(ticks[0]) if ticks else None
        if earlier is None or earlier.tick == later.tick:
            return StatusChange(from_tick=earlier.tick if earlier else None, to_tick=later.tick)
        return diff_blocks(earlier, later)


def diff_blocks(earlier: StatusBlock, later: StatusBlock) -> StatusChange:
    change = StatusChange(from_tick=earlier.tick, to_tick=later.tick)
    keys = set(earlier.records) | set(later.records)
    for key in sorted(keys):
        before = earlier.records.get(key)
        after = later.records.get(key)
        if before != after:
            change.transitions.append(StatusTransition(entity=key, before=before, after=after))
    return change
