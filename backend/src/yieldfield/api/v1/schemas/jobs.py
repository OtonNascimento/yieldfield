"""Job status DTO (spec §5.2) — the poll surface for all async operations.

Plain `str` enums keep schemas infrastructure-free (the Job enums live in
infrastructure/persistence); routers map `.value` when building this DTO.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class JobStatusRead(BaseModel):
    job_id: str
    job_type: str
    status: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    result_type: str | None = None
    result_ref: str | None = None
