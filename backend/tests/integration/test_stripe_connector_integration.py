"""Stripe connector against stripe-mock (deterministic) + a gated live test-mode test.

The connector talks to the v15 StripeClient; here we point it at the official
`stripe/stripe-mock` container via the connector's `base_url`. The live test runs only
when a real STRIPE_TEST_SECRET_KEY is present, so CI passes with no committed secrets
(§11/§16).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from yieldfield.domain.billing.connector_port import ConnectorCredentials
from yieldfield.domain.billing.invoice import Invoice
from yieldfield.domain.shared.ids import TenantId
from yieldfield.domain.shared.time_window import TimeWindow
from yieldfield.infrastructure.connectors.stripe_billing.connector import StripeBillingConnector

pytestmark = pytest.mark.integration

_WIDE = TimeWindow(datetime(2015, 1, 1, tzinfo=UTC), datetime(2035, 1, 1, tzinfo=UTC))
_CREDS = {"api_key": "sk_test_123", "webhook_secret": "whsec_x"}


def _connector(base_url: str | None) -> StripeBillingConnector:
    connector = StripeBillingConnector(TenantId("t_1"), base_url=base_url)
    connector.authenticate(ConnectorCredentials(secrets=_CREDS))
    return connector


def test_pull_invoices_maps_mock_data_and_stamps_tenant(stripe_mock_base_url: str) -> None:
    invoices = list(_connector(stripe_mock_base_url).pull_invoices(_WIDE))
    assert all(isinstance(inv, Invoice) for inv in invoices)
    assert all(inv.tenant_id == "t_1" for inv in invoices)  # tenant stamping (mock = canned data)


def test_pull_usage_events_executes_against_mock(stripe_mock_base_url: str) -> None:
    events = list(_connector(stripe_mock_base_url).pull_usage_events(_WIDE))  # may be empty
    assert all(event.tenant_id == "t_1" for event in events)


def test_live_test_mode_invoices_when_key_present() -> None:
    key = os.environ.get("STRIPE_TEST_SECRET_KEY")
    if not key:
        pytest.skip("STRIPE_TEST_SECRET_KEY not set; skipping live Stripe test-mode test")
    connector = StripeBillingConnector(TenantId("t_1"))
    connector.authenticate(ConnectorCredentials(secrets={"api_key": key}))
    invoices = list(connector.pull_invoices(_WIDE))
    assert all(inv.tenant_id == "t_1" for inv in invoices)
