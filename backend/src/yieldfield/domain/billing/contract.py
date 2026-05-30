"""Contract — links a tenant's end customer to a plan over a term (§8 glossary)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from yieldfield.domain.shared.errors import InvalidEntityError
from yieldfield.domain.shared.ids import ContractId, PlanId, TenantId
from yieldfield.domain.shared.time_window import TimeWindow


@dataclass(frozen=True, slots=True)
class Contract:
    id: ContractId
    tenant_id: TenantId
    customer_id: str
    plan_id: PlanId
    term: TimeWindow

    def __post_init__(self) -> None:
        if not self.customer_id.strip():
            raise InvalidEntityError("Contract customer_id is required.")

    def is_active_at(self, moment: datetime) -> bool:
        return self.term.contains(moment)
