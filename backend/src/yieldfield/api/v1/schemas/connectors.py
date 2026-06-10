"""Connector DTOs (spec §5.2/§5.3). Secrets go in, NEVER come back out (§11)."""

from __future__ import annotations

from pydantic import BaseModel

from yieldfield.api.v1.schemas.common import PageMeta
from yieldfield.domain.billing.connector import Connector, ConnectorStatus, ConnectorType


class ConnectorCreate(BaseModel):
    connector_type: ConnectorType
    secrets: dict[str, str]


class ConnectorPublic(BaseModel):
    """The only connector shape the API returns — id/type/status, no credentials (§11)."""

    id: str
    connector_type: ConnectorType
    status: ConnectorStatus

    @classmethod
    def from_connector(cls, connector: Connector) -> ConnectorPublic:
        return cls(
            id=str(connector.id),
            connector_type=connector.connector_type,
            status=connector.status,
        )


class ConnectorPage(BaseModel):
    items: list[ConnectorPublic]
    meta: PageMeta
