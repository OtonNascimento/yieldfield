"""Reconciliation entity (§8) — aggregates findings from one run and totals the leakage."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from yieldfield.domain.findings.finding import Finding, FindingLineage
from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.findings.severity import Severity
from yieldfield.domain.reconciliation.reconciliation import Reconciliation
from yieldfield.domain.shared.errors import CurrencyMismatchError, InvalidEntityError
from yieldfield.domain.shared.ids import FindingId, ReconciliationId, TenantId
from yieldfield.domain.shared.money import Money
from yieldfield.domain.shared.time_window import TimeWindow


def _window() -> TimeWindow:
    return TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))


def _finding(fid: str, amount: str, currency: str = "USD") -> Finding:
    return Finding(
        id=FindingId(fid),
        tenant_id=TenantId("t_1"),
        reconciliation_id=ReconciliationId("r_1"),
        customer_id="cust_42",
        metric="api_calls",
        leakage_type=LeakageType.UNBILLED_USAGE,
        severity=Severity.MEDIUM,
        amount=Money.of(amount, currency),
        status=RecoveryStatus.NEW,
        lineage=FindingLineage(rule_version="reconciliation-v1"),
        explanation="unbilled usage",
    )


def _reconciliation(*findings: Finding, currency: str = "USD") -> Reconciliation:
    return Reconciliation(
        id=ReconciliationId("r_1"),
        tenant_id=TenantId("t_1"),
        window=_window(),
        currency=currency,
        executed_at=datetime(2026, 1, 1, tzinfo=UTC),
        rule_version="reconciliation-v1",
        findings=findings,
    )


class TestReconciliation:
    def test_total_leakage_sums_findings(self) -> None:
        recon = _reconciliation(_finding("f_1", "10.00"), _finding("f_2", "5.50"))
        assert recon.total_leakage() == Money.of("15.50", "USD")
        assert recon.finding_count == 2

    def test_empty_reconciliation_has_zero_leakage(self) -> None:
        recon = _reconciliation()
        assert recon.total_leakage() == Money.zero("USD")
        assert recon.finding_count == 0

    def test_currency_mismatch_between_findings_is_rejected(self) -> None:
        recon = _reconciliation(_finding("f_1", "10.00", "USD"), _finding("f_2", "5.00", "EUR"))
        with pytest.raises(CurrencyMismatchError):
            recon.total_leakage()


def test_reconciliation_carries_audit_fields() -> None:
    executed = datetime(2026, 6, 1, tzinfo=UTC)
    recon = Reconciliation(
        id=ReconciliationId("rec_1"),
        tenant_id=TenantId("t_1"),
        window=_window(),
        currency="USD",
        executed_at=executed,
        rule_version="reconciliation-v1",
    )
    assert recon.executed_at == executed
    assert recon.rule_version == "reconciliation-v1"
    assert recon.finding_count == 0


def test_reconciliation_rejects_naive_executed_at() -> None:
    with pytest.raises(InvalidEntityError):
        Reconciliation(
            id=ReconciliationId("rec_1"),
            tenant_id=TenantId("t_1"),
            window=_window(),
            currency="USD",
            executed_at=datetime(2026, 6, 1),  # naive — no tzinfo
            rule_version="reconciliation-v1",
        )
