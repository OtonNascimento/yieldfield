"""Connector port (§17) — the interface every billing connector implements.

Defined in domain/billing/ (per the project decision). Concrete connectors live in
infrastructure/connectors/<name>/ (Slice 2) and need touch nothing else.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal

from yieldfield.domain.billing.connector_port import ConnectorCredentials, ConnectorPort
from yieldfield.domain.billing.invoice import Invoice
from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.shared.ids import TenantId, UsageEventId
from yieldfield.domain.shared.time_window import TimeWindow


class FakeConnector:
    """A minimal in-memory connector satisfying the port structurally."""

    def authenticate(self, credentials: ConnectorCredentials) -> None:
        self.authenticated_with = credentials

    def pull_usage_events(self, window: TimeWindow) -> Iterable[UsageEvent]:
        return [
            UsageEvent(
                id=UsageEventId("u_1"),
                tenant_id=TenantId("t_1"),
                customer_id="cust_42",
                metric="api_calls",
                quantity=Decimal("100"),
                occurred_at=datetime(2026, 1, 2, tzinfo=UTC),
            )
        ]

    def pull_invoices(self, window: TimeWindow) -> Iterable[Invoice]:
        return []

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        return signature == "valid-signature"


def _window() -> TimeWindow:
    return TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))


class TestProtocolConformance:
    def test_complete_connector_satisfies_port(self) -> None:
        assert isinstance(FakeConnector(), ConnectorPort)

    def test_incomplete_connector_does_not_satisfy_port(self) -> None:
        class Partial:
            def authenticate(self, credentials: ConnectorCredentials) -> None: ...

        assert not isinstance(Partial(), ConnectorPort)


class TestCredentialsDto:
    def test_carries_named_secrets(self) -> None:
        creds = ConnectorCredentials(secrets={"api_key": "sk_test_123"})
        assert creds.secrets["api_key"] == "sk_test_123"


class TestPortBehaviourThroughFake:
    def test_pull_usage_events_returns_domain_events(self) -> None:
        connector: ConnectorPort = FakeConnector()
        events = list(connector.pull_usage_events(_window()))
        assert events[0].metric == "api_calls"

    def test_verify_webhook(self) -> None:
        connector: ConnectorPort = FakeConnector()
        assert connector.verify_webhook(b"{}", "valid-signature") is True
        assert connector.verify_webhook(b"{}", "forged") is False
