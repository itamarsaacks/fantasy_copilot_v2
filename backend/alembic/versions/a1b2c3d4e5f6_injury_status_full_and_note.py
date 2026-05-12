"""injury status_full and injury_note

Revision ID: a1b2c3d4e5f6
Revises: cf69b33713d6
Create Date: 2026-05-12

Captures Yahoo's richer injury fields:
- status_full: longer description ("Day-To-Day", "Out", "Doubtful")
- injury_note: free-text notes about cause / projected return

These ride on the existing Yahoo sync. No new provider / cron needed.
Unlocks get_injury_status tool — agent can stop hitting Tavily for
status info that Yahoo already gives us.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "cf69b33713d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("players", sa.Column("status_full", sa.String(), nullable=True))
    op.add_column("players", sa.Column("injury_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("players", "injury_note")
    op.drop_column("players", "status_full")
