"""SQLAlchemy engine, session factory, and Base declarative class.

SQLite by default. To swap to Postgres, set DATABASE_URL=postgresql://...
The engine is lazily constructed so tests can point at an in-memory DB.
"""

import os
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

_DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "app.db"
_DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{_DEFAULT_DB_PATH}")

_engine_kwargs = {"echo": False, "future": True}
if DATABASE_URL.startswith("sqlite"):
    # SQLite + threaded FastAPI needs this flag
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency — yields a scoped session, closes on teardown."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Called at app startup; idempotent."""
    from . import models  # noqa: F401 — register models on Base
    Base.metadata.create_all(bind=engine)
