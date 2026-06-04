"""Connector factory (§17) — the one place a connector type maps to its adapter class.

Adding a platform = a new ConnectorType member + a branch here + the adapter package.
Nothing in reconciliation or the API changes. Returns an *unauthenticated* connector;
the registration service authenticates it.
"""

from __future__ import annotations

from yieldfield.domain.billing.connector import Connector, ConnectorType
from yieldfield.domain.billing.connector_port import ConnectorPort
from yieldfield.infrastructure.connectors.base.connector import ConnectorError
from yieldfield.infrastructure.connectors.stripe_billing.connector import StripeBillingConnector


def build_connector(connector: Connector, *, base_url: str | None = None) -> ConnectorPort:
    """Construct the concrete connector for `connector.connector_type` (not yet authenticated)."""
    if connector.connector_type == ConnectorType.STRIPE_BILLING:
        return StripeBillingConnector(connector.tenant_id, base_url=base_url)
    raise ConnectorError(f"Unsupported connector type: {connector.connector_type!r}.")
