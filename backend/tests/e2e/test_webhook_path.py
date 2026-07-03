"""Webhook ingress end to end (audit TE-1): a genuinely signed payload traverses the real
registration service, cipher, store, and worker composition roots. Requires Docker."""

from __future__ import annotations

import hashlib
import hmac
import time

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

AUTH = {"Authorization": "Bearer e2e-token"}
_WEBHOOK_SECRET = "whsec_e2e_webhook_path"  # noqa: S105 — test-only secret


def _stripe_signature(payload: bytes, secret: str) -> str:
    timestamp = int(time.time())
    signed = f"{timestamp}.{payload.decode()}".encode()
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def test_signed_webhook_round_trips_to_a_succeeded_ingest_job(client: TestClient) -> None:
    created = client.post(
        "/api/v1/connectors",
        headers=AUTH,
        json={
            "connector_type": "stripe_billing",
            "secrets": {"api_key": "sk_test_e2e", "webhook_secret": _WEBHOOK_SECRET},
        },
    )
    assert created.status_code == 201, created.text
    connector_id = created.json()["id"]

    # The REAL verification path: decrypt the stored blob, verify a genuine HMAC.
    payload = b'{"id":"evt_e2e_1","object":"event","type":"invoice.paid"}'
    accepted = client.post(
        f"/api/v1/webhooks/{connector_id}",
        content=payload,
        headers={"Stripe-Signature": _stripe_signature(payload, _WEBHOOK_SECRET)},
    )
    assert accepted.status_code == 202, accepted.text

    # The eager queue ran the real ingest composition root against stripe-mock.
    job = client.get(f"/api/v1/jobs/{accepted.json()['job_id']}", headers=AUTH).json()
    assert job["status"] == "succeeded", job
    assert job["job_type"] == "ingest_invoices"

    # A tampered payload under the same signature is rejected and enqueues nothing.
    tampered = client.post(
        f"/api/v1/webhooks/{connector_id}",
        content=b'{"id":"evt_evil","object":"event"}',
        headers={"Stripe-Signature": _stripe_signature(payload, _WEBHOOK_SECRET)},
    )
    assert tampered.status_code == 400
    assert tampered.json()["error"]["code"] == "invalid_webhook_signature"
