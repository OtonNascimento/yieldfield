"""Reconciliation repository port (§12). The reconciliation is the aggregate root:
persisting it persists its findings; loading it reconstructs them. Pure Protocol.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from yieldfield.domain.reconciliation.reconciliation import Reconciliation
from yieldfield.domain.shared.ids import ReconciliationId, TenantId


@runtime_checkable
class ReconciliationRepository(Protocol):
    def add(self, tenant_id: TenantId, reconciliation: Reconciliation) -> None: ...
    def get(
        self, tenant_id: TenantId, reconciliation_id: ReconciliationId
    ) -> Reconciliation | None: ...
    def list_for_tenant(self, tenant_id: TenantId) -> Sequence[Reconciliation]: ...
