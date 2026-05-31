"""Pure translation of Stripe objects → domain entities (§17).

Kept pure and unit-tested so the money path is correct regardless of how Stripe is
reached. Inputs are Mapping-like (Stripe SDK objects are dict-like; tests pass dicts).
Stripe currencies are lowercase and amounts are in minor units; we uppercase and convert
to major units (two-decimal assumption — zero-decimal currencies are a later refinement).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from yieldfield.domain.billing.invoice import Invoice, InvoiceLineItem
from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.shared.ids import InvoiceId, InvoiceLineItemId, TenantId, UsageEventId
from yieldfield.domain.shared.money import Money
from yieldfield.domain.shared.time_window import TimeWindow

_MINOR_UNITS = Decimal(100)


def _ts(value: Any) -> datetime:
    return datetime.fromtimestamp(int(value), tz=UTC)


def _money_from_minor(amount: Any, currency: str) -> Money:
    return Money(Decimal(int(amount)) / _MINOR_UNITS, currency.upper())


def invoice_from_stripe(tenant_id: TenantId, raw: Mapping[str, Any]) -> Invoice:
    currency = str(raw["currency"]).upper()
    line_items = tuple(
        InvoiceLineItem(
            id=InvoiceLineItemId(str(line["id"])),
            metric=str(line["metric"]),
            quantity=Decimal(str(line.get("quantity") or 0)),
            amount=_money_from_minor(line["amount"], str(line["currency"])),
        )
        for line in raw["lines"]
    )
    return Invoice(
        id=InvoiceId(str(raw["id"])),
        tenant_id=tenant_id,
        customer_id=str(raw["customer"]),
        period=TimeWindow(_ts(raw["period_start"]), _ts(raw["period_end"])),
        currency=currency,
        line_items=line_items,
    )


def usage_event_from_stripe(tenant_id: TenantId, raw: Mapping[str, Any]) -> UsageEvent:
    return UsageEvent(
        id=UsageEventId(str(raw["id"])),
        tenant_id=tenant_id,
        customer_id=str(raw["customer_id"]),
        metric=str(raw["metric"]),
        quantity=Decimal(str(raw["quantity"])),
        occurred_at=_ts(raw["occurred_at"]),
    )
