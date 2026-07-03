"""Request-scoped OLTP session (spec §5.1): commit on success, rollback on error, always close.

The engine is a process-wide singleton built lazily (importing the app needs no
database, §16). Readiness probes reuse it via `process_engine`, and the app's lifespan
hook releases its pooled connections on graceful shutdown via `dispose_engine`
(audit PR-5).
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from yieldfield.config.settings import get_settings
from yieldfield.infrastructure.persistence.engine import build_sessionmaker, create_db_engine


@lru_cache(maxsize=1)
def _engine() -> Engine:
    settings = get_settings()
    return create_db_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    return build_sessionmaker(_engine())


def process_engine() -> Engine:
    """The process-wide engine (readiness probes reuse this pool instead of building one)."""
    return _engine()


def dispose_engine() -> None:
    """Release pooled connections and reset the caches; safe when nothing was built."""
    if _engine.cache_info().currsize:
        _engine().dispose()
    _engine.cache_clear()
    _session_factory.cache_clear()


def db_session() -> Iterator[Session]:
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


DbSession = Annotated[Session, Depends(db_session)]
