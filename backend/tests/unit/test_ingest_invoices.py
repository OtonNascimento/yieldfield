"""IngestInvoices pulls from the connector and upserts each invoice (§4.1)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from yieldfield.application.ingestion.ingest_invoices import IngestInvoices
from yieldfield.domain.billing.connector_port import ConnectorCredentials
from yieldfield.domain.billing.invoice import Invoice
from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.shared.ids import InvoiceId, TenantId
from yieldfield.domain.shared.time_window import TimeWindow

TENANT = TenantId("t_1")
WINDOW = TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))


def _invoice(invoice_id: str, customer_id: str = "cus_1") -> Invoice:
    return Invoice(
        id=InvoiceId(invoice_id),
        tenant_id=TENANT,
        customer_id=customer_id,
        period=WINDOW,
        currency="USD",
        line_items=(),
    )


class FakeInvoiceRepo:
    def __init__(self) -> None:
        self.added: list[tuple[TenantId, Invoice]] = []

    def add(self, tenant_id: TenantId, invoice: Invoice) -> None:
        self.added.append((tenant_id, invoice))

    def get(self, tenant_id: TenantId, invoice_id: InvoiceId) -> Invoice | None:
        return None

    def list_in_window(self, tenant_id: TenantId, window: TimeWindow) -> Sequence[Invoice]:
        return []


class FakeConnector:
    def __init__(self, invoices: Sequence[Invoice]) -> None:
        self._invoices = invoices

    def authenticate(self, credentials: ConnectorCredentials) -> None:
        return None

    def pull_usage_events(self, window: TimeWindow) -> Iterable[UsageEvent]:
        return []

    def pull_invoices(self, window: TimeWindow) -> Iterable[Invoice]:
        return list(self._invoices)

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        return True


def test_ingests_all_pulled_invoices_and_returns_count() -> None:
    repo = FakeInvoiceRepo()
    connector = FakeConnector([_invoice("inv_1"), _invoice("inv_2")])
    count = IngestInvoices(repo).run(TENANT, WINDOW, connector)
    assert count == 2
    assert [inv.id for _, inv in repo.added] == [InvoiceId("inv_1"), InvoiceId("inv_2")]


def test_passes_tenant_scope_to_repository() -> None:
    repo = FakeInvoiceRepo()
    IngestInvoices(repo).run(TENANT, WINDOW, FakeConnector([_invoice("inv_1")]))
    assert repo.added[0][0] == TENANT


def test_empty_pull_returns_zero_and_adds_nothing() -> None:
    repo = FakeInvoiceRepo()
    count = IngestInvoices(repo).run(TENANT, WINDOW, FakeConnector([]))
    assert count == 0
    assert repo.added == []


class StreamingConnector:
    """Yields invoices from a one-shot generator — pins single-pass consumption (no re-iteration)."""

    def __init__(self, count: int) -> None:
        self._count = count

    def authenticate(self, credentials: ConnectorCredentials) -> None:
        return None

    def pull_usage_events(self, window: TimeWindow) -> Iterable[UsageEvent]:
        return []

    def pull_invoices(self, window: TimeWindow) -> Iterable[Invoice]:
        return (_invoice(f"inv_{i}") for i in range(self._count))

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        return True


def test_one_shot_generator_pull_is_consumed_exactly_once() -> None:
    # A real connector may stream invoices from a lazy generator; the use-case must consume it
    # exactly once. A second iteration would exhaust it and under-count.
    repo = FakeInvoiceRepo()
    count = IngestInvoices(repo).run(TENANT, WINDOW, StreamingConnector(3))
    assert count == 3
    assert len(repo.added) == 3
