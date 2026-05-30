"""Money value object — a money path, tested hardest (§7).

Money is the canonical representation of a dollar (or other-currency) figure across
the domain. It must be exact (no float), currency-safe (no cross-currency arithmetic),
and immutable.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from yieldfield.domain.shared.errors import CurrencyMismatchError, InvalidMoneyError
from yieldfield.domain.shared.money import Money


class TestConstruction:
    def test_of_accepts_string_and_normalises_to_decimal(self) -> None:
        money = Money.of("10.00", "USD")
        assert money.amount == Decimal("10.00")
        assert money.currency == "USD"

    def test_of_accepts_int(self) -> None:
        assert Money.of(10, "USD").amount == Decimal(10)

    def test_of_rejects_float_to_avoid_binary_rounding(self) -> None:
        # Floats silently lose cents; the domain must refuse them.
        with pytest.raises(InvalidMoneyError):
            Money.of(10.1, "USD")  # type: ignore[arg-type]

    def test_zero_factory(self) -> None:
        zero = Money.zero("EUR")
        assert zero.amount == Decimal(0)
        assert zero.currency == "EUR"
        assert zero.is_zero

    def test_currency_must_be_three_letter_iso_code(self) -> None:
        with pytest.raises(InvalidMoneyError):
            Money.of("1.00", "usd")  # lowercase
        with pytest.raises(InvalidMoneyError):
            Money.of("1.00", "US")  # too short
        with pytest.raises(InvalidMoneyError):
            Money.of("1.00", "USDD")  # too long


class TestImmutabilityAndEquality:
    def test_is_frozen(self) -> None:
        money = Money.of("1.00", "USD")
        with pytest.raises(FrozenInstanceError):
            money.amount = Decimal("2.00")  # type: ignore[misc]

    def test_value_equality_ignores_decimal_exponent(self) -> None:
        assert Money.of("10.0", "USD") == Money.of("10.00", "USD")

    def test_inequality_across_currencies(self) -> None:
        assert Money.of("10.00", "USD") != Money.of("10.00", "EUR")

    def test_hashable_and_usable_in_sets(self) -> None:
        assert len({Money.of("10.0", "USD"), Money.of("10.00", "USD")}) == 1


class TestArithmetic:
    def test_add_same_currency(self) -> None:
        assert Money.of("10.00", "USD") + Money.of("5.50", "USD") == Money.of("15.50", "USD")

    def test_subtract_same_currency(self) -> None:
        assert Money.of("10.00", "USD") - Money.of("3.00", "USD") == Money.of("7.00", "USD")

    def test_add_rejects_cross_currency(self) -> None:
        with pytest.raises(CurrencyMismatchError):
            Money.of("10.00", "USD") + Money.of("5.00", "EUR")

    def test_subtract_rejects_cross_currency(self) -> None:
        with pytest.raises(CurrencyMismatchError):
            Money.of("10.00", "USD") - Money.of("5.00", "EUR")

    def test_multiply_by_int_and_decimal(self) -> None:
        assert Money.of("10.00", "USD") * 3 == Money.of("30.00", "USD")
        assert Money.of("10.00", "USD") * Decimal("1.5") == Money.of("15.00", "USD")

    def test_multiply_rejects_float(self) -> None:
        with pytest.raises(InvalidMoneyError):
            Money.of("10.00", "USD") * 1.5  # type: ignore[operator]

    def test_negate(self) -> None:
        assert -Money.of("10.00", "USD") == Money.of("-10.00", "USD")

    def test_abs(self) -> None:
        assert abs(Money.of("-10.00", "USD")) == Money.of("10.00", "USD")


class TestSignPredicates:
    def test_is_positive_negative_zero(self) -> None:
        assert Money.of("1.00", "USD").is_positive
        assert Money.of("-1.00", "USD").is_negative
        assert Money.zero("USD").is_zero
        assert not Money.zero("USD").is_positive
        assert not Money.zero("USD").is_negative


class TestComparison:
    def test_ordering_same_currency(self) -> None:
        assert Money.of("1.00", "USD") < Money.of("2.00", "USD")
        assert Money.of("2.00", "USD") > Money.of("1.00", "USD")
        assert Money.of("1.00", "USD") <= Money.of("1.00", "USD")

    def test_ordering_rejects_cross_currency(self) -> None:
        with pytest.raises(CurrencyMismatchError):
            _ = Money.of("1.00", "USD") < Money.of("2.00", "EUR")


# ── Property-based (§7: property tests on the money paths) ────────────────────
money_amounts = st.decimals(
    min_value=Decimal("-1000000"),
    max_value=Decimal("1000000"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)


class TestProperties:
    @given(a=money_amounts, b=money_amounts)
    def test_addition_is_commutative(self, a: Decimal, b: Decimal) -> None:
        ma, mb = Money(a, "USD"), Money(b, "USD")
        assert ma + mb == mb + ma

    @given(a=money_amounts, b=money_amounts)
    def test_subtraction_inverts_addition(self, a: Decimal, b: Decimal) -> None:
        ma, mb = Money(a, "USD"), Money(b, "USD")
        assert (ma + mb) - mb == ma

    @given(a=money_amounts)
    def test_double_negation_is_identity(self, a: Decimal) -> None:
        money = Money(a, "USD")
        negated = -money
        assert -negated == money
