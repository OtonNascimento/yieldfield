"""Dependency-connectivity probes for /ready (§11, §13).

Probes REPORT, they never raise: each check returns "ok" / "error" / "skipped"
(unconfigured). Lives in dependencies/ — the API's composition seam — because the checks
build infrastructure clients (engine, ClickHouse, Redis).
"""

from __future__ import annotations

from sqlalchemy import text

from yieldfield.config.settings import Settings
from yieldfield.infrastructure.analytics_store.clickhouse_client import create_clickhouse_client
from yieldfield.infrastructure.persistence.engine import create_db_engine

_OK = "ok"
_ERROR = "error"
_SKIPPED = "skipped"


def _check_postgres(settings: Settings) -> str:
    if not settings.database_url:
        return _SKIPPED
    try:
        engine = create_db_engine(settings.database_url)
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        finally:
            engine.dispose()
        return _OK
    except Exception:
        return _ERROR


def _check_clickhouse(settings: Settings) -> str:
    if not settings.clickhouse_url:
        return _SKIPPED
    try:
        create_clickhouse_client(settings.clickhouse_url).command("SELECT 1")
        return _OK
    except Exception:
        return _ERROR


def _check_redis(settings: Settings) -> str:
    if not settings.redis_url:
        return _SKIPPED
    try:
        import redis

        redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2).ping()
        return _OK
    except Exception:
        return _ERROR


def dependency_checks(settings: Settings) -> dict[str, str]:
    return {
        "postgres": _check_postgres(settings),
        "clickhouse": _check_clickhouse(settings),
        "redis": _check_redis(settings),
    }
