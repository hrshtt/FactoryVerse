"""The Python mirror of an agent's `turn` stream.

NOTIFICATIONS_PRIMITIVE_DEFERRED.md, "The Python mirror": per port, hold
``(epoch, seq)``. At attach, ask Lua (``stream_state`` over RCON) and adopt
it — never guess a baseline from disk. Accept a datagram iff the epoch
matches and the sequence is next. On a gap, read the stream file from
``seq+1`` and fill; every filled item is marked ``filled_from_file``. On an
epoch change, reset. A datagram that is ``in_file`` only (oversize) is
always read from the file.

Two classes, split so the rules are testable without a socket:

* :class:`TurnStreamCursor` — the acceptance rules and the file fill. Pure.
* :class:`TurnStreamListener` — a socket thread that feeds the cursor and
  delivers accepted envelopes into the listener's notification queue in the
  shape :class:`~FactoryVerse.game.agent.event_stream.GameEvent` reads.
"""

from __future__ import annotations

import json
import logging
import queue
import socket
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

STREAM_NAME = "turn"


@dataclass
class Accepted:
    """One envelope the cursor let through, in order."""

    envelope: Dict[str, Any]
    filled_from_file: bool = False


@dataclass
class TurnStreamCursor:
    """Acceptance rules for one stream, with a file fill for gaps.

    ``file_path`` is the stream's JSONL file (one envelope per line, the
    same bytes the datagram carried). It may be ``None`` in tests; then a gap
    is announced (``gaps``) and skipped rather than filled.
    """

    epoch: int = 0
    seq: int = 0
    file_path: Optional[Path] = None
    # Every gap that could not be filled from the file: (epoch, first_missing, last_missing)
    gaps: List[tuple] = field(default_factory=list)
    # Counters for probes and tests
    accepted_count: int = 0
    filled_count: int = 0
    dropped_stale: int = 0
    epoch_resets: int = 0

    def adopt(self, state: Dict[str, Any]) -> None:
        """Adopt Lua's ``{epoch, seq}`` at attach (or after a gap)."""
        self.epoch = int(state.get("epoch", 0))
        self.seq = int(state.get("seq", 0))

    def offer(self, envelope: Dict[str, Any]) -> List[Accepted]:
        """Offer one datagram. Returns the envelopes to deliver, in order.

        The list is empty for a stale/duplicate datagram, one item for the
        expected next, and ``gap + 1`` items when a gap was filled from the
        file. An oversize ``in_file`` envelope is always resolved from the
        file (it carries no data).
        """
        try:
            epoch = int(envelope["epoch"])
            seq = int(envelope["seq"])
        except (KeyError, TypeError, ValueError):
            logger.warning("turn stream: envelope without epoch/seq dropped: %r", envelope)
            return []

        if epoch != self.epoch:
            if epoch > self.epoch:
                # A new epoch means the file was truncated and the counter
                # reset. Adopt it; anything before is gone by construction.
                logger.info("turn stream: epoch %d → %d, resetting", self.epoch, epoch)
                self.epoch = epoch
                self.seq = 0
                self.epoch_resets += 1
            else:
                self.dropped_stale += 1
                return []

        if seq <= self.seq:
            self.dropped_stale += 1
            return []

        out: List[Accepted] = []
        if seq > self.seq + 1:
            # Gap: (self.seq+1 .. seq-1) are missing. Fill from the file.
            filled = self._read_file_range(epoch, self.seq + 1, seq - 1)
            have = {int(e["seq"]): e for e in filled}
            for missing in range(self.seq + 1, seq):
                if missing in have:
                    out.append(Accepted(have[missing], filled_from_file=True))
                    self.filled_count += 1
                else:
                    # Announce, never hide. Constitution §21: no gaps unannounced.
                    self._record_gap(epoch, missing)
        if envelope.get("in_file"):
            fetched = self._read_file_range(epoch, seq, seq)
            if fetched:
                out.append(Accepted(fetched[0], filled_from_file=True))
                self.filled_count += 1
            else:
                self._record_gap(epoch, seq)
        else:
            out.append(Accepted(envelope, filled_from_file=False))
        self.seq = seq
        self.accepted_count += len(out)
        return out

    def _record_gap(self, epoch: int, seq: int) -> None:
        if self.gaps and self.gaps[-1][0] == epoch and self.gaps[-1][2] == seq - 1:
            self.gaps[-1] = (epoch, self.gaps[-1][1], seq)
        else:
            self.gaps.append((epoch, seq, seq))
        logger.warning("turn stream: epoch %d seq %d lost and not in file", epoch, seq)

    def _read_file_range(self, epoch: int, first: int, last: int) -> List[Dict[str, Any]]:
        if self.file_path is None:
            return []
        try:
            text = self.file_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError as exc:  # pragma: no cover - platform specific
            logger.warning("turn stream: cannot read %s: %s", self.file_path, exc)
            return []
        found: List[Dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                if int(item.get("epoch", -1)) != epoch:
                    continue
                s = int(item["seq"])
            except (TypeError, ValueError, KeyError):
                continue
            if first <= s <= last:
                found.append(item)
        found.sort(key=lambda e: int(e["seq"]))
        return found


def envelope_to_notification(envelope: Dict[str, Any], filled_from_file: bool) -> Dict[str, Any]:
    """Reshape a turn-stream envelope into the payload ``GameEvent.from_payload`` reads.

    The envelope is ``{epoch, seq, tick, event_type, data}`` with ``agent_id``
    inside ``data``. The typed layer keys on ``notification_type``.
    """
    data = dict(envelope.get("data") or {})
    return {
        "event_type": "notification",
        "notification_type": envelope.get("event_type", "unknown"),
        "agent_id": data.get("agent_id", 0),
        "tick": envelope.get("tick", 0),
        "data": data,
        "epoch": envelope.get("epoch"),
        "seq": envelope.get("seq"),
        "source": STREAM_NAME,
        "filled_from_file": filled_from_file,
    }


class TurnStreamListener:
    """Bind an agent's turn port, run the cursor, deliver into a queue.

    ``state_source`` is called at :meth:`start` (and by :meth:`resync`) and
    must return Lua's ``{epoch, seq, ...}`` — normally a closure over the
    RCON ``stream_state`` call. ``deliver`` receives each accepted
    notification-shaped payload in order.
    """

    def __init__(
        self,
        port: int,
        file_path: Optional[Path],
        state_source: Callable[[], Dict[str, Any]],
        deliver: Callable[[Dict[str, Any]], None],
        host: str = "0.0.0.0",
    ):
        self.port = port
        self.host = host
        self.cursor = TurnStreamCursor(file_path=file_path)
        self._state_source = state_source
        self._deliver = deliver
        self.sock: Optional[socket.socket] = None
        self.thread: Optional[threading.Thread] = None
        self.running = False
        self._lock = threading.Lock()

    def resync(self) -> Dict[str, Any]:
        state = self._state_source()
        with self._lock:
            self.cursor.adopt(state)
        logger.info(
            "turn stream: adopted epoch=%s seq=%s from Lua on port %d",
            state.get("epoch"), state.get("seq"), self.port,
        )
        return state

    def start(self) -> None:
        self.resync()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind((self.host, self.port))
        except OSError as exc:
            self.sock.close()
            self.sock = None
            raise RuntimeError(f"turn stream: cannot bind {self.host}:{self.port}: {exc}")
        self.sock.settimeout(0.5)
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True, name=f"turn-stream-{self.port}")
        self.thread.start()
        logger.info("✅ turn stream listener on %s:%d", self.host, self.port)

    def stop(self) -> None:
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
            self.thread = None
        if self.sock:
            self.sock.close()
            self.sock = None

    def feed(self, raw: bytes) -> int:
        """Feed one datagram's bytes (also used by tests). Returns items delivered."""
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("turn stream: undecodable datagram dropped: %s", exc)
            return 0
        with self._lock:
            accepted = self.cursor.offer(envelope)
        for item in accepted:
            self._deliver(envelope_to_notification(item.envelope, item.filled_from_file))
        return len(accepted)

    def _loop(self) -> None:
        while self.running and self.sock:
            try:
                data, _addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                if self.running:
                    logger.exception("turn stream: socket error")
                continue
            try:
                self.feed(data)
            except Exception:  # pragma: no cover - defensive
                logger.exception("turn stream: error handling datagram")


def queue_deliverer(q: "queue.Queue[Dict[str, Any]]") -> Callable[[Dict[str, Any]], None]:
    """Deliver into the AsyncActionListener's notification queue."""

    def _put(payload: Dict[str, Any]) -> None:
        q.put(payload)

    return _put


__all__ = [
    "Accepted",
    "TurnStreamCursor",
    "TurnStreamListener",
    "envelope_to_notification",
    "queue_deliverer",
    "STREAM_NAME",
]
