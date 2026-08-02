import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

# Loads backend/.env if present. Real deployments (Render, Railway, Fly,
# Docker, etc.) will set these as real environment variables instead, which
# load_dotenv() never overrides (it only fills in variables that aren't
# already set).
load_dotenv()

# RC_DATABASE_URL (or the more common DATABASE_URL, which most Postgres
# hosts inject automatically) points at Postgres, e.g.:
#   postgresql+psycopg://user:password@host:5432/readers_club
# Falls back to a local SQLite file only if neither is set, so existing
# dev setups that haven't configured Postgres yet don't break outright.
SQLALCHEMY_DATABASE_URL = (
    os.environ.get("RC_DATABASE_URL")
    or os.environ.get("DATABASE_URL")
    or "sqlite:///./readers_club.db"
)

# Some hosts (Render, Heroku-style) still hand out "postgres://" URLs, but
# SQLAlchemy 2.x + psycopg3 need the "postgresql+psycopg://" scheme.
if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace(
        "postgres://", "postgresql+psycopg://", 1
    )
elif SQLALCHEMY_DATABASE_URL.startswith("postgresql://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace(
        "postgresql://", "postgresql+psycopg://", 1
    )

_is_sqlite = SQLALCHEMY_DATABASE_URL.startswith("sqlite")

_connect_args = {"check_same_thread": False} if _is_sqlite else {}

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,  # drop/reconnect dead connections instead of erroring
)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        """SQLite ignores FK constraints and ON DELETE CASCADE unless this is
        turned on for every connection. WAL mode also reduces 'database is
        locked' errors under concurrent reads/writes. Postgres enforces both
        of these by default, so this only runs for the SQLite fallback."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
