"""Request-scoped OLTP session (spec §5.1): commit on success, rollback on error, always close."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session, sessionmaker

from yieldfield.config.settings import get_settings
from yieldfield.infrastructure.persistence.engine import build_sessionmaker, create_db_engine


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    """One engine per process, built lazily so importing the app needs no database (§16)."""
    return build_sessionmaker(create_db_engine(get_settings().database_url))


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
