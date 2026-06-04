"""ClickHouse usage-event store: round-trip, window boundary, tenant isolation (§11)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.shared.ids import TenantId, UsageEventId
from yieldfield.domain.shared.time_window import TimeWindow

pytestmark = pytest.mark.integration

_WINDOW = TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))


def _event(tid: str, eid: str, when: datetime, qty: str) -> UsageEvent:
    return UsageEvent(
        id=UsageEventId(eid),
        tenant_id=TenantId(tid),
        customer_id="cus_1",
        metric="api_call",
        quantity=Decimal(qty),
        occurred_at=when,
    )


def test_append_then_query_round_trips_with_decimal_precision(clickhouse_store: Any) -> None:
    event = _event("t_1", "ue_1", datetime(2026, 1, 15, tzinfo=UTC), "12.000000000123")
    clickhouse_store.append(TenantId("t_1"), [event])
    results = list(clickhouse_store.query(TenantId("t_1"), _WINDOW))
    assert event in results
    matched = next(e for e in results if e.id == "ue_1")
    assert matched.quantity == Decimal("12.000000000123")  # 12 fractional digits preserved


def test_query_excludes_events_on_the_window_end_boundary(clickhouse_store: Any) -> None:
    on_end = _event(
        "t_1", "ue_end", datetime(2026, 2, 1, tzinfo=UTC), "1"
    )  # == window.end → excluded
    clickhouse_store.append(TenantId("t_1"), [on_end])
    ids = {e.id for e in clickhouse_store.query(TenantId("t_1"), _WINDOW)}
    assert "ue_end" not in ids  # half-open [start, end)


def test_query_is_tenant_isolated(clickhouse_store: Any) -> None:
    clickhouse_store.append(
        TenantId("t_X"), [_event("t_X", "ue_x", datetime(2026, 1, 10, tzinfo=UTC), "5")]
    )
    ids = {e.id for e in clickhouse_store.query(TenantId("t_Y"), _WINDOW)}
    assert "ue_x" not in ids  # tenant Y never sees tenant X's events (§11)


def test_duplicate_append_is_deduped(clickhouse_store: Any) -> None:
    tid = TenantId("tenant-dedup")
    event = UsageEvent(
        id=UsageEventId("meter_x:cus_1:1714521600"),
        tenant_id=tid,
        customer_id="cus_1",
        metric="api_calls",
        quantity=Decimal("5"),
        occurred_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    clickhouse_store.append(tid, [event])
    clickhouse_store.append(tid, [event])  # same id — must collapse to one row

    window = TimeWindow(datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 6, 1, tzinfo=UTC))
    rows = list(clickhouse_store.query(tid, window))
    assert len(rows) == 1
    assert rows[0].quantity == Decimal("5")
