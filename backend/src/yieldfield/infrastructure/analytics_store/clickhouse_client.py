"""ClickHouse client factory (§12). Parses the configured URL and builds a client.

URL form: ``http(s)://user:pass@host:port/database`` (matches docker-compose / .env).
"""

from __future__ import annotations

from typing import Any, TypedDict
from urllib.parse import urlsplit

from yieldfield.infrastructure.analytics_store.errors import AnalyticsStoreError

_DEFAULT_HTTP_PORT = 8123


class ClickHouseParts(TypedDict):
    host: str
    port: int
    username: str
    password: str
    database: str
    secure: bool


def parse_clickhouse_url(url: str | None) -> ClickHouseParts:
    if not url:
        raise AnalyticsStoreError("CLICKHOUSE_URL is required to build the analytics client (§16).")
    parts = urlsplit(url)
    database = parts.path.lstrip("/") or "default"
    return ClickHouseParts(
        host=parts.hostname or "localhost",
        port=parts.port or _DEFAULT_HTTP_PORT,
        username=parts.username or "default",
        password=parts.password or "",
        database=database,
        secure=parts.scheme == "https",
    )


def create_clickhouse_client(url: str | None) -> Any:
    """Build a clickhouse-connect client from the configured URL (fail-fast, §16)."""
    import clickhouse_connect

    parts = parse_clickhouse_url(url)
    return clickhouse_connect.get_client(
        host=parts["host"],
        port=parts["port"],
        username=parts["username"],
        password=parts["password"],
        database=parts["database"],
        secure=parts["secure"],
    )
