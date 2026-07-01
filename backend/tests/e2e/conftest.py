"""E2E fixtures (spec §12): real containers + eager Celery so worker code runs inline.

Settings are injected via env vars; every process-level cache (settings, the API session
factory, the worker engine/store) is cleared around each test so each test sees this
wiring and later suites see none of it.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_INI = REPO_ROOT / "ops" / "migrations" / "alembic.ini"

TENANT_ID = "tenant-e2e"
TOKEN = "e2e-token"  # noqa: S105 — test-only bearer token, not a real credential


@pytest.fixture(scope="session")
def _postgres() -> Iterator[Any]:
    try:
        from testcontainers.postgres import PostgresContainer

        container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        container.start()
    except Exception as exc:
        pytest.skip(f"Docker/testcontainers unavailable: {exc}")
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def _clickhouse() -> Iterator[Any]:
    try:
        from testcontainers.clickhouse import ClickHouseContainer

        container = ClickHouseContainer("clickhouse/clickhouse-server:24.3-alpine")
        container.start()
    except Exception as exc:
        pytest.skip(f"Docker/testcontainers unavailable: {exc}")
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def _stripe_mock() -> Iterator[str]:
    try:
        from testcontainers.core.container import DockerContainer
        from testcontainers.core.waiting_utils import wait_for_logs

        container = DockerContainer("stripe/stripe-mock:latest").with_exposed_ports(12111)
        container.start()
        wait_for_logs(container, "Listening", timeout=30)
    except Exception as exc:
        pytest.skip(f"Docker/testcontainers unavailable: {exc}")
    try:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(12111)
        yield f"http://{host}:{port}"
    finally:
        container.stop()


@pytest.fixture(scope="session")
def _database_url(_postgres: Any) -> str:
    """Migrated-to-head database with the E2E tenant row seeded (FK target, §11)."""
    from alembic import command
    from alembic.config import Config

    from yieldfield.domain.billing.tenant import Tenant
    from yieldfield.domain.shared.ids import TenantId
    from yieldfield.infrastructure.persistence.engine import create_db_engine
    from yieldfield.infrastructure.persistence.repositories import SqlAlchemyTenantRepository

    url: str = _postgres.get_connection_url()
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    engine = create_db_engine(url)
    with Session(engine) as session:
        SqlAlchemyTenantRepository(session).add(Tenant(id=TenantId(TENANT_ID), name="E2E"))
        session.commit()
    engine.dispose()
    return url


@pytest.fixture(scope="session")
def _clickhouse_url(_clickhouse: Any) -> str:
    """ClickHouse URL with the usage_events schema provisioned."""
    from yieldfield.infrastructure.analytics_store.clickhouse_client import (
        create_clickhouse_client,
    )
    from yieldfield.infrastructure.analytics_store.clickhouse_usage_event_store import (
        ClickHouseUsageEventStore,
    )

    host = _clickhouse.get_container_host_ip()
    port = _clickhouse.get_exposed_port(8123)
    url = f"http://{_clickhouse.username}:{_clickhouse.password}@{host}:{port}/{_clickhouse.dbname}"
    ClickHouseUsageEventStore(create_clickhouse_client(url)).ensure_schema()
    return url


def _clear_process_caches() -> None:
    from yieldfield.api.v1.dependencies import database
    from yieldfield.config.settings import get_settings
    from yieldfield.workers import tasks as worker_tasks

    get_settings.cache_clear()
    database._session_factory.cache_clear()
    worker_tasks._session_factory.cache_clear()
    worker_tasks._usage_event_store.cache_clear()


@pytest.fixture()
def client(
    _database_url: str,
    _clickhouse_url: str,
    _stripe_mock: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.setenv("YIELDFIELD_DATABASE_URL", _database_url)
    monkeypatch.setenv("YIELDFIELD_CLICKHOUSE_URL", _clickhouse_url)
    monkeypatch.setenv("YIELDFIELD_CONNECTOR_BASE_URL", _stripe_mock)
    monkeypatch.setenv("YIELDFIELD_CREDENTIALS_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("YIELDFIELD_API_TOKENS", json.dumps({TOKEN: TENANT_ID}))
    monkeypatch.setenv("YIELDFIELD_INGESTION_ENABLED", "true")
    _clear_process_caches()

    import yieldfield.workers.tasks  # noqa: F401 — registers the tasks on the celery app
    from yieldfield.api.main import create_app
    from yieldfield.api.v1.dependencies.tasks import get_task_queue
    from yieldfield.workers.celery_app import celery_app

    class _EagerTaskQueue:
        """Celery's `send_task` ignores task_always_eager (by-name dispatch never resolves
        the registered task object), so the production queue would leave Jobs PENDING here.
        Dispatch the SAME name contract straight into the registered tasks, inline —
        the REAL worker composition roots still execute."""

        def enqueue(self, task_name: str, *args: str) -> str:
            return str(celery_app.tasks[task_name].apply(args=list(args)).id)

    celery_app.conf.task_eager_propagates = True  # .apply() re-raises task errors
    app = create_app()
    app.dependency_overrides[get_task_queue] = _EagerTaskQueue
    try:
        yield TestClient(app)
    finally:
        celery_app.conf.task_eager_propagates = False
        _clear_process_caches()
