"""The domain persistence ports are pure, runtime-checkable Protocols (§11, §12)."""

from __future__ import annotations

from typing import get_type_hints

from yieldfield.domain.billing.repositories import (
    ContractRepository,
    InvoiceRepository,
    PlanRepository,
    TenantRepository,
)
from yieldfield.domain.billing.usage_event_store import UsageEventStore
from yieldfield.domain.findings.repositories import FindingRepository
from yieldfield.domain.reconciliation.repositories import ReconciliationRepository


def test_all_read_write_methods_require_tenant_scope() -> None:
    # Every method except TenantRepository.add/get carries an explicit tenant_id arg.
    assert "tenant_id" in get_type_hints(PlanRepository.get)
    assert "tenant_id" in get_type_hints(InvoiceRepository.list_in_window)
    assert "tenant_id" in get_type_hints(UsageEventStore.query)
    assert "tenant_id" in get_type_hints(FindingRepository.list_for_reconciliation)
    assert "tenant_id" in get_type_hints(ReconciliationRepository.add)
    assert "tenant_id" in get_type_hints(ContractRepository.list_for_customer)


def test_a_conforming_stub_satisfies_the_protocol() -> None:
    class _Tenants:
        def add(self, tenant: object) -> None: ...
        def get(self, tenant_id: object) -> object: ...

    assert isinstance(_Tenants(), TenantRepository)
