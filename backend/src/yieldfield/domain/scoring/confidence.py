"""Confidence — a probability in [0, 1] (§6.4).

The probabilistic core's internal representation. The user never sees this number;
they see dollars and explanations (§2). It exists so findings can be ranked/filtered
by the engine's certainty internally.
"""

from __future__ import annotations

from dataclasses import dataclass

from yieldfield.domain.shared.errors import InvalidEntityError


@dataclass(frozen=True, slots=True)
class Confidence:
    value: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 1.0:
            raise InvalidEntityError(f"Confidence must be in [0, 1], got {self.value}.")
