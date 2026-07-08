"""POST /webhooks/{connector_id} (spec §6, decision F).

Routed by the stable connector_id: `find_by_id` resolves the owning tenant + type from the
opaque id (the single deliberate non-tenant-prescoped read — the id is the routing key and
the SIGNATURE is the authentication, §11). On a valid signature we enqueue an idempotent
re-pull of a recent window (§8 makes re-pulls safe); per-event-type payload parsing is
future work. The `Stripe-Signature` header is read directly while Stripe is the only
connector type; per-type header resolution arrives with a second connector (§17).

This package is a sanctioned composition root (§14) but still consumes the shared
dependency seam for testability. The re-pull job is NOT flag-gated at the route (a 403
would make the provider disable our endpoint); the worker task enforces the
`ingestion_enabled` gate and the Job records the outcome.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Header, Request, status

from yieldfield.api.errors.exceptions import (
    InvalidWebhookSignatureError,
    WebhookPayloadTooLargeError,
)
from yieldfield.api.v1.dependencies.services import (
    INGEST_INVOICES_TASK,
    ConnectorStoreDep,
    JobSubmitterDep,
    RegistrationDep,
)
from yieldfield.api.v1.schemas.common import JobAccepted
from yieldfield.application.errors import EntityNotFoundError
from yieldfield.domain.billing.connector import ConnectorStatus
from yieldfield.domain.shared.ids import ConnectorId

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Minimal Slice-3 behavior (spec §6): a verified event triggers a re-pull of this recent
# window rather than parsing the payload; the idempotent ingest paths make this safe (§8).
REPULL_LOOKBACK = timedelta(days=1)

# Ingress body cap (audit SE-2a): this endpoint is unauthenticated, so bound the bytes
# accepted BEFORE any cipher/verify work. Stripe events are a few KiB; 512 KiB is ample.
_MAX_PAYLOAD_BYTES = 512 * 1024


@router.post(
    "/{connector_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive a signed provider webhook",
    response_model=JobAccepted,
)
async def receive_webhook(
    connector_id: str,
    request: Request,
    store: ConnectorStoreDep,
    registration: RegistrationDep,
    submitter: JobSubmitterDep,
    stripe_signature: Annotated[str, Header(alias="Stripe-Signature")] = "",
) -> JobAccepted:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > _MAX_PAYLOAD_BYTES:
        raise WebhookPayloadTooLargeError(f"Webhook payload exceeds {_MAX_PAYLOAD_BYTES} bytes.")

    connector = store.find_by_id(ConnectorId(connector_id))
    if connector is None or connector.status is not ConnectorStatus.ACTIVE:
        # A non-ACTIVE connector reads exactly like a missing one: no oracle (§11, SE-5).
        raise EntityNotFoundError(f"Connector {connector_id!r} not found.")

    received = 0
    chunks: list[bytes] = []
    async for chunk in request.stream():
        received += len(chunk)
        if received > _MAX_PAYLOAD_BYTES:
            # Enforced WHILE reading (audit SE-2a): a chunked body without
            # content-length must not buffer past the cap before rejection.
            raise WebhookPayloadTooLargeError(
                f"Webhook payload exceeds {_MAX_PAYLOAD_BYTES} bytes."
            )
        chunks.append(chunk)
    payload = b"".join(chunks)
    live = registration.build_authenticated(connector.tenant_id, connector.id)
    if not live.verify_webhook(payload, stripe_signature):
        raise InvalidWebhookSignatureError("Webhook signature verification failed.")

    end = datetime.now(UTC)
    start = end - REPULL_LOOKBACK
    job_id = submitter.submit(
        connector.tenant_id,
        INGEST_INVOICES_TASK,
        start.isoformat(),
        end.isoformat(),
        connector_id,
    )
    return JobAccepted(job_id=job_id)
