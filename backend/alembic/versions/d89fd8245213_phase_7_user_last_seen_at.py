"""phase 7 user last_seen_at

Revision ID: d89fd8245213
Revises: 6b7eb218895a
Create Date: 2026-05-06

Phase 7: freshness controller. The middleware stamps users.last_seen_at on
every authenticated request; the scheduler treats anyone seen in the last
~10 min as active and runs tiered Yahoo syncs only for them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d89fd8245213"
down_revision: Union[str, Sequence[str], None] = "6b7eb218895a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_users_last_seen_at", "users", ["last_seen_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_users_last_seen_at", table_name="users")
    op.drop_column("users", "last_seen_at")
