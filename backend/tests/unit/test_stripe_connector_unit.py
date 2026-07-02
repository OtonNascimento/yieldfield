"""Connector unit tests: port conformance, missing-credential failure, webhook verify,
and invoice-pull window semantics (created-scan pad + period-overlap filter)."""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from yieldfield.domain.billing.connector_port import ConnectorCredentials, ConnectorPort
from yieldfield.domain.shared.ids import TenantId
from yieldfield.domain.shared.time_window import TimeWindow
from yieldfield.infrastructure.connectors.base.connector import ConnectorAuthError
from yieldfield.infrastructure.connectors.stripe_billing.connector import (
    _CREATED_SCAN_PAD,
    StripeBillingConnector,
)

_SECRET = "whsec_test"  # noqa: S105 - dummy test secret, not a real credential


def _sign(payload: bytes, secret: str, timestamp: int) -> str:
    signed = f"{timestamp}.{payload.decode()}".encode()
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def _authed() -> StripeBillingConnector:
    c = StripeBillingConnector(TenantId("t_1"))
    c.authenticate(
        ConnectorCredentials(secrets={"api_key": "sk_test_x", "webhook_secret": _SECRET})
    )
    return c


def test_connector_satisfies_the_domain_port() -> None:
    assert isinstance(StripeBillingConnector(TenantId("t_1")), ConnectorPort)


def test_authenticate_requires_api_key() -> None:
    c = StripeBillingConnector(TenantId("t_1"))
    with pytest.raises(ConnectorAuthError, match="api_key"):
        c.authenticate(ConnectorCredentials(secrets={}))


def test_verify_webhook_accepts_a_valid_signature() -> None:
    # stripe 15.x construct_event checks event.object after parsing; include it.
    payload = b'{"id":"evt_1","object":"event","type":"invoice.created"}'
    header = _sign(payload, _SECRET, int(time.time()))
    assert _authed().verify_webhook(payload, header) is True


def test_verify_webhook_rejects_a_tampered_payload() -> None:
    payload = b'{"id":"evt_1","object":"event","type":"invoice.created"}'
    header = _sign(payload, _SECRET, int(time.time()))
    assert _authed().verify_webhook(b'{"id":"evil","object":"event"}', header) is False


def test_verify_webhook_rejects_a_stale_timestamp() -> None:
    payload = b'{"id":"evt_1","object":"event"}'
    header = _sign(payload, _SECRET, int(time.time()) - 10_000)  # outside tolerance
    assert _authed().verify_webhook(payload, header) is False


def _stripe_invoice(invoice_id: str, period_start: datetime, period_end: datetime) -> Any:
    line = SimpleNamespace(
        id=f"il_{invoice_id}",
        description="api_call",
        price=None,
        quantity=1,
        amount=100,
        currency="usd",
    )
    return SimpleNamespace(
        id=invoice_id,
        customer="cus_1",
        period_start=int(period_start.timestamp()),
        period_end=int(period_end.timestamp()),
        currency="usd",
        lines=SimpleNamespace(data=[line]),
    )


class _FakeInvoicesApi:
    def __init__(self, invoices: list[Any]) -> None:
        self._invoices = invoices
        self.requested_params: dict[str, Any] | None = None

    def list(self, params: dict[str, Any]) -> Any:
        self.requested_params = params
        invoices = self._invoices
        return SimpleNamespace(auto_paging_iter=lambda: iter(invoices))


def test_pull_invoices_scans_padded_created_range_and_filters_by_period_overlap() -> None:
    # Stripe can only filter by CREATION time, but the money path means "billing
    # period" by a window: scan a padded created-range, keep period-overlapping
    # invoices — an arrears invoice created after the window must still arrive,
    # and a non-overlapping period must never leak in (audit API-1).
    window = TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))
    overlapping = _stripe_invoice(
        "in_overlap", datetime(2025, 12, 15, tzinfo=UTC), datetime(2026, 1, 15, tzinfo=UTC)
    )
    outside = _stripe_invoice(
        "in_outside", datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC)
    )
    fake_api = _FakeInvoicesApi([overlapping, outside])
    connector = _authed()
    connector._client = SimpleNamespace(v1=SimpleNamespace(invoices=fake_api))  # type: ignore[assignment]

    pulled = list(connector.pull_invoices(window))

    assert [inv.id for inv in pulled] == ["in_overlap"]
    assert fake_api.requested_params is not None
    created = fake_api.requested_params["created"]
    assert created["gte"] == int((window.start - _CREATED_SCAN_PAD).timestamp())
    assert created["lt"] == int((window.end + _CREATED_SCAN_PAD).timestamp())


def test_verify_webhook_fails_closed_when_no_webhook_secret_is_configured() -> None:
    # webhook_secret is an OPTIONAL credential (§17); a connector registered without one
    # must never accept a webhook — raising beats silently returning True (§11).
    c = StripeBillingConnector(TenantId("t_1"))
    c.authenticate(ConnectorCredentials(secrets={"api_key": "sk_test_x"}))
    payload = b'{"id":"evt_1","object":"event"}'
    with pytest.raises(ConnectorAuthError):
        c.verify_webhook(payload, _sign(payload, _SECRET, int(time.time())))
