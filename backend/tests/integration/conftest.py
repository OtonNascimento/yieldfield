"""Docker-gated fixtures for integration tests (skip cleanly when Docker is absent)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_INI = REPO_ROOT / "ops" / "migrations" / "alembic.ini"


@pytest.fixture(scope="session")
def _postgres_container() -> Iterator[Any]:
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
def migrated_engine(_postgres_container: Any) -> Iterator[Engine]:
    from alembic import command
    from alembic.config import Config

    from yieldfield.infrastructure.persistence.engine import create_db_engine

    url = _postgres_container.get_connection_url()
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    engine = create_db_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def session(migrated_engine: Engine) -> Iterator[Session]:
    with Session(migrated_engine) as s:
        yield s
        s.rollback()


@pytest.fixture(scope="session")
def clickhouse_store() -> Iterator[Any]:
    try:
        from testcontainers.clickhouse import ClickHouseContainer

        container = ClickHouseContainer("clickhouse/clickhouse-server:24.3-alpine")
        container.start()
    except Exception as exc:  # any startup failure means Docker isn't available here
        pytest.skip(f"Docker/testcontainers unavailable: {exc}")
    try:
        import clickhouse_connect

        from yieldfield.infrastructure.analytics_store.clickhouse_usage_event_store import (
            ClickHouseUsageEventStore,
        )

        client = clickhouse_connect.get_client(
            host=container.get_container_host_ip(),
            port=container.get_exposed_port(8123),
            username=container.username,
            password=container.password,
            database=container.dbname,
        )
        store = ClickHouseUsageEventStore(client)
        store.ensure_schema()
        yield store
    finally:
        container.stop()
