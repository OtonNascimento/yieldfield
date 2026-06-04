"""IngestUsageEvents pulls from the connector and appends to the OLAP store (§4.1)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal

from yieldfield.application.ingestion.ingest_usage_events import IngestUsageEvents
from yieldfield.domain.billing.connector_port import ConnectorCredentials
from yieldfield.domain.billing.invoice import Invoice
from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.shared.ids import TenantId, UsageEventId
from yieldfield.domain.shared.time_window import TimeWindow

TENANT = TenantId("t_1")
WINDOW = TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))


def _event(event_id: str, customer_id: str = "cus_1") -> UsageEvent:
    return UsageEvent(
        id=UsageEventId(event_id),
        tenant_id=TENANT,
        customer_id=customer_id,
        metric="api_calls",
        quantity=Decimal("1"),
        occurred_at=datetime(2026, 1, 15, tzinfo=UTC),
    )


class FakeUsageStore:
    def __init__(self) -> None:
        self.appended: list[tuple[TenantId, list[UsageEvent]]] = []

    def append(self, tenant_id: TenantId, events: Iterable[UsageEvent]) -> None:
        self.appended.append((tenant_id, list(events)))

    def query(self, tenant_id: TenantId, window: TimeWindow) -> Iterable[UsageEvent]:
        return []


class FakeConnector:
    def __init__(self, events: list[UsageEvent]) -> None:
        self._events = events

    def authenticate(self, credentials: ConnectorCredentials) -> None:
        return None

    def pull_usage_events(self, window: TimeWindow) -> Iterable[UsageEvent]:
        return list(self._events)

    def pull_invoices(self, window: TimeWindow) -> Iterable[Invoice]:
        return []

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        return True


def test_appends_all_pulled_events_and_returns_count() -> None:
    store = FakeUsageStore()
    connector = FakeConnector([_event("u_1"), _event("u_2")])
    count = IngestUsageEvents(store).run(TENANT, WINDOW, connector)
    assert count == 2
    assert len(store.appended) == 1  # one batch append, not one call per event
    assert [e.id for e in store.appended[0][1]] == [UsageEventId("u_1"), UsageEventId("u_2")]


def test_passes_tenant_scope_to_store() -> None:
    store = FakeUsageStore()
    IngestUsageEvents(store).run(TENANT, WINDOW, FakeConnector([_event("u_1")]))
    assert store.appended[0][0] == TENANT


def test_empty_pull_returns_zero() -> None:
    store = FakeUsageStore()
    count = IngestUsageEvents(store).run(TENANT, WINDOW, FakeConnector([]))
    assert count == 0
    assert store.appended == [(TENANT, [])]
