"""Abstract base connector + shared utilities (§17).

Concrete connectors (Stripe, Metronome, …) subclass this and structurally satisfy the
domain `ConnectorPort`. Shared helpers: required-secret access that never logs the value
(§11), and a webhook timestamp tolerance constant (replay safety, §11).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from yieldfield.domain.billing.connector_port import ConnectorCredentials
from yieldfield.domain.billing.invoice import Invoice
from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.shared.time_window import TimeWindow

WEBHOOK_TOLERANCE_SECONDS = 300


class ConnectorError(Exception):
    """Base error for connector failures."""


class ConnectorAuthError(ConnectorError):
    """Raised when credentials are missing or invalid (§11). Never includes the secret."""


class BaseConnector(ABC):
    """Abstract base every billing connector extends (§17)."""

    @abstractmethod
    def authenticate(self, credentials: ConnectorCredentials) -> None: ...

    @abstractmethod
    def pull_usage_events(self, window: TimeWindow) -> Iterable[UsageEvent]: ...

    @abstractmethod
    def pull_invoices(self, window: TimeWindow) -> Iterable[Invoice]: ...

    @abstractmethod
    def verify_webhook(self, payload: bytes, signature: str) -> bool: ...

    @staticmethod
    def _require_secret(credentials: ConnectorCredentials, key: str) -> str:
        try:
            return credentials.secrets[key]
        except KeyError as exc:
            raise ConnectorAuthError(f"Missing required credential: {key!r}.") from exc
