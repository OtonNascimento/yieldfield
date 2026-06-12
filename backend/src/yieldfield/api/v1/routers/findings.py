"""Findings reads + explicit lifecycle routes (spec §5.2, decision D).

Four explicit POST routes — review/confirm/dismiss/recover — each mapping 1:1 to a domain
transition, all behind the single TransitionFinding use-case (§4.3). Illegal transitions
are 409 (`invalid_finding_transition`); the use-case guarantees nothing persists on an
illegal request.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from yieldfield.api.v1.dependencies.auth import CurrentTenant
from yieldfield.api.v1.dependencies.pagination import PageParamsDep, paginate
from yieldfield.api.v1.dependencies.services import FindingRepo
from yieldfield.api.v1.schemas.common import PageMeta
from yieldfield.api.v1.schemas.findings import FindingPage, FindingRead
from yieldfield.application.errors import EntityNotFoundError
from yieldfield.application.findings.transition_finding import TransitionFinding
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.shared.ids import FindingId, ReconciliationId, TenantId

router = APIRouter(prefix="/findings", tags=["findings"])


@router.get("", summary="List findings for a reconciliation run", response_model=FindingPage)
def list_findings(
    tenant_id: CurrentTenant,
    findings: FindingRepo,
    page: PageParamsDep,
    reconciliation_id: Annotated[str, Query()],
) -> FindingPage:
    rows = findings.list_for_reconciliation(tenant_id, ReconciliationId(reconciliation_id))
    items, next_cursor = paginate(rows, page)
    return FindingPage(
        items=[FindingRead.from_finding(f) for f in items],
        meta=PageMeta(next_cursor=next_cursor),
    )


@router.get("/{finding_id}", summary="Read one finding", response_model=FindingRead)
def get_finding(finding_id: str, tenant_id: CurrentTenant, findings: FindingRepo) -> FindingRead:
    finding = findings.get(tenant_id, FindingId(finding_id))
    if finding is None:
        raise EntityNotFoundError(f"Finding {finding_id!r} not found.")
    return FindingRead.from_finding(finding)


def _transition(
    findings: FindingRepo, tenant_id: TenantId, finding_id: str, target: RecoveryStatus
) -> FindingRead:
    updated = TransitionFinding(findings).run(tenant_id, FindingId(finding_id), target)
    return FindingRead.from_finding(updated)


@router.post("/{finding_id}/review", summary="Mark reviewed", response_model=FindingRead)
def review(finding_id: str, tenant_id: CurrentTenant, findings: FindingRepo) -> FindingRead:
    return _transition(findings, tenant_id, finding_id, RecoveryStatus.REVIEWED)


@router.post("/{finding_id}/confirm", summary="Confirm leakage", response_model=FindingRead)
def confirm(finding_id: str, tenant_id: CurrentTenant, findings: FindingRepo) -> FindingRead:
    return _transition(findings, tenant_id, finding_id, RecoveryStatus.CONFIRMED)


@router.post("/{finding_id}/dismiss", summary="Dismiss finding", response_model=FindingRead)
def dismiss(finding_id: str, tenant_id: CurrentTenant, findings: FindingRepo) -> FindingRead:
    return _transition(findings, tenant_id, finding_id, RecoveryStatus.DISMISSED)


@router.post("/{finding_id}/recover", summary="Mark dollars recovered", response_model=FindingRead)
def recover(finding_id: str, tenant_id: CurrentTenant, findings: FindingRepo) -> FindingRead:
    return _transition(findings, tenant_id, finding_id, RecoveryStatus.RECOVERED)
