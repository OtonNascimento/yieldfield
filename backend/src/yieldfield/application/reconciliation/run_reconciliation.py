"""Run reconciliation (§4.2) — orchestration over the pure matching rules.

Loads the tenant's invoices + usage for a window, attributes the correct plan per customer from
their contracts, runs the pure `reconcile_customer` per (customer, invoice) — selecting that
customer's usage whose `occurred_at` falls within the invoice's billing period — and persists one
immutable `Reconciliation` (decision C). Idempotency on `reconciliation_id` is the repository's
job (§8); a fresh id is a new historical run. Job-unaware (§3).

Simplifications (this slice; named, not silent): a customer's plans are taken from all of that
customer's contracts (last contract wins per metric — term-based disambiguation is future work);
currency is taken from the window's invoices, defaulting to USD for an empty window (§4.2);
uninvoiced usage and mixed-currency are out of scope (§13); invoice selection partitions by
`period_start` — an invoice reconciles in the window containing its `period_start`, so contiguous
windows reconcile every invoice exactly once (ingestion pulls by period *overlap*, which is
broader by design) — and usage is loaded over the span covering every selected invoice's full
billing period, so a period extending past `window.end` still reconciles against all its usage.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from uuid import uuid4

from yieldfield.domain.billing.invoice import Invoice
from yieldfield.domain.billing.plan import Plan
from yieldfield.domain.billing.repositories import (
    ContractRepository,
    InvoiceRepository,
    PlanRepository,
)
from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.billing.usage_event_store import UsageEventStore
from yieldfield.domain.findings.finding import Finding
from yieldfield.domain.reconciliation.matching import DEFAULT_RULE_VERSION, reconcile_customer
from yieldfield.domain.reconciliation.reconciliation import Reconciliation
from yieldfield.domain.reconciliation.repositories import ReconciliationRepository
from yieldfield.domain.shared.ids import FindingId, ReconciliationId, TenantId
from yieldfield.domain.shared.time_window import TimeWindow

_DEFAULT_CURRENCY = "USD"


def _default_finding_id() -> FindingId:
    return FindingId(str(uuid4()))


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _usage_coverage_window(window: TimeWindow, invoices: Sequence[Invoice]) -> TimeWindow:
    """The span usage must be loaded over so every selected invoice sees its FULL
    billing period (§4.2): selection is by period_start ∈ window, but a period may
    extend past window.end — usage in that tail belongs to the invoice."""
    if not invoices:
        return window
    start = min(window.start, min(inv.period.start for inv in invoices))
    end = max(window.end, max(inv.period.end for inv in invoices))
    return TimeWindow(start, end)


class RunReconciliation:
    def __init__(
        self,
        invoices: InvoiceRepository,
        usage_events: UsageEventStore,
        contracts: ContractRepository,
        plans: PlanRepository,
        reconciliations: ReconciliationRepository,
        *,
        finding_id_factory: Callable[[], FindingId] = _default_finding_id,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._invoices = invoices
        self._usage_events = usage_events
        self._contracts = contracts
        self._plans = plans
        self._reconciliations = reconciliations
        self._finding_id_factory = finding_id_factory
        self._clock = clock

    def run(
        self,
        tenant_id: TenantId,
        window: TimeWindow,
        reconciliation_id: ReconciliationId,
        rule_version: str = DEFAULT_RULE_VERSION,
    ) -> Reconciliation:
        """Reconcile `window` for `tenant_id`, persist one Reconciliation, and return it."""
        invoices = list(self._invoices.list_in_window(tenant_id, window))
        invoices_by_customer = self._group_by_customer(invoices)
        usage_by_customer = self._usage_by_customer(
            tenant_id, _usage_coverage_window(window, invoices)
        )

        findings: list[Finding] = []
        for customer_id, customer_invoices in invoices_by_customer.items():
            plans_by_metric = self._plans_for_customer(tenant_id, customer_id)
            if not plans_by_metric:
                continue  # no known pricing for this customer — skip (unpriced usage is future work)
            customer_usage = usage_by_customer.get(customer_id, [])
            # Precondition: a customer's invoice periods do not overlap (true for Stripe billing
            # periods). An event is attributed to every invoice whose period contains it, so
            # overlapping periods would double-count the same usage across invoices.
            for invoice in customer_invoices:
                events_in_period = [
                    event for event in customer_usage if invoice.period.contains(event.occurred_at)
                ]
                findings.extend(
                    reconcile_customer(
                        tenant_id=tenant_id,
                        reconciliation_id=reconciliation_id,
                        customer_id=customer_id,
                        usage_events=events_in_period,
                        invoice=invoice,
                        plans_by_metric=plans_by_metric,
                        id_factory=self._finding_id_factory,
                        rule_version=rule_version,
                    )
                )

        currency = invoices[0].currency if invoices else _DEFAULT_CURRENCY
        reconciliation = Reconciliation(
            id=reconciliation_id,
            tenant_id=tenant_id,
            window=window,
            currency=currency,
            executed_at=self._clock(),
            rule_version=rule_version,
            findings=tuple(findings),
        )
        self._reconciliations.add(tenant_id, reconciliation)
        return reconciliation

    @staticmethod
    def _group_by_customer(invoices: Sequence[Invoice]) -> dict[str, list[Invoice]]:
        grouped: dict[str, list[Invoice]] = {}
        for invoice in invoices:
            grouped.setdefault(invoice.customer_id, []).append(invoice)
        return grouped

    def _usage_by_customer(
        self, tenant_id: TenantId, window: TimeWindow
    ) -> dict[str, list[UsageEvent]]:
        usage_by_customer: dict[str, list[UsageEvent]] = {}
        for event in self._usage_events.query(tenant_id, window):
            usage_by_customer.setdefault(event.customer_id, []).append(event)
        return usage_by_customer

    def _plans_for_customer(self, tenant_id: TenantId, customer_id: str) -> dict[str, Plan]:
        plans_by_metric: dict[str, Plan] = {}
        for contract in self._contracts.list_for_customer(tenant_id, customer_id):
            plan = self._plans.get(tenant_id, contract.plan_id)
            if plan is not None:
                plans_by_metric[plan.metric] = plan
        return plans_by_metric
