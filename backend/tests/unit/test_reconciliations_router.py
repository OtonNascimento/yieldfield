"""POST /reconciliations pre-generates the run id (decision C/E); GETs read the audit trail."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from yieldfield.api.main import create_app
from yieldfield.api.v1.dependencies.services import (
    RUN_RECONCILIATION_TASK,
    get_job_submitter,
    get_reconciliation_repository,
)
from yieldfield.api.v1.dependencies.settings import get_app_settings
from yieldfield.config.settings import Settings
from yieldfield.domain.reconciliation.reconciliation import Reconciliation
from yieldfield.domain.shared.ids import ReconciliationId, TenantId
from yieldfield.domain.shared.time_window import TimeWindow

AUTH = {"Authorization": "Bearer tok-1"}
WINDOW_JSON = {"start": "2026-01-01T00:00:00+00:00", "end": "2026-02-01T00:00:00+00:00"}
WINDOW = TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))


def _settings() -> Settings:
    return Settings(_env_file=None, api_tokens={"tok-1": "tenant-1"})


def _recon(recon_id: str, executed_at: datetime) -> Reconciliation:
    return Reconciliation(
        id=ReconciliationId(recon_id),
        tenant_id=TenantId("tenant-1"),
        window=WINDOW,
        currency="USD",
        executed_at=executed_at,
        rule_version="reconciliation-v1",
        findings=(),
    )


class FakeSubmitter:
    def __init__(self) -> None:
        self.submitted: list[tuple[TenantId, str, tuple[str, ...]]] = []

    def submit(self, tenant_id: TenantId, task_name: str, *task_args: str) -> str:
        self.submitted.append((tenant_id, task_name, task_args))
        return "job_x"


class FakeReconRepo:
    def __init__(self, reconciliations: Sequence[Reconciliation]) -> None:
        self._reconciliations = list(reconciliations)

    def get(
        self, tenant_id: TenantId, reconciliation_id: ReconciliationId
    ) -> Reconciliation | None:
        for r in self._reconciliations:
            if r.id == reconciliation_id:
                return r
        return None

    def list_for_tenant(self, tenant_id: TenantId) -> Sequence[Reconciliation]:
        return list(self._reconciliations)


def _app(submitter: FakeSubmitter, repo: FakeReconRepo | None = None) -> FastAPI:
    app = create_app(_settings())
    app.dependency_overrides[get_app_settings] = _settings
    app.dependency_overrides[get_job_submitter] = lambda: submitter
    app.dependency_overrides[get_reconciliation_repository] = lambda: repo or FakeReconRepo([])
    return app


def test_post_returns_202_and_pre_generates_the_reconciliation_id() -> None:
    submitter = FakeSubmitter()
    client = TestClient(_app(submitter))
    response = client.post("/api/v1/reconciliations", headers=AUTH, json={"window": WINDOW_JSON})
    assert response.status_code == 202
    assert response.json() == {"job_id": "job_x"}
    _tenant, task_name, args = submitter.submitted[0]
    assert task_name == RUN_RECONCILIATION_TASK
    assert args[0] == "2026-01-01T00:00:00+00:00"
    assert args[2].startswith("rec_")  # pre-generated so worker retries converge (decision C/E)


def test_get_by_id_returns_the_financial_read() -> None:
    repo = FakeReconRepo([_recon("rec_1", datetime(2026, 3, 1, tzinfo=UTC))])
    client = TestClient(_app(FakeSubmitter(), repo))
    response = client.get("/api/v1/reconciliations/rec_1", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "rec_1"
    assert body["total_leakage"] == {"amount": "0", "currency": "USD"}
    assert body["rule_version"] == "reconciliation-v1"


def test_get_missing_is_404() -> None:
    client = TestClient(_app(FakeSubmitter()))
    response = client.get("/api/v1/reconciliations/nope", headers=AUTH)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_list_is_newest_first_and_paginated() -> None:
    repo = FakeReconRepo(
        [
            _recon("rec_old", datetime(2026, 1, 5, tzinfo=UTC)),
            _recon("rec_new", datetime(2026, 3, 5, tzinfo=UTC)),
            _recon("rec_mid", datetime(2026, 2, 5, tzinfo=UTC)),
        ]
    )
    client = TestClient(_app(FakeSubmitter(), repo))
    response = client.get("/api/v1/reconciliations?limit=2", headers=AUTH)
    body = response.json()
    assert [r["id"] for r in body["items"]] == ["rec_new", "rec_mid"]  # newest first (§5.2)
    assert body["meta"]["next_cursor"] is not None


def test_reconciliations_require_bearer_auth() -> None:
    client = TestClient(_app(FakeSubmitter()))
    assert client.post("/api/v1/reconciliations", json={"window": WINDOW_JSON}).status_code == 401
