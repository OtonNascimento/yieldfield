"""Finding DTOs (spec §5.3): dollars + explanations out; internal lineage stays in (§2)."""

from __future__ import annotations

from pydantic import BaseModel

from yieldfield.api.v1.schemas.common import MoneyRead, PageMeta
from yieldfield.domain.findings.finding import Finding
from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.findings.severity import Severity


class FindingRead(BaseModel):
    id: str
    reconciliation_id: str
    customer_id: str
    metric: str
    leakage_type: LeakageType
    severity: Severity
    status: RecoveryStatus
    amount: MoneyRead
    explanation: str

    @classmethod
    def from_finding(cls, finding: Finding) -> FindingRead:
        return cls(
            id=str(finding.id),
            reconciliation_id=str(finding.reconciliation_id),
            customer_id=finding.customer_id,
            metric=finding.metric,
            leakage_type=finding.leakage_type,
            severity=finding.severity,
            status=finding.status,
            amount=MoneyRead.from_money(finding.amount),
            explanation=finding.explanation,
        )


class FindingPage(BaseModel):
    items: list[FindingRead]
    meta: PageMeta
