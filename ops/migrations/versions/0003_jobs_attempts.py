"""Delivery-attempt tracking on jobs (§3, audit WK-1).

`run_as_job` counts each delivery on the RUNNING transition and fails the job at the
cap instead of letting a worker-killing payload redeliver forever (acks_late).
Forward-only (§12) with a working downgrade.

Revision ID: 0003_jobs_attempts
Revises: 0002_connectors_jobs_recon_audit
Create Date: 2026-07-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_jobs_attempts"
down_revision = "0002_connectors_jobs_recon_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("jobs", "attempts")
