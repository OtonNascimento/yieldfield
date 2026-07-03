"""Connector registration + (re)building authenticated connectors (§11, §17).

The composition seam between stored connector config and a live connector. Registration
validates required credentials (via authenticate), encrypts them with the cipher, and
persists the config + opaque blob. `build_authenticated` reverses it for ingestion/webhooks.
Lives in infrastructure so the application layer never sees secrets or the cipher.

The `ConnectorStore` Protocol is defined here, in infrastructure — not in the domain (spec
§2.1): no inner layer depends on it, and the encrypted credential blob is not a business
concept. `SqlAlchemyConnectorRepository` (Task 6) satisfies it structurally.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Protocol, runtime_checkable
from uuid import uuid4

from yieldfield.domain.billing.connector import Connector, ConnectorStatus, ConnectorType
from yieldfield.domain.billing.connector_port import ConnectorCredentials, ConnectorPort
from yieldfield.domain.shared.ids import ConnectorId, TenantId
from yieldfield.infrastructure.connectors.base.connector import ConnectorError
from yieldfield.infrastructure.connectors.factory import build_connector
from yieldfield.infrastructure.security.credential_cipher import CredentialCipher


@runtime_checkable
class ConnectorStore(Protocol):
    """Infrastructure connector persistence, including the opaque encrypted blob (§11)."""

    def add(
        self, tenant_id: TenantId, connector: Connector, encrypted_credentials: bytes
    ) -> None: ...

    def get(self, tenant_id: TenantId, connector_id: ConnectorId) -> Connector | None: ...

    def list_for_tenant(self, tenant_id: TenantId) -> Sequence[Connector]: ...

    def load_credentials(self, tenant_id: TenantId, connector_id: ConnectorId) -> bytes | None: ...

    def find_by_id(self, connector_id: ConnectorId) -> Connector | None: ...


def _default_id() -> ConnectorId:
    return ConnectorId(str(uuid4()))


class ConnectorRegistrationService:
    def __init__(
        self,
        store: ConnectorStore,
        cipher: CredentialCipher,
        *,
        id_factory: Callable[[], ConnectorId] = _default_id,
        base_url: str | None = None,
    ) -> None:
        self._store = store
        self._cipher = cipher
        self._id_factory = id_factory
        self._base_url = base_url

    def register(
        self, tenant_id: TenantId, connector_type: ConnectorType, secrets: Mapping[str, str]
    ) -> Connector:
        """Validate, encrypt, and persist a new connector. Raises ConnectorAuthError on
        missing required credentials (§11)."""
        connector = Connector(
            id=self._id_factory(),
            tenant_id=tenant_id,
            connector_type=connector_type,
            status=ConnectorStatus.ACTIVE,
        )
        live = build_connector(connector, base_url=self._base_url)
        live.authenticate(ConnectorCredentials(secrets=dict(secrets)))  # validates required keys
        blob = self._cipher.encrypt(secrets)
        self._store.add(tenant_id, connector, blob)
        return connector

    def build_authenticated(self, tenant_id: TenantId, connector_id: ConnectorId) -> ConnectorPort:
        """Load + decrypt + authenticate the stored connector for ingestion/webhooks (§17)."""
        connector = self._store.get(tenant_id, connector_id)
        if connector is None:
            raise ConnectorError(f"Connector {connector_id!r} not found for tenant {tenant_id!r}.")
        if connector.status is not ConnectorStatus.ACTIVE:
            # Defense in depth (audit SE-5): a disabled connector must never be rebuilt
            # into a live, credentialed client, however the request arrived.
            raise ConnectorError(f"Connector {connector_id!r} is not active.")
        blob = self._store.load_credentials(tenant_id, connector_id)
        if blob is None:
            raise ConnectorError(f"No stored credentials for connector {connector_id!r}.")
        secrets = self._cipher.decrypt(blob)
        live = build_connector(connector, base_url=self._base_url)
        live.authenticate(ConnectorCredentials(secrets=dict(secrets)))
        return live
