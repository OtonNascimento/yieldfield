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


def test_job_belonging_to_other_tenant_is_404() -> None:
    # Tenant isolation at the API boundary: a foreign tenant's job must be invisible —
    # same envelope as a missing job, so existence never leaks (§11).
    foreign = Job(
        id="job_1",
        tenant_id=TenantId("tenant-99"),
        job_type=JobType.RUN_RECONCILIATION,
        status=JobStatus.SUCCEEDED,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    client = TestClient(_app(foreign))
    response = client.get("/api/v1/jobs/job_1", headers=AUTH)  # AUTH maps to tenant-1
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_pending_job_returns_null_optionals() -> None:
    pending = Job(
        id="job_1",
        tenant_id=TenantId("tenant-1"),
        job_type=JobType.RUN_RECONCILIATION,
        status=JobStatus.PENDING,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    client = TestClient(_app(pending))
    response = client.get("/api/v1/jobs/job_1", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    for field in ("started_at", "finished_at", "error", "result_type", "result_ref"):
        assert body[field] is None


def test_failed_job_surfaces_error_and_no_result() -> None:
    failed = Job(
        id="job_1",
        tenant_id=TenantId("tenant-1"),
        job_type=JobType.RUN_RECONCILIATION,
        status=JobStatus.FAILED,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
        started_at=datetime(2026, 6, 1, 0, 0, 1, tzinfo=UTC),
        finished_at=datetime(2026, 6, 1, 0, 0, 2, tzinfo=UTC),
        error="Reconciliation failed: currency mismatch.",
    )
    client = TestClient(_app(failed))
    response = client.get("/api/v1/jobs/job_1", headers=AUTH)
    assert response.status_code == 200  # FAILED is a poll result, not an HTTP error (§3)
    body = response.json()
    assert body["status"] == "failed"
    assert body["error"] == "Reconciliation failed: currency mismatch."
    assert body["result_type"] is None and body["result_ref"] is None


def test_jobs_require_bearer_auth() -> None:
    client = TestClient(_app(_job()))
    assert client.get("/api/v1/jobs/job_1").status_code == 401
