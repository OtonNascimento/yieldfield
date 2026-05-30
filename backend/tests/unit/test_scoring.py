"""Scoring port + ModelRun (§6.4, §12, §17).

The scoring port is the seam behind which the probabilistic engine lives (Slice 5).
ModelRun makes a scored finding reproducible: a finding references the exact run.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.scoring.confidence import Confidence
from yieldfield.domain.scoring.model_run import ModelRun
from yieldfield.domain.scoring.port import ScoreRequest, ScoreResult, ScoringPort
from yieldfield.domain.shared.errors import InvalidEntityError
from yieldfield.domain.shared.ids import ModelRunId
from yieldfield.domain.shared.money import Money


def _model_run(**overrides: object) -> ModelRun:
    defaults: dict[str, object] = {
        "id": ModelRunId("mr_1"),
        "model_name": "leakage-bayes",
        "model_version": "1.2.0",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "params": {"prior": "0.01"},
    }
    defaults.update(overrides)
    return ModelRun(**defaults)  # type: ignore[arg-type]


class TestModelRun:
    def test_valid(self) -> None:
        run = _model_run()
        assert run.model_name == "leakage-bayes"
        assert run.params["prior"] == "0.01"

    def test_requires_name_and_version(self) -> None:
        with pytest.raises(InvalidEntityError):
            _model_run(model_name="")
        with pytest.raises(InvalidEntityError):
            _model_run(model_version="")

    def test_requires_timezone_aware_created_at(self) -> None:
        with pytest.raises(InvalidEntityError):
            _model_run(created_at=datetime(2026, 1, 1))


class TestConfidence:
    def test_valid_range(self) -> None:
        assert Confidence(0.0).value == 0.0
        assert Confidence(1.0).value == 1.0

    def test_rejects_out_of_range(self) -> None:
        with pytest.raises(InvalidEntityError):
            Confidence(-0.01)
        with pytest.raises(InvalidEntityError):
            Confidence(1.01)


class TestScoringPort:
    def test_conforming_scorer_satisfies_port(self) -> None:
        class FakeScorer:
            def score(self, request: ScoreRequest) -> ScoreResult:
                return ScoreResult(confidence=Confidence(0.9), model_run=_model_run())

        scorer: ScoringPort = FakeScorer()
        assert isinstance(scorer, ScoringPort)
        result = scorer.score(
            ScoreRequest(
                leakage_type=LeakageType.UNBILLED_USAGE,
                metric="api_calls",
                amount=Money.of("10.00", "USD"),
            )
        )
        assert result.confidence.value == 0.9
        assert result.model_run.model_name == "leakage-bayes"

    def test_incomplete_scorer_does_not_satisfy_port(self) -> None:
        class NotAScorer: ...

        assert not isinstance(NotAScorer(), ScoringPort)

    def test_score_request_defaults_features_to_empty(self) -> None:
        request = ScoreRequest(
            leakage_type=LeakageType.MISRATED_LINE_ITEM,
            metric="storage",
            amount=Money.of("5.00", "USD"),
        )
        assert isinstance(request.features, Mapping)
        assert dict(request.features) == {}
