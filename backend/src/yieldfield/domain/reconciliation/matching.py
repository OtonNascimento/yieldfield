"""Usage-to-invoice reconciliation matching rules (§4 CORE) — pure logic.

For each (customer, metric) the rule compares what was *used* against what was
*billed*, given the plan's pricing, and emits Findings for two leakage dimensions:

  * unbilled_usage     — used quantity exceeds billed quantity (a quantity gap)
  * misrated_line_item — the billed quantity was priced below the plan (a price gap)

The two are orthogonal and together equal the total shortfall (expected - billed), so
the same dollar is never counted twice. Severity here is a deterministic placeholder
(`provisional_severity`); the probabilistic engine refines it in Slice 5 (§6.4).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal

from yieldfield.domain.billing.invoice import Invoice
from yieldfield.domain.billing.plan import Plan
from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.findings.finding import Finding, FindingLineage
from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.findings.severity import Severity
from yieldfield.domain.shared.ids import FindingId, ReconciliationId, TenantId
from yieldfield.domain.shared.money import Money

DEFAULT_RULE_VERSION = "reconciliation-v1"

# Severity bands by absolute leakage size. Provisional until scoring (Slice 5, §6.4).
_CRITICAL_AT = Decimal("1000")
_HIGH_AT = Decimal("100")
_MEDIUM_AT = Decimal("10")


def provisional_severity(amount: Money) -> Severity:
    """A deterministic severity from leakage size, used until scoring lands (§6.4)."""
    magnitude = abs(amount.amount)
    if magnitude >= _CRITICAL_AT:
        return Severity.CRITICAL
    if magnitude >= _HIGH_AT:
        return Severity.HIGH
    if magnitude >= _MEDIUM_AT:
        return Severity.MEDIUM
    if magnitude > 0:
        return Severity.LOW
    return Severity.GOOD


def reconcile_customer(
    *,
    tenant_id: TenantId,
    reconciliation_id: ReconciliationId,
    customer_id: str,
    usage_events: Sequence[UsageEvent],
    invoice: Invoice,
    plans_by_metric: Mapping[str, Plan],
    id_factory: Callable[[], FindingId],
    rule_version: str = DEFAULT_RULE_VERSION,
    severity_policy: Callable[[Money], Severity] = provisional_severity,
) -> list[Finding]:
    """Reconcile one customer's usage against one invoice, returning new Findings."""
    findings: list[Finding] = []
    metrics = sorted(
        {event.metric for event in usage_events} | {item.metric for item in invoice.line_items}
    )

    for metric in metrics:
        plan = plans_by_metric.get(metric)
        if plan is None:
            # No pricing known for this metric — expected charge is undeterminable. A
            # dedicated "unpriced usage" rule is a future strategy (§17).
            continue

        events = [event for event in usage_events if event.metric == metric]
        line_items = invoice.line_items_for_metric(metric)
        used_quantity = sum((event.quantity for event in events), Decimal(0))
        billed_quantity = sum((item.quantity for item in line_items), Decimal(0))
        billed_amount = Money.zero(invoice.currency)
        for item in line_items:
            billed_amount = billed_amount + item.amount

        # 1) Quantity gap: usage beyond what was billed.
        unbilled_quantity = used_quantity - billed_quantity
        if unbilled_quantity > 0:
            amount = plan.expected_charge(unbilled_quantity)
            if amount.is_positive:
                findings.append(
                    Finding(
                        id=id_factory(),
                        tenant_id=tenant_id,
                        reconciliation_id=reconciliation_id,
                        customer_id=customer_id,
                        metric=metric,
                        leakage_type=LeakageType.UNBILLED_USAGE,
                        severity=severity_policy(amount),
                        amount=amount,
                        status=RecoveryStatus.NEW,
                        lineage=FindingLineage(
                            rule_version=rule_version,
                            usage_event_ids=tuple(event.id for event in events),
                        ),
                        explanation=(
                            f"{unbilled_quantity} {metric} for {customer_id} were not "
                            f"billed (expected {amount})."
                        ),
                    )
                )

        # 2) Price gap: the billed quantity was charged below the plan rate.
        if billed_quantity > 0:
            expected_for_billed = plan.expected_charge(billed_quantity)
            shortfall = expected_for_billed - billed_amount
            if shortfall.is_positive:
                line_item_id = line_items[0].id if len(line_items) == 1 else None
                findings.append(
                    Finding(
                        id=id_factory(),
                        tenant_id=tenant_id,
                        reconciliation_id=reconciliation_id,
                        customer_id=customer_id,
                        metric=metric,
                        leakage_type=LeakageType.MISRATED_LINE_ITEM,
                        severity=severity_policy(shortfall),
                        amount=shortfall,
                        status=RecoveryStatus.NEW,
                        lineage=FindingLineage(
                            rule_version=rule_version,
                            usage_event_ids=tuple(event.id for event in events),
                            invoice_line_item_id=line_item_id,
                        ),
                        explanation=(
                            f"{metric} for {customer_id} was billed {billed_amount} but "
                            f"should be {expected_for_billed}."
                        ),
                    )
                )

    return findings
