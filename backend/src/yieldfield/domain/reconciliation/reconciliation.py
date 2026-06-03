"""Reconciliation (§8 glossary) — the result of one usage-to-invoice run.

Aggregates the findings produced for a tenant over a window and totals the recoverable
leakage in dollars (§2). Job orchestration/state (resumable, idempotent) is an
application/worker concern (§13), added in Slice 3; this is the pure result entity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from yieldfield.domain.findings.finding import Finding
from yieldfield.domain.shared.ids import ReconciliationId, TenantId
from yieldfield.domain.shared.money import Money
from yieldfield.domain.shared.time_window import TimeWindow


@dataclass(frozen=True, slots=True)
class Reconciliation:
    id: ReconciliationId
    tenant_id: TenantId
    window: TimeWindow
    currency: str
    executed_at: datetime
    rule_version: str
    findings: tuple[Finding, ...] = ()

    def total_leakage(self) -> Money:
        """Total recoverable leakage across all findings (§2). Currency-checked."""
        total = Money.zero(self.currency)
        for finding in self.findings:
            total = total + finding.amount
        return total

    @property
    def finding_count(self) -> int:
        return len(self.findings)
