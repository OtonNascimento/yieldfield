"""Ingest invoices (§4.1) — pull from a connector, upsert into the OLTP repository.

Pure orchestration over domain ports: it depends on the `ConnectorPort` and
`InvoiceRepository` abstractions, never a concrete adapter or framework. Idempotency is the
repository's job (upsert-by-id, §8); this use-case just drives it. Job-unaware (§3).
"""

from __future__ import annotations

from yieldfield.domain.billing.connector_port import ConnectorPort
from yieldfield.domain.billing.repositories import InvoiceRepository
from yieldfield.domain.shared.ids import TenantId
from yieldfield.domain.shared.time_window import TimeWindow


class IngestInvoices:
    def __init__(self, invoices: InvoiceRepository) -> None:
        self._invoices = invoices

    def run(self, tenant_id: TenantId, window: TimeWindow, connector: ConnectorPort) -> int:
        """Pull invoices issued in `window`, upsert each, return the count ingested."""
        count = 0
        for invoice in connector.pull_invoices(window):
            self._invoices.add(tenant_id, invoice)
            count += 1
        return count
