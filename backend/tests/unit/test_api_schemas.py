"""DTO shapes: money-as-string precision, tz-aware windows, no secret echo (spec §5.3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from yieldfield.api.v1.schemas.common import JobAccepted, MoneyRead, PageMeta, WindowParam
from yieldfield.api.v1.schemas.connectors import ConnectorPublic
from yieldfield.api.v1.schemas.findings import FindingRead
from yieldfield.api.v1.schemas.jobs import JobStatusRead
from yieldfield.api.v1.schemas.reconciliations import ReconciliationRead
from yieldfield.domain.billing.connector import Connector, ConnectorStatus, ConnectorType
from yieldfield.domain.findings.finding import Finding, FindingLineage
from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.findings.severity import Severity
from yieldfield.domain.reconciliation.reconciliation import Reconciliation
from yieldfield.domain.shared.ids import ConnectorId, FindingId, ReconciliationId, TenantId
from yieldfield.domain.shared.money import Money
from yieldfield.domain.shared.time_window import TimeWindow


def test_money_serializes_amount_as_decimal_string() -> None:
    read = MoneyRead.from_money(Money(Decimal("1234.5600"), "USD"))
    assert read.amount == "1234.5600"  # NUMERIC precision preserved across JSON (§7)
    assert read.currency == "USD"
    assert isinstance(read.model_dump()["amount"], str)


def test_window_param_rejects_naive_datetimes() -> None:
    with pytest.raises(ValidationError):
        WindowParam(start=datetime(2026, 1, 1), end=datetime(2026, 2, 1, tzinfo=UTC))


def test_window_param_rejects_end_before_start() -> None:
    with pytest.raises(ValidationError):
        WindowParam(start=datetime(2026, 2, 1, tzinfo=UTC), end=datetime(2026, 1, 1, tzinfo=UTC))


def test_window_param_allows_equal_start_and_end() -> None:
    # Degenerate-but-valid half-open window [t, t) — matches domain TimeWindow semantics.
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    param = WindowParam(start=moment, end=moment)
    assert param.to_window().duration == timedelta(0)


def test_window_param_round_trips_to_domain_window() -> None:
    param = WindowParam(
        start=datetime(2026, 1, 1, tzinfo=UTC), end=datetime(2026, 2, 1, tzinfo=UTC)
    )
    window = param.to_window()
    assert isinstance(window, TimeWindow)
    assert window.start == param.start and window.end == param.end


def test_connector_public_never_carries_secrets() -> None:
    connector = Connector(
        id=ConnectorId("con_1"),
        tenant_id=TenantId("t_1"),
        connector_type=ConnectorType.STRIPE_BILLING,
        status=ConnectorStatus.ACTIVE,
    )
    public = ConnectorPublic.from_connector(connector)
    assert set(public.model_dump()) == {"id", "connector_type", "status"}  # no secrets field
    # JSON mode pins the wire shape the Slice-4 client generates against: plain strings.
    dumped = public.model_dump(mode="json")
    assert dumped["connector_type"] == "stripe_billing"
    assert type(dumped["connector_type"]) is str


def test_finding_and_reconciliation_reads_expose_dollars_and_explanations() -> None:
    finding = Finding(
        id=FindingId("f_1"),
        tenant_id=TenantId("t_1"),
        reconciliation_id=ReconciliationId("r_1"),
        customer_id="cus_1",
        metric="api_calls",
        leakage_type=LeakageType.UNBILLED_USAGE,
        severity=Severity.LOW,
        amount=Money.of("10.00", "USD"),
        status=RecoveryStatus.NEW,
        lineage=FindingLineage(rule_version="reconciliation-v1"),
        explanation="100 api_calls were not billed.",
    )
    recon = Reconciliation(
        id=ReconciliationId("r_1"),
        tenant_id=TenantId("t_1"),
        window=TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC)),
        currency="USD",
        executed_at=datetime(2026, 3, 1, tzinfo=UTC),
        rule_version="reconciliation-v1",
        findings=(finding,),
    )
    fr = FindingRead.from_finding(finding)
    assert fr.amount.amount == "10.00"
    assert fr.explanation == "100 api_calls were not billed."
    assert "lineage" not in fr.model_dump()  # internal lineage stays internal (§5.3)
    dumped = fr.model_dump(mode="json")
    assert dumped["leakage_type"] == "unbilled_usage"
    assert dumped["status"] == "new"
    rr = ReconciliationRead.from_reconciliation(recon)
    assert rr.total_leakage.amount == "10.00"
    assert rr.finding_count == 1
    assert rr.rule_version == "reconciliation-v1"


def test_job_status_read_maps_optional_result_pair() -> None:
    base: dict[str, Any] = {
        "job_id": "job_1",
        "job_type": "run_reconciliation",
        "status": "succeeded",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    read = JobStatusRead(**base, result_type="reconciliation", result_ref="rec_1")
    assert read.result_ref == "rec_1"
    pending = JobStatusRead(**{**base, "status": "pending"})
    assert pending.result_type is None and pending.error is None
    assert PageMeta().next_cursor is None
    assert JobAccepted(job_id="job_1").job_id == "job_1"
