"""The scoring port (§6.4, §17) — the interface the probabilistic engine satisfies.

Defined here in the domain so nothing in the API or UI depends on the concrete model.
The implementation (PyMC/NumPyro/sklearn) lives in `infrastructure/scoring_engine/`
and is swappable behind this seam (Slice 5). This module holds the contract only —
no model code (ARCHITECTURE domain/scoring/).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.scoring.confidence import Confidence
from yieldfield.domain.scoring.model_run import ModelRun
from yieldfield.domain.shared.money import Money


@dataclass(frozen=True, slots=True)
class ScoreRequest:
    """The features describing a candidate finding to be scored."""

    leakage_type: LeakageType
    metric: str
    amount: Money
    features: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScoreResult:
    """A confidence, stamped with the model run that produced it (§6.5 lineage)."""

    confidence: Confidence
    model_run: ModelRun


@runtime_checkable
class ScoringPort(Protocol):
    def score(self, request: ScoreRequest) -> ScoreResult:
        """Return a confidence for the candidate finding, tied to a ModelRun."""
        ...
