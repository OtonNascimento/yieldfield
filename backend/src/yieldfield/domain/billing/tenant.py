"""Tenant — a customer organization of Yieldfield (§8 glossary, §11 multi-tenancy)."""

from __future__ import annotations

from dataclasses import dataclass

from yieldfield.domain.shared.errors import InvalidEntityError
from yieldfield.domain.shared.ids import TenantId


@dataclass(frozen=True, slots=True)
class Tenant:
    id: TenantId
    name: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise InvalidEntityError("Tenant name is required.")
