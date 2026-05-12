"""nba_schedule.tipoff_at

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-12

ESPN's scoreboard returns full ISO timestamps; we were dropping the
time-of-day. Adding tipoff_at so the Team tab can show "@ DET, 7:30 PM"
instead of just the date.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "nba_schedule",
        sa.Column("tipoff_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("nba_schedule", "tipoff_at")
