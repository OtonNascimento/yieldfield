"""Transition a finding (§4.3) — the one DRY use-case behind the four explicit routes.

Loads the finding (→ EntityNotFoundError if absent), applies the domain lifecycle transition
(`Finding.transition_to`, which raises InvalidFindingTransitionError on an illegal edge), and
persists the result. The illegal-transition guard fires BEFORE `update`, so an invalid request
never writes (decision D). Job-unaware (§3).
"""

from __future__ import annotations

from yieldfield.application.errors import EntityNotFoundError
from yieldfield.domain.findings.finding import Finding
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.findings.repositories import FindingRepository
from yieldfield.domain.shared.ids import FindingId, TenantId


class TransitionFinding:
    def __init__(self, findings: FindingRepository) -> None:
        self._findings = findings

    def run(self, tenant_id: TenantId, finding_id: FindingId, target: RecoveryStatus) -> Finding:
        """Apply `target` to the finding and persist; return the updated finding."""
        finding = self._findings.get(tenant_id, finding_id)
        if finding is None:
            raise EntityNotFoundError(f"Finding {finding_id!r} not found.")
        updated = finding.transition_to(target)  # raises on an illegal transition, before any write
        self._findings.update(tenant_id, updated)
        return updated
