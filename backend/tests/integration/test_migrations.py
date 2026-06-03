"""Migration 0002 applies and reverses on a disposable Postgres (§12).

Uses its OWN throwaway container so it never downgrades the session-scoped
`migrated_engine` database that the other integration tests share.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

REPO_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_INI = REPO_ROOT / "ops" / "migrations" / "alembic.ini"


@pytest.fixture
def fresh_pg_url() -> Iterator[str]:
    try:
        from testcontainers.postgres import PostgresContainer

        container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        container.start()
    except Exception as exc:  # any startup failure means Docker isn't available here
        pytest.skip(f"Docker/testcontainers unavailable: {exc}")
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


@pytest.mark.integration
def test_migration_0002_upgrades_and_downgrades(fresh_pg_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", fresh_pg_url)

    command.upgrade(cfg, "head")
    engine = create_engine(fresh_pg_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"connectors", "jobs"} <= tables
    recon_cols = {c["name"] for c in inspector.get_columns("reconciliations")}
    assert {"executed_at", "rule_version"} <= recon_cols
    engine.dispose()

    command.downgrade(cfg, "0001_oltp_schema")
    engine = create_engine(fresh_pg_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "connectors" not in tables
    assert "jobs" not in tables
    recon_cols = {c["name"] for c in inspector.get_columns("reconciliations")}
    assert "executed_at" not in recon_cols
    assert "rule_version" not in recon_cols
    engine.dispose()
