"""Billing entities (§8 glossary) — canonical domain objects with their invariants."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from yieldfield.domain.billing.contract import Contract
from yieldfield.domain.billing.invoice import Invoice, InvoiceLineItem
from yieldfield.domain.billing.plan import Plan
from yieldfield.domain.billing.tenant import Tenant
from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.shared.errors import CurrencyMismatchError, InvalidEntityError
from yieldfield.domain.shared.ids import (
    ContractId,
    InvoiceId,
    InvoiceLineItemId,
    PlanId,
    TenantId,
    UsageEventId,
)
from yieldfield.domain.shared.money import Money
from yieldfield.domain.shared.time_window import TimeWindow


def _dt(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour, tzinfo=UTC)


class TestTenant:
    def test_valid(self) -> None:
        tenant = Tenant(id=TenantId("t_1"), name="Acme")
        assert tenant.name == "Acme"

    def test_name_required(self) -> None:
        with pytest.raises(InvalidEntityError):
            Tenant(id=TenantId("t_1"), name="  ")


class TestPlan:
    def test_expected_charge_is_unit_price_times_quantity(self) -> None:
        plan = Plan(
            id=PlanId("p_1"),
            tenant_id=TenantId("t_1"),
            name="Metered API",
            metric="api_calls",
            unit_price=Money.of("0.10", "USD"),
        )
        assert plan.expected_charge(Decimal("100")) == Money.of("10.00", "USD")

    def test_rejects_negative_unit_price(self) -> None:
        with pytest.raises(InvalidEntityError):
            Plan(
                id=PlanId("p_1"),
                tenant_id=TenantId("t_1"),
                name="Bad",
                metric="api_calls",
                unit_price=Money.of("-0.10", "USD"),
            )

    def test_expected_charge_rejects_negative_quantity(self) -> None:
        plan = Plan(
            id=PlanId("p_1"),
            tenant_id=TenantId("t_1"),
            name="Metered API",
            metric="api_calls",
            unit_price=Money.of("0.10", "USD"),
        )
        with pytest.raises(InvalidEntityError):
            plan.expected_charge(Decimal("-1"))


class TestContract:
    def _contract(self) -> Contract:
        return Contract(
            id=ContractId("c_1"),
            tenant_id=TenantId("t_1"),
            customer_id="cust_42",
            plan_id=PlanId("p_1"),
            term=TimeWindow(_dt(1), _dt(10)),
        )

    def test_is_active_within_term(self) -> None:
        assert self._contract().is_active_at(_dt(5))

    def test_is_inactive_outside_term(self) -> None:
        assert not self._contract().is_active_at(_dt(20))

    def test_customer_required(self) -> None:
        with pytest.raises(InvalidEntityError):
            Contract(
                id=ContractId("c_1"),
                tenant_id=TenantId("t_1"),
                customer_id="",
                plan_id=PlanId("p_1"),
                term=TimeWindow(_dt(1), _dt(10)),
            )


class TestUsageEvent:
    def test_valid(self) -> None:
        event = UsageEvent(
            id=UsageEventId("u_1"),
            tenant_id=TenantId("t_1"),
            customer_id="cust_42",
            metric="api_calls",
            quantity=Decimal("100"),
            occurred_at=_dt(2),
        )
        assert event.quantity == Decimal("100")

    def test_rejects_negative_quantity(self) -> None:
        with pytest.raises(InvalidEntityError):
            UsageEvent(
                id=UsageEventId("u_1"),
                tenant_id=TenantId("t_1"),
                customer_id="cust_42",
                metric="api_calls",
                quantity=Decimal("-1"),
                occurred_at=_dt(2),
            )

    def test_rejects_naive_timestamp(self) -> None:
        with pytest.raises(InvalidEntityError):
            UsageEvent(
                id=UsageEventId("u_1"),
                tenant_id=TenantId("t_1"),
                customer_id="cust_42",
                metric="api_calls",
                quantity=Decimal("100"),
                occurred_at=datetime(2026, 1, 2),
            )


class TestInvoiceLineItem:
    def test_valid(self) -> None:
        item = InvoiceLineItem(
            id=InvoiceLineItemId("li_1"),
            metric="api_calls",
            quantity=Decimal("100"),
            amount=Money.of("10.00", "USD"),
        )
        assert item.amount == Money.of("10.00", "USD")

    def test_rejects_negative_quantity(self) -> None:
        with pytest.raises(InvalidEntityError):
            InvoiceLineItem(
                id=InvoiceLineItemId("li_1"),
                metric="api_calls",
                quantity=Decimal("-1"),
                amount=Money.of("10.00", "USD"),
            )


class TestInvoice:
    def _line(self, metric: str, amount: str) -> InvoiceLineItem:
        return InvoiceLineItem(
            id=InvoiceLineItemId(f"li_{metric}"),
            metric=metric,
            quantity=Decimal("1"),
            amount=Money.of(amount, "USD"),
        )

    def test_total_sums_line_items(self) -> None:
        invoice = Invoice(
            id=InvoiceId("inv_1"),
            tenant_id=TenantId("t_1"),
            customer_id="cust_42",
            period=TimeWindow(_dt(1), _dt(31)),
            currency="USD",
            line_items=(self._line("api_calls", "10.00"), self._line("storage", "5.50")),
        )
        assert invoice.total() == Money.of("15.50", "USD")

    def test_empty_invoice_total_is_zero(self) -> None:
        invoice = Invoice(
            id=InvoiceId("inv_1"),
            tenant_id=TenantId("t_1"),
            customer_id="cust_42",
            period=TimeWindow(_dt(1), _dt(31)),
            currency="USD",
            line_items=(),
        )
        assert invoice.total() == Money.zero("USD")

    def test_rejects_line_item_currency_mismatch(self) -> None:
        eur_line = InvoiceLineItem(
            id=InvoiceLineItemId("li_eur"),
            metric="api_calls",
            quantity=Decimal("1"),
            amount=Money.of("10.00", "EUR"),
        )
        with pytest.raises(CurrencyMismatchError):
            Invoice(
                id=InvoiceId("inv_1"),
                tenant_id=TenantId("t_1"),
                customer_id="cust_42",
                period=TimeWindow(_dt(1), _dt(31)),
                currency="USD",
                line_items=(eur_line,),
            )

    def test_line_items_for_metric(self) -> None:
        invoice = Invoice(
            id=InvoiceId("inv_1"),
            tenant_id=TenantId("t_1"),
            customer_id="cust_42",
            period=TimeWindow(_dt(1), _dt(31)),
            currency="USD",
            line_items=(self._line("api_calls", "10.00"), self._line("storage", "5.50")),
        )
        items = invoice.line_items_for_metric("api_calls")
        assert len(items) == 1
        assert items[0].metric == "api_calls"
