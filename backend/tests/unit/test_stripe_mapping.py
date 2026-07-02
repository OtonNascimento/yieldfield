"""Pure Stripe→domain mappers — the connector money path (currency, minor units, tz)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from yieldfield.domain.shared.ids import TenantId
from yieldfield.domain.shared.money import Money
from yieldfield.infrastructure.connectors.base.connector import ConnectorError
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


def test_zero_decimal_currency_fails_loudly() -> None:
    # Stripe reports JPY (zero-decimal) in whole units; /100 would be silently wrong
    # by 100x. Anything outside the two-decimal allowlist must raise, not compute (§7).
    raw = {
        "id": "in_jp",
        "customer": "cus_1",
        "period_start": 1735689600,
        "period_end": 1738368000,
        "currency": "jpy",
        "lines": [
            {"id": "il_1", "metric": "api_call", "quantity": 10, "amount": 5000, "currency": "jpy"}
        ],
    }
    with pytest.raises(ConnectorError, match="JPY"):
        invoice_from_stripe(TenantId("t_1"), raw)


def test_two_decimal_currency_converts_exactly() -> None:
    raw = {
        "id": "in_eu",
        "customer": "cus_1",
        "period_start": 1735689600,
        "period_end": 1738368000,
        "currency": "eur",
        "lines": [
            {"id": "il_1", "metric": "api_call", "quantity": 1, "amount": 1234, "currency": "eur"}
        ],
    }
    invoice = invoice_from_stripe(TenantId("t_1"), raw)
    assert invoice.line_items[0].amount == Money.of("12.34", "EUR")


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
