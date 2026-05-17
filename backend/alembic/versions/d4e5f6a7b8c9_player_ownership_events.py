"""player_ownership_events

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-17

Captures each Yahoo transaction as one ownership-change event for a
player in a league. Walking these chronologically reconstructs the
player's full ownership timeline within the league.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_ownership_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "league_id",
            sa.Integer(),
            sa.ForeignKey("leagues.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "player_id",
            sa.Integer(),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column(
            "from_team_id",
            sa.Integer(),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "to_team_id",
            sa.Integer(),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("transaction_key", sa.String(), nullable=False),
        sa.Column(
            "raw",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "league_id",
            "player_id",
            "transaction_key",
            name="uq_pownerevt_unique",
        ),
    )
    op.create_index(
        "ix_player_ownership_events_league_id",
        "player_ownership_events",
        ["league_id"],
    )
    op.create_index(
        "ix_player_ownership_events_player_id",
        "player_ownership_events",
        ["player_id"],
    )
    op.create_index(
        "ix_player_ownership_events_occurred_at",
        "player_ownership_events",
        ["occurred_at"],
    )


def downgrade() -> None:
    op.drop_table("player_ownership_events")
