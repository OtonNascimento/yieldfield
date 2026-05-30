"""TimeWindow value object — the [start, end) range reconciliation runs over (§13)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from yieldfield.domain.shared.errors import InvalidTimeWindowError
from yieldfield.domain.shared.time_window import TimeWindow


def _dt(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour, tzinfo=UTC)


class TestConstruction:
    def test_valid_window(self) -> None:
        window = TimeWindow(_dt(1), _dt(2))
        assert window.start == _dt(1)
        assert window.end == _dt(2)

    def test_rejects_end_before_start(self) -> None:
        with pytest.raises(InvalidTimeWindowError):
            TimeWindow(_dt(2), _dt(1))

    def test_allows_empty_window_start_equals_end(self) -> None:
        window = TimeWindow(_dt(1), _dt(1))
        assert window.duration == timedelta(0)

    def test_rejects_naive_datetimes(self) -> None:
        naive = datetime(2026, 1, 1)
        with pytest.raises(InvalidTimeWindowError):
            TimeWindow(naive, _dt(2))


class TestContainment:
    def test_contains_is_half_open(self) -> None:
        window = TimeWindow(_dt(1), _dt(3))
        assert window.contains(_dt(1))  # start is inclusive
        assert window.contains(_dt(2))
        assert not window.contains(_dt(3))  # end is exclusive
        assert not window.contains(_dt(4))

    def test_empty_window_contains_nothing(self) -> None:
        window = TimeWindow(_dt(1), _dt(1))
        assert not window.contains(_dt(1))


class TestOverlap:
    def test_overlapping_windows(self) -> None:
        assert TimeWindow(_dt(1), _dt(3)).overlaps(TimeWindow(_dt(2), _dt(4)))

    def test_adjacent_windows_do_not_overlap(self) -> None:
        # [1,2) and [2,3) share no instant.
        assert not TimeWindow(_dt(1), _dt(2)).overlaps(TimeWindow(_dt(2), _dt(3)))

    def test_disjoint_windows(self) -> None:
        assert not TimeWindow(_dt(1), _dt(2)).overlaps(TimeWindow(_dt(3), _dt(4)))


class TestDuration:
    def test_duration(self) -> None:
        assert TimeWindow(_dt(1), _dt(1, 6)).duration == timedelta(hours=6)
