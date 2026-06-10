"""Auth resolves tenants from bearer tokens; cursors are opaque and bounded (spec §5.1)."""

from __future__ import annotations

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
from yieldfield.config.settings import Settings
from yieldfield.domain.shared.ids import TenantId


def _settings() -> Settings:
    return Settings(_env_file=None, api_tokens={"tok-1": "tenant-1"})


def test_current_tenant_resolves_token_to_tenant() -> None:
    assert current_tenant(_settings(), authorization="Bearer tok-1") == TenantId("tenant-1")


def test_current_tenant_rejects_missing_header() -> None:
    with pytest.raises(UnauthorizedError):
        current_tenant(_settings(), authorization=None)


def test_current_tenant_rejects_non_bearer_scheme() -> None:
    with pytest.raises(UnauthorizedError):
        current_tenant(_settings(), authorization="Basic tok-1")


def test_current_tenant_rejects_unknown_token() -> None:
    with pytest.raises(UnauthorizedError):
        current_tenant(_settings(), authorization="Bearer nope")


def test_cursor_round_trips_and_is_opaque() -> None:
    cursor = encode_cursor(150)
    assert cursor != "150"  # opaque, not a bare offset (§10)
    assert decode_cursor(cursor) == 150


def test_garbage_cursor_is_a_400() -> None:
    with pytest.raises(HTTPException) as excinfo:
        decode_cursor("not-a-cursor")
    assert excinfo.value.status_code == 400


def test_paginate_slices_and_signals_the_last_page() -> None:
    items = list(range(10))
    first, cursor = paginate(items, PageParams(limit=4, offset=0))
    assert first == [0, 1, 2, 3] and cursor is not None
    middle, cursor2 = paginate(items, PageParams(limit=4, offset=decode_cursor(cursor)))
    assert middle == [4, 5, 6, 7] and cursor2 is not None
    last, end = paginate(items, PageParams(limit=4, offset=decode_cursor(cursor2)))
    assert last == [8, 9] and end is None
