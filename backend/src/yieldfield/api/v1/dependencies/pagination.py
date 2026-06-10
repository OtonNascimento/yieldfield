"""Bounded-limit, opaque-cursor pagination (spec §5.1, §10).

The wire contract is cursor-based (stable for the Slice-4 client). Internally the cursor
encodes an offset over the repository's full listing — a named simplification: the 3A
repositories expose `list_*` without keyset queries. Swapping to keyset pagination later
changes only this module, not the API contract.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Query, status

_PREFIX = "o:"


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"{_PREFIX}{offset}".encode()).decode()


def decode_cursor(cursor: str) -> int:
    try:
        text = base64.urlsafe_b64decode(cursor.encode()).decode()
        if not text.startswith(_PREFIX):
            raise ValueError(text)
        offset = int(text.removeprefix(_PREFIX))
        if offset < 0:
            raise ValueError(text)
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid pagination cursor."
        ) from exc
    return offset


@dataclass(frozen=True, slots=True)
class PageParams:
    limit: int
    offset: int


def page_params(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> PageParams:
    return PageParams(limit=limit, offset=decode_cursor(cursor) if cursor else 0)


PageParamsDep = Annotated[PageParams, Depends(page_params)]


def paginate[T](items: Sequence[T], page: PageParams) -> tuple[list[T], str | None]:
    """Slice one page; return (items, next_cursor) with next_cursor=None on the last page."""
    window = list(items[page.offset : page.offset + page.limit])
    has_more = page.offset + page.limit < len(items)
    return window, encode_cursor(page.offset + page.limit) if has_more else None
