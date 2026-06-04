"""The factory maps a Connector's type to its concrete adapter (§17)."""

from __future__ import annotations

import pytest

from yieldfield.domain.billing.connector import Connector, ConnectorType
from yieldfield.domain.shared.ids import ConnectorId, TenantId
from yieldfield.infrastructure.connectors.base.connector import ConnectorError
from yieldfield.infrastructure.connectors.factory import build_connector
from yieldfield.infrastructure.connectors.stripe_billing.connector import StripeBillingConnector


def test_build_stripe_connector() -> None:
    connector = Connector(
        id=ConnectorId("con_1"),
        tenant_id=TenantId("tenant-1"),
        connector_type=ConnectorType.STRIPE_BILLING,
    )
    live = build_connector(connector, base_url="http://stripe-mock:12111")
    assert isinstance(live, StripeBillingConnector)


def test_unsupported_type_raises() -> None:
    connector = Connector(
        id=ConnectorId("con_1"),
        tenant_id=TenantId("tenant-1"),
        connector_type=ConnectorType.STRIPE_BILLING,
    )
    # Force an unmapped value to prove the guard fires for future types.
    object.__setattr__(connector, "connector_type", "metronome")
    # match= pins the message so the offending type stays in the diagnostic.
    with pytest.raises(ConnectorError, match="metronome"):
        build_connector(connector)
