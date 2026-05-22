"""data foundation tables — nba_game_logs columns, standings cache, backfill cursor

Adds the rest of the master plan §2 schema additions:
- nba_game_logs.did_not_play (BOOLEAN, default false)
- nba_game_logs.source (STRING, default 'yahoo')
- standings_daily_cache (lazy per-league per-date FPS cache)
- standings_cache_invalidations (sweeper queue)
- backfill_cursor (resumable backfill state)

ProjectionCache.stale already exists from a prior migration — verified
in models.py line 516. No change needed there.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # nba_game_logs additions
    op.add_column(
        "nba_game_logs",
        sa.Column(
            "did_not_play",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "nba_game_logs",
        sa.Column(
            "source",
            sa.String(),
            nullable=False,
            server_default=sa.text("'yahoo'"),
        ),
    )

    # standings_daily_cache
    op.create_table(
        "standings_daily_cache",
        sa.Column("league_id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("on_date", sa.Date(), nullable=False),
        sa.Column("fps_total", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column(
            "computed_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["league_id"], ["leagues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("league_id", "team_id", "on_date"),
    )
    op.create_index(
        "ix_standings_daily_cache_league_date",
        "standings_daily_cache",
        ["league_id", "on_date"],
    )

    # standings_cache_invalidations (sweeper queue)
    op.create_table(
        "standings_cache_invalidations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("league_id", sa.Integer(), nullable=True),
        sa.Column("on_date", sa.Date(), nullable=False),
        sa.Column(
            "enqueued_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["league_id"], ["leagues.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_invalidations_league",
        "standings_cache_invalidations",
        ["league_id"],
    )
    op.create_index(
        "ix_invalidations_date",
        "standings_cache_invalidations",
        ["on_date"],
    )

    # backfill_cursor
    op.create_table(
        "backfill_cursor",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_name", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column(
            "last_completed_at", postgresql.TIMESTAMP(timezone=True), nullable=True
        ),
        sa.Column("last_completed_date", sa.Date(), nullable=True),
        sa.Column(
            "state",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_name", "scope", name="uq_backfill_cursor_job_scope"),
    )


def downgrade() -> None:
    op.drop_table("backfill_cursor")
    op.drop_index("ix_invalidations_date", table_name="standings_cache_invalidations")
    op.drop_index("ix_invalidations_league", table_name="standings_cache_invalidations")
    op.drop_table("standings_cache_invalidations")
    op.drop_index(
        "ix_standings_daily_cache_league_date", table_name="standings_daily_cache"
    )
    op.drop_table("standings_daily_cache")
    op.drop_column("nba_game_logs", "source")
    op.drop_column("nba_game_logs", "did_not_play")
