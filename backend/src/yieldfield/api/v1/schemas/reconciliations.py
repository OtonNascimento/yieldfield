"""Reconciliation DTOs (spec §5.2/§5.3): the financial-audit read surface."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from yieldfield.api.v1.schemas.common import MoneyRead, PageMeta, WindowParam, WindowRead
from yieldfield.domain.reconciliation.reconciliation import Reconciliation


class ReconciliationCreate(BaseModel):
    window: WindowParam


class ReconciliationRead(BaseModel):
    id: str
    window: WindowRead
    currency: str
    executed_at: datetime
    rule_version: str
    total_leakage: MoneyRead
    finding_count: int

    @classmethod
    def from_reconciliation(cls, reconciliation: Reconciliation) -> ReconciliationRead:
        return cls(
            id=str(reconciliation.id),
            window=WindowRead.from_window(reconciliation.window),
            currency=reconciliation.currency,
            executed_at=reconciliation.executed_at,
            rule_version=reconciliation.rule_version,
            total_leakage=MoneyRead.from_money(reconciliation.total_leakage()),
            finding_count=reconciliation.finding_count,
        )


class ReconciliationPage(BaseModel):
    items: list[ReconciliationRead]
    meta: PageMeta
