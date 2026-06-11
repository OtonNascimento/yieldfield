"""POST/GET /connectors: register validates creds; responses never carry secrets (§11)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from fastapi import FastAPI
from fastapi.testclient import TestClient

from yieldfield.api.main import create_app
from yieldfield.api.v1.dependencies.services import get_connector_store, get_registration_service
from yieldfield.api.v1.dependencies.settings import get_app_settings
from yieldfield.config.settings import Settings
from yieldfield.domain.billing.connector import Connector, ConnectorStatus, ConnectorType
from yieldfield.domain.shared.ids import ConnectorId, TenantId
from yieldfield.infrastructure.connectors.base.connector import ConnectorAuthError

AUTH = {"Authorization": "Bearer tok-1"}


def _settings() -> Settings:
    return Settings(_env_file=None, api_tokens={"tok-1": "tenant-1"})


def _connector(connector_id: str = "con_1") -> Connector:
    return Connector(
        id=ConnectorId(connector_id),
        tenant_id=TenantId("tenant-1"),
        connector_type=ConnectorType.STRIPE_BILLING,
        status=ConnectorStatus.ACTIVE,
    )


class FakeRegistration:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[TenantId, ConnectorType, Mapping[str, str]]] = []

    def register(
        self, tenant_id: TenantId, connector_type: ConnectorType, secrets: Mapping[str, str]
    ) -> Connector:
        self.calls.append((tenant_id, connector_type, secrets))
        if self.fail:
            raise ConnectorAuthError("Missing required credential: 'api_key'.")
        return _connector()


class FakeStore:
    def __init__(self, connectors: Sequence[Connector]) -> None:
        self._connectors = connectors

    def list_for_tenant(self, tenant_id: TenantId) -> Sequence[Connector]:
        return list(self._connectors)


def _app(registration: FakeRegistration, store: FakeStore | None = None) -> FastAPI:
    app = create_app(_settings())
    app.dependency_overrides[get_app_settings] = _settings
    app.dependency_overrides[get_registration_service] = lambda: registration
    app.dependency_overrides[get_connector_store] = lambda: store or FakeStore([])
    return app


def test_register_returns_201_public_shape_and_no_secrets() -> None:
    registration = FakeRegistration()
    client = TestClient(_app(registration))
    response = client.post(
        "/api/v1/connectors",
        headers=AUTH,
        json={"connector_type": "stripe_billing", "secrets": {"api_key": "sk_test_1"}},
    )
    assert response.status_code == 201
    body = response.json()
    assert body == {"id": "con_1", "connector_type": "stripe_billing", "status": "active"}
    assert "sk_test_1" not in response.text  # the secret never round-trips (§11)
    assert registration.calls[0][0] == TenantId("tenant-1")  # tenant from the token, not the body


def test_register_with_bad_credentials_is_400_connector_auth_error() -> None:
    client = TestClient(_app(FakeRegistration(fail=True)))
    response = client.post(
        "/api/v1/connectors",
        headers=AUTH,
        json={"connector_type": "stripe_billing", "secrets": {}},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "connector_auth_error"


def test_list_connectors_paginates() -> None:
    store = FakeStore([_connector(f"con_{i}") for i in range(3)])
    client = TestClient(_app(FakeRegistration(), store))
    response = client.get("/api/v1/connectors?limit=2", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert [c["id"] for c in body["items"]] == ["con_0", "con_1"]
    assert body["meta"]["next_cursor"] is not None
    response2 = client.get(
        f"/api/v1/connectors?limit=2&cursor={body['meta']['next_cursor']}", headers=AUTH
    )
    assert [c["id"] for c in response2.json()["items"]] == ["con_2"]
    assert response2.json()["meta"]["next_cursor"] is None


def test_unknown_connector_type_is_422() -> None:
    client = TestClient(_app(FakeRegistration()))
    response = client.post(
        "/api/v1/connectors",
        headers=AUTH,
        json={"connector_type": "metronome", "secrets": {}},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_connectors_require_bearer_auth() -> None:
    client = TestClient(_app(FakeRegistration()))
    assert client.get("/api/v1/connectors").status_code == 401
