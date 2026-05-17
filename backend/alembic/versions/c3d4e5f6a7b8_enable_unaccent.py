"""enable unaccent extension

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-17

Diacritic-insensitive name search on the Players tab. Without this,
'jokic' wouldn't match 'Jokić'. Players-endpoint search uses
`unaccent(full_name) ILIKE unaccent(:term)`.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS unaccent")
