"""Registration validates + encrypts + persists; build_authenticated round-trips (§11/§17).

authenticate() on the Stripe connector only constructs the client (no network), so these
are pure unit tests — no stripe-mock required.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from cryptography.fernet import Fernet

from yieldfield.domain.billing.connector import Connector, ConnectorType
from yieldfield.domain.shared.ids import ConnectorId, TenantId
from yieldfield.infrastructure.connectors.base.connector import ConnectorAuthError, ConnectorError
from yieldfield.infrastructure.connectors.registration import ConnectorRegistrationService
from yieldfield.infrastructure.connectors.stripe_billing.connector import StripeBillingConnector
from yieldfield.infrastructure.security.credential_cipher import FernetCredentialCipher


class FakeConnectorStore:
    def __init__(self) -> None:
        self.connectors: dict[str, Connector] = {}
        self.blobs: dict[str, bytes] = {}

    def add(self, tenant_id: TenantId, connector: Connector, encrypted_credentials: bytes) -> None:
        self.connectors[str(connector.id)] = connector
        self.blobs[str(connector.id)] = encrypted_credentials

    def get(self, tenant_id: TenantId, connector_id: ConnectorId) -> Connector | None:
        return self.connectors.get(str(connector_id))

    def list_for_tenant(self, tenant_id: TenantId) -> Sequence[Connector]:
        return list(self.connectors.values())

    def load_credentials(self, tenant_id: TenantId, connector_id: ConnectorId) -> bytes | None:
        return self.blobs.get(str(connector_id))

    def find_by_id(self, connector_id: ConnectorId) -> Connector | None:
        return self.connectors.get(str(connector_id))


def _service(store: FakeConnectorStore) -> ConnectorRegistrationService:
    cipher = FernetCredentialCipher(Fernet.generate_key().decode())
    ids = iter(["con_1", "con_2"])
    return ConnectorRegistrationService(
        store,
        cipher,
        id_factory=lambda: ConnectorId(next(ids)),
        base_url="http://stripe-mock:12111",
    )


def test_register_encrypts_and_persists() -> None:
    store = FakeConnectorStore()
    connector = _service(store).register(
        TenantId("tenant-1"), ConnectorType.STRIPE_BILLING, {"api_key": "sk_test_1"}
    )
    assert connector.id == ConnectorId("con_1")
    # Stored blob is ciphertext, never the plaintext key.
    assert b"sk_test_1" not in store.blobs["con_1"]


def test_register_rejects_missing_required_secret() -> None:
    with pytest.raises(ConnectorAuthError):
        _service(FakeConnectorStore()).register(
            TenantId("tenant-1"), ConnectorType.STRIPE_BILLING, {}
        )


def test_build_authenticated_round_trips() -> None:
    store = FakeConnectorStore()
    service = _service(store)
    connector = service.register(
        TenantId("tenant-1"), ConnectorType.STRIPE_BILLING, {"api_key": "sk_test_1"}
    )
    live = service.build_authenticated(TenantId("tenant-1"), connector.id)
    assert isinstance(live, StripeBillingConnector)


def test_build_authenticated_unknown_connector_raises() -> None:
    with pytest.raises(ConnectorError):
        _service(FakeConnectorStore()).build_authenticated(
            TenantId("tenant-1"), ConnectorId("missing")
        )
