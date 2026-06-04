"""ClickHouse implementation of the UsageEventStore port (§12, §13).

ClickHouse is the source of truth for usage events (spec §3): high-volume, append-mostly,
partitioned by (tenant_id, month) for tenant+time scans. Append/query are tenant-scoped;
the window is half-open [start, end) to match TimeWindow.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.shared.ids import TenantId, UsageEventId
from yieldfield.domain.shared.time_window import TimeWindow
from yieldfield.infrastructure.analytics_store.errors import AnalyticsStoreError

_TABLE = "usage_events"
_COLUMNS = ["id", "tenant_id", "customer_id", "metric", "quantity", "occurred_at"]

_DDL = f"""
CREATE TABLE IF NOT EXISTS {_TABLE} (
    id String,
    tenant_id String,
    customer_id String,
    metric String,
    quantity Decimal128(12),
    occurred_at DateTime64(6, 'UTC')
)
ENGINE = ReplacingMergeTree
PARTITION BY (tenant_id, toYYYYMM(occurred_at))
ORDER BY (tenant_id, occurred_at, id)
"""


def _as_utc(moment: datetime) -> datetime:
    """Normalize to a tz-aware UTC datetime for ClickHouse DateTime64('UTC').

    clickhouse-connect interprets *naive* datetimes as the local timezone, which shifts the
    stored/queried instant (e.g. by the host's UTC offset). Passing tz-aware UTC stores and
    compares the exact instant correctly.
    """
    return moment.astimezone(UTC)


class ClickHouseUsageEventStore:
    def __init__(self, client: Any, *, table: str = _TABLE) -> None:
        self._client = client
        self._table = table

    def ensure_schema(self) -> None:
        self._client.command(_DDL.replace(_TABLE, self._table))

    def append(self, tenant_id: TenantId, events: Iterable[UsageEvent]) -> None:
        rows = []
        for event in events:
            if str(event.tenant_id) != str(tenant_id):
                raise AnalyticsStoreError(
                    f"event tenant_id {event.tenant_id!r} does not match scope {tenant_id!r} (§11)."
                )
            rows.append(
                [
                    str(event.id),
                    str(event.tenant_id),
                    event.customer_id,
                    event.metric,
                    event.quantity,
                    _as_utc(event.occurred_at),
                ]
            )
        if rows:
            self._client.insert(self._table, rows, column_names=_COLUMNS)

    def query(self, tenant_id: TenantId, window: TimeWindow) -> Iterable[UsageEvent]:
        result = self._client.query(
            f"SELECT {', '.join(_COLUMNS)} FROM {self._table} FINAL "  # noqa: S608
            "WHERE tenant_id = {tid:String} "
            "AND occurred_at >= {start:DateTime64} AND occurred_at < {end:DateTime64} "
            "ORDER BY occurred_at, id",
            parameters={
                "tid": str(tenant_id),
                "start": _as_utc(window.start),
                "end": _as_utc(window.end),
            },
        )
        return [self._to_event(row) for row in result.result_rows]

    @staticmethod
    def _to_event(row: tuple[Any, ...]) -> UsageEvent:
        occurred_at = row[5]
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
        return UsageEvent(
            id=UsageEventId(str(row[0])),
            tenant_id=TenantId(str(row[1])),
            customer_id=str(row[2]),
            metric=str(row[3]),
            quantity=Decimal(str(row[4])),
            occurred_at=occurred_at,
        )
