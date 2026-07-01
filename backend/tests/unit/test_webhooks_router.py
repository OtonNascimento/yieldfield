"""Webhooks route by connector_id; the SIGNATURE is the authentication (decision F, §11)."""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import FastAPI
from fastapi.testclient import TestClient

from yieldfield.api.main import create_app
from yieldfield.api.v1.dependencies.services import (
    INGEST_INVOICES_TASK,
    get_connector_store,
    get_job_submitter,
    get_registration_service,
)
from yieldfield.api.v1.dependencies.settings import get_app_settings
from yieldfield.config.settings import Settings
from yieldfield.domain.billing.connector import Connector, ConnectorStatus, ConnectorType
from yieldfield.domain.billing.connector_port import ConnectorCredentials
from yieldfield.domain.billing.invoice import Invoice
from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.shared.ids import ConnectorId, TenantId
from yieldfield.domain.shared.time_window import TimeWindow
from yieldfield.infrastructure.connectors.base.connector import ConnectorAuthError


def _settings() -> Settings:
    return Settings(_env_file=None)  # NOTE: no api_tokens — webhooks use no bearer auth


def _connector() -> Connector:
    return Connector(
        id=ConnectorId("con_1"),
        tenant_id=TenantId("tenant-1"),
        connector_type=ConnectorType.STRIPE_BILLING,
        status=ConnectorStatus.ACTIVE,
    )


class FakeLiveConnector:
    def __init__(self, *, valid: bool) -> None:
        self._valid = valid
        self.verified: list[tuple[bytes, str]] = []

    def authenticate(self, credentials: ConnectorCredentials) -> None:
        return None

    def pull_usage_events(self, window: TimeWindow) -> Iterable[UsageEvent]:
        return []

    def pull_invoices(self, window: TimeWindow) -> Iterable[Invoice]:
        return []

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        self.verified.append((payload, signature))
        return self._valid


class FakeStore:
    def __init__(self, connector: Connector | None) -> None:
        self._connector = connector

    def find_by_id(self, connector_id: ConnectorId) -> Connector | None:
        if self._connector is not None and self._connector.id == connector_id:
            return self._connector
        return None


class FakeRegistration:
    def __init__(self, live: FakeLiveConnector) -> None:
        self.live = live

    def build_authenticated(
        self, tenant_id: TenantId, connector_id: ConnectorId
    ) -> FakeLiveConnector:
        return self.live


class FakeSubmitter:
    def __init__(self) -> None:
        self.submitted: list[tuple[TenantId, str, tuple[str, ...]]] = []

    def submit(self, tenant_id: TenantId, task_name: str, *task_args: str) -> str:
        self.submitted.append((tenant_id, task_name, task_args))
        return "job_x"


def _app(store: FakeStore, registration: FakeRegistration, submitter: FakeSubmitter) -> FastAPI:
    app = create_app(_settings())
    app.dependency_overrides[get_app_settings] = _settings
    app.dependency_overrides[get_connector_store] = lambda: store
    app.dependency_overrides[get_registration_service] = lambda: registration
    app.dependency_overrides[get_job_submitter] = lambda: submitter
    return app


def test_valid_signature_returns_202_and_enqueues_a_repull_for_the_owning_tenant() -> None:
    live = FakeLiveConnector(valid=True)
    submitter = FakeSubmitter()
    client = TestClient(_app(FakeStore(_connector()), FakeRegistration(live), submitter))
    response = client.post(
        "/api/v1/webhooks/con_1",
        content=b'{"type":"invoice.paid"}',
        headers={"Stripe-Signature": "t=1,v1=abc"},
    )
    assert response.status_code == 202
    assert response.json() == {"job_id": "job_x"}
    assert live.verified == [(b'{"type":"invoice.paid"}', "t=1,v1=abc")]
    tenant, task_name, args = submitter.submitted[0]
    assert tenant == TenantId("tenant-1")  # tenant resolved from the connector, not a token
    assert task_name == INGEST_INVOICES_TASK
    assert args[2] == "con_1"  # (start, end, connector_id)


def test_invalid_signature_is_400_and_enqueues_nothing() -> None:
    submitter = FakeSubmitter()
    client = TestClient(
        _app(FakeStore(_connector()), FakeRegistration(FakeLiveConnector(valid=False)), submitter)
    )
    response = client.post(
        "/api/v1/webhooks/con_1", content=b"{}", headers={"Stripe-Signature": "bad"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_webhook_signature"
    assert submitter.submitted == []


def test_missing_signature_header_is_400() -> None:
    client = TestClient(
        _app(
            FakeStore(_connector()),
            FakeRegistration(FakeLiveConnector(valid=False)),
            FakeSubmitter(),
        )
    )
    response = client.post("/api/v1/webhooks/con_1", content=b"{}")
    assert response.status_code == 400


class SecretlessLiveConnector(FakeLiveConnector):
    """A connector registered without the optional webhook_secret (§17) fails closed."""

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        raise ConnectorAuthError("Webhook secret not configured; call authenticate() first.")


def test_connector_without_webhook_secret_fails_closed_with_400_and_enqueues_nothing() -> None:
    submitter = FakeSubmitter()
    client = TestClient(
        _app(
            FakeStore(_connector()),
            FakeRegistration(SecretlessLiveConnector(valid=True)),
            submitter,
        )
    )
    response = client.post(
        "/api/v1/webhooks/con_1", content=b"{}", headers={"Stripe-Signature": "t=1,v1=abc"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "connector_auth_error"
    assert submitter.submitted == []


def test_unknown_connector_id_is_404() -> None:
    client = TestClient(
        _app(FakeStore(None), FakeRegistration(FakeLiveConnector(valid=True)), FakeSubmitter())
    )
    response = client.post(
        "/api/v1/webhooks/nope", content=b"{}", headers={"Stripe-Signature": "t=1,v1=abc"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
