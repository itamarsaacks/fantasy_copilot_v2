"""phase 1 baseline

Revision ID: 029db6dc464b
Revises: 
Create Date: 2026-05-06 16:35:09.112155

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '029db6dc464b'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Phase 1 smoke table — verifies Alembic + Postgres connection. Removed in Phase 3."""
    op.create_table(
        "_phase1_smoke",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("note", sa.Text, nullable=False),
    )
    op.execute("INSERT INTO _phase1_smoke (note) VALUES ('phase 1 wiring verified')")


def downgrade() -> None:
    op.drop_table("_phase1_smoke")
