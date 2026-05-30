"""Plan — the pricing for a metered dimension (§8 glossary).

Slice 1 models a flat per-unit price for one metric. Tiered/graduated pricing is a
later extension (a new strategy, §17), not a rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from yieldfield.domain.shared.errors import InvalidEntityError
from yieldfield.domain.shared.ids import PlanId, TenantId
from yieldfield.domain.shared.money import Money


@dataclass(frozen=True, slots=True)
class Plan:
    id: PlanId
    tenant_id: TenantId
    name: str
    metric: str
    unit_price: Money

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise InvalidEntityError("Plan name is required.")
        if not self.metric.strip():
            raise InvalidEntityError("Plan metric is required.")
        if self.unit_price.is_negative:
            raise InvalidEntityError("Plan unit_price cannot be negative.")

    def expected_charge(self, quantity: Decimal) -> Money:
        """The amount this plan should bill for `quantity` units of its metric."""
        if quantity < 0:
            raise InvalidEntityError("quantity cannot be negative.")
        return self.unit_price * quantity
