"""audit_log actor column

Revision ID: 8786525292e8
Revises: a19979cdf8b3
Create Date: 2026-09-07 02:42:52.614105

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8786525292e8"
down_revision: str | None = "a19979cdf8b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable: rows written before auth landed keep no actor; API-driven
    # mutations record the token subject from W5·C on.
    op.add_column("audit_log", sa.Column("actor", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_log", "actor")
