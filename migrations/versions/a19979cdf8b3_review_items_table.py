"""review_items table

W5·A: low-confidence LLM output (extraction items, impact mappings) routed
to human review. Flat state machine pending → approved | edited | rejected;
`edited` captures corrected values. job_id has no FK by design — it points
into extraction_jobs or change_report_jobs depending on source.

Revision ID: a19979cdf8b3
Revises: 7c1874eb08d6
Create Date: 2026-09-05

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a19979cdf8b3"
down_revision: str | None = "7c1874eb08d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "source",
            sa.Enum("extraction", "impact_mapping", name="review_item_source"),
            nullable=False,
        ),
        sa.Column("item_type", sa.String(length=32), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "edited", "rejected", name="review_item_status"),
            nullable=False,
        ),
        sa.Column("corrected_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_review_items_tenant_id"), "review_items", ["tenant_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_review_items_tenant_id"), table_name="review_items")
    op.drop_table("review_items")
    # Dropping the table does not drop its enum types; leaving them would
    # break a later re-upgrade with "type already exists".
    op.execute("DROP TYPE IF EXISTS review_item_source")
    op.execute("DROP TYPE IF EXISTS review_item_status")
