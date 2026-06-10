"""Shared DTO primitives (spec §5.3): money-as-string, windows, pagination, job handles."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator, model_validator

from yieldfield.domain.shared.money import Money
from yieldfield.domain.shared.time_window import TimeWindow


class MoneyRead(BaseModel):
    """Money over JSON: a decimal STRING amount — floats never touch money (§7)."""

    amount: str
    currency: str

    @classmethod
    def from_money(cls, money: Money) -> MoneyRead:
        return cls(amount=str(money.amount), currency=money.currency)


class WindowRead(BaseModel):
    start: datetime
    end: datetime

    @classmethod
    def from_window(cls, window: TimeWindow) -> WindowRead:
        return cls(start=window.start, end=window.end)


class WindowParam(BaseModel):
    """Inbound window: validated at the boundary (422) before touching the domain."""

    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def _tz_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("must be timezone-aware (ISO-8601 with offset)")
        return value

    @model_validator(mode="after")
    def _ordered(self) -> WindowParam:
        if self.end < self.start:
            raise ValueError("end must not be before start")
        return self

    def to_window(self) -> TimeWindow:
        return TimeWindow(self.start, self.end)


class PageMeta(BaseModel):
    """Opaque-cursor pagination metadata (§10). `next_cursor=None` means last page."""

    next_cursor: str | None = None


class JobAccepted(BaseModel):
    """The 202 handle every async POST returns (spec §3)."""

    job_id: str
