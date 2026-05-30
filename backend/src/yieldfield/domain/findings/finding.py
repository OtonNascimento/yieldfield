"""Finding — a dollar-valued, explainable, auditable leakage record (§4 CORE, §6.5).

Every Finding carries lineage (which inputs, which rule/model version) so any dollar
figure is reconstructable — no black-box numbers reach the user (§2, §6.5). Findings
are immutable; lifecycle changes return a new Finding (§4).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.findings.lifecycle import ensure_transition
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.findings.severity import Severity
from yieldfield.domain.shared.errors import InvalidEntityError
from yieldfield.domain.shared.ids import (
    FindingId,
    InvoiceLineItemId,
    ModelRunId,
    ReconciliationId,
    TenantId,
    UsageEventId,
)
from yieldfield.domain.shared.money import Money


@dataclass(frozen=True, slots=True)
class FindingLineage:
    """The provenance of a finding (§6.5): which inputs and which rule/model version."""

    rule_version: str
    usage_event_ids: tuple[UsageEventId, ...] = ()
    invoice_line_item_id: InvoiceLineItemId | None = None
    model_run_id: ModelRunId | None = None

    def __post_init__(self) -> None:
        if not self.rule_version.strip():
            raise InvalidEntityError("FindingLineage rule_version is required.")


@dataclass(frozen=True, slots=True)
class Finding:
    id: FindingId
    tenant_id: TenantId
    reconciliation_id: ReconciliationId
    customer_id: str
    metric: str
    leakage_type: LeakageType
    severity: Severity
    amount: Money
    status: RecoveryStatus
    lineage: FindingLineage
    explanation: str = field(default="")

    def __post_init__(self) -> None:
        if not self.amount.is_positive:
            raise InvalidEntityError("A finding's amount must be positive recoverable money.")
        if not self.explanation.strip():
            raise InvalidEntityError("A finding must carry a human-readable explanation (§2).")

    # ── lifecycle (§4) ───────────────────────────────────────────────────────
    def transition_to(self, target: RecoveryStatus) -> Finding:
        ensure_transition(self.status, target)
        return replace(self, status=target)

    def review(self) -> Finding:
        return self.transition_to(RecoveryStatus.REVIEWED)

    def confirm(self) -> Finding:
        return self.transition_to(RecoveryStatus.CONFIRMED)

    def recover(self) -> Finding:
        return self.transition_to(RecoveryStatus.RECOVERED)

    def dismiss(self) -> Finding:
        return self.transition_to(RecoveryStatus.DISMISSED)
