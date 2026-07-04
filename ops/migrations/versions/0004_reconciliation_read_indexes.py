"""Composite read indexes for the reconciliation path (§8, audit PF-4).

Reconciliation fetches invoices per tenant windowed by period_start, and contracts per
(tenant, customer); the bare tenant_id indexes from 0001 degrade linearly with tenant
size. Cheap while the tables are empty. Forward-only (§12) with a working downgrade.

Revision ID: 0004_reconciliation_read_indexes
Revises: 0003_jobs_attempts
Create Date: 2026-07-03
"""

from __future__ import annotations

from alembic import op

revision = "0004_reconciliation_read_indexes"
down_revision = "0003_jobs_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_invoices_tenant_period_start", "invoices", ["tenant_id", "period_start"]
    )
    op.create_index("ix_contracts_tenant_customer", "contracts", ["tenant_id", "customer_id"])


def downgrade() -> None:
    op.drop_index("ix_contracts_tenant_customer", table_name="contracts")
    op.drop_index("ix_invoices_tenant_period_start", table_name="invoices")
