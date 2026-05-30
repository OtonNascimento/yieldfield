"""Finding lifecycle state machine (§4 CORE).

The single source of truth for which status transitions are legal:
new -> reviewed -> confirmed -> recovered, with dismiss reachable from any open
(non-terminal) state. Recovered and dismissed are terminal. Kept as pure data + pure
functions so the rules are testable in isolation and reused by the Finding entity.
"""

from __future__ import annotations

from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.shared.errors import InvalidFindingTransitionError

ALLOWED_TRANSITIONS: dict[RecoveryStatus, frozenset[RecoveryStatus]] = {
    RecoveryStatus.NEW: frozenset({RecoveryStatus.REVIEWED, RecoveryStatus.DISMISSED}),
    RecoveryStatus.REVIEWED: frozenset({RecoveryStatus.CONFIRMED, RecoveryStatus.DISMISSED}),
    RecoveryStatus.CONFIRMED: frozenset({RecoveryStatus.RECOVERED, RecoveryStatus.DISMISSED}),
    RecoveryStatus.RECOVERED: frozenset(),
    RecoveryStatus.DISMISSED: frozenset(),
}


def can_transition(current: RecoveryStatus, target: RecoveryStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def ensure_transition(current: RecoveryStatus, target: RecoveryStatus) -> None:
    if not can_transition(current, target):
        raise InvalidFindingTransitionError(f"Cannot move a finding from {current} to {target}.")


def is_terminal(status: RecoveryStatus) -> bool:
    return not ALLOWED_TRANSITIONS[status]
