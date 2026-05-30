"""The Money value object (§7, §8 glossary).

Exact decimal arithmetic (never float), currency-safe (no cross-currency operations),
and immutable. Formatting for display (Lora tabular-nums, etc.) is a frontend concern
(§5A) — Money holds the value, not its presentation.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from yieldfield.domain.shared.errors import CurrencyMismatchError, InvalidMoneyError

_CURRENCY_CODE_LENGTH = 3


def _validate_currency(currency: str) -> None:
    if len(currency) != _CURRENCY_CODE_LENGTH or not currency.isalpha() or not currency.isupper():
        raise InvalidMoneyError(
            f"Currency must be a 3-letter uppercase ISO code, got {currency!r}."
        )


@dataclass(frozen=True, slots=True)
class Money:
    """An exact monetary amount in a single currency."""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise InvalidMoneyError(
                f"Money.amount must be a Decimal, got {type(self.amount).__name__}."
            )
        _validate_currency(self.currency)

    @classmethod
    def of(cls, amount: str | int | Decimal, currency: str) -> Money:
        """Build Money from a string, int, or Decimal. Floats are rejected (§7)."""
        if isinstance(amount, float):
            raise InvalidMoneyError("Money rejects float amounts; use a string or Decimal.")
        if not isinstance(amount, (str, int, Decimal)):
            raise InvalidMoneyError(f"Unsupported amount type: {type(amount).__name__}.")
        try:
            value = Decimal(amount)
        except InvalidOperation as exc:
            raise InvalidMoneyError(f"Not a valid decimal amount: {amount!r}.") from exc
        return cls(value, currency)

    @classmethod
    def zero(cls, currency: str) -> Money:
        return cls(Decimal(0), currency)

    # ── arithmetic ───────────────────────────────────────────────────────────
    def _ensure_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatchError(f"Cannot combine {self.currency} with {other.currency}.")

    def __add__(self, other: Money) -> Money:
        self._ensure_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._ensure_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor: int | Decimal) -> Money:
        if isinstance(factor, float) or not isinstance(factor, (int, Decimal)):
            raise InvalidMoneyError("Money can only be multiplied by an int or Decimal, not float.")
        return Money(self.amount * Decimal(factor), self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __abs__(self) -> Money:
        return Money(abs(self.amount), self.currency)

    # ── comparison (currency-safe) ───────────────────────────────────────────
    def __lt__(self, other: Money) -> bool:
        self._ensure_same_currency(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._ensure_same_currency(other)
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._ensure_same_currency(other)
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._ensure_same_currency(other)
        return self.amount >= other.amount

    # ── sign predicates ──────────────────────────────────────────────────────
    @property
    def is_zero(self) -> bool:
        return self.amount == 0

    @property
    def is_positive(self) -> bool:
        return self.amount > 0

    @property
    def is_negative(self) -> bool:
        return self.amount < 0

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"
