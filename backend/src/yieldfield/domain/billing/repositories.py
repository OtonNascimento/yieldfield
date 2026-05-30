"""OLTP repository ports for the billing aggregates (§12). Pure Protocols.

Placed beside their aggregates, mirroring `connector_port.py`. Every tenant-owned
method takes `tenant_id`; there is no cross-tenant accessor (§11). Infrastructure
implements these in `infrastructure/persistence/`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from yieldfield.domain.billing.contract import Contract
from yieldfield.domain.billing.invoice import Invoice
from yieldfield.domain.billing.plan import Plan
from yieldfield.domain.billing.tenant import Tenant
from yieldfield.domain.shared.ids import ContractId, InvoiceId, PlanId, TenantId
from yieldfield.domain.shared.time_window import TimeWindow


@runtime_checkable
class TenantRepository(Protocol):
    def add(self, tenant: Tenant) -> None: ...
    def get(self, tenant_id: TenantId) -> Tenant | None: ...


@runtime_checkable
class PlanRepository(Protocol):
    def add(self, tenant_id: TenantId, plan: Plan) -> None: ...
    def get(self, tenant_id: TenantId, plan_id: PlanId) -> Plan | None: ...
    def list_for_tenant(self, tenant_id: TenantId) -> Sequence[Plan]: ...


@runtime_checkable
class ContractRepository(Protocol):
    def add(self, tenant_id: TenantId, contract: Contract) -> None: ...
    def get(self, tenant_id: TenantId, contract_id: ContractId) -> Contract | None: ...
    def list_for_customer(self, tenant_id: TenantId, customer_id: str) -> Sequence[Contract]: ...


@runtime_checkable
class InvoiceRepository(Protocol):
    def add(self, tenant_id: TenantId, invoice: Invoice) -> None: ...
    def get(self, tenant_id: TenantId, invoice_id: InvoiceId) -> Invoice | None: ...
    def list_in_window(self, tenant_id: TenantId, window: TimeWindow) -> Sequence[Invoice]: ...
