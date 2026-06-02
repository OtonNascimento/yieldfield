"""Connector — a tenant's registered billing-platform integration config (§17, §11).

Pure: identity, type, and status only. The encrypted credential blob is a persistence
concern and never lives on this entity — the domain never sees secrets (§11). A new
platform = a new ConnectorType member + a concrete connector class behind the port (§17).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from yieldfield.domain.shared.errors import InvalidEntityError
from yieldfield.domain.shared.ids import ConnectorId, TenantId


class ConnectorType(StrEnum):
    STRIPE_BILLING = "stripe_billing"


class ConnectorStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class Connector:
    id: ConnectorId
    tenant_id: TenantId
    connector_type: ConnectorType
    status: ConnectorStatus = ConnectorStatus.ACTIVE

    def __post_init__(self) -> None:
        if not str(self.id).strip():
            raise InvalidEntityError("Connector id is required.")
        if not str(self.tenant_id).strip():
            raise InvalidEntityError("Connector tenant_id is required.")
