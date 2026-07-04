"""Auth resolves tenants from bearer tokens; cursors are opaque and bounded (spec §5.1)."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Sequence

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from yieldfield.api.errors.exceptions import InvalidCursorError, UnauthorizedError
from yieldfield.api.v1.dependencies.auth import current_tenant
from yieldfield.api.v1.dependencies.pagination import (
    PageParams,
    decode_cursor,
    encode_cursor,
    paginate,
)
from yieldfield.api.v1.dependencies.services import _cipher
from yieldfield.config.settings import Settings
from yieldfield.domain.shared.ids import TenantId
from yieldfield.infrastructure.security.credential_cipher import CredentialCipherError


def _settings() -> Settings:
    return Settings(_env_file=None, api_tokens={"tok-1": "tenant-1"})


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_current_tenant_resolves_token_to_tenant() -> None:
    resolved = asyncio.run(current_tenant(_settings(), credentials=_creds("tok-1")))
    assert resolved == TenantId("tenant-1")


def test_current_tenant_rejects_missing_credentials() -> None:
    with pytest.raises(UnauthorizedError):
        asyncio.run(current_tenant(_settings(), credentials=None))


def test_current_tenant_rejects_unknown_token() -> None:
    with pytest.raises(UnauthorizedError):
        asyncio.run(current_tenant(_settings(), credentials=_creds("nope")))


def test_current_tenant_rejects_empty_bearer_token() -> None:
    with pytest.raises(UnauthorizedError):
        asyncio.run(current_tenant(_settings(), credentials=_creds("   ")))


def _connectors_client() -> TestClient:
    from yieldfield.api.main import create_app
    from yieldfield.api.v1.dependencies.services import get_connector_store
    from yieldfield.api.v1.dependencies.settings import get_app_settings
    from yieldfield.domain.billing.connector import Connector

    class _EmptyStore:
        def list_for_tenant(self, tenant_id: object) -> Sequence[Connector]:
            return []

    settings = _settings()
    app = create_app(settings)
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_connector_store] = lambda: _EmptyStore()
    return TestClient(app)


def test_non_bearer_scheme_is_401_at_the_route() -> None:
    # Scheme parsing now lives in HTTPBearer (the OpenAPI securityScheme, audit API-2);
    # a Basic header must still resolve to the same 401 envelope.
    response = _connectors_client().get(
        "/api/v1/connectors", headers={"Authorization": "Basic tok-1"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_lowercase_bearer_scheme_authenticates_at_the_route() -> None:
    # HTTPBearer matches the scheme case-insensitively (RFC 7235). This deliberately
    # liberalizes the old exact-"Bearer " check; pin it so a future refactor doesn't
    # silently flip it back.
    response = _connectors_client().get(
        "/api/v1/connectors", headers={"Authorization": "bearer tok-1"}
    )
    assert response.status_code == 200


def test_garbage_cursor_is_400_invalid_cursor_at_the_route() -> None:
    # The production raise happens inside dependency solving (page_params), not a route
    # body — pin the full path the audit finding (API-3) was about.
    response = _connectors_client().get(
        "/api/v1/connectors?cursor=not-a-cursor",
        headers={"Authorization": "Bearer tok-1"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_cursor"


def test_cursor_round_trips_and_is_opaque() -> None:
    cursor = encode_cursor(150)
    assert cursor != "150"  # opaque, not a bare offset (§10)
    assert decode_cursor(cursor) == 150


def test_garbage_cursor_raises_the_typed_error() -> None:
    # Typed (audit API-3): the envelope carries `invalid_cursor`, not a generic http_400.
    with pytest.raises(InvalidCursorError):
        decode_cursor("not-a-cursor")


@pytest.mark.parametrize(
    "raw",
    [
        base64.urlsafe_b64encode(b"o:-5").decode(),  # negative offset inside valid base64
        base64.urlsafe_b64encode(b"x:5").decode(),  # wrong prefix inside valid base64
    ],
)
def test_semantic_cursor_guards_raise_the_typed_error(raw: str) -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor(raw)


def test_paginate_slices_and_signals_the_last_page() -> None:
    items = list(range(10))
    first, cursor = paginate(items, PageParams(limit=4, offset=0))
    assert first == [0, 1, 2, 3] and cursor is not None
    middle, cursor2 = paginate(items, PageParams(limit=4, offset=decode_cursor(cursor)))
    assert middle == [4, 5, 6, 7] and cursor2 is not None
    last, end = paginate(items, PageParams(limit=4, offset=decode_cursor(cursor2)))
    assert last == [8, 9] and end is None


def test_paginate_exact_last_page_boundary() -> None:
    # offset + limit == len(items) exactly → no next page (off-by-one guard)
    items, next_cursor = paginate(list(range(10)), PageParams(limit=5, offset=5))
    assert items == [5, 6, 7, 8, 9] and next_cursor is None


def test_cipher_requires_credentials_key() -> None:
    # Misconfiguration (no credentials_key) intentionally surfaces as a 500 via CredentialCipherError.
    with pytest.raises(CredentialCipherError):
        _cipher(Settings(_env_file=None))
