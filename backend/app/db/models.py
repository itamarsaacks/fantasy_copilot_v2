"""SQLAlchemy ORM models. Real schema lands in Phase 3.

For Phase 1 we only need a `Base` declarative class so Alembic has something to autogenerate against.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
