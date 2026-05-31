"""Alembic environment for the OLTP schema (§12).

Resolves the database URL from Alembic config (set by tests/CI) or the
YIELDFIELD_DATABASE_URL env var, normalizing to the psycopg-3 driver. Target metadata
comes from the persistence package, so migrations track the ORM models.
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine

from yieldfield.infrastructure.persistence.engine import _normalize_url
from yieldfield.infrastructure.persistence.metadata import metadata

config = context.config
target_metadata = metadata


def _resolve_url() -> str:
    url = config.get_main_option("sqlalchemy.url") or os.environ.get("YIELDFIELD_DATABASE_URL")
    if not url:
        raise RuntimeError("No database URL: set sqlalchemy.url or YIELDFIELD_DATABASE_URL.")
    return _normalize_url(url)


def run_migrations_online() -> None:
    engine = create_engine(_resolve_url(), future=True)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():  # pragma: no cover - online mode only in this project
    raise RuntimeError("Offline migrations are not supported; provide a database URL.")
run_migrations_online()
