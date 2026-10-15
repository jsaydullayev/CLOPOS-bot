"""admins added in the admin panel

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admins",
        sa.Column("user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("added_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_admins")),
    )


def downgrade() -> None:
    op.drop_table("admins")
