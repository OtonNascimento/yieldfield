"""POST /ingestion/*: flag-gated 202s that persist a PENDING Job BEFORE enqueueing (§3, §16)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from yieldfield.api.main import create_app
from yieldfield.api.v1.dependencies.services import (
    INGEST_INVOICES_TASK,
    INGEST_USAGE_EVENTS_TASK,
    JobSubmitter,
    get_job_submitter,
)
from yieldfield.api.v1.dependencies.settings import get_app_settings
from yieldfield.config.settings import Settings
from yieldfield.domain.shared.ids import TenantId
from yieldfield.infrastructure.persistence.job import Job, JobStatus, JobType

AUTH = {"Authorization": "Bearer tok-1"}
WINDOW_JSON = {"start": "2026-01-01T00:00:00+00:00", "end": "2026-02-01T00:00:00+00:00"}


def _settings(*, enabled: bool = True) -> Settings:
    return Settings(_env_file=None, api_tokens={"tok-1": "tenant-1"}, ingestion_enabled=enabled)


class FakeSubmitter:
    def __init__(self) -> None:
        self.submitted: list[tuple[TenantId, str, tuple[str, ...]]] = []

    def submit(self, tenant_id: TenantId, task_name: str, *task_args: str) -> str:
        self.submitted.append((tenant_id, task_name, task_args))
        return "job_x"


def _app(submitter: FakeSubmitter, *, enabled: bool = True) -> FastAPI:
    app = create_app(_settings(enabled=enabled))
    app.dependency_overrides[get_app_settings] = lambda: _settings(enabled=enabled)
    app.dependency_overrides[get_job_submitter] = lambda: submitter
    return app


def test_ingest_invoices_returns_202_and_enqueues_with_window_and_connector() -> None:
    submitter = FakeSubmitter()
    client = TestClient(_app(submitter))
    response = client.post(
        "/api/v1/ingestion/invoices",
        headers=AUTH,
        json={"connector_id": "con_1", "window": WINDOW_JSON},
    )
    assert response.status_code == 202
    assert response.json() == {"job_id": "job_x"}
    tenant, task_name, args = submitter.submitted[0]
    assert tenant == TenantId("tenant-1")
    assert task_name == INGEST_INVOICES_TASK
    assert args == ("2026-01-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00", "con_1")


def test_ingest_usage_events_returns_202() -> None:
    submitter = FakeSubmitter()
    client = TestClient(_app(submitter))
    response = client.post(
        "/api/v1/ingestion/usage-events",
        headers=AUTH,
        json={"connector_id": "con_1", "window": WINDOW_JSON},
    )
    assert response.status_code == 202
    assert submitter.submitted[0][1] == INGEST_USAGE_EVENTS_TASK


@pytest.mark.parametrize("path", ["invoices", "usage-events"])
def test_ingestion_is_403_when_flag_is_off(path: str) -> None:
    submitter = FakeSubmitter()
    client = TestClient(_app(submitter, enabled=False))
    response = client.post(
        f"/api/v1/ingestion/{path}",
        headers=AUTH,
        json={"connector_id": "con_1", "window": WINDOW_JSON},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ingestion_disabled"
    assert submitter.submitted == []  # disabled means zero side effects: no job, no enqueue


def test_naive_window_is_422_enveloped_and_never_submits() -> None:
    submitter = FakeSubmitter()
    client = TestClient(_app(submitter))
    response = client.post(
        "/api/v1/ingestion/invoices",
        headers=AUTH,
        json={
            "connector_id": "con_1",
            "window": {"start": "2026-01-01T00:00:00", "end": "2026-02-01T00:00:00+00:00"},
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert submitter.submitted == []


def test_ingestion_requires_bearer_auth() -> None:
    client = TestClient(_app(FakeSubmitter()))
    response = client.post(
        "/api/v1/ingestion/invoices", json={"connector_id": "con_1", "window": WINDOW_JSON}
    )
    assert response.status_code == 401


def test_job_submitter_persists_pending_job_then_commits_then_enqueues() -> None:
    events: list[str] = []

    class FakeSession:
        def commit(self) -> None:
            events.append("commit")

    class FakeJobs:
        def add(self, tenant_id: TenantId, job: Job) -> None:
            events.append("add")
            assert job.status is JobStatus.PENDING
            assert job.job_type is JobType.INGEST_INVOICES
            assert job.created_at.tzinfo is not None

    class FakeQueue:
        def enqueue(self, task_name: str, *args: str) -> str:
            events.append("enqueue")
            assert task_name == INGEST_INVOICES_TASK
            assert args[1] == "tenant-1"  # (job_id, tenant_id, *task_args)
            return "celery-task-id"

    submitter = JobSubmitter(FakeSession(), FakeJobs(), FakeQueue())  # type: ignore[arg-type]
    job_id = submitter.submit(TenantId("tenant-1"), INGEST_INVOICES_TASK, "a", "b")
    assert job_id.startswith("job_")
    # The PENDING row is durable BEFORE the broker can deliver the task (§3 race guard).
    assert events == ["add", "commit", "enqueue"]
