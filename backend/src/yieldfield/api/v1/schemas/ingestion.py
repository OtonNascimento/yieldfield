"""Ingestion trigger DTO (spec §5.2): which connector, which window.

Window semantics (audit API-1): ingestion pulls the invoices whose BILLING PERIOD
overlaps the window (the connector scans a padded created-range to find them);
reconciliation then selects invoices whose period *starts* inside its window. Using
the same window for both therefore covers every invoice the reconciliation will read.
"""

from __future__ import annotations

from pydantic import BaseModel

from yieldfield.api.v1.schemas.common import WindowParam


class IngestionRequest(BaseModel):
    connector_id: str
    window: WindowParam
