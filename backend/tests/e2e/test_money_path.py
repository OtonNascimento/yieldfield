"""The Slice-3 walking skeleton end to end (spec §12 E2E). Requires Docker."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

# Keep in sync with conftest.py (fixtures load automatically; constants don't import
# portably across test packages without a tests/ root package).
TENANT_ID = "tenant-e2e"
AUTH = {"Authorization": "Bearer e2e-token"}

JAN_JSON = {"start": "2026-01-01T00:00:00+00:00", "end": "2026-02-01T00:00:00+00:00"}


def test_connector_registration_and_live_ingestion_against_stripe_mock(
    client: TestClient,
) -> None:
    # Register: validate (authenticate) → encrypt → persist; secrets never echo (§11).
    created = client.post(
        "/api/v1/connectors",
        headers=AUTH,
        json={
            "connector_type": "stripe_billing",
            "secrets": {"api_key": "sk_test_e2e", "webhook_secret": "whsec_e2e"},
        },
    )
    assert created.status_code == 201, created.text
    connector_id = created.json()["id"]
    assert "sk_test_e2e" not in created.text

    listed = client.get("/api/v1/connectors", headers=AUTH)
    assert connector_id in [c["id"] for c in listed.json()["items"]]

    # Live pull from stripe-mock through the REAL worker composition root (eager Celery).
    accepted = client.post(
        "/api/v1/ingestion/invoices",
        headers=AUTH,
        json={
            "connector_id": connector_id,
            # Wide window: stripe-mock's canned invoices carry fixed historic timestamps.
            "window": {"start": "2008-01-01T00:00:00+00:00", "end": "2030-01-01T00:00:00+00:00"},
        },
    )
    assert accepted.status_code == 202, accepted.text
    job = client.get(f"/api/v1/jobs/{accepted.json()['job_id']}", headers=AUTH).json()
    assert job["status"] == "succeeded", job
    assert job["result_type"] is None and job["result_ref"] is None  # ingestion: no artifact


def test_reconciliation_money_path_audit_records_and_finding_lifecycle(
    client: TestClient, _database_url: str, _clickhouse_url: str
) -> None:
    # ── Seed deterministic billing data through the 3A stores (no API for these yet, §0) ──
    from yieldfield.domain.billing.contract import Contract
    from yieldfield.domain.billing.invoice import Invoice
    from yieldfield.domain.billing.plan import Plan
    from yieldfield.domain.billing.usage_event import UsageEvent
    from yieldfield.domain.shared.ids import (
        ContractId,
        InvoiceId,
        PlanId,
        TenantId,
        UsageEventId,
    )
    from yieldfield.domain.shared.money import Money
    from yieldfield.domain.shared.time_window import TimeWindow
    from yieldfield.infrastructure.analytics_store.clickhouse_client import (
        create_clickhouse_client,
    )
    from yieldfield.infrastructure.analytics_store.clickhouse_usage_event_store import (
        ClickHouseUsageEventStore,
    )
    from yieldfield.infrastructure.persistence.engine import create_db_engine
    from yieldfield.infrastructure.persistence.repositories import (
        SqlAlchemyContractRepository,
        SqlAlchemyInvoiceRepository,
        SqlAlchemyPlanRepository,
    )

    tenant = TenantId(TENANT_ID)
    jan = TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))
    engine = create_db_engine(_database_url)
    with Session(engine) as session:
        SqlAlchemyPlanRepository(session).add(
            tenant,
            Plan(
                id=PlanId("p_e2e"),
                tenant_id=tenant,
                name="Metered",
                metric="api_calls",
                unit_price=Money.of("0.10", "USD"),
            ),
        )
        # The row mappers declare FK columns but no relationship()s, so the unit of work
        # won't order plans before contracts on its own — flush to pin the insert order.
        session.flush()
        SqlAlchemyContractRepository(session).add(
            tenant,
            Contract(
                id=ContractId("con_e2e"),
                tenant_id=tenant,
                customer_id="cus_e2e",
                plan_id=PlanId("p_e2e"),
                term=jan,
            ),
        )
        SqlAlchemyInvoiceRepository(session).add(
            tenant,
            Invoice(
                id=InvoiceId("inv_e2e"),
                tenant_id=tenant,
                customer_id="cus_e2e",
                period=jan,
                currency="USD",
                line_items=(),  # nothing billed → 100 x $0.10 unbilled = $10.00
            ),
        )
        session.commit()
    engine.dispose()

    ClickHouseUsageEventStore(create_clickhouse_client(_clickhouse_url)).append(
        tenant,
        [
            UsageEvent(
                id=UsageEventId("u_e2e_1"),
                tenant_id=tenant,
                customer_id="cus_e2e",
                metric="api_calls",
                quantity=Decimal("100"),
                occurred_at=datetime(2026, 1, 15, tzinfo=UTC),
            )
        ],
    )

    # ── Reconcile via the API; the eager worker persists the auditable run (§3, decision C) ──
    accepted = client.post("/api/v1/reconciliations", headers=AUTH, json={"window": JAN_JSON})
    assert accepted.status_code == 202, accepted.text
    job = client.get(f"/api/v1/jobs/{accepted.json()['job_id']}", headers=AUTH).json()
    assert job["status"] == "succeeded", job
    assert job["result_type"] == "reconciliation"
    reconciliation_id = job["result_ref"]

    recon = client.get(f"/api/v1/reconciliations/{reconciliation_id}", headers=AUTH).json()
    # NUMERIC(38,12) coerces stored money to scale 12; MoneyRead preserves that scale (§7).
    assert recon["total_leakage"] == {"amount": "10.000000000000", "currency": "USD"}
    assert recon["finding_count"] == 1
    assert recon["rule_version"] == "reconciliation-v1"
    listing = client.get("/api/v1/reconciliations", headers=AUTH).json()
    assert reconciliation_id in [r["id"] for r in listing["items"]]

    # ── Finding lifecycle through the four explicit routes (decision D) ──
    findings = client.get(
        f"/api/v1/findings?reconciliation_id={reconciliation_id}", headers=AUTH
    ).json()
    assert len(findings["items"]) == 1
    finding = findings["items"][0]
    assert finding["status"] == "new"
    assert finding["amount"] == {"amount": "10.000000000000", "currency": "USD"}  # scale 12, §7
    assert finding["explanation"].strip()
    finding_id = finding["id"]

    transitions = (("review", "reviewed"), ("confirm", "confirmed"), ("recover", "recovered"))
    for action, expected in transitions:
        response = client.post(f"/api/v1/findings/{finding_id}/{action}", headers=AUTH)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == expected  # $10.00 ends RECOVERED

    illegal = client.post(f"/api/v1/findings/{finding_id}/dismiss", headers=AUTH)
    assert illegal.status_code == 409
    assert illegal.json()["error"]["code"] == "invalid_finding_transition"
