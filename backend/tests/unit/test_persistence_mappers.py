"""Mapper round-trips and the fail-loud precision guard (§7)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from yieldfield.domain.billing.invoice import Invoice, InvoiceLineItem
from yieldfield.domain.billing.plan import Plan
from yieldfield.domain.findings.finding import Finding, FindingLineage
from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.findings.severity import Severity
from yieldfield.domain.reconciliation.reconciliation import Reconciliation
from yieldfield.domain.shared.ids import (
    FindingId,
    InvoiceId,
    InvoiceLineItemId,
    PlanId,
    ReconciliationId,
    TenantId,
    UsageEventId,
)
from yieldfield.domain.shared.money import Money
from yieldfield.domain.shared.time_window import TimeWindow
from yieldfield.infrastructure.persistence import mappers
from yieldfield.infrastructure.persistence.errors import PersistenceError

_WINDOW = TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))


def test_plan_round_trip_preserves_money() -> None:
    plan = Plan(
        id=PlanId("pl_1"),
        tenant_id=TenantId("t_1"),
        name="API calls",
        metric="api_call",
        unit_price=Money.of("0.0000004", "USD"),
    )
    restored = mappers.to_plan(mappers.plan_row(plan))
    assert restored == plan


def test_invoice_round_trip_preserves_line_items() -> None:
    invoice = Invoice(
        id=InvoiceId("in_1"),
        tenant_id=TenantId("t_1"),
        customer_id="cus_1",
        period=_WINDOW,
        currency="USD",
        line_items=(
            InvoiceLineItem(
                id=InvoiceLineItemId("il_1"),
                metric="api_call",
                quantity=Decimal("1000"),
                amount=Money.of("4.00", "USD"),
            ),
        ),
    )
    restored = mappers.to_invoice(mappers.invoice_row(invoice))
    assert restored == invoice


def test_reconciliation_round_trip_preserves_findings_and_lineage() -> None:
    finding = Finding(
        id=FindingId("fd_1"),
        tenant_id=TenantId("t_1"),
        reconciliation_id=ReconciliationId("rc_1"),
        customer_id="cus_1",
        metric="api_call",
        leakage_type=LeakageType.UNBILLED_USAGE,
        severity=Severity.HIGH,
        amount=Money.of("123.45", "USD"),
        status=RecoveryStatus.NEW,
        lineage=FindingLineage(
            rule_version="reconciliation-v1",
            usage_event_ids=(UsageEventId("ue_1"), UsageEventId("ue_2")),
        ),
        explanation="500 api_call for cus_1 were not billed.",
    )
    recon = Reconciliation(
        id=ReconciliationId("rc_1"),
        tenant_id=TenantId("t_1"),
        window=_WINDOW,
        currency="USD",
        executed_at=datetime(2026, 1, 1, tzinfo=UTC),
        rule_version="reconciliation-v1",
        findings=(finding,),
    )
    restored = mappers.to_reconciliation(mappers.reconciliation_row(recon))
    assert restored == recon
    assert restored.findings[0].lineage.usage_event_ids == ("ue_1", "ue_2")


def test_precision_guard_rejects_too_many_fractional_digits() -> None:
    # 13 fractional digits exceeds NUMERIC(38,12): must fail loudly, not round (§7).
    plan = Plan(
        id=PlanId("pl_2"),
        tenant_id=TenantId("t_1"),
        name="too precise",
        metric="m",
        unit_price=Money(Decimal("0.0000000000001"), "USD"),
    )
    with pytest.raises(PersistenceError, match="precision"):
        mappers.plan_row(plan)


def test_connector_row_round_trip() -> None:
    from yieldfield.domain.billing.connector import (
        Connector,
        ConnectorStatus,
        ConnectorType,
    )
    from yieldfield.domain.shared.ids import ConnectorId, TenantId
    from yieldfield.infrastructure.persistence import mappers

    connector = Connector(
        id=ConnectorId("con_1"),
        tenant_id=TenantId("tenant-1"),
        connector_type=ConnectorType.STRIPE_BILLING,
        status=ConnectorStatus.ACTIVE,
    )
    row = mappers.connector_row(connector, b"ENCRYPTED")
    assert row.id == "con_1"
    assert row.connector_type == "stripe_billing"
    assert row.encrypted_credentials == b"ENCRYPTED"
    assert mappers.to_connector(row) == connector
