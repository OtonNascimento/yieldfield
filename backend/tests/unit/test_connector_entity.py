"""Connector is a pure config entity carrying no secrets (§17, §11)."""

from __future__ import annotations

import pytest

from yieldfield.domain.billing.connector import Connector, ConnectorStatus, ConnectorType
from yieldfield.domain.shared.errors import InvalidEntityError
from yieldfield.domain.shared.ids import ConnectorId, TenantId


def test_connector_defaults_to_active() -> None:
    c = Connector(
        id=ConnectorId("con_1"),
        tenant_id=TenantId("tenant-1"),
        connector_type=ConnectorType.STRIPE_BILLING,
    )
    assert c.status is ConnectorStatus.ACTIVE
    assert c.connector_type.value == "stripe_billing"
    # No secret-bearing fields exist on the entity.
    assert not hasattr(c, "credentials")
    assert not hasattr(c, "encrypted_credentials")


def test_connector_requires_ids() -> None:
    with pytest.raises(InvalidEntityError):
        Connector(
            id=ConnectorId(""),
            tenant_id=TenantId("tenant-1"),
            connector_type=ConnectorType.STRIPE_BILLING,
        )
