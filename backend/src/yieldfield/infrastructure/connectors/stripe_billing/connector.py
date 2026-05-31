"""Stripe Billing connector — first concrete ConnectorPort implementation (§4 CORE, §17).

Per-tenant: `tenant_id` stamps every pulled entity. Uses the official `stripe` SDK's
v15 typed client (`StripeClient.v1`); the API key is set once at client construction.
Invoices are the primary, well-supported pull (the reconciliation source). Usage is read
from Billing **meter event summaries** — Stripe's current usage surface (the older
usage-records API was removed in stripe-python 15). The Stripe interaction lives at the
impure edge and is intentionally loosely typed (`_v1()` returns Any) so we are not coupled
to the evolving Stripe typed-params surface; correctness lives in the pure, typed,
unit-tested mappers. The read source is isolated behind those mappers, so it can evolve
(e.g. push-webhook ingestion in a later slice) without touching reconciliation (§17).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import stripe

from yieldfield.domain.billing.connector_port import ConnectorCredentials
from yieldfield.domain.billing.invoice import Invoice
from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.shared.ids import TenantId
from yieldfield.domain.shared.time_window import TimeWindow
from yieldfield.infrastructure.connectors.base.connector import (
    WEBHOOK_TOLERANCE_SECONDS,
    BaseConnector,
    ConnectorAuthError,
)
from yieldfield.infrastructure.connectors.stripe_billing.mapping import (
    invoice_from_stripe,
    usage_event_from_stripe,
)

_API_KEY = "api_key"
_WEBHOOK_SECRET = "webhook_secret"  # noqa: S105 - credential KEY name, not a secret value
_PAGE_LIMIT = 100


class StripeBillingConnector(BaseConnector):
    """Pulls invoices + usage and verifies webhooks for one tenant's Stripe account."""

    def __init__(self, tenant_id: TenantId, *, base_url: str | None = None) -> None:
        self._tenant_id = tenant_id
        self._base_url = base_url
        self._client: stripe.StripeClient | None = None
        self._webhook_secret: str | None = None

    def authenticate(self, credentials: ConnectorCredentials) -> None:
        api_key = self._require_secret(credentials, _API_KEY)
        self._webhook_secret = credentials.secrets.get(_WEBHOOK_SECRET)
        if self._base_url is not None:
            self._client = stripe.StripeClient(api_key, base_addresses={"api": self._base_url})
        else:
            self._client = stripe.StripeClient(api_key)

    def _v1(self) -> Any:
        """The v15 client's v1 service namespace. Returns Any deliberately (impure edge)."""
        if self._client is None:
            raise ConnectorAuthError("Not authenticated; call authenticate() first.")
        return self._client.v1

    def pull_invoices(self, window: TimeWindow) -> Iterable[Invoice]:
        v1 = self._v1()
        invoices = v1.invoices.list(
            params={
                "created": {
                    "gte": int(window.start.timestamp()),
                    "lt": int(window.end.timestamp()),
                },
                "limit": _PAGE_LIMIT,
                "expand": ["data.lines"],
            }
        )
        for inv in invoices.auto_paging_iter():
            raw: dict[str, Any] = {
                "id": inv.id,
                "customer": inv.customer,
                "period_start": inv.period_start,
                "period_end": inv.period_end,
                "currency": inv.currency,
                "lines": [
                    {
                        "id": line.id,
                        "metric": self._line_metric(line),
                        "quantity": line.quantity or 0,
                        "amount": line.amount,
                        "currency": line.currency,
                    }
                    for line in inv.lines.data
                ],
            }
            yield invoice_from_stripe(self._tenant_id, raw)

    def pull_usage_events(self, window: TimeWindow) -> Iterable[UsageEvent]:
        v1 = self._v1()
        start_time = int(window.start.timestamp())
        end_time = int(window.end.timestamp())
        customers = {
            sub.customer
            for sub in v1.subscriptions.list(
                params={"status": "all", "limit": _PAGE_LIMIT}
            ).auto_paging_iter()
        }
        for meter in v1.billing.meters.list(params={"limit": _PAGE_LIMIT}).auto_paging_iter():
            metric = self._meter_metric(meter)
            for customer in customers:
                summaries = v1.billing.meters.event_summaries.list(
                    meter.id,
                    params={
                        "customer": customer,
                        "start_time": start_time,
                        "end_time": end_time,
                    },
                )
                for summary in summaries.auto_paging_iter():
                    raw: dict[str, Any] = {
                        "id": f"{meter.id}:{customer}:{summary.start_time}",
                        "customer_id": customer,
                        "metric": metric,
                        "quantity": summary.aggregated_value,
                        "occurred_at": summary.start_time,
                    }
                    yield usage_event_from_stripe(self._tenant_id, raw)

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        if not self._webhook_secret:
            raise ConnectorAuthError("Webhook secret not configured; call authenticate() first.")
        try:
            stripe.Webhook.construct_event(  # type: ignore[no-untyped-call]  # SDK method is untyped
                payload, signature, self._webhook_secret, tolerance=WEBHOOK_TOLERANCE_SECONDS
            )
        except stripe.SignatureVerificationError:
            return False
        return True

    @staticmethod
    def _line_metric(line: Any) -> str:
        price = getattr(line, "price", None)
        nickname = getattr(price, "nickname", None) if price is not None else None
        return str(getattr(line, "description", None) or nickname or "unknown")

    @staticmethod
    def _meter_metric(meter: Any) -> str:
        name = getattr(meter, "event_name", None) or getattr(meter, "display_name", None)
        return str(name or "unknown")
