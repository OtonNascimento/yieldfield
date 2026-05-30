"""Finding lifecycle (§4): new -> reviewed -> confirmed -> recovered, dismiss from open."""

from __future__ import annotations

import pytest

from yieldfield.domain.findings.finding import Finding, FindingLineage
from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.findings.lifecycle import (
    can_transition,
    ensure_transition,
    is_terminal,
)
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.findings.severity import Severity
from yieldfield.domain.shared.errors import InvalidFindingTransitionError
from yieldfield.domain.shared.ids import FindingId, ReconciliationId, TenantId
from yieldfield.domain.shared.money import Money

S = RecoveryStatus


def _finding(status: RecoveryStatus = S.NEW) -> Finding:
    return Finding(
        id=FindingId("f_1"),
        tenant_id=TenantId("t_1"),
        reconciliation_id=ReconciliationId("r_1"),
        customer_id="cust_42",
        metric="api_calls",
        leakage_type=LeakageType.UNBILLED_USAGE,
        severity=Severity.HIGH,
        amount=Money.of("10.00", "USD"),
        status=status,
        lineage=FindingLineage(rule_version="reconciliation-v1"),
        explanation="unbilled usage",
    )


class TestTransitionTable:
    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (S.NEW, S.REVIEWED),
            (S.REVIEWED, S.CONFIRMED),
            (S.CONFIRMED, S.RECOVERED),
            (S.NEW, S.DISMISSED),
            (S.REVIEWED, S.DISMISSED),
            (S.CONFIRMED, S.DISMISSED),
        ],
    )
    def test_legal_transitions(self, current: RecoveryStatus, target: RecoveryStatus) -> None:
        assert can_transition(current, target)
        ensure_transition(current, target)  # does not raise

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (S.NEW, S.CONFIRMED),  # cannot skip review
            (S.NEW, S.RECOVERED),
            (S.CONFIRMED, S.REVIEWED),  # no going backwards
            (S.RECOVERED, S.DISMISSED),  # terminal
            (S.DISMISSED, S.NEW),  # terminal
            (S.REVIEWED, S.REVIEWED),  # no self-loop
        ],
    )
    def test_illegal_transitions(self, current: RecoveryStatus, target: RecoveryStatus) -> None:
        assert not can_transition(current, target)
        with pytest.raises(InvalidFindingTransitionError):
            ensure_transition(current, target)

    def test_terminal_states(self) -> None:
        assert is_terminal(S.RECOVERED)
        assert is_terminal(S.DISMISSED)
        assert not is_terminal(S.NEW)
        assert not is_terminal(S.CONFIRMED)


class TestFindingTransition:
    def test_transition_returns_new_finding_and_leaves_original_unchanged(self) -> None:
        finding = _finding(S.NEW)
        reviewed = finding.transition_to(S.REVIEWED)
        assert reviewed.status is S.REVIEWED
        assert finding.status is S.NEW  # immutability

    def test_illegal_transition_raises(self) -> None:
        with pytest.raises(InvalidFindingTransitionError):
            _finding(S.NEW).transition_to(S.RECOVERED)

    def test_semantic_helpers_walk_the_happy_path(self) -> None:
        finding = _finding(S.NEW)
        recovered = finding.review().confirm().recover()
        assert recovered.status is S.RECOVERED

    def test_dismiss_from_open_state(self) -> None:
        assert _finding(S.REVIEWED).dismiss().status is S.DISMISSED
