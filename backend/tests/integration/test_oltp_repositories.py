"""OLTP repository round-trips + cross-tenant isolation (§11). Requires Docker."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from yieldfield.domain.billing.contract import Contract
from yieldfield.domain.billing.invoice import Invoice, InvoiceLineItem
from yieldfield.domain.billing.plan import Plan
from yieldfield.domain.billing.tenant import Tenant
from yieldfield.domain.findings.finding import Finding, FindingLineage
from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.findings.severity import Severity
from yieldfield.domain.reconciliation.reconciliation import Reconciliation
from yieldfield.domain.shared.ids import (
    ContractId,
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
    SqlAlchemyContractRepository,
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


def _window(y1: int, m1: int, d1: int, y2: int, m2: int, d2: int) -> TimeWindow:
    return TimeWindow(datetime(y1, m1, d1, tzinfo=UTC), datetime(y2, m2, d2, tzinfo=UTC))


def _invoice(tid: str, iid: str, period: TimeWindow) -> Invoice:
    return Invoice(
        id=InvoiceId(iid),
        tenant_id=TenantId(tid),
        customer_id="cus_1",
        period=period,
        currency="USD",
        line_items=(),
    )


def _contract(tid: str, cid: str, customer_id: str, plan_id: str) -> Contract:
    return Contract(
        id=ContractId(cid),
        tenant_id=TenantId(tid),
        customer_id=customer_id,
        plan_id=PlanId(plan_id),
        term=_WINDOW,
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


def test_list_in_window_selects_by_period_start_within_window(session: Session) -> None:
    SqlAlchemyTenantRepository(session).add(_tenant("t_1"))
    SqlAlchemyTenantRepository(session).add(_tenant("t_2"))
    repo = SqlAlchemyInvoiceRepository(session)
    # In: period_start inside [Jan 1, Feb 1).
    repo.add(TenantId("t_1"), _invoice("t_1", "in_in", _window(2026, 1, 10, 2026, 2, 10)))
    # Out: overlaps the window but period_start precedes it — the partitioning
    # semantic: an invoice reconciles in the window containing its period_start.
    repo.add(TenantId("t_1"), _invoice("t_1", "in_straddle", _window(2025, 12, 15, 2026, 1, 15)))
    # Out: period_start == window.end (half-open [start, end)).
    repo.add(TenantId("t_1"), _invoice("t_1", "in_next", _window(2026, 2, 1, 2026, 3, 1)))
    # Out: another tenant's invoice inside the window (§11).
    repo.add(TenantId("t_2"), _invoice("t_2", "in_other", _window(2026, 1, 20, 2026, 2, 20)))
    session.flush()

    listed = repo.list_in_window(TenantId("t_1"), _WINDOW)
    assert [inv.id for inv in listed] == [InvoiceId("in_in")]


def test_list_for_customer_is_tenant_and_customer_scoped(session: Session) -> None:
    SqlAlchemyTenantRepository(session).add(_tenant("t_1"))
    SqlAlchemyTenantRepository(session).add(_tenant("t_2"))
    plans = SqlAlchemyPlanRepository(session)
    plans.add(TenantId("t_1"), _plan("t_1", "pl_1"))
    plans.add(TenantId("t_2"), _plan("t_2", "pl_2"))
    session.flush()  # plans must hit the DB before contracts reference them (FK)

    repo = SqlAlchemyContractRepository(session)
    repo.add(TenantId("t_1"), _contract("t_1", "con_match", "cus_1", "pl_1"))
    repo.add(TenantId("t_1"), _contract("t_1", "con_other_cus", "cus_2", "pl_1"))
    repo.add(TenantId("t_2"), _contract("t_2", "con_other_tenant", "cus_1", "pl_2"))
    session.flush()

    listed = repo.list_for_customer(TenantId("t_1"), "cus_1")
    assert [c.id for c in listed] == [ContractId("con_match")]


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
        executed_at=datetime(2026, 1, 1, tzinfo=UTC),
        rule_version="reconciliation-v1",
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
        executed_at=datetime(2026, 1, 1, tzinfo=UTC),
        rule_version="reconciliation-v1",
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


@pytest.mark.integration
def test_invoice_add_is_idempotent(session: Session) -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    from yieldfield.domain.billing.invoice import Invoice, InvoiceLineItem
    from yieldfield.domain.billing.tenant import Tenant
    from yieldfield.domain.shared.ids import InvoiceId, InvoiceLineItemId, TenantId
    from yieldfield.domain.shared.money import Money
    from yieldfield.domain.shared.time_window import TimeWindow
    from yieldfield.infrastructure.persistence.repositories import (
        SqlAlchemyInvoiceRepository,
        SqlAlchemyTenantRepository,
    )

    tid = TenantId("tenant-idem")
    SqlAlchemyTenantRepository(session).add(Tenant(id=tid, name="Idem"))
    session.flush()
    repo = SqlAlchemyInvoiceRepository(session)
    period = TimeWindow(datetime(2026, 5, 1, tzinfo=UTC), datetime(2026, 6, 1, tzinfo=UTC))

    def build(amount: str) -> Invoice:
        return Invoice(
            id=InvoiceId("inv_1"),
            tenant_id=tid,
            customer_id="cus_1",
            period=period,
            currency="USD",
            line_items=(
                InvoiceLineItem(
                    id=InvoiceLineItemId("li_1"),
                    metric="api_calls",
                    quantity=Decimal("10"),
                    amount=Money.of(amount, "USD"),
                ),
            ),
        )

    repo.add(tid, build("100"))
    session.flush()
    repo.add(tid, build("250"))  # same id again — must replace, not duplicate
    session.flush()

    stored = repo.get(tid, InvoiceId("inv_1"))
    assert stored is not None
    assert stored.total() == Money.of("250", "USD")
    assert len(stored.line_items) == 1  # line items replaced, not accumulated


@pytest.mark.integration
def test_reconciliation_add_is_idempotent(session: Session) -> None:
    tid = TenantId("tenant-rc-idem")
    SqlAlchemyTenantRepository(session).add(Tenant(id=tid, name="RcIdem"))
    session.flush()

    repo = SqlAlchemyReconciliationRepository(session)
    findings_repo = SqlAlchemyFindingRepository(session)

    def _finding(fid: str, amount: str) -> Finding:
        return Finding(
            id=FindingId(fid),
            tenant_id=tid,
            reconciliation_id=ReconciliationId("rc-idem"),
            customer_id="cus_idem",
            metric="api_call",
            leakage_type=LeakageType.UNBILLED_USAGE,
            severity=Severity.HIGH,
            amount=Money.of(amount, "USD"),
            status=RecoveryStatus.NEW,
            lineage=FindingLineage(rule_version="reconciliation-v1"),
            explanation="leakage detected.",
        )

    def _recon(findings: tuple[Finding, ...]) -> Reconciliation:
        return Reconciliation(
            id=ReconciliationId("rc-idem"),
            tenant_id=tid,
            window=_WINDOW,
            currency="USD",
            executed_at=datetime(2026, 3, 1, tzinfo=UTC),
            rule_version="reconciliation-v1",
            findings=findings,
        )

    # First add: one finding
    repo.add(tid, _recon((_finding("fd-idem-1", "50.00"),)))
    session.flush()

    # Second add: same reconciliation id, different finding set (two findings)
    repo.add(tid, _recon((_finding("fd-idem-2", "75.00"), _finding("fd-idem-3", "25.00"))))
    session.flush()

    # Findings should reflect ONLY the second add — no accumulation from the first
    findings = list(findings_repo.list_for_reconciliation(tid, ReconciliationId("rc-idem")))
    finding_ids = {f.id for f in findings}
    assert FindingId("fd-idem-1") not in finding_ids, "first-add finding must be replaced"
    assert FindingId("fd-idem-2") in finding_ids
    assert FindingId("fd-idem-3") in finding_ids
    assert len(findings) == 2  # replaced, not accumulated

    # Reconciliation's own fields reflect the second version
    stored_rc = repo.get(tid, ReconciliationId("rc-idem"))
    assert stored_rc is not None
    assert stored_rc.total_leakage() == Money.of("100.00", "USD")


@pytest.mark.integration
def test_upsert_rejects_cross_tenant_id_collision(session: Session) -> None:
    from yieldfield.infrastructure.persistence.errors import PersistenceError

    tid_a = TenantId("tenant-col-A")
    tid_b = TenantId("tenant-col-B")
    tenants = SqlAlchemyTenantRepository(session)
    tenants.add(Tenant(id=tid_a, name="ColA"))
    tenants.add(Tenant(id=tid_b, name="ColB"))
    session.flush()

    invoices = SqlAlchemyInvoiceRepository(session)
    period = _WINDOW

    inv_a = Invoice(
        id=InvoiceId("inv-collision"),
        tenant_id=tid_a,
        customer_id="cus_a",
        period=period,
        currency="USD",
        line_items=(
            InvoiceLineItem(
                id=InvoiceLineItemId("li-col-1"),
                metric="api_calls",
                quantity=Decimal("5"),
                amount=Money.of("50.00", "USD"),
            ),
        ),
    )
    # Tenant A owns inv-collision
    invoices.add(tid_a, inv_a)
    session.flush()

    # Tenant B tries to upsert with the same invoice id — second _guard must fire
    inv_b = Invoice(
        id=InvoiceId("inv-collision"),  # same id as A's invoice
        tenant_id=tid_b,
        customer_id="cus_b",
        period=period,
        currency="USD",
        line_items=(
            InvoiceLineItem(
                id=InvoiceLineItemId("li-col-2"),
                metric="api_calls",
                quantity=Decimal("1"),
                amount=Money.of("10.00", "USD"),
            ),
        ),
    )
    with pytest.raises(PersistenceError):
        invoices.add(tid_b, inv_b)
