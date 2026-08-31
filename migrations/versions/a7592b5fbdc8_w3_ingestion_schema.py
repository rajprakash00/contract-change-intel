"""document_texts, document_chunks, ingestion_jobs; pgvector + lease columns

W3 ingestion schema: parsed text (citation coordinate system), chunks
(vector + full-text halves of hybrid search, ADR-006), and the ingestion
job table. Adds the ADR-004 lease-at-claim retry columns to both job
tables.

Revision ID: a7592b5fbdc8
Revises: 922e1a6f0c05
Create Date: 2026-08-31

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "a7592b5fbdc8"
down_revision: str | None = "922e1a6f0c05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "document_texts",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page_map", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
        sa.PrimaryKeyConstraint("document_id"),
    )
    op.create_index(op.f("ix_document_texts_tenant_id"), "document_texts", ["tenant_id"])

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', text)", persisted=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_document_chunks_tenant_id"), "document_chunks", ["tenant_id"])
    op.create_index(
        "ix_document_chunks_tsv_gin", "document_chunks", ["tsv"], postgresql_using="gin"
    )
    # HNSW parameters stay at library defaults until evals justify tuning (ADR-006).
    op.create_index(
        "ix_document_chunks_embedding_hnsw",
        "document_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("queued", "running", "completed", "failed", name="ingestion_job_status"),
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
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ingestion_jobs_tenant_id"), "ingestion_jobs", ["tenant_id"])

    # Lease-at-claim retry (ADR-004 amendment) for the existing extraction table.
    op.add_column(
        "extraction_jobs",
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("extraction_jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("extraction_jobs", "lease_expires_at")
    op.drop_column("extraction_jobs", "attempts")
    op.drop_index(op.f("ix_ingestion_jobs_tenant_id"), table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
    # Dropping the table does not drop its enum type; leaving it would break
    # a later re-upgrade with "type already exists".
    op.execute("DROP TYPE IF EXISTS ingestion_job_status")
    op.drop_index("ix_document_chunks_embedding_hnsw", table_name="document_chunks")
    op.drop_index("ix_document_chunks_tsv_gin", table_name="document_chunks")
    op.drop_index(op.f("ix_document_chunks_tenant_id"), table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index(op.f("ix_document_texts_tenant_id"), table_name="document_texts")
    op.drop_table("document_texts")
