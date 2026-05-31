"""Pure Stripe→domain mappers — the connector money path (currency, minor units, tz)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from yieldfield.domain.shared.ids import TenantId
from yieldfield.domain.shared.money import Money
from yieldfield.infrastructure.connectors.stripe_billing.mapping import (
    invoice_from_stripe,
    usage_event_from_stripe,
)


def test_invoice_maps_currency_minor_units_and_timestamps() -> None:
    raw = {
        "id": "in_1",
        "customer": "cus_1",
        "period_start": 1735689600,  # 2025-01-01T00:00:00Z
        "period_end": 1738368000,  # 2025-02-01T00:00:00Z
        "currency": "usd",
        "lines": [
            {
                "id": "il_1",
                "metric": "api_call",
                "quantity": 1000,
                "amount": 400,
                "currency": "usd",
            },
        ],
    }
    invoice = invoice_from_stripe(TenantId("t_1"), raw)
    assert invoice.tenant_id == "t_1"
    assert invoice.currency == "USD"
    assert invoice.period.start == datetime(2025, 1, 1, tzinfo=UTC)
    assert invoice.line_items[0].amount == Money.of("4.00", "USD")  # 400 cents → 4.00
    assert invoice.line_items[0].quantity == Decimal("1000")


def test_usage_event_maps_quantity_and_timestamp() -> None:
    raw = {
        "id": "ue_1",
        "customer_id": "cus_1",
        "metric": "api_call",
        "quantity": 12,
        "occurred_at": 1735689600,
    }
    event = usage_event_from_stripe(TenantId("t_1"), raw)
    assert event.tenant_id == "t_1"
    assert event.quantity == Decimal("12")
    assert event.occurred_at == datetime(2025, 1, 1, tzinfo=UTC)
