"""Ingest usage events (§4.1) — pull from a connector, append to the OLAP store.

Appends in a single batch (the store's `append` takes an iterable); idempotency is the
store's job (ReplacingMergeTree on the deterministic event id, §8). Job-unaware (§3).
"""

from __future__ import annotations

from yieldfield.domain.billing.connector_port import ConnectorPort
from yieldfield.domain.billing.usage_event_store import UsageEventStore
from yieldfield.domain.shared.ids import TenantId
from yieldfield.domain.shared.time_window import TimeWindow


class IngestUsageEvents:
    def __init__(self, usage_events: UsageEventStore) -> None:
        self._usage_events = usage_events

    def run(self, tenant_id: TenantId, window: TimeWindow, connector: ConnectorPort) -> int:
        """Pull usage events in `window`, append them, return the count ingested."""
        events = list(connector.pull_usage_events(window))
        self._usage_events.append(tenant_id, events)
        return len(events)
