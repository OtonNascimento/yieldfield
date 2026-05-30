"""Invoice and InvoiceLineItem — an issued bill and its lines (§8 glossary).

A line item carries the *billed* quantity and *billed* amount; reconciliation
compares those against what a plan says should have been billed (§4 CORE). The line
amount is intentionally NOT forced to equal quantity x unit_price — a mismatch there
is exactly the mis-rating leakage we detect.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from yieldfield.domain.shared.errors import CurrencyMismatchError, InvalidEntityError
from yieldfield.domain.shared.ids import InvoiceId, InvoiceLineItemId, TenantId
from yieldfield.domain.shared.money import Money
from yieldfield.domain.shared.time_window import TimeWindow


@dataclass(frozen=True, slots=True)
class InvoiceLineItem:
    id: InvoiceLineItemId
    metric: str
    quantity: Decimal
    amount: Money

    def __post_init__(self) -> None:
        if not self.metric.strip():
            raise InvalidEntityError("InvoiceLineItem metric is required.")
        if self.quantity < 0:
            raise InvalidEntityError("InvoiceLineItem quantity cannot be negative.")


@dataclass(frozen=True, slots=True)
class Invoice:
    id: InvoiceId
    tenant_id: TenantId
    customer_id: str
    period: TimeWindow
    currency: str
    line_items: tuple[InvoiceLineItem, ...]

    def __post_init__(self) -> None:
        if not self.customer_id.strip():
            raise InvalidEntityError("Invoice customer_id is required.")
        for item in self.line_items:
            if item.amount.currency != self.currency:
                raise CurrencyMismatchError(
                    f"Line item {item.id} is {item.amount.currency}, "
                    f"invoice is {self.currency}."
                )

    def total(self) -> Money:
        total = Money.zero(self.currency)
        for item in self.line_items:
            total = total + item.amount
        return total

    def line_items_for_metric(self, metric: str) -> tuple[InvoiceLineItem, ...]:
        return tuple(item for item in self.line_items if item.metric == metric)
