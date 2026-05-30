"""Finding severity (§8) — values are the design-system status palette (§5A).

These five strings are the shared vocabulary between domain and design. The backend
emits them verbatim; the frontend's `design-system/status/` maps them to color tokens
with no translation table. `rank` orders them for sorting/aggregation only.
"""

from __future__ import annotations

from enum import StrEnum


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    GOOD = "good"

    @property
    def rank(self) -> int:
        """0 (good) … 4 (critical). Higher means more severe."""
        return _SEVERITY_RANK[self]


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.GOOD: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}
