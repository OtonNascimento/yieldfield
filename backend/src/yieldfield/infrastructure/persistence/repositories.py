"""SQLAlchemy implementations of the domain repository ports (§12).

Tenant scoping (§11) is enforced here: every read filters by `tenant_id`, and every
write guards that the entity's `tenant_id` matches the caller's scope. Sessions are
injected; the caller owns the transaction boundary (application layer, Slice 3).
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from yieldfield.domain.billing.connector import Connector
from yieldfield.domain.billing.contract import Contract
from yieldfield.domain.billing.invoice import Invoice
from yieldfield.domain.billing.plan import Plan
from yieldfield.domain.billing.tenant import Tenant
from yieldfield.domain.findings.finding import Finding
from yieldfield.domain.reconciliation.reconciliation import Reconciliation
from yieldfield.domain.shared.ids import (
    ConnectorId,
    ContractId,
    FindingId,
    InvoiceId,
    PlanId,
    ReconciliationId,
    TenantId,
)
from yieldfield.domain.shared.time_window import TimeWindow
from yieldfield.infrastructure.persistence import mappers
from yieldfield.infrastructure.persistence.errors import PersistenceError
from yieldfield.infrastructure.persistence.models import (
    ConnectorRow,
    ContractRow,
    FindingRow,
    InvoiceRow,
    PlanRow,
    ReconciliationRow,
    TenantRow,
)


def _guard(scope: TenantId, entity_tenant: str) -> None:
    if str(scope) != str(entity_tenant):
        raise PersistenceError(
            f"entity tenant_id {entity_tenant!r} does not match scope {scope!r} (§11)."
        )


class SqlAlchemyTenantRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, tenant: Tenant) -> None:
        self._session.add(mappers.tenant_row(tenant))

    def get(self, tenant_id: TenantId) -> Tenant | None:
        row = self._session.get(TenantRow, str(tenant_id))
        return mappers.to_tenant(row) if row is not None else None


class SqlAlchemyPlanRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, tenant_id: TenantId, plan: Plan) -> None:
        _guard(tenant_id, plan.tenant_id)
        self._session.add(mappers.plan_row(plan))

    def get(self, tenant_id: TenantId, plan_id: PlanId) -> Plan | None:
        row = self._session.scalars(
            select(PlanRow).where(PlanRow.id == str(plan_id), PlanRow.tenant_id == str(tenant_id))
        ).first()
        return mappers.to_plan(row) if row is not None else None

    def list_for_tenant(self, tenant_id: TenantId) -> Sequence[Plan]:
        rows = self._session.scalars(
            select(PlanRow).where(PlanRow.tenant_id == str(tenant_id)).order_by(PlanRow.id)
        ).all()
        return [mappers.to_plan(r) for r in rows]


class SqlAlchemyContractRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, tenant_id: TenantId, contract: Contract) -> None:
        _guard(tenant_id, contract.tenant_id)
        self._session.add(mappers.contract_row(contract))

    def get(self, tenant_id: TenantId, contract_id: ContractId) -> Contract | None:
        row = self._session.scalars(
            select(ContractRow).where(
                ContractRow.id == str(contract_id), ContractRow.tenant_id == str(tenant_id)
            )
        ).first()
        return mappers.to_contract(row) if row is not None else None

    def list_for_customer(self, tenant_id: TenantId, customer_id: str) -> Sequence[Contract]:
        rows = self._session.scalars(
            select(ContractRow)
            .where(ContractRow.tenant_id == str(tenant_id), ContractRow.customer_id == customer_id)
            .order_by(ContractRow.id)
        ).all()
        return [mappers.to_contract(r) for r in rows]


class SqlAlchemyInvoiceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, tenant_id: TenantId, invoice: Invoice) -> None:
        _guard(tenant_id, invoice.tenant_id)
        self._session.add(mappers.invoice_row(invoice))

    def get(self, tenant_id: TenantId, invoice_id: InvoiceId) -> Invoice | None:
        row = self._session.scalars(
            select(InvoiceRow).where(
                InvoiceRow.id == str(invoice_id), InvoiceRow.tenant_id == str(tenant_id)
            )
        ).first()
        return mappers.to_invoice(row) if row is not None else None

    def list_in_window(self, tenant_id: TenantId, window: TimeWindow) -> Sequence[Invoice]:
        rows = self._session.scalars(
            select(InvoiceRow)
            .where(
                InvoiceRow.tenant_id == str(tenant_id),
                InvoiceRow.period_start >= window.start,
                InvoiceRow.period_start < window.end,
            )
            .order_by(InvoiceRow.id)
        ).all()
        return [mappers.to_invoice(r) for r in rows]


class SqlAlchemyReconciliationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, tenant_id: TenantId, reconciliation: Reconciliation) -> None:
        _guard(tenant_id, reconciliation.tenant_id)
        self._session.add(mappers.reconciliation_row(reconciliation))

    def get(
        self, tenant_id: TenantId, reconciliation_id: ReconciliationId
    ) -> Reconciliation | None:
        row = self._session.scalars(
            select(ReconciliationRow).where(
                ReconciliationRow.id == str(reconciliation_id),
                ReconciliationRow.tenant_id == str(tenant_id),
            )
        ).first()
        return mappers.to_reconciliation(row) if row is not None else None

    def list_for_tenant(self, tenant_id: TenantId) -> Sequence[Reconciliation]:
        rows = self._session.scalars(
            select(ReconciliationRow)
            .where(ReconciliationRow.tenant_id == str(tenant_id))
            .order_by(ReconciliationRow.id)
        ).all()
        return [mappers.to_reconciliation(r) for r in rows]


class SqlAlchemyFindingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, tenant_id: TenantId, finding_id: FindingId) -> Finding | None:
        row = self._session.scalars(
            select(FindingRow).where(
                FindingRow.id == str(finding_id), FindingRow.tenant_id == str(tenant_id)
            )
        ).first()
        return mappers.to_finding(row) if row is not None else None

    def list_for_reconciliation(
        self, tenant_id: TenantId, reconciliation_id: ReconciliationId
    ) -> Sequence[Finding]:
        rows = self._session.scalars(
            select(FindingRow)
            .where(
                FindingRow.tenant_id == str(tenant_id),
                FindingRow.reconciliation_id == str(reconciliation_id),
            )
            .order_by(FindingRow.id)
        ).all()
        return [mappers.to_finding(r) for r in rows]

    def update(self, tenant_id: TenantId, finding: Finding) -> None:
        _guard(tenant_id, finding.tenant_id)
        row = self._session.scalars(
            select(FindingRow).where(
                FindingRow.id == str(finding.id), FindingRow.tenant_id == str(tenant_id)
            )
        ).first()
        if row is None:
            raise PersistenceError(f"Finding {finding.id!r} not found for tenant {tenant_id!r}.")
        row.status = finding.status.value
        row.severity = finding.severity.value
        row.amount_amount = mappers._storable(finding.amount.amount, "amount")
        row.amount_currency = finding.amount.currency
        row.explanation = finding.explanation


class SqlAlchemyConnectorRepository:
    """Connector config + encrypted-credential persistence (the infra ConnectorStore, §2.1)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, tenant_id: TenantId, connector: Connector, encrypted_credentials: bytes) -> None:
        _guard(tenant_id, connector.tenant_id)
        self._session.add(mappers.connector_row(connector, encrypted_credentials))

    def get(self, tenant_id: TenantId, connector_id: ConnectorId) -> Connector | None:
        row = self._session.scalars(
            select(ConnectorRow).where(
                ConnectorRow.id == str(connector_id),
                ConnectorRow.tenant_id == str(tenant_id),
            )
        ).first()
        return mappers.to_connector(row) if row is not None else None

    def list_for_tenant(self, tenant_id: TenantId) -> Sequence[Connector]:
        rows = self._session.scalars(
            select(ConnectorRow)
            .where(ConnectorRow.tenant_id == str(tenant_id))
            .order_by(ConnectorRow.id)
        ).all()
        return [mappers.to_connector(r) for r in rows]

    def load_credentials(self, tenant_id: TenantId, connector_id: ConnectorId) -> bytes | None:
        row = self._session.scalars(
            select(ConnectorRow).where(
                ConnectorRow.id == str(connector_id),
                ConnectorRow.tenant_id == str(tenant_id),
            )
        ).first()
        return row.encrypted_credentials if row is not None else None

    def find_by_id(self, connector_id: ConnectorId) -> Connector | None:
        """Resolve a connector (incl. its tenant) by id alone — the webhook-ingress
        resolver (§6). This is the single deliberate non-tenant-prescoped read; the id is
        the routing key and the webhook signature gates processing (§11)."""
        row = self._session.get(ConnectorRow, str(connector_id))
        return mappers.to_connector(row) if row is not None else None
