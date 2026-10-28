"""SQLAlchemy engine, session factory, and Base declarative class.

SQLite by default. To swap to Postgres, set DATABASE_URL=postgresql://...
The engine is lazily constructed so tests can point at an in-memory DB.
"""

import os
from pathlib import Path
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Load .env here so the alembic CLI and scripts see the same DATABASE_URL as the
# app. Never overrides variables already in the environment (tests set theirs first).
load_dotenv()

_DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "app.db"
_DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)



def normalize_database_url(url: str) -> str:
    """Render (and some other hosts) hand out URLs as `postgres://...`, but
    SQLAlchemy 2.x only accepts `postgresql://`. We also pin the driver to
    psycopg v3 since that's what we depend on."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+psycopg" not in url:
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


DATABASE_URL = normalize_database_url(os.environ.get("DATABASE_URL", f"sqlite:///{_DEFAULT_DB_PATH}"))

_engine_kwargs = {"echo": False, "future": True}
if DATABASE_URL.startswith("sqlite"):
    # SQLite + threaded FastAPI needs this flag
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
elif DATABASE_URL.startswith("postgresql"):
    # pool_pre_ping survives Render's connection-idle terminations
    _engine_kwargs["pool_pre_ping"] = True

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
    """Run pending migrations. Called at app startup; idempotent.

    Alembic is authoritative for schema. Tests bypass this path entirely —
    conftest.py calls Base.metadata.create_all on a throwaway DB.
    """
    from . import models  # noqa: F401 — register models on Base

    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")
