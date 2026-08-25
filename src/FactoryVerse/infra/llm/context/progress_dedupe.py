"""Dedupe verbatim-repeated Task Progress blocks before they enter LLM context.

Background: the orchestrator injects a task
verification progress block as a user message after every tool batch. In the
2026-06-10_23-35-34 engine_unit run that block was appended 163 times but had
only 35 distinct contents — 128 verbatim consecutive repeats accumulated in the
message history and were re-sent on every subsequent LLM call.

Policy implemented here:
- Emit the FULL block whenever its content CHANGED since the last full emission.
  New information is never dropped — only byte-identical repeats are collapsed.
- When unchanged, emit a one-line pointer naming the turn of the last full block,
  so the agent knows where the authoritative block lives in its context.
- Periodic refresh: after ``refresh_every`` consecutive pointers, re-emit the full
  block once even if unchanged (guards against the full block being lost to
  context compression of old turns).

This class is pure (no I/O) so the emission policy is unit-testable.
"""

from typing import Optional

__all__ = ["ProgressDeduper"]


class ProgressDeduper:
    """Change-based deduplication for repeated progress blocks.

    Usage:
        deduper = ProgressDeduper(refresh_every=10)
        rendered = deduper.render(progress_block, turn=turn_number)
        # append `rendered` to the LLM message history
    """

    def __init__(self, refresh_every: int = 10):
        """
        Args:
            refresh_every: After this many consecutive pointer emissions, the full
                block is re-emitted even if unchanged. Must be >= 1.
        """
        if refresh_every < 1:
            raise ValueError(f"refresh_every must be >= 1, got {refresh_every}")
        self._refresh_every = refresh_every
        self._last_full_content: Optional[str] = None
        self._last_full_turn: Optional[int] = None
        self._pointers_since_full = 0

    def render(self, content: str, turn: int) -> str:
        """Render a progress block for injection into the message history.

        Returns the full ``content`` when it differs from the last full emission
        (or when a periodic refresh is due), otherwise a one-line pointer to the
        turn that carries the last full block.

        Args:
            content: The freshly formatted progress block.
            turn: Current turn number (used in the pointer text).

        Returns:
            Either ``content`` verbatim, or a one-line "unchanged" pointer.
        """
        changed = content != self._last_full_content
        refresh_due = self._pointers_since_full >= self._refresh_every

        if changed or refresh_due:
            self._last_full_content = content
            self._last_full_turn = turn
            self._pointers_since_full = 0
            return content

        self._pointers_since_full += 1
        return (
            f"Task Progress unchanged since turn {self._last_full_turn} "
            "(see the earlier Task Progress block)."
        )

    @property
    def last_full_turn(self) -> Optional[int]:
        """Turn number of the most recent full emission (None before first render)."""
        return self._last_full_turn
