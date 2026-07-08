"""RunReconciliation orchestration (§4.2) — the money path, tested hardest.

Fakes stand in for the OLTP repos and the OLAP store; the pure matching engine is exercised
through the use-case. Clock and finding-id factory are injected for deterministic assertions.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from itertools import count

from yieldfield.application.reconciliation.run_reconciliation import RunReconciliation
from yieldfield.domain.billing.contract import Contract
from yieldfield.domain.billing.invoice import Invoice, InvoiceLineItem
from yieldfield.domain.billing.plan import Plan
from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.reconciliation.reconciliation import Reconciliation
from yieldfield.domain.shared.ids import (
    ContractId,
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

TENANT = TenantId("t_1")
RECON = ReconciliationId("r_1")
WINDOW = TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC))
JAN = TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))
FEB = TimeWindow(datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC))
FIXED_NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _counter_ids() -> Callable[[], FindingId]:
    counter = count(1)
    return lambda: FindingId(f"f_{next(counter)}")


def _plan(plan_id: str, metric: str, unit_price: str) -> Plan:
    return Plan(
        id=PlanId(plan_id),
        tenant_id=TENANT,
        name=f"Plan {metric}",
        metric=metric,
        unit_price=Money.of(unit_price, "USD"),
    )


def _contract(contract_id: str, customer_id: str, plan_id: str) -> Contract:
    return Contract(
        id=ContractId(contract_id),
        tenant_id=TENANT,
        customer_id=customer_id,
        plan_id=PlanId(plan_id),
        term=WINDOW,
    )


def _line(metric: str, quantity: str, amount: str, lid: str = "li_1") -> InvoiceLineItem:
    return InvoiceLineItem(
        id=InvoiceLineItemId(lid),
        metric=metric,
        quantity=Decimal(quantity),
        amount=Money.of(amount, "USD"),
    )


def _invoice(
    invoice_id: str,
    customer_id: str,
    *lines: InvoiceLineItem,
    period: TimeWindow = JAN,
) -> Invoice:
    return Invoice(
        id=InvoiceId(invoice_id),
        tenant_id=TENANT,
        customer_id=customer_id,
        period=period,
        currency="USD",
        line_items=lines,
    )


def _event(event_id: str, customer_id: str, metric: str, quantity: str, at: datetime) -> UsageEvent:
    return UsageEvent(
        id=UsageEventId(event_id),
        tenant_id=TENANT,
        customer_id=customer_id,
        metric=metric,
        quantity=Decimal(quantity),
        occurred_at=at,
    )


class FakeInvoiceRepo:
    def __init__(self, invoices: list[Invoice]) -> None:
        self._invoices = invoices

    def add(self, tenant_id: TenantId, invoice: Invoice) -> None:
        return None

    def get(self, tenant_id: TenantId, invoice_id: InvoiceId) -> Invoice | None:
        return None

    def list_in_window(self, tenant_id: TenantId, window: TimeWindow) -> Sequence[Invoice]:
        return [inv for inv in self._invoices if window.contains(inv.period.start)]


class FakeUsageStore:
    def __init__(self, events: list[UsageEvent]) -> None:
        self._events = events

    def append(self, tenant_id: TenantId, events: Iterable[UsageEvent]) -> None:
        return None

    def query(self, tenant_id: TenantId, window: TimeWindow) -> Sequence[UsageEvent]:
        return [e for e in self._events if window.contains(e.occurred_at)]


class FakeContractRepo:
    def __init__(self, contracts: list[Contract]) -> None:
        self._contracts = contracts

    def add(self, tenant_id: TenantId, contract: Contract) -> None:
        return None

    def get(self, tenant_id: TenantId, contract_id: ContractId) -> Contract | None:
        return None

    def list_for_customer(self, tenant_id: TenantId, customer_id: str) -> Sequence[Contract]:
        return [c for c in self._contracts if c.customer_id == customer_id]


class FakePlanRepo:
    def __init__(self, plans: list[Plan]) -> None:
        self._plans = {p.id: p for p in plans}

    def add(self, tenant_id: TenantId, plan: Plan) -> None:
        return None

    def get(self, tenant_id: TenantId, plan_id: PlanId) -> Plan | None:
        return self._plans.get(plan_id)

    def list_for_tenant(self, tenant_id: TenantId) -> Sequence[Plan]:
        return list(self._plans.values())


class FakeReconRepo:
    def __init__(self) -> None:
        self.saved: list[Reconciliation] = []

    def add(self, tenant_id: TenantId, reconciliation: Reconciliation) -> None:
        self.saved.append(reconciliation)

    def get(
        self, tenant_id: TenantId, reconciliation_id: ReconciliationId
    ) -> Reconciliation | None:
        for r in self.saved:
            if r.id == reconciliation_id:
                return r
        return None

    def list_for_tenant(self, tenant_id: TenantId) -> Sequence[Reconciliation]:
        return list(self.saved)


def _service(
    *,
    invoices: list[Invoice],
    events: list[UsageEvent],
    contracts: list[Contract],
    plans: list[Plan],
    recon_repo: FakeReconRepo,
    clock: Callable[[], datetime] = lambda: FIXED_NOW,
) -> RunReconciliation:
    return RunReconciliation(
        FakeInvoiceRepo(invoices),
        FakeUsageStore(events),
        FakeContractRepo(contracts),
        FakePlanRepo(plans),
        recon_repo,
        finding_id_factory=_counter_ids(),
        clock=clock,
    )


# ── core money path ──────────────────────────────────────────────────────────
def test_unbilled_usage_creates_finding_and_persists_once() -> None:
    repo = FakeReconRepo()
    service = _service(
        invoices=[_invoice("inv_1", "cus_1")],  # nothing billed
        events=[_event("u_1", "cus_1", "api_calls", "100", datetime(2026, 1, 15, tzinfo=UTC))],
        contracts=[_contract("con_1", "cus_1", "p_1")],
        plans=[_plan("p_1", "api_calls", "0.10")],
        recon_repo=repo,
    )
    result = service.run(TENANT, WINDOW, RECON)
    assert result.id == RECON
    assert result.finding_count == 1
    assert result.findings[0].leakage_type is LeakageType.UNBILLED_USAGE
    assert result.total_leakage() == Money.of("10.00", "USD")
    assert result.currency == "USD"
    assert result.rule_version == "reconciliation-v1"
    assert result.executed_at == FIXED_NOW
    assert repo.saved == [result]  # persisted exactly once


def test_misrated_line_item_is_detected() -> None:
    repo = FakeReconRepo()
    service = _service(
        invoices=[_invoice("inv_1", "cus_1", _line("api_calls", "100", "5.00"))],  # underpriced
        events=[_event("u_1", "cus_1", "api_calls", "100", datetime(2026, 1, 15, tzinfo=UTC))],
        contracts=[_contract("con_1", "cus_1", "p_1")],
        plans=[_plan("p_1", "api_calls", "0.10")],  # expected $10, billed $5
        recon_repo=repo,
    )
    result = service.run(TENANT, WINDOW, RECON)
    assert result.finding_count == 1
    assert result.findings[0].leakage_type is LeakageType.MISRATED_LINE_ITEM
    assert result.total_leakage() == Money.of("5.00", "USD")


def test_correctly_billed_yields_empty_persisted_run() -> None:
    repo = FakeReconRepo()
    service = _service(
        invoices=[_invoice("inv_1", "cus_1", _line("api_calls", "100", "10.00"))],
        events=[_event("u_1", "cus_1", "api_calls", "100", datetime(2026, 1, 15, tzinfo=UTC))],
        contracts=[_contract("con_1", "cus_1", "p_1")],
        plans=[_plan("p_1", "api_calls", "0.10")],
        recon_repo=repo,
    )
    result = service.run(TENANT, WINDOW, RECON)
    assert result.finding_count == 0
    assert result.total_leakage() == Money.zero("USD")
    assert repo.saved == [result]


def test_injected_id_factory_numbers_findings_deterministically() -> None:
    service = _service(
        invoices=[_invoice("inv_1", "cus_1")],
        events=[_event("u_1", "cus_1", "api_calls", "100", datetime(2026, 1, 15, tzinfo=UTC))],
        contracts=[_contract("con_1", "cus_1", "p_1")],
        plans=[_plan("p_1", "api_calls", "0.10")],
        recon_repo=FakeReconRepo(),
    )
    result = service.run(TENANT, WINDOW, RECON)
    assert result.findings[0].id == FindingId("f_1")


# ── breadth / orchestration edges ────────────────────────────────────────────
def test_each_customer_is_reconciled_against_its_own_plan() -> None:
    service = _service(
        invoices=[_invoice("inv_1", "cus_1"), _invoice("inv_2", "cus_2")],
        events=[
            _event("u_1", "cus_1", "api_calls", "100", datetime(2026, 1, 15, tzinfo=UTC)),
            _event("u_2", "cus_2", "storage", "5", datetime(2026, 1, 15, tzinfo=UTC)),
        ],
        contracts=[_contract("con_1", "cus_1", "p_1"), _contract("con_2", "cus_2", "p_2")],
        plans=[_plan("p_1", "api_calls", "0.10"), _plan("p_2", "storage", "1.00")],
        recon_repo=FakeReconRepo(),
    )
    result = service.run(TENANT, WINDOW, RECON)
    by_customer = {f.customer_id: f for f in result.findings}
    assert by_customer["cus_1"].metric == "api_calls"
    assert by_customer["cus_1"].amount == Money.of("10.00", "USD")
    assert by_customer["cus_2"].metric == "storage"
    assert by_customer["cus_2"].amount == Money.of("5.00", "USD")
    assert result.total_leakage() == Money.of("15.00", "USD")


def test_usage_outside_an_invoice_period_is_excluded() -> None:
    # Window spans Jan+Feb; invoice covers Jan only. The Feb event must not be attributed.
    service = _service(
        invoices=[_invoice("inv_1", "cus_1", period=JAN)],
        events=[
            _event("u_1", "cus_1", "api_calls", "100", datetime(2026, 1, 15, tzinfo=UTC)),
            _event("u_2", "cus_1", "api_calls", "50", datetime(2026, 2, 15, tzinfo=UTC)),
        ],
        contracts=[_contract("con_1", "cus_1", "p_1")],
        plans=[_plan("p_1", "api_calls", "0.10")],
        recon_repo=FakeReconRepo(),
    )
    result = service.run(TENANT, WINDOW, RECON)
    assert result.total_leakage() == Money.of("10.00", "USD")  # only the 100 in Jan


def test_usage_is_attributed_to_the_invoice_whose_period_contains_it() -> None:
    service = _service(
        invoices=[
            _invoice("inv_jan", "cus_1", period=JAN),
            _invoice("inv_feb", "cus_1", period=FEB),
        ],
        events=[
            _event("u_1", "cus_1", "api_calls", "100", datetime(2026, 1, 15, tzinfo=UTC)),
            _event("u_2", "cus_1", "api_calls", "30", datetime(2026, 2, 15, tzinfo=UTC)),
        ],
        contracts=[_contract("con_1", "cus_1", "p_1")],
        plans=[_plan("p_1", "api_calls", "0.10")],
        recon_repo=FakeReconRepo(),
    )
    result = service.run(TENANT, WINDOW, RECON)
    amounts = sorted(f.amount.amount for f in result.findings)
    assert amounts == [Decimal("3.00"), Decimal("10.00")]  # Feb 30→$3, Jan 100→$10
    assert result.total_leakage() == Money.of("13.00", "USD")


def test_empty_window_persists_an_empty_usd_run() -> None:
    repo = FakeReconRepo()
    result = _service(invoices=[], events=[], contracts=[], plans=[], recon_repo=repo).run(
        TENANT, WINDOW, RECON
    )
    assert result.finding_count == 0
    assert result.currency == "USD"
    assert result.total_leakage() == Money.zero("USD")
    assert repo.saved == [result]


def test_customer_with_unresolvable_plan_is_skipped_and_run_still_persists() -> None:
    # The contract points at a plan id the repo cannot resolve → no pricing for the
    # customer → skipped (unpriced usage is future work), and an empty run is persisted.
    repo = FakeReconRepo()
    service = _service(
        invoices=[_invoice("inv_1", "cus_1")],
        events=[_event("u_1", "cus_1", "api_calls", "100", datetime(2026, 1, 15, tzinfo=UTC))],
        contracts=[_contract("con_1", "cus_1", "p_missing")],
        plans=[],  # p_missing does not resolve
        recon_repo=repo,
    )
    result = service.run(TENANT, WINDOW, RECON)
    assert result.finding_count == 0
    assert repo.saved == [result]


def test_usage_in_an_invoice_period_tail_beyond_the_window_is_reconciled() -> None:
    # Selection is by period_start ∈ window, but this invoice's period runs past
    # window.end — usage in that tail (Feb 1-14) belongs to the invoice and must be
    # loaded and reconciled, not dropped by bounding the usage load to the window.
    period = TimeWindow(datetime(2026, 1, 15, tzinfo=UTC), datetime(2026, 2, 15, tzinfo=UTC))
    repo = FakeReconRepo()
    service = _service(
        invoices=[_invoice("inv_1", "cus_1", _line("api_call", "50", "5.00"), period=period)],
        events=[
            _event("u_1", "cus_1", "api_call", "100", datetime(2026, 1, 20, tzinfo=UTC)),
            # Inside the invoice period but OUTSIDE the reconciliation window — the tail.
            _event("u_2", "cus_1", "api_call", "40", datetime(2026, 2, 5, tzinfo=UTC)),
            # Outside the invoice period — must not change the result.
            _event("u_3", "cus_1", "api_call", "25", datetime(2026, 2, 20, tzinfo=UTC)),
        ],
        contracts=[_contract("con_1", "cus_1", "p_1")],
        plans=[_plan("p_1", "api_call", "0.10")],
        recon_repo=repo,
    )
    result = service.run(TENANT, JAN, RECON)
    assert result.finding_count == 1
    assert result.findings[0].leakage_type is LeakageType.UNBILLED_USAGE
    # 140 used (100 on Jan 20 + 40 on Feb 5) - 50 billed = 90 unbilled x $0.10.
    assert result.total_leakage() == Money.of("9.00", "USD")


def test_rerun_with_same_id_produces_the_same_financial_result() -> None:
    # Convergence at the financial level: same inputs + same reconciliation_id ⇒ same findings/total.
    # (Storage-level idempotency on reconciliation_id is the repository's job, integration-tested in 3A.)
    def make() -> RunReconciliation:
        return _service(
            invoices=[_invoice("inv_1", "cus_1")],
            events=[_event("u_1", "cus_1", "api_calls", "100", datetime(2026, 1, 15, tzinfo=UTC))],
            contracts=[_contract("con_1", "cus_1", "p_1")],
            plans=[_plan("p_1", "api_calls", "0.10")],
            recon_repo=FakeReconRepo(),
        )

    first = make().run(TENANT, WINDOW, RECON)
    second = make().run(TENANT, WINDOW, RECON)
    assert first.total_leakage() == second.total_leakage()
    assert [(f.metric, f.leakage_type, f.amount) for f in first.findings] == [
        (f.metric, f.leakage_type, f.amount) for f in second.findings
    ]
