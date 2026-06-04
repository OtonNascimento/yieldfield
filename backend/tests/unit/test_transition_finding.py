"""TransitionFinding loads, applies a domain transition, and persists (§4.3)."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from yieldfield.application.errors import EntityNotFoundError
from yieldfield.application.findings.transition_finding import TransitionFinding
from yieldfield.domain.findings.finding import Finding, FindingLineage
from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.findings.severity import Severity
from yieldfield.domain.shared.errors import InvalidFindingTransitionError
from yieldfield.domain.shared.ids import FindingId, ReconciliationId, TenantId
from yieldfield.domain.shared.money import Money

TENANT = TenantId("t_1")


def _finding(status: RecoveryStatus = RecoveryStatus.NEW) -> Finding:
    return Finding(
        id=FindingId("f_1"),
        tenant_id=TENANT,
        reconciliation_id=ReconciliationId("r_1"),
        customer_id="cus_1",
        metric="api_calls",
        leakage_type=LeakageType.UNBILLED_USAGE,
        severity=Severity.LOW,
        amount=Money.of("10.00", "USD"),
        status=status,
        lineage=FindingLineage(rule_version="reconciliation-v1"),
        explanation="10 api_calls were not billed.",
    )


class FakeFindingRepo:
    def __init__(self, finding: Finding | None) -> None:
        self._finding = finding
        self.updated: list[Finding] = []

    def get(self, tenant_id: TenantId, finding_id: FindingId) -> Finding | None:
        if self._finding is not None and self._finding.id == finding_id:
            return self._finding
        return None

    def list_for_reconciliation(
        self, tenant_id: TenantId, reconciliation_id: ReconciliationId
    ) -> Sequence[Finding]:
        return [] if self._finding is None else [self._finding]

    def update(self, tenant_id: TenantId, finding: Finding) -> None:
        self.updated.append(finding)


def test_review_transitions_new_to_reviewed_and_persists() -> None:
    repo = FakeFindingRepo(_finding(RecoveryStatus.NEW))
    result = TransitionFinding(repo).run(TENANT, FindingId("f_1"), RecoveryStatus.REVIEWED)
    assert result.status is RecoveryStatus.REVIEWED
    assert repo.updated == [result]


def test_missing_finding_raises_entity_not_found() -> None:
    repo = FakeFindingRepo(None)
    with pytest.raises(EntityNotFoundError, match="f_1"):
        TransitionFinding(repo).run(TENANT, FindingId("f_1"), RecoveryStatus.REVIEWED)


def test_illegal_transition_raises_and_does_not_persist() -> None:
    repo = FakeFindingRepo(_finding(RecoveryStatus.NEW))
    # NEW -> CONFIRMED is illegal (must go through REVIEWED, decision D).
    with pytest.raises(InvalidFindingTransitionError):
        TransitionFinding(repo).run(TENANT, FindingId("f_1"), RecoveryStatus.CONFIRMED)
    assert repo.updated == []
