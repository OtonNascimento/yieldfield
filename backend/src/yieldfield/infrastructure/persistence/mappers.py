"""Pure ORM-row ↔ domain-entity mappers (§6.1 keeps the ORM out of the domain).

`_storable` guards the NUMERIC(38,12) boundary: a value with more than 12 fractional
digits would be silently rounded on insert, so we raise instead (§7 fail-loud).
"""

from __future__ import annotations

from decimal import Decimal

from yieldfield.domain.billing.contract import Contract
from yieldfield.domain.billing.invoice import Invoice, InvoiceLineItem
from yieldfield.domain.billing.plan import Plan
from yieldfield.domain.billing.tenant import Tenant
from yieldfield.domain.findings.finding import Finding, FindingLineage
from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.findings.severity import Severity
from yieldfield.domain.reconciliation.reconciliation import Reconciliation
from yieldfield.domain.shared.ids import (
    ContractId,
    FindingId,
    InvoiceId,
    InvoiceLineItemId,
    ModelRunId,
    PlanId,
    ReconciliationId,
    TenantId,
    UsageEventId,
)
from yieldfield.domain.shared.money import Money
from yieldfield.domain.shared.time_window import TimeWindow
from yieldfield.infrastructure.persistence.errors import PersistenceError
from yieldfield.infrastructure.persistence.models import (
    MONEY_SCALE,
    ContractRow,
    FindingRow,
    InvoiceLineItemRow,
    InvoiceRow,
    PlanRow,
    ReconciliationRow,
    TenantRow,
)


def _storable(value: Decimal, field: str) -> Decimal:
    """Reject values that would lose precision at NUMERIC(38,12) (§7)."""
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        raise PersistenceError(f"{field}={value!r} is not a finite decimal.")
    if -exponent > MONEY_SCALE:
        raise PersistenceError(
            f"{field}={value} has more than {MONEY_SCALE} fractional digits and cannot be "
            f"stored without precision loss (§7)."
        )
    return value


# ── Tenant ───────────────────────────────────────────────────────────────────
def tenant_row(tenant: Tenant) -> TenantRow:
    return TenantRow(id=tenant.id, name=tenant.name)


def to_tenant(row: TenantRow) -> Tenant:
    return Tenant(id=TenantId(row.id), name=row.name)


# ── Plan ─────────────────────────────────────────────────────────────────────
def plan_row(plan: Plan) -> PlanRow:
    return PlanRow(
        id=plan.id,
        tenant_id=plan.tenant_id,
        name=plan.name,
        metric=plan.metric,
        unit_price_amount=_storable(plan.unit_price.amount, "unit_price"),
        unit_price_currency=plan.unit_price.currency,
    )


def to_plan(row: PlanRow) -> Plan:
    return Plan(
        id=PlanId(row.id),
        tenant_id=TenantId(row.tenant_id),
        name=row.name,
        metric=row.metric,
        unit_price=Money(row.unit_price_amount, row.unit_price_currency),
    )


# ── Contract ─────────────────────────────────────────────────────────────────
def contract_row(contract: Contract) -> ContractRow:
    return ContractRow(
        id=contract.id,
        tenant_id=contract.tenant_id,
        customer_id=contract.customer_id,
        plan_id=contract.plan_id,
        term_start=contract.term.start,
        term_end=contract.term.end,
    )


def to_contract(row: ContractRow) -> Contract:
    return Contract(
        id=ContractId(row.id),
        tenant_id=TenantId(row.tenant_id),
        customer_id=row.customer_id,
        plan_id=PlanId(row.plan_id),
        term=TimeWindow(row.term_start, row.term_end),
    )


# ── Invoice ──────────────────────────────────────────────────────────────────
def invoice_row(invoice: Invoice) -> InvoiceRow:
    row = InvoiceRow(
        id=invoice.id,
        tenant_id=invoice.tenant_id,
        customer_id=invoice.customer_id,
        period_start=invoice.period.start,
        period_end=invoice.period.end,
        currency=invoice.currency,
    )
    row.line_items = [
        InvoiceLineItemRow(
            id=item.id,
            invoice_id=invoice.id,
            tenant_id=invoice.tenant_id,
            metric=item.metric,
            quantity=_storable(item.quantity, "quantity"),
            amount_amount=_storable(item.amount.amount, "amount"),
            amount_currency=item.amount.currency,
        )
        for item in invoice.line_items
    ]
    return row


def to_invoice(row: InvoiceRow) -> Invoice:
    items = tuple(
        InvoiceLineItem(
            id=InvoiceLineItemId(li.id),
            metric=li.metric,
            quantity=li.quantity,
            amount=Money(li.amount_amount, li.amount_currency),
        )
        for li in row.line_items
    )
    return Invoice(
        id=InvoiceId(row.id),
        tenant_id=TenantId(row.tenant_id),
        customer_id=row.customer_id,
        period=TimeWindow(row.period_start, row.period_end),
        currency=row.currency,
        line_items=items,
    )


# ── Finding / Reconciliation ─────────────────────────────────────────────────
def finding_row(finding: Finding, tenant_id: TenantId) -> FindingRow:
    return FindingRow(
        id=finding.id,
        tenant_id=tenant_id,
        reconciliation_id=finding.reconciliation_id,
        customer_id=finding.customer_id,
        metric=finding.metric,
        leakage_type=finding.leakage_type.value,
        severity=finding.severity.value,
        amount_amount=_storable(finding.amount.amount, "amount"),
        amount_currency=finding.amount.currency,
        status=finding.status.value,
        explanation=finding.explanation,
        lineage_rule_version=finding.lineage.rule_version,
        lineage_usage_event_ids=list(finding.lineage.usage_event_ids),
        lineage_invoice_line_item_id=finding.lineage.invoice_line_item_id,
        lineage_model_run_id=finding.lineage.model_run_id,
    )


def to_finding(row: FindingRow) -> Finding:
    lineage = FindingLineage(
        rule_version=row.lineage_rule_version,
        usage_event_ids=tuple(UsageEventId(x) for x in row.lineage_usage_event_ids),
        invoice_line_item_id=(
            InvoiceLineItemId(row.lineage_invoice_line_item_id)
            if row.lineage_invoice_line_item_id is not None
            else None
        ),
        model_run_id=(
            ModelRunId(row.lineage_model_run_id) if row.lineage_model_run_id is not None else None
        ),
    )
    return Finding(
        id=FindingId(row.id),
        tenant_id=TenantId(row.tenant_id),
        reconciliation_id=ReconciliationId(row.reconciliation_id),
        customer_id=row.customer_id,
        metric=row.metric,
        leakage_type=LeakageType(row.leakage_type),
        severity=Severity(row.severity),
        amount=Money(row.amount_amount, row.amount_currency),
        status=RecoveryStatus(row.status),
        lineage=lineage,
        explanation=row.explanation,
    )


def reconciliation_row(recon: Reconciliation) -> ReconciliationRow:
    row = ReconciliationRow(
        id=recon.id,
        tenant_id=recon.tenant_id,
        window_start=recon.window.start,
        window_end=recon.window.end,
        currency=recon.currency,
    )
    row.findings = [finding_row(f, TenantId(recon.tenant_id)) for f in recon.findings]
    return row


def to_reconciliation(row: ReconciliationRow) -> Reconciliation:
    return Reconciliation(
        id=ReconciliationId(row.id),
        tenant_id=TenantId(row.tenant_id),
        window=TimeWindow(row.window_start, row.window_end),
        currency=row.currency,
        findings=tuple(to_finding(fr) for fr in row.findings),
    )
