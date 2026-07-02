"""Pure translation of Stripe objects → domain entities (§17).

Kept pure and unit-tested so the money path is correct regardless of how Stripe is
reached. Inputs are Mapping-like (Stripe SDK objects are dict-like; tests pass dicts).
Stripe currencies are lowercase and amounts are in minor units; we uppercase and convert
to major units for the two-decimal currencies we support — anything else fails loudly
rather than converting wrongly (§7).
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
from yieldfield.infrastructure.connectors.base.connector import ConnectorError

_MINOR_UNITS = Decimal(100)

# ISO-4217 two-decimal currencies this mapper converts exactly. Stripe reports
# zero-decimal currencies (JPY, KRW, …) in WHOLE units; dividing them by 100 here
# would be silently wrong by 100x — so anything not listed raises instead (§7
# fail-loud). Extend deliberately, with the currency's minor-unit rule in hand.
_TWO_DECIMAL_CURRENCIES = frozenset(
    {
        "USD",
        "EUR",
        "GBP",
        "CAD",
        "AUD",
        "NZD",
        "CHF",
        "SGD",
        "HKD",
        "SEK",
        "NOK",
        "DKK",
        "PLN",
        "CZK",
        "MXN",
        "BRL",
        "ZAR",
        "INR",
        "AED",
        "SAR",
    }
)


def _ts(value: Any) -> datetime:
    return datetime.fromtimestamp(int(value), tz=UTC)


def _supported_currency(currency: str) -> str:
    code = currency.upper()
    if code not in _TWO_DECIMAL_CURRENCIES:
        raise ConnectorError(
            f"Unsupported currency {code!r}: only two-decimal currencies convert exactly "
            f"from Stripe minor units; extend the allowlist deliberately (§7)."
        )
    return code


def _money_from_minor(amount: Any, currency: str) -> Money:
    return Money(Decimal(int(amount)) / _MINOR_UNITS, _supported_currency(currency))


def invoice_from_stripe(tenant_id: TenantId, raw: Mapping[str, Any]) -> Invoice:
    currency = _supported_currency(str(raw["currency"]))  # guard even line-less invoices
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
