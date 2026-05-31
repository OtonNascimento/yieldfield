"""OLTP repository round-trips + cross-tenant isolation (§11). Requires Docker."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from yieldfield.domain.billing.invoice import Invoice, InvoiceLineItem
from yieldfield.domain.billing.plan import Plan
from yieldfield.domain.billing.tenant import Tenant
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
)
from yieldfield.domain.shared.money import Money
from yieldfield.domain.shared.time_window import TimeWindow
from yieldfield.infrastructure.persistence.repositories import (
    SqlAlchemyFindingRepository,
    SqlAlchemyInvoiceRepository,
    SqlAlchemyPlanRepository,
    SqlAlchemyReconciliationRepository,
    SqlAlchemyTenantRepository,
)

pytestmark = pytest.mark.integration

_WINDOW = TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))


def _tenant(tid: str) -> Tenant:
    return Tenant(id=TenantId(tid), name=f"Tenant {tid}")


def _plan(tid: str, pid: str) -> Plan:
    return Plan(
        id=PlanId(pid),
        tenant_id=TenantId(tid),
        name="API calls",
        metric="api_call",
        unit_price=Money.of("0.0000004", "USD"),
    )


def test_plan_round_trips(session: Session) -> None:
    repo = SqlAlchemyPlanRepository(session)
    SqlAlchemyTenantRepository(session).add(_tenant("t_1"))
    repo.add(TenantId("t_1"), _plan("t_1", "pl_1"))
    session.flush()
    assert repo.get(TenantId("t_1"), PlanId("pl_1")) == _plan("t_1", "pl_1")


def test_invoice_round_trips_with_line_items(session: Session) -> None:
    SqlAlchemyTenantRepository(session).add(_tenant("t_1"))
    repo = SqlAlchemyInvoiceRepository(session)
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
    repo.add(TenantId("t_1"), invoice)
    session.flush()
    assert repo.get(TenantId("t_1"), InvoiceId("in_1")) == invoice


def test_reconciliation_persists_findings_and_reads_back(session: Session) -> None:
    SqlAlchemyTenantRepository(session).add(_tenant("t_1"))
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
        lineage=FindingLineage(rule_version="reconciliation-v1"),
        explanation="unbilled usage detected.",
    )
    recon = Reconciliation(
        id=ReconciliationId("rc_1"),
        tenant_id=TenantId("t_1"),
        window=_WINDOW,
        currency="USD",
        findings=(finding,),
    )
    SqlAlchemyReconciliationRepository(session).add(TenantId("t_1"), recon)
    session.flush()

    assert (
        SqlAlchemyReconciliationRepository(session).get(TenantId("t_1"), ReconciliationId("rc_1"))
        == recon
    )
    findings = SqlAlchemyFindingRepository(session).list_for_reconciliation(
        TenantId("t_1"), ReconciliationId("rc_1")
    )
    assert findings == [finding]


def test_finding_status_update_persists(session: Session) -> None:
    SqlAlchemyTenantRepository(session).add(_tenant("t_1"))
    finding = Finding(
        id=FindingId("fd_2"),
        tenant_id=TenantId("t_1"),
        reconciliation_id=ReconciliationId("rc_2"),
        customer_id="cus_1",
        metric="api_call",
        leakage_type=LeakageType.UNBILLED_USAGE,
        severity=Severity.HIGH,
        amount=Money.of("10.00", "USD"),
        status=RecoveryStatus.NEW,
        lineage=FindingLineage(rule_version="reconciliation-v1"),
        explanation="x",
    )
    recon = Reconciliation(
        id=ReconciliationId("rc_2"),
        tenant_id=TenantId("t_1"),
        window=_WINDOW,
        currency="USD",
        findings=(finding,),
    )
    repo = SqlAlchemyFindingRepository(session)
    SqlAlchemyReconciliationRepository(session).add(TenantId("t_1"), recon)
    session.flush()

    repo.update(TenantId("t_1"), finding.review())
    session.flush()
    reloaded = repo.get(TenantId("t_1"), FindingId("fd_2"))
    assert reloaded is not None
    assert reloaded.status is RecoveryStatus.REVIEWED


def test_cross_tenant_reads_are_isolated(session: Session) -> None:
    tenants = SqlAlchemyTenantRepository(session)
    plans = SqlAlchemyPlanRepository(session)
    tenants.add(_tenant("t_A"))
    tenants.add(_tenant("t_B"))
    plans.add(TenantId("t_A"), _plan("t_A", "pl_A"))
    session.flush()

    assert plans.get(TenantId("t_B"), PlanId("pl_A")) is None  # B cannot read A's plan
    assert plans.list_for_tenant(TenantId("t_B")) == []
    assert plans.get(TenantId("t_A"), PlanId("pl_A")) is not None
