"""POST/GET /connectors (spec §5.2): register (validate→encrypt→persist) and list.

The tenant comes from the bearer token, never the body (§11). Registration delegates to
the infrastructure ConnectorRegistrationService via its dependency; bad credentials raise
ConnectorAuthError → 400 `connector_auth_error` (spec §5.4). Update/delete/OAuth are
out of scope this slice (spec §0).
"""

from __future__ import annotations

from fastapi import APIRouter, status

from yieldfield.api.v1.dependencies.auth import CurrentTenant
from yieldfield.api.v1.dependencies.pagination import PageParamsDep, paginate
from yieldfield.api.v1.dependencies.services import ConnectorStoreDep, RegistrationDep
from yieldfield.api.v1.schemas.common import PageMeta
from yieldfield.api.v1.schemas.connectors import ConnectorCreate, ConnectorPage, ConnectorPublic

router = APIRouter(prefix="/connectors", tags=["connectors"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Register a billing-platform connector",
    response_model=ConnectorPublic,
)
def register_connector(
    body: ConnectorCreate, tenant_id: CurrentTenant, registration: RegistrationDep
) -> ConnectorPublic:
    connector = registration.register(tenant_id, body.connector_type, body.secrets)
    return ConnectorPublic.from_connector(connector)


@router.get("", summary="List the tenant's connectors", response_model=ConnectorPage)
def list_connectors(
    tenant_id: CurrentTenant, store: ConnectorStoreDep, page: PageParamsDep
) -> ConnectorPage:
    items, next_cursor = paginate(store.list_for_tenant(tenant_id), page)
    return ConnectorPage(
        items=[ConnectorPublic.from_connector(c) for c in items],
        meta=PageMeta(next_cursor=next_cursor),
    )
