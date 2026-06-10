"""Ingestion trigger DTO (spec §5.2): which connector, which window."""

from __future__ import annotations

from pydantic import BaseModel

from yieldfield.api.v1.schemas.common import WindowParam


class IngestionRequest(BaseModel):
    connector_id: str
    window: WindowParam
