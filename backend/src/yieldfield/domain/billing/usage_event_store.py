"""The usage-event store port (§12) — OLAP, kept separate from the OLTP repos.

ClickHouse is the source of truth for usage events (spec §3). Append-mostly, queried
by tenant + time window. Implemented in `infrastructure/analytics_store/`.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.shared.ids import TenantId
from yieldfield.domain.shared.time_window import TimeWindow


@runtime_checkable
class UsageEventStore(Protocol):
    def append(self, tenant_id: TenantId, events: Iterable[UsageEvent]) -> None: ...
    def query(self, tenant_id: TenantId, window: TimeWindow) -> Iterable[UsageEvent]: ...
