"""UsageEvent — a single metered usage record (§8 glossary).

The high-volume input to reconciliation. Quantity is non-negative and the timestamp
is timezone-aware so an event falls into exactly one reconciliation window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from yieldfield.domain.shared.errors import InvalidEntityError
from yieldfield.domain.shared.ids import TenantId, UsageEventId


@dataclass(frozen=True, slots=True)
class UsageEvent:
    id: UsageEventId
    tenant_id: TenantId
    customer_id: str
    metric: str
    quantity: Decimal
    occurred_at: datetime

    def __post_init__(self) -> None:
        if not self.metric.strip():
            raise InvalidEntityError("UsageEvent metric is required.")
        if self.quantity < 0:
            raise InvalidEntityError("UsageEvent quantity cannot be negative.")
        if self.occurred_at.tzinfo is None:
            raise InvalidEntityError("UsageEvent occurred_at must be timezone-aware.")
