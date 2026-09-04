"""change_report_jobs: third sibling of the ADR-004 job family

W4·C: one row per Change Report run. Diffs the base document against the
named amendment and asks the LLM for per-Change explanations in the
worker process. Same claim/lease columns as the other job tables.

Revision ID: 7c1874eb08d6
Revises: b31c7d2e9a40
Create Date: 2026-09-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7c1874eb08d6"
down_revision: str | None = "b31c7d2e9a40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "change_report_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("base_document_id", sa.Uuid(), nullable=False),
        sa.Column("amended_document_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("queued", "running", "completed", "failed", name="change_report_job_status"),
            nullable=False,
        ),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.String(length=1024), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["base_document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["amended_document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_change_report_jobs_tenant_id"), "change_report_jobs", ["tenant_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_change_report_jobs_tenant_id"), table_name="change_report_jobs")
    op.drop_table("change_report_jobs")
    # Dropping the table does not drop its enum type; leaving it would break
    # a later re-upgrade with "type already exists".
    op.execute("DROP TYPE IF EXISTS change_report_job_status")
