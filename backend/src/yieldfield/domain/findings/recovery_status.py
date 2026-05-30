"""RecoveryStatus (§8) — the finding lifecycle state (§4 CORE).

new -> reviewed -> confirmed -> recovered, with dismissed reachable from the open
states. The allowed transitions are enforced in `lifecycle.py`.
"""

from __future__ import annotations

from enum import StrEnum


class RecoveryStatus(StrEnum):
    NEW = "new"
    REVIEWED = "reviewed"
    CONFIRMED = "confirmed"
    RECOVERED = "recovered"
    DISMISSED = "dismissed"
