"""Domain error hierarchy (§7).

Financial-correctness errors must fail loudly, never be silently swallowed (§6 —
"fail loudly in dev"). Every domain error derives from `DomainError` so the
application/API layers can map the whole family onto the error envelope (§10).
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for all domain rule violations."""


class InvalidMoneyError(DomainError):
    """A Money value was constructed from an invalid amount or currency."""


class CurrencyMismatchError(DomainError):
    """An operation combined two Money values of different currencies."""


class InvalidTimeWindowError(DomainError):
    """A TimeWindow was constructed with an invalid or naive range."""


class InvalidEntityError(DomainError):
    """A domain entity was constructed violating one of its invariants."""


class InvalidFindingTransitionError(DomainError):
    """An illegal finding lifecycle transition was attempted (§4)."""
