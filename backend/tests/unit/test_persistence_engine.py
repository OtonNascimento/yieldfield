"""Engine factory: psycopg-3 URL normalization + fail-fast on missing config (§16)."""

from __future__ import annotations

import pytest

from yieldfield.infrastructure.persistence.engine import _normalize_url, create_db_engine
from yieldfield.infrastructure.persistence.errors import PersistenceError


def test_normalize_bare_postgresql_url_selects_psycopg3() -> None:
    assert _normalize_url("postgresql://u:p@h:5432/db") == "postgresql+psycopg://u:p@h:5432/db"


def test_normalize_leaves_explicit_driver_untouched() -> None:
    url = "postgresql+psycopg://u:p@h:5432/db"
    assert _normalize_url(url) == url


def test_create_engine_without_url_fails_fast() -> None:
    with pytest.raises(PersistenceError, match="DATABASE_URL"):
        create_db_engine(None)
