"""Typed identifiers for domain entities (§8 naming — names are domain concepts).

NewType wrappers over `str` give compile-time safety (a `TenantId` cannot be passed
where an `InvoiceId` is expected) with zero runtime cost. ID *generation* is an
infrastructure concern; the domain only carries and compares them.
"""

from __future__ import annotations

from typing import NewType

TenantId = NewType("TenantId", str)
ContractId = NewType("ContractId", str)
PlanId = NewType("PlanId", str)
UsageEventId = NewType("UsageEventId", str)
InvoiceId = NewType("InvoiceId", str)
InvoiceLineItemId = NewType("InvoiceLineItemId", str)
ReconciliationId = NewType("ReconciliationId", str)
FindingId = NewType("FindingId", str)
ModelRunId = NewType("ModelRunId", str)
ConnectorId = NewType("ConnectorId", str)
