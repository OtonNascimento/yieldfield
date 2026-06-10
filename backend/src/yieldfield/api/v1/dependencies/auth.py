"""Bearer-token → tenant resolution (spec §5.1, §11).

Config-driven (`api_tokens`: token → tenant_id) so an OIDC validator can replace this
dependency later without touching any router. Every tenant-scoped route depends on
`CurrentTenant`; no endpoint ever accepts a tenant_id from the client.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header

from yieldfield.api.errors.exceptions import UnauthorizedError
from yieldfield.api.v1.dependencies.settings import SettingsDep
from yieldfield.domain.shared.ids import TenantId

_BEARER_PREFIX = "Bearer "


def current_tenant(
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> TenantId:
    if not authorization or not authorization.startswith(_BEARER_PREFIX):
        raise UnauthorizedError("Missing or invalid bearer token.")
    token = authorization.removeprefix(_BEARER_PREFIX).strip()
    if not token:
        raise UnauthorizedError("Missing or invalid bearer token.")
    tenant_id = settings.api_tokens.get(token)
    if tenant_id is None:
        raise UnauthorizedError("Missing or invalid bearer token.")
    return TenantId(tenant_id)


CurrentTenant = Annotated[TenantId, Depends(current_tenant)]
