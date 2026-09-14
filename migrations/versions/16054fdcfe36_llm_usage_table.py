"""llm usage table

Issue #30: per-LLM-call usage accounting — tokens, cost, and latency
persisted one row per call (matching the client's one-log-line-per-call
contract), written by the services that make the calls. job_id has no FK
by design — it points into ingestion_jobs, extraction_jobs, or
change_report_jobs depending on job_type, and is null for calls made
outside any job (the search request path).

Revision ID: 16054fdcfe36
Revises: 8786525292e8
Create Date: 2026-09-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "16054fdcfe36"
down_revision: str | None = "8786525292e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "job_type",
            sa.Enum(
                "ingestion",
                "extraction",
                "change_report",
                "search",
                name="llm_usage_job_type",
            ),
            nullable=False,
        ),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_llm_usage_tenant_id_created_at",
        "llm_usage",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_llm_usage_tenant_id_created_at", table_name="llm_usage")
    op.drop_table("llm_usage")
    # Dropping the table does not drop its enum type; leaving it would
    # break a later re-upgrade with "type already exists".
    op.execute("DROP TYPE IF EXISTS llm_usage_job_type")
