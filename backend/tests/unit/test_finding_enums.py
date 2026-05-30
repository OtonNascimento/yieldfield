"""Finding enums (§8) — severity aligned 1:1 to the design-system status palette (§5A)."""

from __future__ import annotations

from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.findings.severity import Severity


class TestSeverity:
    def test_values_are_exactly_the_status_palette(self) -> None:
        # §8: severity uses exactly the five design-system status tokens as values,
        # so a backend severity maps to a design-system status with no translation.
        assert {s.value for s in Severity} == {"critical", "high", "medium", "low", "good"}

    def test_is_a_string_enum(self) -> None:
        assert isinstance(Severity.CRITICAL, str)
        assert Severity.CRITICAL.value == "critical"
        assert str(Severity.GOOD) == "good"

    def test_rank_orders_from_good_up_to_critical(self) -> None:
        ordered = sorted(Severity, key=lambda s: s.rank)
        assert [s.value for s in ordered] == ["good", "low", "medium", "high", "critical"]


class TestLeakageType:
    def test_values(self) -> None:
        assert {t.value for t in LeakageType} == {
            "unbilled_usage",
            "misrated_line_item",
            "unaudited_adjustment",
        }


class TestRecoveryStatus:
    def test_lifecycle_values(self) -> None:
        assert {s.value for s in RecoveryStatus} == {
            "new",
            "reviewed",
            "confirmed",
            "recovered",
            "dismissed",
        }
