"""SQLAlchemy engine + session factory for the OLTP store (§12, §16).

Sync engine (psycopg 3) to match the synchronous connector/worker model. Fails fast
if no database URL is configured, so misconfiguration never surfaces mid money-path.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from yieldfield.infrastructure.persistence.errors import PersistenceError

_BARE_SCHEME = "postgresql://"
_PSYCOPG3_SCHEME = "postgresql+psycopg://"


def _normalize_url(url: str) -> str:
    """Pin the psycopg-3 driver when a bare ``postgresql://`` URL is given."""
    if url.startswith(_BARE_SCHEME):
        return _PSYCOPG3_SCHEME + url[len(_BARE_SCHEME) :]
    return url


def create_db_engine(database_url: str | None) -> Engine:
    """Build the OLTP engine, or fail fast if no URL is configured (§16)."""
    if not database_url:
        raise PersistenceError("DATABASE_URL is required to build the OLTP engine (§16).")
    return create_engine(_normalize_url(database_url), future=True, pool_pre_ping=True)


def build_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    """A session factory; callers own the transaction boundary (application layer, Slice 3)."""
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
