"""TimeWindow value object — a timezone-aware, half-open [start, end) interval.

Reconciliation and ingestion operate over explicit windows (§13). Half-open semantics
keep adjacent windows non-overlapping, so a usage event falls into exactly one window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from yieldfield.domain.shared.errors import InvalidTimeWindowError


@dataclass(frozen=True, slots=True)
class TimeWindow:
    """A half-open time interval [start, end) with timezone-aware bounds."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise InvalidTimeWindowError("TimeWindow bounds must be timezone-aware.")
        if self.end < self.start:
            raise InvalidTimeWindowError(f"end ({self.end}) is before start ({self.start}).")

    def contains(self, moment: datetime) -> bool:
        """True if `moment` is in [start, end)."""
        return self.start <= moment < self.end

    def overlaps(self, other: TimeWindow) -> bool:
        """True if the two windows share at least one instant."""
        return self.start < other.end and other.start < self.end

    @property
    def duration(self) -> timedelta:
        return self.end - self.start
