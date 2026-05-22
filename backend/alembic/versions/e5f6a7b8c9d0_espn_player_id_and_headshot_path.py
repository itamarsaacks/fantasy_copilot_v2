"""espn_player_id + espn_player_id_confidence + headshot_path on players

Adds three columns to support headshots and ESPN-linked player data per
master plan §2.1. Headshots are sourced from ESPN's roster endpoint via
a one-shot backfill script (no runtime third-party dependency).

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "players",
        sa.Column("espn_player_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "players",
        sa.Column("espn_player_id_confidence", sa.String(), nullable=True),
    )
    op.add_column(
        "players",
        sa.Column("headshot_path", sa.String(), nullable=True),
    )
    # Unique on espn_player_id but only where set — partial unique index.
    op.create_index(
        "ix_players_espn_player_id",
        "players",
        ["espn_player_id"],
        unique=True,
        postgresql_where=sa.text("espn_player_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_players_espn_player_id", table_name="players")
    op.drop_column("players", "headshot_path")
    op.drop_column("players", "espn_player_id_confidence")
    op.drop_column("players", "espn_player_id")
