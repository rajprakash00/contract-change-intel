"""documents.amends_document_id: nullable self-FK for amendment chains

W4·B amendment model: a Document may optionally name the Document it
amends. No separate versions table; Change Reports will diff exactly the
two named documents. RESTRICT (not CASCADE/SET NULL) so deleting a
document that still has amendments fails loudly instead of silently
orphaning or erasing the chain.

Revision ID: b31c7d2e9a40
Revises: a7592b5fbdc8
Create Date: 2026-09-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b31c7d2e9a40"
down_revision: str | None = "a7592b5fbdc8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("amends_document_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_documents_amends_document_id_documents",
        "documents",
        "documents",
        ["amends_document_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    # Children lookup gates DELETE; amendment lists can walk a chain.
    op.create_index(
        "ix_documents_amends_document_id",
        "documents",
        ["amends_document_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_documents_amends_document_id", table_name="documents")
    op.drop_constraint("fk_documents_amends_document_id_documents", "documents", type_="foreignkey")
    op.drop_column("documents", "amends_document_id")
