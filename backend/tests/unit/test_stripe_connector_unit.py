"""Connector unit tests: port conformance, missing-credential failure, webhook verify."""

from __future__ import annotations

import hashlib
import hmac
import time

import pytest

from yieldfield.domain.billing.connector_port import ConnectorCredentials, ConnectorPort
from yieldfield.domain.shared.ids import TenantId
from yieldfield.infrastructure.connectors.base.connector import ConnectorAuthError
from yieldfield.infrastructure.connectors.stripe_billing.connector import StripeBillingConnector

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


def test_verify_webhook_fails_closed_when_no_webhook_secret_is_configured() -> None:
    # webhook_secret is an OPTIONAL credential (§17); a connector registered without one
    # must never accept a webhook — raising beats silently returning True (§11).
    c = StripeBillingConnector(TenantId("t_1"))
    c.authenticate(ConnectorCredentials(secrets={"api_key": "sk_test_x"}))
    payload = b'{"id":"evt_1","object":"event"}'
    with pytest.raises(ConnectorAuthError):
        c.verify_webhook(payload, _sign(payload, _SECRET, int(time.time())))
