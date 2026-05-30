"""Finding entity + lineage (§4 CORE, §6.5 — explainable, auditable money)."""

from __future__ import annotations

import pytest

from yieldfield.domain.findings.finding import Finding, FindingLineage
from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.findings.severity import Severity
from yieldfield.domain.shared.errors import InvalidEntityError
from yieldfield.domain.shared.ids import (
    FindingId,
    InvoiceLineItemId,
    ReconciliationId,
    TenantId,
    UsageEventId,
)
from yieldfield.domain.shared.money import Money


def _lineage(**overrides: object) -> FindingLineage:
    defaults: dict[str, object] = {
        "rule_version": "reconciliation-v1",
        "usage_event_ids": (UsageEventId("u_1"),),
        "invoice_line_item_id": None,
        "model_run_id": None,
    }
    defaults.update(overrides)
    return FindingLineage(**defaults)  # type: ignore[arg-type]


def _finding(**overrides: object) -> Finding:
    defaults: dict[str, object] = {
        "id": FindingId("f_1"),
        "tenant_id": TenantId("t_1"),
        "reconciliation_id": ReconciliationId("r_1"),
        "customer_id": "cust_42",
        "metric": "api_calls",
        "leakage_type": LeakageType.UNBILLED_USAGE,
        "severity": Severity.HIGH,
        "amount": Money.of("10.00", "USD"),
        "status": RecoveryStatus.NEW,
        "lineage": _lineage(),
        "explanation": "100 api_calls for cust_42 were not billed.",
    }
    defaults.update(overrides)
    return Finding(**defaults)  # type: ignore[arg-type]


class TestFindingInvariants:
    def test_valid_finding(self) -> None:
        finding = _finding()
        assert finding.amount == Money.of("10.00", "USD")
        assert finding.status is RecoveryStatus.NEW

    def test_amount_must_be_positive(self) -> None:
        # A finding represents recoverable dollars; zero or negative is not a finding.
        with pytest.raises(InvalidEntityError):
            _finding(amount=Money.zero("USD"))
        with pytest.raises(InvalidEntityError):
            _finding(amount=Money.of("-1.00", "USD"))

    def test_explanation_required(self) -> None:
        # §2: no unexplained figure reaches the user.
        with pytest.raises(InvalidEntityError):
            _finding(explanation="  ")


class TestFindingLineage:
    def test_rule_version_required(self) -> None:
        with pytest.raises(InvalidEntityError):
            _lineage(rule_version="")

    def test_carries_source_inputs(self) -> None:
        lineage = _lineage(
            usage_event_ids=(UsageEventId("u_1"), UsageEventId("u_2")),
            invoice_line_item_id=InvoiceLineItemId("li_9"),
        )
        assert lineage.usage_event_ids == (UsageEventId("u_1"), UsageEventId("u_2"))
        assert lineage.invoice_line_item_id == InvoiceLineItemId("li_9")
