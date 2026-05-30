"""Finding repository port (§12). Findings are created via the Reconciliation
aggregate; this port reads them and persists lifecycle changes (status). Pure Protocol.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from yieldfield.domain.findings.finding import Finding
from yieldfield.domain.shared.ids import FindingId, ReconciliationId, TenantId


@runtime_checkable
class FindingRepository(Protocol):
    def get(self, tenant_id: TenantId, finding_id: FindingId) -> Finding | None: ...
    def list_for_reconciliation(
        self, tenant_id: TenantId, reconciliation_id: ReconciliationId
    ) -> Sequence[Finding]: ...
    def update(self, tenant_id: TenantId, finding: Finding) -> None: ...
