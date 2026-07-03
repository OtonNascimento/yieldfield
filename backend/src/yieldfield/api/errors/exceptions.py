"""API-layer typed errors (spec §5.4) — concerns that exist only at the HTTP boundary.

Domain/application errors (InvalidFindingTransitionError, EntityNotFoundError) are raised by
inner layers and mapped in handlers.py; these three originate in the API itself.
"""

from __future__ import annotations


class ApiError(Exception):
    """Base class for errors raised by the API adapter itself."""


class UnauthorizedError(ApiError):
    """Missing/invalid bearer token (§11) → 401 `unauthorized`."""


class IngestionDisabledError(ApiError):
    """Live-pull endpoints are feature-flagged off (§16) → 403 `ingestion_disabled`."""


class InvalidWebhookSignatureError(ApiError):
    """Inbound webhook failed signature verification (§11) → 400 `invalid_webhook_signature`."""


class WebhookPayloadTooLargeError(ApiError):
    """Inbound webhook body exceeds the ingress cap (§11) → 413 `payload_too_large`."""
