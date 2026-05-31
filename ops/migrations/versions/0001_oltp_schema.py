"""Initial OLTP schema (tenants, plans, contracts, invoices, line items, reconciliations, findings).

Forward-only (§12). Money/quantity columns are NUMERIC(38,12); usage events live in
ClickHouse (spec §3), so finding lineage event IDs are a TEXT[] array, not an FK.

Revision ID: 0001_oltp_schema
Revises:
Create Date: 2026-05-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_oltp_schema"
down_revision = None
branch_labels = None
depends_on = None

_MONEY = sa.Numeric(precision=38, scale=12)
_CCY = sa.String(length=3)
_TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
    )
    op.create_table(
        "plans",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("unit_price_amount", _MONEY, nullable=False),
        sa.Column("unit_price_currency", _CCY, nullable=False),
    )
    op.create_index("ix_plans_tenant_id", "plans", ["tenant_id"])
    op.create_table(
        "contracts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("customer_id", sa.Text(), nullable=False),
        sa.Column("plan_id", sa.Text(), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("term_start", _TS, nullable=False),
        sa.Column("term_end", _TS, nullable=False),
    )
    op.create_index("ix_contracts_tenant_id", "contracts", ["tenant_id"])
    op.create_table(
        "invoices",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("customer_id", sa.Text(), nullable=False),
        sa.Column("period_start", _TS, nullable=False),
        sa.Column("period_end", _TS, nullable=False),
        sa.Column("currency", _CCY, nullable=False),
    )
    op.create_index("ix_invoices_tenant_id", "invoices", ["tenant_id"])
    op.create_table(
        "invoice_line_items",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("invoice_id", sa.Text(), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("quantity", _MONEY, nullable=False),
        sa.Column("amount_amount", _MONEY, nullable=False),
        sa.Column("amount_currency", _CCY, nullable=False),
    )
    op.create_index("ix_invoice_line_items_invoice_id", "invoice_line_items", ["invoice_id"])
    op.create_index("ix_invoice_line_items_tenant_id", "invoice_line_items", ["tenant_id"])
    op.create_table(
        "reconciliations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("window_start", _TS, nullable=False),
        sa.Column("window_end", _TS, nullable=False),
        sa.Column("currency", _CCY, nullable=False),
    )
    op.create_index("ix_reconciliations_tenant_id", "reconciliations", ["tenant_id"])
    op.create_table(
        "findings",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "reconciliation_id", sa.Text(), sa.ForeignKey("reconciliations.id"), nullable=False
        ),
        sa.Column("customer_id", sa.Text(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("leakage_type", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("amount_amount", _MONEY, nullable=False),
        sa.Column("amount_currency", _CCY, nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("lineage_rule_version", sa.Text(), nullable=False),
        sa.Column(
            "lineage_usage_event_ids",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("lineage_invoice_line_item_id", sa.Text(), nullable=True),
        sa.Column("lineage_model_run_id", sa.Text(), nullable=True),
    )
    op.create_index("ix_findings_tenant_id", "findings", ["tenant_id"])
    op.create_index("ix_findings_reconciliation_id", "findings", ["reconciliation_id"])


def downgrade() -> None:
    op.drop_table("findings")
    op.drop_table("reconciliations")
    op.drop_table("invoice_line_items")
    op.drop_table("invoices")
    op.drop_table("contracts")
    op.drop_table("plans")
    op.drop_table("tenants")
