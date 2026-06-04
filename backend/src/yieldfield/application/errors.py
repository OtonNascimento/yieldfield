"""Application-layer errors (§4.4).

Use-case-level failures that the API (Plan 3C) maps onto the error envelope (§10). They are
distinct from domain rule violations (`DomainError`) and from infrastructure `PersistenceError`
— the application layer never imports infrastructure (4th import contract, §14), so the
infrastructure error is mapped at the API boundary, not re-raised here.
"""

from __future__ import annotations


class ApplicationError(Exception):
    """Base class for application/use-case errors."""


class EntityNotFoundError(ApplicationError):
    """A requested entity does not exist for the tenant (§4.4) → HTTP 404 in the API."""
