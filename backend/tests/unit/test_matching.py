"""Usage-to-invoice reconciliation matching (§4 CORE) — the money path, tested hardest.

Two leakage dimensions are detected per (customer, metric):
  * unbilled_usage     — usage occurred beyond what was billed (a quantity gap)
  * misrated_line_item — the billed quantity was under-priced vs the plan (a price gap)
Together they partition the total shortfall (expected - billed), with no double count.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from itertools import count

from hypothesis import given
from hypothesis import strategies as st

from yieldfield.domain.billing.invoice import Invoice, InvoiceLineItem
from yieldfield.domain.billing.plan import Plan
from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.findings.finding import Finding
from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.findings.severity import Severity
from yieldfield.domain.reconciliation.matching import provisional_severity, reconcile_customer
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

TENANT = TenantId("t_1")
RECON = ReconciliationId("r_1")
CUSTOMER = "cust_42"


def _id_factory() -> Callable[[], FindingId]:
    counter = count(1)
    return lambda: FindingId(f"f_{next(counter)}")


def _period() -> TimeWindow:
    return TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))


def _plan(unit_price: str, metric: str = "api_calls") -> Plan:
    return Plan(
        id=PlanId("p_1"),
        tenant_id=TENANT,
        name="Metered",
        metric=metric,
        unit_price=Money.of(unit_price, "USD"),
    )


def _event(quantity: str, metric: str = "api_calls", eid: str = "u_1") -> UsageEvent:
    return UsageEvent(
        id=UsageEventId(eid),
        tenant_id=TENANT,
        customer_id=CUSTOMER,
        metric=metric,
        quantity=Decimal(quantity),
        occurred_at=datetime(2026, 1, 15, tzinfo=UTC),
    )


def _line(metric: str, quantity: str, amount: str, lid: str = "li_1") -> InvoiceLineItem:
    return InvoiceLineItem(
        id=InvoiceLineItemId(lid),
        metric=metric,
        quantity=Decimal(quantity),
        amount=Money.of(amount, "USD"),
    )


def _invoice(*lines: InvoiceLineItem) -> Invoice:
    return Invoice(
        id=InvoiceId("inv_1"),
        tenant_id=TENANT,
        customer_id=CUSTOMER,
        period=_period(),
        currency="USD",
        line_items=lines,
    )


def _reconcile(usage: list[UsageEvent], invoice: Invoice, plans: dict[str, Plan]) -> list[Finding]:
    return reconcile_customer(
        tenant_id=TENANT,
        reconciliation_id=RECON,
        customer_id=CUSTOMER,
        usage_events=usage,
        invoice=invoice,
        plans_by_metric=plans,
        id_factory=_id_factory(),
    )


class TestUnbilledUsage:
    def test_usage_with_no_line_item_is_fully_unbilled(self) -> None:
        # 100 api_calls @ $0.10, nothing billed → $10.00 unbilled.
        findings = _reconcile([_event("100")], _invoice(), {"api_calls": _plan("0.10")})
        assert len(findings) == 1
        f = findings[0]
        assert f.leakage_type is LeakageType.UNBILLED_USAGE
        assert f.amount == Money.of("10.00", "USD")
        assert f.status is RecoveryStatus.NEW
        assert f.metric == "api_calls"
        assert f.lineage.usage_event_ids == (UsageEventId("u_1"),)
        assert f.explanation.strip()

    def test_partial_billing_flags_only_the_gap(self) -> None:
        # used 100, billed 60 correctly ($6.00) → 40 unbilled = $4.00.
        findings = _reconcile(
            [_event("100")],
            _invoice(_line("api_calls", "60", "6.00")),
            {"api_calls": _plan("0.10")},
        )
        assert len(findings) == 1
        assert findings[0].leakage_type is LeakageType.UNBILLED_USAGE
        assert findings[0].amount == Money.of("4.00", "USD")


class TestMisratedLineItem:
    def test_correct_quantity_but_underpriced(self) -> None:
        # used 100, billed 100 but only charged $5.00 (should be $10.00) → $5.00 misrated.
        findings = _reconcile(
            [_event("100")],
            _invoice(_line("api_calls", "100", "5.00")),
            {"api_calls": _plan("0.10")},
        )
        assert len(findings) == 1
        f = findings[0]
        assert f.leakage_type is LeakageType.MISRATED_LINE_ITEM
        assert f.amount == Money.of("5.00", "USD")
        assert f.lineage.invoice_line_item_id == InvoiceLineItemId("li_1")


class TestNoLeakage:
    def test_correctly_billed_produces_no_findings(self) -> None:
        findings = _reconcile(
            [_event("100")],
            _invoice(_line("api_calls", "100", "10.00")),
            {"api_calls": _plan("0.10")},
        )
        assert findings == []

    def test_overbilling_is_not_a_finding(self) -> None:
        # Billed more than used — revenue isn't lost, so it is not leakage here.
        findings = _reconcile(
            [_event("50")],
            _invoice(_line("api_calls", "100", "10.00")),
            {"api_calls": _plan("0.10")},
        )
        assert findings == []

    def test_metric_without_a_plan_is_skipped(self) -> None:
        findings = _reconcile([_event("100", metric="unknown")], _invoice(), {})
        assert findings == []


class TestMultipleMetrics:
    def test_findings_are_produced_per_metric(self) -> None:
        findings = _reconcile(
            [_event("100", "api_calls", "u_1"), _event("10", "storage", "u_2")],
            _invoice(),
            {"api_calls": _plan("0.10", "api_calls"), "storage": _plan("1.00", "storage")},
        )
        metrics = {f.metric for f in findings}
        assert metrics == {"api_calls", "storage"}


class TestProvisionalSeverity:
    def test_bands(self) -> None:
        assert provisional_severity(Money.of("0.00", "USD")) is Severity.GOOD
        assert provisional_severity(Money.of("5.00", "USD")) is Severity.LOW
        assert provisional_severity(Money.of("50.00", "USD")) is Severity.MEDIUM
        assert provisional_severity(Money.of("500.00", "USD")) is Severity.HIGH
        assert provisional_severity(Money.of("5000.00", "USD")) is Severity.CRITICAL


class TestPartitionProperty:
    @given(
        unit_price=st.decimals(min_value=Decimal("0.01"), max_value=Decimal("100"), places=2),
        used=st.integers(min_value=0, max_value=10_000),
        billed_qty=st.integers(min_value=0, max_value=10_000),
        billed_amount=st.decimals(min_value=Decimal("0"), max_value=Decimal("100000"), places=2),
    )
    def test_unbilled_plus_misrated_equals_total_shortfall(
        self,
        unit_price: Decimal,
        used: int,
        billed_qty: int,
        billed_amount: Decimal,
    ) -> None:
        plan = _plan(str(unit_price))
        usage = [_event(str(used))] if used > 0 else []
        lines = (_line("api_calls", str(billed_qty), str(billed_amount)),) if billed_qty > 0 else ()
        findings = _reconcile(list(usage), _invoice(*lines), {"api_calls": plan})

        detected = sum((f.amount for f in findings), Money.zero("USD"))
        expected_total = plan.expected_charge(Decimal(used))
        billed_total = Money.of(str(billed_amount), "USD") if billed_qty > 0 else Money.zero("USD")
        shortfall = expected_total - billed_total

        # The detected leakage equals the positive shortfall — never over- or under-counted,
        # but only when both the quantity gap and the price gap are themselves non-negative
        # (the common real case: used >= billed and the billed line is not over-priced).
        if (
            used >= billed_qty
            and (plan.expected_charge(Decimal(billed_qty)) - billed_total).amount >= 0
        ):
            assert detected == (shortfall if shortfall.is_positive else Money.zero("USD"))
