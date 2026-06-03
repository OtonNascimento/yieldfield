"""Connectors + jobs tables and reconciliation audit columns (executed_at, rule_version).

Forward-only (§12) with a working downgrade. Connector credentials are stored as an opaque
encrypted BYTEA (§11); jobs are an operational ledger (§3) whose (result_type, result_ref)
pair is null-or-both-set.

Revision ID: 0002_connectors_jobs_recon_audit
Revises: 0001_oltp_schema
Create Date: 2026-06-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_connectors_jobs_recon_audit"
down_revision = "0001_oltp_schema"
branch_labels = None
depends_on = None

_TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "connectors",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("connector_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("encrypted_credentials", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", _TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_connectors_tenant_id", "connectors", ["tenant_id"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", _TS, nullable=True),
        sa.Column("finished_at", _TS, nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result_type", sa.Text(), nullable=True),
        sa.Column("result_ref", sa.Text(), nullable=True),
        sa.Column("celery_task_id", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "(result_type IS NULL) = (result_ref IS NULL)", name="ck_jobs_result_pair"
        ),
    )
    op.create_index("ix_jobs_tenant_id", "jobs", ["tenant_id"])

    op.add_column(
        "reconciliations",
        sa.Column("executed_at", _TS, nullable=False, server_default=sa.func.now()),
    )
    op.add_column(
        "reconciliations",
        sa.Column(
            "rule_version", sa.Text(), nullable=False, server_default="reconciliation-v1"
        ),
    )


def downgrade() -> None:
    op.drop_column("reconciliations", "rule_version")
    op.drop_column("reconciliations", "executed_at")
    op.drop_index("ix_jobs_tenant_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_connectors_tenant_id", table_name="connectors")
    op.drop_table("connectors")
