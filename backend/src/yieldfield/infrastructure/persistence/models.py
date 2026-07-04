"""SQLAlchemy declarative ORM rows for the OLTP store (§12).

These are infrastructure-only; the domain entities stay framework-pure (§6.1) and are
translated by `mappers.py`. Money/quantity columns are NUMERIC(38,12): exact decimal
(never float, §7), precision 38 to stay aligned with ClickHouse Decimal128(12), scale
12 to cover sub-cent usage-based pricing without rounding at the storage boundary.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime

MONEY_SCALE = 12
_MONEY = Numeric(38, MONEY_SCALE)
_TS = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


class TenantRow(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # These relationships order ONLY tenant→child inserts in the unit of work (a tenant
    # row flushes before rows referencing it). Nothing orders siblings against each other
    # — ContractRow.plan_id has no relationship — so same-session bulk adds must flush
    # between dependent siblings (see tests/e2e/test_money_path.py). Audit AR-2.
    plans: Mapped[list[PlanRow]] = relationship(back_populates="tenant")
    contracts: Mapped[list[ContractRow]] = relationship(back_populates="tenant")
    invoices: Mapped[list[InvoiceRow]] = relationship(back_populates="tenant")
    reconciliations: Mapped[list[ReconciliationRow]] = relationship(back_populates="tenant")
    findings: Mapped[list[FindingRow]] = relationship(back_populates="tenant")
    connectors: Mapped[list[ConnectorRow]] = relationship(back_populates="tenant")
    jobs: Mapped[list[JobRow]] = relationship(back_populates="tenant")


class PlanRow(Base):
    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    unit_price_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    unit_price_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    tenant: Mapped[TenantRow] = relationship(back_populates="plans")


class ContractRow(Base):
    __tablename__ = "contracts"
    # Reconciliation read path (§8): contracts are fetched per (tenant, customer).
    # Created by migration 0004; the unit parity test keeps both in sync (audit PF-4).
    __table_args__ = (Index("ix_contracts_tenant_customer", "tenant_id", "customer_id"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.id"), nullable=False, index=True
    )
    customer_id: Mapped[str] = mapped_column(Text, nullable=False)
    plan_id: Mapped[str] = mapped_column(Text, ForeignKey("plans.id"), nullable=False)
    term_start: Mapped[datetime] = mapped_column(_TS, nullable=False)
    term_end: Mapped[datetime] = mapped_column(_TS, nullable=False)
    tenant: Mapped[TenantRow] = relationship(back_populates="contracts")


class InvoiceRow(Base):
    __tablename__ = "invoices"
    # Reconciliation read path (§8): invoices are windowed per tenant by period_start.
    # Created by migration 0004; the unit parity test keeps both in sync (audit PF-4).
    __table_args__ = (Index("ix_invoices_tenant_period_start", "tenant_id", "period_start"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.id"), nullable=False, index=True
    )
    customer_id: Mapped[str] = mapped_column(Text, nullable=False)
    period_start: Mapped[datetime] = mapped_column(_TS, nullable=False)
    period_end: Mapped[datetime] = mapped_column(_TS, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    line_items: Mapped[list[InvoiceLineItemRow]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="InvoiceLineItemRow.id",
    )
    tenant: Mapped[TenantRow] = relationship(back_populates="invoices")


class InvoiceLineItemRow(Base):
    __tablename__ = "invoice_line_items"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    invoice_id: Mapped[str] = mapped_column(
        Text, ForeignKey("invoices.id"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    amount_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    amount_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    invoice: Mapped[InvoiceRow] = relationship(back_populates="line_items")


class ReconciliationRow(Base):
    __tablename__ = "reconciliations"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.id"), nullable=False, index=True
    )
    window_start: Mapped[datetime] = mapped_column(_TS, nullable=False)
    window_end: Mapped[datetime] = mapped_column(_TS, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    # Matches DEFAULT_RULE_VERSION in matching.py — keep in sync; DB defaults must be literals.
    rule_version: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="reconciliation-v1"
    )
    findings: Mapped[list[FindingRow]] = relationship(
        back_populates="reconciliation",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="FindingRow.id",
    )
    tenant: Mapped[TenantRow] = relationship(back_populates="reconciliations")


class FindingRow(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.id"), nullable=False, index=True
    )
    reconciliation_id: Mapped[str] = mapped_column(
        Text, ForeignKey("reconciliations.id"), nullable=False, index=True
    )
    customer_id: Mapped[str] = mapped_column(Text, nullable=False)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    leakage_type: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    amount_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    amount_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    lineage_rule_version: Mapped[str] = mapped_column(Text, nullable=False)
    lineage_usage_event_ids: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    lineage_invoice_line_item_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    lineage_model_run_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    reconciliation: Mapped[ReconciliationRow] = relationship(back_populates="findings")
    tenant: Mapped[TenantRow] = relationship(back_populates="findings")


class ConnectorRow(Base):
    __tablename__ = "connectors"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.id"), nullable=False, index=True
    )
    connector_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_credentials: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        _TS, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    tenant: Mapped[TenantRow] = relationship(back_populates="connectors")


class JobRow(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("(result_type IS NULL) = (result_ref IS NULL)", name="ck_jobs_result_pair"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.id"), nullable=False, index=True
    )
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(_TS, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(_TS, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    tenant: Mapped[TenantRow] = relationship(back_populates="jobs")
