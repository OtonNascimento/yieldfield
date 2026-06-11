"""GET /jobs/{id}: the OLTP-backed poll surface for async work (spec §5.2)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from yieldfield.api.main import create_app
from yieldfield.api.v1.dependencies.services import get_job_repository
from yieldfield.api.v1.dependencies.settings import get_app_settings
from yieldfield.config.settings import Settings
from yieldfield.domain.shared.ids import TenantId
from yieldfield.infrastructure.persistence.job import Job, JobResultType, JobStatus, JobType

AUTH = {"Authorization": "Bearer tok-1"}


def _settings() -> Settings:
    return Settings(_env_file=None, api_tokens={"tok-1": "tenant-1"})


class FakeJobRepo:
    def __init__(self, job: Job | None) -> None:
        self._job = job

    def get(self, tenant_id: TenantId, job_id: str) -> Job | None:
        if self._job is not None and self._job.id == job_id and self._job.tenant_id == tenant_id:
            return self._job
        return None


def _app(job: Job | None) -> FastAPI:
    app = create_app(_settings())
    app.dependency_overrides[get_app_settings] = _settings
    app.dependency_overrides[get_job_repository] = lambda: FakeJobRepo(job)
    return app


def _job() -> Job:
    return Job(
        id="job_1",
        tenant_id=TenantId("tenant-1"),
        job_type=JobType.RUN_RECONCILIATION,
        status=JobStatus.SUCCEEDED,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
        started_at=datetime(2026, 6, 1, 0, 0, 1, tzinfo=UTC),
        finished_at=datetime(2026, 6, 1, 0, 0, 2, tzinfo=UTC),
        result_type=JobResultType.RECONCILIATION,
        result_ref="rec_1",
    )


def test_get_job_returns_status_and_result_pair() -> None:
    client = TestClient(_app(_job()))
    response = client.get("/api/v1/jobs/job_1", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == "job_1"
    assert body["job_type"] == "run_reconciliation"
    assert body["status"] == "succeeded"
    assert body["result_type"] == "reconciliation"
    assert body["result_ref"] == "rec_1"
    assert body["error"] is None


def test_missing_job_is_404_enveloped() -> None:
    client = TestClient(_app(None))
    response = client.get("/api/v1/jobs/nope", headers=AUTH)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_jobs_require_bearer_auth() -> None:
    client = TestClient(_app(_job()))
    assert client.get("/api/v1/jobs/job_1").status_code == 401
