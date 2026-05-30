"""The connector port (§17) — the interface every billing connector implements.

A connector is the primary axis of growth: adding Metronome/Orb/Lago after Stripe
means implementing this port in `infrastructure/connectors/<name>/` and touching
nothing in reconciliation or UI. The port lives in the domain so the application
layer depends on the abstraction, not on any concrete connector (dependency rule).

Signatures are synchronous: pulls run inside Celery workers (§13), which are
synchronous, so a sync contract is the natural fit. The shared abstract base adapter
and connector utilities land in `infrastructure/connectors/base/` in Slice 2.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from yieldfield.domain.billing.invoice import Invoice
from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.shared.time_window import TimeWindow


@dataclass(frozen=True, slots=True)
class ConnectorCredentials:
    """Opaque, connector-specific secrets (e.g. an API key). Never logged (§11)."""

    secrets: Mapping[str, str]


@runtime_checkable
class ConnectorPort(Protocol):
    """Authenticate, pull usage events, pull invoices, verify inbound webhooks (§17)."""

    def authenticate(self, credentials: ConnectorCredentials) -> None:
        """Establish an authenticated session, or raise on bad credentials."""
        ...

    def pull_usage_events(self, window: TimeWindow) -> Iterable[UsageEvent]:
        """Yield the tenant's usage events occurring within `window`."""
        ...

    def pull_invoices(self, window: TimeWindow) -> Iterable[Invoice]:
        """Yield the invoices issued within `window`."""
        ...

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        """Return True iff the inbound webhook signature is valid (§11)."""
        ...
