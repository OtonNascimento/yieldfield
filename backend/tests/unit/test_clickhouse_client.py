"""ClickHouse client URL parsing + the append tenant-scope guard (no Docker)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.shared.ids import TenantId, UsageEventId
from yieldfield.infrastructure.analytics_store.clickhouse_client import parse_clickhouse_url
from yieldfield.infrastructure.analytics_store.clickhouse_usage_event_store import (
    ClickHouseUsageEventStore,
)
from yieldfield.infrastructure.analytics_store.errors import AnalyticsStoreError


def test_parse_clickhouse_url_extracts_connection_parts() -> None:
    parts = parse_clickhouse_url("http://user:pass@host:8123/analytics")
    assert parts == {
        "host": "host",
        "port": 8123,
        "username": "user",
        "password": "pass",
        "database": "analytics",
        "secure": False,
    }


def test_parse_clickhouse_url_requires_a_value() -> None:
    with pytest.raises(AnalyticsStoreError, match="CLICKHOUSE_URL"):
        parse_clickhouse_url(None)


def test_append_rejects_events_from_another_tenant() -> None:
    store = ClickHouseUsageEventStore(client=None)  # guard runs before client use
    foreign = UsageEvent(
        id=UsageEventId("ue_1"),
        tenant_id=TenantId("t_OTHER"),
        customer_id="cus_1",
        metric="api_call",
        quantity=Decimal("1"),
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(AnalyticsStoreError, match="does not match"):
        store.append(TenantId("t_1"), [foreign])
