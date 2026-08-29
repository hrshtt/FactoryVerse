"""Raw reader over the electric-network sample file.

The snapshot mod appends one JSON line per 300-tick window to
``script-output/factoryverse/snapshots/power_networks.jsonl``
(``fv_snapshot/game_state/Power.lua`` ``_on_nth_tick_power_networks_sample``):
``{"tick": T, "networks": [...]}`` — always written, even with zero networks,
so the file is a bounded heartbeat log. Each network carries its engine
``network_id`` (ephemeral — renumbers on merge/split), its anchor pole (the
durable reference), pole/member counts, production/consumption/storage and
the per-prototype breakdowns.

Power flow is polled simulation state with no event backing, so it does not
belong in the map model (Constitution §10). This reader is the lawful home:
the sample file is read on demand and every answer says which sample it came
from (``source``; §11).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class PowerSample:
    """One sampled block: every live electric network at ``tick``."""

    tick: int
    networks: List[Dict[str, Any]] = field(default_factory=list)
    path: Optional[Path] = None

    @property
    def source(self) -> str:
        return f"power_dump:{self.tick}"

    def network(self, network_id: Optional[int]) -> Optional[Dict[str, Any]]:
        if network_id is None:
            return None
        for net in self.networks:
            if net.get("network_id") == network_id:
                return net
        return None


def parse_samples(lines: Iterable[str], path: Optional[Path] = None) -> List[PowerSample]:
    """Parse the file's lines; a torn last line (mid-append) is skipped."""
    out: List[PowerSample] = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict) or "tick" not in obj:
            continue
        networks = obj.get("networks") or []
        if not isinstance(networks, list):
            networks = []
        out.append(PowerSample(tick=int(obj["tick"]), networks=networks, path=path))
    return out


class PowerDumpReader:
    """Reads ``power_networks.jsonl`` on demand."""

    def __init__(self, path: Path):
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def samples(self) -> List[PowerSample]:
        if not self._path.is_file():
            return []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                return parse_samples(f, path=self._path)
        except OSError:
            return []

    def available_ticks(self) -> List[int]:
        return sorted(s.tick for s in self.samples())

    def newest(self) -> Optional[PowerSample]:
        samples = self.samples()
        return max(samples, key=lambda s: s.tick) if samples else None

    def at_or_before(self, tick: int) -> Optional[PowerSample]:
        candidates = [s for s in self.samples() if s.tick <= tick]
        return max(candidates, key=lambda s: s.tick) if candidates else None


__all__ = ["PowerDumpReader", "PowerSample", "parse_samples"]
