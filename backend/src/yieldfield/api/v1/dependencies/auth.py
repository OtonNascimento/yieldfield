"""Bearer-token → tenant resolution (spec §5.1, §11).

Config-driven (`api_tokens`: token → tenant_id) so an OIDC validator can replace this
dependency later without touching any router. Every tenant-scoped route depends on
`CurrentTenant`; no endpoint ever accepts a tenant_id from the client.

The bearer scheme is declared via `HTTPBearer` so it lands in the OpenAPI contract as a
securityScheme the generated client can model (audit API-2). `auto_error=False` keeps
failure shaping here: every missing/malformed/unknown case is the same 401 envelope.
"""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from yieldfield.api.errors.exceptions import UnauthorizedError
from yieldfield.api.v1.dependencies.settings import SettingsDep
from yieldfield.domain.shared.ids import TenantId

_bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Static bearer token mapped to a tenant (OIDC replaces this later, §11).",
)


async def current_tenant(
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer_scheme)] = None,
) -> TenantId:
    # Async on purpose (no I/O): sync dependencies run in the threadpool, where the
    # contextvars bind below would die with the thread's context copy (audit PR-4a).
    if credentials is None:
        raise UnauthorizedError("Missing or invalid bearer token.")
    token = credentials.credentials.strip()
    if not token:
        raise UnauthorizedError("Missing or invalid bearer token.")
    tenant_id = settings.api_tokens.get(token)
    if tenant_id is None:
        raise UnauthorizedError("Missing or invalid bearer token.")
    # Correlate every log line of this request with the tenant (§11, audit PR-4a).
    structlog.contextvars.bind_contextvars(tenant_id=tenant_id)
    return TenantId(tenant_id)


CurrentTenant = Annotated[TenantId, Security(current_tenant)]
