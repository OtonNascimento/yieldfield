"""SQLAlchemy declarative ORM rows for the OLTP store (§12).

These are infrastructure-only; the domain entities stay framework-pure (§6.1) and are
translated by `mappers.py`. Money/quantity columns are NUMERIC(38,12): exact decimal
(never float, §7), precision 38 to stay aligned with ClickHouse Decimal128(12), scale
12 to cover sub-cent usage-based pricing without rounding at the storage boundary.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, Text
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
    # Relationships exist so that SQLAlchemy's unit-of-work topological sort respects
    # FK ordering when TenantRow and its children are added to the same session without
    # being linked through the ORM object graph (e.g. integration tests, bulk inserts).
    plans: Mapped[list[PlanRow]] = relationship(back_populates="tenant")
    contracts: Mapped[list[ContractRow]] = relationship(back_populates="tenant")
    invoices: Mapped[list[InvoiceRow]] = relationship(back_populates="tenant")
    reconciliations: Mapped[list[ReconciliationRow]] = relationship(back_populates="tenant")
    findings: Mapped[list[FindingRow]] = relationship(back_populates="tenant")


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
