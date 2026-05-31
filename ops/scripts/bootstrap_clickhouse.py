"""Provision the ClickHouse OLAP schema (§12). ClickHouse is not Alembic-managed.

Run (from backend/, where the yieldfield package is installed):
    uv run python ../ops/scripts/bootstrap_clickhouse.py
Reads YIELDFIELD_CLICKHOUSE_URL from the environment (§16).
"""

from __future__ import annotations

import os
import sys

from yieldfield.infrastructure.analytics_store.clickhouse_client import create_clickhouse_client
from yieldfield.infrastructure.analytics_store.clickhouse_usage_event_store import (
    ClickHouseUsageEventStore,
)


def main() -> int:
    url = os.environ.get("YIELDFIELD_CLICKHOUSE_URL")
    client = create_clickhouse_client(url)
    ClickHouseUsageEventStore(client).ensure_schema()
    print("ClickHouse usage_events schema ensured.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
