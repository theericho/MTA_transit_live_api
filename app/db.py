"""Database setup: SQLAlchemy engine, sessions, and schema creation.

DATABASE_URL selects the backend (README, design decision 4): SQLite by
default for zero-setup local development, PostgreSQL in production, e.g.
postgresql+psycopg://user:pass@host/db. Schema and queries stay portable.

All datetimes are stored timezone-naive in UTC.
"""
import os
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./transit.db")


class Base(DeclarativeBase):
    pass


_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def utcnow_naive() -> datetime:
    """Current UTC time, tz-naive, matching how datetimes are stored."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def init_db() -> None:
    from app.models import tables  # noqa: F401  registers the ORM models

    Base.metadata.create_all(engine)
    _add_missing_columns()


# Columns added after the table already shipped. create_all() creates missing
# tables but never alters existing ones, so a database created before v4 would
# keep the old stations table. This applies them idempotently, in both SQLite
# and Postgres, without wiping anyone's history. A real migration tool
# (Alembic) is the next step if the schema keeps evolving.
_ADDED_COLUMNS = {
    "stations": {
        "complex_id": "INTEGER REFERENCES complexes(id)",
        "daytime_routes": "VARCHAR(64)",
    },
}


def _add_missing_columns() -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if not inspector.has_table(table):
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def get_session():
    """FastAPI dependency yielding a database session."""
    with SessionLocal() as session:
        yield session
