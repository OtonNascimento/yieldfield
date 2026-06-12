"""Findings reads + the four explicit lifecycle routes (decision D): one use-case behind them."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from yieldfield.api.main import create_app
from yieldfield.api.v1.dependencies.services import get_finding_repository
from yieldfield.api.v1.dependencies.settings import get_app_settings
from yieldfield.config.settings import Settings
from yieldfield.domain.findings.finding import Finding, FindingLineage
from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.findings.severity import Severity
from yieldfield.domain.shared.ids import FindingId, ReconciliationId, TenantId
from yieldfield.domain.shared.money import Money

AUTH = {"Authorization": "Bearer tok-1"}


def _settings() -> Settings:
    return Settings(_env_file=None, api_tokens={"tok-1": "tenant-1"})


def _finding(finding_id: str = "f_1", status: RecoveryStatus = RecoveryStatus.NEW) -> Finding:
    return Finding(
        id=FindingId(finding_id),
        tenant_id=TenantId("tenant-1"),
        reconciliation_id=ReconciliationId("rec_1"),
        customer_id="cus_1",
        metric="api_calls",
        leakage_type=LeakageType.UNBILLED_USAGE,
        severity=Severity.LOW,
        amount=Money.of("10.00", "USD"),
        status=status,
        lineage=FindingLineage(rule_version="reconciliation-v1"),
        explanation="100 api_calls were not billed.",
    )


class FakeFindingRepo:
    def __init__(self, findings: Sequence[Finding]) -> None:
        self._findings = {str(f.id): f for f in findings}
        self.updated: list[Finding] = []

    def get(self, tenant_id: TenantId, finding_id: FindingId) -> Finding | None:
        return self._findings.get(str(finding_id))

    def list_for_reconciliation(
        self, tenant_id: TenantId, reconciliation_id: ReconciliationId
    ) -> Sequence[Finding]:
        return [f for f in self._findings.values() if f.reconciliation_id == reconciliation_id]

    def update(self, tenant_id: TenantId, finding: Finding) -> None:
        self.updated.append(finding)
        self._findings[str(finding.id)] = finding


def _app(repo: FakeFindingRepo) -> FastAPI:
    app = create_app(_settings())
    app.dependency_overrides[get_app_settings] = _settings
    app.dependency_overrides[get_finding_repository] = lambda: repo
    return app


def test_list_findings_filters_by_reconciliation_id() -> None:
    client = TestClient(_app(FakeFindingRepo([_finding("f_1"), _finding("f_2")])))
    response = client.get("/api/v1/findings?reconciliation_id=rec_1", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert {f["id"] for f in body["items"]} == {"f_1", "f_2"}
    assert body["items"][0]["amount"] == {"amount": "10.00", "currency": "USD"}


def test_list_requires_the_reconciliation_id_filter() -> None:
    client = TestClient(_app(FakeFindingRepo([])))
    response = client.get("/api/v1/findings", headers=AUTH)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_get_finding_by_id() -> None:
    client = TestClient(_app(FakeFindingRepo([_finding()])))
    response = client.get("/api/v1/findings/f_1", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["explanation"] == "100 api_calls were not billed."


def test_get_missing_finding_is_404() -> None:
    client = TestClient(_app(FakeFindingRepo([])))
    response = client.get("/api/v1/findings/nope", headers=AUTH)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    ("action", "start", "expected"),
    [
        ("review", RecoveryStatus.NEW, "reviewed"),
        ("confirm", RecoveryStatus.REVIEWED, "confirmed"),
        ("dismiss", RecoveryStatus.NEW, "dismissed"),
        ("recover", RecoveryStatus.CONFIRMED, "recovered"),
    ],
)
def test_each_explicit_route_applies_its_transition_and_persists(
    action: str, start: RecoveryStatus, expected: str
) -> None:
    repo = FakeFindingRepo([_finding(status=start)])
    client = TestClient(_app(repo))
    response = client.post(f"/api/v1/findings/f_1/{action}", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["status"] == expected
    assert repo.updated[0].status.value == expected


def test_illegal_transition_is_409_and_not_persisted() -> None:
    repo = FakeFindingRepo([_finding(status=RecoveryStatus.NEW)])
    client = TestClient(_app(repo))
    response = client.post("/api/v1/findings/f_1/confirm", headers=AUTH)  # NEW→CONFIRMED illegal
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_finding_transition"
    assert repo.updated == []


def test_findings_require_bearer_auth() -> None:
    client = TestClient(_app(FakeFindingRepo([])))
    assert client.get("/api/v1/findings?reconciliation_id=rec_1").status_code == 401
