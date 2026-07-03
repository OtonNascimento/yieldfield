"""Auth resolves tenants from bearer tokens; cursors are opaque and bounded (spec §5.1)."""

from __future__ import annotations

import asyncio
import base64

import pytest
from fastapi import HTTPException

from yieldfield.api.errors.exceptions import UnauthorizedError
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


def test_current_tenant_resolves_token_to_tenant() -> None:
    resolved = asyncio.run(current_tenant(_settings(), authorization="Bearer tok-1"))
    assert resolved == TenantId("tenant-1")


def test_current_tenant_rejects_missing_header() -> None:
    with pytest.raises(UnauthorizedError):
        asyncio.run(current_tenant(_settings(), authorization=None))


def test_current_tenant_rejects_non_bearer_scheme() -> None:
    with pytest.raises(UnauthorizedError):
        asyncio.run(current_tenant(_settings(), authorization="Basic tok-1"))


def test_current_tenant_rejects_unknown_token() -> None:
    with pytest.raises(UnauthorizedError):
        asyncio.run(current_tenant(_settings(), authorization="Bearer nope"))


def test_current_tenant_rejects_empty_bearer_token() -> None:
    with pytest.raises(UnauthorizedError):
        asyncio.run(current_tenant(_settings(), authorization="Bearer   "))


def test_cursor_round_trips_and_is_opaque() -> None:
    cursor = encode_cursor(150)
    assert cursor != "150"  # opaque, not a bare offset (§10)
    assert decode_cursor(cursor) == 150


def test_garbage_cursor_is_a_400() -> None:
    with pytest.raises(HTTPException) as excinfo:
        decode_cursor("not-a-cursor")
    assert excinfo.value.status_code == 400


@pytest.mark.parametrize(
    "raw",
    [
        base64.urlsafe_b64encode(b"o:-5").decode(),  # negative offset inside valid base64
        base64.urlsafe_b64encode(b"x:5").decode(),  # wrong prefix inside valid base64
    ],
)
def test_semantic_cursor_guards_are_a_400(raw: str) -> None:
    with pytest.raises(HTTPException) as excinfo:
        decode_cursor(raw)
    assert excinfo.value.status_code == 400


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
